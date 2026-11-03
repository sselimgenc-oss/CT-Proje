"""Kopya hesap v4 (v3 + H5 risk sınırları) için elle hesaplanmış altın örnekler. Sınır sayıları `kurallar.yaml` `risk_dry_run`dan okunur (testte de)."""
import pandas as pd
import pytest

from copytrade import izleme_motoru as m
from copytrade import kopya_v3, kopya_v4
from copytrade.defter import sabit_tutar_egrisi
from copytrade.kurallar import load_rules

T0 = pd.Timestamp('2026-10-27T00:00:00Z')
NOW = pd.Timestamp('2026-10-27T12:00:00Z')
ms = lambda s: m.millis(m.timestamp(s))                     # noqa: E731
RULES = load_rules()
RISK = RULES['risk_dry_run']
EMIR, TRADER = float(RISK['emir_tavan_usd']), float(RISK['trader_tavan_usd'])      # 100 $, 200 $ (kurallar.yaml)
N0 = float(sabit_tutar_egrisi(RULES)(1000.0))                                       # ≈ 20,7548 $: ilk açılış tutarı (kopya 1.000 $ iken)


def fill(time, side, size, before, price, coin='BTC'):
    return {'time': ms(time), 'coin': coin, 'side': side, 'sz': str(size), 'startPosition': str(before), 'px': str(price),
            'tid': ms(time), 'oid': str(ms(time)), 'closedPnl': '0', 'fee': '0'}


def duz(coin='BTC', fiyat=100.0):
    return {coin: [{'t': ms(f'2026-10-27T{h:02d}:00Z'), 'o': fiyat} for h in range(0, 13)]}


def yurutme(*dakikalar, fiyat=100.0, coin='BTC'):
    return {coin: {ms(f'2026-10-27T{d}:00Z'): fiyat for d in dakikalar}}


def v3_v4(fills, yur, rules=RULES, azami=None, saatlik=None):
    saatlik = saatlik or duz()
    a = kopya_v3.hesapla(fills, saatlik, {}, yur, [], T0, NOW, 30, 'intraday', rules)
    b = kopya_v4.hesapla(fills, saatlik, {}, yur, [], T0, NOW, 30, 'intraday', rules, azami_kaldirac=azami)
    return a, b


KATLAMA = [fill('2026-10-27T10:00:00Z', 'B', 1, 0, 100), fill('2026-10-27T10:05:00Z', 'B', 4, 1, 100), fill('2026-10-27T10:10:00Z', 'B', 15, 5, 100),
           fill('2026-10-27T10:15:00Z', 'B', 80, 20, 100), fill('2026-10-27T10:20:00Z', 'B', 100, 100, 100)]
YUR = yurutme('10:30', '10:35', '10:40', '10:45', '10:50')


def test_a_ekleme_yapmayan_trader_v3_esittir_v4():
    fills = [fill('2026-10-27T10:00:00Z', 'B', 10, 0, 99), fill('2026-10-27T11:00:00Z', 'A', 10, 10, 111)]
    saatlik = {'BTC': [{'t': ms('2026-10-27T10:00:00Z'), 'o': 99.0}, {'t': ms('2026-10-27T11:00:00Z'), 'o': 111.0}]}
    v3, v4 = v3_v4(fills, {'BTC': {ms('2026-10-27T10:30:00Z'): 100.0, ms('2026-10-27T11:30:00Z'): 110.0}}, saatlik=saatlik)
    assert v4['surum'] == 'v4' and v3['surum'] == 'v3'
    for k in ('bakiye_usd', 'getiri', 'dusus', 'gerceklesen', 'acik', 'toplam', 'funding', 'maliyet', 'tasfiye', 'egri', 'kapanan_islemler', 'kapanis_nedenleri'):
        assert v4[k] == v3[k], k                                  # birebir aynı (tam eşitlik)
    assert v4['risk_kirpma'] == [] and v4['risk_kirpma_toplam'] == 0
    assert v4['tepe_pozisyon_usd'] == pytest.approx(N0)             # açılış 20,75 $ < emir tavanı < trader tavanı


