"""H1 gecikme–kâr ölçümü: altın örnekler (elle hesap) + uç durumlar. Getiri ORAN, tutar 1.000 $ sanal kopya ölçeği."""
from pathlib import Path

import pandas as pd
import pytest

from copytrade import gecikme_kar as gk
from copytrade import izleme_motoru as m
from copytrade.defter import sabit_tutar_egrisi
from copytrade.kurallar import load_rules

T0 = pd.Timestamp('2026-10-27T00:00:00Z')
NOW = pd.Timestamp('2026-10-27T12:00:00Z')
ms = lambda s: m.millis(m.timestamp(s))
RULES = load_rules()
TUTAR_1000 = sabit_tutar_egrisi(RULES)(1000.0)            # açılış tutarı ($, 1.000 $ kopyada)
R = RULES['maliyet_taker'] + RULES['maliyet_kayma']       # 0,00095 tek yön


def fill(time, side, size, before, price, coin='BTC'):
    return {'time': ms(time), 'coin': coin, 'side': side, 'sz': str(size), 'startPosition': str(before), 'px': str(price),
            'tid': ms(time), 'oid': str(ms(time)), 'closedPnl': '0', 'fee': '0'}


def yurutme(tablo):
    """{gecikme: {coin: {'HH:MM': fiyat}}} -> {gecikme: {coin: {ms: fiyat}}}"""
    return {g: {c: {ms(f'2026-10-27T{hm}:00Z'): p for hm, p in rows.items()} for c, rows in coins.items()} for g, coins in tablo.items()}


def calistir(fills, yur, saatlik=None, isaret=None, now=NOW, gecikmeler=gk.GECIKMELER):
    return gk.olc(fills, saatlik or {}, isaret or {}, yur, [], T0, now, 'intraday', RULES, gecikmeler=gecikmeler)


def net_beklenen(giris, cikis):
    own = TUTAR_1000 / giris / 1000.0
    return own * (cikis - giris) - own * giris * R - own * cikis * R


def test_altin_1_anlik_dolum_fiyati_arti_kayma_ve_taker():
    # Al 1 BTC 10:00 @100, sat 11:00 @110. Anlık: yürütme = trader dolum fiyatı (mum yok); maliyet = (taker 0,045% + kayma 0,05%) × notional, iki yönde.
    fills = [fill('2026-10-27T10:00:00Z', 'B', 1, 0, 100), fill('2026-10-27T11:00:00Z', 'A', 1, 1, 110)]
    s = calistir(fills, {}, gecikmeler=(0,))
    own = TUTAR_1000 / 100 / 1000
    beklenen = own * 10 - own * 100 * 0.00095 - own * 110 * 0.00095     # elle: 10 $/BTC kâr − 0,095% × 2 yön
    assert s[0]['net'] == pytest.approx(beklenen) and s[0]['net'] > 0
    assert (s[0]['islem'], s[0]['fiyatsiz'], s[0]['bekleyen']) == (1, 0, 0)
    assert s[0]['net'] == pytest.approx(net_beklenen(100, 110))


def test_altin_2_ayni_dolumlar_gecikme_basina_yan_yana():
    # Aynı iki dolum (10:00 al @100, 11:00 sat @110); gecikme arttıkça yürütme kötüleşir: net sırayla düşer.
    fills = [fill('2026-10-27T10:00:00Z', 'B', 1, 0, 100), fill('2026-10-27T11:00:00Z', 'A', 1, 1, 110)]
    yur = yurutme({1: {'BTC': {'10:01': 100.5, '11:01': 109.5}}, 5: {'BTC': {'10:05': 101.0, '11:05': 109.0}},
                   30: {'BTC': {'10:30': 102.0, '11:30': 108.0}}, 120: {'BTC': {'12:00': 104.0}}})
    # 120 dk: açılış 12:00 @104 yürütülür; kapanış hedefi 13:00 > şimdi -> BEKLEYEN (fiyatsız değil), pozisyon açık kalır; işaret 12:00 @106.
    s = calistir(fills, yur, isaret={'BTC': [{'t': ms('2026-10-27T12:00:00Z'), 'o': 106.0}]})
    assert s[0]['net'] == pytest.approx(net_beklenen(100, 110))
    assert s[1]['net'] == pytest.approx(net_beklenen(100.5, 109.5))
    assert s[5]['net'] == pytest.approx(net_beklenen(101, 109))
    assert s[30]['net'] == pytest.approx(net_beklenen(102, 108))
    own = TUTAR_1000 / 104 / 1000
    assert s[120]['net'] == pytest.approx(own * (106 - 104) - own * 104 * R)           # açık pozisyon, işaretle değerlenmiş, çıkış maliyeti yok
    assert s[0]['net'] > s[1]['net'] > s[5]['net'] > s[30]['net']
    assert [s[g]['bekleyen'] for g in (0, 1, 5, 30, 120)] == [0, 0, 0, 0, 1]
    assert [s[g]['fiyatsiz'] for g in (0, 1, 5, 30, 120)] == [0, 0, 0, 0, 0]
    assert [s[g]['islem'] for g in (0, 1, 5, 30, 120)] == [1, 1, 1, 1, 0]


