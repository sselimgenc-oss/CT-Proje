"""Kopya hesap v3.
AGENTS.md kural 6).

`defter.copy_ledger` (kural 7) — yalnız `tutar_egrisi` parametresiyle.

Çapraz teminat tasfiyesi ve (E3) aşamalı zarar_kes/kar_al da AYNI motorda, gerçek (yol bağımlı) pozisyon üzerinde
çalışır (`defter._risk_denetle`/`_zorla_kapat`) — `golge.py _denetle_ve_kapat`'ın AYNI dondurulmuş eşikleriyle
(`golge_likidasyon_esigi`, `golge_v2`, DEĞİŞTİRİLMEDİ), ama `golge.v2_cikislari`'nin sentetik-dolum-enjekte-etme
desenini KULLANMAZ: proportional `scale`'in sabit tutarda karşılığı yok (yol bağımlı), o yüzden risk katmanı
doğrudan `copy_ledger`'ın gerçek `held`/`entry` durumuna kodlandı.

**Kapsam dışı (ayrı GOREV alt maddeleri, bu PR'ın kapsamında değil):** pozisyon tavanı (`golge_pozisyon_tavan_carpani`

**Gözlem (test sırasında bulundu, davranış DOĞRU — düzeltme değil):** sabit tutar küçük olduğundan (eğri $1.000'da
~%2 açar, $10.000 tavanında bile ~%15), tek bir pozisyonun TEK BAŞINA çapraz teminat eşiğine (−1,0) ya da intraday
zarar_kes'e (−0,50) gerçek fiyat hareketiyle ulaşması pratikte neredeyse imkânsızdır — küçük, çeşitlendirilmiş
pozisyonların hesabı tek başına batıramaması tasarımın kendisidir (testlerde eşik yalnız mekanizmayı göstermek için
gevşetildi, bkz. `tests/test_kopya_v3.py`). Gerçek veride bu katmanın asıl devreye girme yolu, aynı coin'e art arda
"""

from __future__ import annotations

import math

import pandas as pd

from copytrade.defter import FundingRates, Market, copy_ledger, sabit_tutar_egrisi
from copytrade.kopya_v2 import iso_ms
from copytrade.kurallar import load_rules

MINUTE = 60_000
BASE_USD = 1000.0


def hesapla(fills: list[dict], saatlik: dict[str, list[dict]], isaret: dict[str, list[dict]],
            yurutme: dict[str, dict[int, float]], funding: list[dict],
            t0: pd.Timestamp, now: pd.Timestamp, delay: int, style: str, rules: dict | None = None) -> dict:
    """v3 sanal kopya sonucu (1.000 $ ölçeğinde, v1/v2 ile aynı ölçek). Girdiler `kopya_v2.hesapla` ile aynı anlamda;
    ``serisi`` (trader hesap değeri serisi) burada gerekmez — sabit tutar trader'ın hesabına bakmaz, yalnız kopyanın
    KENDİ değerine; ``style`` E3'ün aşamalı zarar_kes/kar_al eşiği için gerekli (intraday/swing)."""
    rules = rules or load_rules()
    t0_ms, now_ms = int(t0.value // 1_000_000), int(now.value // 1_000_000)
    base = {'surum': 'v3', 'baslangic_usd': BASE_USD, 'gecikme_dk': delay, 't0': str(t0.date())}
    annotated = []
    for fill in fills:
        target = math.ceil((int(fill['time']) + delay * MINUTE) / MINUTE) * MINUTE
        price = yurutme.get(str(fill['coin']), {}).get(target)
        annotated.append(dict(fill, _execution_time=target, _execution_price=price) if price else dict(fill))
    candles = {coin: sorted(saatlik.get(coin, []) + isaret.get(coin, []), key=lambda c: c['t'])
               for coin in {*saatlik, *isaret}}
    ledger = copy_ledger(annotated, Market(candles), None, delay, t0_ms, now_ms, FundingRates(funding), rules,
                         daily=True, tutar_egrisi=sabit_tutar_egrisi(rules), base_usd=BASE_USD, style=style,
                         islem_kaydi=True)
    if ledger.get('net') is None:
        return {**base, 'durum': 'hesaplanamadi', 'neden': 'yürütülebilir dolum yok'}
    days = pd.date_range(t0.normalize(), now.normalize(), freq='1D')
    net = pd.Series(0.0, index=days)
    if len(ledger['daily']):
        net = net.add(ledger['daily'].reindex(days, fill_value=0.0), fill_value=0.0)
    equity = BASE_USD * (1 + net.cumsum())
    kapanis_nedenleri = [{'coin': e['coin'], 'neden': e['neden'], 'zaman': iso_ms(e['zaman_ms'])}
                        for e in ledger['olaylar']]
    # İlk 11 `paper_sonuclari` girdisi (yalnız raporlama; bakiye/getiri aşağıda değişmeden hesaplanır): kapanan kopya işlemleri, 1.000 $ ölçeğinde.
    kapanan_islemler = [{'coin': t['coin'], 'acilis': iso_ms(t['acilis_ms']), 'kapanis': iso_ms(t['kapanis_ms']),
                         'sonuc_usd': t['sonuc_usd'], 'getiri': t['sonuc_usd'] / t['acilan_usd'] if t['acilan_usd'] else None,
                         'neden': t['neden'], 'gecerli': t['gecerli']} for t in ledger['islemler']]
    liquidations = [e['zaman_ms'] for e in ledger['olaylar'] if e.get('neden') == 'likidasyon']
    when, source = (min(liquidations), 'mum') if liquidations else (None, None)
    broke = equity[equity <= 0]
    if when is None and len(broke):
        when, source = int(broke.index[0].value // 1_000_000), 'gunluk_ozsermaye'
    if when is not None:                              # tasfiye: bakiye 0'da kalır, sonrası sermaye yok
        day = pd.Timestamp(int(when), unit='ms', tz='UTC').normalize()
        equity[equity.index >= day] = 0.0
    equity = equity.clip(lower=0.0)
    balance = float(equity.iloc[-1]) if len(equity) else BASE_USD
    base_series = pd.concat([pd.Series([BASE_USD]), equity.reset_index(drop=True)])
    drawdown = float((1 - base_series / base_series.cummax()).max())
    tasfiye_zamani = iso_ms(when) if when is not None else None
    return {**base, 'bakiye_usd': balance, 'getiri': balance / BASE_USD - 1, 'dusus': drawdown,
            'egri': [[str(day.date()), float(value)] for day, value in equity.items()],
            'gerceklesen': ledger['realized'] + ledger['funding'], 'acik': ledger['unrealized_end'],
            'toplam': ledger['net'], 'funding': ledger['funding'], 'maliyet': ledger['costs'],
            'fiyatsiz_eylem': int(ledger.get('missing', 0)), 'tasfiye': when is not None,
            'tasfiye_zamani': tasfiye_zamani, 'tasfiye_kaynagi': source,
            'kapanis_nedenleri': kapanis_nedenleri, 'kapanan_islemler': kapanan_islemler}
