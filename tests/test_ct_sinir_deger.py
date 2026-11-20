"""Para-yolu SINIR testleri: tam sınır / sınırın hemen ötesi (denetim: %100 satır kapsamı ama zayıf sınır testi).
tasfiye_kontrol (hesap), degisti_mi + stop_iptal hata yolları (borsa_stop), sert_sinirlar, risk.coin_tavani."""
import math

import pytest

from copytrade import boyut
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
                                           ("canli_marj_kaldirac", 1), ("canli_marj_kaldirac", 5), ("canli_marj_kaldirac", 3)])
def test_sert_sinirda_ve_icinde_kabul(anahtar, deger):
    _dogrula(**{anahtar: deger})


@pytest.mark.parametrize("anahtar,deger", [("canli_kasa_ust_usd", 1500.000001), ("canli_kasa_ust_usd", 1501), ("canli_gunluk_kayip_oran", 0.05 + 1e-9),
                                           ("canli_marj_kaldirac", 5.0000001), ("canli_marj_kaldirac", 0.9999999), ("canli_marj_kaldirac", 0), ("canli_marj_kaldirac", 6),
                                           ("canli_marj_kaldirac", 1.0000001), ("canli_marj_kaldirac", 4.9999999)])                 # D8: kesirli kaldıraç (aralık içinde bile) reddedilir
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


# ------------------------------------------------------------------ 5) risk.py: mutasyon sonrası eklenen sınır testleri
T0 = 1_700_000_000_000
GUN_MS = 86_400_000


def _risk(kasa=1000.0, durum=None, **kural):
    return rk.Risk({**RULES, **kural}, kasa, durum)


def test_gun_ve_dakika_sabitleri():
    assert rk.DAKIKA == 60_000
    assert rk.gun(GUN_MS) == "1970-01-02" and rk.gun(GUN_MS - 1) == "1970-01-01" and rk.gun(3 * GUN_MS + 5) == "1970-01-04"


def test_coin_tavan_usd_oran_slot_ve_eksik_kural():
    assert rk.coin_tavan_usd(RULES, 1000.0) == 300.0
    sadece_oran = {k: v for k, v in RULES.items() if k != "radar_slot_tavan_carpan"}
    assert rk.coin_tavan_usd(sadece_oran, 2.0) == pytest.approx(0.6) and rk.coin_tavan_usd(sadece_oran, 1000.0) == pytest.approx(300.0)   # slot kuralı yoksa yalnız oran
    kucuk_oran = {**RULES, "canli_coin_tavan_oran": 0.1}                                                                                  # oran 100 $ < slot tavanı: slot kazanır
    assert rk.coin_tavan_usd(kucuk_oran, 1000.0) == pytest.approx(float(RULES["radar_slot_tavan_carpan"]) * boyut.slot_usd(1000.0, kucuk_oran)) and 100.0 < rk.coin_tavan_usd(kucuk_oran, 1000.0)


def test_durumdan_yukleme_alanlari():
    r = _risk(durum={"zirve": 9, "gun": "g", "gun_basi": 3, "son_oz": 5, "dur": True, "dur_neden": "x", "kapat_gunu": "d"})
    assert (r.zirve, r.gun, r.gun_basi, r.son_oz, r.dur, r.dur_neden, r.kapat_gunu, r.dur_dosya) == (9.0, "g", 3.0, 5.0, True, "x", "d", True)
    bos = _risk(500.0)
    assert (bos.zirve, bos.gun, bos.gun_basi, bos.son_oz, bos.dur, bos.dur_neden, bos.kapat_gunu, bos.dur_dosya) == (500.0, None, 500.0, None, False, None, None, False)


def test_ozsermaye_ilk_cagri_taban_ve_son_oz():
    r = _risk()
    assert r.ozsermaye_isle(1000.0, T0) == [] and r.gun_basi == 1000.0 and r.son_oz == 1000.0 and r.gun == rk.gun(T0)


