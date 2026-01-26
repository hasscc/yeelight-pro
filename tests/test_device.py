import asyncio
import pytest

from homeassistant.components.light import ColorMode
from homeassistant.components.climate import FAN_LOW, FAN_MEDIUM, FAN_HIGH
from homeassistant.components.climate.const import HVACMode

from custom_components.yeelight_pro.core.device import (
    XDevice,
    LightDevice,
    MotionDevice,
    ContactDevice,
    CoverDevice,
    RelayDevice,
    SwitchPanelDevice,
    RelayDoubleDevice,
    WifiPanelDevice,
    ClimateDevice,
    GatewayDevice,
    NodeType,
    DeviceType,
)
from custom_components.yeelight_pro.core.converters.base import (
    Converter,
    PropConv,
    PropBoolConv,
    PropMapConv,
    EventConv,
    SceneConv,
)


class FakeGateway:
    """Минимальная заглушка ProGateway для тестов XDevice.from_node и set_prop."""

    def __init__(self, host="1.2.3.4", pid=1):
        self.host = host
        self.pid = pid
        self.devices = {}
        self.sent = []
        self.get_node_calls = []
        self.add_device_calls = []
        self.setup_entity_calls = []
        # device для случая GatewayDevice (в реальном коде это сам gateway-девайс)
        self.device = None

    async def get_node(self, node_id, wait_result=False):
        self.get_node_calls.append((node_id, wait_result))
        return {"id": node_id}

    async def add_device(self, dvc):
        self.devices[dvc.id] = dvc
        self.add_device_calls.append(dvc)

    async def setup_entity(self, domain, device, conv):
        self.setup_entity_calls.append((domain, device, conv))

    async def send(self, method, params=None, wait_result=True, **kwargs):
        self.sent.append((method, params, wait_result, kwargs))
        return {"ok": True}


class FakeHass:
    """Простейший hass с async_create_task."""

    def __init__(self, loop=None):
        self.loop = loop or asyncio.get_event_loop()
        self.created_tasks = []

    def async_create_task(self, coro):
        task = self.loop.create_task(coro)
        self.created_tasks.append(task)
        return task


def make_xdevice():
    node = {"id": 1, "nt": NodeType.MESH, "type": 0, "n": "Test"}
    dev = XDevice(node)
    dev.hass = FakeHass()
    return dev


# ---------- from_node / from_nodes ----------


@pytest.mark.asyncio
async def test_from_node_invalid_nt_returns_none():
    gw = FakeGateway()
    node = {"id": 1, "nt": 999, "type": DeviceType.LIGHT}
    dvc = await XDevice.from_node(gw, node)
    assert dvc is None


@pytest.mark.asyncio
async def test_from_node_light_creates_lightdevice_and_registers_on_gateway():
    gw = FakeGateway(pid=1)
    node = {
        "id": 10,
        "nt": NodeType.MESH,
        "type": DeviceType.LIGHT,
        "n": "Lamp",
    }

    dvc = await XDevice.from_node(gw, node)

    assert isinstance(dvc, LightDevice)
    assert dvc.id == 10
    assert dvc.name == "Lamp"
    # add_device был вызван
    assert 10 in gw.devices


@pytest.mark.asyncio
async def test_from_node_reuses_existing_device_and_updates_name():
    gw = FakeGateway()
    node_old = {"id": 1, "nt": NodeType.MESH, "type": DeviceType.LIGHT, "n": "Old"}
    existing = LightDevice(node_old)
    gw.devices[1] = existing

    node_new = {"id": 1, "nt": NodeType.MESH, "type": DeviceType.LIGHT, "n": "New"}

    dvc = await XDevice.from_node(gw, node_new)

    assert dvc is existing
    assert existing.name == "New"
    # add_device не должен был вызываться ещё раз
    assert gw.add_device_calls == []


