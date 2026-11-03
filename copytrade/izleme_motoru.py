"""Saatlik, salt okunur Hyperliquid izleme; yalnız sanal defter üretir.

Dış sözleşme durum.json'dur. Yeniden oynatılabilir ham veriler ve imleçler
motor.json'da ayrı tutulur; başarısız bir koşu iki dosyayı da yayımlamaz.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from copytrade.defter import Market, copy_ledger
from copytrade.kapi import (SLIPPAGE, TAKER, binance_availability, delayed_copy, spot_usdc,
                            write_binance_universe)
from copytrade.pozisyon_mutabakat import mutabakat, ozet
from copytrade.olcut import _funding_amount, asset_class, calculate_metrics, closed_round_trips, perp_fills
from copytrade.tarama import PublicClient, RateLimiter
from copytrade import ilk11_alanlar
from copytrade.izleme_liste import KOLLAR, STYLES, load_list, perp_dex_names  # noqa: F401 - m.load_list / m.KOLLAR / m.perp_dex_names dış API'si korunur
from copytrade import oda_risk
from copytrade import kopya_v2
from copytrade import kopya_v3
from copytrade import saglik_hatti
from copytrade.kurallar import load_rules

MINUTE = 60_000
DAY = 86_400_000
NEGATIF_MUM_YENIDEN_MS = 6 * 60 * MINUTE      # eksik mum (coin, hedef) bu süre sonra yeniden denenir (K-18); kalıcı atlama yok


def timestamp(value) -> pd.Timestamp:
    result = pd.Timestamp(value)
    return result.tz_localize('UTC') if result.tzinfo is None else result.tz_convert('UTC')


def iso(value) -> str:
    return timestamp(value).isoformat().replace('+00:00', 'Z')


def at_ms(value: int) -> str:
    return iso(pd.to_datetime(value, unit='ms', utc=True))


def millis(value) -> int:
    return int(timestamp(value).timestamp() * 1000)


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def fill_key(fill: dict) -> str:
    # tid may be numeric or a string in retained JSON; coin disambiguates markets.
    identity = [fill.get('coin'), str(fill['tid'])] if 'tid' in fill else fill
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def merge_rows(old: list[dict], new: list[dict], key=fill_key) -> list[dict]:
    rows = {key(row): row for row in old}
    for row in new:
        rows.setdefault(key(row), row)
    return sorted(rows.values(), key=lambda row: int(row['time']))


def funding_key(row: dict) -> str:
    return json.dumps([row['time'], row.get('delta', {}).get('coin'), row.get('hash'),
                       _funding_amount(row)], sort_keys=True)


def funding_since(client, address: str, start: int, end: int) -> list[dict]:
    result = []
    while start <= end:
        page = client.info({'type': 'userFunding', 'user': address, 'startTime': start, 'endTime': end})
        if not isinstance(page, list):
            raise ValueError('Geçersiz funding yanıtı.')
        result = merge_rows(result, page, funding_key)
        if len(page) < 500:
            return result
        newest = max(int(row['time']) for row in page)
        if newest <= start:
            raise ValueError('Funding zaman imleci ilerlemiyor; veri eksik olabilir.')
        start = newest  # overlap boundary; deduplicate
    return result


def order_id(fill: dict) -> str:
    value = fill.get('oid')
    if value is None or str(value) == '':
        raise ValueError('Dolumda oid eksik; olay güvenle üretilemez.')
    return str(value)


def event_id(trader: str, oid: str, kind: str) -> str:
    return f'{trader}-{oid}-{kind}'


def event_oid(event: dict) -> str:
    prefix = f"{event['trader']}-"
    suffix = f"-{event['tur']}"
    value = str(event['id'])
    if not value.startswith(prefix) or not value.endswith(suffix):
        raise ValueError('Geçersiz emir olay kimliği.')
    return value[len(prefix):-len(suffix)]


def order_fills(fills: list[dict]) -> list[list[dict]]:
    """Group all fills belonging to one Hyperliquid order in deterministic order."""
    grouped: dict[str, list[dict]] = {}
    for fill in sorted(perp_fills(fills), key=lambda item: (int(item['time']), str(item.get('tid', '')))):
        grouped.setdefault(order_id(fill), []).append(fill)
    return sorted(grouped.values(), key=lambda rows: (int(rows[0]['time']), order_id(rows[0])))


def fill_events(trader: str, fills: list[dict], account: float, positions: list[dict]) -> list[dict]:
    """Emit one event per order; partial fills never become false size changes."""
    result = []
    by_coin = {p['coin']: p for p in positions}
    for rows in order_fills(fills):
        fill = rows[-1]
        oid = order_id(fill)
        before = float(rows[0].get('startPosition', 0))
        signed = sum(float(item['sz']) * (-1 if item['side'] == 'A' else 1) for item in rows)
        after = before + signed
        if abs(after) < 1e-10:
            after = 0.0
        price = sum(float(item['px']) * abs(float(item['sz'])) for item in rows) / sum(abs(float(item['sz'])) for item in rows)
        kinds = []
        if before and (not after or before * after < 0):
            kinds.append(('kapanis', before))
        if after and (not before or before * after < 0):
            kinds.append(('acilis', after))
        elif before * after > 0 and abs(abs(after) / abs(before) - 1) > .25 + 1e-12:
            kinds.append(('buyutme' if abs(after) > abs(before) else 'azaltma', after))
        for kind, size in kinds:
            position = by_coin.get(fill['coin'], {})
            event = {'id': event_id(trader, oid, kind), 'zaman': at_ms(int(fill['time'])),
                     'trader': trader, 'tur': kind, 'coin': fill['coin'],
                     'yon': 'long' if size > 0 else 'short', 'fiyat': price,
                     'hesap_payi': abs(after * price) / account if account > 0 else 0.0,
                     'kaldirac': position.get('kaldirac', abs(size * float(fill['px'])) / account if account > 0 else 0.0), 'not': ''}
            if kind in {'acilis', 'buyutme'}:
                event['sanal_sonuc'] = {'durum': 'acik', 'net_yuzde': None, 'kapanis': None}
            result.append(event)
    return result


def health_denominator(portfolio: list, t0: pd.Timestamp) -> float:
    """Freeze the health denominator at t0 so later account-value changes cannot rewrite history."""
    data = dict(portfolio).get('perpAllTime') or dict(portfolio).get('allTime') or {}
    values = pd.Series({pd.to_datetime(t, unit='ms', utc=True): float(v)
                        for t, v in data.get('accountValueHistory', [])}, dtype=float).sort_index()
    positive = values[values > 0]
    at_or_before = positive[positive.index <= t0]
    selected = at_or_before.iloc[-1] if len(at_or_before) else (positive[positive.index >= t0].iloc[0] if len(positive[positive.index >= t0]) else None)
    if selected is None:
        raise ValueError('t0 için pozitif hesap değeri yok; sağlık hesaplanamaz.')
    return float(selected)


def portfolio_curve(portfolio: list, now: pd.Timestamp, denominator: float) -> pd.Series:
    periods = dict(portfolio)
    data = periods.get('perpAllTime') or periods.get('allTime') or {}
    pnl = pd.Series({pd.to_datetime(t, unit='ms', utc=True): float(v)
                     for t, v in data.get('pnlHistory', [])}, dtype=float).sort_index()
    if pnl.empty or denominator <= 0:
        raise ValueError('Portfolio PnL/pozitif t0 hesap değeri eksik; sağlık hesaplanamaz.')
    pnl = pnl[pnl.index <= now].resample('1D').last().ffill()
    return pnl / denominator


def health(history: pd.Series, t0: pd.Timestamp, now: pd.Timestamp, leverage: float,
           martingale: bool, last_fill: int | None, performans_konisi: bool | None = None) -> dict:
    """Pilotta (``saglik_performans_konisi: false``) ışık yalnız veri bayatlığı ve kaldıraca bakar (K-6: performans sızmaz)."""
    if performans_konisi is None:
        performans_konisi = bool(load_rules()['saglik_performans_konisi'])
    daily = history.diff().dropna()
    before, live = daily[daily.index < t0], daily[daily.index >= t0]
    red, yellow = [], []
    if leverage > 10:
        red.append('gerçek kaldıraç > 10x')
    elif leverage >= 3:
        yellow.append('gerçek kaldıraç 3–10x')
    if martingale:
        red.append('martingale işareti')
    if last_fill is None or millis(now) - last_fill >= 30 * DAY:
        yellow.append('son 30 günde işlem yok')
    return {'isik': 'kirmizi' if red else 'sari' if yellow else 'yesil',
            'nedenler': red + yellow or ['kaldıraç normal']}


def cached_candle(value: object) -> tuple[float, bool]:
    """Read both v1 numeric entries and v1.2 entries with their price source."""
    if isinstance(value, dict):
        return float(value['fiyat']), bool(value.get('yaklasik', False))
    return float(value), False


def _mum_eksik(eksik: list[dict] | None, negatif: dict | None, coin: str, target: int, now_ms: int) -> None:
    if eksik is not None:
        eksik.append({'coin': coin, 'hedef': target})
    if negatif is not None:
        negatif.setdefault(coin, {})[str(target)] = now_ms


def _negatif_sil(negatif: dict | None, coin: str, target: int) -> None:
    if negatif is not None and coin in negatif:
        negatif[coin].pop(str(target), None)
        if not negatif[coin]:
            del negatif[coin]


def execution_candles(client, fills: list[dict], cache: dict, now_ms: int, delay: int = 30,
                      eksik: list[dict] | None = None, negatif: dict | None = None) -> tuple[dict[str, list[dict]], bool]:
    """Use 1m opens when retained; fall back to the matching 1h opening, never a later price.

    Hedef için mum yok / fiyatı ≤ 0 ise hedef ATLANIR (önbelleğe girmez, sonraki saat yeniden denenir) ve ``eksik``e ``{"coin", "hedef"}`` eklenir;
    trader düşürülmez (K-14). Ağ / API hatası ise yine istisnadır (okuma hatası).

    Negatif önbellek (K-18): ``negatif`` = ``{coin: {hedef: son_deneme_ms}}``. Eksik çıkan hedef kaydedilir; ``NEGATIF_MUM_YENIDEN_MS`` (6 saat) dolmadan
    API'ye YENİDEN SORULMAZ (saatlik koşu süresini şişirmesin) ama ``eksik``e ``onbellek: True`` ile yine yazılır (sayılır, fiyatsız kalır).
    Süre dolunca bir kez yeniden denenir: mum gelmişse kayıt silinir ve fiyat önbelleğe girer; gelmemişse kayıt tazelenir (kalıcı atlama yok)."""
    needed = {}
    approximate = any(cached_candle(value)[1] for rows in cache.values() for value in rows.values())
    for fill in fills:
        target = math.ceil((int(fill['time']) + delay * MINUTE) / MINUTE) * MINUTE
        if target <= now_ms and str(target) not in cache.get(fill['coin'], {}):
            son = (negatif or {}).get(fill['coin'], {}).get(str(target))
            if son is not None and now_ms - int(son) < NEGATIF_MUM_YENIDEN_MS:
                if eksik is not None and not any(e['coin'] == fill['coin'] and e['hedef'] == target for e in eksik):
                    eksik.append({'coin': fill['coin'], 'hedef': target, 'onbellek': True})
                continue
            if target not in needed.setdefault(fill['coin'], []):
                needed[fill['coin']].append(target)
    for coin, targets in needed.items():
        exact = [target for target in targets if target >= now_ms - 4999 * MINUTE]
        older = [target for target in targets if target < now_ms - 4999 * MINUTE]
        if exact:
            candles = client.candles(coin, min(exact), now_ms, interval='1m')
            prices = {int(c['t']): float(c['o']) for c in candles}
            for target in exact:
                if target not in prices or prices[target] <= 0:
                    _mum_eksik(eksik, negatif, coin, target, now_ms)
                    continue
                cache.setdefault(coin, {})[str(target)] = {'fiyat': prices[target], 'yaklasik': False}
                _negatif_sil(negatif, coin, target)
        if older:
            hourly = client.candles(coin, min(target // (60 * MINUTE) * (60 * MINUTE) for target in older),
                                    now_ms, interval='1h')
            prices = {int(c['t']): float(c['o']) for c in hourly}
            for target in older:
                hour = target // (60 * MINUTE) * (60 * MINUTE)
                if hour not in prices or prices[hour] <= 0:
                    _mum_eksik(eksik, negatif, coin, target, now_ms)
                    continue
                cache.setdefault(coin, {})[str(target)] = {'fiyat': prices[hour], 'yaklasik': True}
                _negatif_sil(negatif, coin, target)
                approximate = True
    return ({coin: [{'t': int(t), 'o': cached_candle(value)[0]} for t, value in rows.items()]
             for coin, rows in cache.items()}, approximate)


def open_copy_coins(actions: list[dict]) -> set[str]:
    """Kopya eylemlerinin net işaretli toplamı sıfır olmayan coinler: pencere sonunda açık pozisyonu olanlar (işaretlenecek)."""
    net: dict[str, float] = {}
    for action in actions:
        net[action['coin']] = net.get(action['coin'], 0.0) + float(action['sz']) * (-1 if action['side'] == 'A' else 1)
    return {coin for coin, size in net.items() if abs(size) > 1e-10}


def mark_candles(client, actions: list[dict], now_ms: int) -> dict[str, list[dict]]:
    """Açık kopya pozisyonlu her coin için en son 1 dk mumun açılışı (işaretleme fiyatı); mumun zamanı da taşınır (işaret yaşı)."""
    marks: dict[str, list[dict]] = {}
    for coin in sorted(open_copy_coins(actions)):
        rows = [c for c in client.candles(coin, now_ms - 15 * MINUTE, now_ms, interval='1m') if int(c['t']) <= now_ms and float(c['o']) > 0]
        if rows:
            last = max(rows, key=lambda c: int(c['t']))
            marks[coin] = [{'t': int(last['t']), 'o': float(last['o'])}]
    return marks


def copy_actions(fills: list[dict]) -> list[dict]:
    """Copy post-t0 changes only; closing inherited exposure must not open an inverse position."""
    positions, result = {}, []
    for fill in fills:
        coin = fill['coin']
        before = float(fill.get('startPosition', 0))
        signed = float(fill['sz']) * (-1 if fill['side'] == 'A' else 1)
        held = positions.get(coin, 0.0)
        if before * signed < 0:
            leader_close = min(abs(before), abs(signed))
            close = min(abs(held), leader_close) if held * before > 0 else 0.0
            signed = (close + max(0.0, abs(signed) - leader_close)) * (1 if signed > 0 else -1)
        if abs(signed) > 1e-10:
            result.append(dict(fill, sz=str(abs(signed)), startPosition=str(held)))
        positions[coin] = held + signed
    return result


def copy_results(fills: list[dict], candles: dict, funding: list[dict], account: float,
                 t0: pd.Timestamp, now: pd.Timestamp, events: dict, approximate: bool = False, delay: int = 30) -> dict:
    prices = {coin: {int(c['t']): float(c['o']) for c in rows} for coin, rows in candles.items()}
    # Pending fills are not charged before their execution time (tarza göre gecikme: intraday 30, swing 120 dk).
    mature = [f for f in fills if math.ceil((int(f['time']) + delay * MINUTE) / MINUTE) * MINUTE <= millis(now)]
    days = pd.date_range(t0.normalize(), now.normalize(), freq='1D')
    # Sonuç kanonik defterden (defter.copy_ledger) gelir: gerçekleşmiş + açık (işaretlenmiş) K/Z ayrı yayımlanır.
    ledger_fills, fiyatsiz = [], 0
    for fill in list(mature):
        execution = math.ceil((int(fill['time']) + delay * MINUTE) / MINUTE) * MINUTE
        if execution not in prices.get(fill['coin'], {}):
            mature.remove(fill)              # yürütme fiyatı yok (K-14): dolum atlanır ve sayılır; trader düşmez
            fiyatsiz += 1
            continue
        ledger_fills.append(dict(fill, _execution_time=execution, _execution_price=prices[fill['coin']][execution]))
    ledger = copy_ledger(ledger_fills, Market(candles), account, delay, millis(t0), millis(now), daily=True)
    if ledger['net'] is None:
        raise ValueError('Sanal defter için pozitif hesap değeri gerekli.')
    net = pd.Series(0.0, index=days)
    if len(ledger['daily']):
        net = net.add(ledger['daily'].reindex(days, fill_value=0.0), fill_value=0.0)
    funding_frac = 0.0
    for row in funding:                     # trader'ın funding'i hesap değerine oranlanır (kopya, trader'ı hesap oranıyla yansıtır)
        amount = _funding_amount(row) / account
        funding_frac += amount
        day = pd.Timestamp(int(row['time']), unit='ms', tz='UTC').normalize()
        if day in net.index:
            net[day] += amount
    equity = 1000 * (1 + net.cumsum())
    # FIFO lots allocate realized return and exact friction/funding to the event
    # that opened/increased them. An event may contain many partial fills/lots;
    # it closes only after every lot belonging to that event closes.
    lots = {}
    event_totals: dict[str, dict[str, float]] = {}
    event_by_order = {(e['trader'], event_oid(e)): e['id'] for e in events.values()
                      if e['tur'] in {'acilis', 'buyutme'}}
    trader_id = next((e['trader'] for e in events.values()), '')
    timeline = [(math.ceil((int(f['time']) + delay * MINUTE) / MINUTE) * MINUTE, 0, f) for f in mature]
    timeline += [(int(f['time']), 1, f) for f in funding]
    for time_ms, kind, row in sorted(timeline, key=lambda x: (x[0], x[1])):
        coin = row.get('coin') if kind == 0 else row.get('delta', {}).get('coin')
        active = lots.setdefault(coin, [])
        if kind == 1:
            total = sum(lot['remaining'] for lot in active)
            for lot in active:
                amount = _funding_amount(row) * lot['remaining'] / total if total else 0.0
                lot['pnl'] += amount
                if lot['event']:
                    event_totals[lot['event']]['pnl'] += amount
            continue
        execution = math.ceil(time_ms / MINUTE) * MINUTE
        price = prices[coin][execution]
        signed = float(row['sz']) * (-1 if row['side'] == 'A' else 1)
        remaining = abs(signed)
        direction = 1 if signed > 0 else -1
        while remaining > 1e-10 and active and active[0]['direction'] != direction:
            lot = active[0]
            closed = min(lot['remaining'], remaining)
            realized = closed * ((price - lot['price']) * lot['direction'] - price * (TAKER + SLIPPAGE))
            lot['pnl'] += realized
            if lot['event']:
                event_totals[lot['event']]['pnl'] += realized
            lot['remaining'] -= closed; remaining -= closed
            if lot['event']:
                total_event = event_totals[lot['event']]
                total_event['remaining'] -= closed
                if total_event['remaining'] < 1e-10 and lot['event'] in events:
                    events[lot['event']]['sanal_sonuc'] = {
                        'durum': 'kapandi', 'net_yuzde': total_event['pnl'] / total_event['notional'],
                        'kapanis': at_ms(execution)}
            if lot['remaining'] < 1e-10:
                active.pop(0)
        if remaining > 1e-10:
            ident = event_by_order.get((trader_id, order_id(row)), '')
            notional, entry_cost = remaining * price, -remaining * price * (TAKER + SLIPPAGE)
            active.append({'remaining': remaining, 'direction': direction, 'price': price,
                           'notional': notional, 'pnl': entry_cost, 'event': ident})
            if ident:
                total_event = event_totals.setdefault(ident, {'remaining': 0.0, 'notional': 0.0, 'pnl': 0.0})
                total_event['remaining'] += remaining
                total_event['notional'] += notional
                total_event['pnl'] += entry_cost
    peak = np.maximum.accumulate(np.r_[1000.0, equity.to_numpy()])
    drawdown = float(np.max(1 - np.r_[1000.0, equity.to_numpy()] / peak)) if len(equity) else 0.0
    balance = float(equity.iloc[-1]) if len(equity) else 1000.0
    result = {'baslangic_usd': 1000, 'bakiye_usd': balance, 'getiri': balance / 1000 - 1,
            'dusus': drawdown, 'gecikme_dk': delay, 't0': str(t0.date()),
            'egri': [[str(day.date()), float(value)] for day, value in equity.items()],
            # hesap değerine oranlı kesirler: gerçekleşmiş (maliyet + funding dahil), açık (işaretlenmiş) ve toplam; son işaret zamanı
            'gerceklesen': ledger['realized'] + funding_frac, 'acik': ledger['unrealized_end'], 'toplam': ledger['net'] + funding_frac,
            'son_isaret': at_ms(ledger['mark_time']) if ledger['mark_time'] is not None else None, 'isaret_eksik': int(ledger['mark_missing'])}
    if fiyatsiz:
        result['fiyatsiz_eylem'] = fiyatsiz
    notes = (['yaklaşık fiyat'] if approximate else []) + (['eksik işaretleme'] if ledger['mark_missing'] else []) + ([f'{fiyatsiz} dolumun fiyatı eksik (atlandı)'] if fiyatsiz else [])
    if notes:
        result['not'] = ', '.join(notes)
    return result


def positions_from_state(states: list[dict], fills: list[dict], symbols: set[str] | None, now: pd.Timestamp) -> tuple[float, list[dict]]:
    account = sum(float(state['marginSummary']['accountValue']) for state in states)
    result = []
    for state in states:
        for item in state['assetPositions']:
            p = item['position']
            size = float(p['szi'])
            if not size:
                continue
            coin = p['coin']
            openings = [f for f in fills if f['coin'] == coin and
                        (float(f.get('startPosition', 0)) == 0 or
                         float(f.get('startPosition', 0)) * (float(f.get('startPosition', 0)) +
                         float(f['sz']) * (-1 if f['side'] == 'A' else 1)) < 0)]
            result.append({'coin': coin, 'sinif': asset_class(coin), 'yon': 'long' if size > 0 else 'short',
                           'giris': float(p['entryPx']), 'buyukluk_usd': abs(float(p['positionValue'])),
                           'hesap_payi': abs(float(p['positionValue'])) / account if account > 0 else 0.0,
                           'kaldirac': float(p['leverage']['value']), 'anlik_kz_usd': float(p['unrealizedPnl']),
                           'acilis': at_ms(int(openings[-1]['time'])) if openings else '',
                           'binance': binance_availability(coin, symbols)})
    return account, result


def defter_pozisyonlari(fills: list[dict]) -> dict[str, float]:
    """Dolumlardan türetilen pozisyon (kaynak birimi): her coinin son dolumundan sonraki işaretli büyüklük (``startPosition`` + dolum)."""
    last: dict[str, tuple[int, float]] = {}
    for fill in sorted(perp_fills(fills), key=lambda f: int(f['time'])):
        signed = float(fill['sz']) * (-1 if fill['side'] == 'A' else 1)
        last[fill['coin']] = (int(fill['time']), float(fill.get('startPosition', 0)) + signed)
    return {coin: size for coin, (_, size) in last.items()}


def mutabakat_raporu(fills: list[dict], states: list[dict], now: pd.Timestamp, rules: dict | None = None,
                      onceki_hesap_degeri: float | None = None, hesap_degeri: float | None = None) -> dict:
    """Oda üyesi için defter ↔ ``clearinghouseState`` mutabakatı (A13): yalnız rapor; hiçbir pozisyon kapatılmaz, defter değişmez.
    ``veri_kalitesi.mutabakat``: durum sayıları, ``uyumsuz_oran``, ``yetim_coinler``, atlanan bozuk satır, zaman."""
    rules = rules or load_rules()
    exchange = {'assetPositions': [item for state in states for item in state.get('assetPositions', [])]}
    rows, broken = mutabakat(defter_pozisyonlari(fills), exchange, float(rules['mutabakat_goreli_tolerans']), float(rules['mutabakat_mutlak_tolerans']))
    summary = ozet(rows)
    jump = (abs(hesap_degeri / onceki_hesap_degeri - 1) if onceki_hesap_degeri and hesap_degeri else 0.0)
    # Kırmızı nedenler sarıdan önce gelir: sıçrama, yetim pozisyonu gizlememeli.
    if summary['yetim']:
        health = {'isik': 'kirmizi', 'neden': 'yetim pozisyon'}
    elif summary['uyumsuz_oran'] >= float(rules['mutabakat_saglik_kirmizi_uyumsuz_oran']):
        health = {'isik': 'kirmizi', 'neden': 'pozisyon oranı uyumsuz'}
    elif jump >= float(rules['mutabakat_saglik_hesap_degeri_sicrama_oran']):
        health = {'isik': 'sari', 'neden': 'hesap değeri sıçraması (yatırma/çekme şüphesi)'}
    elif summary['uyumsuz_oran'] >= float(rules['mutabakat_saglik_sari_uyumsuz_oran']):
        health = {'isik': 'sari', 'neden': 'kaçırılmış dolum olasılığı'}
    elif broken:
        health = {'isik': 'sari', 'neden': 'bozuk mutabakat satırı'}
    else:
        health = {'isik': 'yesil', 'neden': 'mutabakat uyumlu'}
    return {**summary, 'saglik': health, 'hesap_degeri_sicramasi': jump, 'yetim_coinler': [r['coin'] for r in rows if r['durum'] == 'yetim'],
            'sorunlu': [r for r in rows if r['durum'] != 'uyumlu'], 'bozuk_satir': broken, 'zaman': iso(now)}


def gate_result(root: Path, address: str) -> dict:
    for path in sorted((root / 'copytrade/kapi').glob('*/sonuc.csv'), reverse=True):
        with path.open(encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                if row['address'].lower() == address.lower():
                    return {'sinif': row['sinif'] if row['sinif'] in {'Geçti', 'Yetersiz', 'Kaldı'} else 'Yetersiz',
                            'tarih': path.parent.name, 'not': row.get('neden', '')}
    return {'sinif': 'Yetersiz', 'tarih': '', 'not': 'Kapı sonucu bulunamadı'}


def gate_style(root: Path, address: str) -> str | None:
    """Adresin en son kapı sonucundaki ``tarz`` (intraday | swing | scalp); sonuç veya sütun yoksa ``None``."""
    for path in sorted((root / 'copytrade/kapi').glob('*/sonuc.csv'), reverse=True):
        with path.open(encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                if row['address'].lower() == address.lower():
                    return row.get('tarz') or None
    return None


def resolve_style(root: Path, row: dict) -> str:
    """İzleme listesindeki ``tarz``; yoksa kapı sonucundan; ikisi de yoksa ``bilinmiyor`` (gecikme 30 dk)."""
    return row.get('tarz') or gate_style(root, row['adres']) or 'bilinmiyor'


def delay_for_style(style: str, rules: dict | None = None) -> int:
    """Sanal kopya gecikmesi (dk): intraday 30, swing 120 (kurallar.yaml ``kopya_gecikme_dk``); scalp/bilinmiyor 30."""
    rules = rules or load_rules()
    return int(rules['kopya_gecikme_dk']['swing' if style == 'swing' else 'intraday'])


def clearinghouse_states(client: PublicClient, address: str, dexes: list[str]) -> list[dict]:
    """Read main perpetuals plus each HIP-3 dex; state responses are not interchangeable."""
    states = [client.info({'type': 'clearinghouseState', 'user': address}, weight=2)]
    for dex in dexes:
        states.append(client.info({'type': 'clearinghouseState', 'user': address, 'dex': dex}, weight=2))
    return states


def with_data_error(trader: dict, error: Exception) -> dict:
    previous = copy.deepcopy(trader)
    short = data_error_reason(error)
    reasons = [reason for reason in previous['saglik']['nedenler'] if not reason.startswith('veri hatası:')]
    previous['saglik']['nedenler'] = reasons + [f'veri hatası: {short}']
    previous['gecerli'] = False
    previous['veri_durumu'], previous['veri_durumu_neden'] = 'okuma_hatasi', short       # önceki yük korunur; bu saatin okuması başarısız
    return previous


def kasa_egrisi(traderlar: list[dict], kol: str, gun: int = 90) -> list[list[object]]:
    """Koldaki sanal-kopya bakiyelerinin son ``gun`` günlük toplamı.

    v3 hesaplanamamış bir trader
    o günden dışarıda bırakılır (sıfır olarak sayılmaz) — her trader kendi son bilinen günlük bakiyesiyle
    taşınır; eksik eğri uydurulmaz.
    """
    curves = []
    for trader in traderlar:
        if trader.get('kol') != kol:
            continue
        values = {str(day): float(value) for day, value in trader.get('sanal_kopya_v3', {}).get('egri', [])}
        if values:
            curves.append(values)
    dates = sorted({day for curve in curves for day in curve})[-gun:]
    result = []
    for day in dates:
        total = 0.0
        for curve in curves:
            known = [key for key in curve if key <= day]
            if known:
                total += curve[max(known)]
        result.append([day, total])
    return result


def data_error_reason(error: Exception) -> str:
    return str(error).splitlines()[0][:120] or type(error).__name__


def unavailable_trader(root: Path, row: dict, error: Exception) -> dict:
    """Publish an explicit placeholder when a trader has never completed a read."""
    # Yer tutucu, beklenen tüm alanları taşımalıdır.
    style = resolve_style(root, row)
    return {**{k: v for k, v in row.items() if k != 'tarz'}, 'tarz': style, 'veri_zamani': None, 'gecerli': False,
            'kapi': gate_result(root, row['adres']),
            'saglik': {'isik': 'sari', 'nedenler': [f'veri hatası: {data_error_reason(error)}']},
            'form': {'skor': 0.0, 'getiri_30g': 0.0, 'getiri_90g': 0.0},
            'hesap_degeri': 0.0, 'hesap_degeri_toplam': None, 'pozisyonlar': [], 'egri': [],
            'son_islem': {'coin': '', 'yon': '', 'acilis': '', 'kapanis': '', 'net_yuzde': 0.0},
            'veri_durumu': 'okuma_hatasi', 'veri_durumu_neden': data_error_reason(error), 'mum_eksik': {'hedef': 0, 'onbellekten': 0},
            'sanal_kopya': {'baslangic_usd': 1000, 'bakiye_usd': 1000.0, 'getiri': 0.0, 'dusus': 0.0,
                            'gecikme_dk': delay_for_style(style), 't0': str(timestamp(row['t0']).date()), 'egri': [], 'yer_tutucu': True},
            'sanal_kopya_v2': {'surum': 'v2', 'durum': 'hesaplanamadi', 'yer_tutucu': True, 'neden': 'hiç okunmadı'},
            'sanal_kopya_v3': {'surum': 'v3', 'durum': 'hesaplanamadi', 'yer_tutucu': True, 'neden': 'hiç okunmadı'},
            'ilk11_form_ham': {'hata': 'hiç okunmadı'}, 'son_perp_dolum': None,
            'ilk11_gecerli_saat': {'baslangic': row.get('takim_hafta') or str(timestamp(row['t0']).date()), 'saat': 0, 'son_saat': None}}


def yonsuz_guncelle(client, address: str, saved: dict, states: list[dict], fills: list[dict], now: pd.Timestamp) -> dict:
    """Oda ve kontrol üyesi için ``yonsuz_bayrak`` (A26): funding geliri ve spot bakiyesi günde bir kez çekilip ``motor.json``'da önbelleğe alınır; maker payı ve spot↔perp örtüşmesi
    her saat eldeki dolum ve pozisyonlardan hesaplanır. Okunamayan kaynak ``None`` olur ve ``hata`` alanına yazılır (gizlenmez, o gün önbelleğe girmez → sonraki saat yeniden dener)."""
    rules, gun, hatalar = load_rules(), str(now.date()), []
    onbellek = saved.get('yonsuz_onbellek')
    if not onbellek or onbellek.get('gun') != gun:
        onbellek = {'gun': gun, 'funding_usd': None, 'spot': None}
        try:
            start = millis(now) - int(rules['yonsuz_pencere_gun']) * DAY
            onbellek['funding_usd'] = sum(_funding_amount(row) for row in funding_since(client, address, start, millis(now)))
        except Exception as error:
            hatalar.append(f'funding: {data_error_reason(error)}')
        try:
            spot = client.info({'type': 'spotClearinghouseState', 'user': address}, weight=2)
            onbellek['spot'] = {str(b['coin']): float(b['total']) for b in spot.get('balances', []) if float(b.get('total', 0))}
        except Exception as error:
            hatalar.append(f'spot: {data_error_reason(error)}')
        if not hatalar:
            saved['yonsuz_onbellek'] = onbellek
    perp = {item['position']['coin']: float(item['position']['szi']) for state in states for item in state['assetPositions'] if float(item['position']['szi'])}
    return oda_risk.yonsuz_bayrak(onbellek['funding_usd'], oda_risk.toplam_kar(saved.get('portfolio') or [], millis(now), rules), onbellek['spot'], perp, fills, millis(now), rules,
                                  '; '.join(hatalar) or None)


def gecerli_saat_say(saved: dict, row: dict, now: pd.Timestamp) -> dict:
    """`ilk11_gecerli_saat` (şartname §4.1 eşitlik 3): trader'ın kadroya SON girişinden (`takim_hafta`; yoksa `t0`) itibaren geçerli (`gecerli == true`)
    saatlik okuma sayısı. Aynı saat dilimine düşen ikinci koşu yeniden saymaz; `takim_hafta` değişince (yeni giriş) sayaç sıfırlanır. Sayım BU motorun
    okumalarından başlar (geriye dönük doldurulmaz). `motor.json`'da kalıcı (`saved['ilk11_gecerli_saat']`), `durum.json`'a trader alanı olarak yayımlanır."""
    baslangic = row.get('takim_hafta') or str(timestamp(row['t0']).date())
    kayit = saved.get('ilk11_gecerli_saat')
    if not kayit or kayit.get('baslangic') != baslangic:
        kayit = {'baslangic': baslangic, 'saat': 0, 'son_saat': None}
    saat = iso(now.floor('h'))
    if kayit['son_saat'] != saat:
        kayit['saat'] += 1
        kayit['son_saat'] = saat
    saved['ilk11_gecerli_saat'] = kayit
    return dict(kayit)


def durum_icin_kirp(trader: dict, now: pd.Timestamp, rules: dict | None = None) -> dict:
    """`durum.json` (yayın) için `sanal_kopya_v3.kapanan_islemler` kırpması; TAM geçmiş `motor.json`'daki `son_trader`'da silinmeden kalır.

    Yayımlanan: kapanışı son `ilk11_form_pencere_gun` günde (now − N gün, now] olanlar VE (pencereden eski olsa da) en son `ilk11_durum_min_gecerli_islem`
    GEÇERLİ işlem (terfi kapısı son N geçerli işleme bakar). Sıra korunur. `kapanan_islemler_toplam` = tam geçmişteki sayı. Trader'ın kopyası döner."""
    rules = rules or load_rules()
    v3 = trader.get('sanal_kopya_v3')
    islemler = v3.get('kapanan_islemler') if isinstance(v3, dict) else None
    if islemler is None:
        return trader
    sinir = now - pd.Timedelta(days=int(rules['ilk11_form_pencere_gun']))
    gecerli = [i for i, x in enumerate(islemler) if x.get('gecerli') is True]
    son_gecerli = set(sorted(gecerli, key=lambda i: islemler[i]['kapanis'])[-int(rules['ilk11_durum_min_gecerli_islem']):])
    kalan = [x for i, x in enumerate(islemler) if timestamp(x['kapanis']) > sinir or i in son_gecerli]
    return {**trader, 'sanal_kopya_v3': {**v3, 'kapanan_islemler': kalan, 'kapanan_islemler_toplam': len(islemler)}}


