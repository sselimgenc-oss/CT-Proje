"""Alınmayan sinyal neden dağılımı (`gunluk_ozet.alinmayan_neden`, JSON `alinmayan_neden`, pano kartı): altın örnek, ML çift sayım koruması, boş veri. YALNIZ BİLGİ.

Altın örnek (elle hesaplandı):
  emir_yok : ml_filtre_atla ×2, ders_emekli ×1, bant_ici ×3, neden yok ×1
  ml_filtre_atla olayı (motordaki aynı 2 atlamanın olay kaydı): ×2  → ML adedi max(2, 2) = 2 (çift sayılmaz)
  karsi_olgu_kapandi: ml_filtre_atla −10,0 ve −2,5; hip3_atlandi +50,0 (bugün atlama yok); ders_emekli pnl yok
  Beklenen sıra (adet azalan, eşitlikte neden adı): bant_ici 3 · ml_filtre_atla 2 · "?" 1 · ders_emekli 1 · hip3_atlandi 0
"""
from __future__ import annotations

from copytrade.canli import gunluk_ozet as go
from copytrade.canli import pano
from tests.test_gunluk_ozet import _motor

ALTIN = [
    {"olay": "emir_yok", "neden": "ml_filtre_atla", "eylem": "ac"},
    {"olay": "emir_yok", "neden": "ml_filtre_atla", "eylem": "ac"},
    {"olay": "ml_filtre_atla", "kurulum": "T_aaaaaa", "coin": "BTC"},
    {"olay": "ml_filtre_atla", "kurulum": "T_aaaaaa", "coin": "ETH"},
    {"olay": "emir_yok", "neden": "ders_emekli", "eylem": "ac"},
    {"olay": "emir_yok", "neden": "bant_ici", "eylem": "ac"},
    {"olay": "emir_yok", "neden": "bant_ici", "eylem": "ac"},
    {"olay": "emir_yok", "neden": "bant_ici", "eylem": "artir"},
    {"olay": "emir_yok", "eylem": "ac"},                                   # neden yok → "?"
    {"olay": "karsi_olgu_kapandi", "neden": "ml_filtre_atla", "pnl_usd": -10.0},
    {"olay": "karsi_olgu_kapandi", "neden": "ml_filtre_atla", "pnl_usd": -2.5},
    {"olay": "karsi_olgu_kapandi", "neden": "hip3_atlandi", "pnl_usd": 50.0},     # bugün atlama yok: yalnız kapanış
    {"olay": "karsi_olgu_kapandi", "neden": "ders_emekli", "pnl_usd": None},      # kapanış var, pnl yok → null
    {"olay": "emir", "eylem": "ac", "durum": "dolu", "usd_dolan": 10.0},         # emir değil: sayılmaz
]

BEKLENEN = [
    {"neden": "bant_ici", "adet": 3, "karsi_olgu_kapanan": 0, "karsi_olgu_pnl": None},
    {"neden": "ml_filtre_atla", "adet": 2, "karsi_olgu_kapanan": 2, "karsi_olgu_pnl": -12.5},
    {"neden": "?", "adet": 1, "karsi_olgu_kapanan": 0, "karsi_olgu_pnl": None},
    {"neden": "ders_emekli", "adet": 1, "karsi_olgu_kapanan": 1, "karsi_olgu_pnl": None},
    {"neden": "hip3_atlandi", "adet": 0, "karsi_olgu_kapanan": 1, "karsi_olgu_pnl": 50.0},
]


def test_altin_ornek_satirlar_ve_sira():
    assert go.alinmayan_neden(ALTIN) == BEKLENEN


def test_ml_olay_yalniz_ise_olay_sayisi_kullanilir():
    # motor emir_yok yazmadıysa (yalnız ml_filtre_atla olayı) adet olay sayısıdır
    satirlar = go.alinmayan_neden([{"olay": "ml_filtre_atla"}] * 3)
    assert satirlar == [{"neden": "ml_filtre_atla", "adet": 3, "karsi_olgu_kapanan": 0, "karsi_olgu_pnl": None}]


def test_bos_veri_bos_liste():
    assert go.alinmayan_neden([]) == []
    assert go.alinmayan_neden([{"olay": "emir", "usd_dolan": 1.0}]) == []


def test_olustur_alinmayan_neden_alani_kopya_kaliteden_once(tmp_path):
    m, _saat = _motor(tmp_path)
    m.kayit({"olay": "emir_yok", "adres": "0x" + "1" * 40, "coin": "ETH", "neden": "bant_ici", "eylem": "ac"})
    o = go.olustur(m, {})
    assert list(o)[-2:] == ["alinmayan_neden", "kopya_kalite"]                  # yeni alan sonda değil; kopya_kalite son kalır
    assert o["alinmayan_neden"] == [{"neden": "bant_ici", "adet": 1, "karsi_olgu_kapanan": 0, "karsi_olgu_pnl": None}]
    assert o["islem"]["alinmayan_sinyal"] == 1                                    # mevcut alan değişmedi


def test_pano_karti_altin_ve_bos():
    assert pano._alinmayan_neden_html([]) == pano.BIRIKIYOR
    html = pano._alinmayan_neden_html(go.alinmayan_neden(ALTIN))
    assert "ALINSAYDI K/Z $" in html
    assert "toplu emir bekliyor (fark küçük)" in html                              # etiketler telegram.ATLA_TR'den
    assert "ML filtresi (düşük puan)" in html
    assert "−12,00" not in html and "−12,50 $" in html                             # ml_filtre_atla karşı-olgu toplamı −12,50 $
