"""Support for switch."""
import logging

from homeassistant.core import callback
from homeassistant.components.switch import (
    SwitchEntity,
    DOMAIN as ENTITY_DOMAIN,
)

from . import (
    XDevice,
    XEntity,
    Converter,
    async_add_setuper,
)

_LOGGER = logging.getLogger(__name__)


def setuper(add_entities):
    def setup(device: XDevice, conv: Converter):
        if not (entity := device.entities.get(conv.attr)):
            entity = XSwitchEntity(device, conv)
        if not entity.added:
            add_entities([entity])
    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(hass, config_entry, ENTITY_DOMAIN, setuper(async_add_entities))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))


class XSwitchEntity(XEntity, SwitchEntity):
    _attr_is_on = None

    @callback
    def async_set_state(self, data: dict):
        super().async_set_state(data)

        if self._name in data:
            self._attr_is_on = data[self._name]

    async def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        return await self.async_turn(True, **kwargs)

    async def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        return await self.async_turn(False, **kwargs)

    async def async_turn(self, on=True, **kwargs):
        """Turn the entity on/off."""
        kwargs[self._name] = on
        ret = await self.device_send_props(kwargs)
        if ret:
            self._attr_is_on = on
            self.async_write_ha_state()
        return ret
