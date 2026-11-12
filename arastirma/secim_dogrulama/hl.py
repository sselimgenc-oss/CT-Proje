"""HL salt-okur istemci: küresel token-bucket hız sınırı + yeniden deneme + diskte kalıcı önbellek (adres/uç başına bir gzip JSON).

Yalnız iki uç: api.hyperliquid.xyz/info (POST) ve stats-data.hyperliquid.xyz/Mainnet/leaderboard (GET). Anahtar / emir YOK.
"""
from __future__ import annotations

import gzip
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import requests

KOK = Path(os.environ.get("WF_VERI") or Path(__file__).resolve().parent)   # veri dizini (Actions: geri yüklenen durum)
CACHE = KOK / "cache"
INFO = "https://api.hyperliquid.xyz/info"
LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

AGIRLIK_DK = 1000          # ağırlık/dk (HL IP sınırı ~1200; pay bırakılır)
KOVA = 200                 # anlık patlama kapasitesi (ağırlık)
BEKLE_429 = (10, 20, 40, 80, 160, 300)
BEKLE_5XX = (5, 15, 45, 90)


# ------------------------------------------------------------------------------------------------ önbellek
def yol(uc: str, anahtar: str) -> Path:
    return CACHE / uc / f"{anahtar.lower()}.json.gz"


def oku(uc: str, anahtar: str) -> Any:
    p = yol(uc, anahtar)
    if not p.exists():
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, EOFError):
        return None               # bozuk dosya: yeniden çekilir


def yaz(uc: str, anahtar: str, veri: Any) -> None:
    p = yol(uc, anahtar)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + f".tmp{os.getpid()}")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=5) as f:
        json.dump(veri, f, separators=(",", ":"))
    tmp.replace(p)


def var_mi(uc: str, anahtar: str) -> bool:
    return yol(uc, anahtar).exists()


# ------------------------------------------------------------------------------------------------ hız sınırı
class TokenBucket:
    """Küresel (süreç içi, iş parçacığı güvenli) kova: dakikada `oran` ağırlık dolar, en çok `kapasite` birikir. Yanıt sonrası ek ağırlık
    (dolum/mum listesi boyutu) `borc` ile düşülür; kova eksiye inebilir, sonraki istek bekler."""

    def __init__(self, oran: float = AGIRLIK_DK, kapasite: float = KOVA):
        self.oran, self.kapasite = oran / 60.0, kapasite
        self.jeton, self.t = kapasite, time.monotonic()
        self.kilit = threading.Lock()
        self.toplam = 0.0
        self.baslangic = time.monotonic()

    def _doldur(self) -> None:
        now = time.monotonic()
        self.jeton = min(self.kapasite, self.jeton + (now - self.t) * self.oran)
        self.t = now

    def al(self, w: float) -> None:
        while True:
            with self.kilit:
                self._doldur()
                if self.jeton >= min(w, self.kapasite):
                    self.jeton -= w
                    self.toplam += w
                    return
                bekle = (min(w, self.kapasite) - self.jeton) / self.oran
            time.sleep(min(max(bekle, 0.05), 30))

    def borc(self, w: float) -> None:
        with self.kilit:
            self._doldur()
            self.jeton -= w
            self.toplam += w

    def yavasla(self) -> None:
        """429 geldi: oran %15 düşer (en az 400/dk); 10 dk 429'suz geçerse %5 artar (en çok AGIRLIK_DK)."""
        with self.kilit:
            self.oran = max(400 / 60.0, self.oran * 0.85)
            self.son429 = time.monotonic()

    def toparlan(self) -> None:
        with self.kilit:
            if time.monotonic() - getattr(self, "son429", 0) > 300 and self.oran < AGIRLIK_DK / 60.0:
                self.oran = min(AGIRLIK_DK / 60.0, self.oran * 1.05)
                self.son429 = time.monotonic() - 150

    def hiz(self) -> float:
        dk = max((time.monotonic() - self.baslangic) / 60.0, 1e-9)
        return self.toplam / dk


class HLHatasi(RuntimeError):
    pass


