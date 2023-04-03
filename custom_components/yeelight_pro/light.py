"""Support for light."""
import logging
import asyncio
import time

from homeassistant.core import callback
from homeassistant.components.light import (
    LightEntity,
    DOMAIN as ENTITY_DOMAIN,
    ColorMode,
    LightEntityFeature,
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_TRANSITION,
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
            entity = XLightEntity(device, conv)
        if not entity.added:
            add_entities([entity])
    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(hass, config_entry, ENTITY_DOMAIN, setuper(async_add_entities))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))


class XLightEntity(XEntity, LightEntity):
    _attr_is_on = None
    target_task: asyncio.Task = None

    def __init__(self, device: XDevice, conv: Converter, option=None):
        super().__init__(device, conv, option)

        self._attr_supported_color_modes = {
            ColorMode.ONOFF,
        }
        if device.converters.get(ATTR_TRANSITION):
            self._attr_supported_features |= LightEntityFeature.TRANSITION
        if device.converters.get(ATTR_BRIGHTNESS):
            self._attr_supported_color_modes.add(ColorMode.BRIGHTNESS)
        if cov := device.converters.get(ATTR_COLOR_TEMP):
            self._attr_supported_color_modes.add(ColorMode.COLOR_TEMP)
            if hasattr(cov, 'minm') and hasattr(cov, 'maxm'):
                self._attr_min_mireds = cov.minm
                self._attr_max_mireds = cov.maxm
            elif hasattr(cov, 'mink') and hasattr(cov, 'maxk'):
                self._attr_min_mireds = int(1000000 / cov.maxk)
                self._attr_max_mireds = int(1000000 / cov.mink)
                self._attr_min_color_temp_kelvin = cov.mink
                self._attr_max_color_temp_kelvin = cov.maxk
        if device.converters.get(ATTR_RGB_COLOR):
            self._attr_supported_color_modes.add(ColorMode.RGB)

        self._target_attrs = {}

    @callback
    def async_set_state(self, data: dict):
        if self.target_task:
            self.target_task.cancel()
        diff = time.time() - self._target_attrs.get('time', 0)
        delay = float(self._target_attrs.get(ATTR_TRANSITION) or 5)

        async def set_state():
            await asyncio.sleep(delay - diff + 0.01)
            self.async_set_state(data)
            self.async_write_ha_state()

        if diff < delay:
            check_attrs = [self._name, ATTR_BRIGHTNESS, ATTR_COLOR_TEMP, ATTR_COLOR_TEMP_KELVIN]
            for k in check_attrs:
                if k not in data:
                    continue
                elif k not in self._target_attrs:
                    check_attrs.remove(k)
                elif self._target_attrs[k] == data[k]:
                    self._target_attrs.pop(k, None)
                    check_attrs.remove(k)
            if check_attrs:
                # ignore new state
                self.target_task = self.hass.loop.create_task(set_state())
                _LOGGER.info('%s: Ignore new state: %s', self.name, [data, self._target_attrs, diff, delay])
                return

        super().async_set_state(data)
        if self._name in data:
            self._attr_is_on = data[self._name]
        if ATTR_BRIGHTNESS in data:
            self._attr_brightness = data[ATTR_BRIGHTNESS]
        if ATTR_COLOR_TEMP in data:
            self._attr_color_temp = data[ATTR_COLOR_TEMP]
        if ATTR_RGB_COLOR in data:
            self._attr_rgb_color = data[ATTR_RGB_COLOR]

    async def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        kwargs[self._name] = True
        self._target_attrs = {
            **kwargs,
            'time': time.time(),
        }
        if ATTR_COLOR_TEMP in kwargs:
            self._attr_color_mode = ColorMode.COLOR_TEMP
        else:
            self._attr_color_mode = ColorMode.BRIGHTNESS
        return await self.async_turn(kwargs[self._name], **kwargs)

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

    async def async_will_remove_from_hass(self):
        if self.target_task:
            self.target_task.cancel()
        await super().async_will_remove_from_hass()
