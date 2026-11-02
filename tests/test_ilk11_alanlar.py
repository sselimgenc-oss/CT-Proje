"""İlk 11 ham alanları (copytrade/ilk11_alanlar.py): ELLE hesaplı altın örnekler (docs/ILK11_SECIM_SARTNAME.md §6 madde 6) + gerçek veri uç durumları.

Numaralar şartnamedeki altın örnek numaralarıdır (1–11, 14, 17). Girdi + beklenen sayı testin içindedir; ağ yok.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from copytrade import ilk11, ilk11_alanlar as al, olcut
from copytrade.ilk11_veri import form_esle
from copytrade.kurallar import load_rules

RULES = load_rules()
DAY = 86_400_000
HOUR = 3_600_000
T0 = 1_760_000_000_000                       # sabit ms (2025-10-09); pencereler son noktadan geriye sayılır
NOW = pd.Timestamp("2026-11-01T10:00:00Z")   # Pazar 13:00 TSİ
NOW_MS = int(NOW.value // 1_000_000)


def pf(ad, pnl, av):
    """HL portfolio biçimi: [[ad, {accountValueHistory, pnlHistory}]]; pnl / av = [(ms, değer)]."""
    return [[ad, {"accountValueHistory": [[t, str(v)] for t, v in av], "pnlHistory": [[t, str(v)] for t, v in pnl], "vlm": "0.0"}]]


def gunluk(ad, pnl, av, adim=DAY, bas=T0):
    return pf(ad, [(bas + i * adim, v) for i, v in enumerate(pnl)], [(bas + i * adim, v) for i, v in enumerate(av)])


# ------------------------------------------------------------------------------------------------ 1–3 pencere getiri / düşüş

def test_golden_1_pencere_getiri_hesap_1000_pnl_100_yatirma_getiri_degildir():
    """Hesap 1.000 $, PnL 0 -> +100, akış yok: 100/1000 = 0,10. Sonradan +1.000 $ yatırma (ΔPnL 0, hesap 1.100 -> 2.100): getiri DEĞİŞMEZ."""
    temel = gunluk("month", [0, 100], [1000, 1100])
    assert al.pencere_getiri(temel, "month", 30) == pytest.approx(0.10)
    yatirmali = gunluk("month", [0, 100, 100], [1000, 1100, 2100])
    assert al.pencere_getiri(yatirmali, "month", 30) == pytest.approx(0.10)
    # Dönem ortasında yatırma: dönem 2 getirisi 0 (sermaye 1100 + 500), dönem 3: 100 / 2100 (önceki değer) -> 1,1 · (1 + 100/2100)
    orta = gunluk("month", [0, 100, 100, 200], [1000, 1100, 2100, 2200])
    assert al.pencere_getiri(orta, "month", 30) == pytest.approx(1.1 * (1 + 100 / 2100) - 1)


def test_golden_2_yedi_gun_kesimi_sekizinci_gunden_onceki_pnl_sayilmaz():
    """Günlük noktalar g0..g8. g0->g1 +%10 (pnl 0->100, hesap 1000->1100), g1..g7 sabit, g7->g8 +%10 (pnl 100->210, hesap 1100->1210).
    7 günlük pencere (son − 7 g = g1): taban g1 -> yalnız son dönem: 110/1100 = 0,10. 8 günlük pencere (taban g0): 1,1 · 1,1 − 1 = 0,21."""
    pnl = [0, 100, 100, 100, 100, 100, 100, 100, 210]
    av = [1000, 1100, 1100, 1100, 1100, 1100, 1100, 1100, 1210]
    p = gunluk("week", pnl, av)
    assert al.pencere_getiri(p, "week", 7) == pytest.approx(0.10)
    assert al.pencere_getiri(p, "week", 8) == pytest.approx(0.21)


def test_golden_3_pencere_dusus_ozsermaye_1_1_2_0_9_1_0_ise_ceyrek():
    """Özsermaye 1,0 -> 1,2 -> 0,9 -> 1,0 (hesap 1000, 1200, 900, 1000; PnL 0, 200, −100, 0; akış yok). Zirve 1,2, dip 0,9: 1 − 0,9/1,2 = 0,25."""
    p = gunluk("month", [0, 200, -100, 0], [1000, 1200, 900, 1000])
    assert al.pencere_dusus(p, "month", 30) == pytest.approx(0.25)
    assert al.pencere_getiri(p, "month", 30) == pytest.approx(0.0)           # 0,2 · −0,25 · 0,1111: eğri 1,0'a döner


def test_golden_4_pozitif_gun_orani_gunluk_delta_5_eksi3_0_2_ise_ikide_uc():
    """Gün sonu PnL [0, 5, 2, 2, 4] -> günlük ΔPnL [+5, −3, 0, +2]: aktif (≠ 0) gün 3, pozitif 2 -> 2/3. 0 olan gün paydaya girmez."""
    p = gunluk("month", [0, 5, 2, 2, 4], [1000] * 5)
    assert al.pozitif_gun_orani(p, "month", 30) == pytest.approx(2 / 3)
    # Pencere sınırı: 3 günlük pencere yalnız son üç ΔPnL'i sayar: [−3, 0, +2] -> 1/2
    assert al.pozitif_gun_orani(p, "month", 3) == pytest.approx(1 / 2)


def test_pozitif_gun_gun_icindeki_birden_cok_noktanin_sonuncusunu_alir_ve_bos_gunu_atlar():
    """Gün 0: 3 nokta (son değer 10), gün 1 nokta yok (taşınır), gün 2: 7. ΔPnL = [0 (gün 1), −3 (gün 2)] -> aktif 1, pozitif 0 -> 0,0."""
    pnl = [(T0, 0), (T0 + 6 * HOUR, 4), (T0 + 12 * HOUR, 10), (T0 + 2 * DAY + 6 * HOUR, 7)]
    p = pf("month", pnl, [(T0, 1000), (T0 + 2 * DAY + 6 * HOUR, 1007)])
    assert al.pozitif_gun_orani(p, "month", 30) == 0.0


# ------------------------------------------------------------------------------------------------ 5 kazanma oranı

def fill(t, coin, side, sz, start, closed=0.0, fee=0.0, px=100.0):
    return {"time": t, "coin": coin, "side": side, "sz": str(sz), "px": str(px), "startPosition": str(start), "closedPnl": str(closed),
            "fee": str(fee), "tid": t}


def tur(coin, t, saat, pnl, fee=0.0):
    """Tek coin, 1 birim al, `saat` sonra sat; kapanış fill'inde closedPnl = pnl (ücret ayrı)."""
    return [fill(t, coin, "B", 1, 0), fill(t + int(saat * HOUR), coin, "A", 1, 1, closed=pnl, fee=fee)]


