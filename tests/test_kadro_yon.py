"""Paylaşım verisi `durum/paylasim/kadro_yon_v1.json` (ct.kadro_yon.v1): toplulaştırma, adres sızıntısı yok, eksik mark, durum_yaz dosyası."""
from __future__ import annotations

import json

import pytest

from copytrade.canli import motor as mt
from tests.test_canli_motor import adr, kadro, kur, satir


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _motor(tmp_path):
    k = kadro([satir(1, 1), satir(2, 2), satir(3, 3)], 0)
    m, _hl, saat, _ = kur(tmp_path, kadro_=k)
    k["kosu_ms"] = saat() - 3_600_000
    m.baslat()
    return m, saat


def test_toplulastirma_ve_siralama(tmp_path):
    m, saat = _motor(tmp_path)
    m.marks.update({"BTC": 100.0, "ETH": 10.0})
    m.poz_tr = {adr(1): {"BTC": 2.0, "ETH": -1.0}, adr(2): {"BTC": 1.0}, adr(3): {"BTC": -0.5}, adr(9): {"BTC": 1000.0}}   # adr(9) saha dışı (inen): sayılmaz
    simdi = saat()
    m._poz_tr_ms[(adr(1), "BTC")] = simdi - 30_000
    m._poz_tr_senk_ms[adr(2)] = simdi - 90_000
    o = m.kadro_yon_ozet(simdi)
    assert o["sema"] == "ct.kadro_yon.v1" and o["kip"] == m.kip and o["saha_trader_sayisi"] == len(m.saha.uyeler)
    btc, eth = o["coinler"]
    assert btc["coin"] == "BTC" and (btc["long_trader"], btc["short_trader"], btc["net_yon"]) == (2, 1, "long")
    assert btc["nominal_long_usd"] == 300.0 and btc["nominal_short_usd"] == 50.0 and btc["net_nominal_usd"] == 250.0
    assert btc["veri_yasi_sn"] == 90.0
    assert eth["coin"] == "ETH" and eth["net_yon"] == "short" and eth["net_nominal_usd"] == -10.0


def test_adres_sizintisi_yok(tmp_path):
    m, saat = _motor(tmp_path)
    m.marks["BTC"] = 100.0
    m.poz_tr = {adr(1): {"BTC": 1.0}}
    s = json.dumps(m.kadro_yon_ozet(saat()))
    assert "0x" not in s and "kasa" not in s and "ozsermaye" not in s


def test_eksik_mark_nominal_null_trader_sayilir(tmp_path):
    m, saat = _motor(tmp_path)
    m.marks.pop("XYZ", None)
    m.poz_tr = {adr(1): {"xyz:GOLD": 3.0}, adr(2): {"xyz:GOLD": -1.0}}
    (c,) = m.kadro_yon_ozet(saat())["coinler"]
    assert c["coin"] == "xyz:GOLD" and (c["long_trader"], c["short_trader"]) == (1, 1)
    assert c["nominal_long_usd"] is None and c["net_nominal_usd"] is None and c["net_yon"] == "notr"


def test_durum_yaz_dosyayi_yazar_ve_hata_yutulur(tmp_path):
    m, saat = _motor(tmp_path)
    m.marks["BTC"] = 100.0
    m.poz_tr = {adr(1): {"BTC": 1.0}}
    m.durum_yaz()
    yol = tmp_path / "durum" / "paylasim" / "kadro_yon_v1.json"
    veri = json.loads(yol.read_text(encoding="utf-8"))
    assert veri["coinler"][0]["coin"] == "BTC" and veri["notlar"].startswith("Trader pozisyonlarının toplamı")
    m.kadro_yon_ozet = lambda simdi: 1 / 0
    m.durum_yaz()                                                      # yükseltmez