@pytest.mark.asyncio
async def test_from_nodes_returns_only_supported_devices():
    gw = FakeGateway()
    nodes = [
        {"id": 1, "nt": NodeType.MESH, "type": DeviceType.LIGHT},
        {"id": 2, "nt": 0, "type": DeviceType.LIGHT},  # невалидный nt -> должен быть проигнорирован
    ]

    devices = await XDevice.from_nodes(gw, nodes)

    # должен вернуться только один корректный девайс
    assert len(devices) == 1
    assert isinstance(devices[0], LightDevice)
    assert devices[0].id == 1
    # во втором узле nt=0, поэтому девайс для него не создаётся
    assert 2 not in gw.devices


# ---------- subscribe_attrs / decode / encode / encode_read / update ----------


def test_subscribe_attrs_collects_self_childs_and_children_converters():
    dev = make_xdevice()

    main = Converter("main")
    main.childs = {"child1", "child2"}

    child = Converter("child1", parent="main")
    other = Converter("other", parent="other_parent")

    dev.add_converters(main, child, other)

    attrs = dev.subscribe_attrs(main)
    assert attrs == {"main", "child1", "child2"}


def test_decode_uses_prop_and_params_for_propconv():
    dev = make_xdevice()

    c1 = Converter("a")
    c2 = PropConv("b", prop="bx")

    dev.add_converters(c1, c2)

    value = {
        "a": 1,
        "params": {"bx": 2, "ignore": 9},
    }

    payload = dev.decode(value)
    assert payload == {"a": 1, "b": 2}


def test_decode_event_uses_event_name_for_lookup():
    dev = make_xdevice()

    # motion.true
    conv_motion = EventConv("motion.true")
    dev.converters["motion.true"] = conv_motion

    data = {"value": "motion.true", "params": {"foo": "bar"}}
    payload = dev.decode_event(data)
    # EventConv превращает motion.true -> motion: True + params
    assert payload["motion"] is True
    assert payload["foo"] == "bar"

    # panel.click
    conv_panel = EventConv("panel.click")
    dev.converters["panel.click"] = conv_panel
    data2 = {"value": "panel.click", "params": {"key": 1, "count": 2}}
    payload2 = dev.decode_event(data2)
    assert payload2["event"] == "panel.click"
    assert payload2["action"] == "button1_double"
    assert payload2["button"] == 1


def test_encode_builds_set_section_for_propconv():
    dev = make_xdevice()

    c1 = Converter("plain")
    c2 = PropConv("in_params", prop="p1")
    dev.add_converters(c1, c2)

    payload = dev.encode({"plain": 10, "in_params": 20})
    assert payload["plain"] == 10
    assert payload["set"]["p1"] == 20


def test_encode_read_calls_read_only_for_requested_attrs():
    dev = make_xdevice()

    class ReadConv(Converter):
        def read(self, device, payload):
            payload[self.attr] = "read"

    c1 = ReadConv("a")
    c2 = ReadConv("b")
    dev.add_converters(c1, c2)

    payload = dev.encode_read({"b"})
    assert payload == {"b": "read"}


def test_update_pushes_state_to_interested_entities_only():
    dev = make_xdevice()

    class FakeEntity:
        def __init__(self, subscribed_attrs, added):
            self.subscribed_attrs = set(subscribed_attrs)
            self.added = added
            self.state_calls = []
            self.write_calls = 0

        def async_set_state(self, value):
            self.state_calls.append(value)

        def async_write_ha_state(self):
            self.write_calls += 1

    e1 = FakeEntity({"a"}, added=True)
    e2 = FakeEntity({"b"}, added=False)

    dev.entities["e1"] = e1
    dev.entities["e2"] = e2

    dev.update({"a": 1, "b": 2})

    assert e1.state_calls == [{"a": 1, "b": 2}]
    assert e1.write_calls == 1

    assert e2.state_calls == [{"a": 1, "b": 2}]
    assert e2.write_calls == 0


