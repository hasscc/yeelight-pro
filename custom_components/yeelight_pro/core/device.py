import asyncio
import logging
from enum import IntEnum
from .converters.base import *

from typing import Dict, List, TYPE_CHECKING

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
    ILLUMINATION_SENSOR = 135
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
        self.cids = node.get('cids')
        self.ch_num = node.get('ch_num')
        self.prop = {}
        self.entities: Dict[str, "XEntity"] = {}
        self.gateways: List["ProGateway"] = []
        self.converters = {}
        self.setup_converters()

    def setup_converters(self):
        pass

    def add_converter(self, conv: Converter):
        self.converters[conv.attr] = conv

    def add_converters(self, *args: Converter):
        for conv in args:
            self.add_converter(conv)

    @staticmethod
    async def from_node(gateway: "ProGateway", node: dict):
        if node.get('nt') not in [NodeType.MESH, NodeType.MRSH_GROUP, NodeType.SCENE]:
            return None
        if not (nid := node.get('id')):
            return None
        if dvc := gateway.devices.get(nid):
            if n := node.get('n'):
                dvc.name = n
        else:
            dvc = XDevice(node)
            if dvc.nt in [NodeType.SCENE]:
                if isinstance(gateway.device, GatewayDevice):
                    await gateway.device.add_scene(node)
                return gateway.device
            elif dvc.type in DEVICE_TYPE_LIGHTS:
                dvc = LightDevice(node)
            elif dvc.type in [DeviceType.SWITCH_PANEL]:
                dvc = SwitchPanelDevice(node)
            elif dvc.type in [DeviceType.RELAY_DOUBLE]:
                dvc = RelayDoubleDevice(node)
            elif dvc.type in [DeviceType.SWITCH_SENSOR]:
                # Add support for the E-Series Knob as its DeviceType ID is 128.
                dvc = KnobDevice(node)                  
            elif dvc.type in [DeviceType.KNOB]:
                dvc = KnobDevice(node)
            elif dvc.type in [DeviceType.MOTION_SENSOR, DeviceType.MOTION_WITH_LIGHT]:
                dvc = MotionDevice(node)
            elif dvc.type in [DeviceType.MAGNET_SENSOR]:
                dvc = ContactDevice(node)
            elif dvc.type in [DeviceType.CURTAIN]:
                dvc = CoverDevice(node)
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

    async def prop_changed(self, data: dict):
        has_new = False
        for k in data.keys():
            if k not in self.prop:
                has_new = True
                break
        self.prop.update(data)
        if has_new:
            self.setup_converters()
            await self.setup_entities()
        self.update(self.decode(data))

    async def event_fired(self, data: dict):
        decoded = self.decode_event(data)
        self.update(decoded)
        _LOGGER.debug('Event fired: %s', [data, decoded])

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
        if not self.converters:
            _LOGGER.warning('Device has none converters: %s', [type(self), self.id])
        for conv in self.converters.values():
            domain = conv.domain
            if domain is None:
                continue
            if conv.attr in self.entities:
                continue
            await asyncio.sleep(1)  # wait for setup
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
        """Decode device event for HA."""
        payload = {}
        event = data.get('value') or data.get('type')
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
        cmd = kwargs.pop('method', 'gateway_set.prop')
        node = {
            'id': self.id,
            'nt': self.nt,
            **kwargs,
        }
        return await self.gateway.send(cmd, nodes=[node])


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
        if ColorMode.RGB in self.color_modes:
            self.add_converter(ColorRgbConv('rgb_color', prop='c', parent='light'))
        if self.type == DeviceType.LIGHT_WITH_ZOOM_CT:
            self.add_converter(PropConv('angel', 'number'))

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
            modes.add(ColorMode.RGB)
        return modes


