"""Kadro seçimi rastgeleye karşı (YALNIZ BİLGİ; seçim, eşik ve işlem mantığı değişmez; K-65 "seçim rastgeleden iyi değil" için canlı, tekrarlanabilir kontrol).

Metrik = `radar_isabet` ile AYNI: `ilk11` grubunun `sonraki_7g` (maliyet sonrası kopya getirisi, oran) ortalaması. Aday havuz = seçicinin baktığı R1 havuzu = `ilk11` ∪ `havuz_geri`
satırları (isabet.json `satirlar`; yalnız `sonraki_7g` ölçülenler). Havuz isabet.json satırlarından kurulur; satır yoksa / ilk11 ölçümü yoksa o gün "havuz yok" yazılır.
Boş (null) dağılım: aynı havuzdan, seçilenle AYNI sayıda (k) rastgele alt küme; R=1000 (tohum = YYYYMMDD sayısı, isabet tohumuyla aynı kural). C(n,k) ≤ R ise tüm alt kümeler
TAM sayılır (rastgelelik yok, sonuç elle doğrulanır). Yüzdelik = 100 × (boş < gerçek + ½ boş = gerçek) payı; p = boş ≥ gerçek payı (küçük p = seçim şansın üstünde).
Günlük isabetler 7 günlük pencerelerle örtüşür; toplu özet bağımsız değildir (yalnız bilgi).

    python -m copytrade.radar_rastgele --kok radar --veri-dali radar --ozet-md radar/ISABET_OZET.md
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from datetime import UTC, datetime
from itertools import combinations
from math import comb
from pathlib import Path

SEMA = "radar-rastgele-v1"
R = 1000
SECILEN_GRUP = "ilk11"
HAVUZ_GRUPLARI = ("ilk11", "havuz_geri")


def _tohum(tarih: str) -> int:
    return int(tarih.replace("-", ""))


def bos_dagilim(havuz: list[float], k: int, r: int, tohum: int) -> tuple[list[float], str]:
    """k'lı alt küme ortalamaları. C(n,k) ≤ r → hepsi ("tam"); değilse r rastgele ("ornek", sabit tohum). Döner (ortalamalar, yontem)."""
    h = sorted(havuz)
    if comb(len(h), k) <= r:
        return [sum(c) / k for c in combinations(h, k)], "tam"
    rng = random.Random(tohum)
    return [sum(rng.sample(h, k)) / k for _ in range(r)], "ornek"


def yuzdelik_p(gercek: float, bos: list[float], eps: float = 1e-12) -> tuple[float, float]:
    """(yüzdelik 0-100, p). Eşitlik eps toleranslı (kayan nokta)."""
    n = len(bos)
    alt = sum(1 for b in bos if b < gercek - eps)
    esit = sum(1 for b in bos if abs(b - gercek) <= eps)
    return 100.0 * (alt + 0.5 * esit) / n, (n - alt) / n


def _havuz_sec(satirlar: list[dict]) -> tuple[list[float], list[float]]:
    havuz = [s["sonraki_7g"] for s in satirlar if s.get("grup") in HAVUZ_GRUPLARI and s.get("sonraki_7g") is not None]
    sec = [s["sonraki_7g"] for s in satirlar if s.get("grup") == SECILEN_GRUP and s.get("sonraki_7g") is not None]
    return havuz, sec


def karsilastir(satirlar: list[dict], tarih: str, r: int = R) -> dict:
    """Bir isabet günü için. `satirlar`: isabet.json satırları. Havuz/seçilen yoksa durum "havuz_yok"."""
    havuz, sec = _havuz_sec(satirlar)
    if not sec or len(havuz) < len(sec) + 1:
        return {"durum": "havuz_yok", "tarih": tarih, "havuz_n": len(havuz), "secilen_n": len(sec)}
    gercek = sum(sec) / len(sec)
    bos, yontem = bos_dagilim(havuz, len(sec), r, _tohum(tarih))
    yz, p = yuzdelik_p(gercek, bos)
    return {"durum": "tamam", "tarih": tarih, "havuz_n": len(havuz), "secilen_n": len(sec), "secilen_ortalama": gercek, "rastgele_medyan": float(statistics.median(bos)),
            "rastgele_ortalama": sum(bos) / len(bos), "yuzdelik": yz, "p": p, "yontem": yontem, "r": len(bos), "tohum": _tohum(tarih)}


