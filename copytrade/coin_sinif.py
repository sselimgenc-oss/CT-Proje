"""Coin sınıflandırma (kripto / hisse / endeks / emtia / spot). NUMPY/PANDAS GEREKTİRMEZ: canlı vardiya iş akışı yalnız websockets/PyYAML/requests kurar;
motor bu modülü içe aktarır (olcut.py pandas gerektirdiği için doğrudan olcut içe aktarılamaz — 06.11 vardiyası numpy yokluğundan başlamadı)."""
from __future__ import annotations

COMMODITIES = {"CL", "BRENTOIL", "OIL", "GOLD", "SILVER", "XAU", "XAG", "NATGAS", "NG", "COPPER", "HG", "PLATINUM"}
INDICES = {"XYZ100", "SPX", "US500", "NDX", "NAS100", "US30", "DJI", "RUT", "SP500", "USA500", "USTECH"}


def asset_class(coin: str) -> str:
    """Hyperliquid coin -> kripto / hisse / endeks / emtia / spot. HIP-3 markets carry a ``dex:`` prefix."""
    coin = str(coin)
    if coin.startswith("@") or "/" in coin:
        return "spot"
    if ":" not in coin:
        return "kripto"
    name = coin.split(":", 1)[1].upper()
    return "emtia" if name in COMMODITIES else "endeks" if name in INDICES else "hisse"
