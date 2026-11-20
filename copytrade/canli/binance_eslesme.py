"""HL coin -> Binance USDⓈ-M sembol eşlemesi (K-81, Aşama A Binance kâğıt; docs/binance-plan.md §3). SAF (ağ yok): tablo `copytrade/binance_eslesme.yaml`.

`coz(coin)` döner `(Esleme | None, neden | None)`. Neden kodları (AÇILIŞ atlama; kapanış/azaltma eşleme tablosunda varsa serbest):
- `binance_eslesme_yok`: tabloda yok (spot `@N`, `A/B`, bilinmeyen HIP-3, bilinmeyen `kXXX`) ya da tabloda Binance karşılığı `null`;
- `binance_eslesme_dogrulanmadi`: tabloda var ama `dogrulandi: false` (dayanak varlık / çarpan teyitli değil).
Birim kuralı: HL fiyatı = Binance fiyatı × `carpan`; HL miktarı = Binance miktarı / `carpan` (nosyonel $ iki yanda aynı). kPEPE <-> 1000PEPEUSDT çarpanı 1'dir (ikisi de 1000 PEPE)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ESLEME_YOLU = Path(__file__).resolve().parent.parent / "binance_eslesme.yaml"
NEDEN_YOK = "binance_eslesme_yok"
NEDEN_DOGRULANMADI = "binance_eslesme_dogrulanmadi"


@dataclass(frozen=True)
class Esleme:
    hl: str
    binance: str
    carpan: float = 1.0
    dogrulandi: bool = False
    tur: str = "kripto"


class EslemeTablosu:
    def __init__(self, veri: dict | None = None) -> None:
        veri = veri or {}
        ana = veri.get("ana_dex") or {}
        self.otomatik = bool(ana.get("otomatik", False))
        self.sonek = str(ana.get("sonek", "USDT"))
        self._satir: dict[str, dict] = {str(k): dict(v) for k, v in (veri.get("satirlar") or {}).items() if isinstance(v, dict)}
        for k, v in self._satir.items():
            c = float(v.get("carpan", 1) or 0)
            if not c > 0:
                raise ValueError(f"binance_eslesme: {k} için carpan > 0 olmalı")

    @classmethod
    def yukle(cls, yol: Path = ESLEME_YOLU) -> "EslemeTablosu":
        with Path(yol).open(encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    def coz(self, coin: str) -> tuple[Esleme | None, str | None]:
        coin = str(coin)
        s = self._satir.get(coin)
        if s is not None:
            sembol = s.get("binance")
            if not sembol:
                return None, NEDEN_YOK
            e = Esleme(coin, str(sembol), float(s.get("carpan", 1) or 1), bool(s.get("dogrulandi", False)), str(s.get("tur", "kripto")))
            return (e, None) if e.dogrulandi else (e, NEDEN_DOGRULANMADI)
        if self.otomatik and coin and not coin.startswith("@") and "/" not in coin and ":" not in coin and not (coin[0] == "k" and len(coin) > 1 and coin[1:].isupper()):
            return Esleme(coin, coin.upper() + self.sonek, 1.0, True, "kripto"), None
        return None, NEDEN_YOK

    def semboller(self) -> list[str]:
        """Tablodaki (açık satırlar) benzersiz Binance sembolleri."""
        return sorted({str(v["binance"]) for v in self._satir.values() if v.get("binance")})

    def hl_coinleri(self, sembol: str) -> list[str]:
        return [k for k, v in self._satir.items() if v.get("binance") == sembol]

    def to_json(self) -> dict[str, Any]:
        return {"otomatik": self.otomatik, "satir": len(self._satir)}
