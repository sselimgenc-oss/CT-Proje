"""Kural maliyeti (`ct.kural_maliyet.v1`): `durum/paylasim/kural_maliyet_v1.json` + `.md`. YALNIZ BİLGİ: kural, eşik, slot tavanı ve işlem mantığına girmez.

Son 7 günde alınmayan sinyallerin NEDEN başına özeti: kaç olay, kaç trader, karşı-olgu (hayali pozisyon) sonucu.
Karşı-olgu adres|coin başına TEK (ilk atlama) açılır; sık nedenleri (ör. slot_tavani) eksik örnekler, toplam $ alt sınırdır.
Trader adresi çıkmaz; yalnız adet.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from copytrade.canli.kayit_oku import kayitlari_oku
from copytrade.canli.hafta_paketi import _yaz_atomik

SEMA = "ct.kural_maliyet.v1"
DOSYA_JSON = "kural_maliyet_v1.json"
DOSYA_MD = "kural_maliyet_v1.md"
PENCERE_GUN = 7
VURGU = "slot_tavani"


def _say(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _t(neden: Any) -> str:
    return str(neden or "?")


def topla(kayitlar: list[dict], karsi_olgu: dict | None, simdi_ms: int, gun: int = PENCERE_GUN) -> list[dict]:
    """Neden başına satırlar (saf). Sıra: olay_adedi azalan, sonra neden. Pencere: zaman_ms >= simdi - gun gün (zamansız satır dahil)."""
    esik = simdi_ms - gun * 86_400_000
    olay: dict[str, int] = {}
    tr: dict[str, set] = {}
    kap_n: dict[str, int] = {}
    kap_pnl: dict[str, float] = {}
    kap_usd: dict[str, float] = {}
    for k in kayitlar:
        ms = _say(k.get("zaman_ms"))
        if ms is not None and ms < esik:
            continue
        o = k.get("olay")
        if o == "emir_yok":
            n = _t(k.get("neden"))
            olay[n] = olay.get(n, 0) + 1
            if k.get("adres"):
                tr.setdefault(n, set()).add(k["adres"])
        elif o == "karsi_olgu_kapandi":
            n = _t(k.get("neden"))
            kap_n[n] = kap_n.get(n, 0) + 1
            kap_pnl[n] = kap_pnl.get(n, 0.0) + (_say(k.get("pnl_usd")) or 0.0)
            kap_usd[n] = kap_usd.get(n, 0.0) + (_say(k.get("hayali_usd")) or 0.0)
    ac_n: dict[str, int] = {}
    ac_pnl: dict[str, float] = {}
    ac_usd: dict[str, float] = {}
    for v in (karsi_olgu or {}).values():
        if not isinstance(v, dict):
            continue
        n = _t(v.get("neden"))
        ac_n[n] = ac_n.get(n, 0) + 1
        ac_pnl[n] = ac_pnl.get(n, 0.0) + (_say(v.get("son_pnl")) or 0.0)
        ac_usd[n] = ac_usd.get(n, 0.0) + (_say(v.get("hayali_usd")) or 0.0)
    satirlar = []
    for n in set(olay) | set(kap_n) | set(ac_n):
        satirlar.append({"neden": n, "olay_adedi": olay.get(n, 0), "trader_sayisi": len(tr.get(n, ())),
                         "karsi_olgu_kapanan_n": kap_n.get(n, 0), "karsi_olgu_kapanan_pnl": round(kap_pnl.get(n, 0.0), 2),
                         "karsi_olgu_acik_n": ac_n.get(n, 0), "karsi_olgu_acik_pnl": round(ac_pnl.get(n, 0.0), 2),
                         "toplam_karsi_olgu_pnl": round(kap_pnl.get(n, 0.0) + ac_pnl.get(n, 0.0), 2),
                         "hayali_nosyonel": round(kap_usd.get(n, 0.0) + ac_usd.get(n, 0.0), 2)})
    return sorted(satirlar, key=lambda r: (-r["olay_adedi"], r["neden"]))


def olustur(kayitlar: list[dict], karsi_olgu: dict | None, simdi_ms: int) -> dict:
    satirlar = topla(kayitlar, karsi_olgu, simdi_ms)
    vurgu = next((r for r in satirlar if r["neden"] == VURGU), None)
    notlar = ["Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.",
              "Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.",
              "Olay = emir_yok adedi; karşı-olgu yalnız ac/artir (hak_bitti, kucuk_hareket, gec_goruldu_alinmaz hariç).",
              "Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.",
              f"Pencere son {PENCERE_GUN} gün; trader adresi yok, yalnız adet."]
    return {"sema": SEMA, "proje": "CT", "uretim": datetime.fromtimestamp(simdi_ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pencere_gun": PENCERE_GUN, "satirlar": satirlar, "vurgu": {VURGU: vurgu}, "notlar": notlar}


def _satir_md(r: dict) -> str:
    return (f"| {r['neden']} | {r['olay_adedi']} | {r['trader_sayisi']} | {r['karsi_olgu_kapanan_pnl']:.2f} ({r['karsi_olgu_kapanan_n']}) | "
            f"{r['karsi_olgu_acik_pnl']:.2f} ({r['karsi_olgu_acik_n']}) | {r['toplam_karsi_olgu_pnl']:.2f} | {r['hayali_nosyonel']:.2f} |")


def markdown(veri: dict) -> str:
    out = [f"# CT kural maliyeti (son {veri['pencere_gun']} gün, {veri['uretim']})", ""]
    v = (veri.get("vurgu") or {}).get(VURGU)
    if v:
        out += [f"**Slot tavanı:** {v['olay_adedi']} olay, {v['trader_sayisi']} trader; karşı-olgu toplam {v['toplam_karsi_olgu_pnl']:.2f} $ "
                f"(kapanan {v['karsi_olgu_kapanan_pnl']:.2f}, açık {v['karsi_olgu_acik_pnl']:.2f}; hayali nosyonel {v['hayali_nosyonel']:.2f} $).", ""]
    else:
        out += ["**Slot tavanı:** son 7 günde kayıt yok.", ""]
    out += ["| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |", "|---|---:|---:|---:|---:|---:|---:|"]
    out += [_satir_md(r) for r in veri["satirlar"]] or ["| - | 0 | 0 | 0.00 | 0.00 | 0.00 | 0.00 |"]
    out += ["", "Notlar:", ""] + [f"- {n}" for n in veri["notlar"]]
    return "\n".join(out) + "\n"


def yaz(motor: Any) -> None:
    """`paylasim/kural_maliyet_v1.json` ve `.md` yazar (hata çağırana çıkar; çağıran yutar)."""
    simdi = int(motor.saat_ms())
    veri = olustur(kayitlari_oku(Path(motor.kayit.dizin), simdi, PENCERE_GUN), getattr(motor, "karsi_olgu", None), simdi)
    d = Path(motor.durum_dizin) / "paylasim"
    _yaz_atomik(d / DOSYA_JSON, json.dumps(veri, ensure_ascii=False, indent=1))
    _yaz_atomik(d / DOSYA_MD, markdown(veri))
