"""Public Hyperliquid client (rate limiter + retries); all HTTP reads are unauthenticated.

Eski günlük aday tarayıcı (prefilter/run/main) T1'de silindi; yeni tarama T2'de yazılacak."""
from __future__ import annotations

import time
from typing import Any

import requests

from copytrade.kurallar import load_rules

LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
INFO = "https://api.hyperliquid.xyz/info"
MAX_WEIGHT_PER_MINUTE = 700  # IP sınırı 1.200; yanıt boyutu ek ağırlığı ve paylaşılan Actions IP'leri için pay


class RateLimiter:
    def __init__(self, limit: int = MAX_WEIGHT_PER_MINUTE, clock=time.monotonic, sleep=time.sleep):
        self.limit, self.clock, self.sleep, self.events = limit, clock, sleep, []
        self.waited = 0.0  # istemci tarafı hız sınırında bekleyen toplam süre (sn); ilerleme günlüğü için
        self.weight_used = 0

    def acquire(self, weight: int) -> None:
        while True:
            now = self.clock()
            self.events = [(at, used) for at, used in self.events if now - at < 60]
            if sum(used for _, used in self.events) + weight <= self.limit:
                self.events.append((now, weight))
                self.weight_used += weight
                return
            pause = max(0.01, 60 - (now - self.events[0][0]))
            self.waited += pause
            self.sleep(pause)


class RateLimitError(RuntimeError):
    """Persistent 429 for one request; the address is skipped, the run continues."""


SERVER_ERROR_ATTEMPTS = 3          # (eski ilke) HTTP 5xx için toplam deneme
SERVER_ERROR_WAITS = (2, 6)        # (eski ilke) denemeler arası artan bekleme (sn)
RATE_LIMIT_WAITS = (5, 10, 20, 40, 60)           # (eski ilke) 429: 5 yeniden deneme
KAPI_YENIDEN_BEKLEME = (5, 15, 45)               # kapı ilkesi: YALNIZ 5xx ve ağ hatasında 3 yeniden deneme, bekleme (sn); 4xx (429 hariç) yeniden denenmez
RETRY_AFTER_MAX = 300                            # 429'da `Retry-After` başlığına uyulur (bekleme = max(takvim, başlık)); uç değerler bu kadar sn ile sınırlanır
_AG_HATALARI = (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError)


