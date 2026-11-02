"""`kapanan_islemler` (v3) / `copy_ledger(islem_kaydi=True)` altın örnekleri (docs/ILK11_SECIM_SARTNAME.md §4.2, §6 madde 12).

Sözleşme: bir işlem = kopya pozisyonunun bir coinde 0'dan açılıp 0'a dönmesi (ters dönüşte iki satır); `sonuc_usd` = gerçekleşen K/Z − taker/kayma maliyeti
± funding, 1.000 $ sanal kopya ölçeğinde; `getiri` = sonuc_usd / işlemde açılan toplam $. YALNIZ raporlama: bakiye / getiri DEĞİŞMEZ (kural 6).
Maliyet oranı C = %0,045 + %0,05 = %0,095; sabit işlem tutarı 50 $ (kopya 0,0005 birim/1.000 $ ölçeği: 50/100/1000).
"""
from __future__ import annotations

import pandas as pd
import pytest

from copytrade import izleme_motoru as m
from copytrade import kopya_v3
from copytrade.defter import DAY, HOUR, FundingRates, Market, copy_ledger, sabit_tutar_egrisi
from copytrade.kurallar import load_rules

T0 = 20_833 * DAY
C = 0.00095
BASE = 1000.0
RULES = load_rules()
TUTAR_50 = lambda hesap: 50.0     # noqa: E731 — sabit tutar, hesaba bakmaz (eğri ayrı testte)


def candles(prices: dict, coin="BTC"):
    return {coin: [{"t": T0 + h * HOUR, "o": str(p), "c": str(p)} for h, p in sorted(prices.items())]}


def fill(minutes, side, size, before, px=0.0, coin="BTC"):
    return {"time": T0 + minutes * 60_000, "coin": coin, "side": side, "sz": str(size), "startPosition": str(before), "px": str(px)}


def funding_rows(hours=range(1, 6), rate="0.0001"):
    return FundingRates([{"time": T0 + h * HOUR + 5, "delta": {"coin": "BTC", "usdc": "999", "fundingRate": rate, "szi": "10"}} for h in hours])


def run(fills, market, delay=0, start=T0 - DAY, end_hours=7, rates=None, kayit=True, tutar=TUTAR_50, rules=None):
    return copy_ledger(fills, Market(market), None, delay, start, T0 + end_hours * HOUR, rates, rules or RULES, True,
                       tutar_egrisi=tutar, base_usd=BASE, style=None, islem_kaydi=kayit)


FLAT = candles({h: 100 for h in range(0, 9)})


def test_golden_12a_tek_coinde_ac_kapa_maliyet_ve_funding_elle():
    """B10@100 (saat 1), A10@110 (saat 5): kopya 0,0005 birim. K/Z 0,0005·10 = 0,005; maliyet 0,0005·100·C + 0,0005·110·C = 0,0000475 + 0,00005225;
    funding: 4 saat (1..4) · açılış 100 · oran 0,0001 = 0,04 -> −0,0005·0,04 = −0,00002. Net 0,005 − 0,0000475 − 0,00005225 − 0,00002 = 0,00488025 -> 4,88025 $; açılan 0,0005·100·1000 = 50 $."""
    out = run([fill(60, "B", 10, 0, 100), fill(300, "A", 10, 10, 110)], FLAT, rates=funding_rows())
    assert len(out["islemler"]) == 1
    t = out["islemler"][0]
    beklenen = 1000 * (0.0005 * 10 - 0.0005 * 100 * C - 0.0005 * 110 * C - 0.0005 * 0.04)
    assert t["sonuc_usd"] == pytest.approx(beklenen) == pytest.approx(4.88025)
    assert t["acilan_usd"] == pytest.approx(50.0) and t["sonuc_usd"] / t["acilan_usd"] == pytest.approx(0.097605)
    assert (t["coin"], t["neden"], t["gecerli"]) == ("BTC", "trader", True)
    assert (t["acilis_ms"], t["kapanis_ms"]) == (T0 + HOUR, T0 + 5 * HOUR)
    assert out["funding"] == pytest.approx(-0.00002)
    # Kapalı (yatay) hesapta işlem toplamı = defter neti ($): hiçbir K/Z işlemlerin dışında kalmaz
    assert sum(x["sonuc_usd"] for x in out["islemler"]) == pytest.approx(out["net"] * BASE)


