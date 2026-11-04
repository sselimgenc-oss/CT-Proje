"""Hyperliquid/Binance ortak yardımcılar (eski kapı modülünden taşındı, T1; davranış değişmedi).

Salt okunur: kimlik doğrulama, emir ya da cüzdan yok. Maliyet parametreleri `kurallar.yaml`'dan gelir.
"""
from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

from copytrade.kurallar import load_rules

TAKER = float(load_rules()["maliyet_taker"])
SLIPPAGE = float(load_rules()["maliyet_kayma"])


def spot_usdc(client: Any, address: str) -> float:
    """Spot USDC bakiyesi (``spotClearinghouseState``; USDC dışı bakiyeler sayılmaz). İlk 11 `hesap` alanının İ (kapı) ve F (izleme) tanımı bunu
    paylaşır: ana + HIP-3 + spot USDC (kural 7)."""
    state = client.info({"type": "spotClearinghouseState", "user": address}, weight=2) or {}
    return sum(float(b.get("total", 0) or 0) for b in state.get("balances", []) if str(b.get("coin")) == "USDC")


@lru_cache(maxsize=1)
def _binance_aliases() -> dict[str, str]:
    return {str(k).upper(): str(v).upper() for k, v in (load_rules().get("binance_takma_ad") or {}).items()}


def binance_symbol(coin: str, aliases: dict[str, str] | None = None) -> str:
    """Hyperliquid coin → Binance USDⓈ-M sembolü; spot eşlenemez (``yok``).

    HIP-3 (``dex:AD``): önek atılır, takma ad tablosu (kurallar.yaml ``binance_takma_ad``: GOLD→XAU, SILVER→XAG,
    BRENTOIL→BZ; diğerleri aynı ad) + ``USDT``. Sembolün Binance'te gerçekten bulunması ``binance_availability``'de.
    """
    coin = str(coin)
    if coin.startswith("@") or "/" in coin:
        return "yok"
    if ":" in coin:
        name = coin.split(":", 1)[1].upper()
        return (aliases if aliases is not None else _binance_aliases()).get(name, name) + "USDT"
    return ("1000" + coin[1:] if coin.startswith("k") else coin) + "USDT"


def write_binance_universe(root: Path, now: datetime | None = None, get=requests.get) -> tuple[set[str] | None, str]:
    now = now or datetime.now(UTC)
    path = root / "binance_vadeli.txt"
    source = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        response = get(source, timeout=30)
        if response.status_code in (403, 451):
            path.write_text(f"# {source} | {now.isoformat()} | erişim engeli: HTTP {response.status_code}\n", encoding="utf-8")
            return None, f"HTTP {response.status_code}"
        response.raise_for_status()
        symbols = sorted(x["symbol"] for x in response.json().get("symbols", [])
                         if x.get("status") == "TRADING" and x.get("contractType") == "PERPETUAL"
                         and x.get("quoteAsset") == "USDT")
        path.write_text(f"# {source} | {now.isoformat()}\n" + "\n".join(symbols) + "\n", encoding="utf-8")
        return set(symbols), "ok"
    except requests.RequestException as exc:
        path.write_text(f"# {source} | {now.isoformat()} | erişim hatası: {type(exc).__name__}\n", encoding="utf-8")
        return None, type(exc).__name__


def read_binance_universe(path: Path) -> tuple[set[str] | None, str]:
    """Plan işinin dondurduğu listeyi oku; engelli kaynak tüm parçalarda yoktur."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"Geçersiz Binance anlık görüntüsü: {path}")
    if "erişim " in lines[0]:
        return None, lines[0].rsplit(": ", 1)[-1]
    return {line.strip() for line in lines[1:] if line.strip()}, "dondurulmuş"


def binance_availability(coin: str, symbols: set[str] | None) -> str:
    if binance_symbol(coin) == "yok":
        return "yok"
    return "bilinmiyor" if symbols is None else ("var" if binance_symbol(coin) in symbols else "yok")
