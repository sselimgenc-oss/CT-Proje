"""F08: elle hesaplanmış ortak kasa örnekleri (maliyet sıfırlanır)."""
import pytest

from copytrade.kurallar import load_rules_asil
from copytrade.portfoy_oynatma import oynat


def _kadro(*dolumlar):
    return [{"adres": f"T{i}", "hesap_usd": 1000, "dolumlar": list(dolumlar[i]) if i < len(dolumlar) else []}
            for i in range(5)]


def _f(t, coin, side, sz, px=100):
    return {"time": t, "coin": coin, "side": side, "sz": sz, "px": px}


def _rules():
    return {**load_rules_asil(), "maliyet_taker": 0, "maliyet_kayma": 0}


def test_ayni_coin_tavani():
    # Her trader hedefi 200 × (1000/1000) = 200 $. İkinci BTC 100 $'a kırpılır.
    r = oynat(_kadro([_f(1, "BTC", "B", 10)], [_f(2, "BTC", "B", 10)]), {"BTC": 110}, _rules())
    assert r["uye_getirileri_toplami"] == pytest.approx(0.04)
    assert r["portfoy_getirisi"] == pytest.approx(0.03)
    assert r["fark"] == pytest.approx(0.01)
    assert r["kirpma_usd"]["coin_tavani_kirpildi"] == pytest.approx(100)


def test_marj_tavani():
    rules = {**_rules(), "canli_coin_tavan_oran": 1.0, "canli_marj_kaldirac": 1}
    # Her üye 300 $ hedefler; ilk üçü 900 $, dördüncü 100 $, beşinci 0 $.
    groups = [[_f(i + 1, f"C{i}", "B", 15)] for i in range(5)]
    r = oynat(_kadro(*groups), {f"C{i}": 110 for i in range(5)}, rules)
    assert r["uye_getirileri_toplami"] == pytest.approx(0.15)
    assert r["portfoy_getirisi"] == pytest.approx(0.10)
    assert r["kirpma_usd"]["marj_yok"] == pytest.approx(500)


def test_ters_yon():
    r = oynat(_kadro([_f(1, "BTC", "B", 10)], [_f(2, "BTC", "A", 10)]), {"BTC": 110}, _rules())
    assert r["uye_getirileri_toplami"] == pytest.approx(0)
    assert r["portfoy_getirisi"] == pytest.approx(0.02)
    assert r["kirpma_usd"]["ters_netlesme"] == pytest.approx(200)
