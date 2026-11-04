"""Tek boyutlandırma (K‑28, RADAR_V1.md §5/§5b): `copytrade/boyut.py` ve `kopya_v5` için elle hesaplanmış altın örnekler."""
import pandas as pd
import pytest

from copytrade import boyut, kopya_v5
from copytrade import izleme_motoru as m
from copytrade.kurallar import load_rules

RULES = load_rules()
T0 = pd.Timestamp('2026-10-27T00:00:00Z')
NOW = pd.Timestamp('2026-10-27T12:00:00Z')
ms = lambda s: m.millis(m.timestamp(s if len(s) > 6 else f'2026-10-27T{s}:00Z'))   # noqa: E731  ('10:00' → 2026-10-27T10:00:00Z)
SLOT = 1000 / 11                                              # 90,909…


@pytest.mark.parametrize('kasa, n, slot', [(100, 4, 25.0), (250, 10, 25.0), (500, 11, 500 / 11), (750, 11, 750 / 11), (1000, 11, 1000 / 11)])
def test_saha_sayisi_ve_slot(kasa, n, slot):
    assert boyut.saha_sayisi(kasa, RULES) == n and boyut.slot_usd(kasa, RULES) == pytest.approx(slot)
    assert boyut.slot_usd(500, RULES) == pytest.approx(45.4545, abs=1e-4) and boyut.slot_usd(1000, RULES) == pytest.approx(90.91, abs=1e-2)


@pytest.mark.parametrize('kasa', [0, -5, 24.99, 1000.01, float('nan')])
def test_kasa_sinirlari_hata(kasa):
    with pytest.raises(ValueError):
        boyut.saha_sayisi(kasa, RULES)


def test_kasa_tam_sinirlar_gecer():
    assert boyut.saha_sayisi(25, RULES) == 1 and boyut.saha_sayisi(1000, RULES) == 11


def acilis(nosyonel, hesap=100_000.0, fiyat=100.0):
    return boyut.hedef_emir('ac', 0.0, nosyonel / fiyat, hesap, 0.0, SLOT, fiyat, RULES)


def test_acilis_orantili_min_ve_tavan():
    emir, neden = acilis(30_000)                                 # 90,91 × 0,30 = 27,27 $
    assert emir == pytest.approx(27.27, abs=1e-2) and neden == 'tamam'
    emir, neden = acilis(5_000)                                  # 4,55 $ < 11 → 3 × slot ≥ 11 → 11 $
    assert emir == 11.0 and neden == 'min_emir_yuvarlandi'
    emir, neden = acilis(400_000)                                # 363,6 $ → tavan 3 × 90,91 = 272,73 $
    assert emir == pytest.approx(272.73, abs=1e-2) and neden == 'tavan_kirpildi'


def test_min_emir_atlandi_kucuk_slot():
    """slot 2 $ → 3 × slot = 6 < 11: küçük açılış yuvarlanamaz → atlanır."""
    assert boyut.hedef_emir('ac', 0.0, 10.0, 100_000.0, 0.0, 2.0, 100.0, RULES) == (0.0, 'min_emir_atlandi')


def test_azaltma_oran_kucuk_kalan_ve_atlama():
    emir, neden = boyut.hedef_emir('azalt', 10.0, 5.0, 0.0, 27.27, SLOT, 100.0, RULES)          # trader %50 azaltır → 13,635 $
    assert emir == pytest.approx(13.635) and neden == 'tamam'
    emir, neden = boyut.hedef_emir('azalt', 10.0, 6.0, 0.0, 15.0, SLOT, 100.0, RULES)           # %40 → 6 $ < 11, kalan 9 < 11 → 15 $ tam
    assert emir == 15.0 and neden == 'kucuk_kalan_kapat'
    assert boyut.hedef_emir('azalt', 10.0, 9.0, 0.0, 60.0, SLOT, 100.0, RULES) == (0.0, 'min_emir_atlandi')   # %10 → 6 $ < 11, kalan 54 ≥ 11 → atla


