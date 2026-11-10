"""Geçmiş saatlik piyasa funding oranları; coin ve pencere başına tek istek."""
from __future__ import annotations

from typing import Any

HAFTA_MS = 7 * 24 * 3_600_000


class FundingOnbellegi:
    def __init__(self, client: Any):
        self.client = client
        self.cache: dict[tuple[str, int], list[dict]] = {}

    def oku(self, coinler: set[str], bas: int, bit: int) -> list[dict]:
        sonuc = []
        for coin in sorted(coinler):
            for hafta in range(bas // HAFTA_MS * HAFTA_MS, bit, HAFTA_MS):
                key = (coin, hafta)
                if key not in self.cache:
                    rows = self.client.info({"type": "fundingHistory", "coin": coin, "startTime": hafta,
                                             "endTime": hafta + HAFTA_MS}, weight=20)
                    if not isinstance(rows, list):
                        raise ValueError(f"{coin} fundingHistory yanıtı liste değil")
                    self.cache[key] = [{"time": int(r["time"]), "delta": {"coin": coin, "fundingRate": str(r["fundingRate"])}}
                                       for r in rows if hafta <= int(r["time"]) < hafta + HAFTA_MS]
                sonuc.extend(r for r in self.cache[key] if bas <= r["time"] < bit)
        return sonuc
