"""Pano kartı "Sunucu kaynakları" (`pano._kaynak_html`, yalnız bilgi): tam veri, kısmi null, veri yok.

Altın örnek (elle hesaplandı):
  ram_mb 512,3 → "512 MB" (0 ondalık); ram_tepe_mb 640,0 → "640 MB"; cgroup_mb 812,0 → "812 MB"
  yuk_1dk 0,42 → "0,42"; disk_bos_gb 12,5 → "12,5 GB"
  olc_ms = 2026-11-19 07:00 UTC = 10:00 TSİ → "19.11 10:00 TSİ"
"""
from __future__ import annotations

from datetime import UTC, datetime

from copytrade.canli import pano

OLC_MS = int(datetime(2026, 11, 19, 7, 0, tzinfo=UTC).timestamp() * 1000)


def _tam() -> dict:
    return {"ram_mb": 512.3, "ram_tepe_mb": 640.0, "cgroup_mb": 812.0, "cgroup_tepe_mb": 900.0,
            "yuk_1dk": 0.42, "disk_bos_gb": 12.5, "disk_toplam_gb": 50.0, "olc_ms": OLC_MS}


def test_tam_veri_altin_ornek():
    h = pano._kaynak_html(_tam())
    assert "RAM: 512 MB · tepe 640 MB" in h
    assert "bellek (servis): 812 MB" in h
    assert "yük (1 dk): 0,42 · disk boş: 12,5 GB" in h
    assert "ölçüm zamanı: 19.11 10:00 TSİ" in h
    assert "veri yok" not in h


def test_kismi_null_tire_gosterir():
    k = _tam()
    k.update({"ram_mb": None, "cgroup_mb": None, "yuk_1dk": None, "olc_ms": None})
    h = pano._kaynak_html(k)
    assert "RAM: — · tepe 640 MB" in h                       # ölçülemeyen alan "—", diğer alanlar yerinde
    assert "bellek (servis): —" in h
    assert "yük (1 dk): — · disk boş: 12,5 GB" in h
    assert "ölçüm zamanı: —" in h
    assert "veri yok" not in h


def test_tum_alanlar_null_kart_yine_render_edilir():
    k = {"ram_mb": None, "ram_tepe_mb": None, "cgroup_mb": None, "cgroup_tepe_mb": None,
         "yuk_1dk": None, "disk_bos_gb": None, "disk_toplam_gb": None, "olc_ms": None}
    h = pano._kaynak_html(k)
    assert "veri yok" not in h
    assert "RAM: — · tepe —" in h
    assert "disk boş: —" in h


def test_kaynak_yoksa_veri_yok():
    for kaynak in (None, {}, "bozuk"):
        h = pano._kaynak_html(kaynak)  # type: ignore[arg-type]
        assert h == pano.BIRIKIYOR
