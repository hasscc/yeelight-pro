import asyncio

import pytest

from homeassistant.components.light import (
    ColorMode,
    LightEntityFeature,
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_TRANSITION,
)

from custom_components.yeelight_pro.core.device import XDevice
from custom_components.yeelight_pro.core.converters.base import (
    Converter,
    BrightnessConv,
    ColorTempKelvin,
    ColorRgbConv,
)
from custom_components.yeelight_pro.light import XLightEntity


class FakeBus:
    def async_fire(self, *_, **__):
        """No-op event bus."""


class FakeHass:
    """Минимальный fake hass для XEntity/XLightEntity."""

    def __init__(self):
        self.bus = FakeBus()
        self.events = []

    def async_create_task(self, coro):
        return asyncio.create_task(coro)


class FakeGateway:
    """Минимальный gateway, чтобы XEntity мог собрать device_info."""

    def __init__(self):
        self.host = "127.0.0.1"
        self.entry_id = "test-entry"
        # device нужен только с .id
        self.device = type("DG", (), {"id": "gw-id"})()


@pytest.fixture(autouse=True)
def patch_light_write_state(monkeypatch):
    """Глушим async_write_ha_state, чтобы не требовался живой hass-воркер."""
    monkeypatch.setattr(
        XLightEntity,
        "async_write_ha_state",
        lambda self, *_, **__: None,
    )


def make_light_device(
    with_rgb: bool = True,
    with_ct: bool = True,
    with_brightness: bool = True,
    with_transition: bool = True,
):
    """Создаёт минимальный XDevice, подходящий для тестов XLightEntity."""
    node = {"id": 1, "nt": 2, "n": "Test Light", "type": 0}
    device = XDevice(node)
    device.hass = FakeHass()
    device.gateways.append(FakeGateway())

    # базовый конвертер питания
    light_conv = Converter("light", "light")

    converters = {"light": light_conv}

    if with_brightness:
        converters[ATTR_BRIGHTNESS] = BrightnessConv(
            ATTR_BRIGHTNESS,
            parent="light",
            prop="l",
        )

    if with_ct:
        converters[ATTR_COLOR_TEMP] = ColorTempKelvin(
            ATTR_COLOR_TEMP,
            parent="light",
            prop="ct",
            mink=2700,
            maxk=6500,
        )

    if with_rgb:
        converters[ATTR_RGB_COLOR] = ColorRgbConv(
            ATTR_RGB_COLOR,
            parent="light",
            prop="c",
        )

    if with_transition:
        converters[ATTR_TRANSITION] = Converter(
            ATTR_TRANSITION,
            parent="light",
            prop="duration",
        )

    device.converters = converters
    return device, light_conv


def test_light_supported_modes_rgb_ct_transition():
    device, conv = make_light_device(
        with_rgb=True,
        with_ct=True,
        with_brightness=True,
        with_transition=True,
    )
    entity = XLightEntity(device, conv)

    # supported_color_modes определяется по наличию конвертеров
    assert entity.supported_color_modes == {ColorMode.RGB, ColorMode.COLOR_TEMP}

    # min/max mireds/kelvin считаются из ColorTempKelvin
    cov = device.converters[ATTR_COLOR_TEMP]
    assert entity.min_mireds == int(1_000_000 / cov.maxk)
    assert entity.max_mireds == int(1_000_000 / cov.mink)
    assert entity._attr_min_color_temp_kelvin == cov.mink
    assert entity._attr_max_color_temp_kelvin == cov.maxk

    # transition-фича включается, если есть конвертер transition
    assert entity.supported_features & LightEntityFeature.TRANSITION


def test_light_supported_modes_brightness_fallback():
    # нет RGB и CT -> только BRIGHTNESS
    device, conv = make_light_device(
        with_rgb=False,
        with_ct=False,
        with_brightness=True,
    )
    entity = XLightEntity(device, conv)
    assert entity.supported_color_modes == {ColorMode.BRIGHTNESS}


def test_light_supported_modes_onoff_fallback():
    # только питание -> ONOFF
    device, conv = make_light_device(
        with_rgb=False,
        with_ct=False,
        with_brightness=False,
    )
    entity = XLightEntity(device, conv)
    assert entity.supported_color_modes == {ColorMode.ONOFF}


def test_async_set_state_updates_fields():
    device, conv = make_light_device()
    entity = XLightEntity(device, conv)

    data = {
        "light": True,
        ATTR_BRIGHTNESS: 123,
        ATTR_COLOR_TEMP: 250,
        ATTR_COLOR_TEMP_KELVIN: 4000,
        ATTR_RGB_COLOR: (1, 2, 3),
    }

    entity.async_set_state(data)

    assert entity._attr_is_on is True
    assert entity.brightness == 123
    assert entity.color_temp == 250
    assert entity.color_temp_kelvin == 4000
    assert entity.rgb_color == (1, 2, 3)


@pytest.mark.asyncio
async def test_turn_on_sets_power_and_color_mode_rgb(monkeypatch):
    device, conv = make_light_device()
    entity = XLightEntity(device, conv)

    sent = {}

    async def fake_send(payload):
        sent.update(payload)
        return True

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    await entity.async_turn_on(**{ATTR_RGB_COLOR: (255, 0, 0)})

    assert sent["light"] is True
    assert sent[ATTR_RGB_COLOR] == (255, 0, 0)
    assert entity._attr_is_on is True
    assert entity._attr_color_mode == ColorMode.RGB


@pytest.mark.asyncio
async def test_turn_off_calls_device(monkeypatch):
    device, conv = make_light_device()
    entity = XLightEntity(device, conv)

    sent = {}

    async def fake_send(payload):
        sent.update(payload)
        return True

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    await entity.async_turn_off()
    assert sent["light"] is False
    assert entity._attr_is_on is False


@pytest.mark.asyncio
async def test_prestage_color_temp_kelvin(monkeypatch):
    device, conv = make_light_device()
    entity = XLightEntity(device, conv)

    sent = {}

    async def fake_send(payload):
        sent.update(payload)
        return True

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    await entity.async_prestage_color_temp(**{ATTR_COLOR_TEMP_KELVIN: 4000})

    assert sent["color_temp"] == 4000
    assert entity.color_temp_kelvin == 4000
    assert entity.color_temp == int(1_000_000 / 4000)
    assert entity._attr_color_mode == ColorMode.COLOR_TEMP
    # питание не трогаем
    assert entity._attr_is_on is None or entity._attr_is_on is False


@pytest.mark.asyncio
async def test_prestage_color_temp_mired_with_clamp(monkeypatch):
    device, conv = make_light_device()
    entity = XLightEntity(device, conv)

    sent = {}

    async def fake_send(payload):
        sent.update(payload)
        return True

    monkeypatch.setattr(entity, "device_send_props", fake_send)

    # mired, соответствующий очень большому Kelvin,
    # должен заклампиться до maxk=6500
    mired = 50  # 1_000_000 / 50 = 20000 K
    await entity.async_prestage_color_temp(**{ATTR_COLOR_TEMP: mired})

    assert sent["color_temp"] == 6500
    assert entity.color_temp_kelvin == 6500
    assert entity.color_temp == int(1_000_000 / 6500)
    assert entity._attr_color_mode == ColorMode.COLOR_TEMP
