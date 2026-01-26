import asyncio

import pytest

from custom_components.yeelight_pro.sensor import XSensorEntity, XActionEntity
from custom_components.yeelight_pro.core.converters.base import Converter


class FakeHass:
    """Минимальный hass: нужен только loop для XActionEntity."""

    def __init__(self, loop=None):
        self.loop = loop or asyncio.get_event_loop()

    def async_create_task(self, coro):
        return self.loop.create_task(coro)


class FakeGatewayDevice:
    def __init__(self):
        self.id = "gw-device-id"


class FakeGateway:
    """Фейковый gateway, чтобы XEntity мог собрать device_info."""

    def __init__(self):
        self.host = "127.0.0.1"
        self.entry_id = "test-entry"
        self.device = FakeGatewayDevice()


class FakeDevice:
    """
    Лёгкая заглушка вместо XDevice для XSensorEntity/XActionEntity.
    Ожидаемые поля/методы для XEntity:
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
        self.name = "Test device"
        self.pid = "pid"
        self.type = "type"
        self.firmware_version = "1.0.0"
        self.entities = {}
        self.online = True

    def subscribe_attrs(self, conv):
        return {conv.attr}

    def entity_id(self, conv):
        return f"{conv.domain}.test_{conv.attr}"


def make_sensor_entity():
    loop = asyncio.get_event_loop()
    hass = FakeHass(loop)
    device = FakeDevice(hass)
    conv = Converter("temperature", "sensor")
    entity = XSensorEntity(device, conv)
    return entity


def make_action_entity():
    loop = asyncio.get_event_loop()
    hass = FakeHass(loop)
    device = FakeDevice(hass)
    conv = Converter("action", "sensor")
    entity = XActionEntity(device, conv)
    return entity


def test_xsensor_async_set_state_sets_native_and_attr():
    """XSensorEntity.async_set_state должен проставлять native_value и extra native_value."""
    entity = make_sensor_entity()

    data = {"temperature": 25, "extra": "foo"}

    # Метод callback — вызываем напрямую
    entity.async_set_state(data)

    # state внутри XEntity выставляется по ключу conv.attr -> "temperature"
    assert entity._attr_native_value == 25
    assert entity._attr_extra_state_attributes["native_value"] == 25


def test_xsensor_async_restore_last_state_restores_native_and_attrs():
    """XSensorEntity.async_restore_last_state восстанавливает native_value и только нужные attrs."""
    entity = make_sensor_entity()

    attrs = {
        "native_value": 30,
        "temperature": 30,
        "other": "ignored",
    }

    entity.async_restore_last_state(state="old", attrs=attrs)

    # native_value должен браться из attrs['native_value']
    assert entity._attr_native_value == 30
    # extra_state_attributes должны содержать только подписанные атрибуты и native_value
    assert entity._attr_extra_state_attributes["native_value"] == 30
    assert entity._attr_extra_state_attributes["temperature"] == 30
    assert "other" not in entity._attr_extra_state_attributes


@pytest.mark.asyncio
async def test_xaction_async_set_state_schedules_clear_and_resets(monkeypatch):
    """
    XActionEntity.async_set_state:
    - устанавливает native_value и extra attrs
    - запускает clear_state, который обнуляет native_value.
    """
    entity = make_action_entity()

    # убираем реальные вызовы HA, чтобы не требовался настоящий hass
    monkeypatch.setattr(
        entity,
        "async_write_ha_state",
        lambda *a, **k: None,
    )

    data = {"action": "single", "foo": "bar"}

    entity.async_set_state(data)

    # сразу после установки
    assert entity._attr_native_value == "single"
    assert entity._attr_extra_state_attributes == data
    assert entity.clear_task is not None
    assert not entity.clear_task.done()

    # ждём выполнения clear_state
    await asyncio.sleep(0.4)

    assert entity._attr_native_value == ""


def test_xaction_async_set_state_ignores_when_no_name_or_hass():
    """Если в data нет ключа _name или нет hass — состояние не меняется."""
    entity = make_action_entity()

    # нет ключа "action" — не должно ничего менять
    entity.async_set_state({"foo": "bar"})
    assert entity._attr_native_value == ""

    # нет hass — тоже игнор
    entity.hass = None
    entity.async_set_state({"action": "tap"})
    assert entity._attr_native_value == ""