def test_golden_12b_ters_donuste_iki_satir_ucret_ve_funding_bolusumu():
    """B10@100 (saat 1); A15@110 (saat 3, before 10): trader ters döner -> kopya 0,0005'i kapatır, KISA açar: 50/110/1000 = 0,000454545 birim;
    B5@105 (saat 5, before −5) kısayı kapatır. İşlem 1: K/Z 0,005, maliyet 0,0005·100·C + 0,0005·110·C (ücret miktarla bölünür: kapanan kısım
    yalnız 0,0005·110·C), funding saat 1,2: −0,0005·2·100·r. İşlem 2: K/Z 0,000454545·(110−105), maliyet 0,000454545·(110+105)·C,
    funding saat 3,4 (kısa): +0,000454545·2·100·r."""
    out = run([fill(60, "B", 10, 0, 100), fill(180, "A", 15, 10, 110), fill(300, "B", 5, -5, 105)], FLAT, rates=funding_rows())
    assert len(out["islemler"]) == 2
    s2 = 50.0 / 110.0 / 1000.0
    r = 0.0001
    t1, t2 = out["islemler"]
    assert t1["sonuc_usd"] == pytest.approx(1000 * (0.0005 * 10 - 0.0005 * (100 + 110) * C - 0.0005 * 2 * 100 * r))
    assert t2["sonuc_usd"] == pytest.approx(1000 * (s2 * 5 - s2 * (110 + 105) * C + s2 * 2 * 100 * r))
    assert t1["acilan_usd"] == pytest.approx(50.0) and t2["acilan_usd"] == pytest.approx(50.0)
    assert (t1["kapanis_ms"], t2["acilis_ms"]) == (T0 + 3 * HOUR, T0 + 3 * HOUR)                  # ters dönüş: aynı an biter / açılır
    assert t1["gecerli"] is True and t2["gecerli"] is True and t1["neden"] == t2["neden"] == "trader"
    assert sum(x["sonuc_usd"] for x in out["islemler"]) == pytest.approx(out["net"] * BASE)


def test_kismi_azaltmalar_ayni_islemdir_tek_satir():
    out = run([fill(60, "B", 10, 0, 100), fill(120, "A", 4, 10, 110), fill(180, "A", 6, 6, 120)], FLAT)
    assert len(out["islemler"]) == 1
    # kopya 0,0005: %40 (0,0002) 110'da, kalan 0,0003 120'de kapanır
    kz = 0.0002 * 10 + 0.0003 * 20
    maliyet = (0.0005 * 100 + 0.0002 * 110 + 0.0003 * 120) * C
    assert out["islemler"][0]["sonuc_usd"] == pytest.approx(1000 * (kz - maliyet))
    assert out["islemler"][0]["acilan_usd"] == pytest.approx(50.0)


def test_ekleme_acilan_tutara_yazilir_getiri_toplam_acilana_oranli():
    out = run([fill(60, "B", 10, 0, 100), fill(120, "B", 5, 10, 100), fill(180, "A", 15, 15, 110)], FLAT)
    # kopya 0,0005 + ekleme %50 = 0,00025 -> 0,00075 birim; açılan 0,0005·100 + 0,00025·100 = 0,075 = 75 $
    t = out["islemler"][0]
    assert t["acilan_usd"] == pytest.approx(75.0)
    assert t["sonuc_usd"] == pytest.approx(1000 * (0.00075 * 10 - (0.0005 * 100 + 0.00025 * 100 + 0.00075 * 110) * C))


def test_acik_islem_listelenmez_ve_coinler_ayri_islemdir():
    out = run([fill(60, "B", 10, 0, 100), fill(60, "B", 3, 0, 100, coin="ETH"), fill(180, "A", 10, 10, 110)],
              {**FLAT, **candles({h: 100 for h in range(0, 9)}, "ETH")})
    assert [t["coin"] for t in out["islemler"]] == ["BTC"] and out["acik_pozisyon_sayisi"] == 1       # ETH hâlâ açık


