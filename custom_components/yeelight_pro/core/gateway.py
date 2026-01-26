from __future__ import annotations

import asyncio
import logging
import random
import json
from typing import TYPE_CHECKING, Callable, Dict, Set, Union, Optional, Any

from .const import PID_WIFI_PANEL, DOMAIN
from .device import XDevice, GatewayDevice, WifiPanelDevice
from .converters.base import Converter

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
MSG_SPLIT = b'\r\n'

# Reconnect backoff settings
MIN_RECONNECT_DELAY = 1.0
MAX_RECONNECT_DELAY = 60.0
RECONNECT_BACKOFF_FACTOR = 2.0

# Error thresholds
MAX_JSON_ERRORS = 5  # Reconnect after N consecutive JSON decode errors
KEEPALIVE_INTERVAL = 30  # Seconds between keepalive pings


class ProGateway:
    """Yeelight Pro Gateway TCP client."""
    
    host: str
    port: int = 65443
    device: Optional[XDevice] = None

    reader: Optional[asyncio.StreamReader] = None
    writer: Optional[asyncio.StreamWriter] = None
    main_task: Optional[asyncio.Task] = None
    _keepalive_task: Optional[asyncio.Task] = None
    _stopping: bool = False

    def __init__(self, host: str, **options: Any) -> None:
        self.host = host
        self.pid: int = options.get('pid', 1)
        self.hass: Optional[HomeAssistant] = options.get('hass')
        self.timeout: float = options.get('timeout', 5)
        self.keepalive: float = options.get('keepalive', KEEPALIVE_INTERVAL)
        self.entry_id: Optional[str] = options.get('entry_id')
        self.devices: Dict[Union[str, int], XDevice] = {}
        self.setups: Dict[str, Callable] = {}
        self.log = options.get('logger', _LOGGER)
        self._msgs: Dict[Union[int, str], asyncio.Future] = {}
        self._reconnect_delay: float = MIN_RECONNECT_DELAY
        self._stopping: bool = False
        self._json_error_count: int = 0
        self._last_topology_devices: Set[Union[str, int]] = set()
        self._was_connected: bool = False
        self._reconnect_count: int = 0

        self.log.debug('[%s] Gateway initialized, pid=%s', self.host, self.pid)

    def add_setup(self, domain: str, handler: Callable) -> None:
        """Add hass entity setup function."""
        if '.' in domain:
            _, domain = domain.rsplit('.', 1)
        self.setups[domain] = handler
        self.log.debug('[%s] Setup handler added: %s', self.host, domain)

    async def setup_entity(self, domain: str, device: XDevice, conv: Converter) -> None:
        """Setup a single entity for a device."""
        handler = self.setups.get(domain)
        if handler:
            handler(device, conv)
        else:
            self.log.warning('[%s] Setup handler not ready: domain=%s, device=%s', 
                           self.host, domain, device.id)

    async def add_device(self, device: XDevice) -> None:
        """Add a device to this gateway."""
        if not device.hass:
            device.hass = self.hass
        if device.id not in self.devices:
            self.devices[device.id] = device
            self.log.info('[%s] Device added: id=%s, name=%s, type=%s', 
                         self.host, device.id, device.name, device.type)
        if self not in device.gateways:
            device.gateways.append(self)

        # Don't setup device from second gateway
        if len(device.gateways) > 1:
            return
        await device.setup_entities()

    async def start(self) -> None:
        """Start the gateway connection."""
        self._stopping = False
        self._reconnect_delay = MIN_RECONNECT_DELAY
        self._json_error_count = 0
        self._msgs['ready'] = asyncio.get_running_loop().create_future()
        self.main_task = asyncio.create_task(self.run_forever())
        self.log.info('[%s] Gateway starting', self.host)
        await self.ready()

    async def ready(self) -> bool:
        """Wait for gateway to be ready and request topology."""
        if not self.writer:
            if not (fut := self._msgs.get('ready')):
                return False
            try:
                await asyncio.wait_for(fut, self.timeout)
            except asyncio.TimeoutError:
                self.log.warning('[%s] Gateway ready timeout', self.host)
                return False

        await self.topology()
        return True

    async def stop(self, *args: Any) -> None:
        """Stop the gateway connection and cleanup."""
        self.log.info('[%s] Gateway stopping', self.host)
        self._stopping = True
        
        # Cancel keepalive task
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
        self._keepalive_task = None
        
        # Cancel all pending futures to avoid leaks
        for cid, fut in list(self._msgs.items()):
            if not fut.done():
                fut.cancel()
        self._msgs.clear()
        
        # Cancel main task
        if self.main_task and not self.main_task.cancelled():
            self.main_task.cancel()
            try:
                await self.main_task
            except asyncio.CancelledError:
                pass
        self.main_task = None
        
        # Close connection
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            self.writer = None
        self.reader = None
        
        # Remove gateway from devices
        for device in list(self.devices.values()):
            if self in device.gateways:
                device.gateways.remove(self)
        
        self.log.info('[%s] Gateway stopped', self.host)

    async def run_forever(self) -> None:
        """Main connection loop with exponential backoff."""
        while not self._stopping:
            try:
                if not await self.connect():
                    delay = self._reconnect_delay
                    self.log.debug('[%s] Reconnect in %.1f seconds', self.host, delay)
                    await asyncio.sleep(delay)
                    # Exponential backoff
                    self._reconnect_delay = min(
                        self._reconnect_delay * RECONNECT_BACKOFF_FACTOR,
                        MAX_RECONNECT_DELAY
                    )
                    continue
                
                # Reset backoff and error count on successful connection
                self._reconnect_delay = MIN_RECONNECT_DELAY
                self._json_error_count = 0
                
                # Start keepalive task
                self._keepalive_task = asyncio.create_task(self._keepalive_loop())
                
                # Read messages in loop until disconnect
                await self._read_loop()
                
                # Cancel keepalive on disconnect
                if self._keepalive_task and not self._keepalive_task.done():
                    self._keepalive_task.cancel()
                    try:
                        await self._keepalive_task
                    except asyncio.CancelledError:
                        pass
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.log.error('[%s] Main loop error: %s', self.host, exc, exc_info=exc)
        self.log.debug('[%s] Main loop stopped', self.host)

    async def connect(self) -> bool:
        """Establish connection to gateway."""
        try:
            res = await asyncio.wait_for(self._connect(), self.timeout)
        except asyncio.TimeoutError:
            self.log.error('[%s] Connection timeout', self.host)
            res = False
        except (ConnectionError, OSError) as exc:
            self.log.error('[%s] Connection error: %s', self.host, exc)
            res = False
        except Exception as exc:
            self.log.error('[%s] Unexpected connection error: %s', self.host, exc, exc_info=exc)
            res = False
        return res

    async def _connect(self) -> bool:
        """Internal connect implementation."""
        if not self.writer:
            self.log.debug('[%s] Connecting to port %d', self.host, self.port)
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            if not self.writer:
                return False
            self.log.info('[%s] Connected successfully', self.host)
            if fut := self._msgs.get('ready'):
                fut.set_result(True)
                del self._msgs['ready']
            self._update_connection_state(True)
            if self._was_connected:
                self._reconnect_count += 1
                self._send_reconnect_notification()
            self._was_connected = True
        return True

    async def check_available(self) -> Optional[Exception]:
        """Check if gateway is reachable."""
        try:
            await asyncio.wait_for(self._connect(), self.timeout)
        except Exception as exc:
            self.log.error('[%s] Availability check failed', self.host)
            return exc
        return None
    
    async def _keepalive_loop(self) -> None:
        """Send periodic keepalive pings to detect dead connections."""
        while not self._stopping and self.writer:
            try:
                await asyncio.sleep(self.keepalive)
                if self._stopping or not self.writer:
                    break
                # Send a lightweight topology request as keepalive
                result = await self.send('gateway_get.node', params={'id': 0}, wait_result=True)
                if result is None:
                    self.log.warning('[%s] Keepalive failed, connection may be dead', self.host)
                    await self._close_connection()
                    break
                self.log.debug('[%s] Keepalive OK', self.host)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.log.debug('[%s] Keepalive error: %s', self.host, exc)
                break

    async def _read_loop(self) -> None:
        """Read messages continuously until disconnect."""
        buffer = b""
        while not self._stopping:
            try:
                chunk = await self.reader.readline()
                if not chunk:
                    self.log.warning('[%s] Connection closed by gateway', self.host)
                    break
                buffer += chunk
                if buffer.endswith(MSG_SPLIT):
                    msg = buffer[:-len(MSG_SPLIT)]
                    buffer = b""
                    if msg:
                        await self.on_message(msg)
            except asyncio.CancelledError:
                raise
            except (ConnectionError, BrokenPipeError, OSError) as exc:
                self.log.error('[%s] Read error: %s', self.host, exc)
                break
            except Exception as exc:
                self.log.error('[%s] Unexpected read error: %s', self.host, exc, exc_info=exc)
                break
        
        await self._close_connection()
    
    async def _close_connection(self) -> None:
        """Close the current connection."""
        if self.writer:
            self.log.debug('[%s] Closing connection', self.host)
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            self.writer = None
            self._update_connection_state(False)
        self.reader = None

    async def on_message(self, msg: bytes) -> None:
        """Handle incoming message from gateway."""
        try:
            dat = json.loads(msg.decode()) or {}
            # Reset error count on successful parse
            self._json_error_count = 0
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json_error_count += 1
            self.log.error('[%s] JSON decode error (%d/%d): %s; raw=%r', 
                          self.host, self._json_error_count, MAX_JSON_ERRORS, exc, msg[:200])
            if self._json_error_count >= MAX_JSON_ERRORS:
                self.log.error('[%s] Too many JSON errors, forcing reconnect', self.host)
                await self._close_connection()
            return

        cmd = dat.get("method")
        cid = cmd if cmd in ("gateway_post.topology", "device_post.topology") else dat.get("id")
        nodes = dat.get("nodes") or []

        if ack := self._msgs.get(cid):
            ack.set_result(dat)
        else:
            self.log.debug('[%s] Message: method=%s, nodes=%d', self.host, cmd, len(nodes))

        is_topology = cmd in ("gateway_post.topology", "device_post.topology")

        if is_topology and not self.device:
            if self.pid == PID_WIFI_PANEL and nodes:
                self.device = WifiPanelDevice(nodes[0])
            else:
                self.device = GatewayDevice(self)
            await self.add_device(self.device)

        if not nodes and "params" in dat:
            nodes = [dat["params"]]

        # Track devices in topology for stale device detection
        if is_topology:
            current_topology_devices: Set[Union[str, int]] = set()
            for node in nodes:
                if nid := node.get("id"):
                    current_topology_devices.add(nid)
            
            # Detect removed devices (P1.5)
            if self._last_topology_devices:
                removed = self._last_topology_devices - current_topology_devices
                for removed_id in removed:
                    if removed_id in self.devices and removed_id != self.device.id:
                        self.log.warning('[%s] Device disappeared from topology: %s', 
                                        self.host, removed_id)
                        # Mark device as unavailable (don't remove to preserve entity_id)
                        device = self.devices[removed_id]
                        device.prop['o'] = False  # Mark offline
                        device.update({'available': False})
            
            self._last_topology_devices = current_topology_devices

        for node in nodes:
            nid = node.get("id")
            if not nid:
                continue
            if is_topology:
                await XDevice.from_node(self, node)

            dvc = self.devices.get(nid)
            if not dvc:
                self.log.debug('[%s] Device not found for node: %s', self.host, nid)
                continue

            if cmd in ("gateway_post.prop", "device_post.prop"):
                await dvc.prop_changed(node)
            elif cmd in ("gateway_post.event", "device_post.event"):
                await dvc.event_fired(node)

    async def send(self, method: str, wait_result: bool = True, **kwargs: Any) -> Optional[Dict]:
        """Send a command to the gateway."""
        if not self.writer:
            if not await self.connect():
                self.log.warning('[%s] Cannot send %s: not connected', self.host, method)
                return None
        
        if method in ("gateway_get.topology", "device_get.topology"):
            cid: Union[str, int] = method.replace("_get.", "_post.")
        else:
            cid = random.randint(1_000_000_000, 2_147_483_647)
        
        fut: Optional[asyncio.Future] = None
        if wait_result:
            fut = asyncio.get_running_loop().create_future()
            self._msgs[cid] = fut

        dat = {
            'id': cid,
            'method': method,
            **kwargs,
        }
        self.log.debug('[%s] Send: %s', self.host, method)
        
        try:
            self.writer.write(json.dumps(dat).encode() + MSG_SPLIT)
            await self.writer.drain()
        except Exception as exc:
            self.log.error('[%s] Send error for %s: %s', self.host, method, exc)
            if cid in self._msgs:
                del self._msgs[cid]
            await self._close_connection()
            return None

        if not fut:
            return None
        
        try:
            await asyncio.wait_for(fut, self.timeout)
        except asyncio.TimeoutError:
            self.log.debug('[%s] Timeout waiting for %s', self.host, method)
            return None
        except asyncio.CancelledError:
            return None
        finally:
            self._msgs.pop(cid, None)
        
        return fut.result()

    async def topology(self, wait_result: bool = False) -> Optional[Dict]:
        """Request topology from gateway."""
        cmd = 'device_get.topology' if self.pid == PID_WIFI_PANEL else 'gateway_get.topology'
        return await self.send(cmd, wait_result=wait_result)

    async def get_node(self, nid: int = 0, wait_result: bool = True) -> Optional[Dict]:
        """Get node information."""
        cmd = 'device_get.node' if self.pid == PID_WIFI_PANEL else 'gateway_get.node'
        return await self.send(cmd, params={'id': nid}, wait_result=wait_result)

    async def get_room(self, rid: int = 0, wait_result: bool = True) -> Optional[Dict]:
        """Get room information."""
        return await self.send('gateway_get.room', params={'id': rid}, wait_result=wait_result)

    async def get_scene(self, rid: int = 0, wait_result: bool = True) -> Optional[list]:
        """Get scenes list."""
        res = await self.send('gateway_get.scene', params={'id': rid}, wait_result=wait_result)
        if res:
            return res.get('scenes', [])
        return None
    
    @property
    def is_connected(self) -> bool:
        """Return True if gateway is connected."""
        return self.writer is not None and not self._stopping
    
    @property
    def device_count(self) -> int:
        """Return number of devices."""
        return len(self.devices)

    def _update_connection_state(self, connected: bool) -> None:
        """Update gateway device connection state."""
        if self.device:
            self.device.update({'connection': connected, 'available': connected})

    def _send_reconnect_notification(self) -> None:
        """Send persistent notification on reconnect."""
        if not self.hass:
            return
        try:
            from homeassistant.components import persistent_notification
            persistent_notification.async_create(
                self.hass,
                f"Gateway {self.host} reconnected (attempt #{self._reconnect_count})",
                title="Yeelight Pro Reconnected",
                notification_id=f"{DOMAIN}-reconnect-{self.host}",
            )
        except Exception as exc:
            self.log.debug('[%s] Failed to send reconnect notification: %s', self.host, exc)
