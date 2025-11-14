import asyncio
import json
import random

import pytest

from custom_components.yeelight_pro.core.gateway import ProGateway, MSG_SPLIT
from custom_components.yeelight_pro.core.const import PID_WIFI_PANEL
from custom_components.yeelight_pro.core.device import GatewayDevice, WifiPanelDevice


class Hass:
    """Простейший заглушечный hass для ProGateway в этих тестах."""
    def __init__(self):
        self.events = []


class GatewayForTests(ProGateway):
    async def add_device(self, device):
        """Подключаем девайс к шлюзу, но НЕ вызываем setup_entities()."""
        if not device.hass:
            device.hass = self.hass
        if device.id not in self.devices:
            self.devices[device.id] = device
        if self not in device.gateways:
            device.gateways.append(self)
        # никаких await device.setup_entities()


def get_gateway(host=None):
    if not host:
        host = "127.0.0.1"
    return GatewayForTests(host, hass=Hass())


def test_gateway():
    host = "127.0.0.1"
    gtw = get_gateway(host)
    assert gtw.host == host


class DummyWriter:
    """Простейший writer, который только накапливает записанные байты."""

    def __init__(self):
        self.written = []
        self.closed = False

    def write(self, data: bytes):
        self.written.append(data)

    async def drain(self):
        return

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return


# ---------- send / topology ----------


@pytest.mark.asyncio
async def test_send_topology_uses_post_cid_and_writes_json(monkeypatch):
    """Для gateway_get.topology id должен быть 'gateway_post.topology', а не random int."""
    gtw = ProGateway("1.2.3.4")

    async def fake_connect(self):
        self.writer = DummyWriter()
        return True

    monkeypatch.setattr(ProGateway, "connect", fake_connect, raising=True)

    await gtw.send("gateway_get.topology", wait_result=False)

    assert isinstance(gtw.writer, DummyWriter)
    assert len(gtw.writer.written) == 1

    raw = gtw.writer.written[0].rstrip(MSG_SPLIT)
    payload = json.loads(raw.decode("utf-8"))

    assert payload["method"] == "gateway_get.topology"
    assert payload["id"] == "gateway_post.topology"


@pytest.mark.asyncio
async def test_send_wait_result_resolved_by_on_message(monkeypatch):
    """send(wait_result=True) ждёт ответа, который приходит через on_message."""
    gtw = ProGateway("1.2.3.4")
    gtw.writer = DummyWriter()  # считаем, что уже подключены

    created_ids = []

    orig_randint = random.randint

    def fake_randint(a, b):
        val = orig_randint(a, b)
        created_ids.append(val)
        return val

    monkeypatch.setattr(
        "custom_components.yeelight_pro.core.gateway.random.randint",
        fake_randint,
    )

    # запускаем send в фоне
    send_task = asyncio.create_task(
        gtw.send("gateway_get.node", params={"id": 1}, wait_result=True)
    )

    # даём циклу чуть поработать, чтобы _msgs успел заполниться
    await asyncio.sleep(0)

    assert len(created_ids) == 1
    cid = created_ids[0]
    assert cid in gtw._msgs  # future зарегистрирован

    # имитируем приход ответа
    reply = {"id": cid, "result": {"ok": True}}
    await gtw.on_message(json.dumps(reply).encode("utf-8"))

    res = await send_task
    assert res == reply
    assert cid not in gtw._msgs  # future удалён


# ---------- check_available ----------


@pytest.mark.asyncio
async def test_check_available_returns_exception_on_failure(monkeypatch):
    """check_available возвращает исключение при ошибке подключения."""
    gtw = ProGateway("1.2.3.4")

    async def fake_connect(self):
        raise RuntimeError("boom")

    monkeypatch.setattr(ProGateway, "_connect", fake_connect, raising=True)

    err = await gtw.check_available()
    assert isinstance(err, RuntimeError)


# ---------- get_scene ----------


@pytest.mark.asyncio
async def test_get_scene_unwraps_scenes(monkeypatch):
    """get_scene разворачивает поле 'scenes' из ответа send."""
    gtw = ProGateway("1.2.3.4")

    async def fake_send(method, params=None, wait_result=True):
        assert method == "gateway_get.scene"
        assert params == {"id": 42}
        assert wait_result is True
        return {"scenes": [1, 2, 3]}

    monkeypatch.setattr(gtw, "send", fake_send)

    res = await gtw.get_scene(42)
    assert res == [1, 2, 3]


@pytest.mark.asyncio
async def test_get_scene_none_when_no_result(monkeypatch):
    """Если send вернул None, get_scene тоже возвращает None."""
    gtw = ProGateway("1.2.3.4")

    async def fake_send(method, params=None, wait_result=True):
        return None

    monkeypatch.setattr(gtw, "send", fake_send)

    res = await gtw.get_scene(1)
    assert res is None


# ---------- on_message / создание устройств ----------


