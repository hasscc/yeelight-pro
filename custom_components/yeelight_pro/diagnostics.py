"""Diagnostics support for Yeelight Pro."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .core.const import DOMAIN, CONF_GATEWAYS
from .core.gateway import ProGateway


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    gtw: ProGateway | None = hass.data.get(DOMAIN, {}).get(CONF_GATEWAYS, {}).get(entry.entry_id)
    
    diagnostics_data: dict[str, Any] = {
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "gateway": None,
    }
    
    if gtw:
        devices_info = []
        for dev_id, device in gtw.devices.items():
            devices_info.append({
                "id": dev_id,
                "name": device.name,
                "type": device.type,
                "pid": device.pid,
                "nt": device.nt,
                "online": device.online,
                "firmware_version": device.firmware_version,
                "converters": list(device.converters.keys()),
                "entities": list(device.entities.keys()),
            })
        
        diagnostics_data["gateway"] = {
            "host": gtw.host,
            "port": gtw.port,
            "pid": gtw.pid,
            "connected": gtw.is_connected,
            "stopping": gtw._stopping,
            "reconnect_delay": gtw._reconnect_delay,
            "json_error_count": gtw._json_error_count,
            "keepalive_interval": gtw.keepalive,
            "pending_messages": len(gtw._msgs),
            "devices_count": gtw.device_count,
            "last_topology_devices": list(gtw._last_topology_devices),
            "setups_registered": list(gtw.setups.keys()),
            "devices": devices_info,
        }
    
    return diagnostics_data
