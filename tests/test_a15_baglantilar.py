"""A15 bağlantıları: defter işaret yaşı geçerli mumla ölçülür (E4 ile birleşik); kapı akıl sağlığı raporunda mum özeti."""
import pytest

from copytrade.defter import DAY, HOUR, Market, copy_ledger
from copytrade.kurallar import load_rules

RULES = load_rules()
T0 = 20_833 * DAY


def mum(hour, o, h=None, l=None, c=None):
    return {"t": T0 + hour * HOUR, "T": T0 + (hour + 1) * HOUR - 1, "s": "BTC", "i": "1h", "o": str(o), "c": str(c if c is not None else o),
            "h": str(h if h is not None else o + 1), "l": str(l if l is not None else o - 1), "v": "10", "n": 5}


def test_market_mark_bozuk_ve_sicrama_mumlarini_atlar_son_gecerli_mumu_kullanir():
    candles = {"BTC": [mum(0, 100), mum(1, 100), mum(2, 7, h=3, l=9, c=7), mum(3, 40)]}      # saat 2 bozuk (h<l), saat 3 çöküş (100 → 40, ÷2,5)
    market = Market(candles)
    assert market.mark_at("BTC", T0 + 3 * HOUR + 30 * 60_000) is None                         # son geçerli mum 2,5 sa önce > 120 dk: işaret yok (çöküş mumu 40 kullanılmaz)
    assert market.mark_at("BTC", T0 + 2 * HOUR + 30 * 60_000) == (T0 + 1 * HOUR, 100.0)      # yaş 1,5 sa ≤ 120 dk: bozuk mum atlanır
    assert market.mark_at("BTC", T0 + 1 * HOUR + 30 * 60_000) == (T0 + 1 * HOUR, 100.0)


def test_market_mark_yas_sinirini_gecerli_mumdan_olcer():
    market = Market({"BTC": [mum(0, 100), mum(1, 7, h=3, l=9, c=7)]})
    limit = int(RULES["isaret_yas_max_dk"]) * 60_000
    assert market.mark_at("BTC", T0 + limit) == (T0, 100.0)                                  # sınırda geçerli
    assert market.mark_at("BTC", T0 + limit + 1) is None and market.mark("BTC", T0 + limit + 1) is None


def test_eksik_alanli_mumlar_kontrol_edilmez_ozet_mumlar_eskisi_gibi_calisir():
    market = Market({"BTC": [{"t": T0, "o": 100, "c": 100}, {"t": T0 + HOUR, "o": 90}]})     # canlı yürütme/işaret mumları yalnız t, o taşır
    assert market.mark_at("BTC", T0 + HOUR + 1) == (T0 + HOUR, 90.0)


def test_defter_bozuk_son_mum_yuzunden_mark_missing_sayar_ve_acigi_isaretlemez():
    """Uçtan uca: 10 BTC @100 açık; son iki mum bozuk/çöküş, son geçerli mum 5 saat önce → mark_missing 1, açık K/Z 0 (bayat/bozuk fiyatla işaretlenmez)."""
    candles = {"BTC": [mum(0, 100), mum(1, 7, h=3, l=9, c=7), mum(4, 40), mum(5, 40, h=39, l=41)]}
    fills = [{"time": T0, "coin": "BTC", "side": "B", "sz": "10", "startPosition": "0", "px": "100", "tid": 1, "_execution_time": T0, "_execution_price": 100.0}]
    out = copy_ledger(fills, Market(candles), 1000, 0, T0, T0 + 5 * HOUR + 1000)
    assert out["mark_missing"] == 1 and out["unrealized_end"] == 0.0 and out["mark_time"] is None
    ok = copy_ledger(fills, Market({"BTC": [mum(0, 100), mum(1, 90)]}), 1000, 0, T0, T0 + HOUR + 1000)
    assert ok["mark_missing"] == 0 and ok["unrealized_end"] == pytest.approx(10 * (90 - 100) / 1000)


# ---------------------------------------------------------------- kapı akıl sağlığı raporu: mum özeti






