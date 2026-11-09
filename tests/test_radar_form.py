"""R2 form puanı (copytrade/radar_form.py; RADAR_V1.md §4): elle hesaplanmış altın örnekler. Ağsız."""
import pandas as pd
import pytest

from copytrade import radar_form as f
from copytrade.kurallar import load_rules

RULES = load_rules()
HOUR = 3_600_000


V1 = {**RULES, "radar_agirlik_g": 0.35, "radar_agirlik_k": 0.15, "radar_agirlik_i1": 0.10, "radar_agirlik_i2": 0.10, "radar_agirlik_y": 0.10, "radar_agirlik_h": 0.20}   # v1 ağırlıkları (altın örnek korunur)


def test_agirliklar_toplami_bir_ve_rules_den():
    assert sum(float(RULES[f.AGIRLIK_ANAHTARI[b]]) for b in f.BILESENLER) == pytest.approx(1.0)
    # v1.1 (K-53) S4: H = 0, diğer dördü v1 değerleri / 0,80 (oranlar aynı; form 0–100)
    assert [float(RULES[f.AGIRLIK_ANAHTARI[b]]) for b in f.BILESENLER] == pytest.approx([0.35 / 0.8, 0.15 / 0.8, 0.10 / 0.8, 0.10 / 0.8, 0.10 / 0.8, 0.0])


def test_yuzdelik_altin_ornekler():
    assert f.yuzdelik_sira([1, 2, 3]) == [0.0, 50.0, 100.0]
    assert f.yuzdelik_sira([3, 1, 2]) == [100.0, 0.0, 50.0]
    assert f.yuzdelik_sira([1, 1, 3]) == [25.0, 25.0, 100.0]                  # eşitlikte ortalama sıra (0 ve 1 → 0,5 / 2 × 100)
    assert f.yuzdelik_sira([0.1, 0.3, 0.2], az_iyi=True) == [100.0, 0.0, 50.0]
    assert f.yuzdelik_sira([5]) == [50.0] and f.yuzdelik_sira([]) == []
    assert f.yuzdelik_sira([None, 1.0, 2.0]) == [0.0, 50.0, 100.0]             # None en kötü


def satir(adres, g, k, i1, i2, y, h, s72=0.0, gecti=True):
    return {"adres": adres, "gecti": gecti, "kopya_alt20": g, "kopya_getiri_7g": k, "kopya_kazanc_gun_orani": i1, "kopya_dusus": i2, "yayilma": y, "hype_payi": h,
            "kopya_getiri_72s": s72, "max_kaldirac": 3.0, "kopya_gunluk": [0.0, k]}


def test_agirlikli_form_elle():
    """A: G %100, K %50, İ1 %100, İ2 %100 (az düşüş iyi), Y %50, H %50 → 0,35×100 + 0,15×50 + 0,10×100 + 0,10×100 + 0,10×50 + 0,20×50 = 35 + 7,5 + 10 + 10 + 5 + 10 = 77,5.
    B: G 50, K 100, İ1 50, İ2 50, Y 100, H 0 → 17,5 + 15 + 5 + 5 + 10 + 0 = 52,5. C: yalnız H %100 → 20."""
    A = satir("0xA", 0.03, 0.02, 1.0, 0.01, 0.5, 0.5)
    B = satir("0xB", 0.02, 0.03, 0.5, 0.02, 0.8, 0.0)
    C = satir("0xC", 0.01, 0.01, 0.0, 0.03, 0.2, 1.0)
    puanli, soguyan = f.form_puanla([C, A, B, satir("0xD", 9, 9, 9, 0, 9, 9, gecti=False)], V1)          # gecti=False girmez
    assert [p["adres"] for p in puanli] == ["0xA", "0xB", "0xC"] and soguyan == []
    assert [p["form"] for p in puanli] == pytest.approx([77.5, 52.5, 20.0])
    assert puanli[0]["bilesenler"] == {"G": 100.0, "K": 50.0, "I1": 100.0, "I2": 100.0, "Y": 50.0, "H": 50.0}
    # v1.1 (H = 0): A 0,4375×100 + 0,1875×50 + 0,125×(100 + 100 + 50) = 84,375; B 21,875 + 18,75 + 6,25 + 6,25 + 12,5 = 65,625; C (yalnız H) = 0
    puanli, _ = f.form_puanla([C, A, B], RULES)
    assert [p["adres"] for p in puanli] == ["0xA", "0xB", "0xC"] and [p["form"] for p in puanli] == pytest.approx([84.375, 65.625, 0.0])