def test_artirma_oran_atlama_ve_tavan():
    emir, neden = boyut.hedef_emir('artir', 10.0, 15.0, 0.0, 40.0, SLOT, 100.0, RULES)           # trader %50 artırır → 20 $
    assert emir == pytest.approx(20.0) and neden == 'tamam'
    assert boyut.hedef_emir('artir', 10.0, 11.0, 0.0, 40.0, SLOT, 100.0, RULES) == (0.0, 'min_emir_atlandi')  # 4 $ < 11 → atla
    emir, neden = boyut.hedef_emir('artir', 10.0, 30.0, 0.0, 200.0, SLOT, 100.0, RULES)         # istenen 400 $; toplam tavan 272,73 → 72,73 $
    assert emir == pytest.approx(3 * SLOT - 200.0) and neden == 'slot_tavani'            # K‑35: toplam tavan etiketi


def test_trader_tam_kapanis_bizim_tamami_ve_bilinmeyen_eylem():
    assert boyut.hedef_emir('kapat', 10.0, 0.0, 0.0, 7.0, SLOT, 100.0, RULES) == (7.0, 'tam_kapanis')      # 11 $ altı olsa da tamamı
    with pytest.raises(ValueError):
        boyut.hedef_emir('x', 0, 0, 0, 0, SLOT, 100.0, RULES)


def fill(time, side, size, before, price, coin='BTC'):
    return {'time': ms(time), 'coin': coin, 'side': side, 'sz': str(size), 'startPosition': str(before), 'px': str(price),
            'tid': ms(time), 'oid': str(ms(time)), 'closedPnl': '0', 'fee': '0'}


def saat_mumlari(fiyat=100.0):
    return {'BTC': [{'t': ms(f'2026-10-27T{h:02d}:00:00Z'), 'o': fiyat} for h in range(0, 13)]}


def oynat(delay, rules, fills=None, hesap=20_000.0):
    fills = fills or [fill('10:00', 'B', 100, 0, 100), fill('11:00', 'A', 100, 100, 110)]
    yurut = {'BTC': {ms('2026-10-27T10:01:00Z'): 100.0, ms('2026-10-27T11:01:00Z'): 110.0}}
    return kopya_v5.hesapla(fills, saat_mumlari(), {}, yurut, [], T0, NOW, delay, 'intraday', rules, trader_hesap_usd=hesap, kasa_usd=1000.0)


def test_v5_altin_ornek_ayna_ve_kopya_tek_long_100_den_110a():
    """Trader hesap 20.000 $, 100 BTC × 100 = 10.000 $ (oran 0,5) açar, 110'dan tamamını kapatır. Slot 90,909 $ → açılış 45,4545 $ = 0,454545 BTC.
    Ayna (gecikme 0, maliyet 0): kâr 0,454545 × 10 = 4,54545 $ → getiri 0,00454545. Kopya (1 dk gecikme, aynı mum fiyatları, maliyet 0,00095): maliyet = (45,4545 + 50) × 0,00095 = 0,0906818 $
    → net 4,454773 $ → getiri 0,004454773; kopya_koruma = 0,98005."""
    sifir = {**RULES, 'maliyet_taker': 0.0, 'maliyet_kayma': 0.0}
    ayna, kopya = oynat(0, sifir), oynat(1, RULES)
    assert ayna['surum'] == 'v5' and ayna['kasa_usd'] == 1000.0 and ayna['slot_usd'] == pytest.approx(1000 / 11)
    assert ayna['getiri'] == pytest.approx(0.00454545, abs=1e-8)
    assert kopya['getiri'] == pytest.approx(0.004454773, abs=1e-8)
    assert kopya['getiri'] / ayna['getiri'] == pytest.approx(0.98005, abs=1e-5)


