"""Pano ölçüm kartları (yalnız bilgi): Öğrenme etkisi, Kural maliyeti, Seçim × rastgele, Sunucu sağlığı satırları, sıralama ve "veri birikiyor". Ağsız."""
from __future__ import annotations

import re

import pytest

from copytrade.canli import pano

KOD_ADLARI = ("slot_tavani", "ml_filtre_atla", "hip3_atlandi", "ders_emekli", "bant_ici", "gec_acilis", "ders_kucultulen", "filtre_atlanan", "karsi_olgu", "K‑41", "K-41", "yeniden_baslama_1s", "oom_son")
OZET = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1010.0, "getiri": 0.01, "acik": [], "saha": 0, "saha_n": 0}
SIMDI = 1_800_000_000_000

OGRENME = {"aktif_ders": 4, "yeni_ders": 1, "emekli_ders": 2, "filtre_aktif": True, "filtre_atlanan": 7, "filtre_karsi_olgu_pnl": -12.5, "ders_kucultulen": 3, "ders_engellenen": 1}
KM = {"pencere_gun": 7, "satirlar": [
    {"neden": "slot_tavani", "olay_adedi": 40, "trader_sayisi": 5, "toplam_karsi_olgu_pnl": -31.2},
    {"neden": "ters_netlesme", "olay_adedi": 9, "trader_sayisi": 2, "toplam_karsi_olgu_pnl": 14.0},
    {"neden": "ml_filtre_atla", "olay_adedi": 12, "trader_sayisi": 4, "toplam_karsi_olgu_pnl": -5.0}],
    "vurgu": {"slot_tavani": {"neden": "slot_tavani", "olay_adedi": 40, "trader_sayisi": 5, "toplam_karsi_olgu_pnl": -31.2}}}
ISABET = [{"tarih": "2026-11-18", "rastgele_karsilastirma": {"durum": "tamam", "secilen_ortalama": 0.021, "rastgele_medyan": 0.008, "yuzdelik": 71.0, "p": 0.29}},
          {"tarih": "2026-11-19", "rastgele_karsilastirma": {"durum": "havuz_yok"}}]
SG = {"toplu": {"durum": "tamam", "gun_n": 5, "rho_ort": 0.12, "p": 0.31, "r": 1000}}
RS = {"pencere_gun": 7, "tablolar": {"rejim_1d": [{"etiket": "range", "n": 4, "kazanan": 2, "isabet_yuzde": 50.0, "toplam_pnl": -30.0, "ortalama_pnl": -7.5}], "rejim_4h": [{"etiket": "range", "n": 4, "kazanan": 2, "isabet_yuzde": 50.0, "toplam_pnl": -30.0, "ortalama_pnl": -7.5}], "duygu": [{"etiket": "Fear", "n": 1, "kazanan": 1, "isabet_yuzde": 100.0, "toplam_pnl": 3.0, "ortalama_pnl": 3.0}]}}
KAYIT = [{"zaman_ms": SIMDI - 3_600_000, "olay": "emir", "durum": "dolu", "adres": "0x" + "1" * 40, "coin": "BTC", "yon": "uzun", "usd_dolan": 50.0, "kayma_trader": 0.0004, "gecikme_ms": 1500, "gorme_ms": 800, "eylem": "ac"},
         {"zaman_ms": SIMDI - 3_600_000, "olay": "emir_yok", "neden": "bant_ici", "adres": "0x" + "1" * 40, "coin": "ETH", "eylem": "ac"}]
SAGLIK = {"yeniden_baslama_1s": 2, "oom_son": False}


def kart(html: str, baslik: str) -> str:
    """TEKNİK sekmesinde başlığı `baslik` ile başlayan açılır kartın (`<details class="td">`) iç HTML'i."""
    m = re.search(r'<details class="td"><summary><span>' + re.escape(baslik) + r'[^<]*</span>.*?</summary><div class="pi">(.*?)</div></details>', html, re.S)
    assert m, baslik
    return m.group(1)


def metin(h: str) -> str:
    return re.sub(r"<[^>]+>", " ", h)


def test_ogrenme_karti_veri_ve_bos():
    h = pano._ogrenme_html(OGRENME)
    assert h.count("<b>") == 6 and h.count('class="ha"') == 1
    assert "7" in h and "−12,50 $" in h and "Geçerli ders: <b>4" in h and "Emekli ders: <b>2" in h
    assert pano._ogrenme_html(None) == pano.BIRIKIYOR and pano._ogrenme_html({}) == pano.BIRIKIYOR
    assert "—" in pano._ogrenme_html({"filtre_atlanan": 0, "filtre_karsi_olgu_pnl": None, "ders_kucultulen": None, "ders_engellenen": 0})


