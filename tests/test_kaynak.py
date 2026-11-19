"""Sunucu kaynak ölçümü (copytrade/canli/kaynak.py): en iyi çaba, asla hata fırlatmaz."""
from __future__ import annotations

import os

from copytrade.canli import kaynak

ANAHTAR = {"ram_mb", "ram_tepe_mb", "cgroup_mb", "cgroup_tepe_mb", "yuk_1dk", "disk_bos_gb", "disk_toplam_gb"}


def test_olc_anahtarlar_ve_disk(tmp_path):
    o = kaynak.olc(tmp_path)
    assert set(o) == ANAHTAR
    assert o["disk_bos_gb"] is not None and o["disk_bos_gb"] > 0


def test_surec_bellek_ayristirir(tmp_path):
    f = tmp_path / "status"
    f.write_text("Name:\tx\nVmHWM:\t  2048 kB\nVmRSS:\t  1024 kB\n", encoding="utf-8")
    assert kaynak._surec_bellek(str(f)) == (1.0, 2.0)
    assert kaynak._surec_bellek(str(tmp_path / "yok")) == (None, None)


def test_cgroup_okur_ve_yoksa_none(tmp_path):
    kok = tmp_path / "cg"
    (kok / "sg.slice").mkdir(parents=True)
    (kok / "sg.slice" / "memory.current").write_text(str(10 * 1024 * 1024) + "\n", encoding="utf-8")
    (kok / "sg.slice" / "memory.peak").write_text("bozuk\n", encoding="utf-8")
    pc = tmp_path / "proc_cgroup"
    pc.write_text("0::/sg.slice\n", encoding="utf-8")
    d = kaynak._cgroup_dizin(str(kok), str(pc))
    assert d is not None and kaynak._cgroup_mb(d, "memory.current") == 10.0
    assert kaynak._cgroup_mb(d, "memory.peak") is None and kaynak._cgroup_mb(d, "yok") is None
    assert kaynak._cgroup_dizin(str(kok), str(tmp_path / "yok")) is None and kaynak._cgroup_mb(None, "x") is None


def test_olc_hata_firlatmaz(tmp_path, monkeypatch):
    def patla(*a, **k):
        raise OSError("yok")
    monkeypatch.setattr(os, "getloadavg", patla)
    monkeypatch.setattr(kaynak.shutil, "disk_usage", patla)
    monkeypatch.setattr(kaynak.Path, "read_text", patla)
    o = kaynak.olc(tmp_path)
    assert o["yuk_1dk"] is None and o["disk_bos_gb"] is None and o["ram_mb"] is None and o["cgroup_mb"] is None
