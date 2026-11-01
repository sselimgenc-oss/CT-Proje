import asyncio
import json

import pytest

from copytrade.hl_ws_runtime import DryRunRuntime, RuntimeConfig


ADDRESSES = tuple(f"0x{i:040x}" for i in range(1, 12))


def fills_message(*fills):
    return {"channel": "userFills", "data": {"user": ADDRESSES[0], "fills": list(fills)}}


def fill(tid, timestamp):
    return {"coin": "BTC", "side": "B", "px": "100", "sz": "0.1", "time": timestamp,
            "oid": 10, "tid": tid}


class FakeAdapter:
    def __init__(self, messages=(), backfill_messages=()):
        self.messages = list(messages)
        self.backfill_messages = list(backfill_messages)
        self.connected_addresses = None
        self.plans = []
        self.closed = 0

    async def connect(self, addresses):
        self.connected_addresses = addresses

    async def receive(self, timeout_seconds):
        if self.messages:
            return self.messages.pop(0)
        await asyncio.sleep(0.005)
        return None

    async def backfill(self, plan, addresses):
        self.plans.append((plan, addresses))
        return self.backfill_messages

    async def close(self):
        self.closed += 1


def config(path):
    return RuntimeConfig(addresses=ADDRESSES, network_enabled=True, evidence_path=path,
                         heartbeat_timeout_seconds=1, reconnect_initial_seconds=0.01,
                         reconnect_max_seconds=0.02)


def test_config_fails_closed_without_explicit_network_and_exact_first11():
    with pytest.raises(ValueError, match="ağ kapalı"):
        RuntimeConfig(addresses=ADDRESSES).validate()
    with pytest.raises(ValueError, match="tam 11"):
        RuntimeConfig(addresses=ADDRESSES[:10], network_enabled=True).validate()


def test_runtime_subscribes_only_supplied_addresses_backfills_and_writes_safe_evidence(tmp_path):
    async def scenario():
        path = tmp_path / "evidence.jsonl"
        adapter = FakeAdapter(messages=[fills_message(fill(77, 1_000))],
                              backfill_messages=[fills_message(fill(77, 1_000))])
        runtime = DryRunRuntime(config(path), adapter, clock_ms=lambda: 1_500)
        async def stop_soon():
            while runtime.health.counters["messages"] < 2:
                await asyncio.sleep(0.001)
            runtime.request_stop("test_stop")
        stopper = asyncio.create_task(stop_soon())
        manifest = await runtime.run()
        await stopper
        return path, adapter, runtime, manifest

    path, adapter, runtime, manifest = asyncio.run(scenario())
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert adapter.connected_addresses == ADDRESSES
    assert adapter.plans[0][1] == ADDRESSES
    assert adapter.plans[0][0]["kind"] == "read_only_backfill_request"
    assert runtime.health.counters["accepted"] == 1
    assert runtime.health.counters["duplicates"] == 1
    assert runtime.health.counters["proposals"] == 1
    decisions = [row for row in rows if row["event_type"] == "dry_run_decision"]
    assert len(decisions) == 1
    assert decisions[0]["decision"]["order_sent"] is False
    assert decisions[0]["decision"]["exchange_post_performed"] is False
    assert ADDRESSES[0] not in path.read_text()
    assert manifest["completed"] is False and manifest["stop_reason"] == "test_stop"
    assert rows[-1]["event_type"] == "run_manifest"
    assert adapter.closed >= 1


def test_health_ready_requires_connected_fresh_heartbeat():
    async def scenario():
        adapter = FakeAdapter()
        runtime = DryRunRuntime(config(None), adapter)
        assert runtime.health_snapshot()["ready"] is False
        task = asyncio.create_task(runtime.run())
        while not runtime.health.connected:
            await asyncio.sleep(0)
        fresh = runtime.health_snapshot()
        runtime.health.last_heartbeat_monotonic -= 10
        stale = runtime.health_snapshot()
        runtime.request_stop()
        await task
        return fresh, stale

    fresh, stale = asyncio.run(scenario())
    assert fresh["ready"] is True
    assert stale["ready"] is False
