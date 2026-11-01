import asyncio
import json

import pytest

from copytrade.hl_public_adapter import HyperliquidPublicAdapter


ADDRESSES = ("0x" + "1" * 40, "0x" + "2" * 40)


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.frames = [json.dumps({"channel": "subscriptionResponse", "data": {}}),
                       json.dumps({"channel": "userFills", "data": {"user": ADDRESSES[0], "fills": []}})]
        self.closed = False

    async def send(self, data):
        self.sent.append(json.loads(data))

    async def recv(self):
        return self.frames.pop(0)

    async def close(self):
        self.closed = True


def test_connect_subscribes_only_explicit_public_addresses_and_receive_filters_ack():
    async def scenario():
        socket = FakeSocket()
        calls = []

        async def connector(url, **kwargs):
            calls.append((url, kwargs))
            return socket

        adapter = HyperliquidPublicAdapter(ws_connect=connector)
        assert calls == []  # construction performs no I/O
        await adapter.connect(ADDRESSES)
        message = await adapter.receive(1)
        await adapter.close()
        return socket, calls, message

    socket, calls, message = asyncio.run(scenario())
    assert calls[0][0] == "wss://api.hyperliquid.xyz/ws"
    assert [x["subscription"] for x in socket.sent] == [
        {"type": "userFills", "user": addr} for addr in ADDRESSES]
    assert message["channel"] == "userFills"
    assert socket.closed


def test_backfill_uses_public_info_read_contract_per_address_and_wraps_fills():
    calls = []

    def http_post(url, payload, timeout):
        calls.append((url, payload, timeout))
        return [{"coin": "BTC", "side": "B", "px": "10", "sz": "1", "time": 100,
                 "tid": len(calls)}]

    async def scenario():
        adapter = HyperliquidPublicAdapter(http_post=http_post)
        return await adapter.backfill({"kind": "read_only_backfill_request", "start_ms": 10,
                                       "end_ms": 200, "after_event_time_ms": None}, ADDRESSES)

    messages = asyncio.run(scenario())
    assert [call[0] for call in calls] == ["https://api.hyperliquid.xyz/info"] * 2
    assert [call[1] for call in calls] == [
        {"type": "userFillsByTime", "user": addr, "startTime": 10, "endTime": 200}
        for addr in ADDRESSES]
    assert all(m["channel"] == "userFills" and m["data"]["fills"] for m in messages)


@pytest.mark.parametrize("ws_url,info_url", [
    ("ws://example.test/ws", "https://example.test/info"),
    ("wss://example.test/ws", "http://example.test/info"),
])
def test_insecure_endpoints_are_rejected(ws_url, info_url):
    with pytest.raises(ValueError, match="güvenli"):
        HyperliquidPublicAdapter(ws_url=ws_url, info_url=info_url)


def test_invalid_backfill_plan_fails_without_io():
    calls = []
    adapter = HyperliquidPublicAdapter(http_post=lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="plan"):
        asyncio.run(adapter.backfill({"kind": "other"}, ADDRESSES))
    assert calls == []
