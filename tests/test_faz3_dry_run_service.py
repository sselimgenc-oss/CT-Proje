import asyncio
import json

import pytest

from copytrade.faz3_dry_run_service import ServiceConfig, _health_server
from copytrade.hl_ws_runtime import DryRunRuntime, RuntimeConfig


ADDRESSES = ",".join(f"0x{i:040x}" for i in range(1, 12))


def set_valid_env(monkeypatch, tmp_path, **overrides):
    values = {
        "RUN_MODE": "dry_run", "NETWORK_ENABLED": "false", "WS_URL": "",
        "SUBSCRIPTIONS": ADDRESSES, "RUN_DURATION_SECONDS": "86400",
        "HEALTH_HOST": "127.0.0.1", "HEALTH_PORT": "8080",
        "EVIDENCE_DIR": str(tmp_path), "ADAPTER_FACTORY": "",
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_config_check_is_offline_but_service_start_requires_opt_in(monkeypatch, tmp_path):
    set_valid_env(monkeypatch, tmp_path)
    config = ServiceConfig.from_env()
    config.validate()
    assert config.runtime.network_enabled is False
    with pytest.raises(ValueError, match="ağ kapalı"):
        config.validate(starting=True)


@pytest.mark.parametrize("updates, message", [
    ({"RUN_MODE": "live"}, "RUN_MODE=dry_run"),
    ({"SUBSCRIPTIONS": ADDRESSES.rsplit(",", 1)[0]}, "tam 11"),
    ({"SUBSCRIPTIONS": ",".join(ADDRESSES.split(",")[:10] + [ADDRESSES.split(",")[0]])}, "benzersiz"),
    ({"RUN_DURATION_SECONDS": "86401"}, "1..86400"),
    ({"NETWORK_ENABLED": "yes"}, "true veya false"),
    ({"HEALTH_HOST": "0.0.0.0"}, "loopback"),
])
def test_invalid_config_fails_closed(monkeypatch, tmp_path, updates, message):
    set_valid_env(monkeypatch, tmp_path, **updates)
    with pytest.raises(ValueError, match=message):
        ServiceConfig.from_env().validate()


def test_health_and_ready_endpoints_are_local_and_return_safe_status(monkeypatch):
    async def scenario():
        runtime = DryRunRuntime(RuntimeConfig(addresses=tuple(f"0x{i:040x}" for i in range(1, 12)),
                                             network_enabled=True), adapter=object())
        captured = {}

        class FakeServer:
            def close(self): pass
            async def wait_closed(self): pass

        async def fake_start_server(handler, host, port):
            captured["handler"] = handler
            captured["bind"] = (host, port)
            return FakeServer()

        monkeypatch.setattr("copytrade.faz3_dry_run_service.asyncio.start_server", fake_start_server)
        server = await _health_server(runtime, "127.0.0.1", 8080)

        class FakeReader:
            def __init__(self, path):
                self.lines = [f"GET {path} HTTP/1.1\r\n".encode(), b"Host: localhost\r\n", b"\r\n"]
            async def readline(self): return self.lines.pop(0) if self.lines else b""

        class FakeWriter:
            def __init__(self): self.data = b""; self.closed = False
            def write(self, data): self.data += data
            async def drain(self): pass
            def close(self): self.closed = True
            async def wait_closed(self): pass

        async def get(path):
            writer = FakeWriter()
            await captured["handler"](FakeReader(path), writer)
            head, body = writer.data.split(b"\r\n\r\n", 1)
            return head.split(b"\r\n", 1)[0], json.loads(body)

        health_status, health = await get("/healthz")
        ready_status, ready = await get("/readyz")
        server.close()
        await server.wait_closed()
        assert captured["bind"] == ("127.0.0.1", 8080)
        return health_status, health, ready_status, ready

    health_status, health, ready_status, ready = asyncio.run(scenario())
    assert health_status == b"HTTP/1.1 200 OK"
    assert health["mode"] == "dry_run" and health["status"] == "ok"
    assert ready_status == b"HTTP/1.1 503 Service Unavailable"
    assert ready["ready"] is False
    assert "addresses" not in ready and "payload" not in ready
