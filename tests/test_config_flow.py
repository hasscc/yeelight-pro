import pytest

from homeassistant import data_entry_flow
from homeassistant.const import CONF_HOST

from custom_components.yeelight_pro.config_flow import (
    YeelightProConfigFlow,
    OptionsFlowHandler,
)
from custom_components.yeelight_pro.core.const import (
    DOMAIN,
    CONF_PID,
    PID_GATEWAY,
)


class Hass:
    """Минимальный hass для конфиг-флоу.

    ConfigFlow использует:
    - hass.data[DOMAIN]
    - hass.config_entries.flow.async_progress_by_handler(...)
    """

    class _DummyFlow:
        def async_progress_by_handler(
            self,
            handler,
            include_uninitialized=False,
            match_context=None,
        ):
            # В тестах других параллельных flow нет
            return []

    class _DummyConfigEntries:
        def __init__(self):
            self.flow = Hass._DummyFlow()

    def __init__(self):
        self.data = {DOMAIN: {}}
        self.config_entries = Hass._DummyConfigEntries()


class FakeGateway:
    """Фейковый gateway с настраиваемым результатом check_available()."""

    def __init__(self, error=None):
        self._error = error

    async def check_available(self):
        # В реальном коде метод возвращает None при успехе
        # и Exception / строку при ошибке. Мы повторяем этот контракт.
        return self._error


@pytest.mark.asyncio
async def test_config_flow_user_success(monkeypatch):
    """Успешный сценарий: gateway доступен, создаётся entry."""
    hass = Hass()
    flow = YeelightProConfigFlow()
    flow.hass = hass
    flow.context = {}  # <--- делаем контекст обычным dict

    # Замокаем async_set_unique_id, чтобы не лезть в self.context (mappingproxy)
    async def fake_set_unique_id(self, unique_id, raise_on_progress: bool = True):
        self._test_unique_id = unique_id
        return None

    monkeypatch.setattr(
        YeelightProConfigFlow,
        "async_set_unique_id",
        fake_set_unique_id,
        raising=True,
    )

    async def fake_get_gateway_from_config(hass_, cfg, renew=False):
        # Эмулируем успешное подключение — ошибок нет
        return FakeGateway(error=None)

    monkeypatch.setattr(
        "custom_components.yeelight_pro.config_flow.get_gateway_from_config",
        fake_get_gateway_from_config,
    )

    user_input = {
        CONF_HOST: "1.2.3.4",
        CONF_PID: PID_GATEWAY,
    }

    result = await flow.async_step_user(user_input=user_input)

    # Должен создаться entry
    assert result["type"] == "create_entry"
    # Заголовок — host (если он задан)
    assert result["title"] == user_input[CONF_HOST]
    # Данные из user_input попадают в entry как есть
    assert result["data"][CONF_HOST] == user_input[CONF_HOST]
    assert result["data"][CONF_PID] == user_input[CONF_PID]


@pytest.mark.asyncio
async def test_config_flow_user_cannot_access(monkeypatch):
    """Ошибка доступа к gateway: форма с errors['base'] == 'cannot_access'."""
    hass = Hass()
    flow = YeelightProConfigFlow()
    flow.hass = hass
    flow.context = {}  # <--- тоже подменяем context на mutable dict

    # Тот же мок async_set_unique_id, чтобы не падать на mappingproxy
    async def fake_set_unique_id(self, unique_id, raise_on_progress: bool = True):
        self._test_unique_id = unique_id
        return None

    monkeypatch.setattr(
        YeelightProConfigFlow,
        "async_set_unique_id",
        fake_set_unique_id,
        raising=True,
    )

    async def fake_get_gateway_from_config(hass_, cfg, renew=False):
        # Эмулируем недоступный gateway: check_available вернёт Exception
        return FakeGateway(error=Exception("boom"))

    monkeypatch.setattr(
        "custom_components.yeelight_pro.config_flow.get_gateway_from_config",
        fake_get_gateway_from_config,
    )

    user_input = {
        CONF_HOST: "1.2.3.4",
        CONF_PID: PID_GATEWAY,
    }

    result = await flow.async_step_user(user_input=user_input)

    # При ошибке должен быть показан form step "user" с ошибкой cannot_access
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"]["base"] == "cannot_access"


