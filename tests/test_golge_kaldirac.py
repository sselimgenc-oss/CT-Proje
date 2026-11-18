"""Anlık kaldıraç (trader nosyonel / hesap değeri) + gölge kurallar (yalnız kayıt) + pano gösterimi. Elle hesaplanmış altın örnekler; ağsız."""
import json

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import pano
from tests.test_canli_motor import RULES, adr, kayitlar, kur, olay


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


def test_golge_kurallar_yalniz_durum_degisiminde_kayit_ve_karar_yolu_degismez(tmp_path):
    assert (RULES["golge_hesap_alt_usd"], RULES["golge_kaldirac_uyari"], RULES["golge_kaldirac_cikar"]) == (5000, 5, 20)
    m, _, saat, _ = kur(tmp_path)
    m.baslat()
    a = adr(1)
    kadro_once = dict(m.saha.uyeler)
    m.marks["BTC"] = 100.0
    m.poz_tr[a] = {"BTC": 3000.0}                                   # nosyonel 300.000
    m.hesap_tr[a] = {"deger": 4000.0, "ms": saat()}                 # kaldıraç 75x, hesap < 5000
    m.golge_kural_adimi(saat())
    m.golge_kural_adimi(saat())                                     # ikinci çağrı: değişim yok → yeni kayıt yok
    ev = kayitlar(tmp_path, "golge_kural")
    assert sorted(e["kural"] for e in ev) == ["A_hesap_5k", "B_kaldirac_20x", "B_kaldirac_5x"] and all(e["durum"] == "basladi" and e["adres"] == a for e in ev)
    assert m.kaldirac_tr[a]["anlik_kaldirac"] == pytest.approx(75.0) and m.kaldirac_tr[a]["hesap_usd"] == 4000.0
    m.hesap_tr[a] = {"deger": 20_000.0, "ms": saat()}               # kaldıraç 15x: A ve B2 biter, B1 sürer
    m.golge_kural_adimi(saat())
    yeni = kayitlar(tmp_path, "golge_kural")[3:]
    assert sorted((e["kural"], e["durum"]) for e in yeni) == [("A_hesap_5k", "bitti"), ("B_kaldirac_20x", "bitti")]
    m.poz_tr[a] = {}                                                # kaldıraç 0x: B1 biter
    m.golge_kural_adimi(saat())
    assert [(e["kural"], e["durum"]) for e in kayitlar(tmp_path, "golge_kural")[5:]] == [("B_kaldirac_5x", "bitti")] and a not in m._golge_acik
    m.hesap_tr.pop(a)                                               # veri yok: kural durumu değişmez, kayıt yok, kaldıraç None
    m.golge_kural_adimi(saat())
    assert len(kayitlar(tmp_path, "golge_kural")) == 6 and m.kaldirac_tr[a]["anlik_kaldirac"] is None
    assert dict(m.saha.uyeler) == kadro_once and not kayitlar(tmp_path, "emir")      # kadro ve emir yolu dokunulmadı


def test_golge_durum_motor_jsona_yazilir_ve_yeniden_baslatmada_tekrar_basladi_yazmaz(tmp_path):
    m, _, saat, _ = kur(tmp_path)
    m.baslat()
    a = adr(1)
    m.hesap_tr[a] = {"deger": 1000.0, "ms": saat()}
    m.golge_kural_adimi(saat())
    m.durum_yaz()
    mj = json.loads((tmp_path / "durum" / "motor.json").read_text(encoding="utf-8"))
    assert mj["golge_acik"] == {a: ["A_hesap_5k"]} and mj["kaldirac_tr"][a]["hesap_usd"] == 1000.0 and mj["kaldirac_tr"][a]["anlik_kaldirac"] == 0.0
    m2, _, saat2, _ = kur(tmp_path)
    m2.baslat()
    m2.hesap_tr[a] = {"deger": 1000.0, "ms": saat2()}
    m2.golge_kural_adimi(saat2())
    assert len(kayitlar(tmp_path, "golge_kural")) == 1


def test_dakika_golge_adimi_calisir_hata_vermez(tmp_path):
    m, _, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 1, 100.0, 0.0, saat))
    m.dakika()
    assert not kayitlar(tmp_path, "adim_hata") and adr(1) in m.kaldirac_tr


def _html(kaldirac_tr, satir):
    ozet = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "acik": []}
    return pano.html_olustur(ozet, {}, {}, [], [], 1_793_900_000_000, {"kosu_ms": 1_793_863_000_000, "satirlar": [satir]}, {"uyeler": {}, "inen": {}}, kaldirac_tr=kaldirac_tr)


def test_pano_kart_anlik_kaldirac_ve_radar_etiketi_ve_eksik_veri():
    a = "0xaaaa111122223333"
    satir = {"adres": a, "sira": 1, "katman": "ilk11", "form": 75.0, "kopya_getiri_7g": 0.014, "max_kaldirac": 7.5}
    h = _html({a: {"anlik_kaldirac": 3.26, "hesap_usd": 12345.0, "ms": 1}}, satir)
    assert "Anlık kaldıraç" in h and "3,3x (hesap 12.345 $)" in h
    assert "Radar azami (7g)" in h and "7,5x" in h and "Azami kaldıraç" not in h
    h2 = _html(None, satir)                                                  # veri yok → "—"
    assert "Anlık kaldıraç</span><br>—" in h2 and "7,5x" in h2
    h3 = _html({a: {"anlik_kaldirac": None, "hesap_usd": None}}, {**satir, "max_kaldirac": None})
    assert "Anlık kaldıraç</span><br>—" in h3 and "Radar azami (7g)</span><br>—" in h3
