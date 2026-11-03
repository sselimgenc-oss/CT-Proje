"""H1 — gecikme–kâr ölçümü (docs/GOREV_H1_GECIKME_KAR.md). YALNIZ ölçüm: seçim, kapı, eşik ve izleme çıktısı değişmez.

Aynı trader dolumları için v3 kopya netini gecikme başına (0 = anlık, 1, 5, 30, 120 dk) yan yana hesaplar. Hesap yalnız
`kopya_v3.hesapla` → `defter.copy_ledger` motorundadır (kural 7); burada yalnız veri çekimi, gecikme döngüsü ve tablo vardır.
Veri bir kez çekilir (dolum, funding, saatlik mum, işaret); yürütme fiyatı için 1 dk mumlar coin başına bir kez okunur.

Birimler: getiri ORAN (0,012 = %1,2); tutar 1.000 $ sanal kopya ölçeği; zaman UTC.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from copytrade import izleme_motoru as im
from copytrade import kopya_v2, kopya_v3
from copytrade.izleme_liste import load_list
from copytrade.kurallar import load_rules
from copytrade.olcut import perp_fills
from copytrade.tarama import PublicClient, RateLimiter

SURUM = 'h1-v1'
GECIKMELER = (0, 1, 5, 30, 120)          # dk; 0 = anlık (dolum fiyatı + taker + kayma)
DAKIKA_PENCERESI_DK = 4800               # 1 dk mum erişimi (~4999 dk) içinde kalan pencere: bütün gecikmeler gerçek 1 dk açılışı
SUTUNLAR = ('net', 'islem', 'fiyatsiz', 'bekleyen', 'yaklasik')


class MumOnbellegi:
    """Aynı (coin, aralık) için kapsayan aralık bir kez okunur; sonraki gecikmeler (daha geç başlangıç) bellekten süzülür."""

    def __init__(self, client) -> None:
        self.client, self.rows, self.cagri = client, {}, 0

    def candles(self, coin: str, start_ms: int, end_ms: int, interval: str = '1m') -> list[dict]:
        key = (coin, interval)
        kayit = self.rows.get(key)
        if kayit is None or start_ms < kayit[0] or end_ms > kayit[1]:
            self.cagri += 1
            kayit = (start_ms, end_ms, self.client.candles(coin, start_ms, end_ms, interval=interval))
            self.rows[key] = kayit
        return [c for c in kayit[2] if start_ms <= int(c['t']) <= end_ms]


def _sonlu(deger) -> float | None:
    return float(deger) if isinstance(deger, (int, float)) and math.isfinite(deger) else None


def gecikme_sonucu(v3: dict, bekleyen: int, yaklasik: int) -> dict:
    """Bir gecikmenin v3 çıktısından tablo hücresi. Hesaplanamayan: ``net`` None (sıfır SAYILMAZ)."""
    if v3.get('durum') == 'hesaplanamadi':
        return {'net': None, 'islem': 0, 'fiyatsiz': int(v3.get('fiyatsiz_eylem', 0)), 'bekleyen': bekleyen, 'yaklasik': yaklasik,
                'tasfiye': False, 'neden': v3.get('neden')}
    return {'net': _sonlu(v3.get('getiri')), 'islem': len(v3.get('kapanan_islemler', [])),
            'fiyatsiz': int(v3.get('fiyatsiz_eylem', 0)), 'bekleyen': bekleyen, 'yaklasik': yaklasik,
            'tasfiye': bool(v3.get('tasfiye')), 'neden': None}


def olc(fills: list[dict], saatlik: dict, isaret: dict, yurutme: dict[int, dict], funding: list[dict],
        t0: pd.Timestamp, now: pd.Timestamp, style: str, rules: dict, gecikmeler=GECIKMELER,
        yaklasik: dict[int, int] | None = None) -> dict[int, dict]:
    """Aynı ``fills`` için gecikme başına v3 sonucu. ``yurutme[gecikme]`` = ``{coin: {hedef_ms: açılış}}`` (anlıkta gerekmez).
    ``bekleyen``: yürütme zamanı henüz gelmemiş dolum sayısı (fiyatsız DEĞİL, B17/A4-3b)."""
    now_ms = int(now.value // 1_000_000)
    sonuc = {}
    for gecikme in gecikmeler:
        v3 = kopya_v3.hesapla(fills, saatlik, isaret, yurutme.get(gecikme, {}), funding, t0, now, gecikme, style, rules)
        bekleyen = sum(1 for f in fills if gecikme > 0 and kopya_v3.hedef_ms(int(f['time']), gecikme) > now_ms)
        sonuc[gecikme] = gecikme_sonucu(v3, bekleyen, (yaklasik or {}).get(gecikme, 0))
    return sonuc


def trader_satiri(ident: str, adres: str, style: str, t0: pd.Timestamp, sonuc: dict[int, dict], mevcut_gecikme: int,
                  dolum: int) -> dict:
    return {'id': ident, 'adres': adres, 'tarz': style, 't0': im.iso(t0), 'dolum': dolum, 'mevcut_gecikme_dk': mevcut_gecikme,
            'mevcut_net': (sonuc.get(mevcut_gecikme) or {}).get('net'),
            'gecikmeler': {str(g): s for g, s in sonuc.items()}}


def _istatistik(degerler: list[float]) -> dict | None:
    return {'min': min(degerler), 'medyan': statistics.median(degerler), 'maks': max(degerler)} if degerler else None


def ozet(satirlar: list[dict]) -> dict:
    """Anlıkta kazanan/kaybeden trader sayısı ve anlık − 30 dk net farkı (oran puanı). Net None olan trader sayılmaz."""
    anlik = [(s['id'], s['gecikmeler'].get('0', {}).get('net')) for s in satirlar]
    gecerli = [(i, n) for i, n in anlik if n is not None]
    fark = []
    for s in satirlar:
        a, b = s['gecikmeler'].get('0', {}).get('net'), s['gecikmeler'].get('30', {}).get('net')
        if a is not None and b is not None:
            s['fark_anlik_30dk'] = a - b
            fark.append(a - b)
        else:
            s['fark_anlik_30dk'] = None
    return {'trader': len(satirlar), 'anlik_hesaplanan': len(gecerli), 'anlik_hesaplanamayan': len(satirlar) - len(gecerli),
            'anlik_kazanan': sum(1 for _, n in gecerli if n > 0), 'anlik_kaybeden': sum(1 for _, n in gecerli if n < 0),
            'anlik_sifir': sum(1 for _, n in gecerli if n == 0),
            'fark_anlik_30dk': _istatistik(fark), 'fark_anlik_30dk_ortalama': (sum(fark) / len(fark)) if fark else None,
            'anlik_30dk_karsilastirilan': len(fark)}


def tablo_md(satirlar: list[dict], ozet_: dict, gecikmeler=GECIKMELER) -> str:
    yuzde = lambda v: '—' if v is None else f'{v * 100:+.2f}%'
    baslik = ['id', 'tarz', 'dolum'] + [f'net {g} dk' for g in gecikmeler] + ['işlem (0/30)', 'fiyatsız (0/1/5/30/120)', 'fark 0−30']
    out = ['| ' + ' | '.join(baslik) + ' |', '|' + '---|' * len(baslik)]
    for s in satirlar:
        g = s['gecikmeler']
        hucre = lambda k, a: (g.get(str(k)) or {}).get(a, '—')
        out.append('| ' + ' | '.join([s['id'], s['tarz'], str(s['dolum'])] + [yuzde((g.get(str(k)) or {}).get('net')) for k in gecikmeler]
                                      + [f"{hucre(0, 'islem')}/{hucre(30, 'islem')}", '/'.join(str(hucre(k, 'fiyatsiz')) for k in gecikmeler),
                                         yuzde(s.get('fark_anlik_30dk'))]) + ' |')
    out += ['', f"Anlıkta kazanan {ozet_['anlik_kazanan']}, kaybeden {ozet_['anlik_kaybeden']}, sıfır {ozet_['anlik_sifir']}, "
                f"hesaplanamayan {ozet_['anlik_hesaplanamayan']} (trader {ozet_['trader']}).",
            f"Anlık − 30 dk net farkı: {ozet_['fark_anlik_30dk'] and {k: yuzde(v) for k, v in ozet_['fark_anlik_30dk'].items()}}, "
            f"ortalama {yuzde(ozet_['fark_anlik_30dk_ortalama'])} ({ozet_['anlik_30dk_karsilastirilan']} trader)."]
    return '\n'.join(out) + '\n'


def olc_trader(root: Path, client, row: dict, now: pd.Timestamp, pencere: str, rules: dict) -> dict:
    """Bir izleme satırı için canlı okuma + ölçüm. ``pencere``: 'dakika' (son ~80 saat; bütün gecikmeler gerçek 1 dk açılışı) |
    'tam' (t0'dan; 1 dk mum erişimi dışındaki eski dolumlar saatlik açılışla YAKLAŞIK: kısa gecikmeler birbirinden ayrışmaz)."""
    address, t0 = row['adres'], im.timestamp(row['t0'])
    now_ms = im.millis(now)
    if pencere == 'dakika':
        t0 = max(t0, now - pd.Timedelta(minutes=DAKIKA_PENCERESI_DK))
    elif pencere != 'tam':
        raise ValueError(f'bilinmeyen pencere: {pencere}')
    fresh = client.fills(address, min(im.millis(t0), now_ms - 90 * im.DAY))
    if not isinstance(fresh, list):
        raise ValueError('Geçersiz dolum yanıtı.')
    fills = im.merge_rows([], [f for f in fresh if int(f['time']) <= now_ms])
    copy_fills = [f for f in perp_fills(fills) if int(f['time']) >= im.millis(t0)]
    funding = im.funding_since(client, address, im.millis(t0), now_ms)
    actions = im.copy_actions(copy_fills)
    isaret = im.mark_candles(client, actions, now_ms)
    onbellek = MumOnbellegi(client)
    saatlik = kopya_v2.saatlik_mumlar(onbellek, {}, copy_fills, im.open_copy_coins(actions), now_ms)
    yurutme: dict[int, dict] = {}
    yaklasik: dict[int, int] = {}
    for gecikme in GECIKMELER:
        if gecikme == 0:
            continue
        cache: dict = {}
        mumlar, _ = im.execution_candles(onbellek, copy_fills, cache, now_ms, gecikme)
        yurutme[gecikme] = {coin: {int(c['t']): float(c['o']) for c in rows} for coin, rows in mumlar.items()}
        yaklasik[gecikme] = sum(1 for rows in cache.values() for v in rows.values() if im.cached_candle(v)[1])
    style = im.resolve_style(root, row)
    sonuc = olc(copy_fills, saatlik, isaret, yurutme, funding, t0, now, style, rules, yaklasik=yaklasik)
    return trader_satiri(row['id'], address.lower(), style, t0, sonuc, im.delay_for_style(style, rules), len(copy_fills))


def calistir(root: Path, liste: Path, idler: list[str] | None, pencere: str, now: pd.Timestamp, client=None,
             taker: float | None = None, kayma: float | None = None) -> dict:
    rules = dict(load_rules())
    if taker is not None:
        rules['maliyet_taker'] = taker
    if kayma is not None:
        rules['maliyet_kayma'] = kayma
    satirlar_liste = load_list(liste)
    if idler:
        eksik = [i for i in idler if i not in {r['id'] for r in satirlar_liste}]
        if eksik:
            raise ValueError(f'listede olmayan kimlik: {eksik}')
        satirlar_liste = [r for r in satirlar_liste if r['id'] in idler]
    client = client or PublicClient(limiter=RateLimiter())
    satirlar, hatalar = [], []
    for row in satirlar_liste:
        try:
            satirlar.append(olc_trader(root, client, row, now, pencere, rules))
        except Exception as error:  # noqa: BLE001 - tek trader'ın okuma hatası ölçümü düşürmez; açıkça yazılır
            hatalar.append({'id': row['id'], 'hata': im.data_error_reason(error)})
            print(f"{row['id']}: veri hatası: {im.data_error_reason(error)}")
    ozet_ = ozet(satirlar)
    return {'surum': SURUM, 'uretildi': im.iso(now), 'pencere': pencere, 'gecikmeler_dk': list(GECIKMELER),
            'maliyet': {'taker': float(rules['maliyet_taker']), 'kayma': float(rules['maliyet_kayma'])},
            'traderlar': satirlar, 'hatalar': hatalar, 'ozet': ozet_}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('.'))
    ap.add_argument('--liste', type=Path, default=None)
    ap.add_argument('--idler', default='', help='virgülle ayrılmış izleme kimlikleri (boş = listedeki hepsi)')
    ap.add_argument('--pencere', choices=['dakika', 'tam'], default='dakika')
    ap.add_argument('--taker', type=float, default=None, help='taker oranı (varsayılan kurallar.yaml maliyet_taker)')
    ap.add_argument('--kayma', type=float, default=None, help='kayma oranı (varsayılan kurallar.yaml maliyet_kayma)')
    ap.add_argument('--cikti', type=Path, default=Path('gecikme_kar'))
    args = ap.parse_args(argv)
    now = im.timestamp(datetime.now(UTC))
    sonuc = calistir(args.root, args.liste or args.root / 'copytrade/izleme_listesi.yaml',
                     [i for i in args.idler.split(',') if i], args.pencere, now, taker=args.taker, kayma=args.kayma)
    args.cikti.mkdir(parents=True, exist_ok=True)
    (args.cikti / 'gecikme_kar.json').write_text(json.dumps(sonuc, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    md = tablo_md(sonuc['traderlar'], sonuc['ozet'])
    (args.cikti / 'gecikme_kar.md').write_text(md, encoding='utf-8')
    print(md)


if __name__ == '__main__':
    main()
