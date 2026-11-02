"""Paket D — haftalık geri bildirim raporu (rotasyon içindir): havuz genelinde puan ↔ ileri getiri Spearman'ı ve kaldıraç/tarz kırılımı.
Kol bazında (oda/kontrol/taban/elle) getiri HİÇBİR YERDE yazılmaz (performans körlüğü, ön kayıt D madde 6)."""
import json
import re
from pathlib import Path

import numpy as np
import pytest

from copytrade import haftalik_rapor
from copytrade.kurallar import load_rules

RULES = load_rules()
ROOT = Path(__file__).resolve().parents[1]


def addr(group: str, i: int) -> str:
    return "0x" + (group + str(i)) * 20


def entry(tarz, puan, kollar, dilim):
    return {"kol": kollar[0], "kollar": kollar, "tarz": tarz, "puan": puan, "dilim": f"{tarz}/{dilim}"}


def pool():
    """intraday: puan 1..5, ileri [2,1,4,3,5] (ρ = 0,8; alt dilim 1–3, üst 4–5); swing: puan 1..5, ileri [5,4,3,2,1] (ρ = −1)."""
    entries, ileri = {}, {}
    for i, (puan, getiri) in enumerate(zip([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]), 1):
        kollar = ["oda", "aday", "havuz"] if i == 5 else ["kontrol", "havuz"] if i == 1 else ["havuz"]
        entries[addr("a", i)] = entry("intraday", puan, kollar, "alt" if i <= 3 else "ust")
        ileri[addr("a", i)] = getiri / 100 + (0.123456 if i == 5 else 0)           # oda üyesinin ayırt edilebilir getirisi (raporda görünmemeli)
    for i, (puan, getiri) in enumerate(zip([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]), 1):
        entries[addr("b", i)] = entry("swing", puan, ["havuz"], "alt" if i <= 2 else "ust")
        ileri[addr("b", i)] = getiri / 100
    entries[addr("c", 1)] = {"kol": "taban", "kollar": ["taban"], "tarz": None, "puan": None}          # havuz dışı (taban): rapora girmez
    return {"secim_surumu": "v1.3", "kapi_tarihi": "2026-10-28", "adresler": entries}, ileri


def rank_corr(x, y):
    """Bağımsız (ortalama sıralı) Spearman: her değerin sırası = kendinden küçük sayısı + (eşit sayısı + 1) / 2."""
    def ranks(v):
        return np.array([sum(w < t for w in v) + (sum(w == t for w in v) + 1) / 2 for t in v])
    a, b = ranks(x) - (len(x) + 1) / 2, ranks(y) - (len(y) + 1) / 2
    return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))


def test_birincil_havuz_genelinde_spearman_ve_kirilim_altin_ornek():
    result, ileri = pool()
    out = haftalik_rapor.hesapla(result, ileri, RULES)
    members = [a for a, e in result["adresler"].items() if e.get("puan") is not None]
    assert out["n"] == 10 and out["eksik"] == 0
    assert out["birincil"]["rho"] == pytest.approx(rank_corr([result["adresler"][a]["puan"] for a in members], [ileri[a] for a in members]))
    groups = {g["ad"]: g for g in out["kirilim"]}
    assert groups["tarz: intraday"]["rho"] == pytest.approx(0.8) and groups["tarz: intraday"]["n"] == 5
    assert groups["tarz: swing"]["rho"] == pytest.approx(-1.0)
    assert groups["tarz: intraday"]["p_tek_yonlu"] == pytest.approx(0.0656417, abs=1e-6)          # n = 5, ρ = 0,8 (analiz_d altın örneği)
    assert groups["kaldıraç: alt"]["n"] == 5 and groups["kaldıraç: ust"]["n"] == 5
    assert groups["intraday/alt"]["n"] == 3 and groups["intraday/alt"]["p_tek_yonlu"] is None      # n ≤ 3: p/GA yok, "n yetersiz"