@pytest.mark.asyncio
async def test_get_node_calls_gateway_send():
    dev = make_xdevice()
    gw = FakeGateway()
    dev.gateways.append(gw)

    res = await dev.get_node()

    # возвращаемое значение — то, что вернул gateway.send
    assert res == {"ok": True}

    # send() был вызван с правильным методом и params
    assert len(gw.sent) == 1
    method, params, wait_result, kwargs = gw.sent[0]
    assert method == "gateway_get.node"
    assert params == {"id": dev.id}
    assert wait_result is True


@pytest.mark.asyncio
async def test_set_prop_builds_payload_and_calls_gateway():
    dev = make_xdevice()
    gw = FakeGateway()
    dev.gateways.append(gw)

    await dev.set_prop(foo="bar")

    assert len(gw.sent) == 1
    method, params, wait_result, kwargs = gw.sent[0]
    assert method == "gateway_set.prop"
    assert params is None  # мы передаём nodes через kwargs
    assert "nodes" in kwargs
    node = kwargs["nodes"][0]
    assert node["id"] == dev.id
    assert node["nt"] == dev.nt
    assert node["foo"] == "bar"


# ---------- LightDevice / MotionDevice / CoverDevice / WifiPanelDevice / ClimateDevice ----------


def test_lightdevice_color_modes_by_type_and_converters():
    # базовый светильник
    d0 = LightDevice({"id": 1, "nt": NodeType.MESH, "type": DeviceType.LIGHT})
    assert d0.color_modes == {ColorMode.ONOFF}
    assert "light" in d0.converters
    assert isinstance(d0.converters["light"], PropBoolConv)

    # с яркостью
    d1 = LightDevice({"id": 2, "nt": NodeType.MESH, "type": DeviceType.LIGHT_WITH_BRIGHTNESS})
    assert d1.color_modes == {ColorMode.ONOFF, ColorMode.BRIGHTNESS}
    assert "brightness" in d1.converters

    # с температурой цвета
    d2 = LightDevice({"id": 3, "nt": NodeType.MESH, "type": DeviceType.LIGHT_WITH_COLOR_TEMP})
    assert ColorMode.BRIGHTNESS in d2.color_modes
    assert ColorMode.COLOR_TEMP in d2.color_modes
    assert "color_temp" in d2.converters

    # RGB
    d3 = LightDevice({"id": 4, "nt": NodeType.MESH, "type": DeviceType.LIGHT_WITH_COLOR})
    assert ColorMode.RGB in d3.color_modes
    assert "rgb_color" in d3.converters

    # LIGHT_WITH_ZOOM_CT добавляет angel
    d4 = LightDevice({"id": 5, "nt": NodeType.MESH, "type": DeviceType.LIGHT_WITH_ZOOM_CT})
    assert "angel" in d4.converters


def test_motiondevice_adds_luminance_for_cids_73():
    node = {
        "id": 1,
        "nt": NodeType.MESH,
        "type": DeviceType.MOTION_WITH_LIGHT,
        "cids": [73],
    }
    dev = MotionDevice(node)

    # motion, events, light
    assert "motion" in dev.converters
    assert "light" in dev.converters
    # и наш дополнительный luminance
    assert "luminance" in dev.converters
    lum = dev.converters["luminance"]
    assert isinstance(lum, PropConv)
    assert lum.unit_of_measurement == "lx"
    assert lum.device_class == "illuminance"


def test_contactdevice_converters():
    dev = ContactDevice({"id": 1, "nt": NodeType.MESH, "type": DeviceType.MAGNET_SENSOR})
    assert "contact" in dev.converters
    assert "contact.open" in dev.converters
    assert "contact.close" in dev.converters


def test_coverdevice_adds_reverse_when_rs_in_prop_params():
    dev = CoverDevice({"id": 1, "nt": NodeType.MESH, "type": DeviceType.CURTAIN})
    # базовые конвертеры
    assert "motor" in dev.converters
    assert "position" in dev.converters
    assert "current_position" in dev.converters

    # reverse нет, пока нет 'rs'
    assert "reverse" not in dev.converters

    # добавляем rs и вызываем setup_converters ещё раз
    dev.prop = {"params": {"rs": True}}
    dev.setup_converters()
    assert "reverse" in dev.converters
    assert isinstance(dev.converters["reverse"], PropBoolConv)


