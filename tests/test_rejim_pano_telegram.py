"""Rejim × sonuç görünümü (yalnız bilgi): pano kartı (`durum/paylasim/rejim_sonuc_v1.json`) ve haftalık Telegram'ın tek rejim satırı. Ağsız."""
from __future__ import annotations

from copytrade.canli import pano
from copytrade.canli import telegram as tg


def _satir(etiket, n, toplam):
    return {"etiket": etiket, "n": n, "kazanan": 0, "isabet_yuzde": 0.0, "toplam_pnl": toplam, "ortalama_pnl": round(toplam / n, 2) if n else 0.0}


RS = {"sema": "ct.rejim_sonuc.v1", "pencere_gun": 7, "tablolar": {
    "rejim_1d": [_satir("bilinmiyor", 9, 500.0), _satir("range", 4, -30.0), _satir("trend_up", 6, 45.0)],
    "rejim_4h": [_satir("range", 4, -30.0), _satir("trend_up", 6, 45.0)],
    "duygu": [_satir("Fear", 3, 12.0)]}}


# ---------------------------------------------------------------- Telegram: tek satır
def test_rejim_satiri_en_iyi_en_kotu_bilinmiyor_haric():
    s = tg.rejim_satiri(RS["tablolar"]["rejim_1d"])
    assert s == "🧭 Rejim (7g): en iyi trend_up 1g +45,00 $ (n=6), en kötü range 1g −30,00 $ (n=4)"


def test_rejim_satiri_bilinen_kova_yoksa_none():
    assert tg.rejim_satiri(None) is None
    assert tg.rejim_satiri([]) is None
    assert tg.rejim_satiri([_satir("bilinmiyor", 3, 10.0)]) is None
    assert tg.rejim_satiri([_satir("range", 0, 0.0)]) is None           # boş kova sayılmaz


def test_msg_haftalik_rejim_yoksa_eski_cikti_ayni():
    eski = tg.msg_haftalik("sanal", 1000.0, 1030.0, 1000.0, 105.0, 100.0, 42, [("0xaaaaaaaaaaaa", 20.0)])
    yeni = tg.msg_haftalik("sanal", 1000.0, 1030.0, 1000.0, 105.0, 100.0, 42, [("0xaaaaaaaaaaaa", 20.0)], rejim=None)
    assert yeni == eski and "🧭" not in eski


def test_msg_haftalik_rejim_satiri_sonda():
    metin = tg.msg_haftalik("sanal", 1000.0, 1030.0, 1000.0, 105.0, 100.0, 42, [], rejim=RS["tablolar"]["rejim_1d"])
    son = metin.splitlines()[-1]
    assert son.startswith("🧭 Rejim (7g): en iyi trend_up 1g")
    assert metin.count("🧭") == 1


# ---------------------------------------------------------------- Pano kartı
def test_pano_rejim_karti_veri_yoksa_veri_yok():
    assert "veri birikiyor" in pano._rejim_sonuc_html(None)
    assert "veri birikiyor" in pano._rejim_sonuc_html({})
    assert "veri birikiyor" in pano._rejim_sonuc_html({"tablolar": {"rejim_1d": [], "rejim_4h": [], "duygu": []}})


def test_pano_rejim_karti_uc_tablo_ve_kacis():
    veri = {"tablolar": {**RS["tablolar"], "duygu": [_satir("<b>x</b>", 1, 2.0)]}}
    h = pano._rejim_sonuc_html(veri)
    assert h.count("<table>") == 3
    assert "Rejim (1g)" in h and "Rejim (4s)" in h and "Duygu" in h
    assert "yükseliş" in h and "trend_up" not in h and "+45,00 $" in h and "%" in h
    assert "&lt;b&gt;x&lt;/b&gt;" in h and "<b>x</b>" not in h


def test_pano_html_rejim_karti_kwarg_ile_gelir_ve_kwarg_yoksa_veri_yok():
    ozet = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1010.0, "getiri": 0.01, "acik": [], "saha": 0, "saha_n": 0}
    h = pano.html_olustur(ozet, {}, {}, [], [], 1_800_000_000_000, rejim_sonuc=RS)
    assert "Rejim ve duygu × sonuç" in h and "yükseliş" in h
    h0 = pano.html_olustur(ozet, {}, {}, [], [], 1_800_000_000_000)
    assert "Rejim ve duygu × sonuç" in h0 and "veri birikiyor" in h0
