"""CT-Kapı v1 helpers and public-data runner.

This module never authenticates, places orders, or reads wallets.  It deliberately
keeps every unavailable public input as ``Yetersiz`` rather than estimating it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from bisect import bisect_left, bisect_right
from functools import lru_cache
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from copytrade.defter import DAY as DAY_MS
from copytrade.defter import FundingRates, Market, copy_ledger, delayed_execution_quality
from copytrade.ilk11_alanlar import kapi_bilgi_sutunlari
from copytrade.kurallar import load_rules
from copytrade.mum_saglik import mum_kontrol, ozet as mum_ozet
from copytrade.olcut import _funding_amount, asset_class, calculate_metrics, closed_round_trips, perp_fills
from copytrade.tarama import PublicClient, RateLimitError, RateLimiter, _address, prefilter
from kapi.istatistik import deflated_sharpe_ratio, nw_alpha

# Maliyet parametreleri kurallar.yaml'dan (izleme motoru bu adlarla içe aktarır)
TAKER = float(load_rules()["maliyet_taker"])
SLIPPAGE = float(load_rules()["maliyet_kayma"])


def _portfolio_history(portfolio: list[dict]) -> pd.Series:
    periods = {name: value for name, value in portfolio if isinstance(value, dict)}
    data = periods.get("perpAllTime") or periods.get("allTime") or {}
    points = data.get("accountValueHistory", [])
    return pd.Series({pd.to_datetime(t, unit="ms", utc=True): float(v) for t, v in points}).sort_index()


def external_cashflows(ledger: list[dict]) -> pd.Series:
    """Only public deposit/withdraw ledger rows are external flows; transfers are not guessed."""
    items: list[tuple[pd.Timestamp, float]] = []
    for row in ledger:
        delta = row.get("delta", {})
        kind = str(delta.get("type", row.get("type", ""))).lower() if isinstance(delta, dict) else ""
        if kind not in {"deposit", "withdraw", "internaltransfer", "subaccounttransfer", "vaultdeposit", "vaultwithdraw", "spottransfer", "send"}:
            continue
        raw = delta.get("usdc", row.get("usdc", 0)) if isinstance(delta, dict) else row.get("usdc", 0)
        amount = abs(float(raw))
        sender, user = str(row.get("from", row.get("sender", ""))).lower(), str(row.get("user", "")).lower()
        if kind == "withdraw" or (sender and user and sender == user):
            amount = -amount
        items.append((pd.to_datetime(row.get("time"), unit="ms", utc=True), amount))
    if not items:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    return pd.Series(dict(items), dtype=float).groupby(level=0).sum().sort_index()


def time_weighted_monthly(portfolio: list[dict], ledger: list[dict], days: int = 365) -> pd.Series:
    """Monthly time-weighted returns, removing documented deposits and withdrawals.

    Values and cash flows are aligned at their public timestamps.  A flow is
    removed from the closing value of its subperiod before compounding.
    """
    values = _portfolio_history(portfolio)
    if len(values) < 2:
        return pd.Series(dtype=float)
    since = values.index[-1] - pd.Timedelta(days=days)
    values = values[values.index >= since]
    flows = external_cashflows(ledger)
    # A cash flow belongs to the first observed portfolio value after it; never invent a value point.
    assigned = pd.Series(0.0, index=values.index)
    for at, amount in flows.items():
        later = values.index[values.index >= at]
        if len(later): assigned.loc[later[0]] += amount
    flows = assigned
    prior = values.shift(1)
    returns = (values - flows) / prior - 1
    returns = returns.iloc[1:].replace([np.inf, -np.inf], np.nan).dropna()
    if returns.empty:
        return pd.Series(dtype=float)
    return (1 + returns).groupby(returns.index.to_period("M")).prod() - 1


def stage1_stats(portfolio: list[dict], ledger: list[dict] | None = None, days: int | None = None) -> dict[str, float] | None:
    """1. aşama, Hyperliquid'in kendi kümülatif PnL serisinden (``allTime.pnlHistory``; yatırma/çekme içermez).

    Lider denetimi 2 (2026-10-27): hesap değeri serisinden zaman ağırlıklı getiri yatırma/çekme, spot↔perp ve
    örnekleme sıklığı yüzünden −%100 / +%10^40 gibi sonuçlar verdi; kullanılmaz. Kârlı ay = aylık PnL farkı > 0
    (payda gerekmez). Getiri ve düşüş, penceredeki pozitif hesap değerlerinin medyanına bölünür. ``ledger``
    geriye dönük uyumluluk içindir, kullanılmaz.
    """
    days = int(days if days is not None else load_rules()["asama1_pencere_gun"])
    periods = {name: value for name, value in portfolio if isinstance(value, dict)} if portfolio else {}
    data = periods.get("allTime") or {}
    points = data.get("pnlHistory", [])
    if len(points) < 2:
        return None
    pnl = pd.Series({pd.to_datetime(t, unit="ms", utc=True): float(v) for t, v in points}).sort_index()
    values = pd.Series({pd.to_datetime(t, unit="ms", utc=True): float(v) for t, v in data.get("accountValueHistory", [])})
    since = pnl.index[-1] - pd.Timedelta(days=days)
    before = pnl[pnl.index < since]
    window = pnl[pnl.index >= since]
    if len(window) < 2:
        return None
    base = float(before.iloc[-1]) if len(before) else float(window.iloc[0])
    month_end = window.resample("ME").last().dropna()
    monthly = month_end.diff()
    if len(before):
        monthly.iloc[0] = month_end.iloc[0] - base
    else:
        monthly = monthly.iloc[1:]  # pencereden önce başlamıyorsa ilk ay kısmi ve tabansız
    active = monthly[monthly.abs() > 0]
    if active.empty or not (values > 0).any():
        return None
    chain = twr_chain(pnl, values, since)
    if chain is None:
        return None
    equity = chain["equity"]
    drawdown = float((1.0 - equity / equity.cummax()).max())
    total = float(equity.iloc[-1] - 1.0)
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    calmar = None
    if years > 0 and drawdown > 0 and equity.iloc[-1] > 0:
        calmar = float((equity.iloc[-1] ** (1 / years) - 1) / drawdown)
    span = (pnl.index[-1] - max(pnl.index[0], since)).days
    return {"active_months": float(len(active)), "profitable_month_ratio": float((active > 0).mean()),
            "max_drawdown": drawdown, "return_12m": total, "calmar": calmar, "pnl_history_days": float(span),
            # Hesabın tüm geçmişi (365 gün pencereyle kırpılmaz): genç aday ayrımı için.
            "account_age_days": float((pnl.index[-1] - pnl.index[0]).days)}


def twr_chain(pnl: pd.Series, values: pd.Series, since: pd.Timestamp) -> dict[str, pd.Series] | None:
    """Zaman ağırlıklı getiri zinciri (görev 15): her alt dönemin getirisi = PnL farkı / dönem sermayesi.

    Yatırma/çekme getiri sayılmaz: dönem içi net akış = Δhesap değeri − ΔPnL; sermaye = dönem başı değer + akışın yarısı
    (Modified Dietz). Sermaye ≤ 0 olan dönem 0 getiri sayılır; getiri −1'in altına inmez. Düşüş (0–1) ve getiri bu zincirden çıkar;
    eski sürümdeki "PnL / pencere medyan hesap değeri" paydası yatırma-çekmede 10^12 gibi imkânsız değerler üretiyordu.
    """
    frame = pd.merge_asof(pnl.rename("pnl").to_frame(), values.sort_index().rename("av").to_frame(),
                          left_index=True, right_index=True, direction="backward").dropna()
    inside = frame[frame.index >= since]
    reference = frame[frame.index < since].iloc[-1:]
    frame = pd.concat([reference, inside])
    if len(frame) < 2:
        return None
    delta = frame["pnl"].diff()
    previous = frame["av"].shift(1)
    flow = (frame["av"] - previous) - delta
    capital = previous + 0.5 * flow
    returns = (delta / capital.where(capital > 0)).fillna(0.0).clip(lower=-1.0).iloc[1:]
    equity = pd.concat([pd.Series([1.0], index=[frame.index[0]]), (1.0 + returns).cumprod()])
    return {"returns": returns, "equity": equity}


def stage1_pass(stats: dict[str, float] | None, rules: dict | None = None) -> bool:
    """1. aşama: en az 6 aktif ay, kârlı ay oranı ≥ %44, zirveden düşüş ≤ %30, 12 ay getiri > 0 (eşikler kurallar.yaml)."""
    rules = rules or load_rules()
    return bool(stats and stats["active_months"] >= rules["asama1_min_aktif_ay"]
                and stats["profitable_month_ratio"] >= rules["asama1_min_karli_ay_orani"]
                and stats["max_drawdown"] <= rules["asama1_max_dusus"] and stats["return_12m"] > 0)


def hip3_dex_names(client: Any) -> list[str]:
    """HIP-3 dex adları (``perpDexs``; ilk öğe ana piyasa/null). Hesap değeri tabanı için toplamda kullanılır."""
    names = []
    for item in client.info({"type": "perpDexs"}, weight=2) or []:
        name = item.get("name") if isinstance(item, dict) else item
        if name:
            names.append(str(name))
    return names


def account_value_parts(client: Any, address: str, dexes: list[str]) -> dict[str, float]:
    """Bugünkü hesap değerinin parçaları: ana piyasa, HIP-3 dex toplamı ve spot USDC (``spotClearinghouseState``; birleşik hesapta bakiye
    burada durur: 0x69b0 ana + HIP-3 = 0 $, spot USDC 602.437 $). Ana piyasa/spot okunamazsa hata fırlar (satır veri hatası olur);
    bir dex okunamazsa o dex 0 sayılır."""
    ana = float(client.info({"type": "clearinghouseState", "user": address}, weight=2)["marginSummary"]["accountValue"])
    hip3 = 0.0
    for dex in dexes:
        try:
            hip3 += float(client.info({"type": "clearinghouseState", "user": address, "dex": dex}, weight=2)["marginSummary"]["accountValue"])
        except (KeyError, TypeError, ValueError, requests.RequestException):
            continue
    spot_state = client.info({"type": "spotClearinghouseState", "user": address}, weight=2) or {}
    spot = sum(float(b.get("total", 0) or 0) for b in spot_state.get("balances", []) if str(b.get("coin")) == "USDC")
    return {"ana": ana, "hip3": hip3, "spot_usdc": spot}


def total_account_value(client: Any, address: str, dexes: list[str]) -> float:
    """Bugünkü hesap değeri = ana piyasa + tüm HIP-3 dex + spot USDC (görev 27)."""
    return sum(account_value_parts(client, address, dexes).values())


def check_net_range(nets: dict, rules: dict) -> None:
    """Kopya net getirisi makul aralıkta olmalı (``saglik_net_min`` .. ``saglik_net_max``); değilse satır ``hata`` olur (ValueError)."""
    low, high = float(rules["saglik_net_min"]), float(rules["saglik_net_max"])
    for delay, value in nets.items():
        if value is not None and not (low <= value <= high):
            raise ValueError(f"net getiri makul aralık dışı: gecikme {delay} dk = {value:.4g}")


def account_floor_pass(total: float, rules: dict | None = None) -> bool:
    """Görev 27: bugünkü hesap değeri ``hesap_degeri_min_usd`` ve üstüyse geçer (eşik dahil)."""
    rules = rules or load_rules()
    return total >= float(rules["hesap_degeri_min_usd"])


def bhy(p_values: dict[str, float]) -> dict[str, float]:
    """Benjamini--Hochberg--Yekutieli adjusted q values."""
    keys = sorted(p_values, key=p_values.__getitem__)
    n = len(keys)
    if not n:
        return {}
    harmonic = sum(1 / i for i in range(1, n + 1))
    q, out = 1.0, {}
    for rank in range(n, 0, -1):
        key = keys[rank - 1]
        q = min(q, p_values[key] * n * harmonic / rank)
        out[key] = min(1.0, q)
    return out


def placebo_pvalue(actual: float, placebo: list[float]) -> float:
    """Frozen one-sided CT-Kapı p value (1,000 repetitions in the runner)."""
    return (1 + sum(value >= actual for value in placebo)) / (len(placebo) + 1)


def matched_btc_alpha(strategy: pd.Series, btc: pd.Series, exposure: pd.Series, days: int | None = None) -> dict[str, float]:
    """Maruziyet eşleşmiş kıyas (BTC ya da sepet) alfası, CT-Kapı adım 6; pencere ``alfa_pencere_gun`` (kurallar.yaml)."""
    days = int(days if days is not None else load_rules()["alfa_pencere_gun"])
    index = strategy.index.union(btc.index).sort_values()[-days:]
    return nw_alpha(strategy.reindex(index, fill_value=0.0),
                    btc.reindex(index, fill_value=0.0) * exposure.reindex(index, fill_value=0.0), periods=days)


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


_OPEN_LOOKUPS: dict[int, tuple[list, "_Opens"]] = {}


def next_candle_open(candles: list[dict], event_ms: int, delay_minutes: int) -> float | None:
    """Use the first candle opening at/after the requested delay; never its close.

    Mum listesi başına sıralı arama tablosu bir kez kurulur (eskiden her çağrıda yeniden sıralanıyordu: bir adreste
    ~60 sn). Aynı liste nesnesi + aynı uzunluk = aynı tablo.
    """
    if not candles:
        return None
    held = _OPEN_LOOKUPS.get(id(candles))
    if held is None or held[0] is not candles or held[1].count != len(candles):
        held = (candles, _Opens(candles))
        _OPEN_LOOKUPS[id(candles)] = held
    return held[1].at(event_ms + delay_minutes * 60_000)


def prev_candle_open(candles: list[dict], event_ms: int, delay_minutes: int) -> float | None:
    """Mutabakat alt/üst sınırı: hedef zamanda veya ondan ÖNCE açılan son mum (saatlik mumda en çok 1 sa erken)."""
    if not candles:
        return None
    held = _OPEN_LOOKUPS.get(id(candles))
    if held is None or held[0] is not candles or held[1].count != len(candles):
        held = (candles, _Opens(candles))
        _OPEN_LOOKUPS[id(candles)] = held
    return held[1].before(event_ms + delay_minutes * 60_000)


def delayed_copy(fills: list[dict], candles: dict[str, list[dict]], account_value: float, delay_minutes: int,
                 funding: list[dict] | None = None, *, rounding: str = "up", trace: list[dict] | None = None
                 ) -> tuple[pd.Series | None, int]:
    """Net daily virtual-copy PnL, using delayed candle opens and exact stated friction.

    ``rounding``: ``up`` (varsayılan, kapı) hedeften sonraki ilk mum açılışı; ``down`` hedeften önceki son mum
    (mutabakat için karşı sınır). ``trace``: verilirse her dolum/funding satırı (coin, brüt, maliyet, nominal) eklenir.
    """
    if account_value <= 0:
        return None, 0
    position: dict[str, float] = {}; missing = 0
    entry: dict[str, float] = {}
    rows: list[tuple[pd.Timestamp, float]] = []
    for fill in sorted(perp_fills(fills), key=lambda x: int(x.get("time", 0))):
        coin, size = str(fill.get("coin")), float(fill.get("sz", 0)) / account_value
        signed = -size if str(fill.get("side")) in {"A", "Sell", "sell"} else size
        lookup = next_candle_open if rounding == "up" else prev_candle_open
        price = float(fill.get("px", 0)) if delay_minutes == 0 else lookup(candles.get(coin, []), int(fill["time"]), delay_minutes)
        if price is None:
            missing += 1; continue
        before = position.get(coin, 0.0)
        close = min(abs(before), abs(signed)) if before and before * signed < 0 else 0.0
        pnl = close * (price - entry.get(coin, price)) * (1 if before > 0 else -1)
        after = before + signed
        if before == 0 or before * signed > 0:
            entry[coin] = (entry.get(coin, price) * abs(before) + price * abs(signed)) / abs(after)
        elif after == 0 or before * after < 0:
            entry[coin] = price
        position[coin] = after
        cost = abs(signed * price) * (TAKER + SLIPPAGE)
        rows.append((pd.to_datetime(fill["time"], unit="ms", utc=True), pnl - cost))
        if trace is not None:
            trace.append({"coin": coin, "time": int(fill["time"]), "gross": pnl, "cost": cost, "notional": abs(signed * price), "funding": 0.0})
    for item in funding or []:
        rows.append((pd.to_datetime(item["time"], unit="ms", utc=True), _funding_amount(item) / account_value))
        if trace is not None:
            delta = item.get("delta", {})
            trace.append({"coin": str(delta.get("coin", "?")) if isinstance(delta, dict) else "?", "time": int(item["time"]),
                          "gross": 0.0, "cost": 0.0, "notional": 0.0, "funding": _funding_amount(item) / account_value})
    if not rows:
        return None, missing
    frame = pd.DataFrame(rows, columns=["time", "pnl"]).set_index("time")
    return frame.pnl.resample("1D").sum(), missing


def candle_coverage(fills: list[dict], candles: dict[str, list[dict]]) -> float:
    """Notional-weighted share of fills whose coin has a candle at/after its time."""
    total = covered = 0.0
    for fill in perp_fills(fills):
        weight = abs(float(fill.get("px", 0)) * float(fill.get("sz", 0)))
        if not weight:
            continue
        total += weight
        if next_candle_open(candles.get(str(fill.get("coin")), []), int(fill["time"]), 0) is not None:
            covered += weight
    return covered / total if total else 0.0


class CandleCache:
    """One 1-hour `candleSnapshot` request per coin, shared by all addresses in a run."""
    def __init__(self, client: PublicClient, start_ms: int, end_ms: int):
        self.client, self.start_ms, self.end_ms, self.items = client, start_ms, end_ms, {}
        self.requests = 0  # bu koşuda gerçekten çekilen coin sayısı (önbellek isabeti sayılmaz)
        self._health: dict[str, dict[str, int]] = {}

    def get(self, coin: str) -> list[dict]:
        if coin not in self.items:
            self.requests += 1
            self.items[coin] = self.client.candles(coin, self.start_ms, self.end_ms, interval="1h")
        return self.items[coin]

    def for_fills(self, fills: list[dict]) -> dict[str, list[dict]]:
        return {coin: self.get(coin) for coin in {str(row.get("coin")) for row in perp_fills(fills)}}

    def saglik(self, coin: str) -> dict[str, int]:
        """Coinin mum akıl sağlığı sayıları (``mum_saglik``; A15). Coin başına bir kez hesaplanır, adresler paylaşır."""
        if coin not in self._health:
            rules = load_rules()
            checked = mum_kontrol(self.get(coin), float(rules["mum_sicrama_kat"]), int(rules["mum_medyan_pencere"]))
            counts = mum_ozet(checked)
            self._health[coin] = {"mum_sayisi": len(checked), "mum_bozuk": counts["bozuk"], "mum_sicrama": counts["sicrama"], "mum_bosluk": counts["bosluk"],
                                  "mum_hacimsiz": counts["hacimsiz"], "mum_gecerli": sum(r["gecerli"] for r in checked)}
        return self._health[coin]


def place_ms(templates: list[dict], start_ms: int, end_ms: int, seed: int = 0, notes: list[str] | None = None) -> list[tuple[dict, int]]:
    """Plasebo yerleştirmesi (görev 1 ve 10; milisaniye, vektörel): çakışma yasağı **coin başına**; farklı coinler aynı anda açık olabilir.

    Her işlem bir bütün olarak (ekleme/kısmi kapanış dizisiyle) taşınır; süre = açılıştan kapanışa (en az 1 sa). Bir coinin işlemleri rastgele
    sırayla, sıralı tekdüze boşluklarla birbirine değmeden yerleştirilir (ret örneklemesi yok). Süreleri toplamı pencereye sığmayan coin için
    işlem dizisi bütün olarak dairesel kaydırılır (sarma: pencere sonunu aşan işlem başa taşınır) ve ``notes``'a yazılır.
    Döner: [(şablon, yeni açılış ms)].
    """
    rng = np.random.default_rng(seed)
    length = float(end_ms - start_ms)
    by_coin: dict[str, list[int]] = {}
    for index, trade in enumerate(templates):
        by_coin.setdefault(str(trade["coin"]), []).append(index)
    placed: list[tuple[dict, int]] = []
    for coin in sorted(by_coin):
        indices = by_coin[coin]
        durations = np.maximum(1.0, np.array([templates[i]["holding_hours"] for i in indices], dtype=float)) * 3_600_000.0
        if durations.max() > length:
            raise ValueError("trade does not fit placebo window")
        if durations.sum() > length:
            if any("open_time" not in templates[i] for i in indices):
                raise ValueError("non-overlapping placebo placement unavailable")
            shift = float(rng.uniform(0, length))
            for i, duration in sorted(((i, d) for i, d in zip(indices, durations)), key=lambda x: templates[x[0]]["open_time"]):
                opened = start_ms + ((int(templates[i]["open_time"].value // 1_000_000) - start_ms) + shift) % length
                placed.append((templates[i], int(start_ms if opened + duration > end_ms else opened)))
            if notes is not None and f"{coin}: dairesel kaydırma" not in notes:
                notes.append(f"{coin}: dairesel kaydırma")
            continue
        order = rng.permutation(len(indices))
        gaps = np.sort(rng.uniform(0, length - durations.sum(), len(indices)))
        ordered = durations[order]
        starts = start_ms + gaps + (np.cumsum(ordered) - ordered)
        placed.extend((templates[indices[o]], int(s)) for o, s in zip(order.tolist(), starts.tolist()))
    return placed


def randomize_trades(trades: list[dict], start: pd.Timestamp, end: pd.Timestamp, seed: int = 0,
                     notes: list[str] | None = None) -> list[dict]:
    """``place_ms``'in Timestamp'li sarmalayıcısı (testler ve geriye dönük API): ``open_time``/``close_time`` yeni zamanlarla döner."""
    placed = place_ms(trades, int(start.value // 1_000_000), int(end.value // 1_000_000), seed, notes)
    result = []
    for trade, opened_ms in placed:
        duration = pd.Timedelta(hours=max(1.0, float(trade["holding_hours"])))
        opened = pd.Timestamp(opened_ms, unit="ms", tz="UTC")
        result.append({**trade, "open_time": opened, "close_time": opened + duration})
    return sorted(result, key=lambda x: x["open_time"])


def _trade_templates(fills: list[dict], account_value: float | None = None) -> list[dict]:
    """Kapanmış, açılışı bilinen işlemler → plasebo şablonları: işlemi oluşturan **tüm** dolum parçaları (ekleme/kısmi kapanış dizisi),
    işlem açılışına göreli zamanlarıyla. Plasebo bunları bir bütün olarak yeniden yerleştirir; gerçek kopyayla aynı defterden geçer."""
    templates = []
    for trip in closed_round_trips(perp_fills(fills)):
        if trip["open_time"] is None or trip["holding_hours"] is None or not trip["fills"]:
            continue
        origin = int(trip["open_time"].value // 1_000_000)
        templates.append({"coin": trip["coin"], "holding_hours": trip["holding_hours"],
                          "open_time": trip["open_time"], "close_time": trip["close_time"],
                          "fills": [(f["time"] - origin, f["side"], f["sz"], f["startPosition"], f["px"]) for f in trip["fills"]]})
    return templates


def expand_template(trade: dict, opened_ms: int | None = None) -> list[dict]:
    """Yerleştirilmiş şablon → ``copy_ledger`` dolumları (dolum zamanları = yeni açılış + göreli ofset)."""
    origin = opened_ms if opened_ms is not None else int(trade["open_time"].value // 1_000_000)
    coin = trade["coin"]
    return [{"time": origin + offset, "coin": coin, "side": side, "sz": size, "startPosition": before, "px": px}
            for offset, side, size, before, px in trade["fills"]]


class _Opens:
    """Bir coinin mum açılışları: ``at(t)`` = t'de veya sonra açılan ilk mumun açılışı (kapanışı asla)."""
    def __init__(self, candles: list[dict]):
        rows = sorted((int(x.get("t", x.get("time", 0))), float(x.get("o", x.get("open")))) for x in candles)
        self.times, self.opens = [t for t, _ in rows], [o for _, o in rows]
        self.count = len(candles)

    def at(self, ms: int) -> float | None:
        index = bisect_left(self.times, ms)
        return self.opens[index] if index < len(self.times) else None

    def before(self, ms: int) -> float | None:
        """ms'de veya önce açılan son mumun açılışı (mutabakat alt sınırı)."""
        index = bisect_right(self.times, ms)
        return self.opens[index - 1] if index else None