class Istemci:
    """Repo modüllerinin beklediği yüzey (`info`, `candles`, `portfolio`, `leaderboard`) + sayaçlar."""

    def __init__(self, kova: TokenBucket | None = None, log=print):
        self.kova = kova or TokenBucket()
        self.s = requests.Session()
        self.log = log
        self.stats = {"istek": 0, "429": 0, "5xx": 0, "ag": 0, "hata": 0}
        self.son_hata: str | None = None

    def _istek(self, method: str, url: str, payload: dict | None, w: int) -> Any:
        n429 = n5 = 0
        while True:
            self.kova.al(w)
            try:
                r = self.s.request(method, url, json=payload, timeout=60)
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as h:
                self.stats["ag"] += 1
                if n5 >= len(BEKLE_5XX):
                    self.stats["hata"] += 1
                    self.son_hata = f"ağ: {type(h).__name__}"
                    raise HLHatasi(self.son_hata) from h
                time.sleep(BEKLE_5XX[n5]); n5 += 1
                continue
            self.stats["istek"] += 1
            self.kova.toparlan()
            if r.status_code == 429:
                self.stats["429"] += 1
                if n429 >= len(BEKLE_429):
                    self.stats["hata"] += 1
                    self.son_hata = "429 yeniden deneme tükendi"
                    raise HLHatasi(self.son_hata)
                try:
                    ra = float(r.headers.get("Retry-After", 0) or 0)
                except ValueError:
                    ra = 0
                self.son_hata = f"429 (bekleme {max(BEKLE_429[n429], ra):.0f} sn)"
                self.kova.borc(self.kova.kapasite)          # kovayı boşalt: herkes yavaşlasın
                self.kova.yavasla()
                time.sleep(max(BEKLE_429[n429], min(ra, 300))); n429 += 1
                continue
            if r.status_code >= 500:
                self.stats["5xx"] += 1
                if n5 >= len(BEKLE_5XX):
                    self.stats["hata"] += 1
                    self.son_hata = f"HTTP {r.status_code}"
                    raise HLHatasi(self.son_hata)
                time.sleep(BEKLE_5XX[n5]); n5 += 1
                continue
            if r.status_code >= 400:
                self.stats["hata"] += 1
                self.son_hata = f"HTTP {r.status_code}: {r.text[:120]}"
                raise HLHatasi(self.son_hata)
            data = r.json()
            if isinstance(payload, dict) and isinstance(data, list):
                per = 60 if payload.get("type") == "candleSnapshot" else 20
                if len(data) >= per:
                    self.kova.borc(len(data) // per)
            return data

    # --- repo yüzeyi
    def info(self, payload: dict, weight: int = 20) -> Any:
        return self._istek("POST", INFO, payload, weight)

    def leaderboard(self) -> list[dict]:
        d = self._istek("GET", LEADERBOARD, None, 20)
        return d.get("leaderboardRows", d) if isinstance(d, dict) else d

    def portfolio(self, adres: str) -> Any:
        return self.info({"type": "portfolio", "user": adres}, weight=20) or []

    def candles(self, coin: str, start_ms: int, end_ms: int, interval: str = "1h") -> list[dict]:
        return self.info({"type": "candleSnapshot", "req": {"coin": coin, "interval": interval, "startTime": int(start_ms), "endTime": int(end_ms)}}, weight=20) or []

    # --- dolum: aralık sayfalama
    def dolum_aralik(self, adres: str, bas: int, bit: int, tavan: int | None = None) -> tuple[list[dict], bool]:
        """[bas, bit] perp+spot dolumları (artan zaman, tid tekil). Döner (dolumlar, kesildi_mi): `tavan` dolumu aşınca durur."""
        out, seen, imlec = [], set(), int(bas)
        while True:
            sf = self.info({"type": "userFillsByTime", "user": adres, "startTime": imlec, "endTime": int(bit)})
            if not sf:
                return out, False
            taze = 0
            for f in sf:
                k = str(f.get("tid", (f.get("time"), f.get("coin"), f.get("sz"), f.get("px"))))
                if k not in seen:
                    seen.add(k); out.append(f); taze += 1
            ts = [int(x.get("time", 0)) for x in sf]
            yeni, eski = max(ts), min(ts)
            if len(sf) < 2000 or yeni < imlec or yeni >= bit:
                return out, False
            if tavan is not None and len(out) >= tavan:
                return out, True
            imlec = yeni + 1 if (eski == yeni or not taze) else yeni
