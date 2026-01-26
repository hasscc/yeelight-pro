import asyncio
import json
import random

import pytest

from custom_components.yeelight_pro.core.gateway import (
    ProGateway,
    MSG_SPLIT,
    MIN_RECONNECT_DELAY,
    MAX_JSON_ERRORS,
)
from custom_components.yeelight_pro.core.const import PID_WIFI_PANEL
from custom_components.yeelight_pro.core.device import GatewayDevice, WifiPanelDevice, XDevice


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

    async def fake_main_task():
        await asyncio.sleep(100)

    writer = FakeWriter()
    task = asyncio.create_task(fake_main_task())

    gtw.writer = writer
    gtw.main_task = task

    class DummyDevice:
        def __init__(self):
            self.gateways = [gtw]

    dev = DummyDevice()
    gtw.devices = {1: dev}

    await gtw.stop()

    assert task.cancelled() is True
    assert writer.closed is True
    assert writer.wait_closed_called is True
    assert gtw.writer is None
    assert gtw.main_task is None
    assert gtw not in dev.gateways


@pytest.mark.asyncio
async def test_stop_cancels_pending_futures():
    """stop() должен отменять все pending futures в _msgs."""
    gtw = ProGateway("1.2.3.4")

    loop = asyncio.get_running_loop()
    fut1 = loop.create_future()
    fut2 = loop.create_future()
    fut2.set_result("done")  # already done

    gtw._msgs = {1: fut1, 2: fut2}

    await gtw.stop()

    assert fut1.cancelled() is True
    assert gtw._msgs == {}
    assert gtw._stopping is True


@pytest.mark.asyncio
async def test_send_handles_drain_error(monkeypatch):
    """send() должен корректно обрабатывать ошибки в drain()."""
    gtw = ProGateway("1.2.3.4")

    class FakeWriter:
        def __init__(self):
            self.closed = False

        def write(self, data):
            pass

        async def drain(self):
            raise ConnectionError("Broken pipe")

        def close(self):
            self.closed = True

        async def wait_closed(self):
            pass

    gtw.writer = FakeWriter()

    result = await gtw.send("test_method", wait_result=True)

    assert result is None
    assert gtw.writer is None  # connection closed
    assert len(gtw._msgs) == 0  # future cleaned up


@pytest.mark.asyncio
async def test_send_returns_none_when_not_connected(monkeypatch):
    """send() должен возвращать None если не удалось подключиться."""
    gtw = ProGateway("1.2.3.4")

    async def fake_connect(self):
        return False

    monkeypatch.setattr(ProGateway, "connect", fake_connect, raising=True)

    result = await gtw.send("test_method", wait_result=True)

    assert result is None


# ---------- run_forever ----------


@pytest.mark.asyncio
async def test_run_forever_retries_with_exponential_backoff(monkeypatch):
    """
    run_forever:
    - при первых connect() получаем False → делается sleep с exponential backoff;
    - при успешном connect() вызывается _read_loop();
    - _read_loop бросает CancelledError → выходим из цикла.
    """
    gtw = ProGateway("1.2.3.4")

    connect_calls = []
    sleep_calls = []

    async def fake_connect(self):
        connect_calls.append("call")
        # первые 3 вызова -> False, четвертый -> True
        return len(connect_calls) > 3

    async def fake_read_loop(self):
        # сразу прерываем цикл
        raise asyncio.CancelledError()

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    monkeypatch.setattr(ProGateway, "connect", fake_connect, raising=True)
    monkeypatch.setattr(ProGateway, "_read_loop", fake_read_loop, raising=True)
    monkeypatch.setattr(
        "custom_components.yeelight_pro.core.gateway.asyncio.sleep",
        fake_sleep,
    )

    await gtw.run_forever()

    # Было 4 попытки connect()
    assert len(connect_calls) == 4
    # Exponential backoff: 1.0, 2.0, 4.0
    assert sleep_calls == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_run_forever_resets_backoff_on_success(monkeypatch):
    """После успешного connect() backoff сбрасывается."""
    gtw = ProGateway("1.2.3.4")
    gtw._reconnect_delay = 16.0  # simulate previous failures

    connect_calls = []

    async def fake_connect(self):
        connect_calls.append("call")
        return True

    async def fake_read_loop(self):
        # Check that backoff was reset
        assert self._reconnect_delay == MIN_RECONNECT_DELAY
        raise asyncio.CancelledError()

    monkeypatch.setattr(ProGateway, "connect", fake_connect, raising=True)
    monkeypatch.setattr(ProGateway, "_read_loop", fake_read_loop, raising=True)

    await gtw.run_forever()

    assert len(connect_calls) == 1


@pytest.mark.asyncio
async def test_read_loop_handles_connection_closed():
    """_read_loop должен корректно обрабатывать закрытие соединения."""
    gtw = ProGateway("1.2.3.4")

    class FakeReader:
        def __init__(self):
            self.call_count = 0

        async def readline(self):
            self.call_count += 1
            if self.call_count == 1:
                return b'{"id": 1}\r\n'
            # Simulate connection closed
            return b""

    class FakeWriter:
        def close(self):
            pass

        async def wait_closed(self):
            pass

    gtw.reader = FakeReader()
    gtw.writer = FakeWriter()

    await gtw._read_loop()

    assert gtw.writer is None
    assert gtw.reader is None


