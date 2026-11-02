"""Veri dalı kökündeki ``son.json`` işaretçisini günceller: ``python son_yaz.py son.json anahtar değer [anahtar değer …]``.

ve ``uretildi`` değişir. Biçim: ``{"kapi": "<tarih>", "secim": "<klasör>", "uretildi": "<ISO UTC>"}``.
"""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def yaz(path: Path, guncel: dict[str, str], simdi: datetime | None = None) -> dict[str, str]:
    mevcut = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    mevcut.update(guncel)
    mevcut["uretildi"] = (simdi or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(dict(sorted(mevcut.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return mevcut


def main(argv: list[str]) -> None:
    if len(argv) < 4 or len(argv) % 2:
        raise SystemExit("kullanım: son_yaz.py son.json anahtar değer [anahtar değer …]")
    yaz(Path(argv[1]), dict(zip(argv[2::2], argv[3::2], strict=True)))


if __name__ == "__main__":
    main(sys.argv)