def test_kural_maliyet_karti_slot_tavani_ilk_satir():
    h = pano._kural_maliyet_html(KM)
    assert h.index("Yer sınırı") < h.index("ters netleşme") < h.index("ML filtresi")
    assert "40 sinyal · 5 trader · −31,20 $" in h and "K‑41" not in h
    assert pano._kural_maliyet_html(None) == pano.BIRIKIYOR and pano._kural_maliyet_html({"satirlar": []}) == pano.BIRIKIYOR
    assert "yok" in pano._kural_maliyet_html({"satirlar": [KM["satirlar"][1]], "vurgu": {"slot_tavani": None}})


def test_secim_rastgele_karti_iki_kaynak_ve_bos():
    h = pano._secim_rastgele_html(ISABET, SG)                       # isabet verisi öncelikli
    assert "+%2,10" in h and "+%0,80" in h and "%29" in h and "Ölçülen gün: <b>1" in h
    g = pano._secim_rastgele_html([], SG)                           # yedek: form × gerçek K/Z
    assert "Ölçülen gün: <b>5" in g and "+0,12" in g
    assert pano._secim_rastgele_html([], None) == pano.BIRIKIYOR
    assert pano._secim_rastgele_html(ISABET[1:], {"toplu": {"durum": "yok", "gun_n": 0}}) == pano.BIRIKIYOR


def test_sunucu_sagligi_satirlari():
    h = pano._kaynak_html({"ram_mb": 100.0, "olc_ms": None}, SAGLIK)
    assert "yeniden başlama (son 1 sa): 2" in h and "bellek yetmediği için kapanma (son 1 sa): yok" in h
    assert "kapanma (son 1 sa): var" in pano._kaynak_html({"ram_mb": 1.0}, {"yeniden_baslama_1s": None, "oom_son": True})
    assert "RAM:" in pano._kaynak_html({"ram_mb": 1.0}, None) and "yeniden başlama" not in pano._kaynak_html({"ram_mb": 1.0}, None)
    assert "yeniden başlama (son 1 sa): 2" in pano._kaynak_html(None, SAGLIK)       # kaynak ölçümü yok ama sağlık var
    assert pano._kaynak_html(None, None) == pano.BIRIKIYOR and pano._kaynak_html({}, {"yeniden_baslama_1s": None, "oom_son": None}) == pano.BIRIKIYOR


def _tam() -> str:
    return pano.html_olustur(OZET, {}, {}, KAYIT, [], SIMDI, isabetler=ISABET, kaynak={"ram_mb": 300.0, "disk_bos_gb": 9.0}, rejim_sonuc=RS, gunluk_ozet={"ogrenme": OGRENME, "saglik": SAGLIK},
                             kural_maliyet=KM, secim_gercek=SG)


def _bos() -> str:
    return pano.html_olustur(OZET, {}, {}, [], [], SIMDI)


BASLIKLAR = ["Sunucu kaynakları", "Kural maliyeti", "Alınmayan sinyaller", "Rejim × duygu", "Kopya kalitesi", "Seçim × rastgele", "Öğrenme etkisi"]


def test_kartlar_teknik_sekmesinde_ve_baska_sekmede_yok():
    h = _tam()
    n6 = h[h.index('<section class="n6'):h.index("</section>", h.index('<section class="n6'))]
    assert all(f"<span>{b}" in n6 for b in BASLIKLAR)
    assert all("<details" in n6 for _ in BASLIKLAR)                                  # hepsi açılır kart
    diger = h[h.index('<section class="n1'):h.index('<section class="n6')]
    assert all(f"<span>{b}" not in diger and f'<div class="pb">{b}' not in diger for b in BASLIKLAR)             # tekrar yok


@pytest.mark.parametrize("baslik", BASLIKLAR)
def test_kart_veri_birikiyor_ve_kod_adi_yok(baslik):
    k0 = kart(_bos(), baslik)
    assert "veri birikiyor" in k0 and "veri yok" not in k0
    k1 = metin(kart(_tam(), baslik))
    assert "veri birikiyor" not in k1
    assert not [a for a in KOD_ADLARI if a in k1], k1


@pytest.mark.parametrize("baslik", ["Öğrenme etkisi", "Kural maliyeti", "Seçim × rastgele"])
def test_yeni_kart_3_ile_6_rakam_tek_aciklama(baslik):
    k = kart(_tam(), baslik)
    assert 3 <= k.count("<b>") <= 6 and k.count('class="ha"') == 1


def test_alinmayan_karti_k41_atilir():
    h = pano._alinmayan_neden_html([{"neden": "ters_netlesme", "adet": 2, "karsi_olgu_kapanan": 1, "karsi_olgu_pnl": 3.0}])
    assert "ters netleşme" in h and "K‑41" not in h


def test_bilinmeyen_neden_kodu_ham_gorunmez_diger_yazar():
    from copytrade.canli import pano
    h = pano._alinmayan_neden_html([{"neden": "yeni_teknik_kod", "adet": 3, "karsi_olgu_kapanan": 0, "karsi_olgu_pnl": None}])
    assert "diğer" in h and "yeni_teknik_kod" not in h and "ALINSAYDI K/Z" in h