def test_soguyor_siniri_tam_eksi_yuzde_2_gecer():
    assert f.soguyor({"kopya_getiri_72s": -0.02}, RULES) is False             # tam sınır geçer
    assert f.soguyor({"kopya_getiri_72s": -0.020001}, RULES) is True
    assert f.soguyor({"kopya_getiri_72s": 0.0}, RULES) is False
    assert f.soguyor({"kopya_getiri_72s": None}, RULES) is True               # ölçü yok = kanıt yok
    puanli, soguyan = f.form_puanla([satir("0xA", 0.03, 0.02, 1.0, 0.01, 0.5, 0.5, s72=-0.02), satir("0xB", 0.02, 0.03, 0.5, 0.02, 0.8, 0.0, s72=-0.05)], RULES)
    assert [p["adres"] for p in puanli] == ["0xA"] and soguyan == [{"adres": "0xB", "neden": "soguyor", "kopya_getiri_72s": -0.05}]
    assert puanli[0]["bilesenler"]["G"] == 50.0                                # yüzdelik soguyor elenenler hariç havuzda (1 kişi → 50)


def test_trend_isaretleme_ust_yuzde_25_ya_da_yeni_listeleme():
    """4 coin |7 g getiri| 0,40 / 0,10 / 0,05 / 0,01 → nicelik(0,75) = 0,10 + 0,25 × (0,40 − 0,10) = 0,175 (numpy doğrusal): yalnız 0,40 trend; yeni listelenen 0,01'lik coin de trend."""
    h = {"A": {"getiri": 0.40, "yeni": False}, "B": {"getiri": -0.10, "yeni": False}, "C": {"getiri": 0.05, "yeni": False}, "D": {"getiri": 0.01, "yeni": True}}
    out = f.trend_isaretle(h, RULES)
    assert [out[c]["trend"] for c in "ABCD"] == [True, False, False, True]


def tarih(saat_ms):
    return pd.Timestamp(saat_ms, unit="ms", tz="UTC")


def test_hype_payi_elle_1_trend_1_trend_disi_coin():
    """X (trend; p0 100 → p1 200): saatlik açılış t0: 100, t0+1sa: 120, t0+2sa: 170, t0+3sa: 200. Long işlemler (ilk dolum B):
    t0+1sa'da açılan (ilerleme (120−100)/100 = 0,20 < 0,5) kâr 30 → ERKEN; t0+2sa'da açılan (0,70) kâr 10 → erken değil; Y (trend DEĞİL) erken görünen kâr 60 → sayılmaz;
    pencere öncesi açılmış (open_time yok) kâr 100 → toplama girer, erken değil; zararlı işlem −20 yok sayılır. Toplam brüt kâr = 30 + 10 + 60 + 100 = 200 → H = 30 / 200 = 0,15.
    Karşı yönde işlem (short, hareket yukarı) → erken sayılmaz."""
    t0 = 1_800_000_000_000 // HOUR * HOUR
    hareket = {"X": {"p0": 100.0, "p1": 200.0, "trend": True, "saatlik": {t0: 100.0, t0 + HOUR: 120.0, t0 + 2 * HOUR: 170.0, t0 + 3 * HOUR: 200.0}},
               "Y": {"p0": 100.0, "p1": 200.0, "trend": False, "saatlik": {t0: 100.0, t0 + HOUR: 120.0}}}
    long_ = [{"side": "B"}]
    islemler = [{"coin": "X", "open_time": tarih(t0 + HOUR + 600_000), "net_pnl": 30.0, "fills": long_},
                {"coin": "X", "open_time": tarih(t0 + 2 * HOUR), "net_pnl": 10.0, "fills": long_},
                {"coin": "Y", "open_time": tarih(t0 + HOUR), "net_pnl": 60.0, "fills": long_},
                {"coin": "X", "open_time": None, "net_pnl": 100.0, "fills": long_},
                {"coin": "X", "open_time": tarih(t0 + HOUR), "net_pnl": -20.0, "fills": long_}]
    assert f.hype_payi(islemler, hareket, RULES) == pytest.approx(0.15)
    short = [{"coin": "X", "open_time": tarih(t0), "net_pnl": 50.0, "fills": [{"side": "A"}]}]
    assert f.hype_payi(short, hareket, RULES) == 0.0                           # hareket yönümüzün tersi: erken-trend değil
    assert f.hype_payi([{"coin": "X", "open_time": tarih(t0), "net_pnl": -5.0, "fills": long_}], hareket, RULES) == 0.0     # kâr yok → 0