class ActionDevice(XDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converter(Converter('action', 'sensor'))


class SwitchSensorDevice(ActionDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converters(
            EventConv('panel.click'),
            EventConv('panel.hold'),
            EventConv('panel.release'),
        )


class RelayDevice(XDevice):
    def setup_converters(self):
        super().setup_converters()
        switches = self.switches
        if len(switches) == 1:
            self.add_converter(PropBoolConv('switch', 'switch', prop='1-p'))
        else:
            for i, p in self.switches.items():
                self.add_converter(PropBoolConv(f'switch{i}', 'switch', prop=f'{i}-p'))

    @property
    def switches(self):
        lst = {}
        for i in range(1, 9):
            if (p := self.switch_power(i)) is None:
                continue
            lst[i] = p
        return lst

    def switch_power(self, index=1):
        return self.prop_params.get(f'{index}-p')


class SwitchPanelDevice(RelayDevice, SwitchSensorDevice):
    def setup_converters(self):
        super().setup_converters()
        SwitchSensorDevice.setup_converters(self)

        switches = self.switches
        if len(switches) == 1:
            self.add_converter(PropBoolConv('switch', 'switch', prop='1-sp'))
        else:
            for i, p in self.switches.items():
                self.add_converter(PropBoolConv(f'switch{i}', 'switch', prop=f'{i}-sp'))
        if '0-blp' in self.prop_params:
            self.add_converter(PropBoolConv('backlight', 'light', prop='0-blp'))

    def switch_power(self, index=1):
        return self.prop_params.get(f'{index}-sp')


class RelayDoubleDevice(XDevice):
    def setup_converters(self):
        self.add_converters(
            PropBoolConv('switch1', 'switch', prop='1-p'),
            PropBoolConv('switch2', 'switch', prop='2-p')
        )


class KnobDevice(SwitchSensorDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converter(EventConv('knob.spin'))


class MotionDevice(XDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converter(Converter('motion', 'binary_sensor'))
        self.add_converters(PropBoolConv('motion', 'binary_sensor', prop="mv"))
        self.add_converter(EventConv('motion.true'))
        self.add_converter(EventConv('motion.false'))
        if self.type in [DeviceType.MOTION_WITH_LIGHT]:
            self.add_converter(PropConv('light', 'sensor', prop='level'))
        
        # This is a presence sensor with a built-in light sensor. Its type is still defined as 129,
        # so we can only temporarily distinguish it by the `cids` value.
        if 73 in self.cids:
            # Regular presence sensors use cids = [9], while ceiling-mounted sensors with light detection use cids = [73].
            self.add_converter(PropConv(
                    attr='luminance',
                    domain='sensor',
                    prop='luminance',
                    unit_of_measurement='lx',
                    device_class='illuminance'
            ))

            # Currently, `approach.true` and `approach.false` seem to behave the same as `mv` (motion).


class ContactDevice(XDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converter(Converter('contact', 'binary_sensor'))
        self.add_converter(EventConv('contact.open'))
        self.add_converter(EventConv('contact.close'))


class CoverDevice(XDevice):
    def setup_converters(self):
        super().setup_converters()
        self.add_converters(
            MotorConv('motor', 'cover'),
            PropConv('position', parent='motor', prop='tp'),
            PropConv('current_position', parent='motor', prop='cp'),
        )
        if 'rs' in self.prop_params:
            self.add_converter(PropBoolConv('reverse', 'switch', prop='rs'))


class WifiPanelDevice(RelayDoubleDevice):
    def __init__(self, node: dict):
        super().__init__({
            **node,
            'type': 'wifi_panel',
        })
        self.name = 'Yeelight Wifi Panel'

    async def set_prop(self, **kwargs):
        kwargs['method'] = 'device_set.prop'
        return await super().set_prop(**kwargs)

    def entity_id(self, conv: Converter):
        return f'{conv.domain}.yp_{self.id}_{conv.attr}'

    def setup_converters(self):
        super().setup_converters()
        self.add_converter(Converter('action', 'sensor'))
        self.add_converter(EventConv('keyClick'))
