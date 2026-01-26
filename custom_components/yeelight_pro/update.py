"""Support for firmware update."""
import logging

from homeassistant.core import callback
from homeassistant.const import EntityCategory
from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityFeature,
    UpdateDeviceClass,
    DOMAIN as ENTITY_DOMAIN,
)

from . import (
    XDevice,
    XEntity,
    Converter,
    async_add_setuper,
)
from .core.device import GatewayDevice

_LOGGER = logging.getLogger(__name__)


def setuper(add_entities):
    def setup(device: XDevice, conv: Converter):
        if not (entity := device.entities.get(conv.attr)):
            if conv.attr == 'firmware' and isinstance(device, GatewayDevice):
                entity = XGatewayUpdateEntity(device, conv)
            else:
                entity = XUpdateEntity(device, conv)
        if not entity.added:
            add_entities([entity])
    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(hass, config_entry, ENTITY_DOMAIN, setuper(async_add_entities))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))


class XUpdateEntity(XEntity, UpdateEntity):
    """Update entity for device firmware."""
    
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_supported_features = UpdateEntityFeature(0)

    def __init__(self, device: XDevice, conv: Converter, option=None):
        super().__init__(device, conv, option)
        self._attr_name = 'Firmware'
        self._attr_installed_version = device.firmware_version
        self._attr_latest_version = device.firmware_version
        self._new_version = None

    @callback
    def async_set_state(self, data: dict):
        """Update firmware state."""
        if 'firmware_version' in data:
            self._attr_installed_version = data['firmware_version']
        if 'new_firmware_version' in data:
            self._new_version = data['new_firmware_version']
            self._attr_latest_version = data['new_firmware_version']
        if 'firmware_update_available' in data and data['firmware_update_available']:
            if self._new_version:
                self._attr_latest_version = self._new_version

    @property
    def available(self) -> bool:
        """Firmware update entity is available when device is online."""
        return self.device.online if self.device.online is not None else True


class XGatewayUpdateEntity(XUpdateEntity):
    """Update entity for gateway firmware."""

    def __init__(self, device: GatewayDevice, conv: Converter, option=None):
        super().__init__(device, conv, option)
        self._attr_name = 'Gateway Firmware'

    @property
    def available(self) -> bool:
        """Gateway firmware update is always available when connected."""
        return True