def test_golden_12c_t0_oncesi_acilmis_miras_pozisyon_gecerli_false():
    """Pencere başı T0. Trader T0'dan önce 10 BTC açmış (kopya o dolumu görmez); T0'dan sonra 5 ekliyor -> kopya MİRAS pozisyona taze açar:
    işlem listelenir (sonuç gerçek) ama gecerli = false. 15'i kapatınca kapanır."""
    out = run([fill(-60, "B", 10, 0, 100), fill(60, "B", 5, 10, 100), fill(180, "A", 15, 15, 110)], FLAT, start=T0)
    assert len(out["islemler"]) == 1 and out["islemler"][0]["gecerli"] is False
    assert out["islemler"][0]["sonuc_usd"] == pytest.approx(1000 * (0.0005 * 10 - 0.0005 * (100 + 110) * C))


def test_t0_oncesi_dolum_gecikmeyle_t0_sonrasi_yurutulse_de_miras_sayilir():
    """Dolum T0'dan 10 dk ÖNCE (trader pozisyonu T0 öncesi açtı); 30 dk gecikmeyle yürütme T0'dan sonra (saat 1). Açılışı trader T0 öncesi yaptığından gecerli = false."""
    market = candles({0: 100, 1: 100, 2: 100, 3: 110, 4: 110})
    out = run([fill(-10, "B", 10, 0, 100), fill(120, "A", 10, 10, 110)], market, delay=30, start=T0)
    assert len(out["islemler"]) == 1 and out["islemler"][0]["gecerli"] is False
    assert out["islemler"][0]["acilis_ms"] == T0 + HOUR and out["islemler"][0]["kapanis_ms"] == T0 + 3 * HOUR
    assert run([fill(10, "B", 10, 0, 100), fill(120, "A", 10, 10, 110)], market, delay=30, start=T0)["islemler"][0]["gecerli"] is True


def test_golden_12d_fiyatsiz_yurutme_gecerli_false_ve_eksik_dolum_sayilir():
    """Gecikme 30 dk. Saat 3'teki azaltma dolumu için mum yok (en yakın mum 1,5 saat uzakta -> eksik dolum): işlem açıkken bir dolum fiyatsız kaldığından
    gecerli = false. Karşılaştırma: tüm mumlar varsa gecerli = true."""
    eksik = candles({0: 100, 1: 100, 2: 100, 5: 100, 6: 110})
    out = run([fill(30, "B", 10, 0, 100), fill(180, "A", 4, 10, 110), fill(300, "A", 6, 6, 110)], eksik, delay=30)
    assert out["missing"] == 1 and len(out["islemler"]) == 1 and out["islemler"][0]["gecerli"] is False
    tam = candles({h: (100 if h < 6 else 110) for h in range(0, 9)})
    out2 = run([fill(30, "B", 10, 0, 100), fill(180, "A", 4, 10, 110), fill(300, "A", 6, 6, 110)], tam, delay=30)
    assert out2["missing"] == 0 and out2["islemler"][0]["gecerli"] is True


def test_acilis_dolumu_fiyatsizsa_sonraki_ekleme_islemi_gecersiz_sayar():
    """İlk dolum (açılış) fiyatsız: kopya açmaz. Trader'ın sonraki eklemesi kopyaya MİRAS pozisyona açılış gibi görünür -> gecerli = false."""
    eksik = candles({3: 100, 4: 100, 5: 110, 6: 110})                    # saat 1 civarı mum yok
    out = run([fill(30, "B", 10, 0, 100), fill(240, "B", 5, 10, 100), fill(300, "A", 15, 15, 110)], eksik, delay=30)
    assert out["missing"] == 1 and len(out["islemler"]) == 1 and out["islemler"][0]["gecerli"] is False


def test_islem_kaydi_hesabi_degistirmez_fark_sifir():
    """`islem_kaydi` True/False: sonuç sözlüğünün (islemler hariç) HER değeri aynı (eski ↔ yeni, fark 0), funding / risk / günlük seri dahil."""
    fills = [fill(60, "B", 10, 0, 100), fill(180, "A", 15, 10, 110), fill(300, "B", 5, -5, 105), fill(360, "B", 7, 0, 100)]
    rules = {**RULES, "golge_likidasyon_esigi": -0.00001}
    for rk in (RULES, rules):
        yeni = run(fills, FLAT, rates=funding_rows(), kayit=True, rules=rk)
        eski = run(fills, FLAT, rates=funding_rows(), kayit=False, rules=rk)
        assert "islemler" not in eski and "islemler" in yeni
        assert set(yeni) - {"islemler"} == set(eski)
        for key in eski:
            if key in ("daily", "exposure"):
                pd.testing.assert_series_equal(yeni[key], eski[key], check_exact=True)
            else:
                assert yeni[key] == eski[key], key


