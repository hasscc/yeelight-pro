import logging
from enum import IntEnum
from .converters.base import *

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .. import XEntity
    from .gateway import ProGateway
    from homeassistant.core import HomeAssistant

from homeassistant.components.light import ColorMode

_LOGGER = logging.getLogger(__name__)


class NodeType(IntEnum):
    GATEWAY = -1
    ROOM = 1
    MESH = 2
    GROUP = 3
    MRSH_GROUP = 4
    HOME = 5
    SCENE = 6


class DeviceType(IntEnum):
    LIGHT = 1
    LIGHT_WITH_BRIGHTNESS = 2
    LIGHT_WITH_COLOR_TEMP = 3
    LIGHT_WITH_COLOR = 4
    CURTAIN = 6
    RELAY_DOUBLE = 7
    VRF = 10
    SWITCH_PANEL = 13
    LIGHT_WITH_ZOOM_CT = 14
    AIR_CONDITIONER = 15
    SWITCH_SENSOR = 128
    MOTION_SENSOR = 129
    MAGNET_SENSOR = 130
    KNOB = 132
    MOTION_WITH_LIGHT = 134
    ILLUMINATION_SENSOR = 125
    TEMPERATURE_HUMIDITY = 136


DEVICE_TYPE_LIGHTS = [
    DeviceType.LIGHT,
    DeviceType.LIGHT_WITH_BRIGHTNESS,
    DeviceType.LIGHT_WITH_COLOR_TEMP,
    DeviceType.LIGHT_WITH_COLOR,
    DeviceType.LIGHT_WITH_ZOOM_CT,
]


class XDevice:
    hass: "HomeAssistant" = None
    converters: Dict[str, Converter] = None

    def __init__(self, node: dict):
        self.id = int(node['id'])
        self.nt = node.get('nt', 0)
        self.pid = node.get('pid')
        self.type = node.get('type', 0)
        self.name = node.get('n', '')
        self.prop = {}
        self.entities: Dict[str, "XEntity"] = {}
        self.gateways: List["ProGateway"] = []
        self.setup_converters()

    def setup_converters(self):
        self.converters = {}

    def add_converter(self, conv: Converter):
        if conv.attr not in self.converters:
            self.converters[conv.attr] = conv

    @staticmethod
    async def from_node(gateway: "ProGateway", node: dict):
        if node.get('nt') not in [NodeType.MESH, NodeType.MRSH_GROUP, NodeType.SCENE]:
            return None
        if not (nid := node.get('id')):
            return None
        if dvc := gateway.devices.get(nid):
            dvc.name = node.get('n', '')
        else:
            dvc = XDevice(node)
            if dvc.nt in [NodeType.SCENE]:
                await gateway.device.add_scene(node)
                return gateway.device
            elif dvc.type in DEVICE_TYPE_LIGHTS:
                dvc = LightDevice(node)
            elif dvc.type in [DeviceType.SWITCH_PANEL]:
                dvc = SwitchPanelDevice(node)
            elif dvc.type in [DeviceType.RELAY_DOUBLE]:
                dvc = RelayDevice(node)
            elif dvc.type in [DeviceType.SWITCH_SENSOR]:
                dvc = SwitchSensorDevice(node)
            elif dvc.type in [DeviceType.KNOB]:
                dvc = KnobDevice(node)
            elif dvc.type in [DeviceType.MOTION_SENSOR, DeviceType.MOTION_WITH_LIGHT]:
                dvc = MotionDevice(node)
            elif dvc.type in [DeviceType.MAGNET_SENSOR]:
                dvc = ContactDevice(node)
            else:
                _LOGGER.warning('Unsupported device: %s', node)
                return None
            if gateway.pid == 2:
                await gateway.get_node(dvc.id, wait_result=False)
            await gateway.add_device(dvc)
        return dvc

    @staticmethod
    async def from_nodes(gateway: "ProGateway", nodes: List[dict]):
        dls = []
        for node in nodes:
            if (dvc := XDevice.from_node(gateway, node)) is None:
                continue
            dls.append(dvc)
        return dls

    def prop_changed(self, data: dict):
        has_new = False
        for k in data.keys():
            if k not in self.prop:
                has_new = True
                break
        self.prop.update(data)
        if has_new:
            self.setup_converters()
        self.update(self.decode(data))

    def event_fired(self, data: dict):
        self.update(self.decode_event(data))

    @property
    def gateway(self):
        if self.gateways:
            return self.gateways[0]
        return None

    @property
    def online(self):
        return self.prop.get('o')

    @property
    def firmware_version(self):
        return self.prop.get('fv')

    @property
    def prop_params(self):
        return self.prop.get('params') or {}

    @property
    def unique_id(self):
        return f'{self.type}_{self.id}'

    def entity_id(self, conv: Converter):
        return f'{conv.domain}.yp{self.unique_id}_{conv.attr}'

    async def setup_entities(self):
        if not (gateway := self.gateway):
            return
        for conv in self.converters.values():
            domain = conv.domain
            if domain is None:
                continue
            if conv.attr in self.entities:
                continue
            await gateway.setup_entity(domain, self, conv)

    def subscribe_attrs(self, conv: Converter):
        attrs = {conv.attr}
        if conv.childs:
            attrs |= set(conv.childs)
        attrs.update(c.attr for c in self.converters.values() if c.parent == conv.attr)
        return attrs

    def decode(self, value: dict) -> dict:
        """Decode device props for HA."""
        payload = {}
        for conv in self.converters.values():
            prop = conv.prop or conv.attr
            data = value
            if isinstance(conv, PropConv):
                data = value.get('params') or {}
            if prop not in data:
                continue
            conv.decode(self, payload, data[prop])
        return payload

    def decode_event(self, data: dict) -> dict:
        payload = {}
        event = data.get('value')
        if conv := self.converters.get(event):
            value = data.get('params') or {}
            conv.decode(self, payload, value)
        return payload

    def encode(self, value: dict) -> dict:
        """Encode payload for device."""
        payload = {}
        for conv in self.converters.values():
            if conv.attr not in value:
                continue
            if isinstance(conv, PropConv):
                dat = payload.setdefault('set', {})
            else:
                dat = payload
            conv.encode(self, dat, value[conv.attr])
        return payload

    def encode_read(self, attrs: set) -> dict:
        payload = {}
        for conv in self.converters.values():
            if conv.attr not in attrs:
                continue
            conv.read(self, payload)
        return payload

    def update(self, value: dict):
        """Push new state to Hass entities."""
        if not value:
            return
        attrs = value.keys()

        for entity in self.entities.values():
            if not (entity.subscribed_attrs & attrs):
                continue
            entity.async_set_state(value)
            if entity.added:
                entity.async_write_ha_state()

    async def get_node(self):
        if not self.gateway:
            return None
        return await self.gateway.send('gateway_get.node', params={'id': self.id})

    async def set_prop(self, **kwargs):
        if not self.gateway:
            return None
        node = {
            'id': self.id,
            'nt': self.nt,
            **kwargs,
        }
        return await self.gateway.send('gateway_set.prop', nodes=[node])


