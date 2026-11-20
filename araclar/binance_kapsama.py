"""Binance kapsama + gecikme analizi (yalniz okur, bota dokunmaz).
Kullanim: python araclar/binance_kapsama.py <kayit_jsonl...> --exchangeinfo bx.json
bx.json: 'symbols' listeli exchangeInfo dokumu (alanlar: symbol,status,contractType)."""
import json, sys, statistics as st, collections

def main(a):
    bx = a.index('--exchangeinfo'); info = json.load(open(a[bx + 1])); dosyalar = a[:bx]
    act = {s['symbol'] for s in info['symbols']
           if s['status'] == 'TRADING' and s['contractType'] in ('PERPETUAL', 'TRADIFI_PERPETUAL')}
    E = []
    for f in dosyalar:
        for l in open(f):
            try: o = json.loads(l)
            except ValueError: continue
            if o.get('olay') == 'emir' and o.get('durum') == 'dolu': E.append(o)
    def sembol(c):
        b = c.split(':')[-1]
        for n in (b + 'USDT', '1000' + b[1:] + 'USDT' if b.startswith('k') else '', '1000' + b + 'USDT'):
            if n in act: return n
    k = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for e in E:
        x = k['var' if sembol(e['coin']) else 'yok']; x[0] += 1; x[1] += e['usd_dolan']; x[2] += e['pnl_usd']
    print({a: (v[0], round(v[1]), round(v[2], 2)) for a, v in k.items()})
    for ad, fn in (('toplam', lambda e: e['dolum_ms'] - e['trader_dolum_ms']),
                   ('gorme', lambda e: e['gorme_ms'] - e['trader_dolum_ms'])):
        v = sorted(fn(e) for e in E if e['kaynak'] in ('userFills', 'trades'))
        print(ad, 'medyan', st.median(v), 'p90', v[int(len(v) * .9)])
main(sys.argv[1:])
