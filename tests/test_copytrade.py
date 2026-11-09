from __future__ import annotations



from copytrade.olcut import calculate_metrics, closed_round_trips, martingale_ratio
from copytrade.tarama import RateLimiter


def fill(time, side, size, position, pnl=0, fee=0, coin="BTC", price=100):
    return {"time": time, "side": side, "sz": size, "startPosition": position, "closedPnl": pnl,
            "fee": fee, "coin": coin, "px": price}


def test_round_trip_and_realized_net_pnl():
    fills = [fill(1_000, "B", 1, 0), fill(7_201_000, "A", 1, 1, pnl=10, fee=1)]
    trips = closed_round_trips(fills)
    assert len(trips) == 1
    assert trips[0]["net_pnl"] == 9
    assert trips[0]["holding_hours"] == 2


def test_martingale_only_flags_same_direction_addition_while_losing():
    bad = [fill(1_000, "B", 1, 0, price=100), fill(2_000, "B", 1, 1, price=90)]   # long, adds below entry
    good = [fill(1_000, "B", 1, 0, price=100), fill(2_000, "B", 1, 1, price=110)]  # pyramiding into a winner
    safe = [fill(1_000, "B", 1, 0), fill(2_000, "A", 1, 1, pnl=-1)]                # reduction, not addition
    short_bad = [fill(1_000, "A", 1, 0, price=100), fill(2_000, "A", 1, -1, price=110)]
    assert martingale_ratio(bad) == (1, 1)
    assert martingale_ratio(good) == (0, 1)
    assert martingale_ratio(safe) == (0, 0)
    assert martingale_ratio(short_bad) == (1, 1)


def test_martingale_signal_needs_enough_losing_additions():
    adds = [fill(1_000, "B", 1, 0, price=100)] + [fill(2_000 + i, "B", 1, 1 + i, price=90 - i) for i in range(5)]
    assert calculate_metrics(adds, account_value=10_000)["martingale_signal"]
    assert not calculate_metrics(adds[:3], account_value=10_000)["martingale_signal"]


def test_returns_use_account_value_not_one_dollar():
    day = 86_400_000
    fills = [fill(0, "B", 1, 0), fill(day, "A", 1, 1, pnl=100), fill(2 * day, "B", 1, 0), fill(3 * day, "A", 1, 1, pnl=-50)]
    m = calculate_metrics(fills, account_value=10_000)
    assert 0 < m["ulcer_index"] < 0.01  # a 50 USD dip on 10k is ~0.5 %, not a wipe-out


def test_metrics_include_signed_funding():
    fills = [fill(1_000, "B", 1, 0), fill(7_201_000, "A", 1, 1, pnl=10, fee=1)]
    metrics = calculate_metrics(fills, [{"time": 7_202_000, "delta": {"usdc": "-2"}}])
    assert metrics["closed_trades"] == 1
    assert metrics["history_days"] == 0
















def test_rate_limiter_waits_before_exceeding_limit():
    now = [0.0]
    limiter = RateLimiter(2, clock=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
    limiter.acquire(2)
    limiter.acquire(1)
    assert now[0] >= 60








def test_round_trip_pnl_accumulates_partial_closes_and_flip():
    fills = [{"time": 1, "coin": "BTC", "side": "B", "sz": "2", "px": "100", "startPosition": "0", "closedPnl": "0", "fee": "0"},
             {"time": 3600001, "coin": "BTC", "side": "A", "sz": "1", "px": "110", "startPosition": "2", "closedPnl": "10", "fee": "0"},
             {"time": 7200001, "coin": "BTC", "side": "A", "sz": "2", "px": "120", "startPosition": "1", "closedPnl": "20", "fee": "0"},
             {"time": 10800001, "coin": "BTC", "side": "B", "sz": "1", "px": "110", "startPosition": "-1", "closedPnl": "10", "fee": "0"}]
    trips = closed_round_trips(fills)
    assert [t["net_pnl"] for t in trips] == [30.0, 10.0]
    assert trips[0]["holding_hours"] == 2.0 and trips[1]["holding_hours"] == 1.0


def test_position_open_before_window_has_unknown_holding_and_spot_is_excluded():
    from copytrade.olcut import asset_class, perp_fills
    fills = [{"time": 1, "coin": "ETH", "side": "A", "sz": "1", "px": "10", "startPosition": "1", "closedPnl": "5", "fee": "0"},
             {"time": 2, "coin": "@107", "side": "B", "sz": "1", "px": "10", "closedPnl": "0", "fee": "0"}]
    assert closed_round_trips(perp_fills(fills))[0]["holding_hours"] is None
    assert [asset_class(c) for c in ("BTC", "@107", "PURR/USDC", "xyz:CL", "xyz:XYZ100", "xyz:SKHX")] == [
        "kripto", "spot", "spot", "emtia", "endeks", "hisse"]


def test_martingale_ignores_laddered_entry_and_leverage_uses_position_value():
    from copytrade.olcut import effective_leverage, martingale_ratio
    fills = [{"time": 1, "coin": "BTC", "side": "B", "sz": "1", "px": "100", "startPosition": "0", "oid": 1},
             {"time": 2, "coin": "BTC", "side": "B", "sz": "1", "px": "99.5", "startPosition": "1", "oid": 2},   # -%0,5: kademeli
             {"time": 3, "coin": "BTC", "side": "B", "sz": "1", "px": "90", "startPosition": "2", "oid": 3}]     # -%10: zarara ekleme
    ratio, additions = martingale_ratio(fills)
    assert additions == 2 and ratio == 0.5
    median, top = effective_leverage(fills, 1000)
    assert round(top, 2) == 0.27   # 3 BTC × 90 / 1000
