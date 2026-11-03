from __future__ import annotations

from pathlib import Path

from copytrade.izleme import update
from copytrade.kopya import simulate
from copytrade.kurallar import evaluate
from copytrade.olcut import calculate_metrics, closed_round_trips, martingale_ratio
from copytrade.tarama import RateLimiter, prefilter, run


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


def test_rules_have_three_outcomes():
    assert evaluate({"history_days": 1, "closed_trades": 0})[0] == "yetersiz"
    base = {"history_days": 181, "closed_trades": 51, "profitable_month_ratio": .8, "largest_trade_share": .2,
            "profit_factor_without_best": 1.3, "sortino": 1.6, "calmar": 1.1, "median_holding_hours": 2,
            "median_leverage": 4, "max_leverage": 10, "liquid_coin_share": .9, "martingale_signal": False}
    assert evaluate(base)[0] == "aday"
    assert evaluate({**base, "max_leverage": 16})[0] == "elendi"


def test_watchlist_preserves_t0_and_never_removes(tmp_path: Path):
    path = tmp_path / "izleme.csv"
    update(path, ["0xA"], "2026-01-01", "v1", {"0xa": "aday"})
    rows = update(path, ["0xB"], "2026-02-01", "v2", {"0xa": "elendi", "0xb": "aday"})
    assert [(r["address"], r["t0"], r["status"]) for r in rows] == [("0xA", "2026-01-01", "elendi"), ("0xB", "2026-02-01", "aday")]


def test_copy_charges_friction_and_funding():
    ledger = simulate([fill(1_000, "B", 1, 0, pnl=10, price=100)], 1_000, slippage=.0005, taker_fee=.00045,
                      funding=[{"time": 2_000, "usdc": -2}])
    assert round(ledger.net_pnl.iloc[0], 3) == 7.905


def test_copy_reads_documented_funding_shape_and_does_not_double_charge_fees():
    ledger = simulate([fill(1_000, "A", 1, 1, pnl=10, fee=3, price=100)], 1_000, slippage=0, taker_fee=.00045,
                      funding=[{"time": 2_000, "delta": {"usdc": "-2"}}])
    assert round(ledger.net_pnl.iloc[0], 3) == 7.955  # 10 − our taker 0.045 − funding 2; leader fee not charged


def test_prefilter_keeps_every_eligible_leader_without_a_cap():
    rows = [{"ethAddress": f"0x{i}", "accountValue": 25_000, "monthRoi": 1, "allTimeRoi": 1, "allTimePnl": i}
            for i in range(301)]
    selected = prefilter(rows, [{"address": "0x0"}])
    assert len(selected) == 300  # 0 has non-positive all-time PnL
    assert {row["address"] for row in selected} == {f"0x{i}" for i in range(1, 301)}


def test_prefilter_kurallari_tek_kez_okur_ve_sonuc_ayni(monkeypatch):
    """A2-3b: eşik satır başına değil BİR kez okunur (48.130 satırda YAML okuma ~17 dk sürüyordu). Elle: 5 satır, eşik 20.000: 25.000 geçer; 19.999 geçmez; PnL ≤ 0 geçmez."""
    import copytrade.tarama as tarama
    cagri = {"n": 0}
    gercek = tarama.load_rules

    def sayac():
        cagri["n"] += 1
        return gercek()
    monkeypatch.setattr(tarama, "load_rules", sayac)
    esik = float(gercek()["evren_min_hesap_degeri"])
    rows = [{"ethAddress": "0xa", "accountValue": esik + 5_000, "allTimePnl": 1}, {"ethAddress": "0xb", "accountValue": esik - 1, "allTimePnl": 1},
            {"ethAddress": "0xc", "accountValue": esik + 5_000, "allTimePnl": 0}, {"ethAddress": "0xd", "accountValue": esik, "allTimePnl": 5}, {"ethAddress": "", "accountValue": esik, "allTimePnl": 5}]
    assert [r["address"] for r in tarama.prefilter(rows)] == ["0xa", "0xd"] and cagri["n"] == 1


def test_prefilter_accepts_documented_window_performances_shape():
    row = {"ethAddress": "0xA", "accountValue": "25000", "windowPerformances": [
        {"window": "month", "roi": "1", "pnl": "3"}, {"window": "allTime", "roi": "2", "pnl": "4"}]}
    assert prefilter([row], [])[0]["address"] == "0xA"


def test_rate_limiter_waits_before_exceeding_limit():
    now = [0.0]
    limiter = RateLimiter(2, clock=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
    limiter.acquire(2)
    limiter.acquire(1)
    assert now[0] >= 60


def test_daily_run_writes_public_archive_watchlist_and_report(tmp_path: Path):
    class Client:
        def leaderboard(self):
            return [{"ethAddress": "0xA", "accountValue": "25000", "monthROI": 1, "allTimeROI": 1, "allTimePnL": 1}]

        def fills(self, address, start):
            return [fill(1_000, "B", 1, 0), fill(7_201_000, "A", 1, 1, pnl=10, fee=1)]

        def info(self, payload, weight=20):
            if payload["type"] == "userFunding":
                return []
            return {"assetPositions": []}

    table = run(tmp_path, Client(), today="2026-10-27", limit=1)
    assert len(table) == 1
    assert (tmp_path / "veri/lider/2026-10-27.csv.gz").exists()
    assert (tmp_path / "veri/fills/0xa.csv.gz").exists()
    assert (tmp_path / "RAPOR.md").exists()


def test_prefilter_accepts_live_pair_shape_of_window_performances():
    row = {"ethAddress": "0xA", "accountValue": "30000", "windowPerformances": [
        ["day", {"pnl": "1", "roi": "0.01", "vlm": "5"}], ["month", {"pnl": "3", "roi": "0.1", "vlm": "9"}],
        ["allTime", {"pnl": "4", "roi": "0.2", "vlm": "9"}]]}
    assert prefilter([row], [])[0]["address"] == "0xA"


def test_rate_limited_address_is_recorded_as_no_data_and_run_continues(tmp_path: Path):
    from copytrade.tarama import RateLimitError

    class Client:
        def leaderboard(self):
            return [{"ethAddress": a, "accountValue": "25000", "monthROI": 1, "allTimeROI": 1, "allTimePnL": 1} for a in ("0xA", "0xB")]

        def fills(self, address, start):
            if address == "0xA":
                raise RateLimitError("429")
            return [fill(1_000, "B", 1, 0), fill(7_201_000, "A", 1, 1, pnl=10, fee=1)]

        def info(self, payload, weight=20):
            return [] if payload["type"] == "userFunding" else {"assetPositions": []}

    table = run(tmp_path, Client(), today="2026-10-27")
    assert dict(zip(table.address, table.sonuc))["0xA"] == "veri_yok" and len(table) == 2


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
