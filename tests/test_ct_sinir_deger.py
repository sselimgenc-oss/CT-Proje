"""Para-yolu SINIR testleri: tam sınır / sınırın hemen ötesi (denetim: %100 satır kapsamı ama zayıf sınır testi).
tasfiye_kontrol (hesap), degisti_mi + stop_iptal hata yolları (borsa_stop), sert_sinirlar, risk.coin_tavani."""
import math

import pytest

from copytrade.canli import borsa_stop as bs
from copytrade.canli import risk as rk
from copytrade.canli import sert_sinirlar as sert
from copytrade.canli.hesap import Hesap, Poz, tasfiye_fiyati
from tests.test_canli_motor import RULES


# ------------------------------------------------------------------ 1) tasfiye_kontrol: mark == tasfiye fiyatı
def _hesap(sz):
    h = Hesap(1000.0, 3.0, {"BTC": 40.0})
    h.slot_ac("a", 300.0)
    h.poz["a"] = {"BTC": Poz(sz, 100.0, 0, 3.0)}
    return h, tasfiye_fiyati(sz > 0, 100.0, 3.0, 40.0)


@pytest.mark.parametrize("sz", [1.0, -1.0])
def test_tasfiye_mark_tam_esit_tasfiye(sz):
    h, liq = _hesap(sz)
    ev = h.tasfiye_kontrol({"BTC": liq}, 5)
    assert len(ev) == 1 and ev[0]["tasfiye_px"] == liq and ev[0]["yon"] == ("uzun" if sz > 0 else "kısa")
    assert h.poz["a"].get("BTC") is None or h.poz["a"]["BTC"].sz == 0


@pytest.mark.parametrize("sz,fark", [(1.0, +1e-6), (-1.0, -1e-6)])
def test_tasfiye_mark_hemen_guvenli_tarafta_tasfiye_degil(sz, fark):
    h, liq = _hesap(sz)
    assert h.tasfiye_kontrol({"BTC": liq + fark}, 5) == []                       # long: liq üstü; short: liq altı
    assert h.poz["a"]["BTC"].sz == sz


@pytest.mark.parametrize("sz,fark", [(1.0, -1e-6), (-1.0, +1e-6)])
def test_tasfiye_mark_hemen_asinca_tasfiye(sz, fark):
    h, liq = _hesap(sz)
    assert len(h.tasfiye_kontrol({"BTC": liq + fark}, 5)) == 1


def test_tasfiye_mark_yok_veya_sifir_atlanir():
    h, _ = _hesap(1.0)
    assert h.tasfiye_kontrol({}, 1) == [] and h.tasfiye_kontrol({"BTC": 0.0}, 1) == [] and h.tasfiye_kontrol({"BTC": None}, 1) == []


def test_tasfiye_olay_alanlari_ve_kayit():
    h, liq = _hesap(1.0)
    ev = h.tasfiye_kontrol({"BTC": liq - 1.0}, 77)[0]
    assert (ev["adres"], ev["coin"], ev["mark"], ev["zaman_ms"], ev["sz"], ev["giris"]) == ("a", "BTC", liq - 1.0, 77, 1.0, 100.0)
    assert ev["pnl"] < 0 and h.tasfiyeler == [ev]
    assert ev["pnl"] == pytest.approx(liq - 100.0)                               # tasfiye fiyatında kapanır (ücret 0)


# ------------------------------------------------------------------ 2) borsa_stop.degisti_mi
E = {"long": True, "sz": 100.0, "tetik": 200.0}


def test_degisti_mi_miktar_tam_yuzde2_degismedi_ustu_degisti():
    assert bs.degisti_mi(E, {"long": True, "sz": 102.0, "tetik": 200.0}) is False      # tam %2: katı >
    assert bs.degisti_mi(E, {"long": True, "sz": 98.0, "tetik": 200.0}) is False
    assert bs.degisti_mi(E, {"long": True, "sz": 102.01, "tetik": 200.0}) is True
    assert bs.degisti_mi(E, {"long": True, "sz": 97.99, "tetik": 200.0}) is True      # azalma da sayılır (abs)


def test_degisti_mi_tetik_tam_yarim_yuzde_degismedi_ustu_degisti():
    assert bs.degisti_mi(E, {"long": True, "sz": 100.0, "tetik": 201.0}) is False      # tam %0,5
    assert bs.degisti_mi(E, {"long": True, "sz": 100.0, "tetik": 199.0}) is False
    assert bs.degisti_mi(E, {"long": True, "sz": 100.0, "tetik": 201.01}) is True
    assert bs.degisti_mi(E, {"long": True, "sz": 100.0, "tetik": 198.99}) is True
    assert bs.degisti_mi(E, dict(E)) is False


