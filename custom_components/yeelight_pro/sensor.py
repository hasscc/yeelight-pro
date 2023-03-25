"""Support for sensor."""
import logging
import asyncio

from homeassistant.core import callback
from homeassistant.components.sensor import (
    SensorEntity,
    DOMAIN as ENTITY_DOMAIN,
)
from homeassistant.helpers.restore_state import RestoreEntity

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
            if conv.attr == 'action':
                entity = XActionEntity(device, conv)
            else:
                entity = XSensorEntity(device, conv)
        if not entity.added:
            add_entities([entity])
    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(hass, config_entry, ENTITY_DOMAIN, setuper(async_add_entities))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))


class XSensorEntity(XEntity, SensorEntity, RestoreEntity):

    @callback
    def async_set_state(self, data: dict):
        super().async_set_state(data)
        self._attr_native_value = self._attr_state
        self._attr_extra_state_attributes['native_value'] = self._attr_state

    @callback
    def async_restore_last_state(self, state: str, attrs: dict):
        self._attr_native_value = attrs.get('native_value', state)
        for k, v in attrs.items():
            if k in self.subscribed_attrs or k == 'native_value':
                self._attr_extra_state_attributes[k] = v


class XActionEntity(XEntity, SensorEntity):
    _attr_native_value = ''
    clear_task: asyncio.Task = None

    @callback
    def async_set_state(self, data: dict):
        if self._name not in data or not self.hass:
            return
        if self.clear_task:
            self.clear_task.cancel()

        self._attr_native_value = data[self._name]
        self._attr_extra_state_attributes = data
        self.clear_task = self.hass.loop.create_task(self.clear_state())
        _LOGGER.info('%s: State changed: %s', self.entity_id, data)

    async def clear_state(self):
        await asyncio.sleep(0.3)
        self._attr_native_value = ''
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        if self.clear_task:
            self.clear_task.cancel()

        if self.native_value != '':
            self._attr_native_value = ''
            self.async_write_ha_state()

        await super().async_will_remove_from_hass()
