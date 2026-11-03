"""Kopya hesap v4 = v3 + H5 risk sınırları (docs: lider görevi 2026-11-03; AGENTS kural 6/7).

v3 ile AYNI model (`defter.copy_ledger`, sabit tutar açılış, trader'ın eklemesine oranlı ekleme, aynı maliyet / funding / tasfiye / aşamalı çıkış) — artı `kurallar.yaml`
`risk_dry_run` sınırları (H5 dinleyici defteriyle AYNI sayılar, kodda yeniden yazılmaz):
- emir başına artış ≤ `emir_tavan_usd`;
- kopyanın trader başına brüt pozisyonu ≤ `trader_tavan_usd`;
- başlangıç teminatı (Σ notional / HL azami kaldıracı) ≤ kopya özsermayesi (HL azami kaldıracı canlı `meta`dan gelir, `azami_kaldirac`; yoksa bu sınır uygulanmaz).
Sınır aşılırsa ekleme KIRPILIR ve neden `risk_kirpma`ya yazılır. v3 silinmez / değişmez: v4 `sanal_kopya_v4` olarak v3'ün yanında yayımlanır (kural 6). Birim: 1.000 $ sanal kopya.
`hesapla` v3 gövdesini kullanır (`kopya_v3.hesapla(risk_limitleri=…, surum='v4')`): hesap ikinci bir yerde yazılmaz.
"""
from __future__ import annotations

import pandas as pd

from copytrade import kopya_v3
from copytrade.kurallar import load_rules


def limitler(rules: dict | None = None, azami_kaldirac: dict[str, float] | None = None) -> dict:
    """`kurallar.yaml` `risk_dry_run` bloğundan v4 sınırları (tek kaynak). Birim: $ (referans kasa ölçeği)."""
    r = (rules or load_rules())["risk_dry_run"]
    return {"referans_kasa_usd": float(r["referans_kasa_usd"]), "emir_tavan_usd": float(r["emir_tavan_usd"]), "trader_tavan_usd": float(r["trader_tavan_usd"]),
            "azami_kaldirac": {str(c): float(v) for c, v in (azami_kaldirac or {}).items() if v}}


def hesapla(fills: list[dict], saatlik: dict[str, list[dict]], isaret: dict[str, list[dict]], yurutme: dict[str, dict[int, float]], funding: list[dict],
            t0: pd.Timestamp, now: pd.Timestamp, delay: int, style: str, rules: dict | None = None, azami_kaldirac: dict[str, float] | None = None) -> dict:
    """v4 sanal kopya sonucu: v3 alanları + `limitler`, `risk_kirpma` (kırpılan dolumlar), `acik_pozisyonlar` (açık kopya pozisyonları), `tepe_pozisyon_usd`, `tepe_brut_usd`."""
    rules = rules or load_rules()
    lim = limitler(rules, azami_kaldirac)
    sonuc = kopya_v3.hesapla(fills, saatlik, isaret, yurutme, funding, t0, now, delay, style, rules, risk_limitleri=lim, surum='v4')
    if sonuc.get('durum') == 'hesaplanamadi':
        return sonuc
    azami = lim['azami_kaldirac']
    acik = []
    for p in sonuc.get('acik_pozisyonlar') or []:
        maks = azami.get(p['coin'])
        teminat = None if p['buyukluk_usd'] is None or not maks else p['buyukluk_usd'] / maks
        acik.append({**p, 'azami_kaldirac': maks, 'teminat_usd': teminat,
                     'kz_oran': None if teminat in (None, 0) or p['kz_usd'] is None else p['kz_usd'] / teminat,
                     'acilis': None if p.get('acilis_ms') is None else kopya_v3.iso_ms(p['acilis_ms'])})
    kirpma = sonuc.get('risk_kirpma') or []
    sonuc.update({'acik_pozisyonlar': acik,
                  'limitler': {'emir_tavan_usd': lim['emir_tavan_usd'], 'trader_tavan_usd': lim['trader_tavan_usd'], 'referans_kasa_usd': lim['referans_kasa_usd'],
                               'azami_kaldirac_uygulandi': bool(azami)},
                  'risk_kirpma': [{'coin': k['coin'], 'zaman': kopya_v3.iso_ms(k['zaman_ms']), 'istenen_usd': k['istenen_usd'], 'uygulanan_usd': k['uygulanan_usd'], 'neden': k['neden']}
                                  for k in kirpma[-50:]],
                  'risk_kirpma_toplam': len(kirpma),
                  'risk_kirpma_nedenler': {n: sum(1 for k in kirpma if k['neden'] == n) for n in sorted({k['neden'] for k in kirpma})}})
    return sonuc