def test_golden_5_kazanma_orani_net_10_eksi5_3_eksi1_ise_yarim():
    fills = tur("A1", T0, 1, 10) + tur("A2", T0 + DAY, 1, -5) + tur("A3", T0 + 2 * DAY, 1, 3) + tur("A4", T0 + 3 * DAY, 1, -1)
    rounds = olcut.closed_round_trips(fills)
    assert sorted(r["net_pnl"] for r in rounds) == [-5, -1, 3, 10]
    assert olcut.kazanma_orani(rounds) == 0.5


def test_golden_5_ucret_yuzunden_eksiye_donen_islem_kaybedendir_ve_tersine_donus_iki_islemdir():
    # closedPnl +1,0 ama ücret 1,2 -> net −0,2: KAYBEDEN (ücret dahil)
    assert olcut.kazanma_orani(olcut.closed_round_trips(tur("B1", T0, 1, 1.0, fee=1.2))) == 0.0
    # +10 pozisyonda 15 satış (ters dönüş): closedPnl 3, ücret 0,6 miktarla bölünür: kapanan 10/15 · 0,6 = 0,4 -> 3 − 0,4 = 2,6 (kazanan);
    # açılan 5/15 · 0,6 = 0,2 -> yeni işlem −0,2; sonra 5 alışla kapanır (closedPnl 0, ücret 0): net −0,2 (kaybeden) -> iki işlem, oran 1/2
    flip = [fill(T0, "F", "B", 10, 0), fill(T0 + HOUR, "F", "A", 15, 10, closed=3.0, fee=0.6), fill(T0 + 2 * HOUR, "F", "B", 5, -5)]
    rounds = olcut.closed_round_trips(flip)
    assert len(rounds) == 2
    assert [round(r["net_pnl"], 9) for r in rounds] == [2.6, -0.2]
    assert olcut.kazanma_orani(rounds) == 0.5


