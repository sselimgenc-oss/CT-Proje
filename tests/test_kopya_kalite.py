"""Kopya gecikme ve kayma kartı (`gunluk_ozet.kopya_kalite`, pano "Kopya kalitesi"): altın örnek, uç durumlar, yalnız bilgi.

Altın örnek (elle hesaplandı):
  dolan kayıtlar (usd_dolan > 0):
    1) ac     trader 1000  dolum 1400 (gecikme 400)  gorme 1100 (görme 100)  kayma  0,0002 → +2 bp
    2) artir  trader 2000  dolum 2900 (gecikme 900)  gorme 2300 (görme 300)  kayma  0,0006 → +6 bp
    3) azalt  trader 3000  dolum 3200 (gecikme 200)  görme yok               kayma -0,0001 → -1 bp
    4) kapat  trader None  dolum 4000  gorme 4100    kayma yok (gecikme/görme/kayma atlanır)
  usd_dolan = 0 olan kayıt sayılmaz.
  Genel: n=4; gecikme [400, 900, 200] → medyan 400, p90 (en yakın sıra, n=3 → 3.) 900;
         görme [100, 300] → medyan 200; kayma [2, 6, -1] → medyan 2, p90 6.
  ac_artir: n=2; gecikme [400, 900] → medyan 650; kayma [2, 6] → medyan 4.
  azalt_kapat: n=2; gecikme [200] → medyan 200; kayma [-1] → medyan -1; görme yok → null.
"""
from __future__ import annotations

import pytest

from copytrade.canli import gunluk_ozet as go

ALTIN = [
    {"olay": "emir", "eylem": "ac", "usd_dolan": 10.0, "trader_dolum_ms": 1000, "dolum_ms": 1400, "gorme_ms": 1100, "kayma_trader": 0.0002},
    {"olay": "emir", "eylem": "artir", "usd_dolan": 5.0, "trader_dolum_ms": 2000, "dolum_ms": 2900, "gorme_ms": 2300, "kayma_trader": 0.0006},
    {"olay": "emir", "eylem": "azalt", "usd_dolan": 8.0, "trader_dolum_ms": 3000, "dolum_ms": 3200, "kayma_trader": -0.0001},
    {"olay": "emir", "eylem": "kapat", "usd_dolan": 7.0, "trader_dolum_ms": None, "dolum_ms": 4000, "gorme_ms": 4100, "kayma_trader": None},
    {"olay": "emir", "eylem": "ac", "usd_dolan": 0.0, "trader_dolum_ms": 1, "dolum_ms": 99999, "gorme_ms": 99999, "kayma_trader": 0.5},   # dolmadı: sayılmaz
    {"olay": "emir_yok", "eylem": "ac", "neden": "x"},                                                                          # emir değil: sayılmaz
]


def test_altin_ornek_genel_ve_gruplar():
    q = go.kopya_kalite(ALTIN)
    assert q["n"] == 4
    assert q["gecikme_ms_medyan"] == 400 and q["gecikme_ms_p90"] == 900
    assert q["gorme_ms_medyan"] == 200
    assert q["kayma_bps_medyan"] == pytest.approx(2.0) and q["kayma_bps_p90"] == pytest.approx(6.0)
    ad, az = q["ac_artir"], q["azalt_kapat"]
    assert ad["n"] == 2 and ad["gecikme_ms_medyan"] == 650 and ad["kayma_bps_medyan"] == pytest.approx(4.0)
    assert az["n"] == 2 and az["gecikme_ms_medyan"] == 200 and az["kayma_bps_medyan"] == pytest.approx(-1.0)
    assert az["gorme_ms_medyan"] is None


def test_bos_veri_null():
    q = go.kopya_kalite([])
    assert q["n"] == 0
    for alan in ("gecikme_ms_medyan", "gecikme_ms_p90", "gorme_ms_medyan", "kayma_bps_medyan", "kayma_bps_p90"):
        assert q[alan] is None
    assert q["ac_artir"]["n"] == 0 and q["ac_artir"]["kayma_bps_medyan"] is None
    assert q["azalt_kapat"]["n"] == 0


def test_tek_kayit_ve_p90_en_yakin_sira():
    q = go.kopya_kalite([{"olay": "emir", "eylem": "ac", "usd_dolan": 1.0, "trader_dolum_ms": 10, "dolum_ms": 15, "kayma_trader": -0.0003}])
    assert q["n"] == 1 and q["gecikme_ms_medyan"] == 5 and q["gecikme_ms_p90"] == 5
    assert q["kayma_bps_medyan"] == pytest.approx(-3.0) and q["kayma_bps_p90"] == pytest.approx(-3.0)
    assert q["gorme_ms_medyan"] is None                                     # gorme_ms yok → atlanır
    on = [{"olay": "emir", "eylem": "ac", "usd_dolan": 1.0, "trader_dolum_ms": 0, "dolum_ms": g} for g in range(1, 11)]
    assert go.kopya_kalite(on)["gecikme_ms_p90"] == 9                       # n=10 → ceil(9)=9. değer


def test_olustur_kopya_kalite_alani_sonda(tmp_path):
    from tests.test_gunluk_ozet import _motor
    m, _saat = _motor(tmp_path)
    m.kayit({"olay": "emir", "eylem": "ac", "usd_dolan": 10.0, "trader_dolum_ms": 1000, "dolum_ms": 1400, "kayma_trader": 0.0002})
    o = go.olustur(m, {})
    assert list(o)[-1] == "kopya_kalite"
    assert o["kopya_kalite"]["n"] == 1 and o["kopya_kalite"]["gecikme_ms_medyan"] == 400
    assert o["kopya_kalite"]["kayma_bps_medyan"] == pytest.approx(2.0)


def test_pano_karti_var_ve_bos_veri_aciklamasi():
    from copytrade.canli import pano
    ozet = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0}
    bos = pano.html_olustur(ozet, {}, {}, [], [], 1_793_900_000_000)
    assert "Kopya kalitesi" in bos and "dolan emir yok" in bos
    kayit = {"olay": "emir", "zaman_ms": 1_793_899_000_000, "coin": "BTC", "yon": "B", "eylem": "ac", "durum": "dolu", "usd_dolan": 10.0,
             "trader_dolum_ms": 1_793_898_000_000, "dolum_ms": 1_793_898_400_000, "gorme_ms": 1_793_898_100_000, "kayma_trader": 0.0002}
    dolu = pano.html_olustur(ozet, {}, {}, [kayit], [], 1_793_900_000_000)
    assert "Kopya kalitesi" in dolu and "medyan 400,0 sn" in dolu and "medyan 100,0 sn" in dolu and "+2,0 bp" in dolu     # 400 000 ms = 400,0 sn
