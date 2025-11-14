import types
import pytest

from custom_components.yeelight_pro import (
    async_setup,
    async_add_setuper,
    ComponentServices,
)
from custom_components.yeelight_pro.core.const import (
    DOMAIN,
    CONF_GATEWAYS,
)
from custom_components.yeelight_pro.core.gateway import ProGateway
from homeassistant.const import CONF_HOST


# ---------- Вспомогательные заглушки ----------


class FakeDiscovery:
    def __init__(self):
        self.calls = []

    async def async_load_platform(self, domain, component, config, discovery_info=None):
        self.calls.append((domain, component, config, discovery_info))


class FakeHassForSetup:
    """Минимальный hass для теста async_setup."""

    def __init__(self):
        self.data = {}
        self.helpers = types.SimpleNamespace(discovery=FakeDiscovery())


class FakeServices:
    def __init__(self):
        self.registered = []

    def async_register(self, domain, service, handler, schema=None):
        self.registered.append((domain, service, handler, schema))


class FakeBus:
    def __init__(self):
        self.events = []

    def async_fire(self, event_type, event_data):
        self.events.append((event_type, event_data))


class FakeHassForComponent:
    """Hass, достаточный для ComponentServices / mock_incoming_message."""

    def __init__(self):
        self.data = {DOMAIN: {CONF_GATEWAYS: {}}}
        self.services = FakeServices()
        self.bus = FakeBus()


class FakeCall:
    def __init__(self, data: dict):
        self.data = data


# ---------- Тест async_setup ----------


@pytest.mark.asyncio
async def test_async_setup_creates_gateways_and_loads_platforms(monkeypatch):
    """Проверяем, что async_setup создаёт gateway и поднимает платформы."""

    hass = FakeHassForSetup()
    created_gateway = []

    class FakeGateway:
        def __init__(self, host, **kwargs):
            self.host = host
            self.started = False
            created_gateway.append(self)

        async def start(self):
            self.started = True

    async def fake_get_gateway_from_config(hass_, cfg, renew=False):
        return FakeGateway(cfg[CONF_HOST])

    # Подменяем get_gateway_from_config и ComponentServices,
    # чтобы не тянуть реальные зависимости HA.
    monkeypatch.setattr(
        "custom_components.yeelight_pro.get_gateway_from_config",
        fake_get_gateway_from_config,
        raising=True,
    )

    class DummyComponentServices:
        def __init__(self, hass_):
            self.hass = hass_

    monkeypatch.setattr(
        "custom_components.yeelight_pro.ComponentServices",
        DummyComponentServices,
        raising=True,
    )

    hass_config = {
        DOMAIN: {
            CONF_GATEWAYS: [
                {CONF_HOST: "1.2.3.4"},
            ],
        },
    }

    result = await async_setup(hass, hass_config)
    assert result is True

    # В hass.data должен появиться gateway, привязанный к host
    assert DOMAIN in hass.data
    assert CONF_GATEWAYS in hass.data[DOMAIN]
    assert hass.data[DOMAIN][CONF_GATEWAYS]["1.2.3.4"] is created_gateway[0]

    # Проверяем, что все платформы были переданы в discovery.async_load_platform
    from custom_components.yeelight_pro.core.const import SUPPORTED_DOMAINS

    called_domains = [c[0] for c in hass.helpers.discovery.calls]
    for dom in SUPPORTED_DOMAINS:
        assert dom in called_domains

    # Gateway должен быть стартован
    assert created_gateway[0].started is True


# ---------- Тест async_add_setuper ----------


@pytest.mark.asyncio
async def test_async_add_setuper_adds_setup_when_gateway_is_progateway(monkeypatch):
    """Проверяем, что async_add_setuper вызывает add_setup у ProGateway."""

    hass = object()  # hass в get_gateway_from_config нам не важен

    captured = {}

    class FakeProGateway(ProGateway):
        def __init__(self):
            super().__init__("1.2.3.4")
            self.setups = {}

        def add_setup(self, domain, handler):
            captured["domain"] = domain
            captured["handler"] = handler

    async def fake_get_gateway_from_config(hass_, cfg, renew=False):
        return FakeProGateway()

    monkeypatch.setattr(
        "custom_components.yeelight_pro.get_gateway_from_config",
        fake_get_gateway_from_config,
        raising=True,
    )

    async def dummy_setuper(device, conv):
        pass

    config = {"some": "config"}

    await async_add_setuper(hass, config, "light", dummy_setuper)

    assert captured["domain"] == "light"
    assert captured["handler"] is dummy_setuper


# ---------- Тест async_mock_incoming_message (невалидный JSON) ----------


@pytest.mark.asyncio
async def test_async_mock_incoming_message_invalid_json_creates_notification(monkeypatch):
    """
    Если message нельзя распарсить ни как JSON, ни как literal_eval,
    должен создаваться persistent_notification и метод возвращает False.
    """
    hass = FakeHassForComponent()
    gw = ProGateway("1.2.3.4")
    hass.data[DOMAIN][CONF_GATEWAYS][gw.host] = gw

    # Подменяем async_register_admin_service, чтобы конструктор ComponentServices не упал
    monkeypatch.setattr(
        "custom_components.yeelight_pro.async_register_admin_service",
        lambda *a, **k: None,
        raising=True,
    )

    # Подменяем persistent_notification.async_create, чтобы отловить вызов
    created = {}

    def fake_notification_create(hass_, message, title=None, notification_id=None):
        created["hass"] = hass_
        created["message"] = message
        created["title"] = title
        created["notification_id"] = notification_id

    monkeypatch.setattr(
        "custom_components.yeelight_pro.persistent_notification.async_create",
        fake_notification_create,
        raising=True,
    )

    services = ComponentServices(hass)

    call = FakeCall(
        {
            CONF_HOST: "1.2.3.4",
            "message": "not-a-json-and-not-a-dict",  # гарантированно не распарсится
        }
    )

    result = await services.async_mock_incoming_message(call)

    assert result is False
    # Убедимся, что нотификация создалась
    assert created["hass"] is hass
    assert "Format error" in created["message"]
    assert created["title"] == "Yeelight Pro mock incoming message"
    assert created["notification_id"].endswith("-debug")