def test_kazanma_orani_net_sifir_kazanan_degil_ve_bos_liste_none():
    assert olcut.kazanma_orani([{"net_pnl": 0.0}, {"net_pnl": 2.0}]) == 0.5
    assert olcut.kazanma_orani([]) is None


def test_calculate_metrics_kazanma_orani_bilgi_sutununu_yayimlar():
    fills = tur("A1", T0, 1, 10) + tur("A2", T0 + DAY, 1, -5) + tur("A3", T0 + 2 * DAY, 1, 3) + tur("A4", T0 + 3 * DAY, 1, -1)
    metrics = olcut.calculate_metrics(fills, [], None, account_value=1000.0)
    assert metrics["kazanma_orani"] == 0.5 and metrics["closed_trades"] == 4


# ------------------------------------------------------------------------------------------------ 6–9, 11 form (F) alanları

def tur_pencerede(i, saat, coin=None, pnl=1.0):
    """Pencere içinde (NOW − 20 g + i gün) açılıp `saat` sonra kapanan tek işlem."""
    return tur(coin or f"C{i}", NOW_MS - 20 * DAY + i * HOUR * 12, saat, pnl)


def test_golden_6_siklik_30_gunde_12_islem_ise_0_4_gun_ve_puan_0_4():
    fills = [f for i in range(12) for f in tur_pencerede(i, 1)]
    form = al.form_ham_30g(fills, [], 255_000, None, NOW, RULES)
    assert form["alanlar"]["siklik"] == pytest.approx(0.4)
    assert ilk11.siklik_puani(form["alanlar"]["siklik"]) == pytest.approx(0.4)


def test_golden_7_tutma_saatleri_1_2_30_medyan_2_saat_120_dakika_ve_puan_0_6():
    fills = tur_pencerede(0, 1) + tur_pencerede(2, 2) + tur_pencerede(4, 30)
    form = al.form_ham_30g(fills, [], 255_000, None, NOW, RULES)
    assert form["alanlar"]["tutma"] == pytest.approx(120.0)                      # DAKİKA (saat değil)
    assert ilk11.tutma_puani(120.0) == pytest.approx(1 - 0.6 * math.log10(4) / math.log10(8))
    assert ilk11.tutma_puani(120.0) == pytest.approx(0.6)


def test_golden_8_kaldirac_efektif_2x_puan_0_9():
    """Hesap 1.000 $ (allTime serisi), 20 BTC @ 100 = 2.000 $ pozisyon 4 saat açık: efektif 2,0x; kaldirac_puani(2) = 1 − |2 − 4|/20 = 0,9."""
    acilis = NOW_MS - 5 * DAY
    fills = [fill(acilis, "BTC", "B", 20, 0, px=100.0), fill(acilis + 4 * HOUR, "BTC", "A", 20, 20, px=100.0)]
    portfoy = pf("allTime", [(acilis - DAY, 0), (NOW_MS, 0)], [(acilis - DAY, 1000), (NOW_MS, 1000)])
    form = al.form_ham_30g(fills, portfoy, 1000.0, None, NOW, RULES)
    assert form["alanlar"]["kaldirac"] == pytest.approx(2.0)
    assert ilk11.kaldirac_puani(form["alanlar"]["kaldirac"]) == pytest.approx(0.9)


def test_golden_9_hesap_255000_dolar_puan_karekok_yarim():
    form = al.form_ham_30g([], [], 255_000, None, NOW, RULES)
    assert form["alanlar"]["hesap"] == 255_000
    assert ilk11.hesap_puani(form["alanlar"]["hesap"]) == pytest.approx(math.sqrt(0.5))
    assert ilk11.hesap_puani(form["alanlar"]["hesap"]) == pytest.approx(0.7071, abs=1e-4)


def v3_islem(getiri, kapanis="2026-10-25T00:00:00Z", gecerli=True):
    return {"coin": "BTC", "acilis": "2026-10-24T00:00:00Z", "kapanis": kapanis, "sonuc_usd": getiri * 20.0, "getiri": getiri,
            "neden": "trader", "gecerli": gecerli}


def test_golden_11_golge_form_getiriler_010_eksi005_020_buzulmus_ortalama_002273():
    """Ortalama (0,10 − 0,05 + 0,20)/3 = 0,08333; büzülme n/(n+k) = 3/11 (k = 8): 0,08333 · 3/11 = 0,022727."""
    v3 = {"kapanan_islemler": [v3_islem(0.10), v3_islem(-0.05), v3_islem(0.20)]}
    form = al.form_ham_30g([], [], 255_000, v3, NOW, RULES)
    assert form["alanlar"]["golge"] == pytest.approx(0.0833333 * 3 / 11, abs=1e-6)
    assert form["alanlar"]["golge"] == pytest.approx(0.02273, abs=1e-5)


