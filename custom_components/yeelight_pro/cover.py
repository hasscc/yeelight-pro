"""Support for cover."""
import logging

from homeassistant.core import callback
from homeassistant.components.cover import (
    CoverEntity,
    CoverState,
    DOMAIN as ENTITY_DOMAIN,
    ATTR_POSITION,
    ATTR_CURRENT_POSITION,
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
            entity = XCoverEntity(device, conv)
        if not entity.added:
            add_entities([entity])
    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(hass, config_entry, ENTITY_DOMAIN, setuper(async_add_entities))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))


class XCoverEntity(XEntity, CoverEntity, RestoreEntity):
    _attr_is_closed = None

    @callback
    def async_set_state(self, data: dict):
        if 'run_state' in data:
            self._attr_state = data['run_state']
            self._attr_is_opening = self._attr_state == CoverState.OPENING
            self._attr_is_closing = self._attr_state == CoverState.CLOSING
        if ATTR_POSITION in data:
            self._attr_current_cover_position = data[ATTR_POSITION]
            self._attr_is_closed = self._attr_current_cover_position <= 3

    @callback
    def async_restore_last_state(self, state: str, attrs: dict):
        if state:
            self.async_set_state({'run_state': state})
        if ATTR_CURRENT_POSITION in attrs:
            self.async_set_state({ATTR_POSITION: attrs[ATTR_CURRENT_POSITION]})

    async def async_open_cover(self, **kwargs):
        kwargs[ATTR_POSITION] = 100
        await self.async_set_cover_position(**kwargs)

    async def async_close_cover(self, **kwargs):
        kwargs[ATTR_POSITION] = 0
        await self.async_set_cover_position(**kwargs)

    async def async_stop_cover(self, **kwargs):
        await self.device_send_props({self._name: 'pause'})

    async def async_set_cover_position(self, **kwargs):
        await self.device_send_props(kwargs)