class GatewayDevice(XDevice):
    def __init__(self, gateway: "ProGateway"):
        super().__init__({
            'id': 0,
            'nt': NodeType.GATEWAY,
            'pid': 'gateway',
            'type': 'gateway',
        })
        self.id = gateway.host
        self.name = 'Yeelight Pro'

    async def add_scene(self, node: dict):
        if not (nid := node.get('id')):
            return
        self.add_converter(SceneConv(f'scene_{nid}', 'button', node=node))
        await self.setup_entities()

    def entity_id(self, conv: Converter):
        return f'{conv.domain}.yp_{conv.attr}'


class LightDevice(XDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converter(PropBoolConv('light', 'light', prop='p'))
        self.add_converter(DurationConv('delay', parent='light'))
        self.add_converter(DurationConv('delayoff', 'number', readable=False))
        self.add_converter(DurationConv('transition', prop='duration', parent='light'))
        if ColorMode.BRIGHTNESS in self.color_modes:
            self.add_converter(BrightnessConv('brightness', prop='l', parent='light'))
        if ColorMode.COLOR_TEMP in self.color_modes:
            self.add_converter(ColorTempKelvin('color_temp', prop='ct', parent='light'))

    @property
    def color_modes(self):
        modes = {
            ColorMode.ONOFF,
        }
        if self.type == DeviceType.LIGHT_WITH_BRIGHTNESS:
            modes.add(ColorMode.BRIGHTNESS)
        if self.type == DeviceType.LIGHT_WITH_COLOR_TEMP:
            modes.add(ColorMode.BRIGHTNESS)
            modes.add(ColorMode.COLOR_TEMP)
        if self.type == DeviceType.LIGHT_WITH_COLOR:
            modes.add(ColorMode.BRIGHTNESS)
            modes.add(ColorMode.COLOR_TEMP)
            modes.add(ColorMode.HS)
        return modes


class SwitchPanelDevice(XDevice):
    def setup_converters(self):
        super().setup_converters()
        switches = self.switches
        if len(switches) == 1:
            self.add_converter(PropBoolConv('switch', 'switch', prop='1-sp'))
        else:
            for i, p in self.switches.items():
                self.add_converter(PropBoolConv(f'switch{i}', 'switch', prop=f'{i}-sp'))
        if '0-blp' in self.prop_params:
            self.add_converter(PropBoolConv('backlight', 'light', prop='0-blp'))

    @property
    def switches(self):
        lst = {}
        for i in range(1, 9):
            if (p := self.switch_power(i)) is None:
                continue
            lst[i] = p
        return lst

    def switch_power(self, index=1):
        return self.prop_params.get(f'{index}-sp')


class RelayDevice(SwitchPanelDevice):
    def setup_converters(self):
        super().setup_converters()
        switches = self.switches
        if len(switches) == 1:
            self.add_converter(PropBoolConv('switch', 'switch', prop='1-p'))
        else:
            for i, p in self.switches.items():
                self.add_converter(PropBoolConv(f'switch{i}', 'switch', prop=f'{i}-p'))

    def switch_power(self, index=1):
        return self.prop_params.get(f'{index}-p')


class ActionDevice(XDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converter(Converter('action', 'sensor'))


class SwitchSensorDevice(ActionDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converter(EventConv('panel.click'))
        self.add_converter(EventConv('panel.hold'))
        self.add_converter(EventConv('panel.release'))


class KnobDevice(SwitchSensorDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converter(EventConv('knob.spin'))


class MotionDevice(XDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converter(Converter('motion', 'binary_sensor'))
        self.add_converter(EventConv('motion.true'))
        self.add_converter(EventConv('motion.false'))
        if self.type in [DeviceType.MOTION_WITH_LIGHT]:
            self.add_converter(PropBoolConv('light', 'sensor', prop='level'))


class ContactDevice(XDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converter(Converter('contact', 'binary_sensor'))
        self.add_converter(EventConv('contact.open'))
        self.add_converter(EventConv('contact.close'))