def test_golge_form_yalniz_gecerli_ve_penceredeki_islemler():
    v3 = {"kapanan_islemler": [v3_islem(0.10), v3_islem(0.90, gecerli=False),                      # geçersiz: miras / fiyatsız
                               v3_islem(0.90, kapanis="2026-09-20T00:00:00Z"),                       # 30 gün dışında
                               v3_islem(0.90, kapanis="2026-11-02T00:00:00Z")]}                      # gelecekte (okuma anından sonra)
    form = al.form_ham_30g([], [], 255_000, v3, NOW, RULES)
    assert form["alanlar"]["golge"] == pytest.approx(0.10 * 1 / 9)                                   # n = 1: 0,10 · 1/(1 + 8)
    assert al.form_ham_30g([], [], 255_000, {"kapanan_islemler": []}, NOW, RULES)["alanlar"]["golge"] is None
    assert al.form_ham_30g([], [], 255_000, None, NOW, RULES)["alanlar"]["golge"] is None
    assert al.form_ham_30g([], [], 255_000, {"durum": "hesaplanamadi"}, NOW, RULES)["alanlar"]["golge"] is None


# ------------------------------------------------------------------------------------------------ 10, 17 ilk seçim (kapı satırı)

def test_golden_10_golge_ilk_tarz_gecikmesindeki_net_intraday_012_swing_030():
    satir = {"kapi_gecikme_dk": 30, "gecikme_30dk_net": 0.12, "gecikme_120dk_net": 0.30}
    alanlar, kaynak = al.ilk_alanlar(satir, RULES)
    assert alanlar["golge"] == 0.12 and kaynak["golge"] == "gecikme_30dk_net"
    alanlar, kaynak = al.ilk_alanlar({**satir, "kapi_gecikme_dk": 120}, RULES)
    assert alanlar["golge"] == 0.30 and kaynak["golge"] == "gecikme_120dk_net"
    assert al.ilk_alanlar({"gecikme_30dk_net": 0.12}, RULES)[0]["golge"] is None                       # tarz gecikmesi yok -> puansız


def test_golden_17_kapi_satirindan_median_holding_hours_3_5_tutma_210_dakika():
    assert form_esle({"medyan_tutma_saat": 3.5})[0]["tutma"] == 210                                    # #461: saat -> dakika, korunur
    alanlar, kaynak = al.ilk_alanlar({"median_holding_hours": 3.5}, RULES)
    assert alanlar["tutma"] == 210 and kaynak["tutma"] == "median_holding_hours*60"


def kapi_satiri(**over):
    satir = {"kapi_gecikme_dk": 30, "gecikme_30dk_net": 0.12, "ilk11_ay_roi": 0.2, "ilk11_hafta_roi": 0.03, "hesap_degeri_bugun": 255_000.0,
             "ilk11_dusus_30g": 0.1, "kazanma_orani": 0.55, "gunluk_islem_sikligi": 1.5, "median_holding_hours": 3.5, "median_leverage": 2.0,
             "ilk11_tutarli_30g": 0.6}
    return {**satir, **over}


def test_ilk_alanlar_tum_alanlar_dolu_ve_leaderboard_degerleri_kullanilmaz():
    alanlar, kaynak = al.ilk_alanlar(kapi_satiri(account_value=9e9, roi=1805.0), RULES)           # leaderboard sütunları ASLA okunmaz
    assert alanlar == {"golge": 0.12, "ay_roi": 0.2, "hafta_roi": 0.03, "hesap": 255_000.0, "dusus": 0.1, "kazanma": 0.55,
                       "siklik": 1.5, "tutma": 210.0, "kaldirac": 2.0, "tutarli": 0.6}
    assert list(alanlar) == list(ilk11.KALDIRAC_ALANLARI) and all(isinstance(v, str) for v in kaynak.values())