def veri_durumu_belirle(account: float, paper: dict, paper_v3: dict, eksik_hedef: int, isaret_eksik: list[str] | None = None, eksik_onbellek: int = 0) -> tuple[str, str]:
    """Trader başına veri durumu kodu (K-14; ``durum`` izleme listesinin kendi alanıdır, bu yüzden ``veri_durumu``). Öncelik: perp_bos > fiyatsiz > tamam.
    ``okuma_hatasi`` okuması başarısız saatte ``with_data_error`` / ``unavailable_trader`` tarafından yazılır; ``bayat`` yayın anında ``bayat_isle`` ile.
    Fiyat eksiği = yürütme mumu eksik dolum (v1 atlanan, v3 ``fiyatsiz_eylem``) ya da açık kopya coini için işaret fiyatı eksik (``isaret_eksik``: coin listesi)."""
    if account <= 0:
        return 'perp_bos', 'perp hesap değeri 0 (ana + HIP-3); v1 yer tutucu, v3 / olaylar sürer'
    fiyatsiz = max(int(paper_v3.get('fiyatsiz_eylem', 0) or 0), eksik_hedef, int(paper.get('fiyatsiz_eylem', 0) or 0))
    nedenler = ([f'{fiyatsiz} dolum için mum fiyatı eksik (atlandı, sayıldı)'
                 + (f'; {eksik_onbellek} hedef negatif önbellekten (6 saatte bir yeniden denenir)' if eksik_onbellek else '')] if fiyatsiz else []) + \
               ([f"işaret fiyatı eksik: {', '.join(isaret_eksik)}"] if isaret_eksik else [])
    return ('fiyatsiz', '; '.join(nedenler)) if nedenler else ('tamam', '')


