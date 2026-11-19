"""Sunucu kaynak ölçümü (yalnız okur; stdlib): süreç RAM'i, yük, disk, cgroup belleği. En iyi çaba: ölçülemeyen alan None; fonksiyonlar ASLA hata fırlatmaz (macOS/CI'da çoğu None)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

MB = 1024 * 1024
GB = 1024 ** 3


def _kb_mb(satir: str) -> float | None:
    """'VmRSS:   12345 kB' -> MB."""
    try:
        return round(int(satir.split()[1]) / 1024, 1)
    except (IndexError, ValueError):
        return None


def _surec_bellek(yol: str = "/proc/self/status") -> tuple[float | None, float | None]:
    rss = tepe = None
    try:
        for satir in Path(yol).read_text(encoding="utf-8", errors="replace").splitlines():
            if satir.startswith("VmRSS:"):
                rss = _kb_mb(satir)
            elif satir.startswith("VmHWM:"):
                tepe = _kb_mb(satir)
    except OSError:
        pass
    return rss, tepe


def _cgroup_dizin(kok: str = "/sys/fs/cgroup", proc_cgroup: str = "/proc/self/cgroup") -> Path | None:
    """cgroup v2 altında bu sürecin dizini (yoksa None)."""
    try:
        for satir in Path(proc_cgroup).read_text(encoding="utf-8").splitlines():
            if satir.startswith("0::"):
                d = Path(kok) / satir[3:].strip().lstrip("/")
                return d if d.is_dir() else None
    except OSError:
        pass
    return None


def _cgroup_mb(d: Path | None, ad: str) -> float | None:
    if d is None:
        return None
    try:
        return round(int((d / ad).read_text(encoding="utf-8").strip()) / MB, 1)
    except (OSError, ValueError):
        return None


def olc(durum_dizin: Any = None) -> dict:
    """{ram_mb, ram_tepe_mb, cgroup_mb, cgroup_tepe_mb, yuk_1dk, disk_bos_gb, disk_toplam_gb}; ölçülemeyen None."""
    ram, tepe = _surec_bellek()
    try:
        yuk: float | None = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        yuk = None
    bos = toplam = None
    try:
        du = shutil.disk_usage(str(durum_dizin) if durum_dizin else ".")
        bos, toplam = round(du.free / GB, 2), round(du.total / GB, 2)
    except (OSError, ValueError):
        pass
    cg = None
    try:
        cg = _cgroup_dizin()
    except Exception:                                                  # noqa: BLE001
        pass
    return {"ram_mb": ram, "ram_tepe_mb": tepe, "cgroup_mb": _cgroup_mb(cg, "memory.current"), "cgroup_tepe_mb": _cgroup_mb(cg, "memory.peak"),
            "yuk_1dk": yuk, "disk_bos_gb": bos, "disk_toplam_gb": toplam}
