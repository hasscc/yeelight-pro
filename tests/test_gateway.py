import asyncio

from homeassistant.core import HomeAssistant
from custom_components.yeelight_pro.core.gateway import ProGateway


class Hass(HomeAssistant):
    def __init__(self):
        asyncio.get_running_loop = lambda: asyncio.new_event_loop()
        HomeAssistant.__init__(self)
        self.bus.async_fire = self.async_fire
        self.events = []

    def async_fire(self, *args, **kwargs):
        self.events.append(args)


def test_gateway():
    host = '127.0.0.1'
    gtw = ProGateway(host)
    assert gtw.host == host
