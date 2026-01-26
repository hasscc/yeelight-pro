import asyncio
import threading

import pytest

from homeassistant.components.cover import ATTR_POSITION, ATTR_CURRENT_POSITION

from custom_components.yeelight_pro.cover import XCoverEntity
from custom_components.yeelight_pro.core.converters.base import Converter


class FakeHass:
    """Минимальный hass для XCoverEntity (почти как в других тестах)."""

    def __init__(self, loop=None):
        self.loop = loop or asyncio.get_event_loop()
        self.loop_thread_id = threading.get_ident()
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
    """Упрощённый XDevice для cover."""

    def __init__(self, hass):
        self.hass = hass
        self.gateway = FakeGateway()
        self.id = "dev-1"
        self.name = "Test cover"
        self.pid = "pid"
        self.type = "type"
        self.firmware_version = "1.0.0"
        self.entities = {}
        self.online = True

    def subscribe_attrs(self, conv):
        return {conv.attr}

    def entity_id(self, conv):
        return f"{conv.domain}.test_{conv.attr}"


def make_cover_entity():
    loop = asyncio.get_event_loop()
    hass = FakeHass(loop)
    device = FakeDevice(hass)
    conv = Converter("cover", "cover")
    entity = XCoverEntity(device, conv)
    return entity


def test_cover_async_set_state_run_state_opening_closing():
    entity = make_cover_entity()

    # opening
    entity.async_set_state({"run_state": "opening"})
    assert entity._attr_is_opening is True
    assert entity._attr_is_closing is False
    assert entity._attr_state == "opening"

    # closing
    entity.async_set_state({"run_state": "closing"})
    assert entity._attr_is_opening is False
    assert entity._attr_is_closing is True
    assert entity._attr_state == "closing"

    # другое состояние
    entity.async_set_state({"run_state": "stopped"})
    assert entity._attr_is_opening is False
    assert entity._attr_is_closing is False
    assert entity._attr_state == "stopped"


def test_cover_async_set_state_position_and_is_closed():
    entity = make_cover_entity()

    # Открыто
    entity.async_set_state({ATTR_POSITION: 100})
    assert entity._attr_current_cover_position == 100
    assert entity._attr_is_closed is False

    # На границе закрытия (<= 3)
    entity.async_set_state({ATTR_POSITION: 3})
    assert entity._attr_current_cover_position == 3
    assert entity._attr_is_closed is True

    # Полностью закрыто
    entity.async_set_state({ATTR_POSITION: 0})
    assert entity._attr_current_cover_position == 0
    assert entity._attr_is_closed is True


def test_cover_async_restore_last_state_uses_run_state_and_position():
    entity = make_cover_entity()

    attrs = {
        ATTR_CURRENT_POSITION: 42,
    }

    # state -> run_state, attrs -> позиция
    entity.async_restore_last_state("opening", attrs)

    assert entity._attr_state == "opening"
    assert entity._attr_is_opening is True
    assert entity._attr_is_closing is False
    assert entity._attr_current_cover_position == 42
    assert entity._attr_is_closed is False


@pytest.mark.asyncio
async def test_cover_async_open_close_stop_and_set_position(monkeypatch):
    entity = make_cover_entity()

    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    # open -> position 100
    await entity.async_open_cover()
    assert sent[-1] == {ATTR_POSITION: 100}

    # close -> position 0
    await entity.async_close_cover()
    assert sent[-1] == {ATTR_POSITION: 0}

    # stop -> {self._name: "pause"}
    await entity.async_stop_cover()
    assert sent[-1] == {entity._name: "pause"}

    # set explicit position
    await entity.async_set_cover_position(**{ATTR_POSITION: 55})
    assert sent[-1] == {ATTR_POSITION: 55}