def test_b_katlama_4c92_tipi_v4_pozisyonu_trader_tavanda_durur():
    """Trader 1 → 5 → 20 → 100 → 200 birim (≈ ×200 katlama). v3 kopyası aynı oranda büyür (20,75 $ → 20,75×200 ≈ 4.150 $); v4: 20,75 → 103,77 (×5) → ekleme istenen 311,3 $,
    emir tavanı 100 ama trader tavanı kalanı 200 − 103,77 = 96,23 en kısıtlayıcı → 200,00 $'da durur; sonraki iki ekleme sıfırlanır."""
    v3, v4 = v3_v4(KATLAMA, YUR)
    v3_tepe = kopya_v3.hesapla(KATLAMA, duz(), {}, YUR, [], T0, NOW, 30, 'intraday', RULES, tepe=True)['tepe_pozisyon_usd']
    assert v3_tepe == pytest.approx(N0 * 200)                       # sınırsız: 4.150 $ ≈ 800 $'lık kopya hesabında 5x değil, 4x+ (4c92 sıçrama mekanizması)
    assert v4['tepe_pozisyon_usd'] == pytest.approx(TRADER)         # v4 trader_tavan'da durur (200 $)
    assert v4['acik_pozisyonlar'][0]['buyukluk_usd'] == pytest.approx(TRADER)
    k = v4['risk_kirpma']
    assert [x['neden'] for x in k] == ['trader_tavani'] * 3
    assert k[0]['istenen_usd'] == pytest.approx(N0 * 5 * 3) and k[0]['uygulanan_usd'] == pytest.approx(TRADER - N0 * 5)      # 3. dolum: 311,3 $ istendi, 96,23 $ verildi
    assert k[1]['uygulanan_usd'] == pytest.approx(0.0) and k[2]['uygulanan_usd'] == pytest.approx(0.0)
    assert v4['risk_kirpma_toplam'] == 3 and v4['risk_kirpma_nedenler'] == {'trader_tavani': 3}
    assert v4['limitler']['emir_tavan_usd'] == EMIR and v4['limitler']['trader_tavan_usd'] == TRADER and v4['limitler']['azami_kaldirac_uygulandi'] is False


def test_c_emir_tavani_kirpmasi():
    """Trader tavanı gevşetilince (testin kendi rules kopyası; kurallar.yaml değişmez) tek emirde istenen 311,3 $ → emir tavanı 100 $'a kırpılır."""
    gevsek = {**RULES, 'risk_dry_run': {**RISK, 'trader_tavan_usd': 10_000.0}}
    fills = KATLAMA[:3]                                              # 1 → 5 → 20: ikinci ekleme 3 × (5 × N0) = 311,3 $ ister
    v3, v4 = v3_v4(fills, YUR, rules=gevsek)
    k = v4['risk_kirpma']
    assert [x['neden'] for x in k] == ['emir_tavani'] and k[0]['istenen_usd'] == pytest.approx(N0 * 5 * 3) and k[0]['uygulanan_usd'] == pytest.approx(EMIR)
    assert v4['tepe_pozisyon_usd'] == pytest.approx(N0 * 5 + EMIR)    # 103,77 + 100