def test_v5_kopya_kasasi_olcegi_getiri_kasaya_gore():
    """Kasa 500 → N 11, slot 45,4545 $, açılış 22,7273 $: kâr 2,27273 $ / 500 = 0,00454545 (oran slot/kasa aynı → getiri aynı)."""
    sifir = {**RULES, 'maliyet_taker': 0.0, 'maliyet_kayma': 0.0}
    sonuc = kopya_v5.hesapla([fill('10:00', 'B', 100, 0, 100), fill('11:00', 'A', 100, 100, 110)], saat_mumlari(), {}, {}, [], T0, NOW, 0, 'intraday', sifir,
                             trader_hesap_usd=20_000.0, kasa_usd=500.0)
    assert sonuc['getiri'] == pytest.approx(0.00454545, abs=1e-8) and sonuc['baslangic_usd'] == 500.0


def test_v5_trader_yari_azaltir_kalan_sonra_kapanir():
    """Aç 100 BTC → 45,4545 $ (0,454545 BTC); trader 50 BTC satar (%50) → 22,7273 $ (0,227273 BTC) 105'ten; kalanı 110'dan: kâr = 0,227273×5 + 0,227273×10 = 3,40909 $."""
    sifir = {**RULES, 'maliyet_taker': 0.0, 'maliyet_kayma': 0.0}
    fills = [fill('10:00', 'B', 100, 0, 100), fill('10:30', 'A', 50, 100, 105), fill('11:00', 'A', 50, 50, 110)]
    sonuc = kopya_v5.hesapla(fills, saat_mumlari(), {}, {}, [], T0, NOW, 0, 'intraday', sifir, trader_hesap_usd=20_000.0, kasa_usd=1000.0)
    assert sonuc['getiri'] * 1000 == pytest.approx(3.40909, abs=1e-5)


def test_v5_varsayilan_v3_v4_ayni_kaldi():
    """Kural 6: v5 eklemesi v3'ü değiştirmez (defter `boyutlayici=None` yolu)."""
    from copytrade import kopya_v3
    a = kopya_v3.hesapla([fill('10:00', 'B', 100, 0, 100), fill('11:00', 'A', 100, 100, 110)], saat_mumlari(), {}, {'BTC': {ms('2026-10-27T10:01:00Z'): 100.0, ms('2026-10-27T11:01:00Z'): 110.0}},
                         [], T0, NOW, 1, 'intraday', RULES)
    assert a['surum'] == 'v3' and a['baslangic_usd'] == 1000.0 and a['getiri'] == pytest.approx(0.0020340, abs=1e-6)


# ------------------------------------------------------------------------------------------------ K‑35: slot TOPLAM tavanı (tüm coinler)
def test_k35_slot_toplam_tavani_altin_ornek_72_73():
    """Slot 90,91 → toplam tavan 3 × 90,91 = 272,73 $. Mevcut iki coinde 200 $ varken yeni açılış (istenen 363,6 $ → önce 272,73'e) en çok 72,73 $ olur; kalan 5 $ < 11 → 0; tam tavanda 0."""
    emir, neden = boyut.hedef_emir('ac', 0.0, 4000.0, 100_000.0, 0.0, SLOT, 100.0, RULES, biz_slot_toplam_usd=200.0)
    assert emir == pytest.approx(72.7273, abs=1e-4) and neden == 'slot_tavani'
    assert boyut.hedef_emir('ac', 0.0, 4000.0, 100_000.0, 0.0, SLOT, 100.0, RULES, biz_slot_toplam_usd=267.73) == (0.0, 'slot_tavani')
    assert boyut.hedef_emir('ac', 0.0, 4000.0, 100_000.0, 0.0, SLOT, 100.0, RULES, biz_slot_toplam_usd=3 * SLOT) == (0.0, 'slot_tavani')
    # hedef kendiliğinden küçük (4,55 $): kalan yeterliyse 11 $'a yuvarlanır, değilse 0
    assert boyut.hedef_emir('ac', 0.0, 50.0, 100_000.0, 0.0, SLOT, 100.0, RULES, biz_slot_toplam_usd=200.0) == (11.0, 'min_emir_yuvarlandi')
    assert boyut.hedef_emir('ac', 0.0, 50.0, 100_000.0, 0.0, SLOT, 100.0, RULES, biz_slot_toplam_usd=265.0) == (0.0, 'slot_tavani')
    # tavan altında kalan istek kırpılmaz
    assert boyut.hedef_emir('ac', 0.0, 300.0, 100_000.0, 0.0, SLOT, 100.0, RULES, biz_slot_toplam_usd=100.0) == (pytest.approx(27.2727, abs=1e-4), 'tamam')