def test_degisti_mi_yon_ve_eksik_eski_deger():
    assert bs.degisti_mi(E, {"long": False, "sz": 100.0, "tetik": 200.0}) is True
    assert bs.degisti_mi({"sz": 100.0, "tetik": 200.0}, {"long": True, "sz": 100.0, "tetik": 200.0}) is True   # eski yön yok = short sayılır
    assert bs.degisti_mi({"sz": 100.0, "tetik": 200.0}, {"long": False, "sz": 100.0, "tetik": 200.0}) is False
    for eski in ({"long": True, "tetik": 200.0}, {"long": True, "sz": 0, "tetik": 200.0}, {"long": True, "sz": -1.0, "tetik": 200.0},
                 {"long": True, "sz": 100.0}, {"long": True, "sz": 100.0, "tetik": 0}, {"long": True, "sz": None, "tetik": None}):
        assert bs.degisti_mi(eski, dict(E)) is True


# ------------------------------------------------------------------ 2b) stop_iptal hata yolları
class Yur:
    """Sahte yürütücü: iptal sonuçları ve konan stoplar kontrol edilir."""
    def __init__(self, iptal_ok=True):
        self.iptal_ok, self.iptaller, self.konan, self.n = iptal_ok, [], [], 0

    def stop_koy(self, coin, long, sz, tetik, cloid):
        self.n += 1
        self.konan.append((coin, long, sz, tetik, cloid))
        return 1000 + self.n, "", tetik

    def stop_iptal(self, coin, oid):
        self.iptaller.append((coin, oid))
        return self.iptal_ok(oid) if callable(self.iptal_ok) else self.iptal_ok


def test_eski_stop_iptal_basarisiz_silinecege_ve_hata_olayi():
    b = bs.BorsaStop({"stoplar": {"BTC": {"oid": 7, "cloid": "0x5354aa", "long": True, "sz": 1.0, "tetik": 78.0}}})
    y = Yur(iptal_ok=False)
    olay = b.esitle({"BTC": {"long": True, "sz": 2.0, "tetik": 78.0}}, [{"oid": 7, "cloid": "0x5354aa", "coin": "BTC"}], y)
    assert y.iptaller == [("BTC", 7)] and len(olay["konan"]) == 1
    assert b.silinecek == [{"coin": "BTC", "oid": 7}]
    assert olay["hata"] == [{"coin": "BTC", "islem": "eski_iptal", "oid": 7}]
    assert b.stoplar["BTC"]["oid"] == 1001                                          # yeni stop kayıtlı (önce koy, sonra iptal)


def test_eski_stop_iptal_basarili_hata_yok():
    b = bs.BorsaStop({"stoplar": {"BTC": {"oid": 7, "cloid": "0x5354aa", "long": True, "sz": 1.0, "tetik": 78.0}}})
    y = Yur(iptal_ok=True)
    olay = b.esitle({"BTC": {"long": True, "sz": 2.0, "tetik": 78.0}}, [{"oid": 7, "cloid": "0x5354aa", "coin": "BTC"}], y)
    assert olay["hata"] == [] and b.silinecek == [] and y.iptaller == [("BTC", 7)]


def test_hedef_yok_iptal_basarisiz_silinecek_ve_basarili_olay():
    st = {"oid": 7, "cloid": "0x5354aa", "long": True, "sz": 1.0, "tetik": 78.0}
    b = bs.BorsaStop({"stoplar": {"ETH#yetim": dict(st)}})
    y = Yur(iptal_ok=False)
    olay = b.esitle({}, [{"oid": 7, "cloid": "0x5354aa", "coin": "ETH"}], y)
    assert y.iptaller == [("ETH", 7)]                                               # coin_adi: sonek atılır
    assert olay["hata"] == [{"coin": "ETH#yetim", "islem": "iptal", "oid": 7}] and olay["iptal"] == []
    assert b.silinecek == [{"coin": "ETH#yetim", "oid": 7}] and b.stoplar == {}
    b2 = bs.BorsaStop({"stoplar": {"BTC": dict(st)}})
    olay2 = b2.esitle({}, [{"oid": 7, "cloid": "0x5354aa", "coin": "BTC"}], Yur(True))
    assert olay2["iptal"] == [{"coin": "BTC", "oid": 7, "neden": "pozisyon_yok"}] and b2.silinecek == [] and olay2["hata"] == []