def bayat_isle(trader: dict, uretildi: pd.Timestamp, rules: dict | None = None) -> dict:
    """Yayın anında: ``tamam`` görünen ama ``veri_zamani`` yayın anındaki ``uretildi``'den ``ilk11_form_tazelik_dk`` dakikadan eski trader ``bayat`` olur
    (önceki başarılı veri taşınıyorsa). ``okuma_hatasi`` / ``perp_bos`` / ``fiyatsiz`` önceliği korunur. Kopya döner."""
    if trader.get('veri_durumu') != 'tamam' or not trader.get('veri_zamani'):
        return trader
    yas = (uretildi - timestamp(trader['veri_zamani'])) / pd.Timedelta(minutes=1)
    sinir = int((rules or load_rules())['ilk11_form_tazelik_dk'])
    if yas > sinir:
        return {**trader, 'veri_durumu': 'bayat', 'veri_durumu_neden': f'veri {yas:.0f} dk eski (> {sinir} dk)'}
    return trader


def update_trader(root: Path, client, dexes: list[str], state: dict, all_events: dict,
                  row: dict, now: pd.Timestamp, symbols: set[str] | None) -> dict:
    ident, address, t0 = row['id'], row['adres'], timestamp(row['t0'])
    saved = state['traderlar'].setdefault(ident, {'adres': address.lower(), 't0': iso(t0),
                                                   'fills': [], 'funding': [], 'mumlar': {}, 'mum_eksik': {}})
    if saved['adres'] != address.lower() or saved['t0'] != iso(t0):
        raise ValueError(f'{ident}: adres/t0 değiştirilemez; yeni izleme için yeni id kullanın.')
    start = min(millis(t0), millis(now) - 90 * DAY)
    cursor = saved.get('son_dolum', start)
    fresh = client.fills(address, cursor)
    if not isinstance(fresh, list):
        raise ValueError('Geçersiz dolum yanıtı.')
    fills = merge_rows(saved['fills'], [f for f in fresh if int(f['time']) <= millis(now)])
    saved['fills'] = fills
    saved['son_dolum'] = max([cursor] + [int(f['time']) for f in fills])
    # Health is refreshed hourly. The t0 denominator is persisted once and never recalculated.
    saved['portfolio'] = client.portfolio(address)
    # t0 değişirse (liste yeniden başlatılınca) payda yeni t0'a göre bir kez yeniden sabitlenir.
    saglik_notu = None
    if saved.get('saglik_paydasi_t0') != str(t0.date()):
        try:
            saved['saglik_paydasi'] = health_denominator(saved['portfolio'], t0)
            saved['saglik_paydasi_t0'] = str(t0.date())
        except ValueError as error:           # t0 için pozitif hesap değeri yok: trader düşmez, ışık "bilinmiyor" (K-14); sonraki saat yeniden denenir
            saved['saglik_paydasi'], saglik_notu = None, data_error_reason(error)
    history = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz='UTC'))
    if saved.get('saglik_paydasi'):
        try:
            history = portfolio_curve(saved['portfolio'], now, float(saved['saglik_paydasi']))
        except ValueError as error:
            saglik_notu = data_error_reason(error)
    states = clearinghouse_states(client, address, dexes)
    account, positions = positions_from_state(states, fills, symbols, now)
    if account > 0:
        saved.setdefault('kopya_paydasi', account)
    copy_fills = [f for f in perp_fills(fills) if int(f['time']) >= millis(t0)]
    new_funding = funding_since(client, address, saved.get('son_funding', millis(t0)), millis(now))
    saved['funding'] = merge_rows(saved['funding'], new_funding, funding_key)
    saved['son_funding'] = max([saved.get('son_funding', millis(t0))] + [int(f['time']) for f in saved['funding']])
    for event in fill_events(ident, copy_fills, account, positions):
        all_events[event['id']] = event
    own_events = {key: event for key, event in all_events.items() if event['trader'] == ident}
    actions = copy_actions(copy_fills)
    style = resolve_style(root, row)
    delay = delay_for_style(style)
    eksik_mum: list[dict] = []
    # A4-3a: yürütme fiyatı v3'ün gördüğü HAM dolumlar (copy_fills) için çekilir; `actions` süzgecinde (devralınan pozisyonu kapatma) düşen dolumlar v3'te fiyatsız kalıyordu.
    candles, approximate = execution_candles(client, copy_fills, saved['mumlar'], millis(now), delay, eksik_mum, saved.setdefault('mum_eksik', {}))
    marks = mark_candles(client, actions, millis(now))
    priced = {coin: rows + marks.get(coin, []) for coin, rows in {**{c: [] for c in marks}, **candles}.items()}
    if account > 0:
        paper = copy_results(actions, priced, saved['funding'], saved['kopya_paydasi'], t0, now, own_events, approximate, delay)
    else:                                     # perp hesap değeri 0: v1 (hesaba oranlı) hesaplanamaz -> açıkça işaretli yer tutucu; v3 / olaylar sürer
        paper = {'baslangic_usd': 1000, 'bakiye_usd': 1000.0, 'getiri': 0.0, 'dusus': 0.0, 'gecikme_dk': delay, 't0': str(t0.date()), 'egri': [],
                 'yer_tutucu': True, 'neden': 'perp hesap değeri 0'}
    # girdisi (tek fetch, kural 7). v1 (paper/sanal_kopya) yanında yayımlanır, değiştirmez; hata v1'i düşürmez (kural 6).
    try:
        saatlik = kopya_v2.saatlik_mumlar(client, saved.setdefault('mumlar_1s', {}), copy_fills,
                                          open_copy_coins(actions), millis(now))
        yurutme = {coin: {int(c['t']): float(c['o']) for c in rows} for coin, rows in candles.items()}
        mum_error = None
    except Exception as error:
        saatlik = yurutme = None
        mum_error = error
    if mum_error is not None:
        paper_v2 = {'surum': 'v2', 'durum': 'hesaplanamadi', 'neden': data_error_reason(mum_error)}
        paper_v3 = {'surum': 'v3', 'durum': 'hesaplanamadi', 'neden': data_error_reason(mum_error)}
    else:
        try:
            if account <= 0:
                raise ValueError('perp hesap değeri 0')
            hesap_serisi = kopya_v2.hesap_serisi_guncelle(saved, millis(t0), millis(now), account)
            paper_v2 = kopya_v2.hesapla(copy_fills, saatlik, marks, yurutme, hesap_serisi, saved['funding'],
                                        t0, now, delay, style)
        except Exception as error:
            paper_v2 = {'surum': 'v2', 'durum': 'hesaplanamadi', 'neden': data_error_reason(error)}
        # trader hesabına ORANLI değil, kopyanın KENDİ değerine göre sabit $ tutarla açılış (kopya_v3.py). v2'den
        # bağımsız hata yalıtımı (kural 6).
        try:
            paper_v3 = kopya_v3.hesapla(copy_fills, saatlik, marks, yurutme, saved['funding'], t0, now, delay, style)
        except Exception as error:
            paper_v3 = {'surum': 'v3', 'durum': 'hesaplanamadi', 'neden': data_error_reason(error)}
    leverage = sum(p['buyukluk_usd'] for p in positions) / account if account > 0 else 0.0
    metrics = calculate_metrics(perp_fills(fills), account_value=account)
    light = health(history, t0, now, leverage, metrics['martingale_signal'],
                   max((int(f['time']) for f in perp_fills(fills)), default=None))
    if saglik_notu:                           # payda yok -> ışık "bilinmiyor" (kaldıraç / martingale nedenleri yine yazılır)
        light = {'isik': 'bilinmiyor', 'nedenler': [f'sağlık paydası yok: {saglik_notu}'] + [n for n in light['nedenler'] if n != 'kaldıraç normal']}
    if saved.get('isik') is not None and light['isik'] != saved['isik']:
        event = {'id': f'{ident}-{millis(now)}-isik', 'zaman': iso(now), 'trader': ident,
                 'tur': 'isik', 'coin': '', 'yon': '', 'fiyat': None, 'hesap_payi': None,
                 'kaldirac': None, 'not': light['isik']}
        all_events[event['id']] = event
    saved['isik'] = light['isik']
    saved['son_olaylar'] = [event for event in all_events.values() if event['trader'] == ident]
    equity = pd.Series([value for _, value in paper['egri']],
                       index=pd.DatetimeIndex([timestamp(day) for day, _ in paper['egri']], tz='UTC'), dtype=float)
    base_30 = equity[equity.index < now.normalize() - pd.Timedelta(days=29)]
    ret30 = float(equity.iloc[-1] / (base_30.iloc[-1] if len(base_30) else 1000) - 1) if len(equity) else 0.0
    recent = history[history.index >= now.normalize() - pd.Timedelta(days=89)]
    volatility = float(recent.diff().dropna().std()) if len(recent) > 2 else 0.0
    trades = closed_round_trips(perp_fills(fills))
    last = trades[-1] if trades else None
    last_trade = {'coin': '', 'yon': '', 'acilis': '', 'kapanis': '', 'net_yuzde': 0.0}
    if last:
        ending = next(f for f in reversed(fills) if f['coin'] == last['coin'] and int(f['time']) == millis(last['close_time']))
        traded = [f for f in fills if f['coin'] == last['coin'] and last['open_time'] is not None
                  and millis(last['open_time']) <= int(f['time']) <= millis(last['close_time'])]
        notional = sum(float(f['px']) * float(f['sz']) for f in traded if float(f.get('closedPnl', 0)) == 0)
        last_trade = {'coin': last['coin'], 'yon': 'long' if float(ending.get('startPosition', 0)) > 0 else 'short',
                      'acilis': iso(last['open_time']) if last['open_time'] is not None else '',
                      'kapanis': iso(last['close_time']), 'net_yuzde': last['net_pnl'] / notional if notional else 0.0}
    try:    # İlk 11 `hesap` (İ ile AYNI tanım, kural 7): ana + HIP-3 (marginSummary) + spot USDC; spot okunamazsa alan eksik (trader düşmez)
        hesap_toplam = account + spot_usdc(client, address)
    except Exception:  # noqa: BLE001 - spot okuma hatası yalnız `hesap` alanını eksik bırakır (K-14: tek eksik trader'ı düşürmez)
        hesap_toplam = None
    veri_durumu, veri_durumu_neden = veri_durumu_belirle(account, paper, paper_v3, len(eksik_mum), sorted(open_copy_coins(actions) - set(marks)),
                                                           sum(1 for e in eksik_mum if e.get('onbellek')))
    trader = {**{k: v for k, v in row.items() if k != 'tarz'}, 'tarz': style, 'veri_zamani': iso(now), 'gecerli': True,
              'hesap_degeri_toplam': hesap_toplam,
              'veri_durumu': veri_durumu, 'veri_durumu_neden': veri_durumu_neden,
              'mum_eksik': {'hedef': len(eksik_mum), 'onbellekten': sum(1 for e in eksik_mum if e.get('onbellek'))},
              'kapi': gate_result(root, address), 'saglik': light,
              'form': {'skor': ret30 / volatility if volatility > 0 and math.isfinite(volatility) else 0.0,
                       'getiri_30g': ret30, 'getiri_90g': float(recent.iloc[-1] - recent.iloc[0]) if len(recent) else 0.0},
              'hesap_degeri': account, 'pozisyonlar': positions, 'son_islem': last_trade,
              'egri': [[str(day.date()), float(value)] for day, value in recent.items()], 'sanal_kopya': paper,
              'sanal_kopya_v2': paper_v2, 'sanal_kopya_v3': paper_v3}
    if row.get('kol') in oda_risk.YONSUZ_KOLLAR:
        trader['yonsuz_bayrak'] = yonsuz_guncelle(client, address, saved, states, fills, now)
    if row.get('kol') == 'oda':
        trader['veri_kalitesi'] = {'mutabakat': mutabakat_raporu(fills, states, now, onceki_hesap_degeri=saved.get('son_hesap_degeri'), hesap_degeri=account)}
    # İlk 11 haftalık form ham alanları (tek hesap yeri: ilk11_alanlar); hata trader'ı düşürmez, açıkça yazılır.
    try:
        trader['ilk11_form_ham'] = ilk11_alanlar.form_ham_30g(fills, saved['portfolio'], trader['hesap_degeri_toplam'], paper_v3, now)
    except Exception as error:  # noqa: BLE001 - form alanı hatası izleme okumasını düşürmesin; `hata` alanı Pazar işinde geçersizlik nedenidir
        trader['ilk11_form_ham'] = {'hata': data_error_reason(error)}
    perp_zamanlari = [int(f['time']) for f in perp_fills(fills)]
    trader['son_perp_dolum'] = at_ms(max(perp_zamanlari)) if perp_zamanlari else None    # `bu_pazar_aktif` (as_of − 7 g içinde perp dolumu) girdisi
    trader['ilk11_gecerli_saat'] = gecerli_saat_say(saved, row, now)
    saved['son_hesap_degeri'] = account
    saved['son_trader'] = trader
    return trader