def test_yurutme_zamani_gelmemis_dolum_fiyatsiz_sayilmaz():
    # B17 dersi: 30 dk gecikmeli hedef (11:30) şimdiden (11:10) sonra -> bekliyor; fiyatsiz 0, bekleyen 1. Anlık hemen yürütülür.
    now = pd.Timestamp('2026-10-27T11:10:00Z')
    fills = [fill('2026-10-27T11:00:00Z', 'B', 1, 0, 100)]
    s = calistir(fills, {}, now=now, gecikmeler=(0, 30))
    assert (s[30]['fiyatsiz'], s[30]['bekleyen']) == (0, 1)
    assert (s[0]['fiyatsiz'], s[0]['bekleyen']) == (0, 0)


def test_eksik_mum_fiyatsiz_sayilir_ve_diger_gecikmeleri_bozmaz():
    fills = [fill('2026-10-27T10:00:00Z', 'B', 1, 0, 100), fill('2026-10-27T11:00:00Z', 'A', 1, 1, 110)]
    yur = yurutme({5: {'BTC': {'10:05': 101.0}}})          # 11:05 mumu yok
    s = calistir(fills, yur, gecikmeler=(0, 5))
    assert s[5]['fiyatsiz'] == 1 and s[5]['bekleyen'] == 0
    assert s[0]['fiyatsiz'] == 0 and s[0]['net'] == pytest.approx(net_beklenen(100, 110))


def test_bos_hesap_ve_sifira_yakin_miktar():
    s = calistir([], {})
    assert all(h['net'] == 0.0 and h['islem'] == 0 and h['fiyatsiz'] == 0 for h in s.values())
    # 1e-13 BTC'lik dolum motorda eşik altı (sıfır sayılır): net 0, çökme/bölme yok
    s = calistir([fill('2026-10-27T10:00:00Z', 'B', 1e-13, 0, 100)], {}, gecikmeler=(0,))
    assert s[0]['net'] == 0.0
    # dolum fiyatı 0: anlık gerçekten fiyatsız (mum aranmaz, sahte fiyat yok)
    s = calistir([fill('2026-10-27T10:00:00Z', 'B', 1, 0, 0)], {}, gecikmeler=(0,))
    assert s[0]['fiyatsiz'] == 1 and s[0]['net'] == 0.0


def test_ozet_kazanan_kaybeden_ve_fark():
    def satir(i, n0, n30):
        return {'id': i, 'gecikmeler': {'0': {'net': n0}, '30': {'net': n30}}}
    satirlar = [satir('a', 0.02, 0.005), satir('b', -0.01, -0.03), satir('c', None, 0.01), satir('d', 0.0, 0.0)]
    o = gk.ozet(satirlar)
    assert (o['anlik_kazanan'], o['anlik_kaybeden'], o['anlik_sifir'], o['anlik_hesaplanamayan']) == (1, 1, 1, 1)
    assert o['anlik_30dk_karsilastirilan'] == 3
    assert o['fark_anlik_30dk_ortalama'] == pytest.approx((0.015 + 0.02 + 0.0) / 3)
    assert o['fark_anlik_30dk']['maks'] == pytest.approx(0.02)
    assert satirlar[2]['fark_anlik_30dk'] is None
    bos = gk.ozet([])
    assert bos['fark_anlik_30dk'] is None and bos['fark_anlik_30dk_ortalama'] is None and bos['anlik_kazanan'] == 0