def test_yetim_iptal_basarisiz_ve_basarili():
    acik = [{"oid": 55, "cloid": "0x5354ff", "coin": "SOL"}, {"oid": 56, "cloid": "0xabc", "coin": "SOL"}, {"oid": 57, "cloid": None, "coin": "SOL"}]
    y = Yur(iptal_ok=False)
    olay = bs.BorsaStop().esitle({}, acik, y)
    assert olay["yetim"] == [{"coin": "SOL", "oid": 55, "iptal": False}] and y.iptaller == [("SOL", 55)]      # yalnız bizim önekli
    olay2 = bs.BorsaStop().esitle({}, acik, Yur(True))
    assert olay2["yetim"] == [{"coin": "SOL", "oid": 55, "iptal": True}]


def test_yetim_bilinen_stop_ve_silinecek_ve_bekleyen_dokunulmaz():
    b = bs.BorsaStop({"stoplar": {"BTC": {"oid": 1, "cloid": "0x5354a1", "long": True, "sz": 1.0, "tetik": 78.0}},
                      "silinecek": [{"coin": "ETH", "oid": 2}], "bekleyen": {"SOL": {"cloid": "0x5354A3", "long": True, "sz": 1.0, "tetik": 1.0, "yok": 0}}})
    acik = [{"oid": 1, "cloid": "0x5354a1", "coin": "BTC"}, {"oid": 2, "cloid": "0x5354a2", "coin": "ETH"}, {"oid": 3, "cloid": "0x5354a3", "coin": "SOL"}]
    y = Yur(iptal_ok=False)
    olay = b.esitle({"BTC": {"long": True, "sz": 1.0, "tetik": 78.0}}, acik, y)
    # silinecek (oid 2) yeniden iptal denenir (başarısız → kalır); bekleyen SOL benimsenir (cloid büyük/küçük harf duyarsız) → SOL hedefte yok → iptal
    assert olay["yetim"] == [] and ("ETH", 2) in y.iptaller
    assert {"coin": "ETH", "oid": 2} in b.silinecek


def test_silinecek_acikta_yoksa_dusurulur_varsa_iptal_basarisizsa_kalir():
    b = bs.BorsaStop({"silinecek": [{"coin": "ETH", "oid": 2}, {"coin": "SOL", "oid": 3}, {"coin": "BTC", "oid": 4}]})
    y = Yur(iptal_ok=lambda oid: oid == 3)
    b.esitle({}, [{"oid": 3, "cloid": "x", "coin": "SOL"}, {"oid": 4, "cloid": "x", "coin": "BTC"}], y)
    assert b.silinecek == [{"coin": "BTC", "oid": 4}] and y.iptaller == [("SOL", 3), ("BTC", 4)]      # 2 açıkta yok: iptal denenmez


def test_kayip_stop_acik_emirde_yoksa_kayip_ve_silinir_acik_none_ise_dokunulmaz():
    st = {"oid": 7, "cloid": "0x5354aa", "long": True, "sz": 1.0, "tetik": 78.0}
    b = bs.BorsaStop({"stoplar": {"BTC": dict(st)}})
    olay = b.esitle({"BTC": {"long": True, "sz": 1.0, "tetik": 78.0}}, [], Yur())
    assert olay["kayip"] == ["BTC"] and olay["konan"] == [] and b.stoplar == {}      # kayıp coinde aynı turda yeniden kurulmaz
    b2 = bs.BorsaStop({"stoplar": {"BTC": dict(st)}})
    olay2 = b2.esitle({"BTC": {"long": True, "sz": 1.0, "tetik": 78.0}}, None, Yur())
    assert olay2["kayip"] == [] and olay2["konan"] == [] and b2.stoplar["BTC"]["oid"] == 7 and b2.ilk is True


def test_bekleyen_uc_okumada_gorunmezse_duser_ikide_kalir():
    b = bs.BorsaStop({"bekleyen": {"BTC": {"cloid": "0x5354b1", "long": True, "sz": 1.0, "tetik": 1.0, "yok": 0}}})
    for beklenen in (1, 2):
        b.esitle({}, [], Yur())
        assert b.bekleyen["BTC"]["yok"] == beklenen
    b.esitle({}, [], Yur())
    assert b.bekleyen == {}


def test_bekleyen_acikta_bulunursa_benimsenir_ve_onceki_stop_iptal_edilir():
    eski = {"oid": 7, "cloid": "0x5354aa", "long": True, "sz": 1.0, "tetik": 78.0}
    b = bs.BorsaStop({"stoplar": {"BTC": eski}, "bekleyen": {"BTC": {"cloid": "0x5354b1", "long": True, "sz": 2.0, "tetik": 80.0, "yok": 1}}})
    y = Yur(iptal_ok=False)
    olay = b.esitle({"BTC": {"long": True, "sz": 2.0, "tetik": 80.0}}, [{"oid": 7, "cloid": "0x5354aa", "coin": "BTC"}, {"oid": 9, "cloid": "0x5354b1", "coin": "BTC"}], y)
    assert olay["benimsenen"] == [{"coin": "BTC", "oid": 9, "cloid": "0x5354b1"}] and b.bekleyen == {}
    assert b.stoplar["BTC"]["oid"] == 9 and b.stoplar["BTC"]["sz"] == 2.0 and b.stoplar["BTC"]["tetik"] == 80.0 and b.stoplar["BTC"]["long"] is True
    assert b.silinecek == [{"coin": "BTC", "oid": 7}] and olay["hata"] == [{"coin": "BTC", "islem": "eski_iptal", "oid": 7}]
    assert olay["konan"] == []                                                       # benimsenen stop hedefle aynı: yeniden konmaz