def test_hype_tam_yari_sinir_erken_degil():
    """İlerleme tam 0,5 → 'gerçekleşmeden' değil (sınır dışı): H = 0."""
    t0 = 1_800_000_000_000 // HOUR * HOUR
    hareket = {"X": {"p0": 100.0, "p1": 200.0, "trend": True, "saatlik": {t0: 150.0}}}
    assert f.hype_payi([{"coin": "X", "open_time": tarih(t0), "net_pnl": 10.0, "fills": [{"side": "B"}]}], hareket, RULES) == 0.0


def test_gunluk_getiri_kazanc_orani_yayilma():
    egri = [["2026-10-20", 1000.0], ["2026-10-21", 1010.0], ["2026-10-22", 1010.0], ["2026-10-23", 1005.0], ["2026-10-24", 1020.0]]
    g = f.gunluk_getiriler(egri, 1000.0)
    assert g == pytest.approx([0.0, 0.010, 0.0, -0.005, 0.015])
    assert f.kazanc_gun_orani(g) == pytest.approx(2 / 3)                        # aktif 3 gün (21, 23, 24), 2'si kazançlı; 20 ve 22 pasif
    assert f.kazanc_gun_orani([0.0, 0.0]) == 0.0
    assert f.yayilma([{"sonuc_usd": 30.0}, {"sonuc_usd": 10.0}, {"sonuc_usd": -5.0}]) == pytest.approx(1 - 30 / 40)
    assert f.yayilma([{"sonuc_usd": -5.0}]) == 0.0 and f.yayilma([]) == 0.0
    assert f.yayilma([{"sonuc_usd": 99.0, "gecerli": False}, {"sonuc_usd": 10.0, "gecerli": True}]) == 0.0      # geçersiz işlem sayılmaz → tek kârlı işlem → 0


def test_korelasyon_matrisi():
    k = f.korelasyon([{"adres": "a", "kopya_gunluk": [1.0, 2.0, 3.0]}, {"adres": "b", "kopya_gunluk": [2.0, 4.0, 6.0]}, {"adres": "c", "kopya_gunluk": [3.0, 2.0, 1.0]},
                      {"adres": "d", "kopya_gunluk": [0.0, 0.0, 0.0]}])
    assert k["adresler"] == ["a", "b", "c", "d"] and k["gun_sayisi"] == 3
    assert k["matris"][0][1] == pytest.approx(1.0) and k["matris"][0][2] == pytest.approx(-1.0) and k["matris"][0][0] == 1.0
    assert k["matris"][3][0] is None and k["matris"][3][3] is None             # sabit seri → korelasyon yok


class SahteIstemci:
    def __init__(self, fiyatlar, hata=()):
        self.fiyatlar, self.hata = fiyatlar, set(hata)

    def candles(self, coin, bas, son, interval="1h"):
        if coin in self.hata:
            raise RuntimeError("boom")
        return [{"t": t, "o": str(p)} for t, p in self.fiyatlar.get(coin, [])]


def test_coin_hareketleri_p0_p1_yeni_ve_hatali_coin_atlanir():
    kosu = 1_800_000_000_000 // HOUR * HOUR
    gun = int(RULES["radar_hype_yeni_gun"])
    bas30 = (kosu - gun * 24 * HOUR) // HOUR * HOUR
    pencere = kosu - 168 * HOUR
    eski = [(bas30, 50.0), (pencere, 100.0), (pencere + HOUR, 110.0), (kosu, 150.0)]            # 30 gün önce listelenmiş; p0 = pencere başı, p1 = son
    yeni = [(kosu - 5 * 24 * HOUR, 1.0), (kosu, 2.0)]                                           # 5 gün önce listelenmiş
    h = f.coin_hareketleri(SahteIstemci({"A": eski, "N": yeni, "B": eski}, hata=["B"]), ["A", "N", "B", "Z"], kosu, pencere, RULES)
    assert set(h) == {"A", "N"}                                                                   # B hata, Z mum yok → atlandı
    assert h["A"]["p0"] == 100.0 and h["A"]["p1"] == 150.0 and h["A"]["getiri"] == pytest.approx(0.5) and h["A"]["yeni"] is False
    assert h["N"]["yeni"] is True and h["N"]["trend"] is True