class PublicClient:
    def __init__(self, session: requests.Session | None = None, limiter: RateLimiter | None = None, sleep=time.sleep,
                 yeniden_bekleme: tuple[float, ...] | None = None):
        """``yeniden_bekleme`` verilirse (kapı: ``KAPI_YENIDEN_BEKLEME``) 5xx VE ağ hatasının her biri için o kadar yeniden deneme (bekleme sn). ``None`` = eski ilke
        (5xx: 2 yeniden deneme 2/6 sn, ağ hatası yeniden denenmez; izleme / H1 gibi diğer tüketiciler değişmez). 429 HER İKİ ilkede de aynıdır: 5 yeniden deneme
        5/10/20/40/60 sn (toplam 135 sn; lider kararı: kısalmaz) ve varsa ``Retry-After`` başlığına uyulur."""
        self.session, self.limiter, self.sleep = session or requests.Session(), limiter or RateLimiter(), sleep
        self.yeniden_bekleme = yeniden_bekleme
        self.stats = {"istek": 0, "429": 0, "5xx": 0, "ag": 0}  # ilerleme günlüğü için sayaçlar
        self.uclar: dict[str, list[int]] = {}           # uç türü (info `type`, ya da GET) -> [istek, ağırlık]; ağır trader teşhisi (A4-1)

    def _waits(self, kind: str) -> tuple[float, ...]:
        if kind == "429":
            return RATE_LIMIT_WAITS
        if self.yeniden_bekleme is not None:
            return self.yeniden_bekleme
        return {"5xx": SERVER_ERROR_WAITS, "ag": ()}[kind]

    @staticmethod
    def _retry_after(response: Any) -> float:
        """`Retry-After` (saniye) başlığı; yok / geçersizse 0. `RETRY_AFTER_MAX` ile sınırlı."""
        try:
            return min(max(float((getattr(response, "headers", None) or {}).get("Retry-After", 0)), 0.0), RETRY_AFTER_MAX)
        except (TypeError, ValueError):
            return 0.0

    def _request(self, method: str, url: str, *, payload: dict | None = None, weight: int = 1) -> Any:
        used = {"5xx": 0, "429": 0, "ag": 0}          # hata türü başına yapılan yeniden deneme
        while True:
            self.limiter.acquire(weight)
            try:
                response = self.session.request(method, url, json=payload, timeout=30)
            except _AG_HATALARI:
                self.stats["ag"] += 1
                waits = self._waits("ag")
                if used["ag"] >= len(waits):
                    raise
                self.sleep(waits[used["ag"]])
                used["ag"] += 1
                continue
            self.stats["istek"] += 1
            uc = self.uclar.setdefault(str(payload.get("type", "?")) if isinstance(payload, dict) else method, [0, 0])
            uc[0] += 1
            uc[1] += weight
            kind = "5xx" if response.status_code >= 500 else "429" if response.status_code == 429 else None
            if kind is not None:
                self.stats[kind] += 1
                waits = self._waits(kind)
                if used[kind] >= len(waits):       # yeniden deneme tükendi: 5xx -> HTTPError, 429 -> RateLimitError
                    if kind == "429":
                        raise RateLimitError("Hyperliquid rate limit exceeded after retries")
                    response.raise_for_status()
                self.sleep(max(waits[used[kind]], self._retry_after(response)) if kind == "429" else waits[used[kind]])
                used[kind] += 1
                continue
            response.raise_for_status()           # diğer 4xx: yeniden denenmez
            data = response.json()
            # Yanıt boyutuna göre ek ağırlık (Hyperliquid belgesi): dolum/fonlama listelerinde 20 kayıt başına 1;
            # candleSnapshot'ta 60 mum başına 1 (belgeden hatırlanan değer; 429 artarsa günlükte görünür).
            per = 60 if isinstance(payload, dict) and payload.get("type") == "candleSnapshot" else 20
            if isinstance(data, list) and len(data) >= per:
                self.limiter.acquire(len(data) // per)
                uc[1] += len(data) // per
            return data

    def leaderboard(self) -> list[dict]:
        data = self._request("GET", LEADERBOARD)
        return data.get("leaderboardRows", data) if isinstance(data, dict) else data

    def info(self, payload: dict, weight: int = 20) -> Any:
        return self._request("POST", INFO, payload=payload, weight=weight)

    def fills(self, address: str, start_ms: int, max_rows: int | None = None, end_ms: int | None = None) -> list[dict]:
        # Resmî uç nokta imleç zaman damgasıyla sayfalar; tid ile tekilleştirilir. İmleç `newest` (newest + 1 değil): sayfa sınırında aynı ms'ye düşen
        # sonraki dolumlar kaybolmaz. Sayfanın tamamı aynı ms'deyse ya da yeni dolum gelmediyse imleç 1 ms ilerler (A19).
        page_size = int(load_rules()["api_sayfa_boyutu_dolum"])
        result, cursor, seen = [], start_ms, set()
        while True:
            page = self.info({"type": "userFillsByTime", "user": address, "startTime": cursor, "endTime": int(time.time() * 1000) if end_ms is None else int(end_ms)})
            if not page:
                break
            fresh = 0
            for fill in page:
                key = str(fill.get("tid", (fill.get("time"), fill.get("coin"), fill.get("sz"))))
                if key not in seen:
                    seen.add(key); result.append(fill); fresh += 1
            times = [int(x.get("time", 0)) for x in page]
            newest, oldest = max(times), min(times)
            if len(page) < page_size or newest < cursor or (max_rows is not None and len(result) >= max_rows):
                break                                  # son sayfa; sunucu imleci yok saydı (eski veri); hedef doldu
            if oldest == newest or not fresh:
                cursor = newest + 1                    # tüm sayfa aynı ms ya da yeni dolum yok: 1 ms ilerle
            else:
                cursor = newest
        return result

    def portfolio(self, address: str) -> list[dict]:
        return self.info({"type": "portfolio", "user": address}, weight=20) or []

    def non_funding_ledger(self, address: str, start_ms: int) -> list[dict]:
        return self.info({"type": "userNonFundingLedgerUpdates", "user": address, "startTime": start_ms}, weight=20) or []

    def sub_accounts(self, address: str) -> list[dict]:
        return self.info({"type": "subAccounts", "user": address}, weight=20) or []

    def vault_equities(self, address: str) -> list[dict]:
        return self.info({"type": "userVaultEquities", "user": address}, weight=20) or []

    def vault_details(self, vault: str) -> dict:
        return self.info({"type": "vaultDetails", "vaultAddress": vault}, weight=20) or {}

    def extra_agents(self, address: str) -> list[dict]:
        return self.info({"type": "extraAgents", "user": address}, weight=20) or []

    def candles(self, coin: str, start_ms: int, end_ms: int, interval: str = "1m") -> list[dict]:
        return self.info({"type": "candleSnapshot", "req": {"coin": coin, "interval": interval,
                          "startTime": start_ms, "endTime": end_ms}}, weight=20) or []


def _address(row: dict) -> str:
    return str(row.get("ethAddress", row.get("address", row.get("user", ""))))


def _window(row: dict, name: str, field: str) -> float:
    """Support both flattened leaderboard rows and ``windowPerformances``."""
    aliases = {"month": ("month", "30d"), "allTime": ("allTime", "all", "all_time")}
    wanted = {x.lower() for x in aliases.get(name, (name,))}
    for item in row.get("windowPerformances", []):
        # Live API shape: ["month", {"pnl": "...", "roi": "...", "vlm": "..."}]; older docs: {"window": ..., ...}
        if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[1], dict):
            window, values = item
        elif isinstance(item, dict):
            window, values = item.get("window", ""), item
        else:
            continue
        if str(window).lower() in wanted:
            return float(values.get(field, 0) or 0)
    keys = (f"{name}{field.upper()}", f"{name}{field.capitalize()}", f"{name}_{field}")
    direct = next((float(row[key] or 0) for key in keys if key in row), None)
    if direct is not None:
        return direct
    # Flattened leaderboard names use mixed case (for example ``allTimePnl``).
    wanted_key = f"{name}{field}".lower().replace("_", "")
    return next((float(value or 0) for key, value in row.items()
                 if str(key).lower().replace("_", "") == wanted_key), 0.0)
