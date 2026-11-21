"""Günlük kayıt dosyalarını (JSONL) pencere için okur; kural_maliyet ve secim_gercek raporları kullanır."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

PENCERE_GUN = 7


def kayitlari_oku(dizin: Path, simdi_ms: int, gun: int = PENCERE_GUN) -> list[dict]:
    """Pencereyi kapsayan günlük JSONL dosyaları (bozuk satır/eksik dosya atlanır)."""
    satirlar: list[dict] = []
    for i in range(gun + 1):
        g = datetime.fromtimestamp((simdi_ms - i * 86_400_000) / 1000, UTC).date().isoformat()
        try:
            with (Path(dizin) / f"{g}.jsonl").open(encoding="utf-8") as f:
                for s in f:
                    try:
                        o = json.loads(s)
                    except ValueError:
                        continue
                    if isinstance(o, dict):
                        satirlar.append(o)
        except OSError:
            continue
    return satirlar