def test_ilk_alanlar_nan_ve_eksik_alan_none_kaynagi_none():
    alanlar, kaynak = al.ilk_alanlar(kapi_satiri(ilk11_ay_roi=float("nan"), kazanma_orani=None, hesap_degeri_bugun=0.0), RULES)
    assert alanlar["ay_roi"] is None and alanlar["kazanma"] is None and alanlar["hesap"] is None
    assert kaynak["ay_roi"] is None and kaynak["kazanma"] is None and kaynak["hesap"] is None
    assert al.ilk_alanlar({}, RULES)[0] == dict.fromkeys(ilk11.KALDIRAC_ALANLARI)


# ------------------------------------------------------------------------------------------------ 14 akıl sağlığı

def test_golden_14_ay_roi_1805_none_ve_ihlal_kaynagi():
    """Acil kadrodaki 1805 (leaderboard roi, %180.500) olanaksızdır: [−1, 10] dışı -> kullanılmaz."""
    alanlar, kaynak = al.ilk_alanlar(kapi_satiri(ilk11_ay_roi=1805.0), RULES)
    assert alanlar["ay_roi"] is None and kaynak["ay_roi"] == "akil_sagligi_ihlali:1805"
    alanlar, kaynak = al.ilk_alanlar(kapi_satiri(ilk11_ay_roi=-1.5), RULES)
    assert alanlar["ay_roi"] is None and kaynak["ay_roi"] == "akil_sagligi_ihlali:-1.5"


def test_golden_14_yirmi_adaydan_ikisinde_ihlal_yuzde_10_gt_5_kirmizi_biri_gecer():
    def aday(i, ihlal):
        return al.ilk_alanlar(kapi_satiri(ilk11_ay_roi=1805.0 if ihlal else 0.1), RULES)
    bir = [aday(i, i == 0) for i in range(20)]
    iki = [aday(i, i < 2) for i in range(20)]
    ozet_bir = al.doluluk_ozeti([a for a, _ in bir], [k for _, k in bir])
    ozet_iki = al.doluluk_ozeti([a for a, _ in iki], [k for _, k in iki])
    assert ozet_bir["ay_roi"] == {"toplam": 20, "dolu": 19, "eksik": 0, "ihlal": 1}
    assert al.saglik_sorunlari(ozet_bir, RULES) == []                                                # 1/20 = %5, sınırda geçer (> değil)
    sorun = al.saglik_sorunlari(ozet_iki, RULES)
    assert len(sorun) == 1 and sorun[0].startswith("ay_roi:") and "2/20" in sorun[0]


def test_akil_sagligi_tum_aralik_sinirlari():
    tam = {"golge": 10.0, "ay_roi": 10.0, "hafta_roi": 5.0, "hesap": 5000.0, "dusus": 1.0, "kazanma": 1.0, "siklik": 200.0,
           "tutma": 525_600.0, "kaldirac": 200.0, "tutarli": 1.0}
    temiz, kaynak = al.akil_sagligi(tam, None, RULES, "ilk")
    assert temiz == tam and all(not al.ihlal_mi(v) for v in kaynak.values())                          # sınırlar dahil
    kotu = {"golge": 10.1, "ay_roi": 10.1, "hafta_roi": 5.1, "hesap": 4999.0, "dusus": 1.01, "kazanma": -0.01, "siklik": 200.1,
            "tutma": 0.0, "kaldirac": 200.1, "tutarli": 1.5}
    temiz, kaynak = al.akil_sagligi(kotu, None, RULES, "ilk")
    assert all(v is None for v in temiz.values()) and all(al.ihlal_mi(v) for v in kaynak.values())     # tutma 0: alt sınır DIŞLANIR
    # golge: ilk [−1, 10], form [−1, 3]
    assert al.akil_sagligi({"golge": 5.0}, None, RULES, "ilk")[0]["golge"] == 5.0
    assert al.akil_sagligi({"golge": 5.0}, None, RULES, "form")[0]["golge"] is None
    assert al.akil_sagligi({"ay_roi": float("inf")}, None, RULES)[1]["ay_roi"] == "akil_sagligi_ihlali:inf"


def test_doluluk_sorunlari_yuzde_90_siniri():
    alanlar = [{a: (None if i < 2 else 1.0) for a in ilk11.KALDIRAC_ALANLARI} for i in range(20)]       # 2/20 eksik -> dolu %90
    kaynak = [dict.fromkeys(ilk11.KALDIRAC_ALANLARI) for _ in alanlar]
    ozet = al.doluluk_ozeti(alanlar, kaynak)
    assert al.doluluk_sorunlari(ozet, RULES) == []                                                      # tam %90 geçer (< değil)
    alanlar[2] = dict.fromkeys(ilk11.KALDIRAC_ALANLARI)
    assert len(al.doluluk_sorunlari(al.doluluk_ozeti(alanlar, kaynak), RULES)) == len(ilk11.KALDIRAC_ALANLARI)


