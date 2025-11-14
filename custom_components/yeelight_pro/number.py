"""Support for number."""
import logging
import asyncio

from homeassistant.core import callback
from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
    DOMAIN as ENTITY_DOMAIN,
)
from homeassistant.const import UnitOfTime

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
            if conv.attr == "delayoff":
                entity = DelayoffEntity(device, conv)
            else:
                entity = XNumberEntity(device, conv)
        if not entity.added:
            add_entities([entity])
    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(
        hass,
        config_entry,
        ENTITY_DOMAIN,
        setuper(async_add_entities),
    )


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(
        hass,
        config or discovery_info,
        ENTITY_DOMAIN,
        setuper(async_add_entities),
    )


class XNumberEntity(XEntity, NumberEntity):
    def __init__(self, device: XDevice, conv: Converter, option=None):
        super().__init__(device, conv, option)
        if hasattr(conv, "min"):
            self._attr_native_min_value = conv.min
        if hasattr(conv, "max"):
            self._attr_native_max_value = conv.max
        if hasattr(conv, "step"):
            self._attr_native_step = conv.step

    def _coerce(self, value: float):
        """Привести значение к шагу и диапазону min/max."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return getattr(self, "_attr_native_value", None)

        step = getattr(self, "_attr_native_step", None)
        if step:
            v = round(v / step) * step

        minv = getattr(self, "_attr_native_min_value", None)
        maxv = getattr(self, "_attr_native_max_value", None)
        if minv is not None:
            v = max(minv, v)
        if maxv is not None:
            v = min(maxv, v)
        return v

    @callback
    def async_set_state(self, data: dict):
        """Обновление состояния из данных устройства."""
        super().async_set_state(data)
        if self._name in data:
            coerced = self._coerce(data[self._name])
            if coerced is not None:
                self._attr_native_value = coerced

    async def async_set_native_value(self, value: float):
        """Установка значения через number.set_value."""
        value = self._coerce(value)
        if value is None:
            return False

        if ret := await self.device_send_props({self._name: value}):
            self._attr_native_value = value
            self.async_write_ha_state()
        return ret


class DelayoffEntity(XNumberEntity):
    """Специальная сущность delayoff: секунды до выключения, временно отображаются."""

    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    clear_task: asyncio.Task | None = None

    async def async_set_native_value(self, value: float):
        """Отправляет delayoff + включает свет, потом очищает отображаемое значение."""
        if self.clear_task:
            self.clear_task.cancel()

        value = self._coerce(value)
        if value is None:
            return False

        payload = {self._name: value, "light": True}

        if ret := await self.device_send_props(payload):
            self._attr_native_value = value
            # запоминаем последнее установленное значение
            self._attr_extra_state_attributes["latest_value"] = value
            self.async_write_ha_state()
            # планируем очистку состояния
            self.clear_task = self.hass.async_create_task(self.clear_state())
        return ret

    async def clear_state(self):
        """Через секунду очищает текущее значение (UI флаг)."""
        await asyncio.sleep(1)
        self._attr_native_value = None
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        if self.clear_task:
            self.clear_task.cancel()
        await super().async_will_remove_from_hass()
