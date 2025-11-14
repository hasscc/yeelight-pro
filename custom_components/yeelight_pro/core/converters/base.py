from dataclasses import dataclass
from typing import Any, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from ..device import XDevice


@dataclass
class Converter:
    attr: str  # hass attribute
    domain: Optional[str] = None  # hass domain
    unit_of_measurement: Optional[str] = None  # unit, e.g., 'lx'
    device_class: Optional[str] = None  # device class, e.g., 'illuminance'

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
        # safe reverse lookup
        try:
            raw = next(k for k, v in self.map.items() if v == value)
        except StopIteration:
            # if HA passed the raw key already, keep it; otherwise ignore
            raw = value if value in self.map else None
        if raw is not None:
            super().encode(device, payload, raw)


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

    def decode(self, device, payload, value: int):
        try:
            v = max(0, min(int(self.max), int(value)))
        except Exception:
            v = 0
        payload[self.attr] = round(v / float(self.max) * 255)

    def encode(self, device, payload, value: float):
        try:
            v = max(0, min(255, int(value)))
        except Exception:
            v = 0
        dev_v = round(v / 255.0 * float(self.max))
        super().encode(device, payload, int(dev_v))


@dataclass
class ColorTempKelvin(PropConv):
    mink: int = 2700
    maxk: int = 6500

    def decode(self, device: "XDevice", payload: dict, value: int):
        k = int(value)
        payload[self.attr] = int(1_000_000 / max(1, k))   # mired for HA
        payload["color_temp_kelvin"] = k

    def encode(self, device, payload, value: int):
        """Accept mired or kelvin and send Kelvin to device."""
        try:
            v = int(value)
        except Exception:
            return
        if v <= 1000:  # likely mired from HA
            k = int(1_000_000 / max(1, v))
        else:          # likely Kelvin (e.g., your prestage service)
            k = v
        k = max(self.mink, min(self.maxk, k))
        super().encode(device, payload, k)  # send Kelvin


class ColorRgbConv(PropConv):
    def decode(self, device, payload, value: int):
        r = (value >> 16) & 0xFF
        g = (value >> 8) & 0xFF
        b = value & 0xFF
        payload[self.attr] = (r, g, b)

    def encode(self, device, payload, value: tuple):
        try:
            r, g, b = (int(value[0]), int(value[1]), int(value[2]))
        except Exception:
            r = g = b = 0
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        super().encode(device, payload, (r << 16) | (g << 8) | b)


@dataclass
class EventConv(Converter):
    event: str = ''

    def decode(self, device: "XDevice", payload: dict, value: dict):
        key, val = self.attr, None
        if '.' in self.attr:
            key, val = self.attr.split('.', 1)
        if key in ['motion', 'contact']:
            payload.update({
                key: val in ['true', 'open'],
                **value,
            })
        elif self.attr in ['panel.click', 'panel.hold', 'panel.release', 'keyClick']:
            key = value.get('key', '')
            cnt = value.get('count', None)
            btn = f'button{key}'
            if cnt is not None:
                typ = {1: 'single', 2: 'double', 3: 'triple'}.get(cnt, val)
            else:
                typ = val
            if typ:
                btn += f'_{typ}'
            payload.update({
                'action': btn,
                'event': self.attr,
                'button': key,
                **value,
            })
        elif self.attr in ['knob.spin']:
            keys = ['free_spin', 'hold_spin']
            keys += [ f"{i}-free_spin" for i in range(1,5)] # For E-Series Knob Support
            for typ in keys:
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
class MotorConv(Converter):
    readable: bool = False

    def decode(self, device: "XDevice", payload: dict, value: Any):
        if self.readable and value is not None:
            payload[self.attr] = value

    def encode(self, device: "XDevice", payload: dict, value: Any):
        if value is not None:
            super().encode(device, payload, {
                'action': {
                    'motorAdjust': {
                        'type': value,
                    },
                },
            })


@dataclass
class SceneConv(Converter):
    node: dict = None
