import asyncio

from homeassistant.core import HomeAssistant
from custom_components.yeelight_pro.core.device import (
    XDevice,
    LightDevice,
    RelayDevice,
    SwitchPanelDevice,
)
from .test_gateway import get_gateway


class Hass(HomeAssistant):
    def __init__(self):
        asyncio.get_running_loop = lambda: asyncio.new_event_loop()
        HomeAssistant.__init__(self)
        self.bus.async_fire = self.async_fire
        self.events = []

    def async_fire(self, *args, **kwargs):
        self.events.append(args)


gateway = get_gateway()


def test_light():
    node = {"nt": 2, "id": 1270, "n": "客厅灯", "type": 3}
    device = asyncio.run(XDevice.from_node(gateway, node))
    assert isinstance(device, LightDevice)

    prop = {"id": 1001, "nt": 2, "o": True, "fv": "1.0.1", "params": {"p": True, "l": 20, "c": 255, "ct": 4000}}
    asyncio.run(device.prop_changed(prop))
    data = device.decode(prop)
    assert data['light'] is True
    assert data['brightness'] == round(255 * 20 / 100)
    assert data['color_temp'] == int(1000000.0 / 4000)


def test_relay():
    node = {"id": 1273, "nt": 2, "n": "双路继电器", "type": 7}
    device = asyncio.run(XDevice.from_node(gateway, node))
    assert isinstance(device, RelayDevice)

    prop = {
        "id": 1273, "nt": 2, "pid": 0, "pt": 7, "o": True,
        "params": {
            "p": False, "1-p": True, "2-p": False,
        }
    }
    asyncio.run(device.prop_changed(prop))
    data = device.decode(prop)
    assert data['switch1'] is True
    assert data['switch2'] is False


def test_switch_panel():
    node = {"id": 1271, "nt": 2, "n": "3键开关", "type": 13}
    device = asyncio.run(XDevice.from_node(gateway, node))
    assert isinstance(device, SwitchPanelDevice)

    prop = {
        "id": 1271, "nt": 2, "pid": 854019, "pt": 13, "o": True,
        "params": {
            "0-blp": True, "1-sp": False, "2-sp": True, "3-sp": True,
        }
    }
    asyncio.run(device.prop_changed(prop))
    data = device.decode(prop)
    assert data['switch1'] is False
    assert data['switch2'] is True
    assert data['switch3'] is True
    assert data['backlight'] is True
