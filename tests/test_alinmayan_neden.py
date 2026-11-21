"""Alınmayan sinyal neden dağılımı (`gunluk_ozet.alinmayan_neden`, JSON `alinmayan_neden`, pano kartı): altın örnek, boş veri. YALNIZ BİLGİ.

Altın örnek (elle hesaplandı):
  emir_yok : yon_tavani ×2, hak_bitti ×1, kucuk_hareket ×3, neden yok ×1
  karsi_olgu_kapandi: yon_tavani −10,0 ve −2,5; liste_disi +50,0 (bugün atlama yok); hak_bitti pnl yok
  Beklenen sıra (adet azalan, eşitlikte neden adı): kucuk_hareket 3 · yon_tavani 2 · "?" 1 · hak_bitti 1 · liste_disi 0
"""
from __future__ import annotations

from copytrade.canli import gunluk_ozet as go
from copytrade.canli import pano
from tests.test_gunluk_ozet import _motor

ALTIN = [
    {"olay": "emir_yok", "neden": "yon_tavani", "eylem": "ac"},
    {"olay": "emir_yok", "neden": "yon_tavani", "eylem": "ac"},
        {"olay": "emir_yok", "neden": "hak_bitti", "eylem": "ac"},
    {"olay": "emir_yok", "neden": "kucuk_hareket", "eylem": "ac"},
    {"olay": "emir_yok", "neden": "kucuk_hareket", "eylem": "ac"},
    {"olay": "emir_yok", "neden": "kucuk_hareket", "eylem": "artir"},
    {"olay": "emir_yok", "eylem": "ac"},                                   # neden yok → "?"
    {"olay": "karsi_olgu_kapandi", "neden": "yon_tavani", "pnl_usd": -10.0},
    {"olay": "karsi_olgu_kapandi", "neden": "yon_tavani", "pnl_usd": -2.5},
    {"olay": "karsi_olgu_kapandi", "neden": "liste_disi", "pnl_usd": 50.0},     # bugün atlama yok: yalnız kapanış
    {"olay": "karsi_olgu_kapandi", "neden": "hak_bitti", "pnl_usd": None},      # kapanış var, pnl yok → null
    {"olay": "emir", "eylem": "ac", "durum": "dolu", "usd_dolan": 10.0},         # emir değil: sayılmaz
]

BEKLENEN = [
    {"neden": "kucuk_hareket", "adet": 3, "karsi_olgu_kapanan": 0, "karsi_olgu_pnl": None},
    {"neden": "yon_tavani", "adet": 2, "karsi_olgu_kapanan": 2, "karsi_olgu_pnl": -12.5},
    {"neden": "?", "adet": 1, "karsi_olgu_kapanan": 0, "karsi_olgu_pnl": None},
    {"neden": "hak_bitti", "adet": 1, "karsi_olgu_kapanan": 1, "karsi_olgu_pnl": None},
    {"neden": "liste_disi", "adet": 0, "karsi_olgu_kapanan": 1, "karsi_olgu_pnl": 50.0},
]


def test_altin_ornek_satirlar_ve_sira():
    assert go.alinmayan_neden(ALTIN) == BEKLENEN


def test_bos_veri_bos_liste():
    assert go.alinmayan_neden([]) == []
    assert go.alinmayan_neden([{"olay": "emir", "usd_dolan": 1.0}]) == []


def test_olustur_alinmayan_neden_alani_kopya_kaliteden_once(tmp_path):
    m, _saat = _motor(tmp_path)
    m.kayit({"olay": "emir_yok", "adres": "0x" + "1" * 40, "coin": "ETH", "neden": "kucuk_hareket", "eylem": "ac"})
    o = go.olustur(m, {})
    assert list(o)[-2:] == ["alinmayan_neden", "kopya_kalite"]                  # yeni alan sonda değil; kopya_kalite son kalır
    assert o["alinmayan_neden"] == [{"neden": "kucuk_hareket", "adet": 1, "karsi_olgu_kapanan": 0, "karsi_olgu_pnl": None}]
    assert o["islem"]["alinmayan_sinyal"] == 1                                    # mevcut alan değişmedi


def test_pano_karti_altin_ve_bos():
    assert pano._alinmayan_neden_html([]) == pano.BIRIKIYOR
    html = pano._alinmayan_neden_html(go.alinmayan_neden(ALTIN))
    assert "ALINSAYDI K/Z $" in html
    assert "küçük hareket (&lt; %10, hak tüketmez)" in html                              # etiketler telegram.ATLA_TR'den
    assert "yön tavanı (net %60)" in html
    assert "−12,00" not in html and "−12,50 $" in html                             # yon_tavani karşı-olgu toplamı −12,50 $
