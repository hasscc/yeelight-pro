import asyncio
import pytest

from custom_components.yeelight_pro.button import (
    setuper,
    XButtonEntity,
    XSceneEntity,
)
from custom_components.yeelight_pro.core.converters.base import Converter, SceneConv


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
        self.sent = []

    async def send(self, method, *_, **kwargs):
        self.sent.append((method, kwargs))
        return {"ok": True}


class FakeDevice:
    def __init__(self, hass=None):
        self.hass = hass or FakeHass()
        self.gateway = FakeGateway()
        self.id = 1
        self.name = "Test device"
        self.pid = "pid"
        self.type = "type"
        self.firmware_version = "1.0"
        self.entities = {}
        self.online = True

    def subscribe_attrs(self, conv):
        # кнопки обычно не подписываются ни на что, но XEntity требует set()
        return {conv.attr}

    def entity_id(self, conv):
        return f"{conv.domain}.test_{conv.attr}"


def make_device():
    loop = asyncio.new_event_loop()
    hass = FakeHass(loop)
    return FakeDevice(hass)


def test_button_setuper_creates_simple_button_entity():
    """setuper должен создавать XButtonEntity для обычного Converter."""
    device = make_device()
    conv = Converter("press", "button")

    added = []

    def add_entities(entities):
        added.extend(entities)

    setup = setuper(add_entities)
    setup(device, conv)

    assert len(added) == 1
    entity = added[0]
    assert isinstance(entity, XButtonEntity)
    assert not isinstance(entity, XSceneEntity)
    # сущность лежит в device.entities по attr
    assert device.entities["press"] is entity


def test_button_setuper_creates_scene_entity_for_sceneconv():
    """Для SceneConv должен создаваться XSceneEntity."""
    device = make_device()
    node = {"id": 42, "n": "Party scene"}
    conv = SceneConv("scene_42", "button", node=node)

    added = []

    def add_entities(entities):
        added.extend(entities)

    setup = setuper(add_entities)
    setup(device, conv)

    assert len(added) == 1
    entity = added[0]
    assert isinstance(entity, XSceneEntity)
    assert entity._attr_id == 42
    # имя берётся из node['n']
    assert entity._attr_name == "Party scene"
    assert device.entities["scene_42"] is entity


def test_button_setuper_does_not_add_if_entity_already_added():
    """Если сущность уже есть и added=True — повторно не добавляется."""
    device = make_device()
    conv = Converter("press", "button")
    existing = XButtonEntity(device, conv)
    existing.added = True
    device.entities["press"] = existing

    added = []

    def add_entities(entities):
        added.extend(entities)

    setup = setuper(add_entities)
    setup(device, conv)

    assert added == []  # ничего не добавлено


@pytest.mark.asyncio
async def test_scene_entity_async_press_sends_scene_to_gateway():
    """Нажатие сцены должно вызывать gateway.send с правильными параметрами."""
    device = make_device()
    node = {"id": 99, "n": "Relax"}
    conv = SceneConv("scene_99", "button", node=node)
    entity = XSceneEntity(device, conv)

    # подменяем gateway.send, чтобы отловить вызов
    sent = {}

    async def fake_send(method, **kwargs):
        sent["method"] = method
        sent["kwargs"] = kwargs
        return {"ok": True}

    device.gateway.send = fake_send

    await entity.async_press()

    assert sent["method"] == "gateway_set.prop"
    assert sent["kwargs"] == {"scenes": [{"id": 99}]}