# ------------------------------------------------------------------ 3) sert_sinirlar: tam sınır kabul, hemen ötesi ret
def _dogrula(**kw):
    sert.gercek_kip_dogrula(kw)


@pytest.mark.parametrize("anahtar,deger", [("canli_kasa_ust_usd", 1500.0), ("canli_kasa_ust_usd", 1.0), ("canli_gunluk_kayip_oran", 0.05), ("canli_gunluk_kayip_oran", 0.0),
                                           ("canli_marj_kaldirac", 1), ("canli_marj_kaldirac", 5), ("canli_marj_kaldirac", 3), ("canli_marj_kaldirac", 1.0000001), ("canli_marj_kaldirac", 4.9999999)])
def test_sert_sinirda_ve_icinde_kabul(anahtar, deger):
    _dogrula(**{anahtar: deger})


@pytest.mark.parametrize("anahtar,deger", [("canli_kasa_ust_usd", 1500.000001), ("canli_kasa_ust_usd", 1501), ("canli_gunluk_kayip_oran", 0.05 + 1e-9),
                                           ("canli_marj_kaldirac", 5.0000001), ("canli_marj_kaldirac", 0.9999999), ("canli_marj_kaldirac", 0), ("canli_marj_kaldirac", 6)])
def test_sert_siniri_hemen_asan_reddedilir(anahtar, deger):
    with pytest.raises(ValueError, match=anahtar):
        _dogrula(**{anahtar: deger})


@pytest.mark.parametrize("anahtar", ["canli_kasa_ust_usd", "canli_gunluk_kayip_oran", "canli_marj_kaldirac"])
@pytest.mark.parametrize("deger", [math.nan, math.inf, -math.inf, "nan", "inf"])
def test_nan_ve_sonsuz_reddedilir(anahtar, deger):
    with pytest.raises(ValueError, match=anahtar):
        _dogrula(**{anahtar: deger})


def test_eksik_anahtar_atlanir_ve_etkin_kasa_ust():
    _dogrula()
    assert sert.etkin_kasa_ust({"canli_kasa_ust_usd": 1500}) == 1500.0 and sert.etkin_kasa_ust({"canli_kasa_ust_usd": 1499.5}) == 1499.5
    assert sert.etkin_kasa_ust({"canli_kasa_ust_usd": 1500.5}) == 1500.0 and sert.etkin_kasa_ust({"canli_kasa_ust_usd": 9999}) == 1500.0


# ------------------------------------------------------------------ 4) risk.coin_tavani sınırları
def _r():
    r = rk.Risk(RULES, 1000.0)
    return r, rk.coin_tavan_usd(RULES, 1000.0), float(RULES["radar_min_emir_usd"])


def test_coin_tavani_izin_tam_min_emir_kirpilir_min_doner():
    r, tavan, mn = _r()
    assert r.coin_tavani(mn + 9.0, tavan - mn) == (mn, "coin_tavani_kirpildi")            # izin == min emir: kırpılan kabul
    assert r.coin_tavani(mn + 1e-6, tavan - mn) == (mn, "coin_tavani_kirpildi")
    assert r.coin_tavani(mn + 9.0, tavan - mn + 1e-3) == (0.0, "coin_tavani")              # izin min'in hemen altı: 0
    assert r.coin_tavani(mn + 9.0, tavan - mn - 1e-3) == (pytest.approx(mn + 1e-3), "coin_tavani_kirpildi")
    assert r.coin_tavani(5.0, tavan + 50.0) == (0.0, "coin_tavani")                          # izin negatif: 0 (eksi dönmez)


def test_coin_tavani_emir_tam_izne_esit_kirpilmaz():
    r, tavan, mn = _r()
    assert r.coin_tavani(mn, tavan - mn) == (mn, "")
    assert r.coin_tavani(mn + 1e-10, tavan - mn) == (mn + 1e-10, "")                         # 1e-9 tolerans içi
    assert r.coin_tavani(50.0, 0.0) == (50.0, "")
    assert r.coin_tavani(tavan + 1.0, 0.0) == (tavan, "coin_tavani_kirpildi")