OLAY_YAYIN_SINIRI = 200      # durum.json.olaylar toplam üst sınırı; trader'lara adil paylaştırılır; taşanlar olay_tasan.jsonl -> veri dalı arşivi


def olay_paylari(sayim: dict[str, int], sinir: int = OLAY_YAYIN_SINIRI) -> dict[str, int]:
    """Adil pay (su doldurma): toplam <= ``sinir``; kotadan az olayı olan trader'ın hepsi yayında, artan kota çok olay üretenlere eşit bölünür (kalan tek tek kimlik sırasıyla)."""
    pay = {k: 0 for k in sayim}
    kalan_ler = sorted(k for k, n in sayim.items() if n > 0)
    kalan = sinir
    while kalan_ler and kalan > 0:
        esit, artik = divmod(kalan, len(kalan_ler))
        kucuk = [k for k in kalan_ler if sayim[k] - pay[k] <= esit]
        if kucuk:                                                    # tam sığanlar: hepsi alınır, kota artar
            for k in kucuk:
                kalan -= sayim[k] - pay[k]
                pay[k] = sayim[k]
            kalan_ler = [k for k in kalan_ler if k not in kucuk]
            continue
        for i, k in enumerate(kalan_ler):                            # hepsi esit'ten büyük: eşit böl, artık kimlik sırasıyla +1
            pay[k] += esit + (1 if i < artik else 0)
        break
    return pay


