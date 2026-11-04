"""PublicClient (tarama.py) istemci davranışı: 5xx yeniden deneme, 429, yanıt boyutu ağırlığı. test_trader_secimi.py'den taşındı (davranış aynı). Ağsız."""
from __future__ import annotations

import pytest
import requests

from copytrade.tarama import PublicClient


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body if body is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, statuses):
        self.statuses, self.calls = list(statuses), 0

    def request(self, *_a, **_k):
        self.calls += 1
        return FakeResponse(self.statuses.pop(0), {"ok": True})


class NoLimit:
    def acquire(self, _weight):
        pass


def test_server_errors_are_retried_three_times_with_growing_waits():
    sleeps: list[float] = []
    session = FakeSession([500, 502, 200])
    assert PublicClient(session, NoLimit(), sleeps.append).info({"type": "x"}) == {"ok": True}
    assert session.calls == 3 and sleeps == [2, 6]
    failing, sleeps = FakeSession([500, 503, 500, 200]), []
    with pytest.raises(requests.HTTPError):
        PublicClient(failing, NoLimit(), sleeps.append).info({"type": "x"})
    assert failing.calls == 3 and sleeps == [2, 6]
    limited, sleeps = FakeSession([429, 200]), []
    assert PublicClient(limited, NoLimit(), sleeps.append).info({"type": "x"}) == {"ok": True} and sleeps == [5]


def test_response_size_weight_candles_per_60_other_lists_per_20_and_stats_counted():
    class Limiter:
        def __init__(self): self.weights = []
        def acquire(self, weight): self.weights.append(weight)

    class Session:
        def request(self, *_a, **_k): return FakeResponse(200, [{}] * 120)

    limiter = Limiter()
    client = PublicClient(Session(), limiter, lambda _s: None)
    client.info({"type": "candleSnapshot"}, weight=20)
    client.info({"type": "userFills"}, weight=20)
    assert limiter.weights == [20, 2, 20, 6] and client.stats["istek"] == 2
