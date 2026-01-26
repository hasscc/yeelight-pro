"""Support for binary sensor."""
import logging

from homeassistant.core import callback
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
    DOMAIN as ENTITY_DOMAIN,
)
from homeassistant.helpers.restore_state import RestoreEntity

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
            if conv.attr == 'connection' and isinstance(device, GatewayDevice):
                entity = XGatewayConnectionEntity(device, conv)
            elif conv.attr == 'motion':
                entity = XBinarySensorEntity(device, conv)
            else:
                entity = XBinarySensorEntity(device, conv)
        if not entity.added:
            add_entities([entity])
    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(hass, config_entry, ENTITY_DOMAIN, setuper(async_add_entities))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))


class XBinarySensorEntity(XEntity, BinarySensorEntity, RestoreEntity):

    @callback
    def async_set_state(self, data: dict):
        super().async_set_state(data)
        if self._name in data:
            self._attr_is_on = data[self._name]

    @callback
    def async_restore_last_state(self, state: str, attrs: dict):
        self._attr_is_on = state == STATE_ON
        for k, v in attrs.items():
            if k in self.subscribed_attrs:
                self._attr_extra_state_attributes[k] = v

        if self._name == 'motion':
            self._attr_device_class = BinarySensorDeviceClass.MOTION
        if self._name == 'contact':
            self._attr_device_class = BinarySensorDeviceClass.DOOR


class XGatewayConnectionEntity(XEntity, BinarySensorEntity):
    """Binary sensor for gateway connection status."""
    
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: GatewayDevice, conv: Converter, option=None):
        super().__init__(device, conv, option)
        self._attr_name = 'Connection'
        self._attr_is_on = device.online

    @callback
    def async_set_state(self, data: dict):
        """Update connection state from gateway."""
        if 'connection' in data:
            self._attr_is_on = data['connection']
        elif 'available' in data:
            self._attr_is_on = data['available']

    @property
    def available(self) -> bool:
        """Connection sensor is always available."""
        return True
