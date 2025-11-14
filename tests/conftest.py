import pytest
from custom_components.yeelight_pro.core.device import XDevice
from custom_components.yeelight_pro.core.gateway import ProGateway

@pytest.fixture(autouse=True)
def patch_setup_entities(monkeypatch):
    async def _noop(self):
        return
    monkeypatch.setattr(XDevice, "setup_entities", _noop)

@pytest.fixture
def gateway():
    return ProGateway("127.0.0.1")