def test_kaldirac_siniri_hl_azami_kaldirac_ozsermayeyi_asamaz():
    """HL azami kaldıracı 0,1x verilirse (yalnız sınırı göstermek için) başlangıç teminatı ≤ özsermaye: pozisyon ≈ 1.000 × 0,1 = 100 $'da durur."""
    gevsek = {**RULES, 'risk_dry_run': {**RISK, 'trader_tavan_usd': 10_000.0, 'emir_tavan_usd': 10_000.0}}
    v3, v4 = v3_v4(KATLAMA[:3], YUR, rules=gevsek, azami={'BTC': 0.1})
    k = v4['risk_kirpma']                                            # 1. ekleme 83,02 $ ister, izin (1.000 − 207,5) × 0,1 = 79,25 → pozisyon 100 $; 2. ekleme izin 0
    assert [x['neden'] for x in k] == ['kaldirac_siniri'] * 2 and k[0]['uygulanan_usd'] == pytest.approx(79.25, rel=1e-3) and k[1]['uygulanan_usd'] == pytest.approx(0.0, abs=1e-6)
    assert v4['tepe_pozisyon_usd'] == pytest.approx(100.0, rel=1e-3)
    assert v4['limitler']['azami_kaldirac_uygulandi'] is True
    p = v4['acik_pozisyonlar'][0]
    assert p['azami_kaldirac'] == 0.1 and p['teminat_usd'] == pytest.approx(p['buyukluk_usd'] / 0.1)


def test_d_tasfiye_v4te_de_calisir():
    rules = {**RULES, 'golge_likidasyon_esigi': -0.0001}          # test_kopya_v3.py ile aynı gevşetme: mekanizmayı göstermek için
    fills = [fill('2026-10-27T10:00:00Z', 'B', 10, 0, 100)]
    saatlik = {'BTC': [{'t': ms('2026-10-27T10:00:00Z'), 'o': 100.0}, {'t': ms('2026-10-27T11:00:00Z'), 'o': 99.0}]}
    v3, v4 = v3_v4(fills, {'BTC': {ms('2026-10-27T10:30:00Z'): 100.0}}, rules=rules, saatlik=saatlik)
    assert v4['bakiye_usd'] == 0.0 and v4['getiri'] == -1.0 and v4['tasfiye'] is True and v4['tasfiye_zamani'] == '2026-10-27T11:00:00Z'
    assert (v4['bakiye_usd'], v4['tasfiye_zamani']) == (v3['bakiye_usd'], v3['tasfiye_zamani'])


def test_acik_pozisyon_listesi_gercek_degerlerle():
    """10:00 trader 10 BTC alır (yürütme 10:30 @100); 12:00'de işaret 110: kopya 20,7548 $ notional → 22,83 $ (işaret 110), K/Z = N0 × 0,10 = 2,0755 $ (funding hariç)."""
    fills = [fill('2026-10-27T10:00:00Z', 'B', 10, 0, 100)]
    saatlik = {'BTC': [{'t': ms('2026-10-27T10:00:00Z'), 'o': 100.0}, {'t': ms('2026-10-27T11:00:00Z'), 'o': 105.0}, {'t': ms('2026-10-27T12:00:00Z'), 'o': 110.0}]}
    _, v4 = v3_v4(fills, {'BTC': {ms('2026-10-27T10:30:00Z'): 100.0}}, saatlik=saatlik, azami={'BTC': 40.0})
    [p] = v4['acik_pozisyonlar']
    assert (p['coin'], p['yon'], p['giris'], p['son']) == ('BTC', 'long', 100.0, 110.0) and p['acilis'] == '2026-10-27T10:30:00Z'
    assert p['buyukluk_usd'] == pytest.approx(N0 * 1.1) and p['kz_usd'] == pytest.approx(N0 * 0.1)
    assert p['teminat_usd'] == pytest.approx(N0 * 1.1 / 40.0) and p['kz_oran'] == pytest.approx(0.1 / 1.1 * 40.0)
    assert v4['tepe_brut_usd'] == pytest.approx(N0)


def test_risk_sayilari_kurallar_yamldan_kodda_sabit_yok():
    lim = kopya_v4.limitler({**RULES, 'risk_dry_run': {**RISK, 'emir_tavan_usd': 7.0, 'trader_tavan_usd': 9.0}})
    assert (lim['emir_tavan_usd'], lim['trader_tavan_usd']) == (7.0, 9.0)
    assert (EMIR, TRADER) == (100.0, 200.0)                         # bugünkü kurallar.yaml
