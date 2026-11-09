"""Seçim yapısı D (K-55): saf ölçüler + sahte istemciyle uçtan uca. Ağsız."""
import pytest

from copytrade import secim_d as s
from tests.test_radar_tarama import A1, A2, HOUR, MIN, RULES, Sahte, dolum
from tests.test_v11_kurallar import lider_ay

GUN = 24 * HOUR
T = 400 * GUN                                                               # "şimdi"


def pf(pnl_gunluk, hesap=20_000.0, gun=100):
    """allTime: günlük noktalar; pnl_gunluk(i) = i. günün günlük pnl'i (i = 0 en eski)."""
    pnl, kum = [], 0.0
    for i in range(gun + 1):
        kum += pnl_gunluk(i)
        pnl.append([T - (gun - i) * GUN, str(kum)])
    return [["allTime", {"pnlHistory": pnl, "accountValueHistory": [[t, str(hesap)] for t, _ in pnl]}]]


def test_portfolio_olculeri_istikrarli_ve_dalgali():
    o = s.portfolio_olculeri(pf(lambda i: 20.0), T, RULES)                  # her gün +20 $ → her hafta +140 $ = %0,7
    assert o["hesap_usd"] == 20_000.0 and o["hafta_sayisi"] == 12 and o["pozitif_hafta"] == 12
    assert o["pnl_90g"] == pytest.approx(1800.0) and o["pnl_30g"] == pytest.approx(600.0) and o["dusus_90g"] == 0.0 and o["zirve_dusus"] == 0.0
    assert o["t_istat"] is None                                             # sabit dizi: s = 0 → t yok
    assert s.evren_kapisi(o, RULES) == "t_yok"
    o2 = s.portfolio_olculeri(pf(lambda i: 20.0 + (i % 5) * 3.0), T, RULES)
    assert o2["t_istat"] > 2 and s.evren_kapisi(o2, RULES) is None
    dal = s.portfolio_olculeri(pf(lambda i: 300.0 if (i // 7) % 2 else -280.0), T, RULES)
    assert s.evren_kapisi(dal, RULES) == "istikrarsiz"
    cokus = s.portfolio_olculeri(pf(lambda i: 60.0 if i < 95 else -800.0), T, RULES)        # son 6 gün (95…100) −4.800 $ = hesabın %24'ü; 90 g pnl yine > 0
    assert cokus["pnl_90g"] > 0 and cokus["zirve_dusus"] == pytest.approx(0.24) and s.evren_kapisi(cokus, RULES) == "dusus_90g"
    assert s.portfolio_olculeri([], T, RULES)["hesap_usd"] is None and s.evren_kapisi(s.portfolio_olculeri([], T, RULES), RULES) == "hesap_az"


def test_uye_cikis_yalniz_risk_nedenleri():
    iyi = {"zirve_dusus": 0.1, "pnl_30g": 50.0}
    assert s.uye_cikis(iyi, T - GUN, T, False, 0, RULES) == (None, 0)
    assert s.uye_cikis({**iyi, "zirve_dusus": 0.25}, T - GUN, T, False, 0, RULES) == ("zirve_dusus", 0)
    assert s.uye_cikis(iyi, T - 14 * GUN, T, False, 0, RULES) == ("islem_yok", 0)
    assert s.uye_cikis(iyi, None, T, False, 0, RULES) == ("islem_yok", 0)
    assert s.uye_cikis({**iyi, "pnl_30g": -1.0}, T - GUN, T, True, 0, RULES) == (None, 1)        # ilk negatif ay: uyarı
    assert s.uye_cikis({**iyi, "pnl_30g": -1.0}, T - GUN, T, True, 1, RULES) == ("ay_negatif", 2)
    assert s.uye_cikis({**iyi, "pnl_30g": -1.0}, T - GUN, T, False, 1, RULES) == (None, 1)       # aylık kontrol dışı: sayaç değişmez
    assert s.uye_cikis(iyi, T - GUN, T, True, 1, RULES) == (None, 0)


def test_doldurma_ve_on_filtre():
    ay = "1971-02"                                                          # T = 400. gün
    assert s.doldurma_mi(None, T) and s.doldurma_mi({"radar_surum": "v1.1"}, T)
    assert not s.doldurma_mi({"radar_surum": "v2", "doldurma_ay": ay}, T) and s.doldurma_mi({"radar_surum": "v2", "doldurma_ay": "1971-01"}, T)
    rows = [lider_ay(A1, 50_000, 10, 5, 100), lider_ay(A2, 50_000, 10, 5, -1), lider_ay("0x" + "4" * 40, 9_000, 10, 5, 100)]
    assert [x["adres"] for x in s.on_filtre(rows, RULES)] == [A1]


class SahteP(Sahte):
    def __init__(self, liderler, dolumlar, portfolyo, fiyat):
        super().__init__(liderler, dolumlar, fiyat)
        self.portfolyo = portfolyo

    def portfolio(self, adres):
        return self.portfolyo.get(adres, [])


def _karli_dolumlar(bas, adet=20):
    out, t = [], bas + HOUR
    for _ in range(adet):
        out += [dolum(t, "BTC", "B", 1, 0, 100.0, tid=t), dolum(t + 90 * MIN, "BTC", "A", 1, 1, 110.0, kapanan=10.0, tid=t + 1)]
        t += 24 * HOUR
    return out


def test_kos_ilk_doldurma_sonra_ayni_ay_yalniz_uye_denetimi(tmp_path):
    bas = T - int(RULES["secim_kopya_gun"]) * GUN
    fiyat = lambda coin, ts: 110.0 if (ts - bas - HOUR) % (24 * HOUR) >= 90 * MIN else 100.0     # noqa: E731
    istikrarli = pf(lambda i: 20.0 + (i % 5) * 3.0)
    dalgali = pf(lambda i: 300.0 if (i // 7) % 2 else -280.0)
    c = SahteP([lider_ay(A1, 20_000, 100, 5_000, 600), lider_ay(A2, 20_000, 100, 5_000, 600)], {A1: _karli_dolumlar(bas), A2: _karli_dolumlar(bas)},
               {A1: istikrarli, A2: dalgali}, fiyat)
    havuz, kadro = s.kos(c, T, None, RULES, log=lambda *_: None)
    assert havuz["doldurma"] is True and kadro["radar_surum"] == "v2" and kadro["secim_yapi"] == "D"
    assert [x["adres"] for x in kadro["satirlar"]] == [A1] and kadro["satirlar"][0]["katman"] == "ilk11" and kadro["saha_n"] == 11
    assert kadro["doldurma_ay"] == "1971-02" and kadro["korelasyon"]["adresler"] == [A1]                     # D+: benzerlik matrisi dolu
    aday = next(x for x in havuz["satirlar"] if x["adres"] == A1)
    assert aday["neden"] is None and aday["kopya_getiri"] > 0 and aday["kopya_islem"] == 20
    # aynı ay ikinci koşu: doldurma yok, üye denetlenir, kalır
    c.liderler = []
    havuz2, kadro2 = s.kos(c, T + GUN, kadro, RULES, log=lambda *_: None)
    assert havuz2["doldurma"] is False and [x["adres"] for x in kadro2["satirlar"]] == [A1] and kadro2["cikanlar"] == {}
    # trader 14 gün işlem yapmazsa çıkar (yalnız risk nedeni)
    c.dolumlar = {A1: []}
    _, kadro3 = s.kos(c, T + 2 * GUN, kadro2, RULES, log=lambda *_: None)
    assert kadro3["satirlar"] == [] and kadro3["cikanlar"] == {A1: "islem_yok"}


def test_dplus_cikislari_giris_dususu_slot_sicili_motor_dusurmesi():
    iyi = {"zirve_dusus": 0.0, "pnl_30g": 50.0, "pnl_kum": 1000.0}
    giris = {"hesap_usd": 20_000.0, "pnl_kum": 5_000.0}                    # girişten beri −4.000 $ = %20
    assert s.uye_cikis(iyi, T - GUN, T, False, 0, RULES, giris) == ("giris_dusus", 0)
    assert s.uye_cikis({**iyi, "pnl_kum": 1_001.0}, T - GUN, T, False, 0, RULES, giris) == (None, 0)
    assert s.uye_cikis(iyi, T - GUN, T, True, 1, RULES, None, slot_ay_net=-0.5) == ("ay_negatif", 2)     # E: bizim slot iki ay üst üste zararda
    assert s.uye_cikis({**iyi, "pnl_30g": -9.0}, T - GUN, T, True, 1, RULES, None, slot_ay_net=0.3) == (None, 0)   # slot sicili trader pnl'inin önünde
    h = {"realize": {A1: 3.0}, "ucret": {A1: 0.5}, "funding": {A1: -0.25}}
    assert s.slot_net(h, A1) == pytest.approx(2.25) and s.slot_net(h, A2) is None and s.slot_net(None, A1) is None


def test_dplus_kopya_kapisi_kisa_islem_coin_ve_islem_sayisi():
    bas, son = T - 28 * GUN, T
    fiyat = lambda coin, ts: 110.0 if (ts - bas - HOUR) % (24 * HOUR) >= 90 * MIN else 100.0     # noqa: E731
    c = Sahte([], {}, fiyat)
    from copytrade.kalicilik_testi import SaatlikMum
    mum = SaatlikMum(c, bas, son)
    k = s.kopya_kapisi(_karli_dolumlar(bas), 20_000.0, 20_000.0, mum, bas, son, {"BTC"}, None, RULES)
    assert k["neden"] is None and k["aktif_coin"] == 1 and k["kopya_islem"] == 20 and len(k["kopya_gunluk"]) >= 20
    az = s.kopya_kapisi(_karli_dolumlar(bas, adet=6), 20_000.0, 20_000.0, mum, bas, son, {"BTC"}, None, RULES)
    assert az["neden"] == "kopya_islem_az"                                   # A: < 10 kopya işlemi
    assert s.kopya_kapisi(_karli_dolumlar(bas), 20_000.0, 20_000.0, mum, bas, son, {"BTC"}, None, {**RULES, "secim_aktif_coin_max": 0})["neden"] == "coin_fazla"


def test_kos_motor_dusurdugu_uye_kadrodan_duser(tmp_path):
    kadro = {"radar_surum": "v2", "doldurma_ay": "1971-02", "satirlar": [{"adres": A1, "sira": 1, "form": 3.0}]}
    c = SahteP([], {}, {}, lambda coin, ts: 100.0)
    _, k2 = s.kos(c, T, kadro, RULES, log=lambda *_: None, canli={"saha": {"bekleme": {A1: T + 31 * GUN}}})
    assert k2["satirlar"] == [] and k2["cikanlar"] == {A1: "motor_dustu"}