def test_rapor_metni_korluk_kol_bazinda_getiri_yok():
    result, ileri = pool()
    text = haftalik_rapor.rapor(result, ileri, "2026-11-05", RULES)
    assert "rotasyon içindir" in text and "karar analizi değildir" in text and "| tarz: intraday | 5 |" in text
    assert "0,8" in text and "n yetersiz" in text
    assert not re.search(r"^\|\s*(oda|kontrol|kohort|taban|elle)\b", text, re.M | re.I)             # kol satırı yok
    for forbidden in ("0.1235", "0,1235", "12,35", "12.35"):                                       # oda üyesinin getirisi hiçbir biçimde geçmez
        assert forbidden not in text
    assert "kol bazında" in text.lower() and "yazılmaz" in text                                            # körlük notu


def test_ileri_getirisi_olmayan_adres_eksik_sayilir_ve_hafta_veri_eksik_isaretlenir():
    result, ileri = pool()
    for a in list(ileri)[:2]:
        del ileri[a]                                                                              # 2 / 10 = %20 eksik > %5
    out = haftalik_rapor.hesapla(result, ileri, RULES)
    assert out["n"] == 8 and out["eksik"] == 2 and out["veri_eksik"] is True
    assert "veri eksik" in haftalik_rapor.rapor(result, ileri, "2026-11-05", RULES)


def test_cikti_dosyasi_ve_cli(tmp_path):
    result, ileri = pool()
    (tmp_path / "secim.json").write_text(json.dumps(result), encoding="utf-8")
    (tmp_path / "getiri.json").write_text(json.dumps(ileri), encoding="utf-8")
    haftalik_rapor.main(["--secim", str(tmp_path / "secim.json"), "--getiri", str(tmp_path / "getiri.json"), "--tarih", "2026-11-05",
                         "--cikti", str(tmp_path / "out")])
    assert (tmp_path / "out/haftalik_2026-11-05.md").read_text(encoding="utf-8").startswith("# Haftalık geri bildirim — 2026-11-05")
    assert not (tmp_path / "out/kayit.jsonl").exists()                                             # geçiş kaydı yalnız --gecis ile


def test_gecis_bayragi_haftalik_gecisi_calistirir_getiri_yoksa_da(tmp_path):
    result, _ = pool()
    result["adresler"][addr("a", 5)]["kollar"] = ["oda", "aday", "havuz"]
    (tmp_path / "secim.json").write_text(json.dumps(result), encoding="utf-8")
    haftalik_rapor.main(["--secim", str(tmp_path / "secim.json"), "--tarih", "2026-11-05", "--cikti", str(tmp_path / "out"), "--gecis"])
    rows = [json.loads(line) for line in (tmp_path / "out/kayit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["adres"], r["olay"]) for r in rows] == [(addr("a", 5), "giris")]
    text = (tmp_path / "out/haftalik_2026-11-05.md").read_text(encoding="utf-8")
    assert "ileri getiri verisi yok" in text                                                       # gölge henüz başlamadıysa rapor bunu söyler, sayı uydurmaz


def test_rapor_kosu_suresini_yazar(tmp_path):
    secim = tmp_path / "s.json"
    secim.write_text(json.dumps({"secim_surumu": "v1.3", "kapi_tarihi": "2026-10-28", "adresler": {}}))
    ozet = tmp_path / "o.json"
    ozet.write_text(json.dumps({"sure_sn": 12.5, "satir": {"dolum": 3}, "pencere_disi": 1, "eksik": 2}))
    haftalik_rapor.main(["--secim", str(secim), "--tarih", "2026-11-05", "--cikti", str(tmp_path / "r"), "--ozet", str(ozet)])
    assert "Koşu süresi 12.5 sn · okunan satır {'dolum': 3} · pencere dışı 1 · eksik 2." in (tmp_path / "r/haftalik_2026-11-05.md").read_text()
