"""Günlük kadro (copytrade/radar_kadro.py): sıra, katman, korelasyon, eksik koşu, şema. Ağsız."""
import json

import pytest

from copytrade import radar_kadro as k
from copytrade.kurallar import load_rules

RULES = load_rules()


def gecen(adres, g, kopya, i1=0.5, i2=0.01, y=0.5, h=0.5, gun=(0.0, 0.01), s72=0.0):
    return {"adres": adres, "gecti": True, "neden": None, "kopya_alt20": g, "kopya_getiri_7g": kopya, "kopya_kazanc_gun_orani": i1, "kopya_dusus": i2, "yayilma": y, "hype_payi": h,
            "kopya_getiri_72s": s72, "max_kaldirac": 4.0, "kopya_gunluk": list(gun)}


def elenen(adres, neden="islem_az"):
    return {"adres": adres, "gecti": False, "neden": neden}


def havuz(satirlar, evren_toplam=None):
    return {"sema": "radar-havuz-v1", "kosu_ms": 1_800_000_000_000, "pencere_bas_ms": 0, "evren_toplam": evren_toplam or len(satirlar), "evren_kesilen": 0, "satirlar": satirlar}


def test_kadro_altin_ornek_3_kisi_elle():
    """3 aday: yalnız G ve K değişir (diğer bileşenler eşit → hepsi %50): G/K sırası A (0,03/0,02) en iyi G; B en iyi K; C en kötü. Yüzdelik: A G100 K50, B G50 K100, C 0/0; eşit bileşenler (İ1, İ2, Y, H) üçü de %50.
    form A = 0,35×100 + 0,15×50 + (0,10 + 0,10 + 0,10 + 0,20) × 50 = 35 + 7,5 + 25 = 67,5; B = 17,5 + 15 + 25 = 57,5; C = 25. Slot (kasa 1.000) = 90,909 $, N = 11."""
    h = havuz([gecen("0xB", 0.02, 0.03), gecen("0xC", 0.01, 0.01), gecen("0xA", 0.03, 0.02), elenen("0xD")])
    kd = k.kadro_olustur(h, RULES)
    assert kd["sema"] == "radar-kadro-v1" and kd["kasa_usd"] == 1000.0 and kd["slot_usd"] == pytest.approx(1000 / 11) and kd["saha_n"] == 11 and kd["gecti_sayisi"] == 3
    assert [s["adres"] for s in kd["satirlar"]] == ["0xA", "0xB", "0xC"] and [s["sira"] for s in kd["satirlar"]] == [1, 2, 3]
    assert [s["form"] for s in kd["satirlar"]] == pytest.approx([67.5, 57.5, 25.0]) and {s["katman"] for s in kd["satirlar"]} == {"ilk11"}
    assert set(kd["satirlar"][0]) == {"adres", "sira", "katman", "form", "bilesenler", "kopya_getiri_7g", "max_kaldirac"}
    assert kd["korelasyon"]["adresler"] == ["0xA", "0xB", "0xC"]


def test_ilk11_yedek_19_ve_30_siniri():
    pool = [gecen(f"0x{i:02d}", 0.001 * i, 0.001 * i) for i in range(1, 41)]            # 40 aday, i büyük = iyi
    kd = k.kadro_olustur(havuz(pool), RULES)
    assert len(kd["satirlar"]) == 30 and kd["satirlar"][0]["adres"] == "0x40" and kd["satirlar"][29]["adres"] == "0x11"
    assert [s["katman"] for s in kd["satirlar"]].count("ilk11") == 11 and [s["katman"] for s in kd["satirlar"]].count("yedek") == 19
    assert kd["satirlar"][10]["katman"] == "ilk11" and kd["satirlar"][11]["katman"] == "yedek"
    assert len(kd["korelasyon"]["adresler"]) == 30 and kd["korelasyon"]["adresler"][11] == kd["satirlar"][11]["adres"]   # K-45 eki: korelasyon tüm kadro (Yedek boş slota girebilir)


def test_soguyan_kadroya_girmez_ve_kasa_degisince_slot():
    h = havuz([gecen("0xA", 0.03, 0.02), gecen("0xB", 0.02, 0.03, s72=-0.05)])
    kd = k.kadro_olustur(h, RULES, kasa_usd=100.0)
    assert [s["adres"] for s in kd["satirlar"]] == ["0xA"] and kd["soguyan"] == [{"adres": "0xB", "neden": "soguyor", "kopya_getiri_72s": -0.05}]
    assert kd["saha_n"] == 4 and kd["slot_usd"] == 25.0 and kd["kasa_usd"] == 100.0


def test_bos_havuz_bos_kadro_ve_sema_hatasi():
    kd = k.kadro_olustur(havuz([elenen("0xA"), elenen("0xB")]), RULES)
    assert kd["satirlar"] == [] and kd["gecti_sayisi"] == 0 and kd["korelasyon"]["adresler"] == []
    with pytest.raises(ValueError):
        k.kadro_olustur({**havuz([]), "sema": "yanlis"}, RULES)
    with pytest.raises(ValueError):
        k.kadro_olustur(havuz([]), RULES, kasa_usd=1001.0)


def test_eksik_kosu_zaman_yok_ve_satir_eksigi():
    assert k.kosu_tam_mi(havuz([elenen("0xA")]), RULES) == (True, None)
    assert k.kosu_tam_mi(havuz([elenen("0xA", "zaman_yok")]), RULES)[0] is False
    assert k.kosu_tam_mi(havuz([elenen("0xA")], evren_toplam=5000), RULES)[0] is False        # 1 satır < min(300, 5000)
    assert k.kosu_tam_mi(havuz([elenen(f"0x{i}") for i in range(300)], evren_toplam=5000), RULES) == (True, None)


def test_main_yazar_ve_eksik_kosuda_yazmaz(tmp_path):
    ok = tmp_path / "a" / "havuz.json"
    ok.parent.mkdir()
    ok.write_text(json.dumps(havuz([gecen("0xA", 0.03, 0.02)])), encoding="utf-8")
    assert k.main(["--havuz", str(ok)]) == 0
    assert json.loads((ok.parent / "kadro.json").read_text(encoding="utf-8"))["satirlar"][0]["adres"] == "0xA"
    kotu = tmp_path / "b" / "havuz.json"
    kotu.parent.mkdir()
    kotu.write_text(json.dumps(havuz([elenen("0xA", "zaman_yok")])), encoding="utf-8")
    assert k.main(["--havuz", str(kotu)]) == 2 and not (kotu.parent / "kadro.json").exists()