# ---------------------------------------------------------------------------------------------- v3 (hesapla) uçtan uca

T0_V3 = pd.Timestamp('2026-10-27T00:00:00Z')
NOW_V3 = pd.Timestamp('2026-10-27T12:00:00Z')
ms = lambda s: m.millis(m.timestamp(s))                                            # noqa: E731
TUTAR_1000 = sabit_tutar_egrisi(RULES)(1000.0)


def vfill(time, side, size, before, price, coin='BTC'):
    return {'time': ms(time), 'coin': coin, 'side': side, 'sz': str(size), 'startPosition': str(before), 'px': str(price),
            'tid': ms(time), 'oid': str(ms(time)), 'closedPnl': '0', 'fee': '0'}


def hourly(**prices):
    return {coin: [{'t': ms(f'2026-10-27T{h}:00Z'), 'o': p} for h, p in rows.items()] for coin, rows in prices.items()}


def v3(fills, saatlik, yurutme, funding=(), delay=30, style='intraday', rules=RULES, now=NOW_V3):
    execution = {coin: {ms(f'2026-10-27T{h}:00Z'): p for h, p in rows.items()} for coin, rows in yurutme.items()}
    return kopya_v3.hesapla(fills, saatlik, {}, execution, list(funding), T0_V3, now, delay, style, rules)


def test_golden_12_v3_kapanan_islemler_tek_coin_maliyet_funding_ve_bakiye_ayni():
    """Al 1 BTC 10:00 (yürütme 10:30 @100), sat 11:00 (yürütme 11:30 @110); funding oranı 0,0001/saat, saatlik açılış 100: pozisyon saatleri 11:00 (10:30 ile 11:30 arası
    bir saat başı) -> 1 saat. own = TUTAR_1000/100/1000. sonuc_usd = 1000·(own·10 − own·100·C − own·110·C − own·100·0,0001)."""
    rows = [{'time': ms('2026-10-27T11:00:00Z') + 5, 'delta': {'coin': 'BTC', 'usdc': '9', 'fundingRate': '0.0001', 'szi': '1'}}]
    fills = [vfill('2026-10-27T10:00:00Z', 'B', 1, 0, 99), vfill('2026-10-27T11:00:00Z', 'A', 1, 1, 111)]
    saatlik = hourly(BTC={'10:00': 99.0, '11:00': 100.0, '12:00': 110.0})
    sonuc = v3(fills, saatlik, {'BTC': {'10:30': 100.0, '11:30': 110.0}}, funding=rows)
    own = TUTAR_1000 / 100.0 / 1000.0
    assert len(sonuc['kapanan_islemler']) == 1
    t = sonuc['kapanan_islemler'][0]
    beklenen = 1000 * (own * 10 - own * 100 * C - own * 110 * C - own * 100 * 0.0001)
    assert t['sonuc_usd'] == pytest.approx(beklenen)
    assert t['getiri'] == pytest.approx(beklenen / (own * 100 * 1000))
    assert t['coin'] == 'BTC' and t['acilis'] == '2026-10-27T10:30:00Z' and t['kapanis'] == '2026-10-27T11:30:00Z'
    assert t['neden'] == 'trader' and t['gecerli'] is True
    # bakiye / getiri: işlem satırlarının toplamı + funding ile eşleşir (yatay hesap): bakiye = 1000 + Σ sonuc_usd
    assert sonuc['bakiye_usd'] == pytest.approx(1000 + t['sonuc_usd'])
    assert sonuc['getiri'] == pytest.approx(t['sonuc_usd'] / 1000)


