"""Bir izleme koşusu içinde aynı mum isteğini tekilleştirir (A4 süre iyileştirmesi; hesap DEĞİŞMEZ).

``candleSnapshot`` her trader için coin başına yürütme (1 dk), tasfiye (1 sa) ve işaretleme (1 dk) olarak ayrı istenir; ağır traderlarda süre bu isteklerin
hız sınırı (700 ağırlık/dk) beklemesidir. Bu sarmalayıcı koşu boyunca gelen yanıtları tutar ve şu durumlarda API'ye GİTMEDEN yanıtlar:

1. Aynı (coin, aralık, başlangıç, bitiş): aynen önceki yanıt.
2. Daha önce alınmış TAM bir yanıtın kapsadığı alt aralık: önceki yanıt ``başlangıç ≤ t ≤ bitiş`` süzülür. Yanıt tam sayılmak için 5.000 mumdan kısa olmalı (API üst sınırı; kesilmiş
   yanıt asla yeniden kullanılmaz). Başlangıç mum sınırına hizalıysa süzme API ile aynıdır; hizalı değilse (işaretleme penceresi ``şimdi − 15 dk``) yalnız süzülmüş sonuç BOŞ DEĞİLSE kullanılır
   (boşsa API'ye sorulur: sunucu başlangıcı içeren mumu döndürüyor olabilir).

Yanıtlar yalnız bu nesne yaşadığı sürece (bir ``run``) tutulur; koşular arası önbellek yoktur."""
from __future__ import annotations

from typing import Any

SINIR = 5000                       # candleSnapshot yanıtında en çok mum
ADIM_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}


class MumPaylasimi:
    def __init__(self, istemci: Any) -> None:
        self._istemci = istemci
        self._yanitlar: dict[tuple[str, str], list[tuple[int, int, list[dict]]]] = {}
        self.istek = 0
        self.paylasilan = 0

    def __getattr__(self, ad: str) -> Any:          # candles dışındaki her şey (info, limiter, stats, uclar…) aynen
        return getattr(self._istemci, ad)

    def candles(self, coin: str, start_ms: int, end_ms: int, interval: str = "1m") -> list[dict]:
        for s, e, satirlar in self._yanitlar.get((coin, interval), []):
            if s == start_ms and e == end_ms:
                self.paylasilan += 1
                return list(satirlar)
            if s <= start_ms and end_ms <= e and len(satirlar) < SINIR:
                secilen = [c for c in satirlar if start_ms <= int(c["t"]) <= end_ms]
                hizali = start_ms % ADIM_MS.get(interval, 1) == 0
                if hizali or secilen:
                    self.paylasilan += 1
                    return secilen
        satirlar = self._istemci.candles(coin, start_ms, end_ms, interval=interval)
        self.istek += 1
        if isinstance(satirlar, list):
            self._yanitlar.setdefault((coin, interval), []).append((start_ms, end_ms, list(satirlar)))
        return satirlar
