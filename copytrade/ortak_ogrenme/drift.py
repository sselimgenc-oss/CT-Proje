# Kaynak: sselimgenc-oss/SG-Github-AB-proje trader/paket/ortak_ogrenme/drift.py @ f6221cb (kopya; değiştirme, güncelleme kaynaktan)
"""Drift izleme: CUSUM (spec parca 2 bolum 3). Yalniz standart kutuphane.

ML karsiligi: trader_core/drift_monitor.py -> cusum_replay ve sabitler (ayni degerler).
"""
from __future__ import annotations

from typing import Iterable

from .kayit import Aday

CUSUM_MU0, CUSUM_SIGMA0, CUSUM_K = -0.111, 1.224, 0.5
CUSUM_CLIP = (-1.5, 3.0)
CUSUM_UYARI = 4.0
CUSUM_COOLDOWN = 30
MIN_N = 20


def _r(x: float) -> float:
    return round(x, 9)


def _ge(x: float, t: float) -> bool:
    return _r(x) >= _r(t)


def cusum(rs: Iterable[float]) -> dict:
    """R dizisini (cikis sirasiyla) bastan isler. -> {S, n, cooldown, alarms}; alarms 1-tabanli indekslerdir."""
    rs = list(rs)
    s, cd, alarms = 0.0, 0, []
    for i, r in enumerate(rs, 1):
        x = min(max(r, CUSUM_CLIP[0]), CUSUM_CLIP[1])
        z = (x - CUSUM_MU0) / CUSUM_SIGMA0
        s = max(0.0, s - z - CUSUM_K)
        suppressed = cd > 0
        if cd > 0:
            cd -= 1
        if i >= MIN_N and _ge(s, CUSUM_UYARI) and not suppressed:
            alarms.append(i)
            s, cd = 0.0, CUSUM_COOLDOWN
    return {"S": s, "n": len(rs), "cooldown": cd, "alarms": alarms}


def kurulum_drift(adaylar: Iterable[Aday]) -> dict[str, dict]:
    """Kurulum basina drift. Yalniz alinan ve r'si olan adaylar, ts sirali r dizisiyle cusum.
    Ek alan 'durum': 'uyari' (son alarmdan beri < CUSUM_COOLDOWN islem) | 'normal'."""
    gruplar: dict[str, list[Aday]] = {}
    for a in adaylar:
        if a.alindi and a.r is not None:
            gruplar.setdefault(a.kurulum, []).append(a)
    out: dict[str, dict] = {}
    for k in sorted(gruplar):
        cs = sorted(gruplar[k], key=lambda a: a.ts)
        res = cusum([float(a.r) for a in cs])
        son = res["alarms"][-1] if res["alarms"] else None
        uyari = son is not None and res["n"] - son < CUSUM_COOLDOWN
        res["durum"] = "uyari" if uyari else "normal"
        out[k] = res
    return out