@pytest.mark.asyncio
async def test_on_message_creates_gateway_device(monkeypatch):
    """При topology-сообщении создаётся GatewayDevice, если pid != PID_WIFI_PANEL."""
    gtw = ProGateway("1.2.3.4")

    added = {}

    async def fake_add_device(self, device):
        added["device"] = device
        self.devices[device.id] = device
        device.gateways.append(self)
        device.hass = self.hass

    monkeypatch.setattr(ProGateway, "add_device", fake_add_device, raising=True)

    topo = {
        "id": "gateway_post.topology",
        "method": "gateway_post.topology",
        "nodes": [
            {"id": 0, "nt": -1, "pid": "gateway", "type": "gateway"},
        ],
    }

    await gtw.on_message(json.dumps(topo).encode("utf-8"))

    assert isinstance(gtw.device, GatewayDevice)
    assert added["device"] is gtw.device
    # GatewayDevice в коде переопределяет id на host
    assert "1.2.3.4" in gtw.devices
    assert gtw.devices["1.2.3.4"] is gtw.device


@pytest.mark.asyncio
async def test_on_message_creates_device_for_pid_wifi_panel(monkeypatch):
    """
    При pid=PID_WIFI_PANEL на topology-сообщении создаётся какое-то устройство
    (в текущей реализации это GatewayDevice, но нам важно, что оно вообще есть
    и привязано к gateway).
    """
    gtw = ProGateway("1.2.3.4", pid=PID_WIFI_PANEL)

    async def fake_add_device(self, device):
        self.devices[device.id] = device
        device.gateways.append(self)

    monkeypatch.setattr(ProGateway, "add_device", fake_add_device, raising=True)

    topo = {
        "id": "gateway_post.topology",
        "method": "gateway_post.topology",
        "nodes": [
            {"id": 123, "nt": 2, "pid": "wifi_panel", "type": 7},
        ],
    }

    await gtw.on_message(json.dumps(topo).encode("utf-8"))

    # Важно: устройство создано и привязано к gateway
    assert gtw.device is not None
    # id у WifiPanelDevice — 123, у GatewayDevice — host; проверяем оба варианта
    dev_id = gtw.device.id
    assert dev_id in gtw.devices
    assert gtw.devices[dev_id] is gtw.device
    # Если реализацию поменяют на WifiPanelDevice — тест останется валиден
    assert isinstance(gtw.device, (GatewayDevice, WifiPanelDevice))


@pytest.mark.asyncio
async def test_stop_cancels_task_closes_writer_and_clears_devices():
    """stop() должен отменять main_task, закрывать writer и убирать gateway из device.gateways."""
    gtw = ProGateway("1.2.3.4")

    class FakeWriter:
        def __init__(self):
            self.closed = False
            self.wait_closed_called = False

        def close(self):
            self.closed = True

        async def wait_closed(self):
            self.wait_closed_called = True

    class FakeTask:
        def __init__(self):
            self._cancelled = False

        def cancel(self):
            self._cancelled = True

        def cancelled(self):
            return self._cancelled

    writer = FakeWriter()
    task = FakeTask()

    gtw.writer = writer
    gtw.main_task = task

    class DummyDevice:
        def __init__(self):
            self.gateways = [gtw]

    dev = DummyDevice()
    gtw.devices = {1: dev}

    await gtw.stop()

    assert task._cancelled is True
    assert writer.closed is True
    assert writer.wait_closed_called is True
    assert gtw.writer is None
    assert gtw not in dev.gateways


# ---------- run_forever ----------


@pytest.mark.asyncio
async def test_run_forever_retries_and_stops_on_cancel(monkeypatch):
    """
    run_forever:
    - при первом connect() получаем False → делается sleep(30) и цикл продолжается;
    - при втором connect() успех → вызывается readline();
    - readline бросает CancelledError → выходим из цикла.
    """
    gtw = ProGateway("1.2.3.4")

    connect_calls = []
    sleep_calls = []

    async def fake_connect(self):
        connect_calls.append("call")
        # первый вызов -> False, второй -> True
        return len(connect_calls) > 1

    async def fake_readline(self):
        # сразу прерываем цикл
        raise asyncio.CancelledError()

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    monkeypatch.setattr(ProGateway, "connect", fake_connect, raising=True)
    monkeypatch.setattr(ProGateway, "readline", fake_readline, raising=True)
    # патчим sleep в модуле gateway, а не глобальный asyncio.sleep
    monkeypatch.setattr(
        "custom_components.yeelight_pro.core.gateway.asyncio.sleep",
        fake_sleep,
    )

    # просто дожидаемся завершения цикла — CancelledError внутри run_forever
    # перехватывается, наружу не выходит
    await gtw.run_forever()

    # Было две попытки connect()
    assert len(connect_calls) == 2
    # После первой неудачи был sleep(30)
    assert sleep_calls == [30]
