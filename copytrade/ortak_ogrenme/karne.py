# Kaynak: sselimgenc-oss/SG-Github-AB-proje trader/paket/ortak_ogrenme/karne.py @ f6221cb (kopya; değiştirme, güncelleme kaynaktan)
"""Kurulum karnesi ve sanal kasa (spec parca 2 bolum 1). Yalniz standart kutuphane.

ML karsiligi: trader_core/counterfactual.py -> arm_scorecard, arm_virtual_bankroll, _arm_block, _mean_or_none.
Alan adlari ML'den farklidir (Turkce): candidates->aday, taken->alinan, resolved->cozulen,
mean_r_taken->ort_r_alinan, mean_r_taken_cf->ort_r_tum, by_class->sinif, kasa.taken->kasa.alinan,
kasa.cf->kasa.tum, equity->kasa, return_pct->getiri_pct, max_dd_pct->en_derin_pct.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from .kayit import Aday

KASA_BASLANGIC = 1000.0
KASA_RISK = 0.01


def _ort_or_none(vals: Iterable[float | None]) -> float | None:
    v = [x for x in vals if x is not None]
    return math.fsum(v) / len(v) if v else None


def _blok(cs: Sequence[Aday]) -> dict:
    return {
        "aday": len(cs),
        "alinan": sum(1 for a in cs if a.alindi),
        "cozulen": sum(1 for a in cs if a.r is not None),
        "ort_r_alinan": _ort_or_none(a.r for a in cs if a.alindi),
        "ort_r_tum": _ort_or_none(a.r for a in cs),
    }


def _gruplar(adaylar: Iterable[Aday]) -> dict[str, list[Aday]]:
    g: dict[str, list[Aday]] = {}
    for a in adaylar:
        g.setdefault(a.kurulum, []).append(a)
    return g


def _seri(cs: Sequence[Aday], baslangic: float, risk: float) -> dict:
    ordered = sorted(cs, key=lambda a: a.ts)  # sorted kararlidir: esitlikte girdi sirasi korunur
    eq, peak, worst = float(baslangic), float(baslangic), 0.0
    for a in ordered:
        eq = max(0.0, eq * (1.0 + risk * float(a.r)))
        peak = max(peak, eq)
        if peak > 0:
            worst = max(worst, (peak - eq) / peak * 100.0)
    kasa = round(eq, 2)
    return {
        "n": len(ordered),
        "kasa": kasa,
        "getiri_pct": round((kasa / baslangic - 1.0) * 100.0, 2),
        "en_derin_pct": round(worst, 2),
    }


def sanal_kasa(adaylar: Iterable[Aday], *, baslangic: float = KASA_BASLANGIC, risk: float = KASA_RISK,
               kurulumlar: Sequence[str] = ()) -> dict[str, dict]:
    """Kurulum basina sanal kasa (yalniz rapor). Donus: kurulum -> {"alinan": seri, "tum": seri}.

    alinan: yalniz alinan ve r'si olan adaylar; tum: r'si olan tum adaylar ('alinsaydi' dahil).
    Seri ts'ye gore artan, her adimda eq = max(0, eq * (1 + risk * r)), kasa 2 ondalik.
    kurulumlar: adayi olmayan kurulumlar da (n=0) yer alir."""
    if not baslangic > 0 or not risk > 0:
        raise ValueError("baslangic ve risk pozitif olmali")
    gruplar = _gruplar(adaylar)
    out: dict[str, dict] = {}
    for k in dict.fromkeys([*kurulumlar, *gruplar]):
        cs = gruplar.get(k, [])
        out[k] = {
            "alinan": _seri([a for a in cs if a.alindi and a.r is not None], baslangic, risk),
            "tum": _seri([a for a in cs if a.r is not None], baslangic, risk),
        }
    return out


def karne(adaylar: Iterable[Aday], kurulumlar: Sequence[str] = ()) -> dict[str, dict]:
    """Kurulum karnesi: kurulum -> {aday, alinan, cozulen, ort_r_alinan, ort_r_tum, sinif, kasa}.

    sinif: varlik_sinifi -> ayni alanlar (kasa ve sinif hariç). kasa: sanal_kasa(...)[kurulum].
    Sira: once kurulumlar, sonra adaylardaki goruldugu sira."""
    adaylar = list(adaylar)
    gruplar = _gruplar(adaylar)
    kasa = sanal_kasa(adaylar, kurulumlar=kurulumlar)
    out: dict[str, dict] = {}
    for k in dict.fromkeys([*kurulumlar, *gruplar]):
        cs = gruplar.get(k, [])
        blok = _blok(cs)
        blok["sinif"] = {s: _blok([a for a in cs if a.varlik_sinifi == s])
                         for s in sorted({a.varlik_sinifi for a in cs})}
        blok["kasa"] = kasa[k]
        out[k] = blok
    return out
