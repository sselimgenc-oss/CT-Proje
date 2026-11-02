"""Kopya defteri (docs/GOREV_TRADER_SECIMI.md 19–21): gerçek kopya ve plasebo AYNI fonksiyondan geçer.

Bir trader'ın dolumlarını, gecikmeli ve maliyetli olarak, kendi pozisyonumuz olarak yürütür:

* **Mum zaman sınırı:** yürütme fiyatı, hedef zamandan (dolum + gecikme) sonraki ilk saatlik mumun açılışıdır; o mum hedeften
  en çok 1 mum aralığı uzaktaysa (ya da yoksa) dolum "eksik"tir ve atlanır; sayısı döner (kapı satırı ``kopya_eksik`` işaretler).
* **Miras pozisyon:** pencereden önce açık olan pozisyonu azaltan/kapatan dolum, bizde olmayan bir pozisyonu kapatır; yeni ters
  pozisyon açmaz (``startPosition`` ile).
* **Açık pozisyonlar fiyatlanır:** gün sonu (UTC) ve pencere sonunda gerçekleşmemiş K/Z, mum açılışıyla işaretlenerek eğriye girer.
* **Funding kopyanın kendi pozisyonundan:** saatlik pozisyon × saatlik açılış fiyatı × funding oranı. Oran, trader'ın ``userFunding``
  satırlarındaki ``fundingRate`` değerinden okunur (trader'ın ``usdc`` ödemesi aktarılmaz); satırı olmayan saat için ±24 saatteki en yakın
  oran, o da yoksa coinin medyan oranı kullanılır.
* **Maliyet:** her dolumda taker + kayma (``kurallar.yaml``).

Tutarlar hesap değerine oranla (kesir) döner. Hiçbir eşik burada değildir; hepsi ``kurallar.yaml``'dadır.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Any

import numpy as np

from copytrade.kurallar import load_rules
from copytrade.mum_saglik import mum_kontrol

HOUR = 3_600_000
DAY = 86_400_000
_SELL = frozenset({"A", "Sell", "sell"})


def _by_time(fill: dict) -> int:
    return int(fill["time"])


def cost_rate(rules: dict | None = None) -> float:
    rules = rules or load_rules()
    return float(rules["maliyet_taker"]) + float(rules["maliyet_kayma"])


def v2_sinir(style: str, gecen_gun: float, getiri: float, rules: dict | None = None) -> str | None:
    """Ön kayıttaki V2 eşiği; ``getiri`` ayrılan teminata oranlıdır. (`golge.py`'den taşındı: `defter.copy_ledger`
    sabit tutar modunda da kullanır — tek yer, kural 7; `golge.py` burayı re-export eder.) Aşama günleri
    (0/7/14) kodda sabit değil, `kurallar.yaml` `golge_v2.swing` anahtarlarından (``gun_<gün>``) okunur."""
    rules = rules or load_rules()
    if style == "intraday":
        return "zarar_kes" if getiri <= float(rules["golge_v2"]["intraday"]["zarar_kes"]) else None
    swing = rules["golge_v2"]["swing"]
    days = sorted(int(key.split("_")[1]) for key in swing)
    stage_day = max(day for day in days if gecen_gun >= day)
    limits = swing[f"gun_{stage_day}"]
    if getiri <= float(limits["zarar_kes"]):
        return "zarar_kes"
    if limits["kar_al"] is not None and getiri >= float(limits["kar_al"]):
        return "kar_al"
    return None


def sabit_tutar_egrisi(rules: dict | None = None) -> Any:
    """Hesap değerinden sabit işlem tutarı üreten eğriyi döndürür."""
    rules = rules or load_rules()
    ref_kasa = float(rules["sabit_tutar_ref_kasa_usd"])
    ref_islem = float(rules["sabit_tutar_ref_islem_usd"])
    us = float(rules["sabit_tutar_us"])
    tavan = float(rules["sabit_tutar_tavan_kasa_usd"])

    def tutar(hesap_usd: float) -> float:
        e = max(1.0, min(float(hesap_usd), tavan))
        return ref_islem * (e / ref_kasa) ** us
    return tutar


def _fresh_open(sign: float, price: float, when: int, held: dict[str, float], entry: dict[str, float],
                market: "Market", realized_so_far: float, tutar_egrisi: Any, base_usd: float) -> float:
    """Yeni pozisyonu geçerli kopya hesabı değeriyle açar.

    Hesap: baz × (1 + gerçekleşen_simdiye_kadar + gerçekleşmemiş_simdi); gerçekleşmemiş
    bu dolumdan ÖNCEki ``held``/``entry`` ile hesaplanır (bu dolumun kendisi henüz işlenmedi). Funding bu tahmine girmez
    (saatlik, döngü sonrası ayrı hesaplanır) — küçük bir yaklaşıklık, belgelenmiştir."""
    if price <= 0:
        return 0.0
    unrealized = 0.0
    for coin, size in held.items():
        if size == 0.0:
            continue
        mark = market.mark(coin, when)
        if mark is not None:
            unrealized += size * (mark - entry[coin])
    equity_usd = max(0.0, base_usd * (1.0 + realized_so_far + unrealized))
    tutar_usd = float(tutar_egrisi(equity_usd))
    if tutar_usd <= 0:
        return 0.0
    return sign * (tutar_usd / price) / base_usd


def _sabit_tutar_signed(sign: float, signed: float, before_leader: float, own: float, price: float, when: int,
                        held: dict[str, float], entry: dict[str, float], market: "Market", realized_so_far: float,
                        tutar_egrisi: Any, base_usd: float) -> float:
    """Sabit tutar modunda dolumun kopyaya etkisini hesaplar.

    Mevcut kopya pozisyonuna oranla ekleme yapılır; azaltma/kapatma değişmez (defterin ortak
    kuralı)."""
    if before_leader * signed < 0:            # trader azaltıyor / kapatıyor / ters çeviriyor
        leader_close = min(abs(before_leader), abs(signed))
        close = abs(own) * leader_close / abs(before_leader) if own * before_leader > 0 else 0.0
        remainder = max(0.0, abs(signed) - leader_close)
        opened = _fresh_open(sign, price, when, held, entry, market, realized_so_far, tutar_egrisi, base_usd) if remainder > 0 else 0.0
        return sign * close + opened
    if own == 0.0:
        return _fresh_open(sign, price, when, held, entry, market, realized_so_far, tutar_egrisi, base_usd)
    f = abs(signed) / abs(before_leader) if before_leader else 0.0
    return sign * abs(own) * f


def _zorla_kapat(coin: str, hour: int, mark: float, neden: str, held: dict[str, float], entry: dict[str, float],
                 acilis: dict[str, int], son_kontrol: dict[str, int], rate: float, realized: float, costs: float,
                 flow: dict[int, float], timeline: dict[str, list[tuple[int, float, float]]],
                 olaylar: list[dict], suppressed: set[str]) -> tuple[float, float]:
    """E2/E3 risk katmanı: pozisyonu o saatin markında zorunlu kapatır (gerçek `held`/`entry` üzerinde — sentetik
    dolum YOK, `golge.py _kapat`'ın aksine). Trader'ın pozisyonu sıfırlanana dek coin bastırılır (``suppressed``)."""
    size = held.pop(coin)
    giris = entry.pop(coin)
    acilis.pop(coin, None)
    son_kontrol.pop(coin, None)
    pnl = size * (mark - giris)
    cost = abs(size) * mark * rate
    realized += pnl - cost
    costs += cost
    flow[hour // DAY] = flow.get(hour // DAY, 0.0) + (pnl - cost)
    timeline.setdefault(coin, []).append((hour, 0.0, mark))
    olaylar.append({"coin": coin, "neden": neden, "zaman_ms": hour})
    suppressed.add(coin)
    return realized, costs


def _risk_denetle(held: dict[str, float], entry: dict[str, float], acilis: dict[str, int], son_kontrol: dict[str, int],
                  market: "Market", until_ms: int, rules: dict, style: str | None, rate: float, realized: float,
                  costs: float, flow: dict[int, float], timeline: dict[str, list[tuple[int, float, float]]],
                  olaylar: list[dict], suppressed: set[str]) -> tuple[float, float]:
    """E2/E3 risk katmanı (sabit tutar): çapraz teminat tasfiyesi + (``style`` verilirse) aşamalı zarar_kes/kar_al —
    `golge.py _denetle_ve_kapat` ile AYNI mantık ve AYNI dondurulmuş eşikler (`golge_likidasyon_esigi`, `golge_v2`),
    ama gerçek (yol bağımlı) `held`/`entry` üzerinde, sentetik dolum enjekte etmeden (kural 7: hesap tek yerde) —
    proportional `scale`'in sabit tutarda karşılığı yok, o yüzden `golge.v2_cikislari`'nin ön-simülasyon/enjeksiyon
    deseni burada kullanılamaz."""
    if not held:
        return realized, costs
    esik = float(rules["golge_likidasyon_esigi"])
    first = min((son_kontrol[c] // HOUR + 1) * HOUR for c in held)
    for hour in range(first, until_ms + 1, HOUR):
        if not held:
            break
        active = [c for c in held if hour >= (son_kontrol[c] // HOUR + 1) * HOUR]
        if not active:
            continue
        marks = {c: market.mark(c, hour) for c in active}
        pnls = {c: held[c] * (marks[c] - entry[c]) for c in active if marks[c] is not None}
        # Markı olmayan coin bu saatte DENETLENDİ SAYILIR (son_kontrol ilerler) — ilerlemezse sonraki her dolum
        # aynı (markı hiç olmayan) saat aralığını baştan yeniden tarar (O(dolum × saat) tıkanma; gerçek veride görüldü).
        likidasyon_hepsi = bool(pnls) and sum(pnls.values()) <= esik
        for c in active:
            if likidasyon_hepsi and c in pnls:
                realized, costs = _zorla_kapat(c, hour, marks[c], "likidasyon", held, entry, acilis, son_kontrol,
                                               rate, realized, costs, flow, timeline, olaylar, suppressed)
                continue
            if c not in pnls:
                son_kontrol[c] = hour
                continue
            gecen_gun = (hour - acilis[c]) / DAY
            neden = "likidasyon" if pnls[c] <= esik else (v2_sinir(style, gecen_gun, pnls[c], rules) if style else None)
            if neden:
                realized, costs = _zorla_kapat(c, hour, marks[c], neden, held, entry, acilis, son_kontrol,
                                               rate, realized, costs, flow, timeline, olaylar, suppressed)
            else:
                son_kontrol[c] = hour
    return realized, costs


def delayed_execution_quality(fills: list[dict], market: "Market", delay_min: int,
                              start_ms: int, end_ms: int) -> dict[str, float | int | None]:
    """Gecikmeli dolumun kaynak doluma göre yön-duyarlı fiyat farkı.

    Pozitif ortalama bp kopyacı için daha kötü, negatif değer daha iyi fiyattır.
    Eşit fiyatlar iki yüzdeye de girmez. Bu yalnızca rapor bilgisidir; kapı
    değerlendirmesinde kullanılmaz.
    """
    empty: dict[str, float | int | None] = {"yonlu_dolum_sayisi": 0,
                                             "yonlu_dolum_iyi_orani": None,
                                             "yonlu_dolum_kotu_orani": None,
                                             "yonlu_dolum_ortalama_bp": None}
    if delay_min <= 0:
        return empty
    differences: list[float] = []
    for fill in fills:
        source = float(fill.get("px", 0) or 0)
        if not np.isfinite(source) or source <= 0:
            continue
        found = market.execution(str(fill["coin"]), int(fill["time"]) + delay_min * 60_000)
        if found is None:
            continue
        when, execution = found
        if when < start_ms or when > end_ms or not np.isfinite(execution) or execution <= 0:
            continue
        # Alışta yükselen, satışta düşen fiyat kopyacı için kötüdür.
        direction = -1.0 if fill.get("side") in _SELL else 1.0
        differences.append(((execution / source) - 1.0) * direction * 10_000)
    if not differences:
        return empty
    return {"yonlu_dolum_sayisi": len(differences),
            "yonlu_dolum_iyi_orani": sum(value < 0 for value in differences) / len(differences),
            "yonlu_dolum_kotu_orani": sum(value > 0 for value in differences) / len(differences),
            "yonlu_dolum_ortalama_bp": float(np.mean(differences))}


class Market:
    """Coin başına saatlik mum açılış/kapanış dizileri; yürütme ve işaretleme fiyatları (bisect: dolum başına mikrosaniye)."""

    def __init__(self, candles: dict[str, list[dict]], interval_ms: int = HOUR, max_intervals: int | None = None):
        # Yürütme mumu hedeften en çok ``mum_uzaklik_max_aralik`` (kurallar.yaml; kullanıcı kararı: 1) mum aralığı uzakta olabilir.
        limit = max_intervals if max_intervals is not None else int(load_rules()["mum_uzaklik_max_aralik"])
        self.interval, self.max_distance = interval_ms, interval_ms * limit
        self.mark_max_age = int(load_rules()["isaret_yas_max_dk"]) * 60_000
        self._raw, self._lists, self._cum, self._bad = candles, {}, {}, {}

    def lists(self, coin: str) -> tuple[list[int], list[float], list[float]]:
        if coin not in self._lists:
            rows = sorted((int(c.get("t", c.get("time", 0))), float(c.get("o", c.get("open"))),
                           float(c.get("c", c.get("close", c.get("o", c.get("open")))))) for c in self._raw.get(coin, []))
            self._lists[coin] = ([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows])
        return self._lists[coin]

    def arrays(self, coin: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        times, opens, closes = self.lists(coin)
        return np.array(times, dtype=np.int64), np.array(opens), np.array(closes)

    def execution(self, coin: str, target_ms: int) -> tuple[int, float] | None:
        """Hedeften sonraki ilk mum (zaman, açılış); en çok 1 mum aralığı uzaktaysa ya da yoksa ``None`` (eksik dolum)."""
        times, opens, _ = self.lists(coin)
        index = bisect_left(times, target_ms)
        if index >= len(times) or times[index] - target_ms > self.max_distance:
            return None
        return times[index], opens[index]

    def mark(self, coin: str, at_ms: int) -> float | None:
        """``at_ms``'de veya önce açılan son mumun açılışı (gün sonu / pencere sonu işaretlemesi)."""
        return (self.mark_at(coin, at_ms) or (None, None))[1]

    def mark_at(self, coin: str, at_ms: int) -> tuple[int, float] | None:
        """``mark`` ile aynı, mumun zamanı da döner (işaret yaşı için). Mum ``isaret_yas_max_dk`` (kurallar.yaml) dakikadan eskiyse işaret
        yok sayılır (``None``): bayat fiyatla açık pozisyon işaretlenmez, çağıran ``mark_missing`` sayar (E4)."""
        times, opens, _ = self.lists(coin)
        index = bisect_right(times, at_ms) - 1
        bad = self._bad_times(coin)
        while index >= 0 and times[index] in bad:           # bozuk / sıçrama / boşluk / hacimsiz mumla işaretlenmez (A15)
            index -= 1
        if index < 0 or at_ms - times[index] > self.mark_max_age:
            return None
        return times[index], opens[index]

    def _bad_times(self, coin: str) -> set[int]:
        """``mum_saglik`` ile geçersiz sayılan mum zamanları. Tam OHLC taşımayan mumlar (canlı yürütme/işaret mumları yalnız t, o) kontrol edilmez."""
        if coin not in self._bad:
            rows = self._raw.get(coin, [])
            if rows and all(isinstance(c, dict) and "h" in c and "l" in c and "c" in c for c in rows):
                rules = load_rules()
                checked = mum_kontrol(list(rows), float(rules["mum_sicrama_kat"]), int(rules["mum_medyan_pencere"]))
                self._bad[coin] = {int(r["t"]) for r in checked if not r["gecerli"] and r["t"] is not None}
            else:
                self._bad[coin] = set()
        return self._bad[coin]

    def funding_cum(self, coin: str, rates: FundingRates) -> tuple[list[int], list[float]]:
        """Saat başına (açılış fiyatı × funding oranı) kümülatif toplamı: bir pozisyonun funding'i = −adet × (cum[j] − cum[i]).

        Yalnız tam saatlik (``t % interval == 0``) mumlar funding ızgarasına girer: çağıran (``kopya_v2``) tasfiye
        denetimi için 1 dk'lık işaret mumunu saatlik mumlarla aynı ``Market``'e karıştırabilir; o dakika mumu bir
        saat gibi sayılırsa funding o pencerede fazladan bir kez (ya da eksik) sayılır (E2, Sol denetimi)."""
        key = (coin, id(rates))
        if key not in self._cum:
            times, opens, _ = self.arrays(coin)
            if len(times):
                hourly = times % self.interval == 0
                times, opens = times[hourly], opens[hourly]
            per_hour = opens * rates.array(coin, times) if len(times) else np.zeros(0)
            self._cum[key] = (times.tolist(), np.concatenate([[0.0], np.cumsum(per_hour)]).tolist())
        return self._cum[key]


class FundingRates:
    """Trader'ın funding satırlarından coin başına saatlik oran tablosu (kopyanın funding'i bu orandan hesaplanır)."""

    def __init__(self, rows: list[dict] | None = None):
        self.by_coin: dict[str, dict[int, float]] = {}
        folded: list[tuple[str, int, float]] = []
        for row in rows or []:
            delta = row.get("delta", row)
            if not isinstance(delta, dict) or delta.get("fundingRate") is None or delta.get("coin") is None:
                continue
            hour = int(row["time"]) // HOUR * HOUR
            if delta.get("nSamples") is not None:
                # Eski kayıtlar günde tek satıra katlanır (zaman = günün 00:00 UTC'si, ``usdc`` günün toplamı, ``nSamples`` toplanan saat).
                # ``fundingRate`` toplam DEĞİL, saatlik ölçekte ortalamadır (gerçek veriyle doğrulandı: günün saatlik min–max aralığında,
                # nSamples=24'te saatlik ortalamaya eşit, medyan oran/günlük toplam = 1/24) → ``nSamples``'a bölünmez; günün 24 saatine yayılır.
                folded.append((str(delta["coin"]), hour, float(delta["fundingRate"])))
                continue
            self.by_coin.setdefault(str(delta["coin"]), {})[hour] = float(delta["fundingRate"])
        for coin, day_start, rate in folded:
            table = self.by_coin.setdefault(coin, {})
            for hour in range(day_start, day_start + 24 * HOUR, HOUR):
                table.setdefault(hour, rate)       # gerçek saatlik satır varsa o kalır
        self._cache: dict[str, tuple[np.ndarray, np.ndarray, float]] = {}

    def _table(self, coin: str) -> tuple[np.ndarray, np.ndarray, float]:
        if coin not in self._cache:
            items = sorted(self.by_coin.get(coin, {}).items())
            times = np.array([t for t, _ in items], dtype=np.int64)
            rates = np.array([r for _, r in items])
            self._cache[coin] = (times, rates, float(np.median(rates)) if len(rates) else 0.0)
        return self._cache[coin]

    def array(self, coin: str, hours: np.ndarray, max_gap_ms: int = 24 * HOUR) -> np.ndarray:
        """Verilen saatler için oran: tam saat; yoksa ±24 saatteki en yakın; yoksa coinin medyanı."""
        times, rates, median = self._table(coin)
        if not len(times):
            return np.zeros(len(hours))
        right = np.clip(np.searchsorted(times, hours, side="left"), 0, len(times) - 1)
        left = np.clip(right - 1, 0, len(times) - 1)
        near_right, near_left = np.abs(times[right] - hours), np.abs(times[left] - hours)
        pick = np.where(near_right <= near_left, right, left)
        distance = np.minimum(near_right, near_left)
        return np.where(distance <= max_gap_ms, rates[pick], median)


def capital_scale(account: Any):
    """Kopya sermayesi 1 birimdir; trader'ın dolumu ``1 / hesap değeri`` ile ölçeklenir (kopyalayan, trader'ın hesabına oranla aynı
    maruziyeti taşır). ``account``: sabit sayı ya da zaman indeksli hesap değeri serisi; seri verilirse dolumun anındaki (o ana kadarki
    son) değer kullanılır, ilk noktadan önce ilk değer. Bugünkü değer geçmişe uygulanmaz (çekilmiş hesapta getiri patlamasın).
    Geçerli değer yoksa ``None``."""
    import pandas as pd
    if isinstance(account, pd.Series):
        series = account[account > 0].sort_index()
        if series.empty:
            return None
        times = np.array([int(t.value // 1_000_000) for t in series.index], dtype=np.int64)
        inverse = 1.0 / series.to_numpy(dtype=float)

        def scale(moment: int) -> float:
            index = int(np.searchsorted(times, moment, side="right")) - 1
            return float(inverse[max(index, 0)])
        return scale
    if account is None or float(account) <= 0:
        return None
    constant = 1.0 / float(account)
    return lambda moment: constant


def copy_ledger(fills: list[dict], market: Market, account: Any, delay_min: int, start_ms: int, end_ms: int,
                rates: FundingRates | None = None, rules: dict | None = None, daily: bool = False,
                tutar_egrisi: Any = None, base_usd: float = 1000.0, style: str | None = None) -> dict[str, Any]:
    """Tek kopya defteri. ``fills``: kaynak dolumlar (coin, side A/B, sz, startPosition, time, px), zamana göre sıralı olmak zorunda değil.

    Döner: ``net`` (gerçekleşen − maliyet + funding + pencere sonu gerçekleşmemiş K/Z; hesap değerine oranla), ``missing`` (eksik dolum),
    ``executed``, ``costs``, ``funding``, ``realized``, ``unrealized_end``; ``daily=True`` ise ``daily`` (UTC gün → net, açık pozisyon
    fiyatlaması dahil), ``exposure`` (gün → açık pozisyonlu saat oranı) ve ``max_drawdown`` (kopya eğrisinin zirveden düşüşü, kesir).

    ``tutar_egrisi`` verilirse (E2 sabit tutar, bkz. ``sabit_tutar_egrisi``): ``account``/trader hesabına ORANLI kopyalama
    YERİNE, her taze açılış kopya hesabının KENDİ o anki ``base_usd`` ölçeğindeki değerine göre sabit $ tutarla açılır;
    Bu modda AYRICA E2/E3 risk katmanı (çapraz teminat tasfiyesi + ``style`` verilirse aşamalı zarar_kes/kar_al,
    ``golge.py``'deki ile AYNI dondurulmuş eşikler) gerçek `held`/`entry` üzerinde çalışır; zorunlu çıkışlar
    ``olaylar``'da (``[{"coin","neden","zaman_ms"}]``) döner.
    """
    if tutar_egrisi is None:
        scale = capital_scale(account)
        if scale is None:
            return {"net": None, "missing": 0, "executed": 0}
    else:
        scale = None
    rate = cost_rate(rules)
    held: dict[str, float] = {}       # kopya pozisyonu (coin birimi)
    entry: dict[str, float] = {}
    timeline: dict[str, list[tuple[int, float, float]]] = {}   # coin -> (yürütme zamanı, pozisyon sonrası, ortalama giriş)
    realized = costs = 0.0
    flow: dict[int, float] = {}
    missing = executed = 0
    sells = _SELL
    execution = market.execution
    acilis: dict[str, int] = {}       # E2/E3 risk katmanı (sabit tutar modu): coin -> açılış zamanı
    son_kontrol: dict[str, int] = {}  # coin -> son risk denetimi zamanı
    olaylar: list[dict] = []          # zorunlu çıkışlar: [{"coin","neden","zaman_ms"}]
    suppressed: set[str] = set()      # zorunlu çıkıştan sonra trader pozisyonu sıfırlanana dek kopyalanmaz
    for fill in sorted(fills, key=_by_time):   # kararlı sıralama: aynı ms'deki dolumlar API sırasını korur
        coin = fill["coin"]
        sign = -1.0 if fill["side"] in sells else 1.0
        size = float(fill["sz"])
        before_leader = float(fill.get("startPosition", 0))
        signed = sign * size
        if abs(signed) < 1e-12:
            continue
        if coin in suppressed:
            if abs(before_leader + signed) < 1e-12:
                suppressed.discard(coin)
            continue
        if "_execution_time" in fill:
            when, price = int(fill["_execution_time"]), float(fill["_execution_price"])
        elif delay_min == 0:
            when, price = int(fill["time"]), float(fill.get("px", 0))
        else:
            found = execution(coin, int(fill["time"]) + delay_min * 60_000)
            if found is None:
                missing += 1
                continue
            when, price = found
        if when > end_ms or when < start_ms:
            continue
        if tutar_egrisi is not None:
            realized, costs = _risk_denetle(held, entry, acilis, son_kontrol, market, when, rules, style, rate,
                                            realized, costs, flow, timeline, olaylar, suppressed)
            if coin in suppressed:    # bu dolumun kendi coin'i az önce bu saatte zorunlu kapandı
                if abs(before_leader + signed) < 1e-12:   # trader da AYNI dolumla sıfırlandı: bastırma hemen kalkar
                    suppressed.discard(coin)
                continue
        own = held.get(coin, 0.0)
        if tutar_egrisi is None:
            factor = scale(int(fill["time"]))     # kopya sermayesi 1 / trader'ın o andaki hesap değeri
            if before_leader * signed < 0:    # trader'ın pozisyonunu azaltıyor / kapatıyor / ters çeviriyor
                leader_close = min(abs(before_leader), abs(signed))
                # kopya, kendi pozisyonunun trader'ın kapattığı oranı kadarını kapatır (ölçek zamanla değişse de artık pozisyon kalmaz)
                close = abs(own) * leader_close / abs(before_leader) if own * before_leader > 0 else 0.0
                signed = sign * (close + max(0.0, abs(signed) - leader_close) * factor)
            else:
                signed = signed * factor
        else:
            signed = _sabit_tutar_signed(sign, signed, before_leader, own, price, when, held, entry, market,
                                         realized, tutar_egrisi, base_usd)
        if abs(signed) < 1e-15:
            continue
        executed += 1
        pnl = 0.0
        new_entry = entry.get(coin, price)
        if own * signed < 0:               # kopyada azaltma / kapatma / ters çevirme
            closing = min(abs(own), abs(signed))
            pnl = closing * (price - entry[coin]) * (1.0 if own > 0 else -1.0)
            after = own + signed
            new_entry = price if abs(signed) > abs(own) else entry[coin]
            if abs(after) < 1e-15:
                after = 0.0
        else:                              # açma / ekleme
            after = own + signed
            new_entry = (entry.get(coin, price) * abs(own) + price * abs(signed)) / abs(after)
        cost = abs(signed) * price * rate
        realized += pnl - cost
        costs += cost
        flow[when // DAY] = flow.get(when // DAY, 0.0) + (pnl - cost)
        timeline.setdefault(coin, []).append((when, after, new_entry))
        if after == 0.0:
            held.pop(coin, None)
            entry.pop(coin, None)
            if tutar_egrisi is not None:
                acilis.pop(coin, None)
                son_kontrol.pop(coin, None)
        else:
            held[coin], entry[coin] = after, new_entry
            if tutar_egrisi is not None:
                if own == 0.0 or own * after < 0:   # taze açılış ya da flip: risk saati sıfırlanır
                    acilis[coin] = when
                son_kontrol[coin] = when
    if tutar_egrisi is not None:
        realized, costs = _risk_denetle(held, entry, acilis, son_kontrol, market, end_ms, rules, style, rate,
                                        realized, costs, flow, timeline, olaylar, suppressed)
    # Funding: kopyanın pozisyonu × saatlik açılış × oran; pozisyonun bulunduğu saat aralığı [dolum saati, sonraki olay saati)
    funding_total = 0.0
    funding_by_day: dict[int, float] = {}
    if rates is not None:
        for coin, events in timeline.items():
            times, cum = market.funding_cum(coin, rates)
            if not times:
                continue
            for k, (when, after, _) in enumerate(events):
                if after == 0.0:
                    continue
                until = events[k + 1][0] if k + 1 < len(events) else end_ms
                first, last = bisect_left(times, when), bisect_left(times, until)
                if last <= first:
                    continue
                funding_total += -after * (cum[last] - cum[first])
                if daily:
                    _, opens, _ = market.lists(coin)
                    grid_rates = rates.array(coin, np.array(times[first:last], dtype=np.int64))
                    for hour, price, rate_h in zip(times[first:last], opens[first:last], grid_rates.tolist()):
                        funding_by_day[hour // DAY] = funding_by_day.get(hour // DAY, 0.0) - after * price * rate_h
    boundaries = [end_ms]
    if daily and timeline:
        first_day = min(flow) if flow else start_ms // DAY
        boundaries = [(d + 1) * DAY for d in range(first_day, end_ms // DAY)] + [end_ms]

    event_times = {coin: [e[0] for e in events] for coin, events in timeline.items()}

    def unrealized_at(moment: int) -> tuple[float, int, int | None]:
        total, unknown, oldest = 0.0, 0, None          # oldest: kullanılan işaretlerin en eskisinin mum zamanı (işaret yaşı)
        for coin, events in timeline.items():
            index = bisect_right(event_times[coin], moment) - 1
            if index < 0 or events[index][1] == 0.0:
                continue
            found = market.mark_at(coin, moment)
            if found is None:
                unknown += 1
                continue
            total += events[index][1] * (found[1] - events[index][2])
            oldest = found[0] if oldest is None else min(oldest, found[0])
        return total, unknown, oldest

    unrealized_end, unknown_end, mark_time = unrealized_at(end_ms)
    open_positions = {coin: size for coin, size in held.items() if abs(size) >= 1e-15}
    open_notional = 0.0
    for coin, size in open_positions.items():
        mark = market.mark(coin, end_ms)
        if mark is not None:
            open_notional += abs(size) * mark
    result: dict[str, Any] = {"net": realized + funding_total + unrealized_end, "missing": missing, "executed": executed, "costs": costs,
                              "funding": funding_total, "realized": realized, "unrealized_end": unrealized_end, "mark_missing": unknown_end,
                              "mark_time": mark_time, "acik_pozisyon_sayisi": len(open_positions), "acik_pozisyon_notional": open_notional,
                              "olaylar": olaylar}
    if daily:
        days: dict[int, float] = {}
        previous_u = 0.0
        for boundary in boundaries:
            day = (boundary - 1) // DAY
            u, _, _ = unrealized_at(boundary)
            days[day] = days.get(day, 0.0) + flow.get(day, 0.0) + funding_by_day.get(day, 0.0) + (u - previous_u)
            previous_u = u
        import pandas as pd
        series = pd.Series({pd.Timestamp(d * DAY, unit="ms", tz="UTC").normalize(): v for d, v in sorted(days.items())})
        curve = 1.0 + series.cumsum()
        drawdown = float((1.0 - curve / curve.cummax().clip(lower=1.0)).max()) if len(curve) else 0.0
        hours = np.arange(start_ms // HOUR * HOUR, end_ms, HOUR)
        exposed = np.zeros(len(hours), dtype=bool)
        for events in timeline.values():
            et = np.array([e[0] for e in events], dtype=np.int64)
            ep = np.array([e[1] for e in events])
            idx = np.searchsorted(et, hours, side="right") - 1
            exposed |= np.where(idx >= 0, ep[np.clip(idx, 0, None)] != 0.0, False)
        by_day = pd.Series(exposed.astype(float), index=pd.to_datetime(hours, unit="ms", utc=True)).resample("1D").mean()
        result.update({"daily": series, "exposure": by_day, "max_drawdown": drawdown})
    return result
