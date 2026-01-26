
from custom_components.yeelight_pro.core.converters.base import (
    Converter,
    BoolConv,
    MapConv,
    DurationConv,
    PropConv,
    PropBoolConv,
    PropMapConv,
    BrightnessConv,
    ColorTempKelvin,
    ColorRgbConv,
    EventConv,
    MotorConv,
    SceneConv,
)


class DummyDevice:
    """Простая заглушка XDevice, если где-то понадобится."""
    def __init__(self):
        self.prop_params = {}


def test_converter_encode_decode_basic():
    dev = DummyDevice()
    payload = {}

    conv = Converter("attr", prop="p")

    conv.decode(dev, payload, 123)
    assert payload["attr"] == 123

    payload = {}
    conv.encode(dev, payload, 456)
    assert payload["p"] == 456

    # read ничего не делает, если prop не задан
    payload = {}
    conv2 = Converter("x")
    conv2.read(dev, payload)
    assert payload == {}


def test_boolconv_encode_decode():
    dev = DummyDevice()
    payload = {}

    conv = BoolConv("flag", prop="f")

    conv.decode(dev, payload, 1)
    assert payload["flag"] is True

    payload = {}
    conv.encode(dev, payload, 0)
    assert payload["f"] is False


def test_mapconv_encode_decode_and_fallback():
    dev = DummyDevice()
    payload = {}

    conv = MapConv("mode", map={1: "cool", 2: "heat"})

    conv.decode(dev, payload, 1)
    assert payload["mode"] == "cool"

    # encode по значению
    payload = {}
    conv.encode(dev, payload, "heat")
    assert payload["mode"] == 2

    # если значение не найдено в map, но передан raw-ключ — он пройдёт как есть
    payload = {}
    conv.encode(dev, payload, 1)
    assert payload["mode"] == 1

    # если вообще ни ключ, ни значение — ничего не запишется
    payload = {}
    conv.encode(dev, payload, "unknown")
    assert payload == {}


def test_durationconv_encode_decode():
    dev = DummyDevice()
    conv = DurationConv("delay", readable=True, min=0, max=3600)

    payload = {}
    conv.decode(dev, payload, 5000)  # 5 секунд
    assert payload["delay"] == 5

    payload = {}
    conv.encode(dev, payload, 10)  # 10 секунд -> 10000 мс
    assert payload["delay"] == 10000

    # если readable=False — decode не должен писать значение
    conv2 = DurationConv("d2", readable=False)
    payload = {}
    conv2.decode(dev, payload, 5000)
    assert payload == {}


def test_prop_conv_and_subclasses_are_compatible():
    dev = DummyDevice()
    payload = {}

    conv = PropConv("attr", prop="p")
    conv.decode(dev, payload, 1)
    assert payload["attr"] == 1

    payload = {}
    conv.encode(dev, payload, 2)
    assert payload["p"] == 2

    # PropBoolConv наследует BoolConv и PropConv
    pb = PropBoolConv("flag", prop="f")
    payload = {}
    pb.decode(dev, payload, 1)
    assert payload["flag"] is True

    payload = {}
    pb.encode(dev, payload, False)
    assert payload["f"] is False

    # PropMapConv – тот же MapConv, но с PropConv
    pm = PropMapConv("mode", prop="m", map={1: "cool"})
    payload = {}
    pm.decode(dev, payload, 1)
    assert payload["mode"] == "cool"


def test_brightnessconv_encode_decode_clamps_and_scales():
    dev = DummyDevice()
    conv = BrightnessConv("brightness", prop="l", max=100.0)

    # decode: 0..100 -> 0..255
    payload = {}
    conv.decode(dev, payload, 50)
    assert payload["brightness"] == round(50 / 100 * 255)

    # clamp > max
    payload = {}
    conv.decode(dev, payload, 200)
    assert payload["brightness"] == 255

    # encode: 0..255 -> 0..100
    payload = {}
    conv.encode(dev, payload, 128)
    # обратная конвертация +/- разумная
    assert 0 <= payload["l"] <= 100

    # некорректное значение не роняет и записывает 0
    payload = {}
    conv.encode(dev, payload, "bad")
    assert payload["l"] == 0


def test_colortempkelvin_decode_and_encode_mired_and_kelvin():
    dev = DummyDevice()
    conv = ColorTempKelvin("color_temp", prop="ct", mink=2700, maxk=6500)

    payload = {}
    conv.decode(dev, payload, 4000)
    assert payload["color_temp"] == int(1_000_000 / 4000)
    assert payload["color_temp_kelvin"] == 4000

    # encode mired (например 250 -> 4000K)
    payload = {}
    conv.encode(dev, payload, 250)
    k = payload["ct"]
    assert 2700 <= k <= 6500

    # encode Kelvin за пределами -> кламп
    payload = {}
    conv.encode(dev, payload, 8000)
    assert payload["ct"] == 6500


def test_colorrgbconv_encode_decode_and_clamp():
    dev = DummyDevice()
    conv = ColorRgbConv("rgb_color", prop="c")

    # decode из int
    payload = {}
    conv.decode(dev, payload, 0x112233)
    assert payload["rgb_color"] == (0x11, 0x22, 0x33)

    # encode из tuple
    payload = {}
    conv.encode(dev, payload, (255, 128, 0))
    val = payload["c"]
    assert isinstance(val, int)
    assert (val >> 16) & 0xFF == 255
    assert (val >> 8) & 0xFF == 128
    assert val & 0xFF == 0

    # некорректное tuple -> 0
    payload = {}
    conv.encode(dev, payload, "bad")
    assert payload["c"] == 0


def test_eventconv_motion_true_and_panel_click_and_knob_spin():
    dev = DummyDevice()

    # motion.true
    conv_motion = EventConv("motion.true")
    payload = {}
    conv_motion.decode(dev, payload, {"x": 1})
    # decode ждёт value как dict и использует attr, но логика делится на key/val внутри
    # для теста используем decode_event в XDevice, тут проверяем только ветку motion/contact:
    # но напрямую attr='motion.true' -> key 'motion', val 'true'
    # поэтому вручную смоделируем:
    payload = {}
    conv_motion.attr = "motion.true"
    conv_motion.decode(dev, payload, {"foo": "bar"})
    # ключ 'motion' должен быть True
    assert payload["motion"] is True

    # panel.click
    conv_panel = EventConv("panel.click")
    payload = {}
    conv_panel.decode(dev, payload, {"key": 1, "count": 2})
    # ожидаем action button1_double
    assert payload["action"] == "button1_double"
    assert payload["event"] == "panel.click"
    assert payload["button"] == 1

    # knob.spin: найдёт первый ненулевой ключ
    conv_knob = EventConv("knob.spin")
    payload = {}
    conv_knob.decode(dev, payload, {"free_spin": 5})
    assert payload["action"] == "free_spin"
    assert payload["event"] == "knob.spin"


def test_motorconv_encode_decode():
    dev = DummyDevice()
    # readable=True -> decode пишет значение
    conv = MotorConv("motor", prop="m", readable=True)

    payload = {}
    conv.decode(dev, payload, "up")
    assert payload["motor"] == "up"

    payload = {}
    conv.encode(dev, payload, "down")
    assert payload["m"] == {
        "action": {
            "motorAdjust": {
                "type": "down",
            }
        }
    }


def test_sceneconv_has_node():
    node = {"id": 123, "n": "My Scene"}
    conv = SceneConv("scene_123", "button", node=node)

    assert conv.attr == "scene_123"
    assert conv.domain == "button"
    assert conv.node == node