def test_v3_zarar_kes_ve_likidasyon_nedenleri_islem_satirinda():
    rules = {**RULES, "golge_likidasyon_esigi": -0.001, "golge_v2": {**RULES["golge_v2"], "intraday": {"zarar_kes": -0.0001}}}
    fills = [vfill('2026-10-27T10:00:00Z', 'B', 10, 0, 100)]
    sonuc = v3(fills, hourly(BTC={'10:00': 100.0, '11:00': 99.0}), {'BTC': {'10:30': 100.0}}, rules=rules)
    own = TUTAR_1000 / 100.0 / 1000.0
    (t,) = sonuc['kapanan_islemler']
    assert t['neden'] == 'zarar_kes' and t['kapanis'] == '2026-10-27T11:00:00Z' and t['gecerli'] is True
    assert t['sonuc_usd'] == pytest.approx(1000 * (own * (99 - 100) - own * 100 * C - own * 99 * C))
    assert sonuc['bakiye_usd'] == pytest.approx(1000 + t['sonuc_usd'])

    rules2 = {**RULES, "golge_likidasyon_esigi": -0.0001}
    sonuc2 = v3(fills, hourly(BTC={'10:00': 100.0, '11:00': 99.0}), {'BTC': {'10:30': 100.0}}, rules=rules2)
    assert sonuc2['kapanan_islemler'][0]['neden'] == 'likidasyon' and sonuc2['tasfiye'] is True
    assert sonuc2['bakiye_usd'] == 0.0 and sonuc2['getiri'] == -1.0                                   # kapanan_islemler eklenmesi tasfiye hesabını değiştirmedi


def test_v3_ters_donuste_iki_satir_ve_miras_acilis_gecerli_false():
    """Trader pencere öncesinden 10 BTC taşıyor (startPosition 10); 10:00'da 5 ekliyor -> kopya MİRAS pozisyona taze açar (gecerli false); 11:00'da 20 satış
    (15 kapatır, 5 kısa açar) -> ilk işlem kapanır, ikinci işlem ters dönüşle YENİ açılır; 12:00'da 5 alışla kapanır (gecerli true)."""
    fills = [vfill('2026-10-27T10:00:00Z', 'B', 5, 10, 100), vfill('2026-10-27T11:00:00Z', 'A', 20, 15, 110),
             vfill('2026-10-27T12:00:00Z', 'B', 5, -5, 105)]
    saatlik = hourly(BTC={'10:00': 100.0, '11:00': 110.0, '12:00': 110.0})
    sonuc = v3(fills, saatlik, {'BTC': {'10:30': 100.0, '11:30': 110.0, '12:30': 105.0}}, now=pd.Timestamp('2026-10-27T13:00:00Z'))
    t1, t2 = sonuc['kapanan_islemler']
    assert (t1['gecerli'], t2['gecerli']) == (False, True) and sonuc['fiyatsiz_eylem'] == 0
    own = TUTAR_1000 / 100.0 / 1000.0
    # ters dönüşte KISA, kopyanın o anki değerine göre sabit tutarla açılır: değer = 1.000·(1 − açılış maliyeti + gerçekleşmemiş K/Z @110)
    deger = 1000 * (1 - own * 100 * C + own * (110 - 100))
    s2 = sabit_tutar_egrisi(RULES)(deger) / 110.0 / 1000.0
    assert t1['sonuc_usd'] == pytest.approx(1000 * (own * 10 - own * (100 + 110) * C))
    assert t2['sonuc_usd'] == pytest.approx(1000 * (s2 * 5 - s2 * (110 + 105) * C))
    assert t1['kapanis'] == t2['acilis'] == '2026-10-27T11:30:00Z' and t2['kapanis'] == '2026-10-27T12:30:00Z'
    assert sonuc['bakiye_usd'] == pytest.approx(1000 + t1['sonuc_usd'] + t2['sonuc_usd'])


def test_v3_yurutulen_dolum_yoksa_islem_yok_bakiye_binde_kalir():
    """Tek dolum, mum yok -> eksik dolum (fiyatsiz_eylem 1), kopya hiç açmaz: kapanan_islemler boş, bakiye 1.000 $ (v3'te `hesaplanamadi` dalı sabit tutarda tetiklenmez)."""
    sonuc = v3([vfill('2026-10-27T10:00:00Z', 'B', 1, 0, 100)], hourly(BTC={'10:00': 100.0}), {})
    assert sonuc['kapanan_islemler'] == [] and sonuc['fiyatsiz_eylem'] == 1 and sonuc['bakiye_usd'] == pytest.approx(1000.0)
    bos = v3([], hourly(BTC={'10:00': 100.0}), {})
    assert bos['kapanan_islemler'] == [] and bos['bakiye_usd'] == pytest.approx(1000.0)
