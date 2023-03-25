"""Support for button."""
import logging

from homeassistant.components.button import (
    ButtonEntity,
    DOMAIN as ENTITY_DOMAIN,
)

from . import (
    XDevice,
    XEntity,
    Converter,
    async_add_setuper,
)
from .core.converters.base import SceneConv

_LOGGER = logging.getLogger(__name__)


def setuper(add_entities):
    def setup(device: XDevice, conv: Converter):
        if not (entity := device.entities.get(conv.attr)):
            if isinstance(conv, SceneConv):
                entity = XSceneEntity(device, conv)
            else:
                entity = XButtonEntity(device, conv)
        if not entity.added:
            add_entities([entity])
    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(hass, config_entry, ENTITY_DOMAIN, setuper(async_add_entities))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))


class XButtonEntity(XEntity, ButtonEntity):
    _attr_state = None


class XSceneEntity(XButtonEntity):
    def __init__(self, device: XDevice, conv: SceneConv, option=None):
        super().__init__(device, conv, option)
        self._attr_id = conv.node.get('id')
        self._attr_name = conv.node.get('n') or conv.attr

    async def async_press(self):
        """Press the button."""
        await self.device.gateway.send('gateway_set.prop', scenes=[{'id': self._attr_id}])