def test_mum_onbellegi_kapsanan_araligi_tekrar_okumaz():
    sayac = []

    class Istemci:
        def candles(self, coin, s, e, interval='1m'):
            sayac.append(1)
            return [{'t': t, 'o': 1.0} for t in range(s, e + 1, 60_000)]
    o = gk.MumOnbellegi(Istemci())
    assert len(o.candles('BTC', 0, 600_000)) == 11
    assert len(o.candles('BTC', 120_000, 600_000)) == 9
    assert len(sayac) == 1
    o.candles('BTC', 0, 900_000)           # kapsanmayan aralık: yeniden okunur
    assert len(sayac) == 2


def test_uctan_uca_sahte_istemci_dakika_penceresi():
    # Sahte API: BTC düz 105, trader 100'den alıp 110'dan satıyor (son 3 saat içinde). Boru hattı (dolum -> mum -> v3 -> tablo) offline çalışır.
    now = pd.Timestamp('2026-10-27T12:00:00Z')
    dolumlar = [fill('2026-10-27T09:00:00Z', 'B', 1, 0, 100), fill('2026-10-27T10:00:00Z', 'A', 1, 1, 110)]

    class Istemci:
        def fills(self, address, start, max_rows=None, end_ms=None):
            return dolumlar

        def info(self, body, weight=1):
            return []

        def candles(self, coin, s, e, interval='1m'):
            adim = 60_000 if interval == '1m' else 3_600_000
            return [{'t': t, 'o': 105.0} for t in range(s // adim * adim, e + 1, adim)]
    satir = {'id': 'X1', 'adres': '0xabc', 'takma_ad': 'x', 'durum': 'izlemede', 't0': '2026-10-20', 'tarz': 'intraday'}
    s = gk.olc_trader(Path('.'), Istemci(), satir, now, 'dakika', RULES)
    assert s['ilk_dolum'] == '2026-10-27T09:00:00Z'            # pencere içi ilk dolum (UTC)
    assert s['dolum'] == 2 and s['mevcut_gecikme_dk'] == 30 and s['mevcut_net'] == s['gecikmeler']['30']['net']
    assert set(s['gecikmeler']) == {'0', '1', '5', '30', '120'}
    assert s['gecikmeler']['0']['net'] == pytest.approx(net_beklenen(100, 110))
    assert abs(s['gecikmeler']['30']['net']) < 0.01 and all(h['yaklasik'] == 0 for h in s['gecikmeler'].values())


# ------------------------------------------------------------------------------------------------ ek altın örnekler (SAYISAL, elle hesap)
# Açılış tutarı: 5,2 $ × (1.000 / 200)^0,86 = 5,2 × 3,99130 = 20,754752 $ (kurallar.yaml sabit_tutar_*); taker + kayma = 0,00045 + 0,0005 = 0,00095 (tek yön).
# Dolumlar: 10:00 al 1 BTC, 11:00 sat 1 BTC. Net = (kâr − giriş maliyeti − çıkış maliyeti) / 1.000 $ (ORAN).
def test_altin_3_sayisal_anlik_giris_100_cikis_110():
    # miktar = 20,754752 / 100 = 0,20754752 BTC; kâr = 0,20754752 × 10 = 2,0754752 $
    # maliyet = 0,20754752 × (100 + 110) × 0,00095 = 0,0414066 $ ; net = 2,0340686 $ -> 0,0020340686
    fills = [fill('2026-10-27T10:00:00Z', 'B', 1, 0, 100), fill('2026-10-27T11:00:00Z', 'A', 1, 1, 110)]
    s = calistir(fills, {}, gecikmeler=(0,))
    assert s[0]['net'] == pytest.approx(0.0020340686, abs=1e-9)


def test_altin_4_sayisal_1_dk_gecikme_giris_100_5_cikis_109_5():
    # miktar = 20,754752 / 100,5 = 0,20651494 BTC; kâr = 0,20651494 × 9 = 1,8586345 $
    # maliyet = 0,20651494 × (100,5 + 109,5) × 0,00095 = 0,0412006 $ ; net = 1,8174339 $ -> 0,0018174339
    fills = [fill('2026-10-27T10:00:00Z', 'B', 1, 0, 100), fill('2026-10-27T11:00:00Z', 'A', 1, 1, 110)]
    s = calistir(fills, yurutme({1: {'BTC': {'10:01': 100.5, '11:01': 109.5}}}), gecikmeler=(1,))
    assert s[1]['net'] == pytest.approx(0.0018174339, abs=1e-9)


def test_gelecek_tarihli_dolum_anlikta_yok_sayilir_ve_fiyatsiz_tek_dolum_net_sifir_gorunur():
    # şimdiden sonraki dolum (saat kayması) anlıkta ne işlem ne fiyatsız sayılır.
    # Fiyatı hiç bulunamayan tek yürütme: v3 motoru `net` None DÖNDÜRMEZ (sabit tutar yolunda net daima sayı) -> net 0,0 ve fiyatsiz 1 görünür;
    # tabloyu okuyan `fiyatsiz` sütununa bakmak zorundadır (VERI_SOZLESMESI §4b'de yazılı sınır).
    fills = [fill('2026-10-27T13:00:00Z', 'B', 1, 0, 100)]
    s = calistir(fills, {}, gecikmeler=(0,))
    assert (s[0]['islem'], s[0]['fiyatsiz'], s[0]['bekleyen']) == (0, 0, 0)
    s = calistir([fill('2026-10-27T10:00:00Z', 'B', 1, 0, 100)], {}, gecikmeler=(5,))        # 10:05 mumu yok
    assert s[5]['net'] == 0.0 and s[5]['fiyatsiz'] == 1 and s[5]['islem'] == 0 and s[5]['neden'] is None


def test_sozlesme_ciktidaki_her_alan_veri_sozlesmesinde_yazili():
    """Tüketen/üreten kod sözleşmeye göre sınanır (AGENTS kural 2): çıktıdaki her anahtar docs/VERI_SOZLESMESI.md §4b'de geçer."""
    belge = (Path(__file__).resolve().parents[1] / 'docs/VERI_SOZLESMESI.md').read_text(encoding='utf-8')
    bolum = belge[belge.index('## 4b.'):belge.index('## 5.')]
    fills = [fill('2026-10-27T10:00:00Z', 'B', 1, 0, 100)]
    s = calistir(fills, {}, gecikmeler=(0,))[0]
    satir = gk.trader_satiri('X', '0xabc', 'intraday', T0, {0: s}, 0, 1)
    satir['fark_anlik_30dk'] = None
    sonuc = {'surum': gk.SURUM, 'uretildi': '', 'pencere': '', 'gecikmeler_dk': [], 'maliyet': {'taker': 0, 'kayma': 0}, 'traderlar': [satir], 'hatalar': [],
             'ozet': gk.ozet([satir])}
    anahtarlar = set(sonuc) | set(satir) | set(s) | set(sonuc['ozet']) | set(sonuc['maliyet'])
    eksik = sorted(a for a in anahtarlar if a not in ('0', 'min', 'medyan', 'maks') and f'`{a}' not in bolum and f'.{a}' not in bolum and f'{a}`' not in bolum)
    assert not eksik, f'VERI_SOZLESMESI §4b\'de yazılmayan alanlar: {eksik}'


def test_ilk_dolum_bos_hesapta_none_ve_olcumu_degistirmez():
    bos = gk.trader_satiri('X', '0xabc', 'intraday', T0, calistir([], {}, gecikmeler=(0,)), 0, 0)
    assert bos['ilk_dolum'] is None
    dolu = gk.trader_satiri('X', '0xabc', 'intraday', T0, calistir([], {}, gecikmeler=(0,)), 0, 0, ms('2026-10-27T09:00:00.500Z'))
    assert dolu['ilk_dolum'] == '2026-10-27T09:00:00.500000Z' and {k: v for k, v in dolu.items() if k != 'ilk_dolum'} == {k: v for k, v in bos.items() if k != 'ilk_dolum'}
