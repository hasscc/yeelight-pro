import asyncio
import threading

import pytest

from custom_components.yeelight_pro.switch import XSwitchEntity
from custom_components.yeelight_pro.core.converters.base import Converter


class FakeHass:
    """Минимальный hass для XSwitchEntity, совместимый с async_write_ha_state."""

    def __init__(self, loop=None):
        self.loop = loop or asyncio.new_event_loop()
        self.loop_thread_id = threading.get_ident()
        # заглушки, чтобы XEntity не падал
        self.config = type("Cfg", (), {})()
        self.bus = type("Bus", (), {"async_fire": lambda *a, **k: None})()
        self.states = type("States", (), {"async_entity_ids": lambda *a, **k: []})()


class FakeGatewayDevice:
    def __init__(self):
        self.id = "gw-device-id"


class FakeGateway:
    def __init__(self):
        self.host = "127.0.0.1"
        self.entry_id = "test-entry"
        self.device = FakeGatewayDevice()


class FakeDevice:
    """Упрощённый XDevice для switch."""

    def __init__(self, hass):
        self.hass = hass
        self.gateway = FakeGateway()
        self.id = "dev-1"
        self.name = "Test switch"
        self.pid = "pid"
        self.type = "type"
        self.firmware_version = "1.0.0"
        self.entities = {}
        self.online = True

    def subscribe_attrs(self, conv):
        return {conv.attr}

    def entity_id(self, conv):
        return f"{conv.domain}.test_{conv.attr}"


def make_switch_entity():
    loop = asyncio.new_event_loop()
    hass = FakeHass(loop)
    device = FakeDevice(hass)
    conv = Converter("switch", "switch")
    entity = XSwitchEntity(device, conv)
    return entity


def test_switch_async_set_state_updates_is_on():
    entity = make_switch_entity()

    entity.async_set_state({"switch": True})
    assert entity.is_on is True

    entity.async_set_state({"switch": False})
    assert entity.is_on is False


@pytest.mark.asyncio
async def test_switch_async_turn_on_calls_device_and_sets_is_on(monkeypatch):
    entity = make_switch_entity()

    # глушим запись состояния в HA, чтобы не требовался настоящий entity_id/platform
    monkeypatch.setattr(
        entity,
        "async_write_ha_state",
        lambda *a, **k: None,
    )

    sent = {}

    async def fake_send(payload):
        sent["payload"] = payload
        return True

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    result = await entity.async_turn_on(foo="bar")

    assert result is True
    assert sent["payload"] == {"foo": "bar", "switch": True}
    assert entity.is_on is True


@pytest.mark.asyncio
async def test_switch_async_turn_off_calls_device_and_sets_is_on(monkeypatch):
    entity = make_switch_entity()

    monkeypatch.setattr(
        entity,
        "async_write_ha_state",
        lambda *a, **k: None,
    )

    sent = {}

    async def fake_send(payload):
        sent["payload"] = payload
        return True

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    result = await entity.async_turn_off(foo="bar")

    assert result is True
    assert sent["payload"] == {"foo": "bar", "switch": False}
    assert entity.is_on is False
