import asyncio
import logging
import random
import json
from typing import Callable, Dict, Union, Optional

from .const import PID_WIFI_PANEL
from .device import XDevice, GatewayDevice, WifiPanelDevice
from .converters.base import Converter

_LOGGER = logging.getLogger(__name__)
MSG_SPLIT = b'\r\n'


class ProGateway:
    host: str = None
    port: int = 65443
    device: "XDevice" = None

    reader: Optional[asyncio.StreamReader] = None
    writer: Optional[asyncio.StreamWriter] = None
    main_task: Optional[asyncio.Task] = None

    def __init__(self, host: str, **options):
        self.host = host
        self.pid = options.get('pid', 1)
        self.hass = options.get('hass')
        self.timeout = options.get('timeout', 5)
        self.keepalive = options.get('keepalive', 60)
        self.entry_id = options.get('entry_id')
        self.devices: Dict[str, "XDevice"] = {}
        self.setups: Dict[str, Callable] = {}
        self.log = options.get('logger', _LOGGER)
        self._msgs: Dict[Union[int, str], asyncio.Future] = {}

        self.log.debug('Gateway: %s, pid: %s', host, self.pid)

    def add_setup(self, domain: str, handler):
        """Add hass entity setup function."""
        if '.' in domain:
            _, domain = domain.rsplit('.', 1)
        self.setups[domain] = handler
        self.log.debug('Setup %s added for %s', domain, self.host)

    async def setup_entity(self, domain: str, device: "XDevice", conv: "Converter"):
        handler = self.setups.get(domain)
        if handler:
            handler(device, conv)
        else:
            self.log.warning('Setup %s not ready for %s', domain, [device, conv])

    async def add_device(self, device: "XDevice"):
        if not device.hass:
            device.hass = self.hass
        if device.id not in self.devices:
            self.devices[device.id] = device
        if self not in device.gateways:
            device.gateways.append(self)

        self.log.debug('Setup device: %s', [device.unique_id, device.name, device])

        # don't setup device from second gateway
        if len(device.gateways) > 1:
            return
        await device.setup_entities()

    async def start(self):
        self._msgs['ready'] = asyncio.get_event_loop().create_future()
        self.main_task = asyncio.create_task(self.run_forever())
        await self.ready()

    async def ready(self):
        if not self.writer:
            if not (fut := self._msgs.get('ready')):
                return None
            try:
                await asyncio.wait_for(fut, self.timeout)
            except asyncio.TimeoutError:
                return None

        await self.topology()

    async def stop(self, *args):
        if self.main_task and not self.main_task.cancelled():
            self.main_task.cancel()
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            self.writer = None 
        for device in list(self.devices.values()):
            if self in device.gateways:
                device.gateways.remove(self)

    async def run_forever(self):
        """Main thread loop."""
        while True:
            try:
                if not await self.connect():
                    await asyncio.sleep(30)
                    continue
                await self.readline()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.log.error('Main loop error: %s', [type(exc), exc], exc_info=exc)
        self.log.debug('Stop main loop')

    async def connect(self):
        try:
            res = await asyncio.wait_for(self._connect(), self.timeout)
        except (ConnectionError, Exception) as exc:
            res = False
            self.log.error('Gateway connect error: %s', [self.host, type(exc), exc])
        return res

    async def _connect(self):
        if not self.writer:
            self.log.debug('Connect gateway: %s', self.host)
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            if not self.writer:
                return False
            if fut := self._msgs.get('ready'):
                fut.set_result(True)
                del self._msgs['ready']
        return True

    async def check_available(self):
        try:
            await asyncio.wait_for(self._connect(), self.timeout)
        except Exception as exc:
            self.log.error('Gateway connect error')
            return exc
        return None

    async def readline(self):
        buffer = b""
        while True:
            try:
                chunk = await self.reader.readline()
                if not chunk:
                    # connection closed by peer
                    return b""
                buffer += chunk
                if buffer.endswith(MSG_SPLIT):  # b"\r\n"
                    msg = buffer[:-len(MSG_SPLIT)]
                    await self.on_message(msg)
                    return msg
            except (ConnectionError, BrokenPipeError, Exception) as exc:
                # hard disconnect: close writer and return so run_forever() can reconnect
                try:
                    if self.writer:
                        self.writer.close()
                        await self.writer.wait_closed()
                except Exception:
                    pass
                self.writer = None
                self.log.error("Readline error: %s", [type(exc), exc])
                await asyncio.sleep(max(0.1, self.timeout - 0.1))
                return b""

    async def on_message(self, msg):
        try:
            dat = json.loads(msg.decode()) or {}
        except Exception as exc:
            self.log.error("JSON decode error: %s; raw=%r", exc, msg[:200])
            return

        cmd = dat.get("method")
        # consider both gateway and device topology posts
        cid = cmd if cmd in ("gateway_post.topology", "device_post.topology") else dat.get("id")
        nodes = dat.get("nodes") or []

        if ack := self._msgs.get(cid):
            ack.set_result(dat)
        else:
            self.log.debug("Gateway message: %s", [cid, dat])

        is_topology = cmd in ("gateway_post.topology", "device_post.topology")

        if is_topology and not self.device:
            if self.pid == PID_WIFI_PANEL and nodes:
                self.device = WifiPanelDevice(nodes[0])   # pass the first node
            else:
                self.device = GatewayDevice(self)
            await self.add_device(self.device)

        if not nodes and "params" in dat:
            nodes = [dat["params"]]

        for node in nodes:
            nid = node.get("id")
            if not nid:
                continue
            if is_topology:
                await XDevice.from_node(self, node)
            # (the old check `if cmd == 'gateway_post.topology' and not self.device` becomes redundant)

            dvc = self.devices.get(nid)
            if not dvc:
                self.log.warning("Device not found: %s", node)
                continue

            if cmd in ("gateway_post.prop", "device_post.prop"):
                await dvc.prop_changed(node)
            elif cmd in ("gateway_post.event", "device_post.event"):
                await dvc.event_fired(node)

    async def send(self, method, wait_result=True, **kwargs):
        if not self.writer:
            await self.connect()
        if method in ("gateway_get.topology", "device_get.topology"):
            cid = method.replace("_get.", "_post.")
        else:
            cid = random.randint(1_000_000_000, 2_147_483_647)
        fut = None
        if wait_result:
            fut = asyncio.get_event_loop().create_future()
            self._msgs[cid] = fut

        dat = {
            'id': cid,
            'method': method,
            **kwargs,
        }
        self.log.debug('Send command: %s', dat)
        self.writer.write(json.dumps(dat).encode() + MSG_SPLIT)
        await self.writer.drain()

        if not fut:
            return None
        try:
            await asyncio.wait_for(fut, self.timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            del self._msgs[cid]
        res = fut.result()
        return res

    async def topology(self, wait_result=False):
        cmd = 'device_get.topology' if self.pid == PID_WIFI_PANEL else 'gateway_get.topology'
        await self.send(cmd, wait_result=wait_result)

    async def get_node(self, nid=0, wait_result=True):
        cmd = 'device_get.node' if self.pid == PID_WIFI_PANEL else 'gateway_get.node'
        return await self.send(cmd, params={'id': nid}, wait_result=wait_result)

    async def get_room(self, rid=0, wait_result=True):
        return await self.send('gateway_get.room', params={'id': rid}, wait_result=wait_result)

    async def get_scene(self, rid=0, wait_result=True):
        res = await self.send('gateway_get.scene', params={'id': rid}, wait_result=wait_result)
        if res:
            res = res.get('scenes', [])
        return res
