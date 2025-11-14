import pytest
from homeassistant.const import CONF_HOST

import custom_components.yeelight_pro as yp
from custom_components.yeelight_pro.core.const import DOMAIN, CONF_GATEWAYS
from custom_components.yeelight_pro.core.gateway import ProGateway


class FakeBus:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def async_fire(self, event_name, data=None):
        self.events.append((event_name, data))


class FakeServices:
    def async_register(self, *args, **kwargs):
        # Регистрация сервисов нам в тестах не важна
        return None


class FakeHass:
    def __init__(self):
        self.bus = FakeBus()
        self.services = FakeServices()
        self.data = {DOMAIN: {CONF_GATEWAYS: {}}}


class FakeGateway(ProGateway):
    """Фейковый ProGateway, без реальных подключений."""

    def __init__(self, host: str = "1.2.3.4"):
        # НЕ вызываем super().__init__, чтобы не трогать реальную логику
        self.host = host
        self.sent: list[tuple[str, dict | None, bool]] = []
        self.on_message = None  # будет переписан в тесте

    async def send(self, method, params=None, wait_result=True, **kwargs):
        self.sent.append((method, params, wait_result))
        return {"result": "ok"}


@pytest.mark.asyncio
async def test_async_send_command_no_throw(monkeypatch):
    """Проверяем, что при throw=False уведомление не создаётся и событие шлётся."""

    hass = FakeHass()

    # Заглушаем admin-сервис, чтобы __init__ не упал
    monkeypatch.setattr(yp, "async_register_admin_service", lambda *a, **k: None)

    # Перехватываем persistent_notification.async_create
    notifications = []

    def fake_notify(*args, **kwargs):
        notifications.append((args, kwargs))

    monkeypatch.setattr(yp.persistent_notification, "async_create", fake_notify)

    # Кладём фейковый gateway в hass.data
    gw = FakeGateway()
    hass.data[DOMAIN][CONF_GATEWAYS]["gw1"] = gw

    services = yp.ComponentServices(hass)

    class Call:
        data = {
            CONF_HOST: "1.2.3.4",
            "method": "test_method",
            "params": {"x": 1},
            # Явно ставим throw=False — хотим, чтобы уведомление не создавалось
            "throw": False,
        }

    result = await services.async_send_command(Call())

    # send() был вызван с нужными аргументами
    assert gw.sent == [("test_method", {"x": 1}, True)]
    # вернулся результат из gateway.send
    assert result == {"result": "ok"}

    # уведомлений не создавалось
    assert notifications == []

    # событие на шине есть и содержит нужные поля
    assert len(hass.bus.events) == 1
    event_name, event_data = hass.bus.events[0]
    assert event_name == f"{DOMAIN}.send_command"
    assert event_data["host"] == "1.2.3.4"
    assert event_data["method"] == "test_method"
    assert event_data["params"] == {"x": 1}
    assert event_data["result"] == {"result": "ok"}


@pytest.mark.asyncio
async def test_async_mock_incoming_message_calls_on_message(monkeypatch):
    """Проверяем, что mock_incoming_message вызывает gtw.on_message с байтами."""

    hass = FakeHass()

    monkeypatch.setattr(yp, "async_register_admin_service", lambda *a, **k: None)

    # Заглушка уведомлений, чтобы не мешали в случае ошибок
    monkeypatch.setattr(yp.persistent_notification, "async_create", lambda *a, **k: None)

    gw = FakeGateway()
    hass.data[DOMAIN][CONF_GATEWAYS]["gw1"] = gw

    services = yp.ComponentServices(hass)

    called: dict[str, bytes] = {}

    async def fake_on_message(msg: bytes):
        called["msg"] = msg

    # Переписываем on_message на нашу корутину
    gw.on_message = fake_on_message

    valid_json = (
        '{"id": 8218, "method": "gateway_post.event", '
        '"nodes": [{"params": {}, "value": "motion.false", "id": 301809111, "nt": 2}]}'
    )

    class Call:
        data = {
            CONF_HOST: "1.2.3.4",
            "message": valid_json,
        }

    await services.async_mock_incoming_message(Call())

    # on_message должен быть вызван и получить байты utf-8
    assert called["msg"] == valid_json.encode("utf-8")
