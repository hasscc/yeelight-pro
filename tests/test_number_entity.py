import asyncio
import pytest

from custom_components.yeelight_pro.number import DelayoffEntity
from custom_components.yeelight_pro.core.converters.base import DurationConv


class FakeHass:
    """Минимальный hass: нужен loop и async_create_task."""

    def __init__(self, loop):
        self.loop = loop

    def async_create_task(self, coro):
        return self.loop.create_task(coro)


class FakeGatewayDevice:
    """device у gateway, нужен только id."""

    def __init__(self):
        self.id = "gw-device-id"


class FakeGateway:
    """Минимальный gateway, чтобы XEntity мог собрать device_info."""

    def __init__(self):
        self.host = "127.0.0.1"
        self.entry_id = "test-entry"
        self.device = FakeGatewayDevice()


class FakeDevice:
    """
    Лёгкая заглушка вместо XDevice.

    DelayoffEntity/XEntity ожидают у неё:
    - hass
    - gateway
    - id, name, pid, type, firmware_version
    - entities (dict)
    - subscribe_attrs(conv)
    - entity_id(conv)
    """

    def __init__(self, hass):
        self.hass = hass
        self.gateway = FakeGateway()
        self.id = "dev-1"
        self.name = "Test light"
        self.pid = "pid"
        self.type = "type"
        self.firmware_version = "1.0.0"
        self.entities = {}
        self.online = True

    def subscribe_attrs(self, conv):
        return {conv.attr}

    def entity_id(self, conv):
        # Формат неважен, главное — чтобы был строкой
        return f"{conv.domain}.test_{conv.attr}"


def make_delayoff_entity():
    """Удобный helper для создания сущности DelayoffEntity."""
    loop = asyncio.get_event_loop()
    hass = FakeHass(loop)
    device = FakeDevice(hass)
    conv = DurationConv("delayoff", "number", readable=False)
    entity = DelayoffEntity(device, conv)
    return entity


@pytest.mark.asyncio
async def test_delayoff_set_native_value_sends_props_and_schedules_clear(monkeypatch):
    entity = make_delayoff_entity()

    # глушим async_write_ha_state, чтобы не требовался реальный hass.loop_thread_id
    monkeypatch.setattr(
        DelayoffEntity,
        "async_write_ha_state",
        lambda self, *_, **__: None,
    )

    sent: dict = {}

    async def fake_device_send_props(self, value: dict):
        sent["value"] = value
        return True

    # подменяем отправку на устройство
    monkeypatch.setattr(
        DelayoffEntity,
        "device_send_props",
        fake_device_send_props,
    )

    # вызываем метод
    await entity.async_set_native_value(10)

    # 1) payload правильный
    assert sent["value"] == {"delayoff": 10, "light": True}

    # 2) значения в сущности выставлены
    assert entity._attr_native_value == 10
    assert entity._attr_extra_state_attributes["latest_value"] == 10

    # 3) задача clear_state запущена
    assert entity.clear_task is not None
    assert not entity.clear_task.done()

    # 4) ждём, пока clear_state сбросит значение
    await asyncio.sleep(1.1)

    assert entity._attr_native_value is None
