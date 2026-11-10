"""F04/F06: geçmiş haftanın hacmi ve saatlik kopya funding'i."""
import pandas as pd
import pytest

from copytrade.gecmis_funding import FundingOnbellegi
from copytrade.kalicilik_testi import SaatlikMum
from copytrade.kopya_v5 import hesapla
from copytrade.kurallar import load_rules_asil

HOUR = 3_600_000


class Piyasa:
    def __init__(self):
        self.istek = []

    def info(self, payload, weight=20):
        self.istek.append((payload, weight))
        return [{"time": h * HOUR, "fundingRate": "0.0001"} for h in (1, 2, 3)]

    def candles(self, coin, start_ms, end_ms, interval="1h"):
        return [{"t": h * HOUR, "o": 100, "v": v} for h, v in ((0, 10), (1, 10), (2, 1), (3, 1))]


def test_haftalik_hacim_ayri_ve_onbellekte():
    p = Piyasa()
    mum = SaatlikMum(p, 0, 4 * HOUR)
    rules = {"radar_likit_coin_hacim_usd": 5000}
    assert mum.likit_coinler({"BTC"}, 0, 2 * HOUR, rules) == {"BTC"}
    assert mum.likit_coinler({"BTC"}, 2 * HOUR, 4 * HOUR, rules) == set()
    assert len(mum.seri) == 1


def test_uc_saat_bir_btc_long_funding_eksi_uc_sent():
    p = Piyasa()
    cache = FundingOnbellegi(p)
    rows = cache.oku({"BTC"}, 0, 5 * HOUR)
    assert cache.oku({"BTC"}, 0, 5 * HOUR) == rows
    assert len(p.istek) == 1 and p.istek[0][1] == 20
    rules = {**load_rules_asil(), "maliyet_taker": 0, "maliyet_kayma": 0}
    fills = [{"time": HOUR // 2, "coin": "BTC", "side": "B", "sz": "1", "px": "100", "startPosition": "0"},
             {"time": 7 * HOUR // 2, "coin": "BTC", "side": "A", "sz": "1", "px": "100", "startPosition": "1"}]
    candles = {"BTC": [{"t": h * HOUR, "o": 100} for h in range(5)]}
    t0, t1 = pd.Timestamp(0, unit="ms", tz="UTC"), pd.Timestamp(5 * HOUR, unit="ms", tz="UTC")
    out = hesapla(fills, candles, {}, {}, rows, t0, t1, 0, "intraday", rules, trader_hesap_usd=200)
    assert out["funding"] * 1000 == pytest.approx(-0.03)
