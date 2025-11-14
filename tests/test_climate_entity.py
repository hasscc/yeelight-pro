import asyncio
import threading

import pytest

from homeassistant.components.climate import (
    ClimateEntityFeature,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
)
from homeassistant.components.climate.const import HVACMode

from custom_components.yeelight_pro.core.device import XDevice
from custom_components.yeelight_pro.core.converters.base import Converter
from custom_components.yeelight_pro.climate import XClimateEntity


class FakeHass:
    """Минимальный hass для XClimateEntity."""

    def __init__(self, loop=None):
        self.loop = loop or asyncio.new_event_loop()
        self.loop_thread_id = threading.get_ident()
        # только то, что нужно для climate: единицы измерения температуры
        self.config = type(
            "Cfg",
            (),
            {"units": type("U", (), {"temperature_unit": "°C"})()},
        )()
        # чтобы XEntity не падал, если вдруг захочет что-то писать/читать
        self.bus = type("Bus", (), {"async_fire": lambda *a, **k: None})()
        self.states = type("States", (), {"async_entity_ids": lambda *a, **k: []})()

    def async_create_task(self, coro):
        return self.loop.create_task(coro)


class FakeGateway:
    """Минимальный gateway, чтобы XEntity мог собрать device_info."""

    def __init__(self):
        self.host = "127.0.0.1"
        self.device = type("DG", (), {"id": "gw"})()


def make_climate_device():
    """Создаёт XDevice и Converter для XClimateEntity."""
    node = {"id": 1, "nt": 2, "n": "Test Climate", "type": 0}
    device = XDevice(node)
    device.hass = FakeHass()
    device.gateways.append(FakeGateway())

    conv = Converter("climate", "climate")
    device.converters = {"climate": conv}
    return device, conv


def test_climate_init_defaults():
    """Проверяем дефолтные режимы и фичи после __init__."""
    device, conv = make_climate_device()
    entity = XClimateEntity(device, conv)

    assert entity.hvac_modes == [
        HVACMode.OFF,
        HVACMode.HEAT,
        HVACMode.COOL,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
    ]
    assert entity.fan_modes == [FAN_LOW, FAN_MEDIUM, FAN_HIGH]

    # supported_features
    assert entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
    assert entity.supported_features & ClimateEntityFeature.FAN_MODE
    assert entity.supported_features & ClimateEntityFeature.TURN_ON
    assert entity.supported_features & ClimateEntityFeature.TURN_OFF

    # начальные значения
    assert entity.hvac_mode == HVACMode.OFF
    assert entity.fan_mode is None
    assert entity.temperature_unit == "°C"
    assert entity.target_temperature_step == 1


def test_async_set_state_updates_hvac_mode():
    """async_set_state должен обновлять mode/is_on и hvac_mode."""
    device, conv = make_climate_device()
    entity = XClimateEntity(device, conv)

    # свет включён, режим HEAT
    entity.async_set_state({"mode": HVACMode.HEAT, "is_on": True})
    assert entity.mode == HVACMode.HEAT
    assert entity.is_on is True
    assert entity.hvac_mode == HVACMode.HEAT

    # выключаем — hvac_mode должен стать OFF
    entity.async_set_state({"is_on": False})
    assert entity.is_on is False
    assert entity.hvac_mode == HVACMode.OFF


@pytest.mark.asyncio
async def test_async_set_temperature_calls_device(monkeypatch):
    """async_set_temperature должен слать target_temperature в device_send_props."""
    device, conv = make_climate_device()
    entity = XClimateEntity(device, conv)

    sent = {}

    async def fake_send(payload):
        sent["payload"] = payload

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    await entity.async_set_temperature(temperature=23)

    assert sent["payload"] == {"target_temperature": 23}


@pytest.mark.asyncio
async def test_async_set_hvac_mode_off(monkeypatch):
    """HVACMode.OFF -> is_on=False."""
    device, conv = make_climate_device()
    entity = XClimateEntity(device, conv)

    sent = {}

    async def fake_send(payload):
        sent["payload"] = payload

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    await entity.async_set_hvac_mode(HVACMode.OFF)

    assert sent["payload"] == {"is_on": False}


@pytest.mark.asyncio
async def test_async_set_hvac_mode_cool(monkeypatch):
    """HVACMode.COOL -> is_on=True и mode=COOL."""
    device, conv = make_climate_device()
    entity = XClimateEntity(device, conv)

    sent = {}

    async def fake_send(payload):
        sent["payload"] = payload

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    await entity.async_set_hvac_mode(HVACMode.COOL)

    assert sent["payload"] == {"is_on": True, "mode": HVACMode.COOL}


@pytest.mark.asyncio
async def test_async_set_fan_mode(monkeypatch):
    """async_set_fan_mode добавляет fan_mode в payload и отправляет его."""
    device, conv = make_climate_device()
    entity = XClimateEntity(device, conv)

    sent = {}

    async def fake_send(payload):
        sent["payload"] = payload

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    await entity.async_set_fan_mode(FAN_HIGH, extra=1)

    # должен передать и extra, и fan_mode
    assert sent["payload"] == {"extra": 1, "fan_mode": FAN_HIGH}


@pytest.mark.asyncio
async def test_async_turn_on(monkeypatch):
    """async_turn_on проставляет is_on=True и передаёт остальные kwargs."""
    device, conv = make_climate_device()
    entity = XClimateEntity(device, conv)

    sent = {}

    async def fake_send(payload):
        sent["payload"] = payload

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    await entity.async_turn_on(foo="bar")

    assert sent["payload"] == {"foo": "bar", "is_on": True}


@pytest.mark.asyncio
async def test_async_turn_off(monkeypatch):
    """async_turn_off проставляет is_on=False и передаёт остальные kwargs."""
    device, conv = make_climate_device()
    entity = XClimateEntity(device, conv)

    sent = {}

    async def fake_send(payload):
        sent["payload"] = payload

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    await entity.async_turn_off(foo="bar")

    assert sent["payload"] == {"foo": "bar", "is_on": False}
