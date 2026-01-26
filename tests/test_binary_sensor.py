import asyncio

from homeassistant.const import STATE_ON
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.yeelight_pro.binary_sensor import XBinarySensorEntity
from custom_components.yeelight_pro.core.converters.base import Converter


class FakeHass:
    def __init__(self, loop=None):
        self.loop = loop or asyncio.new_event_loop()


class FakeGatewayDevice:
    def __init__(self):
        self.id = "gw-device-id"


class FakeGateway:
    def __init__(self):
        self.host = "1.2.3.4"
        self.entry_id = "test-entry"
        self.device = FakeGatewayDevice()


class FakeDevice:
    def __init__(self, hass=None):
        self.hass = hass or FakeHass()
        self.gateway = FakeGateway()
        self.id = 1
        self.name = "Test sensor device"
        self.pid = "pid"
        self.type = "type"
        self.firmware_version = "1.0"
        self.entities = {}
        self.online = True

    def subscribe_attrs(self, conv):
        return {conv.attr}

    def entity_id(self, conv):
        return f"{conv.domain}.test_{conv.attr}"


def make_entity(attr: str) -> XBinarySensorEntity:
    hass = FakeHass()
    device = FakeDevice(hass)
    conv = Converter(attr, "binary_sensor")
    return XBinarySensorEntity(device, conv)


def test_binary_sensor_async_set_state_sets_is_on_and_state():
    entity = make_entity("motion")

    data = {"motion": True, "extra": 123}
    entity.async_set_state(data)

    # базовый XEntity выставляет _attr_state и extra_state_attributes
    assert entity._attr_state is True
    assert entity._attr_extra_state_attributes["motion"] is True
    # наш override выставляет _attr_is_on
    assert entity._attr_is_on is True


def test_binary_sensor_restore_last_state_motion():
    entity = make_entity("motion")

    attrs = {"motion": True, "ignored": "x"}
    entity.async_restore_last_state(STATE_ON, attrs)

    assert entity._attr_is_on is True
    # в extra_state_attributes попадают только подписанные атрибуты
    assert entity._attr_extra_state_attributes["motion"] is True
    assert "ignored" not in entity._attr_extra_state_attributes
    # для motion ставится класс MOTION
    assert entity._attr_device_class == BinarySensorDeviceClass.MOTION


def test_binary_sensor_restore_last_state_contact():
    entity = make_entity("contact")

    attrs = {"contact": True}
    entity.async_restore_last_state(STATE_ON, attrs)

    assert entity._attr_is_on is True
    assert entity._attr_extra_state_attributes["contact"] is True
    # для contact ставится класс DOOR
    assert entity._attr_device_class == BinarySensorDeviceClass.DOOR
