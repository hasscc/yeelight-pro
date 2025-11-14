"""Support for light."""
import logging
import asyncio
import time
import voluptuous as vol

from homeassistant.helpers.entity_platform import async_get_current_platform
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
    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "prestage_color_temp",
        vol.Schema({
            vol.Exclusive(ATTR_COLOR_TEMP_KELVIN, "ct"): vol.Coerce(int),
            vol.Exclusive(ATTR_COLOR_TEMP, "ct"): vol.Coerce(int),
        }),
        "async_prestage_color_temp",
    )


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))
    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "prestage_color_temp",
        vol.Schema({
            vol.Exclusive(ATTR_COLOR_TEMP_KELVIN, "ct"): vol.Coerce(int),
            vol.Exclusive(ATTR_COLOR_TEMP, "ct"): vol.Coerce(int),
        }),
        "async_prestage_color_temp",
    )


class XLightEntity(XEntity, LightEntity):
    _attr_is_on = None
    target_task: asyncio.Task = None

    def __init__(self, device: XDevice, conv: Converter, option=None):
        super().__init__(device, conv, option)

        # Initialize flags first
        self._attr_supported_color_modes = set()
        self._attr_supported_features = LightEntityFeature(0)

        # Supported color modes
        if device.converters.get(ATTR_RGB_COLOR):
            self._attr_supported_color_modes.add(ColorMode.RGB)

        if cov := device.converters.get(ATTR_COLOR_TEMP):
            self._attr_supported_color_modes.add(ColorMode.COLOR_TEMP)
            if hasattr(cov, "minm") and hasattr(cov, "maxm"):
                self._attr_min_mireds = cov.minm
                self._attr_max_mireds = cov.maxm
            elif hasattr(cov, "mink") and hasattr(cov, "maxk"):
                self._attr_min_mireds = int(1_000_000 / cov.maxk)
                self._attr_max_mireds = int(1_000_000 / cov.mink)
                self._attr_min_color_temp_kelvin = cov.mink
                self._attr_max_color_temp_kelvin = cov.maxk

        if not self._attr_supported_color_modes:
            self._attr_supported_color_modes = (
                {ColorMode.BRIGHTNESS}
                if device.converters.get(ATTR_BRIGHTNESS)
                else {ColorMode.ONOFF}
            )

        if device.converters.get(ATTR_TRANSITION):
            self._attr_supported_features |= LightEntityFeature.TRANSITION

        self._target_attrs = {}

    def _clamp_ct_kelvin(self, k: int) -> int:
        lo = getattr(self, "_attr_min_color_temp_kelvin", None)
        hi = getattr(self, "_attr_max_color_temp_kelvin", None)
        return max(lo, min(hi, k)) if lo and hi else k

    def _clamp_mired(self, m: int) -> int:
        lo = getattr(self, "_attr_min_mireds", None)
        hi = getattr(self, "_attr_max_mireds", None)
        return max(lo, min(hi, m)) if lo and hi else m

    @callback
    def async_set_state(self, data: dict):
        if self.target_task:
            self.target_task.cancel()

        diff = time.time() - self._target_attrs.get("time", 0)
        delay = float(self._target_attrs.get(ATTR_TRANSITION) or 5)

        async def _apply_state_later():
            await asyncio.sleep(max(0, delay - diff) + 0.01)
            super(XLightEntity, self).async_set_state(data)
            self.async_write_ha_state()

        if diff < delay and self._target_attrs:
            watched = {
                self._name,
                ATTR_BRIGHTNESS,
                ATTR_COLOR_TEMP,
                ATTR_COLOR_TEMP_KELVIN,
                ATTR_RGB_COLOR,
            }
            pending = {
                k: v for k, v in self._target_attrs.items() if k in watched
            }
            for k in list(pending):
                if data.get(k) == pending[k]:
                    self._target_attrs.pop(k, None)
                    pending.pop(k, None)
            if pending:
                self.target_task = asyncio.create_task(_apply_state_later())
                _LOGGER.debug(
                    "%s: Ignore new state during transition: %s",
                    self.name,
                    [data, self._target_attrs, diff, delay],
                )
                return

        super().async_set_state(data)
        if self._name in data:
            self._attr_is_on = data[self._name]
        if ATTR_BRIGHTNESS in data:
            self._attr_brightness = data[ATTR_BRIGHTNESS]
        if ATTR_COLOR_TEMP in data:
            self._attr_color_temp = data[ATTR_COLOR_TEMP]
        if ATTR_COLOR_TEMP_KELVIN in data:
            self._attr_color_temp_kelvin = data[ATTR_COLOR_TEMP_KELVIN]
        if ATTR_RGB_COLOR in data:
            self._attr_rgb_color = data[ATTR_RGB_COLOR]

    async def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        kwargs[self._name] = True
        self._target_attrs = {
            **kwargs,
            "time": time.time(),
        }
        if ATTR_RGB_COLOR in kwargs:
            self._attr_color_mode = ColorMode.RGB
        elif ATTR_COLOR_TEMP in kwargs or ATTR_COLOR_TEMP_KELVIN in kwargs:
            self._attr_color_mode = ColorMode.COLOR_TEMP
        else:
            self._attr_color_mode = None
        return await self.async_turn(kwargs[self._name], **kwargs)

    async def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        return await self.async_turn(False, **kwargs)

    async def async_turn(self, on: bool = True, **kwargs):
        """Turn the entity on/off."""
        kwargs[self._name] = on
        ret = await self.device_send_props(kwargs)
        if ret:
            self._attr_is_on = on
            self.async_write_ha_state()
        return ret

    async def async_prestage_color_temp(self, **kwargs):
        """
        Set color temperature while the light is OFF (no power change).

        Accepts ATTR_COLOR_TEMP_KELVIN or ATTR_COLOR_TEMP (mired).
        """
        payload: dict = {}

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            k = self._clamp_ct_kelvin(int(kwargs[ATTR_COLOR_TEMP_KELVIN]))
            payload["color_temp"] = k
            self._attr_color_temp_kelvin = k
            self._attr_color_temp = int(1_000_000 / max(1, k))
            self._attr_color_mode = ColorMode.COLOR_TEMP

        elif ATTR_COLOR_TEMP in kwargs:
            mired = self._clamp_mired(int(kwargs[ATTR_COLOR_TEMP]))
            k = int(1_000_000 / max(1, mired))
            k = self._clamp_ct_kelvin(k)  # keep both in sync if bounds exist
            payload["color_temp"] = k
            # recompute after clamp
            self._attr_color_temp = int(1_000_000 / max(1, k))
            self._attr_color_temp_kelvin = k
            self._attr_color_mode = ColorMode.COLOR_TEMP

        if not payload:
            return False

        # send props directly; do NOT include power flag
        ret = await self.device_send_props(payload)
        if ret:
            self.async_write_ha_state()
        return ret

    async def async_will_remove_from_hass(self):
        if self.target_task:
            self.target_task.cancel()
        await super().async_will_remove_from_hass()
