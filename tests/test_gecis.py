"""Paket B — geçiş kaydı (docs/GOREV_SECIM_V13.md): yalnız ekleme, silme yok, çıkış kuralı v1.4 (tests/test_cikis_v14.py), tek seçim kaynağı."""
import json
from pathlib import Path

import pandas as pd
import pytest

from copytrade import gecis, secim
from copytrade.kurallar import load_rules

RULES = load_rules()
ROOT = Path(__file__).resolve().parents[1]


def addr(name: str) -> str:
    return "0x" + name * 40


def olay(**extra):
    base = {"tarih": "2026-11-05", "adres": addr("a"), "kol": "oda", "olay": "giris", "neden": "seçim", "secim_surumu": "v1.3", "kapi_tarihi": "2026-10-28"}
    return {**base, **extra}


def test_kayit_yalniz_ekler_sirayi_korur_ve_silme_yolu_yok(tmp_path):
    path = tmp_path / "gecis" / "kayit.jsonl"
    gecis.yaz(path, olay())
    first = path.read_text(encoding="utf-8")
    gecis.yaz(path, olay(adres=addr("b"), tarih="2026-11-12"))
    text = path.read_text(encoding="utf-8")
    assert text.startswith(first) and text.count("\n") == 2                          # mevcut satırlar bayt bayt aynı, yenisi sona eklendi
    assert [r["adres"] for r in gecis.oku(path)] == [addr("a"), addr("b")]
    assert not any(hasattr(gecis, name) for name in ("sil", "temizle", "guncelle", "kaldir"))


def test_kayit_alan_ve_deger_denetimi(tmp_path):
    path = tmp_path / "k.jsonl"
    for bad in (olay(olay="terfi"), olay(kol="havuz"), olay(tarih="05.11.2026"), {k: v for k, v in olay().items() if k != "neden"}, {**olay(), "ekstra": 1}):
        with pytest.raises(ValueError):
            gecis.yaz(path, bad)
    assert not path.exists()                                                           # reddedilen olay dosyaya hiçbir şey yazmaz
    gecis.yaz(path, olay())
    with pytest.raises(ValueError, match="zaten"):
        gecis.yaz(path, olay())                                                        # aynı (tarih, adres, kol, olay) iki kez yazılmaz


def evaluations(path, rows):
    for tarih, uygun in rows:
        gecis.degerlendirme_yaz(path, {"tarih": tarih, "adres": addr("a"), "uygun": uygun, "secim_surumu": "v1.3", "kapi_tarihi": "2026-10-28"})


def test_cikis_icin_iki_ardisik_haftalik_degerlendirme(tmp_path):
    path = tmp_path / "deg.jsonl"
    assert RULES["secim_cikis_ardisik_hafta"] == 2
    evaluations(path, [("2026-11-05", True), ("2026-11-12", False)])
    assert gecis.cikmali(path, addr("a"), 2) is False                                  # tek uygunsuz hafta çıkış değildir
    evaluations(path, [("2026-11-19", False)])
    assert gecis.cikmali(path, addr("a"), 2) is True                                   # 11-12 ve 11-19 ardışık, ikisi de uygunsuz
    assert gecis.cikmali(path, addr("b"), 2) is False                                  # değerlendirmesi olmayan adres


def test_uygunsuz_haftalar_ardisik_degilse_veya_arada_uygun_varsa_cikis_yok(tmp_path):
    path = tmp_path / "deg.jsonl"
    evaluations(path, [("2026-11-05", False), ("2026-11-12", True), ("2026-11-19", False)])
    assert gecis.cikmali(path, addr("a"), 2) is False                                  # arada uygun hafta sayacı sıfırlar
    gap = tmp_path / "gap.jsonl"
    evaluations(gap, [("2026-11-05", False), ("2026-11-19", False)])                    # 14 gün ara: değerlendirme atlanmış, ardışık değil
    assert gecis.cikmali(gap, addr("a"), 2) is False


def result_of(oda: list[str], adaylar: list[str] | None = None, surum="v1.3", kapi="2026-10-28"):
    entries = {}
    for name in set(oda) | set(adaylar or []):
        kollar = (["oda"] if name in oda else []) + ["aday", "havuz"]
        entries[addr(name)] = {"kol": kollar[0], "kollar": kollar}
    return {"secim_surumu": surum, "kapi_tarihi": kapi, "tarih": kapi, "adresler": entries}


def test_haftalik_gecis_giris_cikis_ve_surum_kimligi(tmp_path):
    kayit, deg = tmp_path / "kayit.jsonl", tmp_path / "deg.jsonl"
    week1 = gecis.haftalik(kayit, deg, result_of(["a", "b"]), "2026-11-05", RULES)
    assert [(r["adres"], r["olay"]) for r in week1] == [(addr("a"), "giris"), (addr("b"), "giris")]
    assert all(r["secim_surumu"] == "v1.3" and r["kapi_tarihi"] == "2026-10-28" and r["kol"] == "oda" for r in week1)
    assert gecis.haftalik(kayit, deg, result_of(["a", "b"]), "2026-11-05", RULES) == []          # aynı hafta yeniden koşunca yeni olay yok (idempotent)
    week2 = gecis.haftalik(kayit, deg, result_of(["a", "c"]), "2026-11-12", RULES)               # b odadan düştü; c girer. v1.4: seçim odasından düşmek çıkış değildir
    assert [(r["adres"], r["olay"]) for r in week2] == [(addr("c"), "giris")]
    for hafta in ("2026-11-19", "2026-11-26", "2026-12-03"):
        assert gecis.haftalik(kayit, deg, result_of(["a", "c"]), hafta, RULES, kapanmis_islem={addr("b"): 500}) == []     # havuz alt dilimi değil: çıkış yok
    assert gecis.oda_uyeleri(gecis.oku(kayit)) == {addr("a"), addr("b"), addr("c")}
    assert [r["olay"] for r in gecis.oku(kayit) if r["adres"] == addr("b")] == ["giris"]             # silinmez, iz kalır; çıkış kuralı için tests/test_cikis_v14.py


def test_kollar_py_ikinci_uygulama_kaldirildi_tek_kaynak_secim():
    assert not (ROOT / "copytrade/kollar.py").exists()
    assert hasattr(secim, "adaylar") and hasattr(secim, "kontrol_sec") and hasattr(secim, "oda_sec")
    for path in list((ROOT / "copytrade").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")):
        assert "copytrade.kollar" not in path.read_text(encoding="utf-8") or path.name == "test_gecis.py"
