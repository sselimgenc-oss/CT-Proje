# Kaynak: sselimgenc-oss/SG-Github-AB-proje trader/paket/ortak_ogrenme/ders.py @ af68a02 (kopya; değiştirme, güncelleme kaynaktan)
"""Aday ders yasam dongusu (spec bolum 3). Durum dosyasi JSON; atomik yazim."""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .kayit import Aday
from .notlar import LESSON_CODES, LESSON_PREFIX, ders_uyar_mi, valid_tag


def _gun_baslangici(gun: str) -> datetime:
    return datetime.strptime(gun, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def ders_etkisi(adaylar: Iterable[Aday], kimlik: str, dogum_gunu: str, as_of: datetime,
                shrink_n: int = 0) -> tuple[float, int]:
    """(etki, n). Dogum gununun ertesi 00:00 UTC <= ts < as_of araligindaki, alinmis (alindi, r bilinen)
    ve derse uyan adaylarin R toplami: etki = -fsum(r) * n/(n+shrink_n). n = 0 => (0.0, 0)."""
    return _pencere_etkisi(adaylar, kimlik, _gun_baslangici(dogum_gunu) + timedelta(days=1), as_of, shrink_n)


def _pencere_etkisi(adaylar: Iterable[Aday], kimlik: str, since: datetime, as_of: datetime,
                    shrink_n: int = 0) -> tuple[float, int]:
    kod, _, kurulum = kimlik.partition(":")
    rs = [float(a.r) for a in adaylar
          if a.alindi and a.r is not None and since <= a.ts < as_of and ders_uyar_mi(kod, kurulum, a)]
    n = len(rs)
    if n == 0:
        return 0.0, 0
    return -math.fsum(rs) * n / (n + max(0, int(shrink_n))), n


def _yukle(path: str | os.PathLike) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _kaydet(path: str | os.PathLike, durum: Mapping[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".ders-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(durum, fh, sort_keys=True, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def gece_adimi(adaylar: Sequence[Aday], notlar: Sequence[Mapping[str, Any]], durum_yolu: str | os.PathLike,
               gun: str, shrink_n: int = 0) -> dict[str, list[str]]:
    """Gece adimi. (1) notlardaki yeni `ders:` onerileri 'candidate' olur (born = notun gunu);
    (2) emekli olmayan her ders olculur: n=0 bekler; etki > 0 => alive; etki <= 0 => retired (+retired_day).
    Emekli geri donmez. Donus: {"born", "alive", "retired"} (sirali; alive/retired bu kosudaki gecisler)."""
    durum = _yukle(durum_yolu)
    eski = set(durum)
    for n in notlar:
        for t in n.get("tags", []):
            if isinstance(t, str) and t.startswith(LESSON_PREFIX) and valid_tag(t):
                lid = t[len(LESSON_PREFIX):]
                if lid not in durum:
                    durum[lid] = {"status": "candidate", "born": n["note_date"], "effect": None, "n": 0}
    as_of = _gun_baslangici(gun)
    out: dict[str, list[str]] = {"born": sorted(set(durum) - eski), "alive": [], "retired": []}
    for lid, st in sorted(durum.items()):
        if st.get("status") == "retired":
            continue
        eff, n = ders_etkisi(adaylar, lid, st["born"], as_of, shrink_n)
        st["effect"], st["n"] = round(eff, 6), n
        if n == 0:
            continue
        if eff > 0:
            if st.get("status") != "alive":
                out["alive"].append(lid)
            st["status"] = "alive"
        else:
            st["status"], st["retired_day"] = "retired", gun
            out["retired"].append(lid)
    _kaydet(durum_yolu, durum)
    return out


def etkin_dersler(durum_yolu: str | os.PathLike, limit: int = 8) -> list[str]:
    """candidate + alive dersler; alive once, sonra etki azalan, sonra kimlik."""
    st = _yukle(durum_yolu)
    canli = [(k, v) for k, v in st.items() if isinstance(v, dict) and v.get("status") in ("candidate", "alive")]
    canli.sort(key=lambda kv: (kv[1]["status"] != "alive", -(kv[1].get("effect") or 0.0), kv[0]))
    return [k for k, _ in canli[:max(0, int(limit))]]


def uyan_dersler(etkin: Iterable[str], aday: Aday) -> list[str]:
    """Karar aninda adaya uyan ders kimlikleri (etiket olarak yazilir; islemi engellemez)."""
    out = []
    for kimlik in etkin:
        kod, _, kurulum = kimlik.partition(":")
        if ders_uyar_mi(kod, kurulum, aday):
            out.append(kimlik)
    return out


def fren_durumu(adaylar: Iterable[Aday], etkin_kimlikler: Iterable[str], baslangic: datetime | str, as_of: datetime,
                esik_r: float = 10.0, geri_alma_r: float = 3.0) -> dict[str, Any]:
    """Rapor: toplam_etki = kimliklerin tek tek etkilerinin toplami (shrink 0); fren = toplam <= -esik_r;
    geri_al = tek tek etkisi <= -geri_alma_r olan kimlikler. Uygulamak adaptorun isi."""
    adaylar = list(adaylar)
    kimlikler = list(etkin_kimlikler)
    # baslangic: tz'li datetime => o andan itibaren (dahil); "YYYY-MM-DD" => ertesi gun 00:00 UTC (ders_etkisi ile ayni)
    if isinstance(baslangic, datetime):
        if baslangic.tzinfo is None:
            raise ValueError("baslangic tz'li olmali")
        since = baslangic
    else:
        since = _gun_baslangici(baslangic) + timedelta(days=1)
    etkiler = {k: _pencere_etkisi(adaylar, k, since, as_of, shrink_n=0)[0] for k in kimlikler}
    toplam = math.fsum(etkiler.values())
    return {
        "toplam_etki": toplam,
        "fren": toplam <= -esik_r,
        "geri_al": [k for k in kimlikler if etkiler[k] <= -geri_alma_r],
    }