# ---------------------------------------------------------------------------
# Новый тест: _abort_if_unique_id_configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_flow_abort_if_unique_id_configured(monkeypatch):
    """Проверяем, что при уже сконфигурированном unique_id вызывается abort."""
    hass = Hass()
    flow = YeelightProConfigFlow()
    flow.hass = hass
    flow.context = {}

    async def fake_set_unique_id(self, unique_id, raise_on_progress: bool = True):
        self._test_unique_id = unique_id
        return None

    called = {"abort": False}

    def fake_abort(self):
        called["abort"] = True
        # правильный класс исключения
        raise data_entry_flow.AbortFlow("already_configured")

    # get_gateway_from_config вообще не должен вызываться в этом сценарии
    monkeypatch.setattr(
        "custom_components.yeelight_pro.config_flow.get_gateway_from_config",
        lambda *a, **k: pytest.fail("get_gateway_from_config must not be called"),
    )

    monkeypatch.setattr(
        YeelightProConfigFlow,
        "async_set_unique_id",
        fake_set_unique_id,
        raising=True,
    )
    monkeypatch.setattr(
        YeelightProConfigFlow,
        "_abort_if_unique_id_configured",
        fake_abort,
        raising=True,
    )

    user_input = {
        CONF_HOST: "1.2.3.4",
        CONF_PID: PID_GATEWAY,
    }

    # и тут тоже используем data_entry_flow.AbortFlow
    with pytest.raises(data_entry_flow.AbortFlow):
        await flow.async_step_user(user_input=user_input)

    assert called["abort"] is True


# ---------------------------------------------------------------------------
# Тесты OptionsFlowHandler.async_step_init
# ---------------------------------------------------------------------------


class FakeConfigEntry:
    def __init__(self, entry_id="entry1", data=None, options=None):
        self.entry_id = entry_id
        self.data = data or {}
        self.options = options or {}


class FakeConfigEntriesForOptions:
    def __init__(self, entry: FakeConfigEntry):
        self._entry = entry
        self.updated = None

    def async_get_entry(self, entry_id):
        assert entry_id == self._entry.entry_id
        return self._entry

    def async_update_entry(self, entry, data=None, **kwargs):
        self.updated = {"entry": entry, "data": data, "kwargs": kwargs}


class HassWithOptions:
    def __init__(self, entry: FakeConfigEntry):
        self.data = {DOMAIN: {}}
        self.config_entries = FakeConfigEntriesForOptions(entry)


@pytest.mark.asyncio
async def test_options_flow_init_success(monkeypatch):
    """Успешное изменение host в OptionsFlowHandler."""
    entry = FakeConfigEntry(
        entry_id="entry1",
        data={CONF_HOST: "1.2.3.4"},
        options={"opt": "val"},
    )
    hass = HassWithOptions(entry)

    handler = OptionsFlowHandler(entry)
    handler.hass = hass
    handler.context = {}

    async def fake_get_gateway_from_config(hass_, cfg, renew=False):
        # Доступен без ошибок
        return FakeGateway(error=None)

    monkeypatch.setattr(
        "custom_components.yeelight_pro.config_flow.get_gateway_from_config",
        fake_get_gateway_from_config,
    )

    user_input = {
        CONF_HOST: "2.3.4.5",
    }

    result = await handler.async_step_init(user_input=user_input)

    # Создана entry с keepalive опцией
    assert result["type"] == "create_entry"
    assert result["title"] == ""
    assert result["data"] == {"keepalive": 30}

    # Проверяем, что конфиг-энтри обновился
    updated = hass.config_entries.updated
    assert updated is not None
    assert updated["entry"] is entry
    assert updated["data"][CONF_HOST] == "2.3.4.5"
    # старые поля из data сохраняются, если были
    # (в данном тесте их нет, кроме host)


@pytest.mark.asyncio
async def test_options_flow_init_cannot_access(monkeypatch):
    """При ошибке подключения в OptionsFlowHandler возвращается форма с ошибкой."""
    entry = FakeConfigEntry(
        entry_id="entry1",
        data={CONF_HOST: "1.2.3.4"},
        options={},
    )
    hass = HassWithOptions(entry)

    handler = OptionsFlowHandler(entry)
    handler.hass = hass
    handler.context = {}

    async def fake_get_gateway_from_config(hass_, cfg, renew=False):
        # Недоступен, возвращаем ошибку
        return FakeGateway(error=Exception("boom"))

    monkeypatch.setattr(
        "custom_components.yeelight_pro.config_flow.get_gateway_from_config",
        fake_get_gateway_from_config,
    )

    user_input = {
        CONF_HOST: "2.3.4.5",
    }

    result = await handler.async_step_init(user_input=user_input)

    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert result["errors"]["base"] == "cannot_access"