def test_k35_artirma_toplam_tavan_diger_coinler_sayilir():
    """Bu coinde 40 $, diğer coinlerde 220 $ (toplam 260): trader %50 artırır (istenen 20 $) → kalan 272,73 − 260 = 12,73 $ → 12,73 $ ('slot_tavani'); toplam 268 → kalan 4,73 < 11 → 0."""
    emir, neden = boyut.hedef_emir('artir', 10.0, 15.0, 0.0, 40.0, SLOT, 100.0, RULES, biz_slot_toplam_usd=260.0)
    assert emir == pytest.approx(12.7273, abs=1e-4) and neden == 'slot_tavani'
    assert boyut.hedef_emir('artir', 10.0, 15.0, 0.0, 40.0, SLOT, 100.0, RULES, biz_slot_toplam_usd=268.0) == (0.0, 'slot_tavani')
    assert boyut.hedef_emir('artir', 10.0, 15.0, 0.0, 40.0, SLOT, 100.0, RULES, biz_slot_toplam_usd=None) == (pytest.approx(20.0), 'tamam')      # None: eski coin başına davranış


def test_k35_kopya_v5_uc_coinde_ayni_toplam_tavan_radar_ayni_sayiyi_gorur():
    """Slot 90,909, toplam tavan 272,727 $. Trader hesap 100.000 $; sırayla BTC 150.000 $ (hedef 136,36 → tam), ETH 160.000 $ (hedef 145,45; kalan 136,36 → 136,36 'slot_tavani'), SOL 50.000 $ (hedef 45,45; kalan 0 → 0).
    Ayna (gecikme 0, maliyet 0): üç coin da 100 → 110: kâr = 136,36 × 0,10 × 2 = 27,27 $ → getiri 0,02727. K‑35 ÖNCESİ (`k35=False`): v4'ün eski emir başına 100 $ ve trader toplamı 200 $ sınırı açıktı → BTC 100, ETH 100 (toplam 200'de durdu), SOL 0
    → kâr 100 × 0,10 × 2 = 20 $ → 0,02000 (yani eski kural canlıdan FARKLI sayı görüyordu)."""
    kayit: list = []
    fills = []
    for coin, nos in (('BTC', 150_000), ('ETH', 160_000), ('SOL', 50_000)):
        fills += [fill('10:00', 'B', nos / 100, 0, 100, coin), fill('11:00', 'A', nos / 100, nos / 100, 110, coin)]
    saatlik = {c: [{'t': ms(f'2026-10-27T{h:02d}:00:00Z'), 'o': 100.0} for h in range(0, 13)] for c in ('BTC', 'ETH', 'SOL')}
    sifir = {**RULES, 'maliyet_taker': 0.0, 'maliyet_kayma': 0.0}
    sonuc = kopya_v5.hesapla(fills, saatlik, {}, {}, [], T0, NOW, 0, 'intraday', sifir, trader_hesap_usd=100_000.0, kasa_usd=1000.0, kayit=kayit)
    acilislar = [(e, n, round(u, 2)) for e, n, u in kayit if e == 'ac']
    assert acilislar == [('ac', 'tamam', 136.36), ('ac', 'slot_tavani', 136.36), ('ac', 'slot_tavani', 0.0)]
    assert sonuc['getiri'] == pytest.approx(27.2727 / 1000, abs=1e-6)
    eski = kopya_v5.hesapla(fills, saatlik, {}, {}, [], T0, NOW, 0, 'intraday', sifir, trader_hesap_usd=100_000.0, kasa_usd=1000.0, k35=False)
    assert eski['getiri'] == pytest.approx(20.0 / 1000, abs=1e-6)
