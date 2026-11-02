"""Kopya hesap v2 için altın örnekler."""
import pytest
import pandas as pd

from copytrade import izleme_motoru as m
from copytrade import kopya_v2

T0 = pd.Timestamp('2026-10-27T00:00:00Z')
NOW = pd.Timestamp('2026-10-27T12:00:00Z')
ms = lambda s: m.millis(m.timestamp(s))


def fill(time, side, size, before, price, coin='BTC'):
    return {'time': ms(time), 'coin': coin, 'side': side, 'sz': str(size), 'startPosition': str(before), 'px': str(price),
            'tid': ms(time), 'oid': str(ms(time)), 'closedPnl': '0', 'fee': '0'}


def hourly(**prices):
    return {coin: [{'t': ms(f'2026-10-27T{h}:00Z'), 'o': p} for h, p in rows.items()] for coin, rows in prices.items()}


def run(fills, saatlik, yurutme, serisi, funding=(), isaret=None, delay=30):
    execution = {coin: {ms(f'2026-10-27T{h}:00Z'): p for h, p in rows.items()} for coin, rows in yurutme.items()}
    return kopya_v2.hesapla(fills, saatlik, isaret or {}, execution, serisi, list(funding), T0, NOW, delay, 'intraday')


ACCOUNT_1000 = [[ms('2026-10-27T00:00:00Z'), 1000.0]]


def test_tek_motor_v1_ile_ayni_girdi_ayni_sonuc():
    # Al 1 BTC 10:00 (yürütme 10:30 @100), sat 11:00 (yürütme 11:30 @110), hesap 1.000 $ -> ölçek 0,001.
    # Brüt 0,001 x 10 = 0,01; maliyet 0,001x100x0,00095 + 0,001x110x0,00095 = 0,0001995 -> net 0,0098005 -> 1.009,8005 $.
    fills = [fill('2026-10-27T10:00:00Z', 'B', 1, 0, 99), fill('2026-10-27T11:00:00Z', 'A', 1, 1, 111)]
    v2 = run(fills, hourly(BTC={'10:00': 99.0, '11:00': 111.0}), {'BTC': {'10:30': 100.0, '11:30': 110.0}}, ACCOUNT_1000)
    assert v2['bakiye_usd'] == pytest.approx(1009.8005)
    candles = {'BTC': [{'t': ms('2026-10-27T10:30:00Z'), 'o': 100.0}, {'t': ms('2026-10-27T11:30:00Z'), 'o': 110.0}]}
    v1 = m.copy_results(fills, candles, [], 1000, T0, NOW, {})
    assert v1['bakiye_usd'] == pytest.approx(1009.8005)               # v1 ile v2 aynı girdide aynı sayı (tek motor)
    assert v2['tasfiye'] is False and v2['tasfiye_zamani'] is None and v2['payda_yontemi'] == 'ilk_okuma'


def test_tasfiye_bakiye_sifirda_kalir_ve_zaman_yayimlanir():
    # 20 BTC @100 (hesap 1.000 -> ölçek 0,001 -> kopya 0,02 BTC). 11:00 saatlik işaret 50 -> K/Z = 0,02 x (50-100) = -1,0 <= -1,0 eşik:
    # 11:00'de tasfiye @50. Gerçekleşen -1,0, maliyet 0,02x100x0,00095 + 0,02x50x0,00095 = 0,00285 -> özsermaye 1000x(1-1,00285) < 0 -> bakiye 0.
    fills = [fill('2026-10-27T10:00:00Z', 'B', 20, 0, 100)]
    v2 = run(fills, hourly(BTC={'10:00': 100.0, '11:00': 50.0, '12:00': 40.0}), {'BTC': {'10:30': 100.0}}, ACCOUNT_1000)
    assert v2['tasfiye'] is True and v2['tasfiye_kaynagi'] == 'mum'
    assert v2['tasfiye_zamani'] == '2026-10-27T11:00:00Z'
    assert v2['bakiye_usd'] == 0.0 and v2['getiri'] == -1.0
    assert v2['egri'][-1] == ['2026-10-27', 0.0]


def test_aşamalı_zarar_kes_tasfiyeden_once_pozisyonu_kapatir():
    # E3: intraday zarar_kes eşiği -%50 (kurallar.yaml golge_v2, ön kayıtlı). 11:00'de K/Z = 0,02x(60-100) = -0,8 <=
    # -0,5 (ama -1,0 çapraz teminat eşiğinin ÜSTÜNDE, tasfiye değil) -> pozisyon 11:00'de @60 zorunlu kapanır.
    # Gerçekleşen: -0,8 (kapanış) - giriş maliyeti 0,02x100x0,00095=0,0019 - çıkış maliyeti 0,02x60x0,00095=0,00114
    # = -0,80304 -> bakiye 1000x(1-0,80304) = 196,96.
    fills = [fill('2026-10-27T10:00:00Z', 'B', 20, 0, 100)]
    v2 = run(fills, hourly(BTC={'10:00': 100.0, '11:00': 60.0}), {'BTC': {'10:30': 100.0}}, ACCOUNT_1000,
             isaret={'BTC': [{'t': ms('2026-10-27T11:59:00Z'), 'o': 60.0}]})
    assert v2['tasfiye'] is False                                        # çapraz teminat eşiğine değmedi
    assert v2['bakiye_usd'] == pytest.approx(196.96, rel=1e-6)
    assert v2['kapanis_nedenleri'] == [{'coin': 'BTC', 'neden': 'zarar_kes', 'zaman': '2026-10-27T11:00:00Z'}]