def test_relaydevice_switches_and_switch_power():
    dev = RelayDevice({"id": 1, "nt": NodeType.MESH, "type": DeviceType.RELAY_DOUBLE})
    # задаём параметры
    dev.prop = {"params": {"1-p": True, "2-p": False}}

    # switch_power читает prop_params
    assert dev.switch_power(1) is True
    assert dev.switch_power(2) is False

    switches = dev.switches
    assert switches == {1: True, 2: False}


def test_switchpaneldevice_uses_sp_and_backlight():
    dev = SwitchPanelDevice({"id": 1, "nt": NodeType.MESH, "type": DeviceType.SWITCH_PANEL})
    dev.prop = {"params": {"1-sp": True, "0-blp": True}}
    dev.setup_converters()

    # switch_power переопределён и читает sp
    assert dev.switch_power(1) is True
    # конвертеры по sp + backlight
    assert "switch" in dev.converters or "switch1" in dev.converters
    assert "backlight" in dev.converters


def test_relaydoubledevice_has_two_switches():
    dev = RelayDoubleDevice({"id": 1, "nt": NodeType.MESH, "type": DeviceType.RELAY_DOUBLE})
    assert "switch1" in dev.converters
    assert "switch2" in dev.converters


@pytest.mark.asyncio
async def test_wifipaneldevice_set_prop_uses_device_set_prop():
    node = {"id": 5, "nt": NodeType.MESH, "type": DeviceType.RELAY_DOUBLE}
    dev = WifiPanelDevice(node)
    gw = FakeGateway(host="10.0.0.1")
    dev.gateways.append(gw)

    await dev.set_prop(foo="bar")

    assert len(gw.sent) == 1
    method, params, wait_result, kwargs = gw.sent[0]
    assert method == "device_set.prop"  # переопределён
    node = kwargs["nodes"][0]
    assert node["id"] == dev.id
    assert node["foo"] == "bar"


def test_climatedevice_converters():
    dev = ClimateDevice({"id": 1, "nt": NodeType.MESH, "type": DeviceType.AIR_CONDITIONER})
    # базовый climate конвертер
    assert "climate" in dev.converters
    assert "is_on" in dev.converters
    assert "current_temperature" in dev.converters
    assert "target_temperature" in dev.converters
    assert "mode" in dev.converters
    assert "fan_mode" in dev.converters

    mode_conv = dev.converters["mode"]
    assert isinstance(mode_conv, PropMapConv)
    assert mode_conv.map[1] == HVACMode.COOL

    fan_conv = dev.converters["fan_mode"]
    assert isinstance(fan_conv, PropMapConv)
    assert fan_conv.map[1] == FAN_HIGH
    assert fan_conv.map[2] == FAN_MEDIUM
    assert fan_conv.map[4] == FAN_LOW


@pytest.mark.asyncio
async def test_gatewaydevice_add_scene_adds_sceneconv():
    gw = FakeGateway()
    gwdev = GatewayDevice(gw)

    # привяжем gateway к устройству, чтобы property gateway при желании работал
    gwdev.gateways.append(gw)

    await gwdev.add_scene({"id": 7, "n": "Scene 7"})
    key = "scene_7"
    assert key in gwdev.converters
    assert isinstance(gwdev.converters[key], SceneConv)


def test_entity_id_for_gatewaydevice_and_xdevice():
    # обычный XDevice
    dev = XDevice({"id": 1, "nt": NodeType.MESH, "type": DeviceType.LIGHT})
    conv = Converter("light", domain="light")
    assert dev.entity_id(conv) == "light.yp1_1_light"

    # gateway device использует yp_ без id в середине
    gw = FakeGateway()
    gwdev = GatewayDevice(gw)
    conv2 = Converter("scene_1", domain="button")
    assert gwdev.entity_id(conv2) == "button.yp_scene_1"
