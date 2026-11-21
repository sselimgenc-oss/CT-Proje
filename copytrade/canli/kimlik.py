"""Cüzdan adresi için kararlı takma ad (tam adres hiçbir dosyaya yazılmaz; repo ve veri dalı herkese açık)."""
from __future__ import annotations

import hashlib


def takma_ad(adres: str) -> str:
    """Kararlı takma ad: `T_` + sha256(küçük harf adres) ilk 6 hex. Yalnız harf/rakam/`_`; `0x` içermez; geri çevrilemez."""
    return "T_" + hashlib.sha256(str(adres).strip().lower().encode("utf-8")).hexdigest()[:6]