# ------------------------------------------------------------------------------------------------ uç durumlar (gerçek veriden esinli)

def test_pnl_history_2_noktadan_az_none():
    tek = pf("month", [(T0, 5)], [(T0, 1000)])
    assert al.pencere_getiri(tek, "month", 30) is None and al.pencere_dusus(tek, "month", 30) is None
    assert al.pozitif_gun_orani(tek, "month", 30) is None
    assert al.pencere_getiri([], "month", 30) is None and al.pencere_getiri(None, "month", 30) is None
    assert al.pencere_getiri(gunluk("allTime", [0, 1], [10, 11]), "month", 30) is None                  # istenen pencere yok
    assert al.pencere_getiri(pf("month", [(T0, 0), (T0 + DAY, 5)], []), "month", 30) is None             # hesap değeri serisi yok
    assert al.kapi_bilgi_sutunlari(None, RULES) == dict.fromkeys(("ilk11_ay_roi", "ilk11_hafta_roi", "ilk11_dusus_30g", "ilk11_tutarli_30g"))


def test_hareketsiz_hesap_tutarli_none_getiri_sifir():
    p = gunluk("month", [7, 7, 7, 7], [1000] * 4)
    assert al.pozitif_gun_orani(p, "month", 30) is None                                                 # aktif gün yok: ölçülemez (0 değil)
    assert al.pencere_getiri(p, "month", 30) == 0.0 and al.pencere_dusus(p, "month", 30) == 0.0


def test_sifira_yakin_payda_olanaksiz_getiri_akil_sagligi_ile_elenir():
    """Hesap ~0 dönemi (yatırımdan önce): sermaye ≤ 0 dönem 0 getiri sayılır (sonsuz yok); sermaye 1e-9 $ ise getiri patlar (1e6+),
    alan akıl sağlığı aralığı dışında olduğundan KULLANILMAZ (1805 türü hata)."""
    sifir = gunluk("month", [0, 50, 60], [0, 0, 1000])
    assert math.isfinite(al.pencere_getiri(sifir, "month", 30)) and al.pencere_getiri(sifir, "month", 30) >= -1.0
    # hesap 1e-9 $ iken 1 $ yatırılıp aynı dönemde PnL +1 yazılırsa (akış 0): sermaye 1e-9, getiri 1e9
    patlak = pf("month", [(T0, 0), (T0 + DAY, 1.0)], [(T0, 1e-9), (T0 + DAY, 1.0 + 1e-9)])
    deger = al.pencere_getiri(patlak, "month", 30)
    assert deger > 1e6
    temiz, kaynak = al.akil_sagligi({"ay_roi": deger}, None, RULES)
    assert temiz["ay_roi"] is None and al.ihlal_mi(kaynak["ay_roi"])


def test_bos_hesap_ve_kapanmis_islemi_olmayan_trader():
    form = al.form_ham_30g([], [], None, None, NOW, RULES)
    assert form["alanlar"] == dict.fromkeys(ilk11.KALDIRAC_ALANLARI, None) | {"siklik": 0.0}          # dolum alındı ama işlem yok: 0 (puan 0)
    assert form["dolu_alan"] == 1 and form["pencere_bitis"] == "2026-11-01T10:00:00Z"
    alinamadi = al.form_ham_30g(None, [], None, None, NOW, RULES)
    assert alinamadi["alanlar"]["siklik"] is None and alinamadi["alanlar"]["kazanma"] is None        # dolum verisi YOK: ölçülemedi (0 değil)
    acik_kalan = al.form_ham_30g([fill(NOW_MS - 3 * DAY, "BTC", "B", 1, 0)], [], 10_000, None, NOW, RULES)   # yalnız açık pozisyon
    assert acik_kalan["alanlar"]["siklik"] == 0.0 and acik_kalan["alanlar"]["kazanma"] is None and acik_kalan["alanlar"]["tutma"] is None


