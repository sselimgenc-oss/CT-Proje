"""Toplu emir bandı (kullanıcı kararı 15.11; Fable önerisi): yalnız canlı motor (`bant=True`); radar kopya simülasyonu (`bant=False`) değişmez."""
from copytrade import boyut
import copytrade.kurallar as _k

R = _k.load_rules_asil()          # üretim değerleri (conftest testlerde bandı kapatır)
SLOT = 909.0


def _artir(biz_usd: float, hedef_usd: float, bant: bool) -> tuple[float, str]:
    # trader hesap 100.000 $, fiyat 1 → hedef = slot × poz / hesap ⇒ poz = hedef × hesap / slot
    return boyut.hedef_emir("artir", 0.0, hedef_usd * 100_000 / SLOT, 100_000, biz_usd, SLOT, 1.0, R, biz_usd, bant=bant)


def _azalt(biz_usd: float, hedef_usd: float, bant: bool) -> tuple[float, str]:
    return boyut.hedef_emir("azalt", 1.0, hedef_usd * 100_000 / SLOT, 100_000, biz_usd, SLOT, 1.0, R, biz_usd, bant=bant)


def test_kurallar():
    assert (R["canli_bant_usd"], R["canli_bant_oran"], R["canli_bant_azalt_usd"], R["canli_bant_azalt_oran"]) == (50, 0.10, 25, 0.05)


def test_artir_bant_ici_birikir_esik_asilinca_tek_emir():
    e, n = _artir(100.0, 130.0, bant=False)
    assert round(e, 6) == 30.0 and n == "tamam"                      # bantsız (radar): 30 $ emir
    assert _artir(100.0, 130.0, bant=True) == (0.0, "bant_ici")      # fark 30 < max(50, 13)
    e, n = _artir(100.0, 160.0, bant=True)
    assert round(e, 6) == 60.0 and n == "tamam"                      # birikmiş fark 60 ≥ 50 → hedefe tek emir
    assert _artir(1000.0, 1060.0, bant=True) == (0.0, "bant_ici")    # büyük hedefte oran: 60 < %10 × 1060 = 106
    e, n = _artir(1000.0, 1120.0, bant=True)
    assert round(e, 6) == 120.0 and n == "tamam"


def test_azalt_bant_dar_kucuk_kalan_ve_kapanis_muaf():
    assert _azalt(500.0, 480.0, bant=True) == (0.0, "bant_ici")      # 20 < max(25, 24)
    e, n = _azalt(500.0, 470.0, bant=True)
    assert round(e, 6) == 30.0 and n == "tamam"
    e, n = _azalt(500.0, 480.0, bant=False)
    assert round(e, 6) == 20.0 and n == "tamam"                      # radar yolu değişmez
    assert _azalt(30.0, 5.0, bant=True) == (30.0, "kucuk_kalan_kapat")
    assert boyut.hedef_emir("kapat", 1.0, 0.0, 100_000, 40.0, SLOT, 1.0, R, bant=True) == (40.0, "tam_kapanis")


def test_acilis_muaf():
    e, n = boyut.hedef_emir("ac", 0.0, 3_000.0, 100_000, 0.0, SLOT, 1.0, R, 0.0, bant=True)
    assert round(e, 4) == round(SLOT * 3_000 / 100_000, 4) and n == "tamam"       # 27 $ açılış banda takılmaz
