"""A/B teşhisi (`copytrade/kapi_ab.py`): aynı API yanıtı iki kod sürümüne verilir; `sure_*` ve `kod_hash` dışındaki farklar sayılır."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from copytrade import kapi_ab
from copytrade.kurallar import load_rules

RULES = load_rules()


class Gercek:
    """Canlı uç taklidi: her çağrıda FARKLI değer döner (canlı portfolio gibi); hatalı adres 500 verir."""

    def __init__(self):
        self.sayac = 0

    def portfolio(self, adres):
        self.sayac += 1
        if adres == "0xhata":
            raise RuntimeError("HTTPError: 500")
        return {"son": self.sayac}

    def dex_adlari(self):
        return []


def modul(ad_hash, hesapla, sure=1.0):
    def evaluate_address(lider, client, cache, now, start, start_200, symbols, rules, yalniz_adim5=False, log=None, dexes=None, gunluk=None):
        satir = {"address": lider["address"], "kod_hash": ad_hash, "sure_toplam_sn": sure}
        try:
            satir["deger"] = hesapla(client.portfolio(lider["address"]))
        except Exception as hata:
            satir["hata"] = f"{type(hata).__name__}: {hata}"
        return satir
    return SimpleNamespace(evaluate_address=evaluate_address, CandleCache=lambda *a, **k: None, hip3_dex_names=lambda c: [], HESAP_KOD_HASH=ad_hash)


def tablo():
    satirlar = [{"address": f"0x{i:04d}", "account_value": 1000.0 + i, "kaynak": "leaderboard", "now_ms": 1_793_000_000_000, "asama1": "Geçti"} for i in range(10)]
    satirlar.append({"address": "0xhata", "account_value": 1.0, "kaynak": "leaderboard", "now_ms": 1_793_000_000_000, "asama1": "Geçti", "hata": "HTTPError: 500"})
    return pd.DataFrame(satirlar)


def test_ayni_hesap_farkli_sure_ve_hash_fark_yok_yanit_bir_kez_cekilir():
    gercek = Gercek()
    istemci = kapi_ab.TekrarIstemci(gercek)
    ozet = kapi_ab.karsilastir(modul("a" * 64, lambda p: p["son"] * 2, sure=1.0), modul("b" * 64, lambda p: p["son"] * 2, sure=99.0), istemci, tablo(), 4, 1, set(), RULES, log=lambda *_: None)
    assert (ozet["karsilastirilan_adres"], ozet["basarili"], ozet["hatali"], ozet["fark_olan_adres"], ozet["fark_toplam_sutun"]) == (5, 4, 1, 0, 0)
    assert gercek.sayac == 5 and istemci.cagri["portfolio"] == 5                 # her adres için API TEK çağrı: iki koda aynı yanıt (canlı uç iki çağrıda farklı dönerdi)
    assert ozet["kontrol_disi"] == ["sure_", "kod_hash"] and kapi_ab.KONTROL_DISI == ("sure_",)


def test_hesap_farki_yakalanir_ve_ornek_gosterilir():
    ozet = kapi_ab.karsilastir(modul("a" * 64, lambda p: p["son"]), modul("b" * 64, lambda p: p["son"] + 1), kapi_ab.TekrarIstemci(Gercek()), tablo(), 3, 0, set(), RULES, log=lambda *_: None)
    assert ozet["fark_olan_adres"] == 3 and ozet["fark_toplam_sutun"] == 3
    assert ozet["ayrinti"][0]["fark"] == ["deger"] and set(ozet["ayrinti"][0]["ornek"]["deger"]) != {None}


def test_hata_bir_kez_alinir_iki_koda_ayni_hata_verilir():
    gercek = Gercek()
    ozet = kapi_ab.karsilastir(modul("a" * 64, lambda p: 1), modul("b" * 64, lambda p: 1), kapi_ab.TekrarIstemci(gercek), tablo(), 0, 1, set(), RULES, log=lambda *_: None)
    assert ozet["hatali"] == 1 and ozet["fark_olan_adres"] == 0 and gercek.sayac == 1


def test_kontrol_disi_sabiti_kodda_acik():
    assert kapi_ab.kontrol_disi("sure_toplam_sn") and kapi_ab.kontrol_disi("kod_hash") and not kapi_ab.kontrol_disi("return_12m")


def test_modul_yukle_ayri_kopya_yukler_calisan_paketi_bozmaz(tmp_path):
    import shutil
    from pathlib import Path
    import sys
    import copytrade.kapi as calisan
    kopya = tmp_path / "ana"
    shutil.copytree(Path(calisan.__file__).parent, kopya / "copytrade", ignore=shutil.ignore_patterns("__pycache__"))
    yuklenen = kapi_ab.modul_yukle(kopya)
    assert yuklenen is not calisan and yuklenen.HESAP_KOD_HASH == calisan.HESAP_KOD_HASH and yuklenen.__file__.startswith(str(kopya))
    assert sys.modules["copytrade.kapi"] is calisan and str(kopya) not in sys.path