def test_zarar_kes_esigine_degmeyen_pozisyon_acik_kalir():
    # Aynı pozisyon, işaret -%20 (eşiğin üstünde): hiçbir zorunlu çıkış yok, açık K/Z işaretle yayımlanır.
    fills = [fill('2026-10-27T10:00:00Z', 'B', 20, 0, 100)]
    v2 = run(fills, hourly(BTC={'10:00': 100.0, '11:00': 90.0}), {'BTC': {'10:30': 100.0}}, ACCOUNT_1000,
             isaret={'BTC': [{'t': ms('2026-10-27T11:59:00Z'), 'o': 90.0}]})
    assert v2['tasfiye'] is False and v2['kapanis_nedenleri'] == []
    assert v2['bakiye_usd'] == pytest.approx(1000 * (1 - 0.2 - 0.0019), rel=1e-9)


def test_zamanla_degisen_payda():
    # Hesap 1.000 $ -> 10:45'te 2.000 $. 10:00 alımı (ölçek 1/1000) -> 0,001 BTC; 11:00 alımı (ölçek 1/2000) -> 0,0005 BTC.
    # İşaret fiyatı girişle aynı (100) -> açık K/Z 0; yalnız maliyet: 0,001x100x0,00095 + 0,0005x100x0,00095 = 0,0001425 -> 999,8575 $.
    serisi = [[ms('2026-10-27T00:00:00Z'), 1000.0], [ms('2026-10-27T10:45:00Z'), 2000.0]]
    fills = [fill('2026-10-27T10:00:00Z', 'B', 1, 0, 100), fill('2026-10-27T11:00:00Z', 'B', 1, 1, 100)]
    v2 = run(fills, hourly(BTC={'10:00': 100.0, '11:00': 100.0}), {'BTC': {'10:30': 100.0, '11:30': 100.0}}, serisi,
             isaret={'BTC': [{'t': ms('2026-10-27T11:59:00Z'), 'o': 100.0}]})
    assert v2['bakiye_usd'] == pytest.approx(999.8575)
    assert v2['payda_yontemi'] == 'saatlik_okuma' and v2['payda_okuma_sayisi'] == 2
    sabit = run(fills, hourly(BTC={'10:00': 100.0, '11:00': 100.0}), {'BTC': {'10:30': 100.0, '11:30': 100.0}}, ACCOUNT_1000,
                isaret={'BTC': [{'t': ms('2026-10-27T11:59:00Z'), 'o': 100.0}]})
    assert sabit['bakiye_usd'] == pytest.approx(1000 * (1 - 0.00019))         # sabit payda: 2 x 0,001 BTC -> eski (yanlış) maruziyet


def test_funding_yalniz_kopyalanan_pozisyondan():
    # Trader t0 öncesi 5 BTC devralmış; 10:00'da 1 BTC ekler (startPosition 5). Kopya yalnız eklenen 1 BTC x 0,001 = 0,001 BTC (10:30'dan).
    # Funding saatlik oran 0,01: 11:00 saatinde -0,001 BTC x 100 x 0,01 = -0,001 (kesir). Devralınan 5 BTC'nin funding'i girmez.
    funding = [{'time': ms(f'2026-10-27T{h}:00:00Z'), 'delta': {'coin': 'BTC', 'fundingRate': '0.01', 'usdc': '-5', 'szi': '6'}} for h in ('10', '11', '12')]
    fills = [fill('2026-10-27T10:00:00Z', 'B', 1, 5, 100)]
    v2 = run(fills, hourly(BTC={'10:00': 100.0, '11:00': 100.0}), {'BTC': {'10:30': 100.0}}, ACCOUNT_1000, funding=funding,
             isaret={'BTC': [{'t': ms('2026-10-27T11:59:00Z'), 'o': 100.0}]})
    assert v2['funding'] == pytest.approx(-0.001)
    assert v2['bakiye_usd'] == pytest.approx(1000 * (1 - 0.001 - 0.000095))
    fundingsiz = run(fills, hourly(BTC={'10:00': 100.0, '11:00': 100.0}), {'BTC': {'10:30': 100.0}}, ACCOUNT_1000,
                         isaret={'BTC': [{'t': ms('2026-10-27T11:59:00Z'), 'o': 100.0}]})
    assert fundingsiz['funding'] == 0.0                                      # funding verisi yoksa sıfır


def test_dakika_mumu_funding_izgarasina_girmez():
    # Listede 11:59 işaret mumu olsa da funding'e fazladan saat eklenmez (yukarıdaki test aynı -0,001'i verir); tek başına doğrula.
    from copytrade.defter import FundingRates, Market
    market = Market({'BTC': [{'t': ms('2026-10-27T11:00:00Z'), 'o': 100.0}, {'t': ms('2026-10-27T11:59:00Z'), 'o': 100.0}]})
    times, cum = market.funding_cum('BTC', FundingRates([]))
    assert times == [ms('2026-10-27T11:00:00Z')]
    assert len(cum) == 2                                                     # [0.0, saat 11:00'in kümülatifi]


def test_eksik_hesap_degeri_serisi_hesaplanamadi_doner():
    fills = [fill('2026-10-27T10:00:00Z', 'B', 1, 0, 100)]
    v2 = run(fills, hourly(BTC={'10:00': 100.0}), {'BTC': {'10:30': 100.0}}, [[ms('2026-10-27T00:00:00Z'), 0.0]])
    assert v2['durum'] == 'hesaplanamadi'


def test_bos_hesap_hiç_dolum_hiç_cokme():
    v2 = run([], hourly(), {}, ACCOUNT_1000)
    assert v2['bakiye_usd'] == 1000.0 and v2['tasfiye'] is False
