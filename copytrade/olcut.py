"""Metrics derived from public fills and funding only (never leaderboard ROI)."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["time"] = pd.to_datetime(frame["time"], unit="ms", utc=True, errors="coerce")
    for col in ("closedPnl", "fee", "px", "sz", "startPosition"):
        if col in frame:
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    return frame.dropna(subset=["time"]).sort_values("time", kind="stable").reset_index(drop=True)


def _funding_amount(item: dict[str, Any]) -> float:
    """Accept both documented ``delta.usdc`` and flattened archive rows."""
    value = item.get("delta", item.get("usdc", 0))
    if isinstance(value, dict):
        value = value.get("usdc", 0)
    return float(value or 0)


from copytrade.coin_sinif import COMMODITIES, INDICES, asset_class  # noqa: E402,F401  (numpy gerektirmeyen tek kaynak; canlı motor da buradan alır)


def is_hip3(coin: str) -> bool:
    """HIP‑3 (builder dex, `dex:COIN`): `asset_class` kripto ya da spot değilse (motor `coin_sinifi` ile aynı ayrım)."""
    return asset_class(coin) not in ("kripto", "spot")


def perp_fills(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Spot fills have no position/closedPnl semantics; metrics use perpetual fills only."""
    return [f for f in fills if asset_class(f.get("coin", "")) != "spot"]