def placebo_scores(fills: list[dict], candles: dict[str, list[dict]], account_value: float,
                   start: pd.Timestamp, end: pd.Timestamp, repetitions: int | None = None, delay_minutes: int = 0,
                   notes: list[str] | None = None, rates: FundingRates | None = None, rules: dict | None = None,
                   place=None, return_actual: bool = False):
    """Plasebo skorları (görev 20): trader'ın kapanmış işlemleri (tüm ekleme/kısmi kapanış dizisiyle) rastgele başlangıçlara, coin başına
    çakışmasız yerleştirilir ve **gerçek kopyayla aynı** ``copy_ledger``'dan geçer: aynı tarz gecikmesi, mum zaman sınırı, maliyet, funding,
    pencere sonu fiyatlaması. ``return_actual``: şablonların özgün zamanlarıyla (kimlik yerleştirmesi) aynı defterden çıkan gerçek skor da döner.
    ``place``: yerleştirme işlevi (varsayılan ``randomize_trades``; testler kimlik yerleştirmesi verir).
    """
    rules = rules or load_rules()
    repetitions = int(repetitions if repetitions is not None else rules["plasebo_tekrar"])
    templates = _trade_templates(fills)
    if not templates:
        return ([], None) if return_actual else []
    market, funding_rates = Market(candles), rates or FundingRates([])
    start_ms, end_ms = int(start.value // 1_000_000), int(end.value // 1_000_000)
    def score(placed: list[tuple[dict, int]]) -> float:
        rows = [fill for trade, opened in placed for fill in expand_template(trade, opened)]
        out = copy_ledger(rows, market, account_value, delay_minutes, start_ms, end_ms, funding_rates, rules)
        return float(out["net"] or 0.0)

    def originals() -> list[tuple[dict, int]]:
        return [(trade, int(trade["open_time"].value // 1_000_000)) for trade in templates]

    def injected(seed: int, sink: list[str] | None) -> list[tuple[dict, int]]:
        return [(trade, int(trade["open_time"].value // 1_000_000)) for trade in place(templates, start, end, seed, sink)]

    actual = score(originals())
    scores = [score(place_ms(templates, start_ms, end_ms, seed, notes if seed == 0 else None) if place is None else
                    injected(seed, notes if seed == 0 else None)) for seed in range(repetitions)]
    return (scores, actual) if return_actual else scores


FUNDING_PAGE_SIZE = 500   # userFunding sayfa başına en çok bu kadar kayıt döndürür (API sınırı; eşik değil)


def funding_all(client: Any, address: str, start_ms: int, end_ms: int) -> list[dict]:
    """Tüm funding kayıtları: API sayfa başına en çok 500 döndürür; imleç son kayıttan ilerler (tek sayfa okumak oranları kırpıyordu)."""
    rows, cursor, seen = [], start_ms, set()
    while True:
        page = client.info({"type": "userFunding", "user": address, "startTime": cursor, "endTime": end_ms}, weight=20) or []
        fresh = [x for x in page if (x.get("time"), str(x.get("delta", {}).get("coin"))) not in seen]
        for item in fresh:
            seen.add((item.get("time"), str(item.get("delta", {}).get("coin"))))
        rows.extend(fresh)
        if len(page) < FUNDING_PAGE_SIZE or not fresh:
            return rows
        cursor = max(int(x["time"]) for x in page) + 1


def account_history(portfolio: list) -> pd.Series | None:
    """Portfolio ``allTime.accountValueHistory`` → zaman indeksli seri (kaldıraç hesabın o anki değerine bölünür)."""
    periods = {name: value for name, value in portfolio if isinstance(value, dict)} if portfolio else {}
    points = (periods.get("allTime") or {}).get("accountValueHistory", [])
    if not points:
        return None
    return pd.Series({pd.to_datetime(t, unit="ms", utc=True): float(v) for t, v in points}).sort_index()


def copy_window_metrics(fills: list[dict], funding: list[dict], account_value: float, cache: CandleCache,
                        now_ms: int, active_months: int, ledgers: dict | None = None,
                        rules: dict | None = None, history: pd.Series | None = None) -> tuple[dict[str, Any], dict[int, float | None]]:
    """Prepare documented steps 1--4 and all informational delay results for one trader.

    Kopya sonuçları ``defter.copy_ledger``'dan gelir (mum zaman sınırı, miras pozisyon, açık pozisyon fiyatlaması, kopyanın kendi
    funding'i); ``ledgers`` verilirse gecikme → tam defter sonucu içine konur.
    """
    rules = rules or load_rules()
    start_200 = now_ms - int(rules["mum_pencere_gun"]) * DAY_MS
    recent = [row for row in fills if int(row.get("time", 0)) >= start_200]
    candles = cache.for_fills(recent)
    metrics = calculate_metrics(fills, funding=funding, account_value=account_value, account_history=history,
                                martingale_max_ratio=float(rules["martingale_max_ratio"]),
                                martingale_min_additions=int(rules["martingale_min_additions"]),
                                martingale_min_adverse=float(rules["martingale_min_adverse"]))
    metrics["active_months"] = active_months
    for name in ("mum_sayisi", "mum_bozuk", "mum_sicrama", "mum_bosluk", "mum_hacimsiz", "mum_gecerli"):      # A15: adresin kullandığı coinlerin mum sağlığı (bilgi sütunu)
        metrics[name] = sum(cache.saglik(coin)[name] for coin in candles)
    metrics["candle_coverage"] = candle_coverage(recent, candles)
    metrics["complete_data"] = metrics["candle_coverage"] >= rules["mum_kapsami_min"]
    nets: dict[int, float | None] = {}
    market, rates, source = Market(candles, max_intervals=int(rules["mum_uzaklik_max_aralik"])), FundingRates(funding), perp_fills(recent)
    capital = history if history is not None and len(history) else account_value     # zamana eşlenmiş sermaye ölçeği (bugünkü değer geçmişe uygulanmaz)
    for delay in rules["rapor_gecikmeleri_dk"]:
        out = copy_ledger(source, market, capital, delay, start_200, now_ms, rates, rules)
        nets[delay] = out["net"]
        metrics[f"gecikme_{delay}dk_eksik_dolum"] = out["missing"]
        metrics[f"gecikme_{delay}dk_dolum"] = out["executed"]
        for name in ("acik_pozisyon_sayisi", "unrealized_end", "mark_missing", "acik_pozisyon_notional"):
            metrics[f"gecikme_{delay}dk_{name}"] = out.get(name)
        if delay > 0:          # sıfır gecikmede yürütme = kaynak fiyat: sütun tanımsız (tamamen boş sütun akıl sağlığı kapısını kırar)
            for name, value in delayed_execution_quality(source, market, delay, start_200, now_ms).items():
                metrics[f"gecikme_{delay}dk_{name}"] = value
        if ledgers is not None:
            ledgers[delay] = out
    return metrics, nets


# ---------------------------------------------------------------- CT-Kapı v1.1: tarz, katman, kıyas
def classify_style(median_holding_hours: float | None, rules: dict | None = None) -> str | None:
    """Medyan elde tutma süresine göre tarz: < 1 sa ``scalp``, 1–24 sa ``intraday``, ≥ 24 sa ``swing``."""
    if median_holding_hours is None or not np.isfinite(median_holding_hours):
        return None
    rules = rules or load_rules()
    if median_holding_hours < float(rules["tarz_scalp_alti_saat"]):
        return "scalp"
    return "swing" if median_holding_hours >= float(rules["tarz_swing_ustu_saat"]) else "intraday"


def delay_for_style(tarz: str | None, rules: dict | None = None, key: str = "kopya_gecikme_dk") -> int:
    """Tarza göre gecikme (dk). Scalp ve bilinmeyen tarz intraday gecikmesini kullanır (adım 3 zaten Kaldı)."""
    rules = rules or load_rules()
    return int(rules[key]["swing" if tarz == "swing" else "intraday"])


def short_trade_share(fills: list[dict], tarz: str | None, rules: dict | None = None) -> float | None:
    """Süresi biliniyor olan kapanmış işlemler arasında tarzın 'kısa' sınırından kısa olanların payı."""
    rules = rules or load_rules()
    limit = float(rules["kisa_islem_dk"]["swing" if tarz == "swing" else "intraday"]) / 60
    held = [t["holding_hours"] for t in closed_round_trips(perp_fills(fills)) if t["holding_hours"] is not None]
    return float(sum(h < limit for h in held) / len(held)) if held else None


def market_shares(fills: list[dict], symbols: set[str] | None = None) -> dict[str, float | None]:
    """İşlem hacminin varlık sınıfı payları (``pay_<sınıf>``) ve Binance'te karşılığı olan hacim payı."""
    volume: dict[str, float] = {}
    for fill in perp_fills(fills):
        volume[str(fill.get("coin"))] = volume.get(str(fill.get("coin")), 0.0) + abs(float(fill.get("px", 0)) * float(fill.get("sz", 0)))
    total = sum(volume.values())
    out: dict[str, float | None] = {f"pay_{name}": 0.0 for name in ("kripto", "hisse", "endeks", "emtia")}
    if symbols is not None:
        out["binance_payi"] = None         # liste var ama hacim 0: tanımlı boş (satır zaten metrik üretmiyor)
    if not total:
        return out
    for coin, value in volume.items():
        out[f"pay_{asset_class(coin)}"] = (out.get(f"pay_{asset_class(coin)}") or 0.0) + value / total
    if symbols is not None:                # liste alınamadıysa (HTTP 451 vb.) sütun hiç yazılmaz; sessiz boş sütun bırakılmaz
        out["binance_payi"] = sum(v for c, v in volume.items() if binance_availability(c, symbols) == "var") / total
    return out


def benchmark_kind(crypto_share: float, rules: dict | None = None) -> str:
    """Alfa kıyası: hacmin ≥ %50'si kripto ise BTC, değilse işlem yapılan varlıkların sepeti."""
    rules = rules or load_rules()
    return "BTC" if crypto_share >= float(rules["alfa_kripto_payi_esigi"]) else "sepet"


def daily_close_returns(candles: list[dict]) -> pd.Series:
    close = pd.Series({pd.to_datetime(x.get("t", x.get("time")), unit="ms", utc=True): float(x.get("c", x.get("o")))
                       for x in candles}).sort_index()
    return close.resample("1D").last().pct_change().fillna(0.0) if len(close) else pd.Series(dtype=float)


def basket_returns(candles: dict[str, list[dict]], coins: list[str]) -> pd.Series:
    """İşlem yapılan varlıkların eşit ağırlıklı al-tut sepeti: her gün mumu olan coinlerin getiri ortalaması."""
    series = [daily_close_returns(candles[c]) for c in coins if candles.get(c)]
    series = [x for x in series if len(x)]
    if not series:
        return pd.Series(dtype=float)
    return pd.concat(series, axis=1).mean(axis=1).fillna(0.0)


def katman(statuses: dict[str, str]) -> str:
    """kopyalanabilir = adım 1–7 Geçti; izleme_adayi = adım 1, 2, 3 Geçti; yok = diğer."""
    if all(statuses.get(f"adim{i}") == "Geçti" for i in range(1, 8)):
        return "kopyalanabilir"
    if all(statuses.get(f"adim{i}") == "Geçti" for i in (1, 2, 3)):
        return "izleme_adayi"
    return "yok"



def activity_metrics(fills: list[dict], tarz: str | None, now_ms: int, rules: dict | None = None) -> dict[str, Any]:
    """Aktiflik (adım 2'ye ek): son 90 günde kapanmış düz-düz döngü sayısı ve son işlemden bu yana gün.

    Döngü = pozisyonun sıfıra dönmesi/ters dönmesi (``closed_round_trips``), dolum değil. Son işlem = son perp dolumu.
    ``aktif``: döngü sayısı tarza göre eşiği (intraday 20, swing 5) ve son işlem ≤ 30 gün. Kâr şartı yok.
    """
    rules = rules or load_rules()
    day = 86_400_000
    window = int(rules["aktif_pencere_gun"]) * day
    perp = perp_fills(fills)
    cycles = sum(1 for t in closed_round_trips(perp)
                 if t["close_time"] is not None and int(t["close_time"].value // 1_000_000) >= now_ms - window)
    last = max((int(f.get("time", 0)) for f in perp), default=None)
    days = None if last is None else round((now_ms - last) / day, 1)
    need = int(rules["aktif_son90_dongu"]["swing" if tarz == "swing" else "intraday"])
    return {"son90_dongu": cycles, "son_islem_gun": days,
            "aktif": bool(cycles >= need and days is not None and days <= float(rules["aktif_son_islem_max_gun"]))}


def night_share(fills: list[dict], rules: dict | None = None) -> float | None:
    """Yalnız rapor: TSİ gece saatlerinde (varsayılan 01–09) açılan kapanmış işlemlerin payı. Kapı ölçütü değil."""
    rules = rules or load_rules()
    first, last = rules["gece_saatleri_tsi"]
    opened = [t["open_time"] for t in closed_round_trips(perp_fills(fills)) if t["open_time"] is not None]
    if not opened:
        return None
    return float(sum(first <= t.tz_convert("Europe/Istanbul").hour < last for t in opened) / len(opened))


def delay_test_days(recent: list[dict], now_ms: int, start_200: int) -> float | None:
    """Yalnız rapor: gecikme testinin kapsadığı gün (≈200; mum penceresi ve ilk dolum sınırlar)."""
    times = [int(f["time"]) for f in recent if f.get("time") is not None]
    return round((now_ms - max(start_200, min(times))) / 86_400_000, 1) if times else None


def fill_limit_reached(fills: list[dict], now_ms: int, start_ms: int, stats: dict | None, rules: dict | None = None) -> bool:
    """Dolum geçmişi sınırı (görev 18c): API en son ~``dolum_siniri`` dolumu verebilir. Bu kadar dolum dönmüş ve ilk dolum, hesabın
    (ve 365 günlük pencerenin) izin verdiğinden ``dolum_siniri_bosluk_gun`` günden fazla geç başlıyorsa eski işlemler kaybolmuş olabilir."""
    rules = rules or load_rules()
    if len(fills) < int(rules["dolum_siniri"]):
        return False
    first = min(int(f["time"]) for f in fills)
    available_days = min((now_ms - start_ms) / DAY_MS, float((stats or {}).get("account_age_days", (now_ms - start_ms) / DAY_MS)))
    return bool((now_ms - first) / DAY_MS < available_days - float(rules["dolum_siniri_bosluk_gun"]))


def evidence_status(history_days: int, trades: int, active_months: int, rules: dict | None = None) -> str:
    rules = rules or load_rules()
    return "Geçti" if (history_days >= rules["min_history_days"] and trades >= rules["min_closed_trades"]
                       and active_months >= rules["min_active_months"]) else "Yetersiz"


def gate_status(metrics: dict[str, Any], copy_net: float | None, placebo_p: float | None,
                alpha: dict[str, float] | None, rules: dict | None = None) -> dict[str, str]:
    """Classify documented CT-Kapı steps without silently converting missing data to failure.

    Adım 3 (v1.1): tarz (scalp → Kaldı), kısa işlem payı, kaldıraç ve ``copy_net`` — tarzın gecikmesindeki sanal
    kopya neti (intraday 30 dk, swing 120 dk), çağıran doğru gecikmeyi verir.
    """
    rules = rules or load_rules()
    out = {"adim1": "Geçti" if metrics.get("complete_data") else "Yetersiz"}
    out["adim2"] = evidence_status(int(metrics.get("history_days", 0)), int(metrics.get("closed_trades", 0)), int(metrics.get("active_months", 0)), rules)
    if out["adim2"] == "Geçti" and metrics.get("aktif") is False:
        out["adim2"] = "Yetersiz"  # aktiflik şartı (görev 11): asgari kanıtın parçası
    if out["adim1"] != "Geçti" or out["adim2"] != "Geçti":
        out.update({f"adim{i}": "Yetersiz" for i in range(3, 8)})
        return out
    def value(name: str, missing: float) -> float:
        """Eksik ya da hesaplanamayan (None/NaN) ölçüt şartı sağlamaz; TypeError'a (veri hatası) düşmez."""
        number = metrics.get(name)
        return missing if number is None or not np.isfinite(number) else float(number)

    tarz = metrics.get("tarz") or classify_style(metrics.get("median_holding_hours"), rules)
    short = metrics.get("kisa_islem_payi")
    failed_static = not (tarz in {"intraday", "swing"}
                         and (short is None or short <= float(rules["kisa_islem_payi_max"]))
                         and value("median_leverage", math.inf) <= float(rules["kapi_max_medyan_kaldirac"])
                         and value("max_leverage", math.inf) <= float(rules["kapi_max_kaldirac"]))
    if failed_static:
        out["adim3"] = "Kaldı"                    # tarz/kaldıraç kopya sonucundan bağımsız kesin başarısızlık
    elif metrics.get("kopya_eksik"):
        out["adim3"] = "Yetersiz"                 # eksik dolumlu kopya getirisi güvenilmez (görev 18a)
    else:
        out["adim3"] = "Geçti" if copy_net is not None and copy_net > 0 else "Kaldı"
    out["adim4"] = "Geçti" if (value("profitable_month_ratio", 0) >= rules["adim4_min_karli_ay_orani"]
                               and value("largest_trade_share", 1) < rules["max_largest_trade_share"]
                               and value("profit_factor_without_best", 0) > rules["min_profit_factor_without_best"]
                               and not metrics.get("martingale_signal")) else "Kaldı"
    out["adim5"] = "Geçti" if placebo_p is not None and placebo_p <= float(rules["plasebo_p_max"]) else "Kaldı"
    if alpha is None or not np.isfinite(alpha.get("alfa_yillik", np.nan)) or alpha.get("durum") == "yetersiz":
        out["adim6"] = "Yetersiz"          # artık varyans sıfıra yakın (A19): t anlamsız, alfa ne olursa olsun yetersiz
    elif alpha["alfa_yillik"] <= 0:
        out["adim6"] = "Kaldı"
    else:
        out["adim6"] = "Geçti" if alpha["nw_t"] >= rules["alfa_t_min"] else "Yetersiz"
    return out


class Progress:
    """Adres başına aşama süreleri ve istek sayaçları; ``print(..., flush=True)`` ile Actions günlüğünde canlı görünür."""

    def __init__(self, label: str, client: PublicClient, cache: CandleCache, log=lambda text: print(text, flush=True)):
        self.label, self.client, self.cache, self.log = label, client, cache, log
        self.begin = self.mark = time.perf_counter()
        self.snap = self._snapshot()
        self.stages: dict[str, float] = {}

    def _snapshot(self) -> tuple:
        limiter = getattr(self.client, "limiter", None)
        stats = getattr(self.client, "stats", {})
        return (self.cache.requests, stats.get("istek", 0), stats.get("429", 0), stats.get("5xx", 0), getattr(limiter, "waited", 0.0))

    def stage(self, name: str, detail: str = "") -> None:
        now = time.perf_counter()
        elapsed, self.mark = now - self.mark, now
        self.stages[name] = self.stages.get(name, 0.0) + elapsed
        self.log(f"  {self.label} {name:<9} {elapsed:6.1f} s  {detail}".rstrip())

    def done(self, outcome: str) -> None:
        coin, requests_, e429, e5xx, wait = (a - b for a, b in zip(self._snapshot(), self.snap))
        total = time.perf_counter() - self.begin
        self.log(f"{self.label} TOPLAM {total:.1f} s ({outcome}) | yeni mum isteği {coin} coin, toplam istek {requests_}, "
                 f"hız sınırı beklemesi {wait:.1f} s, 429: {e429}, 5xx: {e5xx} | "
                 + ", ".join(f"{k} {v:.1f}" for k, v in self.stages.items()))


EXTERNAL_DIR = Path(__file__).resolve().parents[1] / "arastirma" / "copytrade" / "bagimsiz_secim"
ADDRESS_PATTERN = re.compile(r"0x[0-9a-fA-F]{40}")


def external_candidates(directory: Path = EXTERNAL_DIR) -> list[str]:
    """Bağımsız seçim notlarında geçen tüm adresler (görev 16): lider tablosu süzgecinden bağımsız kapıya girer."""
    found: set[str] = set()
    for path in sorted(directory.glob("*")) if directory.is_dir() else []:
        if path.is_file():
            found.update(a.lower() for a in ADDRESS_PATTERN.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return sorted(found)


def build_universe(board: list[dict], external: list[str], client: PublicClient | None = None) -> list[dict]:
    """Kapı evreni: süzgeçten geçen lider tablosu satırları (``kaynak = leaderboard``) + dış adaylar (``kaynak = dis_aday``, süzgeç yok).

    Dış adayın hesap değeri önce lider tablosundan (süzgeçsiz), yoksa ``clearinghouseState``'ten alınır; hiçbiri yoksa 0 (gate satırı Yetersiz kalır)."""
    universe = {row["address"].lower(): {**row, "kaynak": "leaderboard"} for row in prefilter(board)}
    raw = {_address(row).lower(): row for row in board if _address(row)}
    for address in sorted({a.lower() for a in external}):
        if address in universe:
            universe[address]["kaynak"] = "dis_aday"
            continue
        value = float(raw[address].get("accountValue", raw[address].get("account_value", 0)) or 0) if address in raw else 0.0
        if not value and client is not None:
            try:
                state = client.info({"type": "clearinghouseState", "user": address}, weight=2)
                value = float(state["marginSummary"]["accountValue"])
            except (KeyError, TypeError, ValueError, requests.RequestException):
                value = 0.0
        universe[address] = {"address": address, "accountValue": value, "kaynak": "dis_aday"}
    return sorted(universe.values(), key=lambda row: row["address"])


def write_universe_snapshot(path: Path, board: list[dict], external: list[str], client: PublicClient | None = None) -> list[dict]:
    """Tek lider tablosundan üretilen kapı evrenini parçalara ortak anlık görüntü olarak yazar."""
    leaders = build_universe(board, external, client)
    path.write_text(json.dumps({"liderler": leaders}, ensure_ascii=False), encoding="utf-8")
    return leaders


def read_universe_snapshot(path: Path) -> list[dict]:
    """Plan işinin yazdığı evren anlık görüntüsünü, sırasını koruyarak yükler."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    leaders = payload.get("liderler")
    if not isinstance(leaders, list) or any(not isinstance(row, dict) or not row.get("address") for row in leaders):
        raise ValueError(f"evren anlık görüntüsü geçersiz: {path}")
    return leaders


def shard_universe(leaders: list[dict], index: int, count: int) -> list[dict]:
    """Sabit sıralı ortak evrenden çakışmasız bir parça seçer."""
    return leaders[index::count]


def evaluate_address(leader: dict, client: PublicClient, cache: CandleCache, now: datetime, start: int, start_200: int,
                     symbols: set[str] | None, rules: dict, yalniz_adim5: bool = False, log=None, dexes: list[str] | None = None,
                     gunluk: dict | None = None) -> dict[str, Any]:
    """Tek adres için 1. aşama + adım 1–6 (adım 7 ve katman birleştirmede). ``yalniz_adim5``: plaseboyu adım 3–4'e
    bakmadan hesaplar (hızlı koşu; satırın adım değerleri yine kurallara göre kalır). Her aşamanın süresi günlüğe yazılır."""
    address = leader["address"]
    row: dict[str, Any] = {"address": address, "account_value": leader["accountValue"], "kaynak": leader.get("kaynak", "leaderboard"),
                           "hesap": HESAP_SURUMU, "kod_hash": HESAP_KOD_HASH, "now_ms": int(now.timestamp() * 1000)}
    progress = Progress(address[:10] + "…" + address[-4:], client, cache, *([log] if log else []))
    outcome = "tamam"
    try:
        portfolio = client.portfolio(address)
        stats = stage1_stats(portfolio)
        row.update(stats or {})
        # İlk 11 bilgi sütunları (K-12.11; adım / eşik kullanmaz): aynı `portfolio` yanıtından, yeni istek yok. Tek hesap yeri: ilk11_alanlar.
        row.update(kapi_bilgi_sutunlari(portfolio, rules))
        row["asama1"] = "Geçti" if stage1_pass(stats, rules) else "Yetersiz"
        progress.stage("portfolio", f"1. aşama: {row['asama1']}")
        if row["asama1"] != "Geçti":
            outcome = "1. aşama geçmedi"
            return row
        if dexes is None:
            dexes = hip3_dex_names(client)
        parts = account_value_parts(client, address, dexes)
        total = sum(parts.values())
        row.update({"hesap_degeri_bugun": total, "hesap_ana": parts["ana"], "hesap_hip3": parts["hip3"], "hesap_spot_usdc": parts["spot_usdc"]})
        progress.stage("hesap", f"bugünkü hesap değeri {total:,.0f} $ (ana {parts['ana']:,.0f} + HIP-3 {parts['hip3']:,.0f} + spot USDC {parts['spot_usdc']:,.0f})")
        if not account_floor_pass(total, rules):
            row.update({"asama1": "Kaldı", "neden": "hesap değeri tabanı"})
            outcome = row["neden"]
            return row
        account, now_ms = float(leader["accountValue"]), row["now_ms"]
        fills = client.fills(address, start)
        row["sure_dolum_sayisi"] = len(fills)
        progress.stage("fills", f"{len(fills)} dolum")
        funding = funding_all(client, address, start, now_ms)
        progress.stage("funding", f"{len(funding)} kayıt")
        recent = [x for x in fills if int(x.get("time", 0)) >= start_200]
        # Mumlar: her coin için koşu boyunca tek istek (CandleCache); gecikme hesapları, plasebo ve sepet kıyası aynı mumları kullanır.
        before = cache.requests
        candles = cache.for_fills(recent)
        progress.stage("mumlar", f"{len(candles)} coin, {cache.requests - before} yeni istek, {len(candles) - (cache.requests - before)} önbellekten")
        ledgers: dict[int, dict] = {}
        history = account_history(portfolio)
        capital = history if history is not None and len(history) else account
        metrics, nets = copy_window_metrics(fills, funding, account, cache, now_ms, int(stats["active_months"]), ledgers, rules, history)
        check_net_range(nets, rules)
        metrics["calmar"] = stats.get("calmar")          # 1. aşama zincirinden (olcut'taki hesap değeri paydalı calmar ölüydü)
        metrics["history_days"] = max(int(metrics.get("history_days", 0)), int(stats["pnl_history_days"]))
        tarz = classify_style(metrics.get("median_holding_hours"), rules)
        metrics["tarz"], metrics["kisa_islem_payi"] = tarz, short_trade_share(fills, tarz, rules)
        metrics.update(activity_metrics(fills, tarz, now_ms, rules))
        metrics["gece_payi"], metrics["gecikme_gun"] = night_share(fills, rules), delay_test_days(recent, now_ms, start_200)
        delay = delay_for_style(tarz, rules)
        actual = nets.get(delay)
        # Seçilmiş tarzın gecikmesindeki bütünlük/fiyat kalitesi bilgi sütunlarını düz adıyla yayımla.
        # Bu atamalar yalnız rapor alanıdır; kapı fonksiyonuna giden ölçütleri değiştirmez.
        for name in ("acik_pozisyon_sayisi", "unrealized_end", "mark_missing", "acik_pozisyon_notional",
                     "yonlu_dolum_sayisi", "yonlu_dolum_iyi_orani", "yonlu_dolum_kotu_orani", "yonlu_dolum_ortalama_bp"):
            metrics[name] = metrics.get(f"gecikme_{delay}dk_{name}")
        for dead in ("liquid_coin_share", "setting_leverage"):    # ölü sütunlar (hep 0 / hep boş) kapı satırına yazılmaz (görev 18b)
            metrics.pop(dead, None)
        missing_fills, executed_fills = metrics.get(f"gecikme_{delay}dk_eksik_dolum", 0), metrics.get(f"gecikme_{delay}dk_dolum", 0)
        metrics["kopya_eksik"] = bool(missing_fills > 0)
        metrics["kopya_eksik_orani"] = missing_fills / (missing_fills + executed_fills) if missing_fills + executed_fills else 0.0
        metrics["dolum_siniri"] = fill_limit_reached(fills, now_ms, start, stats, rules)
        pre = gate_status(metrics, actual, None, None, rules)
        progress.stage("metrik", f"tarz {tarz}, gecikme {delay} dk, 5 gecikme hesabı")
        p_value, notes = None, []
        if actual is not None and (yalniz_adim5 or all(pre[f"adim{i}"] == "Geçti" for i in range(1, 5))):
            repetitions = int(rules["plasebo_tekrar"])
            try:
                # Gerçek skor ve plasebo skorları AYNI defterden çıkar (görev 20): şablonların özgün zamanlarıyla gerçek, rastgele
                # yerleştirmelerle plasebo. Pencere, tarz gecikmesi, funding ve maliyet ortak.
                scores, plasebo_actual = placebo_scores(
                    recent, candles, capital, pd.to_datetime(start_200, unit="ms", utc=True), pd.to_datetime(now_ms, unit="ms", utc=True),
                    repetitions, delay, notes, FundingRates(funding), rules, return_actual=True)
                if len(scores) == repetitions:
                    p_value = placebo_pvalue(plasebo_actual, scores)
                    row["plasebo_gercek_skor"] = plasebo_actual
                else:
                    row["plasebo_hata"] = "yerleştirilecek kapanmış işlem yok"
            except ValueError as exc:
                row["plasebo_hata"] = str(exc)[:80]
            progress.stage("plasebo", f"p={p_value} {row.get('plasebo_hata', '')}".rstrip())
        else:
            progress.stage("plasebo", "atlandı (adım 3–4 geçmedi)")
        if notes:
            row["plasebo_not"] = "; ".join(notes)[:200]
        shares = market_shares(fills, symbols)
        kind = benchmark_kind(shares["pay_kripto"] or 0.0, rules)
        # Alfa: kopya defteri (gecikmesiz), gün başına net getiri; maruziyet = gün içinde açık pozisyonlu saat oranı (gerçek zaman çizelgesi).
        own_ledger = copy_ledger(perp_fills(recent), Market(candles, max_intervals=int(rules["mum_uzaklik_max_aralik"])), capital, 0, start_200, now_ms, FundingRates(funding), rules, daily=True)
        own, exposure = own_ledger.get("daily"), own_ledger.get("exposure")
        bench = (daily_close_returns(cache.get("BTC")) if kind == "BTC"
                 else basket_returns(candles, sorted({str(f.get("coin")) for f in perp_fills(recent)})))
        alpha = matched_btc_alpha(own, bench, exposure) if own is not None and len(bench) else None
        statuses = gate_status(metrics, actual, p_value, alpha, rules)
        gunluk_kaydet(gunluk, address, statuses, own)
        progress.stage("alfa", f"kıyas {kind}, t={alpha['nw_t'] if alpha else None}")
        row.update(metrics)
        row.update(shares)
        row.update({"plasebo_p": p_value, "alfa_kiyas": kind, "kapi_gecikme_dk": delay,
                    **({"alfa_yillik": alpha["alfa_yillik"], "nw_t": alpha["nw_t"]} if alpha else {})})
        row.update({f"gecikme_{d}dk_net": value for d, value in nets.items()})
        if tarz == "swing" and (nets.get(delay_for_style(tarz, rules, "stres_gecikme_dk")) or 0) < 0:
            row["not"] = "gece riskli"
        row.update(statuses)
    except Exception as exc:  # noqa: BLE001 - tek adresin hatası parçayı öldürmesin (görev: adres başı hata yalıtımı)
        row.setdefault("asama1", "Yetersiz")  # 1. aşama sonucu hesaplandıysa korunur
        reason = type(exc).__name__ + ": " + str(exc)[:60]
        row.update({"sinif": "Yetersiz", "hata": reason, "neden": "veri hatası: " + reason})
        print(f"HATA {address}: {reason}", flush=True)
        outcome = row["neden"]
    finally:
        progress.done(outcome)
        # Süreler sonuc.csv'ye de yazılır (Actions günlüğüne bakmadan okunabilsin).
        row.update({f"sure_{name}_sn": round(value, 1) for name, value in progress.stages.items()})
        row["sure_toplam_sn"] = round(time.perf_counter() - progress.begin, 1)
        row["sure_yeni_mum_istegi"] = progress.cache.requests - progress.snap[0]
    return row


def missing_addresses(leaders: list[dict], reference: pd.DataFrame | None, rules: dict | None = None) -> list[dict]:
    """Aynı günün sonuc.csv'sinde olmayan, ``neden`` alanı "veri hatası" olan ya da hesap değeri tabanında kalıp bugünkü hesap değeri
    güncel ``hesap_degeri_min_usd`` eşiğini geçen adresler (``--eksikleri-tamamla``; taban eşiği düşürülünce eski Kaldı satırı yeniden bakılır)."""
    if reference is None or reference.empty:
        return leaders
    rules = rules or load_rules()
    bad = reference["neden"].fillna("").astype(str).str.startswith("veri hatası") if "neden" in reference else False
    if "neden" in reference and "hesap_degeri_bugun" in reference:
        value = pd.to_numeric(reference["hesap_degeri_bugun"], errors="coerce")
        bad = bad | (reference["neden"].fillna("").astype(str).eq("hesap değeri tabanı") & (value >= float(rules["hesap_degeri_min_usd"])))
    ok = set(reference.loc[~bad, "address"].astype(str)) if "neden" in reference else set(reference["address"].astype(str))
    return [row for row in leaders if str(row["address"]) not in ok]


def latest_day(paths: list[str]) -> str | None:
    """``copytrade/kapi/<YYYY-MM-DD>`` yollarından (ya da düz adlardan) en son tarih; yoksa ``None``. Eksik mod aynı günün/son günün sonucuna devam eder."""
    days = [m.group(1) for m in (re.search(r"(?:^|/)(\d{4}-\d{2}-\d{2})/?$", str(path).strip()) for path in paths) if m]
    return max(days) if days else None


def evren_addresses(path: Path) -> set[str]:
    """Ortak evren anlık görüntüsündeki adresler (küçük harf)."""
    return {str(row["address"]).lower() for row in read_universe_snapshot(path)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="CT-Kapı v1.1 public-data stage-1 runner")
    parser.add_argument("--tarih", help="çıktı gün klasörü (varsayılan: bugün UTC); plan işinin seçtiği gün parçalara aynen geçer")
    parser.add_argument("--root", type=Path, default=Path("copytrade"))
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--yalniz-adim5", action="store_true")
    parser.add_argument("--eksikleri-tamamla", action="store_true",
                        help="aynı günün sonuc.csv'sinde olmayan veya 'veri hatası' olan adresleri işle")
    parser.add_argument("--devam", action="store_true")
    parser.add_argument("--birlestir", type=Path)
    parser.add_argument("--beklenen-parca", type=int, help="birleştirme: beklenen parça sayısı (eksik parça → durum: eksik)")
    parser.add_argument("--mod", default="tam", help="birleştirme: tam | hizli | eksik")
    parser.add_argument("--adres", action="append", default=[], help="kapıya zorla eklenen adres (dis_aday); tekrarlanabilir")
    parser.add_argument("--evren-yaz", type=Path, help="yalnız ortak evren anlık görüntüsünü yazıp çık")
    parser.add_argument("--evren-dosyasi", type=Path, help="plan işinin ortak evren anlık görüntüsünü kullan")
    parser.add_argument("--binance-dosyasi", type=Path, help="plan işinin ortak Binance vadeli listesi")
    args = parser.parse_args(argv)
    if args.birlestir:
        merge_shards(args.birlestir, args.root, args.beklenen_parca, args.mod, evren_addresses(args.evren_dosyasi) if args.evren_dosyasi else None)
        return
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("shard index/count geçersiz")
    rules = load_rules()
    now, today = datetime.now(UTC), args.tarih or datetime.now(UTC).date().isoformat()
    out = args.root / "kapi" / today
    out.mkdir(parents=True, exist_ok=True)
    client = PublicClient(limiter=RateLimiter(1000))
    external = sorted(set(external_candidates()) | {a.lower() for a in args.adres})
    if args.evren_yaz:
        leaders = write_universe_snapshot(args.evren_yaz, client.leaderboard(), external, client)
        print(f"Evren anlık görüntüsü: {len(leaders)} adres → {args.evren_yaz}", flush=True)
        return
    leaders = read_universe_snapshot(args.evren_dosyasi) if args.evren_dosyasi else build_universe(client.leaderboard(), external, client)
    evren = len(leaders)
    (out / "evren.json").write_text(json.dumps({"evren": evren}), encoding="utf-8")
    (out / "bitti.json").unlink(missing_ok=True)      # parça bitişi yalnız bu koşunun sonunda yazılır; zaman aşımında yok = eksik
    previous_path = out / "sonuc.csv"
    if args.yalniz_adim5:
        previous = sorted((args.root / "kapi").glob("*/sonuc.csv"))
        eligible = set(pd.read_csv(previous[-1]).query("adim1 == 'Geçti' and adim2 == 'Geçti' and adim3 == 'Geçti' and adim4 == 'Geçti'").address) if previous else set()
        leaders = [row for row in leaders if row["address"] in eligible or row["kaynak"] == "dis_aday"]
    if args.eksikleri_tamamla:
        leaders = missing_addresses(leaders, pd.read_csv(previous_path, low_memory=False) if previous_path.exists() else None, rules)
    leaders = shard_universe(leaders, args.shard_index, args.shard_count)
    if args.binance_dosyasi:
        symbols, binance_note = read_binance_universe(args.binance_dosyasi)
        (out / "binance_vadeli.txt").write_bytes(args.binance_dosyasi.read_bytes())
    else:
        symbols, binance_note = write_binance_universe(out, now)
    start = int((now - timedelta(days=int(rules["fills_lookback_days"]))).timestamp() * 1000)
    start_200 = int((now - timedelta(days=int(rules["mum_pencere_gun"]))).timestamp() * 1000)
    cache = CandleCache(client, start_200, int(now.timestamp() * 1000))
    previous_rows = pd.read_csv(previous_path).to_dict("records") if args.devam and previous_path.exists() else []
    if previous_path.exists() and not args.devam:
        # Veri dalından getirilen eski sonuç yalnız referanstı (yukarıda okundu); parça çıktısı ona karışmasın.
        previous_path.unlink()
    done = {str(row["address"]) for row in previous_rows}
    rows = previous_rows
    print(f"Koşu: evren {evren}, bu parçada {len(leaders)} adres (parça {args.shard_index}/{args.shard_count})", flush=True)
    dexes = hip3_dex_names(client)       # hesap değeri tabanı için bir kez (görev 27)
    gunluk: dict[str, pd.Series] = {}
    if args.devam and (out / "gunluk.csv.gz").exists():        # kesilen koşu devam ederken önceki günlük getiriler korunur
        previous_daily = pd.read_csv(out / "gunluk.csv.gz", index_col=0, parse_dates=True)
        gunluk.update({column: previous_daily[column].dropna() for column in previous_daily})
    for number, leader in enumerate(leaders, 1):
        if leader["address"] in done:
            continue
        print(f"[{number}/{len(leaders)}] {leader['address']}", flush=True)
        rows.append(evaluate_address(leader, client, cache, now, start, start_200, symbols, rules, args.yalniz_adim5 and leader.get("kaynak") != "dis_aday", dexes=dexes, gunluk=gunluk))
        pd.DataFrame(rows).to_csv(out / "sonuc.csv", index=False)  # partial results survive a time limit
        if gunluk:
            pd.DataFrame(gunluk).to_csv(out / "gunluk.csv.gz", compression="gzip")
    pd.DataFrame(leaders).to_csv(out / "asama1.csv.gz", index=False, compression="gzip")
    passed = sum(r.get("asama1") == "Geçti" for r in rows)
    (out / "RAPOR.md").write_text(
        f"# CT-Kapı v1.1\n\n- Evren: {evren}\n- Bu parçada işlenen: {len(rows)}\n- 1. aşamayı geçen: {passed}\n"
        f"- Binance listesi: {binance_note}\n- Gecikme saat başına yuvarlandı (üst sınır).\n- Karar önerisi yok.\n",
        encoding="utf-8")
    (out / "bitti.json").write_text(json.dumps({"parca": args.shard_index, "sayi": args.shard_count, "islenen": len(rows)}), encoding="utf-8")


def _md(frame: pd.DataFrame) -> str:
    """Bağımlılıksız Markdown tablo (tabulate yok)."""
    cells = lambda v: f"{v:.3g}" if isinstance(v, float) else str(v)
    lines = ["| " + " | ".join(frame.columns) + " |", "|" + "---|" * len(frame.columns)]
    lines += ["| " + " | ".join(cells(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join(lines)


def family_mask(table: pd.DataFrame) -> pd.Series:
    """Plasebo/BHY test ailesi: adım 1, 2, 3 ve 4'ü Geçti olanlar."""
    cols = [f"adim{i}" for i in range(1, 5)]
    if not all(c in table for c in cols):
        return pd.Series(False, index=table.index)
    return (table[cols] == "Geçti").all(axis=1)


def _num(row: Any, name: str) -> float | None:
    value = row.get(name)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def fail_reason(row: Any, rules: dict) -> str:
    """Kaldı / Yetersiz bir satırda ilk düşen adımın kısa nedeni ("adım 3 Yetersiz: kopya eksik dolum"). Geçen satır için boş."""
    pct = lambda v: f"%{100 * v:.0f}"      # noqa: E731
    if row.get("asama1") != "Geçti":
        reasons = []
        if (v := _num(row, "active_months")) is not None and v < rules["asama1_min_aktif_ay"]:
            reasons.append(f"aktif ay {v:.0f} < {rules['asama1_min_aktif_ay']}")
        if (v := _num(row, "profitable_month_ratio")) is not None and v < rules["asama1_min_karli_ay_orani"]:
            reasons.append(f"kârlı ay {pct(v)} < {pct(rules['asama1_min_karli_ay_orani'])}")
        if (v := _num(row, "max_drawdown")) is not None and v > rules["asama1_max_dusus"]:
            reasons.append(f"düşüş {pct(v)} > {pct(rules['asama1_max_dusus'])}")
        if (v := _num(row, "return_12m")) is not None and v <= 0:
            reasons.append(f"12 ay getiri {pct(v)} ≤ 0")
        return f"1. aşama {row.get('asama1')}: " + ("; ".join(reasons) or "kâr eğrisi verisi yok/yetersiz")
    step = next((i for i in range(1, 8) if row.get(f"adim{i}") != "Geçti"), None)
    if step is None:
        return ""
    state, reasons = row.get(f"adim{step}"), []
    match step:
        case 1:
            reasons.append(f"mum kapsamı {pct(_num(row, 'candle_coverage') or 0)} < {pct(rules['mum_kapsami_min'])}")
        case 2:
            if (_num(row, "history_days") or 0) < rules["min_history_days"]:
                reasons.append(f"geçmiş {(_num(row, 'history_days') or 0):.0f} gün < {rules['min_history_days']}")
            if (_num(row, "closed_trades") or 0) < rules["min_closed_trades"]:
                reasons.append(f"kapanmış işlem {(_num(row, 'closed_trades') or 0):.0f} < {rules['min_closed_trades']}")
            if (_num(row, "active_months") or 0) < rules["min_active_months"]:
                reasons.append(f"aktif ay {(_num(row, 'active_months') or 0):.0f} < {rules['min_active_months']}")
            if row.get("aktif") is False or str(row.get("aktif")) == "False":
                reasons.append("aktiflik (son 90 gün döngü / son işlem) sağlanmadı")
        case 3:
            if row.get("tarz") not in ("intraday", "swing"):
                reasons.append(f"tarz {row.get('tarz')}")
            if (v := _num(row, "kisa_islem_payi")) is not None and v > rules["kisa_islem_payi_max"]:
                reasons.append(f"kısa işlem payı {pct(v)} > {pct(rules['kisa_islem_payi_max'])}")
            if (v := _num(row, "median_leverage")) is None or v > rules["kapi_max_medyan_kaldirac"]:
                reasons.append(f"medyan kaldıraç {v if v is None else round(v, 2)} > {rules['kapi_max_medyan_kaldirac']}")
            if (v := _num(row, "max_leverage")) is None or v > rules["kapi_max_kaldirac"]:
                reasons.append(f"en yüksek kaldıraç {v if v is None else round(v, 1)} > {rules['kapi_max_kaldirac']}")
            if not reasons and str(row.get("kopya_eksik")) == "True":
                reasons.append("kopya eksik dolum (mum yok)")
            if not reasons:
                delay = _num(row, "kapi_gecikme_dk")
                delay = int(delay) if delay is not None else None
                net = _num(row, f"gecikme_{delay}dk_net") if delay is not None else None
                reasons.append(f"kopya neti {delay} dk gecikmede {'yok' if net is None else f'{net:.3g}'} ≤ 0")
        case 4:
            if (v := _num(row, "profitable_month_ratio")) is not None and v < rules["adim4_min_karli_ay_orani"]:
                reasons.append(f"kârlı ay {pct(v)} < {pct(rules['adim4_min_karli_ay_orani'])}")
            if (v := _num(row, "largest_trade_share")) is None or v >= rules["max_largest_trade_share"]:
                reasons.append(f"en büyük işlem payı {'yok' if v is None else pct(v)} ≥ {pct(rules['max_largest_trade_share'])}")
            if (v := _num(row, "profit_factor_without_best")) is None or v <= rules["min_profit_factor_without_best"]:
                reasons.append(f"en iyisiz PF {'yok' if v is None else round(v, 2)} ≤ {rules['min_profit_factor_without_best']}")
            if str(row.get("martingale_signal")) == "True":
                reasons.append("martingale işareti")
        case 5:
            p = _num(row, "plasebo_p")
            reasons.append("plasebo p üretilemedi" + (f" ({row.get('plasebo_hata')})" if isinstance(row.get("plasebo_hata"), str) else "") if p is None
                           else f"plasebo p {p:.3g} > {rules['plasebo_p_max']}")
        case 6:
            alpha, t = _num(row, "alfa_yillik"), _num(row, "nw_t")
            reasons.append("alfa hesaplanamadı" if alpha is None else f"alfa yıllık {alpha:.3g} ≤ 0" if alpha <= 0 else f"alfa t {t:.2f} < {rules['alfa_t_min']}")
        case 7:
            q = _num(row, "bhy_q")
            reasons.append("BHY q hesaplanamadı (plasebo p yok)" if q is None else f"BHY q {q:.3g} > {rules['bhy_q_max']}")
    return f"adım {step} {state}: " + ("; ".join(reasons) or "ayrıntı yok")


def finalize(table: pd.DataFrame, rules: dict | None = None) -> pd.DataFrame:
    """Parçalar birleştikten sonra adım 7 (BHY, plaseboya ulaşan herkes), nihai sınıf, katman ve genç aday."""
    rules = rules or load_rules()
    table = table.copy()
    steps = [f"adim{i}" for i in range(1, 7)]
    for col in steps + ["plasebo_p", "nw_t", "asama1", "sinif"]:
        if col not in table:
            table[col] = np.nan
    # Çoklu test ailesi (görev 10): adım 1–4'ü geçen tüm adresler, m = aile büyüklüğü. Plasebo p'si üretilemeyen aile üyesi
    # düzeltmede p = 1 sayılır (m'yi küçültmez); adım 7'si Yetersiz kalır. Aile dışında hesaplanmış p (hızlı koşu) teste girmez.
    family = family_mask(table)
    has_p = table["plasebo_p"].notna()
    q = bhy({a: (float(p) if pd.notna(p) else 1.0) for a, p, f in zip(table["address"], table["plasebo_p"], family) if f})
    table["bhy_q"] = table["address"].map(q).where(has_p & family)
    all_pass = (table[steps] == "Geçti").all(axis=1)
    table["adim7"] = np.where(table["bhy_q"].notna(), np.where(table["bhy_q"] <= rules["bhy_q_max"], "Geçti", "Kaldı"), "Yetersiz")

    def klass(row) -> str:
        if row.get("asama1") == "Kaldı":      # hesap değeri tabanı (görev 27)
            return "Kaldı"
        if row.get("asama1") != "Geçti":
            return "Yetersiz"
        values = [row.get(f"adim{i}") for i in range(1, 8)]
        if "Kaldı" in values:
            return "Kaldı"
        return "Geçti" if all(v == "Geçti" for v in values) else "Yetersiz"

    table["sinif"] = table.apply(klass, axis=1)
    table.loc[~all_pass & (table["sinif"] == "Geçti"), "sinif"] = "Yetersiz"
    if "neden" not in table:
        table["neden"] = np.nan
    table["neden"] = table["neden"].astype(object)
    missing_reason = table["neden"].isna() | (table["neden"].astype(str).str.strip() == "")
    needs = missing_reason & (table["sinif"] != "Geçti")
    table.loc[needs, "neden"] = table[needs].apply(lambda row: fail_reason(row, rules), axis=1)
    table["katman"] = table.apply(lambda row: katman({f"adim{i}": row.get(f"adim{i}") for i in range(1, 8)}), axis=1)
    for col in ("history_days", "account_age_days"):
        if col not in table:
            table[col] = np.nan
    table["gecmis_gun"] = table[["history_days", "account_age_days"]].max(axis=1)
    minimum, young = float(rules["min_history_days"]), float(rules["genc_aday_gun"])
    table["genc_aday"] = (table["gecmis_gun"] >= minimum) & (table["gecmis_gun"] < young)
    return table


def funnel_report(table: pd.DataFrame, evren: int | None) -> str:
    """RAPOR.md gövdesi: işlenen / evren, huni tarza ve katmana göre ayrı."""
    total = len(table)
    family = family_mask(table)
    lines = [f"- Plasebo test ailesi **m = {int(family.sum())}** (adım 1–4'ü geçen adresler; BHY bu aile üzerinde, p'si olmayan üye p = 1 sayılır); "
             f"tekrar sayısı {int(load_rules()['plasebo_tekrar'])}",
             f"- İşlenen / evren: {total} / {evren if evren else '?'}"
             + (f" (%{100 * total / evren:.1f}; hedef ≥ %{100 * load_rules()['kapsam_hedefi']:.0f}: {'✓' if total / evren >= load_rules()['kapsam_hedefi'] else '✗'})" if evren else ""),
             f"- 1. aşama (kâr eğrisi) geçti: {(table.asama1 == 'Geçti').sum()}",
             f"- Veri hatası: {table.get('neden', pd.Series(dtype=str)).fillna('').astype(str).str.startswith('veri hatası').sum()}",
             "- Sınıf: " + ", ".join(f"{k} {v}" for k, v in table.sinif.value_counts().items())]
    tarz = table["tarz"].fillna("belirsiz") if "tarz" in table else pd.Series("belirsiz", index=table.index)
    rows = []
    for name in ["intraday", "swing", "scalp", "belirsiz"]:
        part = table[tarz == name]
        if part.empty:
            continue
        rows.append({"tarz": name, "adres": len(part), **{f"adım {i}": int((part.get(f"adim{i}") == "Geçti").sum()) for i in range(1, 8)},
                     "izleme_adayi": int((part.katman == "izleme_adayi").sum()),
                     "kopyalanabilir": int((part.katman == "kopyalanabilir").sum())})
    return ("\n".join(lines) + "\n\n## Huni — tarza göre (geçen sayısı)\n\n" + (_md(pd.DataFrame(rows)) if rows else "_Veri yok._")
            + "\n\n## Katman\n\n" + "\n".join(f"- {k}: {v}" for k, v in table.katman.value_counts().items()))


FREEZE_FILES = ("kurallar.yaml", "kapi.py", "olcut.py", "defter.py")   # koşuyu belirleyen kural ve hesap dosyaları (görev 23)


def freeze_summary(table: pd.DataFrame) -> dict[str, Any]:
    """Dondurma özeti: kural/hesap dosyalarının SHA-256'sı ve aday listesinin (katman ≠ yok) adres özeti. RAPOR'a yazılır; kurallar
    veya hesap koşudan sonra değişirse özet değişir, sonuç artık aynı kuralların ürünü sayılmaz."""
    base = Path(__file__).resolve().parent
    files = {name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in FREEZE_FILES}
    candidates = sorted(str(a).lower() for a in table.loc[table["katman"].isin(["kopyalanabilir", "izleme_adayi"]), "address"]) if "katman" in table else []
    return {"dosyalar": files, "aday_sayisi": len(candidates), "aday_ozeti": hashlib.sha256("\n".join(candidates).encode()).hexdigest()}


def freeze_report(table: pd.DataFrame) -> str:
    summary = freeze_summary(table)
    lines = ["## Dondurma (kurallar ve kod özeti)", ""] + [f"- `{name}` SHA-256: `{digest}`" for name, digest in summary["dosyalar"].items()]
    return "\n".join(lines + [f"- Aday listesi ({summary['aday_sayisi']} adres: kopyalanabilir + izleme_adayi) özeti: `{summary['aday_ozeti']}`"])


# Hesap sürümü: satırın hangi hesap koduyla üretildiğini gösterir. Veri dalındaki eski sonuç dosyasında bu sütun yoksa ya da farklıysa
# satır "eski_hesap"tır: yeni sonuca karışmaz, akıl sağlığı kapısına girmez, ayrı dosyaya yazılır (sonuc_eski_hesap.csv.gz).
HESAP_SURUMU = "v1.1-2026-10-27d"
HESAP_KOD_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

RATIO_COLUMNS = ("profitable_month_ratio", "max_drawdown", "largest_trade_share", "kisa_islem_payi", "gece_payi", "pay_kripto", "pay_hisse",
                 "pay_endeks", "pay_emtia", "binance_payi", "candle_coverage", "plasebo_p", "bhy_q", "kopya_eksik_orani",
                 "ilk11_dusus_30g", "ilk11_tutarli_30g", "kazanma_orani")
LEVERAGE_COLUMNS = ("median_leverage", "max_leverage")
EXPECTED_FILLED = ("closed_trades", "history_days", "median_holding_hours", "median_leverage", "max_leverage", "candle_coverage",
                   "profitable_month_ratio", "max_drawdown", "gecikme_30dk_net", "gecikme_120dk_net", "kisa_islem_payi", "pay_kripto", "tarz")


class SanityError(RuntimeError):
    """Akıl sağlığı kapısı tutmadı: sonuç yayımlanmaz, iş kırmızı olur."""


def sanity_check(table: pd.DataFrame, rules: dict | None = None) -> list[str]:
    """Çıktı akıl sağlığı kapısı (görev 18d; denetim bulgusu: testler yeşilken 1,5e12 düşüş gibi sayılar yayımlandı).

    Kurallar: oran ve düşüş sütunları 0–1; kaldıraç 0–``saglik_max_kaldirac``; metrik üreten satırlarda beklenen sütun tamamen boş değil, yeterli
    satırda (``saglik_min_satir_sabit_kontrolu``) sabit değil; adım 1–4'ü geçen her satırda ``plasebo_p`` dolu. Döner: ihlal listesi (boş = geçti)."""
    rules = rules or load_rules()
    problems: list[str] = []
    for name in RATIO_COLUMNS:
        if name in table:
            values = pd.to_numeric(table[name], errors="coerce").dropna()
            tolerance = float(rules["saglik_oran_toleransi"])
            bad = values[(values < -tolerance) | (values > 1 + tolerance)]
            if len(bad):
                problems.append(f"{name}: {len(bad)} satırda 0–1 dışı (min {values.min():.4g}, max {values.max():.4g})")
    for name in LEVERAGE_COLUMNS:
        if name in table:
            values = pd.to_numeric(table[name], errors="coerce").dropna()
            bad = values[(values < 0) | (values > float(rules["saglik_max_kaldirac"]))]
            if len(bad):
                problems.append(f"{name}: {len(bad)} satırda 0–{rules['saglik_max_kaldirac']} dışı (max {values.max():.4g})")
    if "asama1" not in table:
        return problems + ["asama1 sütunu yok"]
    metric_rows = table[(table["asama1"] == "Geçti") & ~table.get("neden", pd.Series("", index=table.index)).fillna("").astype(str).str.startswith("veri hatası")]
    if len(metric_rows):
        for name in EXPECTED_FILLED:
            if name not in metric_rows or metric_rows[name].isna().all():
                problems.append(f"{name}: metrik üreten {len(metric_rows)} satırda tamamen boş")
            elif len(metric_rows) >= int(rules["saglik_min_satir_sabit_kontrolu"]) and metric_rows[name].nunique() <= 1:
                problems.append(f"{name}: {len(metric_rows)} satırda sabit değer ({metric_rows[name].iloc[0]!r})")
    low, high = float(rules["saglik_net_min"]), float(rules["saglik_net_max"])
    for name in [c for c in table.columns if re.fullmatch(r"gecikme_\d+dk_net", c)]:
        values = pd.to_numeric(table[name], errors="coerce").dropna()
        bad = values[(values < low) | (values > high)]
        if len(bad):
            problems.append(f"{name}: {len(bad)} satırda net getiri {low:g}..{high:g} dışı (min {values.min():.4g}, max {values.max():.4g})")
    if "alfa_yillik" in table:
        values = pd.to_numeric(table["alfa_yillik"], errors="coerce").dropna()
        low_alpha, high_alpha = low * 365, high * 365
        bad = values[~np.isfinite(values) | (values < low_alpha) | (values > high_alpha)]
        if len(bad):
            problems.append(f"alfa_yillik: {len(bad)} satırda yıllık net getiri {low_alpha:g}..{high_alpha:g} dışı")
    if len(metric_rows):
        allowed = set(rules["saglik_bos_olabilir"])
        for name in table.columns:
            if name not in allowed and table[name].isna().all():
                problems.append(f"{name}: tabloda tamamen boş sütun (doldurulmalı ya da kaldırılmalı)")
    if "neden" in table and "sinif" in table:
        silent = table[(table["sinif"] != "Geçti") & table["neden"].fillna("").astype(str).str.strip().eq("")]
        if len(silent):
            problems.append(f"neden: Kaldı/Yetersiz {len(silent)} satırda neden boş")
    if "hata" in table and len(table):
        failed = int(table["hata"].notna().sum())
        limit = float(rules["saglik_max_hata_orani"])
        if failed / len(table) > limit:
            problems.append(f"hata: {failed}/{len(table)} adres hatalı (%{100 * failed / len(table):.1f} > %{100 * limit:.0f})")
    family = family_mask(table)
    if family.any():
        empty = int(table.loc[family, "plasebo_p"].isna().sum()) if "plasebo_p" in table else int(family.sum())
        if empty:
            problems.append(f"plasebo_p: adım 1–4'ü geçen {int(family.sum())} adresin {empty} tanesinde boş")
    return problems


def sanity_by_source(table: pd.DataFrame) -> dict[str, list[str]]:
    """Akıl sağlığı ihlallerini satır kaynağına göre (``satir_kaynagi``: bu koşu / önceki dosya) ayırır; ihlalli adreslerden ilk 5'i."""
    out: dict[str, list[str]] = {}
    if "satir_kaynagi" not in table:
        return out
    rules = load_rules()
    for source, part in table.groupby("satir_kaynagi"):
        found = sanity_check(part.reset_index(drop=True), rules)
        bad = []
        for name in (*RATIO_COLUMNS, *LEVERAGE_COLUMNS):
            if name in part:
                values = pd.to_numeric(part[name], errors="coerce")
                limit = 1.0 if name in RATIO_COLUMNS else float(rules["saglik_max_kaldirac"])
                bad += part.loc[(values < -float(rules["saglik_oran_toleransi"])) | (values > limit + float(rules["saglik_oran_toleransi"])), "address"].astype(str).tolist()
        out[str(source)] = found + ([f"örnek adresler: {sorted(set(bad))[:5]}"] if bad else [])
    return out


def run_status(finished: int, expected: int | None, processed: int, universe: int | None, mod: str, rules: dict) -> dict:
    """Koşu durumu (görev 24): beklenen parçalardan biri bitmediyse veya (hızlı dışı) kapsam hedefin altındaysa ``eksik``."""
    reasons = []
    if expected is not None and finished < expected:
        reasons.append(f"{expected} parçanın yalnız {finished} tanesi bitti (zaman aşımı / hata)")
    coverage = processed / universe if universe else None
    if mod != "hizli" and coverage is not None and coverage < float(rules["kapsam_hedefi"]):
        reasons.append(f"kapsam %{100 * coverage:.1f} < hedef %{100 * float(rules['kapsam_hedefi']):.0f}")
    return {"durum": "eksik" if reasons else "tamam", "parca_beklenen": expected, "parca_biten": finished,
            "islenen": processed, "evren": universe, "kapsam": round(coverage, 4) if coverage is not None else None, "neden": "; ".join(reasons)}


def mum_ozeti(table: pd.DataFrame) -> dict[str, float] | None:
    """Kapı tablosunun mum sağlığı toplamları (adres başına kullandığı coinlerin mumları toplanır) ve geçerli oran; sütun yoksa ``None``."""
    names = ("mum_sayisi", "mum_bozuk", "mum_sicrama", "mum_bosluk", "mum_hacimsiz", "mum_gecerli")
    if not set(names) <= set(table.columns) or not table["mum_sayisi"].notna().any():
        return None
    totals = {name: int(pd.to_numeric(table[name], errors="coerce").fillna(0).sum()) for name in names}
    return {**totals, "gecerli_orani": totals["mum_gecerli"] / totals["mum_sayisi"] if totals["mum_sayisi"] else 0.0}


def mum_rapor(ozet: dict[str, float] | None) -> str:
    """RAPOR.md akıl sağlığı bölümü (A15)."""
    if not ozet:
        return ""
    ratio = f"%{100 * ozet['gecerli_orani']:.1f}".replace(".", ",")
    return (f"## Mum sağlığı (A15)\n\nToplam {ozet['mum_sayisi']} mum (adres başına kullanılan coinlerin toplamı): bozuk {ozet['mum_bozuk']} · sıçrama {ozet['mum_sicrama']} · "
            f"boşluk {ozet['mum_bosluk']} · hacimsiz {ozet['mum_hacimsiz']} · geçerli oran {ratio}. Bilgi bölümüdür; kapı kararını değiştirmez.\n\n")
def gunluk_kaydet(gunluk: dict | None, address: str, statuses: dict, daily: pd.Series | None) -> None:
    """Adım 1 ve 2'yi geçen adresin günlük kopya net getirisini (gecikmesiz defter) toplar; seçim raporu (A14) oda yoğunlaşması ve puan tutarlılığı için okur."""
    if gunluk is not None and daily is not None and len(daily) and statuses.get("adim1") == "Geçti" and statuses.get("adim2") == "Geçti":
        gunluk[address] = daily


def merge_shards(shards: Path, root: Path, expected: int | None = None, mod: str = "tam", universe: set[str] | None = None) -> dict[str, dict]:
    """Merge partial artifacts even if some timeout jobs produced no CSV.

    Aynı günün mevcut ``sonuc.csv``'si (ör. veri dalından) önce okunur; parçalardaki satırlar onu geçersiz kılar
    (``--eksikleri-tamamla`` ve hızlı koşu böyle birleşir).
    ``universe``: ortak evren adres kümesi; verilirse kapsam = |sonuç ∩ evren| / |evren| ve evren dışı satırlar ``evren_disi`` ile işaretlenir
    (verilmezse eski ölçü: satır sayısı / evren sayısı; denetim B14).
    """
    groups: dict[str, list[pd.DataFrame]] = {}
    evren: dict[str, int] = {}
    statuses: dict[str, dict] = {}
    for path in sorted(shards.rglob("sonuc.csv")):
        groups.setdefault(path.parent.name, []).append(pd.read_csv(path))
    for path in shards.rglob("evren.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "evren" not in payload:
            continue  # ortak evren anlık görüntüsü ({"liderler": [...]}) sayı dosyası değildir
        evren[path.parent.name] = max(evren.get(path.parent.name, 0), int(payload["evren"]))
    for date, frames in groups.items():
        output = root / "kapi" / date
        output.mkdir(parents=True, exist_ok=True)
        existing = output / "sonuc.csv"
        legacy = pd.DataFrame()
        fresh = [frame.assign(satir_kaynagi="bu_kosu") for frame in frames]
        if existing.exists():
            # Önceki dosyadaki satırlar yalnız AYNI hesap sürümüyle üretildiyse (ör. aynı günün kesilen koşusu) kalır; v1.1 öncesi / farklı
            # sürüm satırları eski_hesap olarak ayrı tutulur: yeni sonuca ve akıl sağlığı kapısına girmez.
            previous = pd.read_csv(existing, low_memory=False)
            same = previous["hesap"].eq(HESAP_SURUMU) if "hesap" in previous else pd.Series(False, index=previous.index)
            legacy = previous[~same].assign(durum="eski_hesap")
            if same.any():       # boş çerçeve eski sütunları (ör. ölü sütunlar) yeni tabloya taşımasın
                fresh = [previous[same].assign(satir_kaynagi="onceki_dosya_ayni_hesap")] + fresh
        if not evren.get(date) and (output / "evren.json").exists():
            evren[date] = int(json.loads((output / "evren.json").read_text(encoding="utf-8"))["evren"])
        table = pd.concat(fresh, ignore_index=True).drop_duplicates("address", keep="last")
        table = finalize(table)
        covered = None
        if universe is not None:
            table["evren_disi"] = ~table["address"].astype(str).str.lower().isin(universe)
            covered = int((~table["evren_disi"]).sum())
        problems = sanity_check(table)
        if problems:
            raise SanityError(f"{date}: akıl sağlığı kapısı tutmadı, yayımlanmaz:\n- " + "\n- ".join(problems)
                              + f"\nKaynağa göre: {sanity_by_source(table)}\n(eski_hesap olarak ayrılan satır: {len(legacy)}, kapıya girmedi)")
        if len(legacy):
            legacy.to_csv(output / "sonuc_eski_hesap.csv.gz", index=False, compression="gzip")
        status = run_status(len(list(shards.rglob(f"{date}/bitti.json"))), expected, len(table) if covered is None else covered,
                            len(universe) if universe is not None else evren.get(date), mod, load_rules())
        if covered is not None:
            status.update({"islenen": int(len(table)), "kapsanan": covered, "evren_disi_satir": int(len(table)) - covered})
        mum = mum_ozeti(table)
        if mum:
            status["mum_ozeti"] = mum
        daily_files = [path for path in shards.rglob("gunluk.csv.gz") if path.parent.name == date]
        if daily_files or (output / "gunluk.csv.gz").exists():
            # Günlük kopya getirisi (A14): önceki dosya (veri dalı) + bu koşunun parçaları; yeniden hesaplanan adres öncekini geçersiz kılar.
            parts = ([pd.read_csv(output / "gunluk.csv.gz", index_col=0, parse_dates=True)] if (output / "gunluk.csv.gz").exists() else [])
            parts += [pd.read_csv(path, index_col=0, parse_dates=True) for path in sorted(daily_files)]
            combined = pd.concat(parts, axis=1)
            combined = combined.loc[:, ~combined.columns.duplicated(keep="last")].sort_index()
            combined.to_csv(output / "gunluk.csv.gz", compression="gzip")
        status["eski_hesap_satir"] = int(len(legacy))
        status["hesap"] = HESAP_SURUMU
        hashes = sorted(str(value) for value in table.get("kod_hash", pd.Series(dtype=str)).dropna().unique())
        status["kod_hashler"] = hashes
        status["kod_hash_farkli"] = len(hashes) > 1
        status["satir_kaynagi"] = table["satir_kaynagi"].value_counts().to_dict()
        status["kapi_sorunlari"] = []
        statuses[date] = status
        (output / "durum.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
        table.to_csv(output / "sonuc.csv", index=False)
        pd.DataFrame({"address": table.address}).to_csv(output / "asama1.csv.gz", index=False, compression="gzip")
        if evren.get(date):
            (output / "evren.json").write_text(json.dumps({"evren": evren[date]}), encoding="utf-8")
        cols = [c for c in ["address", "tarz", "katman", "genc_aday", "profitable_month_ratio", "max_drawdown", "return_12m", "closed_trades",
                            "median_holding_hours", "median_leverage", "kisa_islem_payi", "son90_dongu", "son_islem_gun", "gece_payi", "gecikme_gun", "gecikme_30dk_net", "gecikme_120dk_net",
                            "gecikme_480dk_net", "plasebo_p", "nw_t", "alfa_kiyas", "bhy_q", "adim3", "adim4", "adim5", "adim6", "adim7", "sinif"] if c in table]
        near = table[table.get("adim2") == "Geçti"].sort_values("nw_t", ascending=False)[cols].head(15)
        banner = (f"> **DURUM: EKSİK** — {status['neden']}. Bu sonuç eksik koşudur; karar için kullanılmaz.\n\n" if status["durum"] == "eksik"
                  else f"Durum: tamam (parça {status['parca_biten']}/{status['parca_beklenen']}).\n\n" if expected is not None else "")
        failed = int(table["hata"].notna().sum()) if "hata" in table else 0
        banner += f"Hatalı adres: {failed}/{len(table)} (hata sütunu; sınıf Yetersiz).\n\n"
        banner += mum_rapor(status.get("mum_ozeti"))
        (output / "RAPOR.md").write_text("# CT-Kapı v1.1\n\n" + banner + funnel_report(table, evren.get(date))
                                         + "\n\n## Kod özeti\n\n" + ("- Tek hash: `" + hashes[0] + "`" if len(hashes) == 1 else "- Farklı kod hash'leri: " + (", ".join("`" + h + "`" for h in hashes) if hashes else "yok"))
                                         + "\n\n" + freeze_report(table) + "\n\n## Adım 2'yi geçenler (alfa t'ye göre ilk 15)\n\n" + _md(near)
                                         + "\n\nGecikme saat başına yuvarlandı (üst sınır). Karar önerisi yok.\n", encoding="utf-8")
    return statuses


if __name__ == "__main__":
    main()