def olay_yayin_ayir(tum: list[dict], sinir: int = OLAY_YAYIN_SINIRI) -> tuple[list[dict], list[dict]]:
    """``tum`` (yeniden eskiye) -> (yayımlanan, taşan); her trader'ın EN YENİ ``olay_paylari`` kadar olayı yayımlanır. İkisi de yeniden eskiye; birleşimleri ``tum``."""
    sayim: dict[str, int] = {}
    for olay in tum:
        sayim[olay['trader']] = sayim.get(olay['trader'], 0) + 1
    hak, goruldu = olay_paylari(sayim, sinir), {k: 0 for k in sayim}
    yayin, tasan = [], []
    for olay in tum:
        goruldu[olay['trader']] += 1
        (yayin if goruldu[olay['trader']] <= hak[olay['trader']] else tasan).append(olay)
    return yayin, tasan


def olay_ozeti(tum: list[dict], yayimlanan: list[dict]) -> dict:
    """``durum.json.olay_ozeti`` (v1.17): yayımlanan pencere tüm olayların YALNIZ bir parçasıysa tüketici bunu görsün. ``trader_basina``: TÜM olaylar (taşanlar dahil) trader başına adet."""
    sayim: dict[str, int] = {}
    for olay in tum:
        sayim[olay['trader']] = sayim.get(olay['trader'], 0) + 1
    return {'toplam': len(tum), 'yayimlanan': len(yayimlanan), 'tasan': len(tum) - len(yayimlanan), 'trader_basina': dict(sorted(sayim.items()))}


