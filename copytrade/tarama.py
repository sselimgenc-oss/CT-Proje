"""Daily public Hyperliquid scanner; all HTTP reads are unauthenticated."""
from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from copytrade.izleme import load as load_watchlist
from copytrade.izleme import update
from copytrade.kopya import simulate
from copytrade.kurallar import evaluate, load_rules
from copytrade.olcut import calculate_metrics

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


SERVER_ERROR_ATTEMPTS = 3          # HTTP 5xx için toplam deneme
SERVER_ERROR_WAITS = (2, 6)        # denemeler arası artan bekleme (sn)


class PublicClient:
    def __init__(self, session: requests.Session | None = None, limiter: RateLimiter | None = None, sleep=time.sleep):
        self.session, self.limiter, self.sleep = session or requests.Session(), limiter or RateLimiter(), sleep
        self.stats = {"istek": 0, "429": 0, "5xx": 0}  # ilerleme günlüğü için sayaçlar

    def _request(self, method: str, url: str, *, payload: dict | None = None, weight: int = 1) -> Any:
        server_errors = 0
        for attempt in range(6):
            self.limiter.acquire(weight)
            response = self.session.request(method, url, json=payload, timeout=30)
            self.stats["istek"] += 1
            if response.status_code >= 500:
                self.stats["5xx"] += 1
                # Geçici sunucu hatası (ör. 500/502/503): 3 deneme, artan bekleme; sonra hata olarak yükselir.
                server_errors += 1
                if server_errors >= SERVER_ERROR_ATTEMPTS:
                    response.raise_for_status()
                self.sleep(SERVER_ERROR_WAITS[server_errors - 1])
                continue
            if response.status_code != 429:
                response.raise_for_status()
                data = response.json()
                # Yanıt boyutuna göre ek ağırlık (Hyperliquid belgesi): dolum/fonlama listelerinde 20 kayıt başına 1;
                # candleSnapshot'ta 60 mum başına 1 (belgeden hatırlanan değer; 429 artarsa günlükte görünür).
                per = 60 if isinstance(payload, dict) and payload.get("type") == "candleSnapshot" else 20
                if isinstance(data, list) and len(data) >= per:
                    self.limiter.acquire(len(data) // per)
                return data
            self.stats["429"] += 1
            self.sleep(min(60, 5 * 2 ** attempt))
        raise RateLimitError("Hyperliquid rate limit exceeded after retries")

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


def prefilter(rows: list[dict], watchlist: list[dict] | None = None) -> list[dict]:
    """CT-Kapı evreni: lider tablosundaki tüm yeterli büyüklükte, pozitif PnL'li hesaplar.

    ``watchlist`` eski günlük tarayıcı çağrılarıyla uyumluluk içindir; kapı evrenini genişletmez veya daraltmaz.
    """
    watch = {x["address"].lower() for x in watchlist or []}
    esik = float(load_rules()["evren_min_hesap_degeri"])      # BİR kez okunur: satır başına YAML okumak 48 bin satırda ~17 dk sürüyordu (A2-3b ölçümü)
    accepted = []
    for row in rows:
        address = _address(row)
        account = float(row.get("accountValue", row.get("account_value", 0)) or 0)
        all_time_pnl = _window(row, "allTime", "pnl")
        if address and account >= esik and all_time_pnl > 0:
            row = dict(row); row["address"] = address; row["accountValue"] = account; accepted.append(row)
    return sorted(accepted, key=lambda x: x["address"].lower())


def _write_gzip(rows: list[dict], path: Path, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if append and path.exists():
        old = pd.read_csv(path, compression="gzip")
        frame = pd.concat([old, frame], ignore_index=True)
        keys = [key for key in ("tid", "time", "coin", "sz", "px") if key in frame]
        if keys:
            frame = frame.drop_duplicates(keys, keep="first")
    frame.to_csv(path, index=False, compression="gzip")


def _write_report(root: Path, today: str, table: pd.DataFrame, copies: list[dict]) -> None:
    tested = len(table)
    candidates = int((table["sonuc"] == "aday").sum()) if not table.empty else 0
    flags = int(table["martingale_signal"].fillna(False).astype(bool).sum()) if not table.empty and "martingale_signal" in table else 0
    lines = ["# Copy trade günlük raporu", "", f"Tarih: {today}", "", f"- Test edilen adres: {tested}",
             f"- Yeni aday: {candidates}", f"- Martingale kırmızı bayrağı: {flags}", "",
             "## t0 sonrası yaklaşık sanal kopya", "", "| Adres | Net (USD) | MDD | İşlem |", "|---|---:|---:|---:|"]
    for item in copies:
        lines.append(f"| {item['address']} | {item['net']:.2f} | {item['mdd']:.2%} | {item['trades']} |")
    if not copies:
        lines.append("| Henüz izlenen adres yok | — | — | — |")
    lines.extend(["", "Kopya sonuçları günlük tarama nedeniyle **yaklaşıktır**; emir, cüzdan ve gerçek para kullanılmaz."])
    (root / "RAPOR.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(root: Path, client: PublicClient, today: str | None = None, version: str = "v1", limit: int | None = None) -> pd.DataFrame:
    today = today or datetime.now(UTC).date().isoformat()
    watch_path = root / "izleme.csv"
    watchlist = load_watchlist(watch_path)
    leaders = prefilter(client.leaderboard(), watchlist)
    if limit is not None:
        leaders = leaders[:limit]
    _write_gzip(leaders, root / "veri" / "lider" / f"{today}.csv.gz")
    liquid = {"BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI", "LTC", "BCH", "PEPE", "WIF", "AAVE", "CRV", "ARB", "OP", "APT", "INJ"}
    rules = load_rules()
    # 180 gün geçmiş şartının ölçülebilmesi için pencere ondan uzun olmalı.
    start = int((datetime.now(UTC) - timedelta(days=int(rules["fills_lookback_days"]))).timestamp() * 1000)
    rows = []
    copies = []
    for leader in leaders:
        address = leader["address"]
        try:
            fills = client.fills(address, start)
            funding = client.info({"type": "userFunding", "user": address, "startTime": start}, weight=20)
            state = client.info({"type": "clearinghouseState", "user": address}, weight=2)
        except (RateLimitError, requests.RequestException) as exc:
            # Missing data is never a pass or a fail: recorded as "veri_yok" and retried tomorrow.
            rows.append({"address": address, "account_value": leader["accountValue"], "sonuc": "veri_yok",
                         "neden": type(exc).__name__})
            continue
        leverage = [float(x.get("position", {}).get("leverage", {}).get("value", 0)) for x in state.get("assetPositions", [])]
        metrics = calculate_metrics(fills, funding=funding, liquid_coins=liquid, leverages=leverage,
                                    account_value=leader["accountValue"],
                                    martingale_max_ratio=float(rules["martingale_max_ratio"]),
                                    martingale_min_additions=int(rules["martingale_min_additions"]))
        decision, reason = evaluate(metrics)
        rows.append({"address": address, "account_value": leader["accountValue"], "sonuc": decision, "neden": reason, **metrics})
        _write_gzip(fills, root / "veri" / "fills" / f"{address.lower()}.csv.gz", append=True)
        if address.lower() in {x["address"].lower() for x in watchlist}:
            for slip in (0.0005, 0.0015):
                copy = simulate(fills, leader["accountValue"], slippage=slip, funding=funding)
                (root / "kopya").mkdir(parents=True, exist_ok=True)
                copy.to_csv(root / "kopya" / f"{address.lower()}_{int(slip * 10000)}bp.csv", index=False)
                if slip == 0.0005 and not copy.empty:
                    drawdown = copy.equity / copy.equity.cummax() - 1
                    copies.append({"address": address, "net": float(copy.equity.iloc[-1] - 1000),
                                   "mdd": abs(float(drawdown.min())), "trades": metrics["closed_trades"]})
    table = pd.DataFrame(rows)
    (root / "veri" / "adaylar").mkdir(parents=True, exist_ok=True)
    table.to_csv(root / "veri" / "adaylar" / f"{today}.csv", index=False)
    candidates = table.loc[table.sonuc == "aday", "address"].tolist() if not table.empty else []
    statuses = {str(x["address"]).lower(): str(x["sonuc"]) for x in rows}
    update(watch_path, candidates, today, version, statuses, int(rules["max_watchlist"]))
    _write_report(root, today, table, copies)
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Hyperliquid candidate scanner")
    parser.add_argument("--root", type=Path, default=Path("copytrade"))
    parser.add_argument("--version", default="v1")
    parser.add_argument("--limit", type=int, help="only inspect this many prefiltered addresses (for a short run)")
    args = parser.parse_args()
    table = run(args.root, PublicClient(), version=args.version, limit=args.limit)
    print(json.dumps({"tested": len(table), "candidates": int((table.sonuc == 'aday').sum()) if not table.empty else 0}))


if __name__ == "__main__":
    main()