def closed_round_trips(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Identify a transaction when signed position returns to zero (or flips sign).

    PnL accumulates over every partial close of the transaction, not only the last fill. A position already open
    when the window starts has unknown opening time: its PnL counts, its holding time is ``None``.

    Tersine dönen dolum (ör. +10 pozisyonda 15 satış): ``closedPnl`` kapanan işleme yazılır; ücret **miktarla bölünerek** kapanan
    (10/15) ve açılan (5/15) işleme dağıtılır. Her işlem ``fills`` ile döner: işlemi oluşturan dolum parçaları (``time``, ``side``,
    ``sz`` = o işleme düşen miktar, ``startPosition`` = işlem içi göreli pozisyon, ``px``, ``tid``); dolum yeniden kurulumu bunları aynı sırayla
    yerleştirir.
    """
    data = _frame(fills)
    open_time: dict[str, pd.Timestamp | None] = {}
    pnl: defaultdict[str, float] = defaultdict(float)
    position: defaultdict[str, float] = defaultdict(float)
    relative: defaultdict[str, float] = defaultdict(float)
    parts: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []

    def part(row: dict[str, Any], coin: str, units: float, sign: float) -> dict[str, Any]:
        item = {"time": int(row["time"].value // 1_000_000), "coin": coin, "side": "A" if sign < 0 else "B", "sz": units,
                "startPosition": relative[coin], "px": float(row.get("px", 0)), "tid": row.get("tid", 0)}
        relative[coin] += sign * units
        return item

    for row in data.to_dict("records"):
        coin = str(row.get("coin", ""))
        before = float(row.get("startPosition", position[coin]))
        side = str(row.get("side", ""))
        size = float(row.get("sz", 0.0))
        sign = -1.0 if side in {"A", "Sell", "sell"} else 1.0
        after = before + sign * size
        if coin not in seen:
            seen.add(coin)
            if abs(before) > 1e-12:
                open_time[coin] = None  # opened before the window
                relative[coin] = before
        fee, closed = float(row.get("fee", 0)), float(row.get("closedPnl", 0))
        closes = abs(before) > 1e-12 and (abs(after) < 1e-12 or before * after < 0)
        if closes:
            closing = min(abs(before), size)
            opening = max(0.0, size - closing)
            share = closing / size if size else 1.0
            pnl[coin] += closed - fee * share
            parts[coin].append(part(row, coin, closing, sign))
            start = open_time.pop(coin, None)
            rows.append({"coin": coin, "open_time": start, "close_time": row["time"],
                         "holding_hours": (row["time"] - start).total_seconds() / 3600 if start is not None else None,
                         "net_pnl": pnl.pop(coin, 0.0), "fills": parts.pop(coin, [])})
            relative[coin] = 0.0
            if opening > 1e-12:           # tersine dönüş: kalan miktar yeni işlemi açar
                open_time[coin] = row["time"]
                pnl[coin] = -fee * (1.0 - share)
                parts[coin] = [part(row, coin, opening, sign)]
        else:
            pnl[coin] += closed - fee
            parts[coin].append(part(row, coin, size, sign))
            if abs(after) > 1e-12 and abs(before) < 1e-12:
                open_time[coin] = row["time"]
        position[coin] = after
    return rows


def kazanma_orani(rounds: list[dict[str, Any]]) -> float | None:
    """Kazanma oranı = ``net_pnl > 0`` olan kapanmış işlem sayısı / kapanmış işlem sayısı (oran, 0–1).

    ``rounds``: ``closed_round_trips`` çıktısı (ücret ``net_pnl``'e dahildir: ücret yüzünden sıfırın altına inen işlem kaybedendir;
    ``net_pnl == 0`` kazanan sayılmaz). Kapanmış işlem yoksa ``None`` (0 değil: ölçülemedi). Yalnız bilgi ölçüsüdür, kapı adımı kullanmaz.
    """
    if not rounds:
        return None
    return sum(1 for x in rounds if x["net_pnl"] > 0) / len(rounds)


def martingale_ratio(fills: list[dict[str, Any]], min_adverse: float | None = None) -> tuple[float, int]:
    """Share of same-direction additions made while the open position is under water by more than ``min_adverse``.

    Dolumlar **gerçek sırayla** (zaman, sonra tid) işlenir; ortalama giriş her dolumda güncellenir. Bir emir (``oid``) birden çok
    dolumla gelse de **tek ekleme** sayılır: ilk dolumunda sayılır, zararda olup olmadığı emrin ağırlıklı ortalama fiyatına göre
    ölçülür (merdiven girişi çok ekleme değildir). Ekleme zararda mı: (emir fiyatı / o anki ortalama giriş − 1) yön ile çarpılmış
    < −``min_adverse``. Returns (ratio, number of additions).
    """
    if min_adverse is None:
        from copytrade.kurallar import load_rules
        min_adverse = float(load_rules()["martingale_min_adverse"])
    data = _frame(fills)
    if data.empty:
        return 0.0, 0
    sort_keys = ["time"] + (["tid"] if "tid" in data else [])
    data = data.sort_values(sort_keys, kind="stable").reset_index(drop=True)
    order_price: dict[str, float] = {}
    if "oid" in data:
        grouped = data.assign(_n=data["px"] * data["sz"]).groupby("oid")
        order_price = {str(k): float(v) for k, v in (grouped["_n"].sum() / grouped["sz"].sum()).items()}
    position: defaultdict[str, float] = defaultdict(float)
    entry: dict[str, float] = {}
    counted: set[tuple[str, str]] = set()
    additions = losing = 0
    for row in data.to_dict("records"):
        coin = str(row.get("coin", ""))
        before = float(row.get("startPosition", position[coin]))
        sign = -1.0 if str(row.get("side", "")) in {"A", "Sell", "sell"} else 1.0
        size, px = float(row.get("sz", 0)), float(row.get("px", 0))
        signed = sign * size
        after = before + signed
        if abs(before) > 1e-12 and before * signed > 0:
            if coin in entry:  # opening fill seen: we know the average entry
                key = (coin, str(row.get("oid", row.get("tid", id(row)))))
                if key not in counted:
                    counted.add(key)
                    additions += 1
                    ref = order_price.get(str(row.get("oid")), px)
                    if (ref / entry[coin] - 1) * (1 if before > 0 else -1) < -min_adverse:
                        losing += 1
                entry[coin] = (entry[coin] * abs(before) + px * size) / abs(after)
        elif abs(before) < 1e-12 or before * after < 0:
            entry[coin] = px  # new position (or flip): fresh average
        if abs(after) < 1e-12:
            entry.pop(coin, None)
        position[coin] = after
    return (losing / additions if additions else 0.0), additions


def effective_leverage(fills: list[dict[str, Any]], account_value: Any) -> tuple[float | None, float | None]:
    """``effective_leverage_detail``'in (medyan, en yüksek) kısmı."""
    return effective_leverage_detail(fills, account_value)[:2]


def effective_leverage_detail(fills: list[dict[str, Any]], account_value: Any,
                              max_plausible: float | None = None) -> tuple[float | None, float | None, int]:
    """(zaman ağırlıklı medyan, en yüksek) gerçek kaldıraç = o anki toplam pozisyon değeri / **o anki** hesap değeri.

    ``account_value``: sabit sayı ya da zaman indeksli hesap değeri serisi (portfolio ``accountValueHistory``); seri verilirse her
    dolumdan sonraki kaldıraç, o dolumdan önceki en son hesap değerine bölünür (bugünkü değere değil). Medyan, pozisyon açıkken geçen
    süreyle ağırlıklıdır (bir sonraki doluma kadar); en yüksek tüm örneklerden. Hesap değeri bilinmeyen/≤ 0 örnek atlanır.

    ``max_plausible`` (varsayılan ``saglik_max_kaldirac``) üstündeki örnek fiziksel olarak olanaksızdır: hesap değeri geçmişi o ana göre
    bayattır (yatırımdan hemen sonraki dolum, önceki küçük noktaya bölünür; canlı koşuda 1,46e6x görüldü). Böyle örnek atılır (ağırlık ve
    en yüksek dışı) ve sayısı üçüncü değer olarak döner (``kaldirac_supheli_ornek``).
    """
    from copytrade.kurallar import load_rules
    ceiling = float(load_rules()["saglik_max_kaldirac"]) if max_plausible is None else float(max_plausible)
    data = _frame(fills)
    if data.empty:
        return None, None, 0
    series = account_value if isinstance(account_value, pd.Series) else None
    if series is None and (not account_value or account_value <= 0):
        return None, None, 0
    if series is not None:
        series = series[series > 0].sort_index()
        if series.empty:
            return None, None, 0
    data = data.sort_values("time", kind="stable")   # API sırası zamana göre garanti değil (sırasız dolum süreyi negatif yapıp çöküyordu)
    position: defaultdict[str, float] = defaultdict(float)
    price: dict[str, float] = {}
    samples: list[tuple[pd.Timestamp, float]] = []
    for row in data.to_dict("records"):
        coin = str(row.get("coin", ""))
        before = float(row.get("startPosition", position[coin]))
        signed = float(row.get("sz", 0)) * (-1 if str(row.get("side", "")) in {"A", "Sell", "sell"} else 1)
        position[coin], price[coin] = before + signed, float(row.get("px", 0))
        value = sum(abs(q) * price.get(c, 0) for c, q in position.items())
        if series is None:
            account = float(account_value)
        else:
            index = series.index.searchsorted(row["time"], side="right") - 1
            account = float(series.iloc[index]) if index >= 0 else float(series.iloc[0])
        samples.append((row["time"], value / account))
    times = pd.DatetimeIndex([t for t, _ in samples]).asi8
    values = np.array([v for _, v in samples], dtype=float)
    values = np.where(np.isfinite(values), values, 0.0)
    if len(values) == 0:
        return None, None, 0
    implausible = values > ceiling
    values = np.where(implausible, 0.0, values)
    # Konumsal hesap: aynı zaman damgalı dolumlar (indeks tekrarı) ağırlık dizisini kaydırmasın.
    durations = np.diff(times).astype(float) / 1e9
    durations = np.where(np.isfinite(durations) & (durations > 0), durations, 0.0)
    held, spans = values[:-1], durations
    mask = held > 0
    if not mask.any() or spans[mask].sum() <= 0:
        positive = values[values > 0]
        median = float(np.median(positive)) if positive.size else 0.0
    else:
        order = np.argsort(held[mask], kind="stable")
        sorted_values, weights = held[mask][order], spans[mask][order]
        cut = int(np.searchsorted(np.cumsum(weights), weights.sum() / 2.0))
        median = float(sorted_values[min(max(cut, 0), len(sorted_values) - 1)])
    return median, float(values.max()), int(implausible.sum())


def calculate_metrics(fills: list[dict[str, Any]], funding: list[dict[str, Any]] | None = None,
                      portfolio: list[dict[str, Any]] | None = None, liquid_coins: set[str] | None = None,
                      leverages: list[float] | None = None, account_value: float | None = None,
                      martingale_max_ratio: float | None = None, martingale_min_additions: int | None = None,
                      martingale_min_adverse: float | None = None, account_history: pd.Series | None = None) -> dict[str, Any]:
    """``account_value`` is the return denominator when no ``portfolio`` history is given (never 1 USD)."""
    from copytrade.kurallar import load_rules   # martingale eşikleri yalnız kurallar.yaml'da (görev 23)
    rules = load_rules()
    martingale_max_ratio = rules["martingale_max_ratio"] if martingale_max_ratio is None else martingale_max_ratio
    martingale_min_additions = rules["martingale_min_additions"] if martingale_min_additions is None else martingale_min_additions
    martingale_min_adverse = rules["martingale_min_adverse"] if martingale_min_adverse is None else martingale_min_adverse
    fills = perp_fills(fills)
    data = _frame(fills)
    funding_frame = pd.DataFrame({"time": pd.to_datetime([x.get("time") for x in funding or []], unit="ms", utc=True),
                                  "net_pnl": [_funding_amount(x) for x in funding or []]})
    if data.empty:
        return {"history_days": 0, "closed_trades": 0, "martingale_signal": False}
    data["net_pnl"] = data["closedPnl"] - data["fee"]
    if not funding_frame.empty:
        cash = pd.concat([data[["time", "net_pnl"]], funding_frame[["time", "net_pnl"]]]).sort_values("time")
    else:
        cash = data[["time", "net_pnl"]]
    daily = cash.set_index("time")["net_pnl"].resample("1D").sum()
    denominator = float(account_value) if account_value and account_value > 0 else 1.0
    if portfolio:
        values = [float(x.get("accountValue", x.get("value", 0))) for x in portfolio]
        positive = [x for x in values if x > 0]
        if positive:
            denominator = sum(positive) / len(positive)
    returns = daily / denominator
    downside = returns[returns < 0]
    sortino = (returns.mean() / math.sqrt((downside ** 2).mean()) * math.sqrt(365)
               if len(downside) and (downside ** 2).mean() > 0 else None)
    equity = denominator + daily.cumsum()
    drawdown = equity / equity.cummax() - 1
    mdd = abs(float(drawdown.min()))
    elapsed_years = (daily.index[-1] - daily.index[0]).total_seconds() / (365.25 * 86400)
    # Annualising a one-day record is meaningless and may overflow numerically.
    cagr = (float(equity.iloc[-1]) / denominator) ** (1 / elapsed_years) - 1 if denominator > 0 and equity.iloc[-1] > 0 and elapsed_years >= 1 / 365 else None
    rounds = closed_round_trips(fills)
    trade_pnl = [x["net_pnl"] for x in rounds]
    wins = [x for x in trade_pnl if x > 0]
    without_best = list(trade_pnl)
    if without_best:
        without_best.remove(max(without_best))   # yalnız BİR en iyi işlem çıkarılır (eşit kârlı diğerleri kalır)
    gross_loss = abs(sum(x for x in without_best if x < 0))
    volumes = (data["px"].abs() * data["sz"].abs()).groupby(data.get("coin", "")).sum()
    total_volume = float(volumes.sum())
    liquid_share = (float(volumes[volumes.index.isin(liquid_coins or set())].sum()) / total_volume if total_volume else 0.0)
    ratio, additions = martingale_ratio(fills, martingale_min_adverse)
    lev_median, lev_max, lev_dropped = effective_leverage_detail(fills, account_history if account_history is not None else denominator)
    history_days = int((data.time.iloc[-1] - data.time.iloc[0]).total_seconds() // 86400)
    return {
        "history_days": history_days,
        "closed_trades": len(rounds), "profitable_month_ratio": float((daily.resample("MS").sum() > 0).mean()),
        "sortino": sortino, "calmar": (cagr / mdd if cagr is not None and mdd else None),
        "ulcer_index": float(math.sqrt((drawdown.pow(2)).mean())),
        "largest_trade_share": (max(wins) / sum(wins) if sum(wins) else None),
        "profit_factor_without_best": (sum(x for x in without_best if x > 0) / gross_loss if gross_loss else None),
        # Bilgi sütunları: kapı eşiği/puanı bunları kullanmaz. Getiri, kapalı işlemlerin hesabın temsilî değerine oranıdır;
        # sıklık ise kapanmış tur sayısının gözlenen takvim günlerine bölümüdür (tek gün için payda 1).
        "en_iyi_islem_haric_getiri": sum(without_best) / denominator,
        "gunluk_islem_sikligi": len(rounds) / max(1, history_days + 1),
        "median_holding_hours": (float(pd.Series(held).median()) if (held := [x["holding_hours"] for x in rounds
                                  if x["holding_hours"] is not None]) else None),
        "kazanma_orani": kazanma_orani(rounds),   # bilgi (İlk 11 `kazanma`; K-12.11): kapı adımı kullanmaz
        "median_leverage": lev_median, "max_leverage": lev_max, "kaldirac_supheli_ornek": lev_dropped,
        "setting_leverage": max(leverages) if leverages else None, "liquid_coin_share": liquid_share,
        "martingale_ratio": ratio,
        # TÜM aynı yönlü eklemeler (her emir bir kez); zararda olanlar ayrı sütunda: oran = aleyhe / tüm (görev: sütun adı yanıltıyordu)
        "martingale_additions": additions, "martingale_aleyhe_ekleme": int(round(ratio * additions)),
        "martingale_signal": additions >= martingale_min_additions and ratio > martingale_max_ratio,
    }
