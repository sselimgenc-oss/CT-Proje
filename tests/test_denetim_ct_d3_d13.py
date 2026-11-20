"""CT denetimi düşük bulgular (D4–D13): her biri için kırmızı→yeşil test."""
from __future__ import annotations

import pytest

from tests.test_canli_motor import adr, kur, olay


def test_d4_artirma_dolmayan_azalt_kuyrugunu_iptal_eder(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    anahtar = f"{adr(1)}|BTC"
    m.kapanis_kuyrugu[anahtar] = {"tur": "azalt", "hedef_sz": 0.05, "neden": "test", "deneme": 0, "ms": saat()}
    m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 300.0, saat))                 # trader artırdı
    assert anahtar not in m.kapanis_kuyrugu


def test_d4_kapat_kuyrugu_artirmada_korunur(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    anahtar = f"{adr(1)}|BTC"
    m.kapanis_kuyrugu[anahtar] = {"tur": "kapat", "hedef_sz": 0.0, "neden": "test", "deneme": 0, "ms": saat()}
    m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 300.0, saat))
    assert anahtar in m.kapanis_kuyrugu


def test_d5_trader_esigi_tek_sabit_toz_kalinti_kapat_sayilir():
    from copytrade.canli import motor as mt
    assert mt.TR_EPS == 1e-9
    assert mt.eylem_belirle(1.0, 5e-10, 1.0) == ["kapat"]                     # poz_tr de 5e-10'u 0 sayar: ikisi tutarlı
    assert mt.eylem_belirle(1.0, 1e-8, 1.0) == ["azalt"]


def test_d7_yetim_borsa_stopu_dinamik_orani_kullanir_birim():
    from copytrade.canli import borsa_stop as bs
    sabit = bs.yetim_hedefler({"ETH": {"sz": 0.5, "mark": 2000.0}}, {}, 0.22, 10.0)
    assert sabit["ETH#yetim"]["tetik"] == pytest.approx(1560.0)
    dinamik = bs.yetim_hedefler({"ETH": {"sz": 0.5, "mark": 2000.0}}, {}, 0.22, 10.0, lambda c, uzun, ref: 0.19)
    assert dinamik["ETH#yetim"]["tetik"] == pytest.approx(1620.0)


def test_d7_yetim_borsa_stopu_motorda_dinamik_stop_acikken_dar_tetik(tmp_path, monkeypatch):
    from tests.test_denetim_1117_yetim import _dk, _hazir
    m, sim, saat, tgp = _hazir(tmp_path, monkeypatch)
    m.rules["dinamik_stop"] = True
    m._hl_maks_kaldirac = {"ETH": 3.0}                                       # 3x azami: tasfiye mesafesi %20 → stop %19
    sim.poz["ETH"] = 0.5
    _dk(m, saat, 2)
    st = [e for e in sim.acik if e["coin"] == "ETH"]
    assert len(st) == 1 and float(st[0]["triggerPx"]) == pytest.approx(1620.0)


def test_d10_gunluk_ozet_metin_kurulamazsa_gun_isareti_atilmaz(tmp_path):
    from datetime import UTC, datetime
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    simdi = int(datetime(2026, 11, 20, 23, 0, tzinfo=UTC).timestamp() * 1000)
    m._ozet_gunu = None
    gercek = m._gunluk_metin

    def bozuk():
        raise RuntimeError("metin kurulamadı")
    m._gunluk_metin = bozuk
    with pytest.raises(RuntimeError):
        m._gunluk_ozet(simdi)
    assert m._ozet_gunu != "2026-11-20"                                      # işaret atılmadı: sonraki dakikada yeniden denenir
    m._gunluk_metin = gercek
    m._gunluk_ozet(simdi)
    assert m._ozet_gunu == "2026-11-20"


def test_d10_haftalik_ozet_metin_kurulamazsa_hafta_isareti_atilmaz(tmp_path):
    from datetime import UTC, datetime
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    simdi = int(datetime(2026, 11, 22, 19, 0, tzinfo=UTC).timestamp() * 1000)          # pazar
    m._hafta_gunu = None
    gercek = m.haftalik_metin

    def bozuk():
        raise RuntimeError("metin kurulamadı")
    m.haftalik_metin = bozuk
    with pytest.raises(RuntimeError):
        m._haftalik_ozet(simdi)
    assert m._hafta_gunu != "2026-11-22"
    m.haftalik_metin = gercek
    m._haftalik_ozet(simdi)
    assert m._hafta_gunu == "2026-11-22"