def uc_ozeti(simdi: dict, once: dict) -> str:
    """Bir trader için uç türü başına istek / ağırlık farkı (ör. ``candleSnapshot 40/1800, userFillsByTime 5/120``); en ağırdan hafife."""
    fark = {k: (v[0] - once.get(k, [0, 0])[0], v[1] - once.get(k, [0, 0])[1]) for k, v in simdi.items()}
    return ', '.join(f'{k} {i}/{w}' for k, (i, w) in sorted(fark.items(), key=lambda kv: -kv[1][1]) if i) or '—'


def run(root: Path, output: Path, client=None, now=None, symbols=None, liste: Path | None = None) -> dict:
    now = timestamp(now or datetime.now(UTC))
    client = client or PublicClient(limiter=RateLimiter())
    watchlist = load_list(liste or root / 'copytrade/izleme_listesi.yaml')
    state = read_json(output / 'motor.json', {'surum': 1, 'traderlar': {}, 'olaylar': {}})
    if state.get('surum') != 1:
        raise ValueError('Desteklenmeyen motor arşivi sürümü.')
    # v1.2 changes trade-event ids from a fill hash to trader/oid/type.  Keep
    # light events, then rebuild all trade events from retained public fills.
    traders = []
    all_events = {key: value for key, value in state['olaylar'].items() if value.get('tur') == 'isik'}
    state['olaylar'] = all_events
    dexes: list[str] = []
    if watchlist:
        dexes = perp_dex_names(client.info({'type': 'perpDexs'}))
    failed = 0
    for row in watchlist:
        retained = state['traderlar'].get(row['id'])
        if retained and (retained['adres'] != row['adres'].lower() or retained['t0'] != iso(timestamp(row['t0']))):
            raise ValueError(f"{row['id']}: adres/t0 değiştirilemez; yeni izleme için yeni id kullanın.")
        try:
            _u0 = {k: list(v) for k, v in getattr(client, 'uclar', {}).items()}
            _t_basla, _i0, _a0, _w0 = time.monotonic(), dict(getattr(client, 'stats', {})), getattr(getattr(client, 'limiter', None), 'weight_used', 0), getattr(getattr(client, 'limiter', None), 'waited', 0.0)
            traders.append(update_trader(root, client, dexes, state, all_events, row, now, symbols))
            _i1 = getattr(client, 'stats', {})                   # tanı: süre API mi, hesap mı (istek / 429 / ağırlık / hız sınırı beklemesi)
            print(f"{row['id']}: okuma süresi {time.monotonic() - _t_basla:.0f} sn, istek {_i1.get('istek', 0) - _i0.get('istek', 0)}, 429 {_i1.get('429', 0) - _i0.get('429', 0)}, "
                  f"ağırlık {getattr(getattr(client, 'limiter', None), 'weight_used', 0) - _a0}, hız sınırı bekleme {getattr(getattr(client, 'limiter', None), 'waited', 0.0) - _w0:.0f} sn, "
                  f"uçlar (istek/ağırlık): {uc_ozeti(getattr(client, 'uclar', {}), _u0)}")
        except Exception as error:
            failed += 1
            print(f"{row['id']}: veri hatası: {data_error_reason(error)}")
            retained = state['traderlar'].get(row['id'], {})
            previous = retained.get('son_trader')
            if previous:
                traders.append(with_data_error(previous, error))
                for event in retained.get('son_olaylar', []):
                    all_events[event['id']] = event
            else:
                traders.append(unavailable_trader(root, row, error))
    if watchlist and failed == len(watchlist):
        raise RuntimeError('Tüm trader verileri hatalı; önceki durum yayımlanmadı.')
    rules = load_rules()
    tum_olaylar = sorted(all_events.values(), key=lambda e: (e['zaman'], e['id']), reverse=True)
    yayimlanan_olaylar, tasan_olaylar = olay_yayin_ayir(tum_olaylar)
    result = {'surum': 1, 'uretildi': iso(now), 'kaynak': 'hyperliquid', 'traderlar': [durum_icin_kirp(bayat_isle(t, now, rules), now, rules) for t in traders],
              'kasa_egri': {'oda': kasa_egrisi(traders, 'oda'), 'kontrol': kasa_egrisi(traders, 'kontrol')},
              'olaylar': yayimlanan_olaylar,
              'olay_ozeti': olay_ozeti(tum_olaylar, yayimlanan_olaylar)}
    oda_uyeleri = [t for t in traders if t.get('kol') == 'oda']
    if oda_uyeleri:
        result['kalabalik'] = {**oda_risk.kalabalik([t for t in oda_uyeleri if t.get('gecerli') and t.get('hesap_degeri')]), 'zaman': iso(now)}
    # ayrı; yalnız rapor). Tazelik kontrolü kasıtlı olarak burada değil (bkz. saglik_hatti modül docstring'i).
    # Boş izleme listesinde (ağ hiç kullanılmayan sözleşme testi) eklenmez — kalabalik alanıyla aynı desen.
    if traders:
        oda_olcu = saglik_hatti.olc(result)
        result['saglik_hatti'] = {**oda_olcu, **saglik_hatti.kontrol(oda_olcu)}
    # Serialize both before replacing either; API/validation/NaN errors leave the archive untouched.
    payloads = {name: json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
                for name, value in [('motor.json', state), ('durum.json', result)]}
    # A4-2: yayın penceresinden taşan olaylar (eskiden sessizce atılıyordu) kalıcı arşive eklenmek üzere JSONL olarak yazılır (.github/scripts/olay_arsivle.py).
    payloads['olay_tasan.jsonl'] = ''.join(json.dumps(e, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n' for e in tasan_olaylar)
    output.mkdir(parents=True, exist_ok=True)
    for name, value in payloads.items():
        temporary = output / (name + '.tmp')
        temporary.write_text(value, encoding='utf-8')
        temporary.replace(output / name)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, default=Path('izleme'))
    parser.add_argument('--liste', type=Path, default=None, help='izleme listesi YAML (varsayılan: <root>/copytrade/izleme_listesi.yaml)')
    args = parser.parse_args()
    # Only a public symbol catalog; blocked access remains explicitly "bilinmiyor".
    symbols = None
    if load_list(args.liste or args.root / 'copytrade/izleme_listesi.yaml'):
        args.output.mkdir(parents=True, exist_ok=True)
        symbols, _ = write_binance_universe(args.output)
    result = run(args.root, args.output, symbols=symbols, liste=args.liste)
    print(f"İzleme: {len(result['traderlar'])} trader, {len(result['olaylar'])} olay.")


if __name__ == '__main__':
    main()
