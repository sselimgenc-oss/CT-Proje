# Kaynak: sselimgenc-oss/SG-Github-AB-proje trader/paket/ortak_ogrenme/kayit.py @ af68a02 (kopya; değiştirme, güncelleme kaynaktan)
"""Ortak aday kaydi (spec bolum 1): Aday, JSON donusumu, JSONL okuma/atomik yazma."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

YONLER = ("long", "short")
VARLIK_SINIFLARI = ("kripto", "hisse", "emtia")
ZORUNLU_ALANLAR = ("id", "proje", "kurulum", "enstruman", "varlik_sinifi", "yon", "ts", "alindi", "r")


@dataclass(frozen=True)
class Aday:
    id: str
    proje: str
    kurulum: str
    enstruman: str
    varlik_sinifi: str
    yon: str
    ts: datetime
    alindi: bool
    r: float | None
    seans: str | None = None
    rejim: str | None = None
    ozellikler: Mapping[str, float] = field(default_factory=dict)
    etiketler: tuple[str, ...] = ()
    cikis: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.yon not in YONLER:
            raise ValueError(f"yon gecersiz: {self.yon!r}")
        if self.varlik_sinifi not in VARLIK_SINIFLARI:
            raise ValueError(f"varlik_sinifi gecersiz: {self.varlik_sinifi!r}")
        if not isinstance(self.ts, datetime) or self.ts.utcoffset() is None:
            raise ValueError("ts tz'li (aware) datetime olmali")
        object.__setattr__(self, "etiketler", tuple(self.etiketler))


def aday_from_dict(d: Mapping[str, Any]) -> Aday:
    """Sozlukten Aday. Zorunlu alan eksikse veya dogrulama basarisizsa ValueError."""
    if not isinstance(d, Mapping):
        raise ValueError("aday sozluk olmali")
    eksik = [k for k in ZORUNLU_ALANLAR if k not in d]
    if eksik:
        raise ValueError(f"zorunlu alan eksik: {eksik}")
    ts = d["ts"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return Aday(
        id=d["id"], proje=d["proje"], kurulum=d["kurulum"], enstruman=d["enstruman"],
        varlik_sinifi=d["varlik_sinifi"], yon=d["yon"], ts=ts, alindi=bool(d["alindi"]), r=d["r"],
        seans=d.get("seans"), rejim=d.get("rejim"),
        ozellikler=dict(d.get("ozellikler") or {}),
        etiketler=tuple(d.get("etiketler") or ()),
        cikis=dict(d.get("cikis") or {}),
    )


def aday_to_dict(a: Aday) -> dict[str, Any]:
    """JSON uyumlu sozluk. ts UTC'ye cevrilir ve ISO-8601 'Z' bicimindedir."""
    ts = a.ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "id": a.id, "proje": a.proje, "kurulum": a.kurulum, "enstruman": a.enstruman,
        "varlik_sinifi": a.varlik_sinifi, "yon": a.yon, "ts": ts, "alindi": a.alindi, "r": a.r,
        "seans": a.seans, "rejim": a.rejim,
        "ozellikler": dict(a.ozellikler), "etiketler": list(a.etiketler), "cikis": dict(a.cikis),
    }


def oku_jsonl(path: str | os.PathLike) -> list[Aday]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[Aday] = []
    with p.open(encoding="utf-8") as fh:
        for satir in fh:
            satir = satir.strip()
            if satir:
                out.append(aday_from_dict(json.loads(satir)))
    return out


def yaz_jsonl(path: str | os.PathLike, adaylar: list[Aday]) -> None:
    """Atomik yazim: gecici dosya + os.replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".aday-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for a in adaylar:
                fh.write(json.dumps(aday_to_dict(a), ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
