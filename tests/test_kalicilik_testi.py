"""Kalıcılık testi (K-53 doğrulaması, yalnız bilgi): saf analiz fonksiyonları + sahte istemciyle bir hafta satırı. Ağsız."""
import pytest

from copytrade import kalicilik_testi as k
from tests.test_radar_tarama import A1, HOUR, MIN, RULES, Sahte, dolum

GUN = 24 * HOUR


def test_haftalar_gun_basina_yuvarlanir_eskiden_yeniye():
    hf = k.haftalar(10 * GUN + 5 * HOUR, 3)
    assert hf == [(10 * GUN - 21 * GUN, 10 * GUN - 14 * GUN), (10 * GUN - 14 * GUN, 10 * GUN - 7 * GUN), (10 * GUN - 7 * GUN, 10 * GUN)]


def test_ciftler_sonraki_hafta_getirisi_none_ise_atlanir():
    kayit = {"a": [{"hafta_bas": 0, "durum": "olculdu", "gecti_v1": True, "kopya_islem_sayisi": 12, "getiri": 0.01},
                   {"hafta_bas": 1, "durum": "islem_yok", "getiri": 0.0},
                   {"hafta_bas": 2, "durum": "olculdu", "getiri": None}]}
    cs = k.ciftler(kayit)
    assert len(cs) == 1 and cs[0]["hafta"] == 0 and cs[0]["sonraki"] == 0.0 and cs[0]["gecti_v1"] is True


def test_haftalik_fark_ve_bootstrap_deterministik():
    cs = [{"hafta": h, "g": g, "sonraki": v} for h, g, v in [(0, 1, 0.03), (0, 0, 0.01), (1, 1, 0.0), (1, 0, 0.02), (2, 1, 0.05)]]
    x = k.haftalik_fark(cs, lambda c: c["g"] == 1, lambda c: c["g"] == 0)
    assert x == pytest.approx([0.02, -0.02])                                # hafta 2'de karşı grup yok → atlanır
    assert k.bootstrap_aralik(x) == k.bootstrap_aralik(x)                   # sabit tohum
    alt, ust = k.bootstrap_aralik(x)
    assert -0.02 <= alt <= ust <= 0.02
    assert k.bootstrap_aralik([0.1]) == (None, None)


def test_hukum_kurali():
    assert k.hukum(0.001, 0.01).startswith("devam")
    assert k.hukum(-0.01, -0.001).startswith("evren")
    assert k.hukum(-0.01, 0.01) == "belirsiz" and k.hukum(None, None) == "veri yetersiz"


def test_analiz_ve_ozet_md():
    cs = []
    for h in range(4):
        for i in range(6):
            gecti = i < 3
            cs.append({"hafta": h, "dolum_gecti": True, "gecti_v1": gecti, "gecti_v11": gecti and i < 2, "kopya_getiri_7g": 0.01 * i, "kopya_alt20": 0.001 * i,
                       "g_t_istat": float(i), "kopya_islem_sayisi": 5 * i, "sonraki": 0.01 if gecti else -0.01})
    a = k.analiz(cs)
    assert a["cift"] == 24 and a["hafta"] == 4
    assert a["test"]["b_v1_gecen_eksi_gecmeyen"]["ort"] == pytest.approx(0.02) and a["test"]["b_v1_gecen_eksi_gecmeyen"]["hukum"].startswith("devam")
    assert a["spearman"]["kopya_getiri_7g"]["ort"] < 0                       # geçenler düşük kopya getirili → ters sıra
    assert a["grup_ort"]["v1_gecen"]["n"] == 12 and round(a["grup_ort"]["v1_gecen"]["ort_usd"], 6) == 10.0
    md = k.ozet_md(a)
    assert "b_v11_gecen_eksi_gecmeyen" in md and "+20.00 $" in md


def test_hafta_satiri_sahte_istemci_karli_trader():
    """12 tur: 100'den aç, 90 dk sonra 110'dan kapat; saatlik mum. Gecikmesiz + maliyetli kopya kâr eder; dolum kuralları geçer; 12 kopya işlem."""
    t0, t1 = 100 * GUN, 107 * GUN
    fills, t = [], t0 + HOUR
    for _ in range(12):
        fills += [dolum(t, "BTC", "B", 1, 0, 100.0, tid=t), dolum(t + 90 * MIN, "BTC", "A", 1, 1, 110.0, kapanan=10.0, tid=t + 1)]
        t += 6 * HOUR
    c = Sahte([], {A1: fills}, lambda coin, ts: 100.0)
    mum = k.SaatlikMum(c, t0, t1)
    s = k.hafta_satiri(A1, fills, 20_000.0, 20_000.0, mum, t0, t1, {"BTC"}, None, RULES)
    assert s["durum"] == "olculdu" and s["dolum_gecti"] is True and s["kopya_islem_sayisi"] == 12
    assert s["getiri"] > 0 and s["gecti_v1"] == s["gecti_v11"]
    assert k.hafta_satiri(A1, [], 20_000.0, 20_000.0, mum, t0, t1, {"BTC"}, None, RULES) == {"durum": "islem_yok", "getiri": 0.0}
    assert k.hafta_satiri(A1, None, 20_000.0, 20_000.0, mum, t0, t1, {"BTC"}, None, RULES)["durum"] == "dolum_fazla"


def test_saatlik_mum_dakika_istegine_son_saat():
    c = Sahte([], {}, lambda coin, ts: 100.0 + ts // HOUR % 3)
    mum = k.SaatlikMum(c, 0, 10 * HOUR)
    assert [x["t"] for x in mum.candles("BTC", 5 * HOUR + MIN, 5 * HOUR + 20 * MIN, "1m")] == [5 * HOUR]      # aralıkta saat yok → önceki son saat
    assert [x["t"] for x in mum.candles("BTC", 2 * HOUR, 4 * HOUR, "1h")] == [2 * HOUR, 3 * HOUR, 4 * HOUR]
