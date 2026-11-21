"""Anlık kaldıraç (trader nosyonel / hesap değeri) + gölge kurallar (yalnız kayıt) + pano gösterimi. Elle hesaplanmış altın örnekler; ağsız."""

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import pano
from tests.test_canli_motor import adr, kayitlar, kur, olay


def test_anlik_kaldirac_altin_ornek_ve_eksik_veri():
    poz = {"BTC": 2.0, "ETH": -10.0}
    marks = {"BTC": 50_000.0, "ETH": 2_000.0}                      # nosyonel = 100.000 + 20.000 = 120.000
    assert mt.anlik_kaldirac_hesapla(poz, marks, 24_000.0) == pytest.approx(5.0)
    assert mt.anlik_kaldirac_hesapla({}, marks, 24_000.0) == 0.0     # pozisyonsuz = 0x (bilinmiyor değil)
    assert mt.anlik_kaldirac_hesapla(poz, {"BTC": 50_000.0}, 24_000.0) is None   # ETH mark'ı yok
    assert mt.anlik_kaldirac_hesapla(None, marks, 24_000.0) is None
    assert mt.anlik_kaldirac_hesapla(poz, marks, None) is None
    assert mt.anlik_kaldirac_hesapla(poz, marks, 0.0) is None
    assert mt.anlik_kaldirac_hesapla({"BTC": 0.0}, {}, 100.0) == 0.0


def test_trader_kaldirac_adimi_yalniz_bilgi_yazar_karar_yolu_degismez(tmp_path):
    """K-86: gölge kurallar silindi; trader kaldıracı yalnız pano bilgisi (`kaldirac_tr`)."""
    m, _, saat, _ = kur(tmp_path)
    m.baslat()
    a = adr(1)
    kadro_once = dict(m.saha.uyeler)
    m.marks["BTC"] = 100.0
    m.poz_tr[a] = {"BTC": 3000.0}                                   # nosyonel 300.000
    m.hesap_tr[a] = {"deger": 4000.0, "ms": saat()}                 # kaldıraç 75x
    m.trader_kaldirac_adimi(saat())
    assert m.kaldirac_tr[a]["anlik_kaldirac"] == pytest.approx(75.0) and m.kaldirac_tr[a]["hesap_usd"] == 4000.0
    assert not kayitlar(tmp_path, "golge_kural") and not hasattr(m, "_golge_acik")
    m.hesap_tr.pop(a)                                               # veri yok: kaldıraç None
    m.trader_kaldirac_adimi(saat())
    assert m.kaldirac_tr[a]["anlik_kaldirac"] is None
    assert dict(m.saha.uyeler) == kadro_once and not kayitlar(tmp_path, "emir")      # kadro ve emir yolu dokunulmadı


def test_dakika_kaldirac_adimi_calisir_hata_vermez(tmp_path):
    m, _, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 1, 100.0, 0.0, saat))
    m.dakika()
    assert not kayitlar(tmp_path, "adim_hata") and adr(1) in m.kaldirac_tr


def _html(kaldirac_tr, satir):
    ozet = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "acik": []}
    return pano.html_olustur(ozet, {}, {}, [], [], 1_793_900_000_000, {"kosu_ms": 1_793_863_000_000, "satirlar": [satir]}, {"uyeler": {}, "inen": {}}, kaldirac_tr=kaldirac_tr)
