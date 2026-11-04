"""Altın örnekler (görev 25): elle hesaplanmış küçük senaryolar, kopya defterinden (copy_ledger) geçer. (T1: eski ikinci motor kolu silindi; defter kolu ve beklenen sayılar aynen.)

Ortak: hesap 1000 $, maliyet %0,095 (taker %0,045 + kayma %0,05) her dolumda; sonuçlar hesaba oranla.
"""
from __future__ import annotations

import pytest

from copytrade.defter import DAY, HOUR, FundingRates, Market, copy_ledger
from copytrade.kurallar import load_rules

T0 = 20_833 * DAY
A = 1000.0
RULES = load_rules()


def candles(prices, coin="BTC"):
    return {coin: [{"t": T0 + h * HOUR, "o": str(p), "c": str(p)} for h, p in sorted(prices.items())]}


def fill(minutes, side, size, before, px, coin="BTC", tid=0):
    return {"time": T0 + minutes * 60_000, "coin": coin, "side": side, "sz": str(size), "startPosition": str(before), "px": str(px),
            "closedPnl": "0", "fee": "0", "tid": tid}


def both(fills, market, delay, end_hours, rates=None):
    """Kopya defteri neti."""
    start_ms, end_ms = T0 - DAY, T0 + end_hours * HOUR
    return copy_ledger(fills, Market(market), A, delay, start_ms, end_ms, rates, RULES)["net"]


SCENARIOS = {
    # (açıklama) → (dolumlar, mumlar, gecikme dk, pencere sonu (saat), funding, beklenen net)
    "1 miras pozisyonun kapanışı (bizde yok → hiçbir şey)": (
        [fill(120, "A", 5, 5, 100)], candles({0: 100, 3: 100}), 0, 24, None, 0.0),
    "2 parçalı açılış ve kısmi kapanışlar (ortalama giriş 105)": (
        [fill(60, "B", 10, 0, 100), fill(120, "B", 10, 10, 110), fill(180, "A", 10, 20, 120), fill(240, "A", 10, 10, 130)],
        candles({0: 100}), 0, 24, None, (400 - 4.37) / 1000),
    "3 tersine dönüş (kapat + yeni ters pozisyon aç)": (
        [fill(60, "B", 10, 0, 100), fill(120, "A", 15, 10, 110), fill(180, "B", 5, -5, 105)],
        candles({0: 100}), 0, 24, None, (125 - 3.01625) / 1000),
    "4 gecikmede mum boşluğu (kapanış dolumu eksik, açık pozisyon fiyatlanır)": (
        [fill(10, "B", 10, 0, 100), fill(100, "A", 10, 10, 100)], candles({0: 99, 1: 100, 2: 104}), 30, 2, None, 0.03905),
    "5 açık pozisyonun fiyatlanması (kapanış yürütmesi pencere sonrasına düşer)": (
        [fill(60, "B", 10, 0, 100), fill(300, "A", 10, 10, 100)], candles({h: (100 if h < 5 else 106) for h in range(0, 8)}), 30, 5, None,
        (-1000 * 0.00095 + 10 * (106 - 100)) / 1000),
    "6 funding kopyanın kendi pozisyonundan (trader'ın usdc'si değil)": (
        [fill(60, "B", 10, 0, 100), fill(300, "A", 10, 10, 100)], candles({h: 100 for h in range(0, 8)}), 0, 7,
        FundingRates([{"time": T0 + h * HOUR + 5, "delta": {"coin": "BTC", "usdc": "999", "fundingRate": "0.0001"}} for h in range(1, 6)]),
        -0.0023),
    "7 gecikme: sonraki mum açılışı": (
        [fill(70, "B", 10, 0, 100), fill(190, "A", 10, 10, 100)], candles({1: 99, 2: 101, 3: 102, 4: 105, 5: 106}), 30, 6, None,
        (40 - 1.957) / 1000),
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenario_gives_the_hand_computed_number_in_the_ledger(name):
    fills, market, delay, end_hours, rates, expected = SCENARIOS[name]
    assert both(fills, market, delay, end_hours, rates) == pytest.approx(expected, abs=1e-9)


def test_there_are_at_least_six_golden_scenarios():
    assert len(SCENARIOS) >= 6