def test_form_yalniz_pencere_icinde_kapanan_islemleri_sayar_acilisi_bilinmeyen_tutmaya_girmez():
    eski = tur("OLD", NOW_MS - 40 * DAY, 1, 5.0)                                     # 40 gün önce kapandı: pencere dışı
    miras = [fill(NOW_MS - 10 * DAY, "INH", "A", 4, 4, closed=2.0, px=100.0)]       # açılışı pencere öncesi: kazanma/siklik sayar, tutma saymaz
    yeni = tur("NEW", NOW_MS - 5 * DAY, 6, -1.0)
    form = al.form_ham_30g(eski + miras + yeni, [], 10_000, None, NOW, RULES)["alanlar"]
    assert form["siklik"] == pytest.approx(2 / 30) and form["kazanma"] == 0.5
    assert form["tutma"] == pytest.approx(6 * 60)                                    # yalnız açılışı bilinen NEW


def test_spot_dolumu_form_alanlarina_girmez():
    spot = [fill(NOW_MS - 3 * DAY, "@107", "B", 1, 0), fill(NOW_MS - 2 * DAY, "@107", "A", 1, 1, closed=9.0)]
    assert al.form_ham_30g(spot, [], 10_000, None, NOW, RULES)["alanlar"]["siklik"] == 0.0


def test_dolum_siniri_10000_dolum_hizli_ve_tutarli():
    """HL userFillsByTime tek çağrıda ~10.000 dolum döner (sınır): 5.000 işlem, 30 günde 166,7/gün -> aralık içinde ([0, 200])."""
    fills = []
    for i in range(5000):
        t = NOW_MS - 29 * DAY + i * 500_000
        fills += [fill(t, "ETH", "B", 1, 0), fill(t + 60_000, "ETH", "A", 1, 1, closed=1.0)]
    assert len(fills) == 10_000
    form = al.form_ham_30g(fills, [], 50_000, None, NOW, RULES)["alanlar"]
    assert form["siklik"] == pytest.approx(5000 / 30) and form["kazanma"] == 1.0 and form["tutma"] == pytest.approx(1.0)


def test_form_ham_30g_naif_zaman_reddedilir():
    with pytest.raises(ValueError):
        al.form_ham_30g([], [], 1000, None, "2026-11-01T10:00:00", RULES)


def test_form_ham_30g_aralik_disi_alan_ihlal_olarak_isaretlenir():
    """Kapanmamış verinin olanaksız değeri: hesap 5.000 $ altı (ana+HIP-3, spot hariç) form'da da aralık dışıdır."""
    form = al.form_ham_30g([], [], 1200.0, None, NOW, RULES)
    assert form["alanlar"]["hesap"] is None and form["alan_kaynagi"]["hesap"] == "akil_sagligi_ihlali:1200"


def test_form_tam_senaryo_portfolio_month_week_dolu():
    gun = 86_400_000
    ay = [(NOW_MS - (25 - i) * gun, 100 * i) for i in range(26)]                     # her gün +100 PnL
    av = [(NOW_MS - (25 - i) * gun, 1000 + 100 * i) for i in range(26)]
    portfoy = pf("month", ay, av) + pf("week", ay[-8:], av[-8:])
    form = al.form_ham_30g([], portfoy, 5000, None, NOW, RULES)["alanlar"]
    assert 0 < form["ay_roi"] < RULES["ilk11_saglik"]["ay_roi"][1] and 0 < form["hafta_roi"] < RULES["ilk11_saglik"]["hafta_roi"][1]
    assert form["dusus"] == 0.0 and form["tutarli"] == 1.0


def test_kapi_bilgi_sutunlari_hafta_ve_ay_ayri_pencere():
    gun = 86_400_000
    ay = [(T0 + i * gun, 100 * i) for i in range(30)]
    av = [(T0 + i * gun, 1000 + 100 * i) for i in range(30)]
    portfoy = pf("month", ay, av) + pf("week", ay[-8:], av[-8:])
    s = al.kapi_bilgi_sutunlari(portfoy, RULES)
    assert set(s) == {"ilk11_ay_roi", "ilk11_hafta_roi", "ilk11_dusus_30g", "ilk11_tutarli_30g"}
    assert s["ilk11_ay_roi"] > s["ilk11_hafta_roi"] > 0 and s["ilk11_dusus_30g"] == 0.0 and s["ilk11_tutarli_30g"] == 1.0


# ------------------------------------------------------------------------------------------------ kapı entegrasyonu (K-12.11)