def toplu(gunler: list[dict], bos_listeleri: list[list[float]], r: int = R) -> dict:
    """Tamamlanan günlerin toplu özeti: yüzdeliklerin ortalaması (şansta ≈ 50), seçilen − rastgele ortalama farkı, toplu p.
    Toplu p: her günün boş dağılımından bağımsız birer çekimin ortalaması (sabit tohum, R kez) ≥ gerçek ortalama payı."""
    ok = [g for g in gunler if g["durum"] == "tamam"]
    if not ok:
        return {"durum": "yok", "gun_n": 0}
    secilen_ort = sum(g["secilen_ortalama"] for g in ok) / len(ok)
    rastgele_ort = sum(g["rastgele_ortalama"] for g in ok) / len(ok)
    rng = random.Random(sum(g["tohum"] for g in ok))
    sim = [sum(rng.choice(b) for b in bos_listeleri) / len(bos_listeleri) for _ in range(r)]
    toplu_yz, toplu_p = yuzdelik_p(secilen_ort, sim)
    return {"durum": "tamam", "gun_n": len(ok), "yuzdelik_ort": sum(g["yuzdelik"] for g in ok) / len(ok), "secilen_ort": secilen_ort, "rastgele_ort": rastgele_ort,
            "fark_ort": secilen_ort - rastgele_ort, "toplu_yuzdelik": toplu_yz, "toplu_p": toplu_p, "p_5_alti_gun": sum(1 for g in ok if g["p"] < 0.05)}


def rapor(isabetler: list[dict], r: int = R) -> dict:
    """Tüm isabet günleri (tarih sırası) → {gunler, toplu}."""
    gunler, bos_listeleri = [], []
    for i in sorted(isabetler, key=lambda x: x["tarih"]):
        satirlar = i.get("satirlar") or []
        g = karsilastir(satirlar, i["tarih"], r)
        if g["durum"] == "tamam":
            havuz, _ = _havuz_sec(satirlar)
            bos_listeleri.append(bos_dagilim(havuz, g["secilen_n"], r, g["tohum"])[0])
        gunler.append(g)
    return {"sema": SEMA, "metrik": "ilk11 sonraki_7g ortalaması (radar_isabet ile aynı)", "havuz": "ilk11 ∪ havuz_geri (sonraki_7g ölçülen)", "gunler": gunler,
            "toplu": toplu(gunler, bos_listeleri, r)}


def md_tablo(rp: dict) -> str:
    f = lambda v: f"{100 * v:+.2f}"          # noqa: E731
    c = ["### Kadro seçimi rastgeleye karşı (yalnız bilgi)", "", "| Hafta | Seçilen ort. % | Rastgele medyan % | Yüzdelik | p |", "|---|---|---|---|---|"]
    for g in rp["gunler"]:
        if g["durum"] == "tamam":
            c.append(f"| {g['tarih']} | {f(g['secilen_ortalama'])} | {f(g['rastgele_medyan'])} | {g['yuzdelik']:.0f} | {g['p']:.3f} |")
        else:
            c.append(f"| {g['tarih']} | havuz yok | — | — | — |")
    t = rp["toplu"]
    if t["durum"] == "tamam":
        c += ["", f"Toplu ({t['gun_n']} gün): ortalama yüzdelik {t['yuzdelik_ort']:.0f} (şans ≈ 50), seçilen − rastgele {f(t['fark_ort'])} puan, toplu p {t['toplu_p']:.3f}; "
                  f"p<0,05 olan gün {t['p_5_alti_gun']}. _Günlük pencereler örtüşür; yalnız bilgi._"]
    else:
        c += ["", "Toplu: hesaplanabilir gün yok."]
    return "\n".join(c)


def _isabetler(dal: str | None, kok: Path) -> list[dict]:
    from copytrade.pbo_rapor import git_isabetler, yerel_isabetler
    birlesik = {i["tarih"]: i for i in (git_isabetler(dal) if dal else [])}
    birlesik.update({i["tarih"]: i for i in yerel_isabetler(kok)})
    return list(birlesik.values())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kok", type=Path, default=Path("radar"))
    ap.add_argument("--veri-dali", default=None)
    ap.add_argument("--cikti", type=Path, default=Path("radar"))
    ap.add_argument("--tarih", default=None)
    ap.add_argument("--ozet-md", type=Path, default=None, help="tablo bu dosyaya EKLENİR")
    args = ap.parse_args(argv)
    try:
        gunler = sorted(d.name for d in args.kok.glob("????-??-??"))
        tarih = args.tarih or (gunler[-1] if gunler else datetime.now(UTC).date().isoformat())
        rp = rapor(_isabetler(args.veri_dali, args.kok))
        klasor = args.cikti / tarih
        klasor.mkdir(parents=True, exist_ok=True)
        (klasor / "rastgele_karsilastirma.json").write_text(json.dumps(rp, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
        md = md_tablo(rp)
        print(md)
        if args.ozet_md:
            ayrac = "\n" if args.ozet_md.exists() and args.ozet_md.stat().st_size else ""
            with args.ozet_md.open("a", encoding="utf-8") as f:
                f.write(ayrac + md + "\n")
    except Exception as hata:                                  # noqa: BLE001 — radar yayımı engellenmez
        print(f"::error::RASTGELE KARŞILAŞTIRMA HATASI: {type(hata).__name__}: {str(hata)[:200]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
