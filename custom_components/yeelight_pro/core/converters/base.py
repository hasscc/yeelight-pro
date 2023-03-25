from dataclasses import dataclass
from typing import Any, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from ..device import XDevice


@dataclass
class Converter:
    attr: str  # hass attribute
    domain: Optional[str] = None  # hass domain

    prop: Optional[str] = None
    parent: Optional[str] = None

    enabled: Optional[bool] = True  # support: True, False, None (lazy setup)
    poll: bool = False  # hass should_poll

    # don't init with dataclass because no type:
    childs = None  # set or dict? of children attributes

    def decode(self, device: "XDevice", payload: dict, value: Any):
        payload[self.attr] = value

    def encode(self, device: "XDevice", payload: dict, value: Any):
        payload[self.prop or self.attr] = value

    def read(self, device: "XDevice", payload: dict):
        if not self.prop:
            return


class BoolConv(Converter):
    def decode(self, device: "XDevice", payload: dict, value: Union[bool, int]):
        payload[self.attr] = bool(value)

    def encode(self, device: "XDevice", payload: dict, value: Union[bool, int]):
        super().encode(device, payload, bool(value))


@dataclass
class MapConv(Converter):
    map: dict = None

    def decode(self, device: "XDevice", payload: dict, value: Union[str, int]):
        payload[self.attr] = self.map.get(value)

    def encode(self, device: "XDevice", payload: dict, value: Any):
        value = next(k for k, v in self.map.items() if v == value)
        super().encode(device, payload, value)


@dataclass
class DurationConv(Converter):
    min: float = 0
    max: float = 3600
    step: float = 1
    readable: bool = True

    def decode(self, device: "XDevice", payload: dict, value: Union[int, float, str, None]):
        if self.readable and value is not None:
            payload[self.attr] = int(float(value) / 1000)

    def encode(self, device: "XDevice", payload: dict, value: Union[int, float, str, None]):
        if value is not None:
            super().encode(device, payload, int(float(value) * 1000))


class PropConv(Converter):
    pass


class PropBoolConv(BoolConv, PropConv):
    pass


class PropMapConv(MapConv, PropConv):
    pass


@dataclass
class BrightnessConv(PropConv):
    max: float = 100.0

    def decode(self, device: "XDevice", payload: dict, value: int):
        payload[self.attr] = round(value / self.max * 255.0)

    def encode(self, device: "XDevice", payload: dict, value: float):
        value = round(value / 255.0 * self.max)
        super().encode(device, payload, int(value))


@dataclass
class ColorTempKelvin(PropConv):
    # 2700..6500 => 370..153
    mink: int = 2700
    maxk: int = 6500

    def decode(self, device: "XDevice", payload: dict, value: int):
        """Convert degrees kelvin to mired shift."""
        payload[self.attr] = int(1000000.0 / value)
        payload['color_temp_kelvin'] = value

    def encode(self, device: "XDevice", payload: dict, value: int):
        value = int(1000000.0 / value)
        if value < self.mink:
            value = self.mink
        if value > self.maxk:
            value = self.maxk
        super().encode(device, payload, value)


@dataclass
class EventConv(Converter):
    event: str = ''

    def decode(self, device: "XDevice", payload: dict, value: dict):
        key, val = self.attr.split('.', 1)
        if key in ['motion', 'contact']:
            payload.update({
                key: val in ['true', 'open'],
                **value,
            })
        elif self.attr in ['panel.click', 'panel.hold', 'panel.release']:
            key = value.get('key', '')
            btn = f'button{key}'
            typ = {1: 'single', 2: 'double'}.get(value.get('count'), val)
            if typ:
                btn += f'_{typ}'
            payload.update({
                'action': btn,
                'event': self.attr,
                'button': key,
                **value,
            })
        elif self.attr in ['knob.spin']:
            for typ in ['free_spin', 'hold_spin']:
                if value.get(typ) in [None, 0]:
                    continue
                payload.update({
                    'action': typ,
                    'event': self.attr,
                    **value,
                })

    def encode(self, device: "XDevice", payload: dict, value: dict):
        super().encode(device, payload, value)


@dataclass
class SceneConv(Converter):
    node: dict = None