@pytest.mark.asyncio
async def test_read_loop_handles_connection_error():
    """_read_loop должен корректно обрабатывать ошибки соединения."""
    gtw = ProGateway("1.2.3.4")

    class FakeReader:
        async def readline(self):
            raise ConnectionError("Connection lost")

    class FakeWriter:
        def close(self):
            pass

        async def wait_closed(self):
            pass

    gtw.reader = FakeReader()
    gtw.writer = FakeWriter()

    await gtw._read_loop()

    assert gtw.writer is None
    assert gtw.reader is None


# ---------- JSON error counter ----------


@pytest.mark.asyncio
async def test_json_error_counter_resets_on_success():
    """Счётчик JSON ошибок сбрасывается при успешном парсинге."""
    gtw = ProGateway("1.2.3.4")
    gtw._json_error_count = 3

    # Valid JSON message
    await gtw.on_message(b'{"id": 1, "method": "test"}')

    assert gtw._json_error_count == 0


@pytest.mark.asyncio
async def test_json_error_counter_increments_on_error():
    """Счётчик JSON ошибок увеличивается при ошибке."""
    gtw = ProGateway("1.2.3.4")
    gtw._json_error_count = 0

    # Invalid JSON
    await gtw.on_message(b'not valid json {')

    assert gtw._json_error_count == 1


@pytest.mark.asyncio
async def test_json_error_triggers_reconnect_after_max():
    """После MAX_JSON_ERRORS ошибок соединение закрывается."""
    gtw = ProGateway("1.2.3.4")
    gtw._json_error_count = MAX_JSON_ERRORS - 1

    class FakeWriter:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

        async def wait_closed(self):
            pass

    gtw.writer = FakeWriter()

    # This should trigger reconnect
    await gtw.on_message(b'invalid json')

    assert gtw._json_error_count == MAX_JSON_ERRORS
    assert gtw.writer is None  # Connection closed


# ---------- Keepalive ----------


@pytest.mark.asyncio
async def test_keepalive_loop_stops_on_stopping_flag(monkeypatch):
    """Keepalive останавливается при _stopping=True."""
    gtw = ProGateway("1.2.3.4", keepalive=0.1)
    gtw.writer = DummyWriter()

    sleep_count = [0]

    async def fake_sleep(delay):
        sleep_count[0] += 1
        gtw._stopping = True  # Stop after first sleep

    monkeypatch.setattr(
        "custom_components.yeelight_pro.core.gateway.asyncio.sleep",
        fake_sleep,
    )

    await gtw._keepalive_loop()

    assert sleep_count[0] == 1


@pytest.mark.asyncio
async def test_keepalive_closes_connection_on_failure(monkeypatch):
    """Keepalive закрывает соединение при неудаче."""
    gtw = ProGateway("1.2.3.4", keepalive=0.01)

    class FakeWriter:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

        async def wait_closed(self):
            pass

    gtw.writer = FakeWriter()

    async def fake_send(method, **kwargs):
        return None  # Simulate failure

    monkeypatch.setattr(gtw, "send", fake_send)

    await gtw._keepalive_loop()

    assert gtw.writer is None


# ---------- Topology device tracking ----------


@pytest.mark.asyncio
async def test_topology_tracks_devices():
    """Топология отслеживает устройства."""
    gtw = ProGateway("1.2.3.4")
    gtw.device = GatewayDevice(gtw)
    gtw.devices[gtw.device.id] = gtw.device

    topo = {
        "method": "gateway_post.topology",
        "nodes": [
            {"id": 100, "nt": 2, "type": 1},
            {"id": 200, "nt": 2, "type": 2},
        ],
    }

    await gtw.on_message(json.dumps(topo).encode())

    assert gtw._last_topology_devices == {100, 200}


@pytest.mark.asyncio
async def test_topology_detects_removed_devices():
    """Топология обнаруживает удалённые устройства."""
    gtw = ProGateway("1.2.3.4")
    gtw.device = GatewayDevice(gtw)
    gtw.devices[gtw.device.id] = gtw.device

    # Create a device that will be "removed"
    device = XDevice({"id": 100, "nt": 2, "type": 1, "n": "Test"})
    device.prop = {"o": True}
    gtw.devices[100] = device
    gtw._last_topology_devices = {100, 200}

    # New topology without device 100
    topo = {
        "method": "gateway_post.topology",
        "nodes": [
            {"id": 200, "nt": 2, "type": 2},
        ],
    }

    await gtw.on_message(json.dumps(topo).encode())

    # Device 100 should be marked offline
    assert device.prop.get("o") is False


# ---------- Properties ----------


def test_is_connected_property():
    """is_connected возвращает корректное значение."""
    gtw = ProGateway("1.2.3.4")

    assert gtw.is_connected is False

    gtw.writer = DummyWriter()
    assert gtw.is_connected is True

    gtw._stopping = True
    assert gtw.is_connected is False


def test_device_count_property():
    """device_count возвращает количество устройств."""
    gtw = ProGateway("1.2.3.4")

    assert gtw.device_count == 0

    gtw.devices = {1: "dev1", 2: "dev2"}
    assert gtw.device_count == 2