def test_gun_sinirinda_taban_onceki_gunun_son_ozsermayesi_f09():
    r = _risk()
    r.ozsermaye_isle(1000.0, T0)
    r.ozsermaye_isle(980.0, T0 + 1000)
    gun2 = (T0 // GUN_MS + 1) * GUN_MS
    r.ozsermaye_isle(950.0, gun2)
    assert r.gun_basi == 980.0 and r.son_oz == 950.0
    assert r.acilis_durdu["gunluk_kayip"] is False
    # gün ya da son_oz bilinmiyorsa taban güncel özsermaye (kayıtlı eski değer kullanılmaz / çökmez)
    a = _risk(durum={"gun": "2000-01-01"})
    a.ozsermaye_isle(900.0, T0)
    assert a.gun_basi == 900.0
    b = _risk(durum={"son_oz": 500.0})
    b.ozsermaye_isle(900.0, T0)
    assert b.gun_basi == 900.0


def test_gunluk_kayip_tam_esikte_olay_hemen_altinda_yok_tekrar_yok():
    r = _risk()
    r.ozsermaye_isle(1000.0, T0)
    assert r.ozsermaye_isle(951.0, T0 + 1) == []                                    # %4,9
    assert r.ozsermaye_isle(950.0, T0 + 2) == ["gunluk_kayip"]                      # tam %5
    assert r.acilis_durdu["gunluk_kayip"] is True
    assert r.ozsermaye_isle(940.0, T0 + 3) == []                                    # bayrak zaten açık: tekrar olay yok


def test_gunluk_kayip_tolerans_1e12():
    a = _risk()
    a.ozsermaye_isle(1000.0, T0)
    assert a.ozsermaye_isle(1000.0 * (1 - (0.05 - 0.5e-12)), T0 + 1) == ["gunluk_kayip"]     # eşiğin 0,5e-12 altı: tolerans içinde → tetik
    b = _risk()
    b.ozsermaye_isle(1000.0, T0)
    assert b.ozsermaye_isle(1000.0 * (1 - (0.05 - 1.5e-12)), T0 + 1) == []                   # 1,5e-12 altı: tetik yok


def test_gunluk_kapat_tam_esik_gunde_bir_kez_ve_varsayilan_1():
    r = _risk()
    r.ozsermaye_isle(1000.0, T0)
    assert r.ozsermaye_isle(901.0, T0 + 1) == ["gunluk_kayip"]
    assert r.ozsermaye_isle(900.0, T0 + 2) == ["gunluk_kapat"]                      # tam %10 (yaml 0,1)
    assert r.kapat_gunu == rk.gun(T0) and r.ozsermaye_isle(850.0, T0 + 3) == []
    gun2 = (T0 // GUN_MS + 1) * GUN_MS
    r.ozsermaye_isle(850.0, gun2)                                                    # yeni gün tabanı 850
    assert "gunluk_kapat" in r.ozsermaye_isle(765.0, gun2 + 1) and r.kapat_gunu == rk.gun(gun2)          # ertesi gün yeniden tetiklenir
    kuralsiz = rk.Risk({k: v for k, v in RULES.items() if k != "canli_gunluk_kapat_oran"}, 1000.0, {"zirve": 1000.0})
    kuralsiz.ozsermaye_isle(1000.0, T0)
    assert "gunluk_kapat" not in kuralsiz.ozsermaye_isle(10.0, T0 + 1)               # varsayılan 1,0: %99 kayıp kapatmaz
    assert "gunluk_kapat" in kuralsiz.ozsermaye_isle(0.0, T0 + 2)                    # %100 kayıp kapatır


def test_zirve_dusus_tam_esik_dur_ve_alanlar():
    r = _risk()
    r.ozsermaye_isle(1000.0, T0)
    assert "zirve_dusus" not in r.ozsermaye_isle(800.5, T0 + 1)
    assert r.dur is False
    ol = r.ozsermaye_isle(800.0, T0 + 2)
    assert "zirve_dusus" in ol and r.dur is True and r.dur_neden == "zirve_dusus" and r.dur_dosya is False
    assert "zirve_dusus" not in r.ozsermaye_isle(700.0, T0 + 3)                      # dur zaten açık: tekrar yok


def test_zirve_dusus_tolerans_ve_zirve_yukselir():
    a = _risk()
    a.ozsermaye_isle(1000.0, T0)
    assert "zirve_dusus" in a.ozsermaye_isle(1000.0 * (1 - (0.2 - 0.5e-12)), T0 + 1)
    b = _risk()
    b.ozsermaye_isle(1000.0, T0)
    assert "zirve_dusus" not in b.ozsermaye_isle(1000.0 * (1 - (0.2 - 1.5e-12)), T0 + 1)
    c = _risk()
    c.ozsermaye_isle(1200.0, T0)
    assert c.zirve == 1200.0 and c.ozsermaye_isle(960.0, T0 + 1) and c.dur is True            # düşüş yeni zirveden (%20)


def test_sifir_ve_kucuk_taban_bolme_koruması():
    z = rk.Risk(RULES, 0.0)
    assert z.ozsermaye_isle(0.0, T0) == [] and z.dur is False                       # taban/zirve 0: oran 0 (1 değil, bölme hatası yok)
    k = rk.Risk(RULES, 0.5, {"gun": rk.gun(T0), "gun_basi": 0.5})
    ol = k.ozsermaye_isle(0.4, T0)                                                  # 0,5 $ tabanı da hesaplanır (eşik 1'e bağlı değil)
    assert "gunluk_kayip" in ol and "zirve_dusus" in ol


def test_donem_yenile_ve_zirve_yenile():
    r = _risk()
    r.acilis_durdu["gunluk_kayip"] = True
    r.donem_yenile(300.0)
    assert (r.zirve, r.gun_basi, r.son_oz) == (300.0, 300.0, 300.0) and r.acilis_durdu["gunluk_kayip"] is False
    assert r.zirve_yenile(250.0) == 300.0 and r.zirve == 250.0


def test_kasa_siniri_tam_sinir_ve_tolerans():
    r = _risk()
    ust = 1000.0
    assert r.kasa_siniri_asildi(ust, ust) is False and r.acilis_durdu["kasa_siniri"] is False
    assert r.kasa_siniri_asildi(ust + 1e-9, ust) is False                           # tolerans tam sınırı
    assert r.kasa_siniri_asildi(ust + 1.5e-9, ust) is True and r.acilis_durdu["kasa_siniri"] is True
    assert r.kasa_siniri_asildi(ust - 1.0, ust) is False and r.acilis_durdu["kasa_siniri"] is False
    assert r.kasa_siniri_asildi(1500.0) is False and r.kasa_siniri_asildi(1500.01) is True    # varsayılan: etkin sert sınır


def test_acilis_izni_dur_bayrak_patlama_ve_serbest():
    r = _risk()
    assert r.acilis_izni("a", "BTC", False, T0) == (True, "")
    r.bayrak("mutabakat", True)
    assert r.acilis_izni("a", "BTC", False, T0) == (False, "mutabakat")
    r.bayrak("mutabakat", False)
    r.fren_bitis["a"] = T0 + 5
    assert r.acilis_izni("a", "BTC", False, T0) == (False, "patlama_freni")
    r.dur = True
    assert r.acilis_izni("a", "BTC", False, T0) == (False, "dur")


def test_patlama_freni_sureleri_tam_sinir():
    r = _risk()
    r.fren_bitis["a"] = 1000
    assert r.patlama_freni("a", "X", False, 999) is True
    assert r.patlama_freni("a", "X", False, 1000) is False                          # bitiş anı dahil değil
    assert _risk().patlama_freni("a", "X", False, 0) is False                       # kayıt yok: varsayılan 0, 0 < 0 değil


def test_patlama_freni_esik_8_farkli_coin_ve_kayit():
    r = _risk()
    for i in range(7):
        r.yeni_coin_kaydet("a", f"C{i}", T0 + i)
    r.yeni_coin_kaydet("a", "C0", T0 + 50)                                          # aynı coin tekrar: sayılmaz
    assert len(r.yeni_coin["a"]) == 7
    assert r.patlama_freni("a", "C3", False, T0 + 100) is False                     # yeni coin değil: sayılmaz
    assert r.patlama_freni("a", "YENI", True, T0 + 100) is True                     # 7 + yeni = 8 ≥ 8
    assert r.fren_bitis["a"] == T0 + 100 + 30 * rk.DAKIKA and "a" not in r.yeni_coin
    assert r.patlama_freni("a", "Z", False, T0 + 100 + 30 * rk.DAKIKA - 1) is True
    assert r.patlama_freni("a", "Z", False, T0 + 100 + 30 * rk.DAKIKA) is False


def test_patlama_freni_7_farkli_coin_yetmez_ve_yeni_coin_zaten_kayitli_sayilir_bir_kez():
    r = _risk()
    for i in range(6):
        r.yeni_coin_kaydet("a", f"C{i}", T0)
    assert r.patlama_freni("a", "YENI", True, T0 + 1) is False                      # 6 + 1 = 7 < 8
    assert r.patlama_freni("a", "C2", True, T0 + 1) is False                        # kayıtlı coin: yine 6 farklı
    assert "a" not in r.fren_bitis


def test_patlama_penceresi_tam_sinir():
    for sapma, beklenen in ((0, True), (-1, True), (1, False)):                     # 10 dk: tam sınırda kayıt hâlâ pencerede
        r = _risk()
        for i in range(7):
            r.yeni_coin_kaydet("a", f"C{i}", T0)
        assert r.patlama_freni("a", "YENI", True, T0 + 10 * rk.DAKIKA + sapma) is beklenen
    r = _risk()
    r.yeni_coin_kaydet("a", "C0", T0)
    assert r._pencere_coinleri("b", T0) == set() and r._pencere_coinleri("a", T0 + 1) == {"C0"}
    assert r._pencere_coinleri("a", T0 + 10 * rk.DAKIKA + 1) == set()


def test_coin_tavani_tolerans_ve_negatif_izin_kucuk_min():
    r, tavan, mn = _r()
    brut = tavan - mn
    izin = tavan - brut
    assert r.coin_tavani(izin + 1e-9, brut) == (izin + 1e-9, "")                    # tolerans tam sınırı: kırpılmaz
    assert r.coin_tavani(izin + 1.5e-9, brut) == (izin, "coin_tavani_kirpildi")
    kucuk = _risk(radar_min_emir_usd=0.5)
    assert kucuk.coin_tavani(5.0, tavan + 10.0) == (0.0, "coin_tavani")             # izin negatif: kırpılan 0 < min


def test_marj_kirp_sinirlar():
    r = _risk(radar_min_emir_usd=11)
    assert r.marj_kirp(5.0, 0.0, 11.0, 1.0) == (5.0, "")                            # izin 11 ≥ emir
    assert r.marj_kirp(50.0, 0.0, 11.0, 1.0) == (11.0, "marj_yok")                  # izin tam min emir: kabul
    assert r.marj_kirp(50.0, 0.0, 10.99, 1.0) == (0.0, "marj_yok")                  # izin min altı: 0
    assert r.marj_kirp(50.0, 4.0, 10.0, 2.0) == (12.0, "marj_yok")                  # (10 − 4) × 2
    assert r.marj_kirp(12.0, 4.0, 10.0, 2.0) == (12.0, "")                          # emir tam izne eşit
    assert r.marj_kirp(12.0 + 1e-9, 4.0, 10.0, 2.0) == (12.0 + 1e-9, "")            # tolerans tam sınırı
    assert r.marj_kirp(12.0 + 1.5e-9, 4.0, 10.0, 2.0) == (12.0, "marj_yok")
    assert r.marj_kirp(50.0, 4.0, 10.0) == (18.0, "marj_yok")                       # varsayılan kaldıraç yaml (3x)
    kucuk = _risk(radar_min_emir_usd=0.5)
    assert kucuk.marj_kirp(50.0, 20.0, 10.0, 3.0) == (0.0, "marj_yok")              # marj aşıldı: izin 0 (eksi/1 değil)


def test_sert_tolerans_ve_kasa_sinir_testleri_eklenti():
    sert.gercek_kip_dogrula({"canli_kasa_ust_usd": 1500 + 1e-9})                    # tolerans tam sınırı kabul
    with pytest.raises(ValueError, match="canli_kasa_ust_usd"):
        sert.gercek_kip_dogrula({"canli_kasa_ust_usd": 1500 + 1.5e-9})
    sert.gercek_kip_dogrula({"canli_gunluk_kayip_oran": 0.05 + 1e-12})
    with pytest.raises(ValueError, match="canli_gunluk_kayip_oran"):
        sert.gercek_kip_dogrula({"canli_gunluk_kayip_oran": 0.05 + 1.5e-12})


# ------------------------------------------------------------------ 6) borsa_stop: hedefler / yetim_hedefler / _stop_durum / bekleyen akışı (mutasyon sonrası)
def _p(sz, giris):
    return Poz(sz, giris, 0)


def test_hedefler_net_sifira_yakin_atlanir_ve_sonraki_coin_islenir():
    poz = {"a": {"A": _p(1.0, 100.0), "B": _p(1.0, 100.0), "C": _p(1e-12, 100.0), "D": _p(1.5e-12, 100.0)}, "b": {"A": _p(-1.0, 100.0)}}
    h = bs.hedefler(poz, {"A": 100.0, "B": 100.0, "C": 100.0, "D": 100.0}, 0.2, 0.0)
    assert set(h) == {"B", "D"}                                                     # A net 0 (sonrakini engellemez), C tam 1e-12 atlanır, D 1,5e-12 işlenir


def test_hedefler_giris_yoksa_atlanir_ve_sonraki_coin_islenir():
    poz = {"a": {"A": _p(1.0, 0.0), "B": _p(1.0, 100.0)}}
    assert set(bs.hedefler(poz, {"A": 100.0, "B": 100.0}, 0.2, 0.0)) == {"B"}


def test_hedefler_min_nosyonel_mark_ile_ve_tam_sinir():
    assert "A" in bs.hedefler({"a": {"A": _p(1.0, 10.0)}}, {"A": 10.0}, 0.2, 10.0)               # nosyonel tam 10 = min: stop konur
    assert "A" not in bs.hedefler({"a": {"A": _p(1.0, 10.0)}}, {"A": 9.99}, 0.2, 10.0)
    assert "A" not in bs.hedefler({"a": {"A": _p(0.2, 100.0)}}, {"A": 10.0}, 0.2, 10.0)          # nosyonel MARK ile (2 $), girişle (20 $) değil
    assert "A" in bs.hedefler({"a": {"A": _p(0.2, 100.0)}}, {}, 0.2, 10.0)                       # mark yok: girişe düşer
    poz = {"a": {"A": _p(0.01, 100.0), "B": _p(1.0, 100.0)}}
    assert set(bs.hedefler(poz, {"A": 100.0, "B": 100.0}, 0.2, 10.0)) == {"B"}                   # küçük coin sonrakini engellemez


def test_hedefler_dinamik_oran_fonksiyonu():
    h = bs.hedefler({"a": {"A": _p(1.0, 100.0), "B": _p(-1.0, 100.0)}}, {"A": 100.0, "B": 100.0}, 0.22, 0.0, oran_fn=lambda c, long, giris: 0.1 if long else 0.05)
    assert h["A"]["tetik"] == pytest.approx(90.0) and h["B"]["tetik"] == pytest.approx(105.0)


def test_yetim_hedefler_degerler_ve_anahtar():
    marks = {"ETH": 2000.0, "SOL": 100.0}
    h = bs.yetim_hedefler({"ETH": {"sz": 0.5, "mark": 1900.0}, "SOL": {"sz": -2.0, "mark": 110.0}}, marks, 0.2, 10.0)
    assert set(h) == {"ETH#yetim", "SOL#yetim"}
    assert h["ETH#yetim"] == {"long": True, "sz": 0.5, "tetik": pytest.approx(1900.0 * 0.8)}
    assert h["SOL#yetim"] == {"long": False, "sz": 2.0, "tetik": pytest.approx(110.0 * 1.2)}
    assert bs.yetim_hedefler({"ETH": {"sz": 0.5, "mark": 1900.0}}, {}, 0.2, 10.0)["ETH#yetim"]["sz"] == 0.5     # mark yok: referans mark ile nosyonel
    assert "ETH#yetim" in bs.yetim_hedefler({"ETH": {"sz": 0.5, "mark": 1900.0}}, {}, 0.2, 10.0)
    assert bs.yetim_hedefler({"X": {"sz": 0.5, "mark": 100.0}}, {"X": 100.0}, 0.2, 10.0)["X#yetim"]["long"] is True   # küçük (0,5) uzun miktar da uzun


def test_yetim_hedefler_atlama_kosullari():
    marks = {"A": 100.0, "B": 100.0, "C": 100.0, "D": 100.0}
    for y in ({"mark": 100.0}, {"sz": None, "mark": 100.0}, {"sz": 0.0, "mark": 100.0}, {"sz": 1e-12, "mark": 100.0},       # sz yok/0/tam 1e-12
              {"sz": 5.0}, {"sz": 5.0, "mark": None}, {"sz": 5.0, "mark": 0.0}, {"sz": 5.0, "mark": -1.0}):                  # referans mark yok/0/eksi
        assert bs.yetim_hedefler({"A": y}, marks, 0.2, 0.0) == {}, y
    assert set(bs.yetim_hedefler({"A": {"sz": 1.5e-12, "mark": 100.0}}, marks, 0.2, 0.0)) == {"A#yetim"}     # 1,5e-12 işlenir
    assert set(bs.yetim_hedefler({"A": {"sz": 1.0, "mark": 1.0}}, marks, 0.2, 0.0)) == {"A#yetim"}           # ref 1 geçerli
    assert set(bs.yetim_hedefler({"A": {"sz": 1.0, "mark": 0.5}}, marks, 0.2, 0.0)) == {"A#yetim"}           # ref 0,5 geçerli (ucuz coin)
    # sıralama: geçersiz kayıt sonrakini engellemez
    y = {"A": {"sz": 0.0, "mark": 100.0}, "B": {"sz": 5.0, "mark": 0.0}, "C": {"sz": 0.01, "mark": 100.0}, "D": {"sz": 1.0, "mark": 100.0}}
    assert set(bs.yetim_hedefler(y, marks, 0.2, 10.0)) == {"D#yetim"}


def test_yetim_hedefler_min_nosyonel_mark_ile_ve_tam_sinir():
    assert "A#yetim" in bs.yetim_hedefler({"A": {"sz": 1.0, "mark": 100.0}}, {"A": 10.0}, 0.2, 10.0)       # nosyonel tam 10 = min
    assert bs.yetim_hedefler({"A": {"sz": 1.0, "mark": 100.0}}, {"A": 9.99}, 0.2, 10.0) == {}
    assert bs.yetim_hedefler({"A": {"sz": 1.0, "mark": 100.0}}, {"A": 5.0}, 0.2, 10.0) == {}              # güncel mark (5), referans (100) değil
    assert bs.yetim_hedefler({"A": {"sz": 0.0, "mark": 100.0}}, {"A": 100.0}, 0.0, 0.0) == {}            # sz 0: min 0 olsa bile yok


def test_degisti_mi_eksik_eski_alan_varsayilanlari():
    yeni = {"long": True, "sz": 1.0, "tetik": 1.0}
    assert bs.degisti_mi({"long": True, "tetik": 1.0}, yeni) is True                  # eski sz yok
    assert bs.degisti_mi({"long": True, "sz": 1.0}, yeni) is True                     # eski tetik yok
    assert bs.degisti_mi({"long": True, "sz": 100.0, "tetik": 0.5}, {"long": True, "sz": 100.0, "tetik": 0.5}) is False   # ucuz coin fiyatı geçerli


class YurD(Yur):
    """stop_durum + stop_koy sonuçlarını kontrol eden sahte."""
    def __init__(self, iptal_ok=True, durum=None, koy=None, olay_sirasi=None):
        super().__init__(iptal_ok)
        self.durum, self.koy, self.sorgular, self.sira = durum or {}, koy, [], olay_sirasi if olay_sirasi is not None else []

    def stop_durum(self, cloid):
        self.sorgular.append(cloid)
        return self.durum.get(cloid)

    def stop_koy(self, coin, long, sz, tetik, cloid):
        self.sira.append("koy")
        if self.koy is not None:
            r = self.koy(coin)
            if r is not None:
                self.konan.append((coin, long, sz, tetik, cloid))
                return r
        return super().stop_koy(coin, long, sz, tetik, cloid)


def test_stop_durum_yardimcisi():
    class A:
        def stop_durum(self, c):
            return {"abc": 7}.get(c)

    class Hata:
        def stop_durum(self, c):
            raise RuntimeError("x")
    assert bs._stop_durum(A(), "abc") == 7 and bs._stop_durum(A(), "yok") is None
    assert bs._stop_durum(A(), "") is None and bs._stop_durum(A(), None) is None      # cloid yok: sorulmaz
    assert bs._stop_durum(object(), "abc") is None and bs._stop_durum(Hata(), "abc") is None


def test_ilk_durum_ve_ilk_bayragi():
    b = bs.BorsaStop()
    assert b.kalici_yaz is None and b.ilk is True and b.stoplar == {} and b.bekleyen == {} and b.ceza_ms is None
    b.esitle({}, [], Yur())
    assert b.ilk is False
    c = bs.BorsaStop()
    c.esitle({}, None, Yur())
    assert c.ilk is True                                                               # okunamadı: eşitleme yapılmadı sayılır


def test_bekleyen_eksik_alanlar_benimsemede_sifir_ve_yok_sayaci_bire_baslar():
    b = bs.BorsaStop({"bekleyen": {"BTC": {"cloid": "0x5354b1"}, "ETH": {"cloid": "0x5354b2"}}})
    b.esitle({"BTC": {"long": False, "sz": 0.0, "tetik": 0.0}}, [{"oid": 9, "cloid": "0x5354b1", "coin": "BTC"}], Yur())
    assert b.bekleyen["ETH"]["yok"] == 1                                              # sayaç yoksa 0'dan başlar → 1
    b2 = bs.BorsaStop()
    b2._benimse("BTC", 9, {"cloid": "0x5354b1"}, {"benimsenen": [], "hata": []}, Yur())
    assert b2.stoplar["BTC"] == {"oid": 9, "cloid": "0x5354b1", "long": False, "sz": 0.0, "tetik": 0.0}      # eksik alanlar 0'a düşer


def test_bekleyen_bulunamayan_sonrakini_engellemez():
    b = bs.BorsaStop({"bekleyen": {"A": {"cloid": "0x5354a1", "yok": 0}, "B": {"cloid": "0x5354b1", "long": True, "sz": 1.0, "tetik": 5.0, "yok": 0}}})
    olay = b.esitle({"B": {"long": True, "sz": 1.0, "tetik": 5.0}}, [{"oid": 9, "cloid": "0x5354b1", "coin": "B"}], Yur())
    assert olay["benimsenen"] == [{"coin": "B", "oid": 9, "cloid": "0x5354b1"}] and b.bekleyen["A"]["yok"] == 1


def test_esitle_kayip_ve_degismeyen_sonrakini_engellemez():
    st = lambda oid: {"oid": oid, "cloid": f"0x5354{oid}", "long": True, "sz": 1.0, "tetik": 78.0}      # noqa: E731
    b = bs.BorsaStop({"stoplar": {"A": st(1), "B": st(2)}})
    h = {c: {"long": True, "sz": 1.0, "tetik": 78.0} for c in ("A", "B", "C")}
    y = Yur()
    olay = b.esitle(h, [{"oid": 2, "cloid": "0x53542", "coin": "B"}], y)           # A kayıp (açıkta yok), B değişmedi, C yeni
    assert olay["kayip"] == ["A"] and [k["coin"] for k in olay["konan"]] == ["C"] and set(b.stoplar) == {"B", "C"}


def test_bekleyen_hedef_yolunda_borsaya_sorulur_benimsenir_degisirse_yenilenir():
    bek = {"cloid": "0x5354c1", "long": True, "sz": 1.0, "tetik": 78.0, "yok": 0}
    y = YurD(durum={"0x5354c1": 55})
    b = bs.BorsaStop({"bekleyen": {"BTC": dict(bek)}})
    olay = b.esitle({"BTC": {"long": True, "sz": 2.0, "tetik": 78.0}}, None, y)       # benimsenen miktar hedeften farklı: yeni stop + benimsenen iptal
    assert y.sorgular == ["0x5354c1"] and olay["benimsenen"] == [{"coin": "BTC", "oid": 55, "cloid": "0x5354c1"}]
    assert len(olay["konan"]) == 1 and ("BTC", 55) in y.iptaller and b.bekleyen == {} and b.stoplar["BTC"]["sz"] == 2.0
    y2 = YurD(durum={"0x5354c1": 55})
    b2 = bs.BorsaStop({"bekleyen": {"BTC": dict(bek)}})
    olay2 = b2.esitle({"BTC": {"long": True, "sz": 1.0, "tetik": 78.0}, "ETH": {"long": True, "sz": 1.0, "tetik": 5.0}}, None, y2)
    assert olay2["konan"] and [k["coin"] for k in olay2["konan"]] == ["ETH"] and y2.iptaller == [] and b2.stoplar["BTC"]["oid"] == 55   # aynı: yeniden konmaz, sonraki coin işlenir
    y3 = YurD(durum={})
    b3 = bs.BorsaStop({"bekleyen": {"BTC": dict(bek)}})
    b3.esitle({"BTC": {"long": True, "sz": 1.0, "tetik": 78.0}}, None, y3)            # borsa bilmiyor: yeni stop konur
    assert y3.sorgular == ["0x5354c1"] and b3.stoplar["BTC"]["oid"] == 1001


def test_stop_gonderimden_once_kalici_yaz_ve_bekleyen_kaydi_ve_hata_devam():
    sira: list = []
    y = YurD(olay_sirasi=sira, koy=lambda c: (None, "reddedildi", 0.0) if c == "A" else None)
    b = bs.BorsaStop()
    b.kalici_yaz = lambda: sira.append(("yaz", sorted(b.bekleyen)))
    olay = b.esitle({"A": {"long": True, "sz": 1.0, "tetik": 5.0}, "B": {"long": True, "sz": 1.0, "tetik": 6.0}}, None, y)
    assert sira[0] == ("yaz", ["A"]) and sira[1] == "koy"                              # yazma gönderimden ÖNCE ve bekleyen kayıtlıyken
    assert olay["hata"] == [{"coin": "A", "islem": "koy", "neden": "reddedildi"}] and [k["coin"] for k in olay["konan"]] == ["B"]
    assert b.bekleyen["A"]["yok"] == 0 and "B" not in b.bekleyen and b.stoplar["B"]["oid"] == 1001      # başarısız: kayıt kalır; başarılı: silinir
    # yazma hatası stop kurmayı engellemez
    b2 = bs.BorsaStop()

    def patla():
        raise OSError("disk")
    b2.kalici_yaz = patla
    assert len(b2.esitle({"A": {"long": True, "sz": 1.0, "tetik": 5.0}}, None, Yur())["konan"]) == 1


def test_sdk_hatasi_orderstatus_ile_sorulur_diger_nedenlerde_sorulmaz():
    h = {"A": {"long": True, "sz": 1.0, "tetik": 5.0}}
    y = YurD(koy=lambda c: (None, "sdk_hatasi: timeout", 0.0))
    b = bs.BorsaStop()
    olay = b.esitle(h, None, y)
    assert len(y.sorgular) == 1 and olay["hata"] and olay["konan_belirsiz"] == [] and "A" not in b.stoplar     # emir gitmemiş: hata
    y2 = YurD(koy=lambda c: (None, "sdk_hatasi: timeout", 0.0))
    b2 = bs.BorsaStop()
    orig = y2.stop_koy

    def koy_ve_kaydet(coin, long, sz, tetik, cloid):
        y2.durum[cloid] = 77                                                           # istek aslında gitmiş
        return orig(coin, long, sz, tetik, cloid)
    y2.stop_koy = koy_ve_kaydet
    olay2 = b2.esitle(h, None, y2)
    assert olay2["konan_belirsiz"][0]["oid"] == 77 and b2.stoplar["A"]["oid"] == 77 and olay2["hata"] == []
    y3 = YurD(koy=lambda c: (None, "reddedildi", 0.0))
    y3.durum = {}
    olay3 = bs.BorsaStop().esitle(h, None, y3)
    assert y3.sorgular == [] and olay3["konan_belirsiz"] == [] and olay3["hata"]      # sdk hatası değilse sorulmaz
    y4 = YurD()
    olay4 = bs.BorsaStop().esitle(h, None, y4)
    assert y4.sorgular == [] and len(olay4["konan"]) == 1                              # başarılı koyma: sorgu yok


# ------------------------------------------------------------------ 7) hesap.py: defter aritmetiği ve sınırları (mutasyon sonrası)
from copytrade.canli import hesap as hs  # noqa: E402


def _h(**kw):
    return Hesap(1000.0, 3.0, kw.get("maks"))


def test_poz_ve_hesap_varsayilanlari():
    p = Poz(1.0, 2.0, 3)
    assert (p.kaldirac, p.giris_ctx, p.zirve_kar) == (3.0, None, 0.0) and isinstance(p.zirve_kar, float)
    h = _h()
    assert h.dinleyici is None and h.son_niyet_cloid is None and h.kapanmis_net == 0.0 and h.tasfiyeler == []
    assert hs.EPS == 1e-12


def test_slot_ac_eski_defteri_kapanmis_nete_tasir():
    h = _h()
    h.kapanmis_net = 10.0
    h.realize["a"], h.ucret["a"], h.funding["a"] = 5.0, 2.0, 3.0
    h.slot_ac("a", 300.0)
    assert h.kapanmis_net == 10.0 + 5.0 - 2.0 + 3.0 and h.realize["a"] == h.ucret["a"] == h.funding["a"] == 0.0 and h.slot_bas["a"] == 300.0 and h.poz["a"] == {}
    h.slot_ac("yeni", 100.0)                                                          # yeni üye: kayıt yok → net 0 (varsayılanlar 0)
    assert h.kapanmis_net == 16.0


def test_donem_yenile_neti_tasir_pozisyonluysa_reddeder():
    h = _h()
    h.slot_ac("a", 300.0)
    h.kapanmis_net = 10.0
    h.realize["a"], h.ucret["a"], h.funding["a"] = 5.0, 2.0, 3.0
    h.slot_bas["eksik"] = 50.0                                                        # realize/ucret/funding kaydı yok → 0 sayılır
    eski = h.donem_yenile(2000.0, 400.0)
    assert h.kapanmis_net == 16.0 and h.kasa_usd == 2000.0 and h.slot_bas == {"a": 400.0, "eksik": 400.0}
    assert h.realize["a"] == h.ucret["a"] == h.funding["a"] == 0.0 and eski["kasa_usd"] == 1000.0 and eski["kapanmis_net"] == 10.0
    h.poz["a"]["BTC"] = Poz(1.0, 100.0, 0)
    with pytest.raises(ValueError):
        h.donem_yenile(1.0, 1.0)


def test_slot_kapat_net_tasir_ve_siler_pozisyonluysa_dokunmaz():
    h = _h()
    h.slot_ac("a", 300.0)
    h.kapanmis_net = 10.0
    h.realize["a"], h.ucret["a"], h.funding["a"] = 5.0, 2.0, 3.0
    h.slot_kapat("a")
    assert h.kapanmis_net == 16.0 and "a" not in h.poz and "a" not in h.slot_bas and "a" not in h.realize and "a" not in h.ucret and "a" not in h.funding
    h.slot_kapat("hic_yok")
    assert h.kapanmis_net == 16.0                                                     # kayıtsız: net değişmez
    h.slot_ac("b", 100.0)
    h.poz["b"]["BTC"] = Poz(1.0, 100.0, 0)
    h.realize["b"] = 9.0
    h.slot_kapat("b")
    assert h.kapanmis_net == 16.0 and h.realize["b"] == 9.0                           # açık pozisyon: silinmez


def test_ters_yonlu_var_yon_esik_ve_toz():
    h = _h()
    h.poz = {"a": {"BTC": Poz(-1.0, 100.0, 0)}, "b": {"ETH": Poz(2.0, 10.0, 0)}}
    assert h.ters_yonlu_var("x", "BTC", "B") is True and h.ters_yonlu_var("x", "BTC", "A") is False        # a short: alış ters
    assert h.ters_yonlu_var("x", "ETH", "A") is True and h.ters_yonlu_var("x", "ETH", "B") is False        # b long: satış ters
    assert h.ters_yonlu_var("a", "BTC", "B") is False                                  # kendi pozisyonu sayılmaz
    assert h.ters_yonlu_var("x", "SOL", "B") is False
    assert h.ters_yonlu_var("x", "BTC", "B", toz_usd=100.0) is False                   # nosyonel tam 100 = toz: sayılmaz
    assert h.ters_yonlu_var("x", "BTC", "B", toz_usd=99.99) is True
    assert h.ters_yonlu_var("x", "BTC", "B", {"BTC": 50.0}, toz_usd=60.0) is False     # mark ile nosyonel 50 (giriş 100 değil)
    assert h.ters_yonlu_var("x", "BTC", "B", {"BTC": 200.0}, toz_usd=150.0) is True
    kucuk = _h()
    kucuk.poz = {"a": {"BTC": Poz(-0.5, 1.0, 0)}}
    assert kucuk.ters_yonlu_var("x", "BTC", "B") is True                               # varsayılan toz 0: 0,5 $ sayılır


def test_ters_yonlu_var_eps_siniri():
    for sz, yon, beklenen in ((-1e-12, "B", False), (-1.5e-12, "B", True), (-6e-13, "B", False), (6e-13, "A", False), (1.5e-12, "A", True), (0.0, "B", False), (0.0, "A", False)):
        h = _h()
        h.poz = {"a": {"BTC": Poz(sz, 100.0, 0)}}
        assert h.ters_yonlu_var("x", "BTC", yon) is beklenen, (sz, yon)


def test_uygula_gecersiz_dolum():
    h = _h()
    for sz, px in ((0.0, 100.0), (-1.0, 100.0), (1.0, 0.0), (1.0, -1.0), (1.0, math.inf), (1.0, math.nan)):
        with pytest.raises(ValueError):
            h.uygula("a", "BTC", "B", sz, px, 0.0, 1)
    h.uygula("a", "BTC", "B", 1.0, 1.0, 0.0, 1)                                       # px 1 ve altı geçerli (ucuz coin)
    h.uygula("a", "SHIB", "B", 1.0, 0.5, 0.0, 1)
    assert h.poz["a"]["BTC"].giris == 1.0 and h.poz["a"]["SHIB"].giris == 0.5


def test_uygula_acilis_artirma_azaltma_kapanis_ve_dinleyici():
    h = _h()
    olaylar = []
    h.dinleyici = olaylar.append
    assert h.uygula("a", "BTC", "B", 1.0, 100.0, 0.5, 1000) == 0.0
    p = h.poz["a"]["BTC"]
    assert (p.sz, p.giris, p.acilis_ms, p.kaldirac, p.zirve_kar) == (1.0, 100.0, 1000, 3.0, 0.0)
    assert olaylar[-1] == {"adres": "a", "coin": "BTC", "yon": "B", "sz": 1.0, "px": 100.0, "pnl": 0.0, "ucret": 0.5, "ms": 1000, "yeni": True, "kapandi": False, "poz_sz": 1.0, "acilis_ms": 1000, "kaldirac": 3.0}
    p.zirve_kar = 0.3
    p.kaldirac = 5.0
    h.uygula("a", "BTC", "B", 1.0, 200.0, 0.0, 2000)                                  # artırma: ağırlıklı ortalama, zirve sıfırlanır
    assert (p.sz, p.giris, p.zirve_kar, p.acilis_ms) == (2.0, 150.0, 0.0, 1000) and olaylar[-1]["yeni"] is False and olaylar[-1]["acilis_ms"] == 1000 and olaylar[-1]["kaldirac"] == 5.0
    pnl = h.uygula("a", "BTC", "A", 0.5, 170.0, 0.1, 3000)                            # azaltma: long kâr
    assert pnl == pytest.approx(0.5 * 20.0) and p.sz == 1.5 and olaylar[-1]["kapandi"] is False and olaylar[-1]["poz_sz"] == 1.5 and olaylar[-1]["pnl"] == pnl
    pnl2 = h.uygula("a", "BTC", "A", 1.5, 140.0, 0.0, 4000)                           # kapanış: kayıp
    assert pnl2 == pytest.approx(1.5 * -10.0) and "BTC" not in h.poz["a"]
    assert olaylar[-1]["kapandi"] is True and olaylar[-1]["poz_sz"] == 0.0 and olaylar[-1]["acilis_ms"] == 1000 and olaylar[-1]["kaldirac"] == 5.0    # silinen pozisyondan
    assert h.realize["a"] == pytest.approx(pnl + pnl2) and h.ucret["a"] == pytest.approx(0.6)


def test_uygula_short_pnl_ve_kayitsiz_adres_varsayilanlari():
    h = _h()
    h.uygula("a", "BTC", "A", 2.0, 100.0, 0.25, 1)                                    # slot_ac yok: realize/ucret kaydı yok → 0'dan başlar
    assert h.realize["a"] == 0.0 and h.ucret["a"] == 0.25
    assert h.uygula("a", "BTC", "B", 2.0, 90.0, 0.0, 2) == pytest.approx(20.0)        # short kâr
    h2 = _h()
    h2.uygula("a", "BTC", "A", 1.0, 100.0, 0.0, 1)
    assert h2.uygula("a", "BTC", "B", 1.0, 110.0, 0.0, 2) == pytest.approx(-10.0)     # short zarar


def test_uygula_dinleyici_hatasi_hesabi_bozmaz_ve_cagrilir():
    h = _h()
    cagri = []

    def patla(e):
        cagri.append(e)
        raise RuntimeError("x")
    h.dinleyici = patla
    h.uygula("a", "BTC", "B", 1.0, 100.0, 0.0, 1)
    assert len(cagri) == 1 and h.poz["a"]["BTC"].sz == 1.0
    _h().uygula("a", "BTC", "B", 1.0, 100.0, 0.0, 1)                                  # dinleyici yok: sorunsuz


def test_uygula_eps_ve_tolerans_sinirlari():
    h = _h()
    h.poz = {"a": {"BTC": Poz(1e-12, 100.0, 5)}}                                      # tam EPS: boş pozisyon DEĞİL (artırma)
    h.uygula("a", "BTC", "B", 1.0, 200.0, 0.0, 7)
    assert h.poz["a"]["BTC"].sz != 1.0 and h.poz["a"]["BTC"].acilis_ms == 5
    h2 = _h()
    h2.poz = {"a": {"BTC": Poz(5e-13, 100.0, 5)}}                                     # EPS altı: boş sayılır, yeniden açılır
    h2.uygula("a", "BTC", "B", 1.0, 200.0, 0.0, 7)
    assert h2.poz["a"]["BTC"].sz == 1.0 and h2.poz["a"]["BTC"].acilis_ms == 7 and h2.poz["a"]["BTC"].giris == 200.0
    t = _h()
    t.poz = {"a": {"BTC": Poz(1.0, 100.0, 0)}}
    t.uygula("a", "BTC", "A", 1.0 + 1e-9, 100.0, 0.0, 1)                              # tolerans tam sınırı: kabul
    with pytest.raises(ValueError, match="ters dönüş"):
        u = _h()
        u.poz = {"a": {"BTC": Poz(1.0, 100.0, 0)}}
        u.uygula("a", "BTC", "A", 1.0 + 1.5e-9, 100.0, 0.0, 1)
    k = _h()
    k.poz = {"a": {"BTC": Poz(2e-12, 100.0, 0)}}
    k.uygula("a", "BTC", "A", 1e-12, 100.0, 0.0, 1)                                   # kalan tam 1e-12: silinmez
    assert k.poz["a"]["BTC"].sz == pytest.approx(1e-12)
    k2 = _h()
    k2.poz = {"a": {"BTC": Poz(2.5e-12, 100.0, 0)}}
    k2.uygula("a", "BTC", "A", 1e-12, 100.0, 0.0, 1)                                  # kalan 1,5e-12: silinmez
    assert "BTC" in k2.poz["a"]
    k3 = _h()
    k3.poz = {"a": {"BTC": Poz(1.5e-12 + 5e-13, 100.0, 0)}}
    k3.uygula("a", "BTC", "A", 1.5e-12, 100.0, 0.0, 1)                                # kalan 5e-13: silinir
    assert "BTC" not in k3.poz["a"]


def test_ucret_duzelt_slotlu_ve_kapanmis():
    h = _h()
    h.slot_ac("a", 100.0)
    h.ucret_duzelt("a", 0.3)
    assert h.ucret["a"] == pytest.approx(0.3) and h.kapanmis_net == 0.0
    h.ucret_duzelt("a", -0.1)
    assert h.ucret["a"] == pytest.approx(0.2)
    h.kapanmis_net = 10.0
    h.ucret_duzelt("silinmis", 0.25)
    assert h.kapanmis_net == pytest.approx(9.75) and "silinmis" not in h.ucret


def test_degerleme_poz_brut_marj_funding_ozsermaye():
    h = _h()
    h.slot_ac("a", 300.0)
    h.slot_ac("b", 300.0)
    h.poz["a"] = {"BTC": Poz(-2.0, 100.0, 0, 4.0), "ETH": Poz(1.0, 10.0, 0, 2.0)}
    h.poz["b"] = {"BTC": Poz(1.0, 100.0, 0, 5.0)}
    assert h.sz("a", "BTC") == -2.0 and h.sz("a", "SOL") == 0.0 and h.sz("zz", "BTC") == 0.0
    assert h.poz_usd("a", "BTC", None) == 200.0 and h.poz_usd("a", "BTC", 150.0) == 300.0 and h.poz_usd("a", "SOL", 150.0) == 0.0 and h.poz_usd("zz", "BTC", 1.0) == 0.0
    assert h.brut_coin("BTC", {}) == 300.0 and h.brut_coin("BTC", {"BTC": 150.0}) == 450.0 and h.brut_coin("SOL", {}) == 0.0
    assert h.brut_toplam({}) == 310.0 and h.brut_toplam({"BTC": 150.0, "ETH": 20.0}) == 470.0
    assert h.marj_toplam() == pytest.approx(200.0 / 4 + 10.0 / 2 + 100.0 / 5)
    h.funding_isle("a", 1.5)
    h.funding_isle("a", -0.5)
    h.funding_isle("yeni", 2.0)
    assert h.funding["a"] == 1.0 and h.funding["yeni"] == 2.0 and h.funding_toplam() == 3.0
    h.realize["a"], h.ucret["a"] = 7.0, 2.0
    marks = {"BTC": 90.0}
    assert h.slot_ozsermaye("a", marks) == pytest.approx(300.0 + 7.0 - 2.0 + 1.0 + (-2.0 * -10.0))
    assert h.slot_ozsermaye("yok", marks) is None
    h.slot_bas["eksik"] = 50.0                                                        # realize/ucret/funding kaydı yok → 0
    h.poz["eksik"] = {}
    assert h.slot_ozsermaye("eksik", marks) == 50.0


def test_tasfiye_mark_olmayan_coin_sonrakini_engellemez_ve_ucretsiz():
    h = Hesap(1000.0, 3.0, {"BTC": 40.0})
    h.slot_ac("a", 300.0)
    h.poz["a"] = {"ETH": Poz(1.0, 100.0, 0, 3.0), "BTC": Poz(1.0, 100.0, 0, 3.0)}
    ev = h.tasfiye_kontrol({"BTC": 1.0}, 9)                                           # ETH'nin marku yok (atlanır), BTC tasfiye
    assert [e["coin"] for e in ev] == ["BTC"] and h.ucret["a"] == 0.0


def test_to_json_from_json_gidis_donus_ve_varsayilanlar():
    h = _h()
    h.slot_ac("a", 300.0)
    for i in range(201):
        h.tasfiyeler.append({"i": i})
    h.poz["a"]["BTC"] = Poz(1.0, 100.0, 5, 4.0)
    h.son_niyet_cloid = "0xabc"
    h.belirsiz = {"c1": {"ms": 1, "deneme": 2}}
    h.kapanmis_net = 3.5
    d = h.to_json()
    assert len(d["tasfiyeler"]) == 200 and d["tasfiyeler"][0] == {"i": 1} and d["tasfiyeler"][-1] == {"i": 200}
    r = Hesap.from_json(d)
    assert r.son_niyet_cloid == "0xabc" and r.belirsiz == {"c1": {"ms": 1, "deneme": 2}} and r.kapanmis_net == 3.5 and r.poz["a"]["BTC"].kaldirac == 4.0 and r.kaldirac == 3.0
    bos = Hesap.from_json({"kasa_usd": 100.0})
    assert bos.kaldirac == 3.0 and bos.kapanmis_net == 0.0 and bos.belirsiz == {} and bos.son_niyet_cloid is None and bos.maks_kaldirac == {}
    assert Hesap.from_json({"kasa_usd": 100.0, "belirsiz": None}).belirsiz == {}


def test_gunluk_kapat_tolerans_1e12():
    a = _risk()
    a.ozsermaye_isle(1000.0, T0)
    assert "gunluk_kapat" in a.ozsermaye_isle(1000.0 * (1 - (0.1 - 0.5e-12)), T0 + 1)     # eşiğin 0,5e-12 altı: tolerans içinde → tetik
    b = _risk()
    b.ozsermaye_isle(1000.0, T0)
    assert "gunluk_kapat" not in b.ozsermaye_isle(1000.0 * (1 - (0.1 - 1.5e-12)), T0 + 1)  # 1,5e-12 altı: tetik yok


def test_stop_durum_bos_cloid_sorulmaz_her_zaman_oid_donen_yurutucu():
    class Hep:
        cagri = 0

        def stop_durum(self, c):
            Hep.cagri += 1
            return 7
    assert bs._stop_durum(Hep(), "") is None and bs._stop_durum(Hep(), None) is None and Hep.cagri == 0
    assert bs._stop_durum(Hep(), "x") == 7 and Hep.cagri == 1


def test_dinleyici_yeni_bayragi_tam_eps_pozisyonda_false():
    h = _h()
    olaylar = []
    h.dinleyici = olaylar.append
    h.poz = {"a": {"BTC": Poz(1e-12, 100.0, 5)}}
    h.uygula("a", "BTC", "B", 1.0, 100.0, 0.0, 7)
    assert olaylar[-1]["yeni"] is False