def _kapi_istemcisi(portfoy):
    class Client:
        requests = 0

        def info(self, body, weight=1):
            if body["type"] == "perpDexs":
                return [None]
            if body["type"] == "spotClearinghouseState":
                return {"balances": []}
            return {"marginSummary": {"accountValue": "100"}}      # bugünkü hesap 100 $ < taban: satır "hesap değeri tabanı"nda kesilir

        def portfolio(self, address):
            return portfoy
    return Client()


def test_kapi_satiri_bilgi_sutunlarini_portfolio_ayni_yanitindan_yazar():
    from datetime import datetime, timezone

    from copytrade import kapi
    from test_asama1_payda import portfolio as alltime
    gun = 86_400_000
    ay = [(T0 + i * gun, 100 * i) for i in range(30)]
    av = [(T0 + i * gun, 1000 + 100 * i) for i in range(30)]
    portfoy = alltime([i * 100 for i in range(14)], [1000 + i * 100 for i in range(14)]) + pf("month", ay, av) + pf("week", ay[-8:], av[-8:])
    cache = type("C", (), {"requests": 0})()
    satir = kapi.evaluate_address({"address": "0xa", "accountValue": 50000.0}, _kapi_istemcisi(portfoy), cache,
                                  datetime.now(timezone.utc), 0, 0, None, RULES, dexes=[])
    assert satir["neden"] == "hesap değeri tabanı"
    beklenen = al.kapi_bilgi_sutunlari(portfoy, RULES)
    for sutun, deger in beklenen.items():
        assert satir[sutun] == deger and deger is not None, sutun
    assert 0 < satir["ilk11_ay_roi"] and satir["ilk11_dusus_30g"] == 0.0 and satir["ilk11_tutarli_30g"] == 1.0


def test_yeni_oran_sutunlari_akil_sagligi_kapisinda_0_1_disi_kirmizi():
    from copytrade.kapi import RATIO_COLUMNS, sanity_check
    from test_saglik_kapisi import good_row, table
    assert {"ilk11_dusus_30g", "ilk11_tutarli_30g", "kazanma_orani"} <= set(RATIO_COLUMNS)
    assert sanity_check(table(good_row(ilk11_dusus_30g=0.3, ilk11_tutarli_30g=0.6, kazanma_orani=0.5)), RULES) == []
    for sutun, deger in (("ilk11_dusus_30g", 1.5), ("ilk11_tutarli_30g", -0.2), ("kazanma_orani", 1.2)):
        assert any(p.startswith(sutun) for p in sanity_check(table(good_row(**{sutun: deger})), RULES)), sutun


def test_bilgi_sutunu_hatasi_kapi_sonucunu_degistirmez(monkeypatch):
    """K-12.11: bilgi sütunu hesabı patlarsa adres "veri hatası"na düşmez; 4 sütun None + `ilk11_bilgi_hatasi`, diğer her alan hatasız koşuyla birebir aynı."""
    from datetime import datetime, timezone

    from copytrade import kapi
    from test_asama1_payda import portfolio as alltime
    portfoy = alltime([i * 100 for i in range(14)], [1000 + i * 100 for i in range(14)])

    def kosu():
        return kapi.evaluate_address({"address": "0xa", "accountValue": 50000.0}, _kapi_istemcisi(portfoy),
                                     type("C", (), {"requests": 0})(), datetime.now(timezone.utc), 0, 0, None, RULES, dexes=[])
    temiz = kosu()

    def patlak(*a, **k):
        raise KeyError("bozuk portfolio")
    monkeypatch.setattr(kapi, "kapi_bilgi_sutunlari", patlak)
    hatali = kosu()
    degisken = {"now_ms", "ilk11_bilgi_hatasi"} | {k for k in hatali if k.startswith("sure_")}
    assert hatali["ilk11_bilgi_hatasi"].startswith("KeyError") and "hata" not in hatali
    for sutun in ("ilk11_ay_roi", "ilk11_hafta_roi", "ilk11_dusus_30g", "ilk11_tutarli_30g"):
        assert hatali[sutun] is None

    def ortak(r):
        return {k: v for k, v in r.items() if k not in degisken and not k.startswith("ilk11_")}
    assert ortak(hatali) == ortak(temiz)
    assert hatali["asama1"] == temiz["asama1"] and hatali["neden"] == temiz["neden"] == "hesap değeri tabanı"
