"""K-73 (kullanıcı kararı 19.11 gece): SANAL kipte rejim/haber/HIP-3/gölge kurallar/drift/iz süren koruma işlem etkiler; GERÇEK kip aynen. Yalnız atlar/küçültür; kapanış/azaltma asla engellenmez."""
from __future__ import annotations

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from copytrade.canli.ogrenme_adaptor import Ogrenme, takma_ad
from copytrade.kurallar import load_rules
from tests.test_canli_motor import SahteHL, adr, kadro, kayitlar, kur, olay, satir


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _motor(tmp_path, **kurallar):
    k = kadro([satir(1, 1)], 0)
    m, hl, saat, _ = kur(tmp_path, kadro_=k, hl=SahteHL(), kurallar=kurallar)
    k["kosu_ms"] = saat() - 3_600_000
    m.baslat()
    return m, saat


def _rejim(m, saat, coin, d1, h4):
    m.rejim_anlik = {"gecerli_son_ms": saat() + 10_000_000, "rejimler": {coin: {"1d": d1, "4h": h4}}}


def _haber(m, saat, ton, adet):
    t = saat()
    m.haber_anlik = {"haber_ms": t, "haberler": [{"t": t - 1000 * i, "b": "bitcoin gelismesi", "ton": ton} for i in range(adet)]}


def _ac(m, saat, yon="B", coin="BTC", no="x:1", sz=300):
    return m.olay_isle(olay(no, adr(1), coin, yon, sz, 100.0, 0.0, saat))[0]


def test_etiketler_ve_yaml_varsayilanlari():
    for n in ("rejim_ters", "haber_ters", "hesap_kucuk", "kaldirac_cok_yuksek", "iz_suren_koruma"):
        assert tg.ATLA_TR.get(n)
    r = load_rules()
    assert r["sanal_rejim_filtre"] is r["sanal_haber_filtre"] is r["sanal_hip3_kopya"] is r["sanal_golge_kurallar_etkin"] is r["sanal_iz_suren"] is True
    assert r["sanal_haber_min_baslik"] == 2 and r["canli_hip3_kopya"] is False and r["radar_hip3_kopya"] is True


# ---------------------------------------------------------------- 1) rejim
def test_rejim_ters_long_atlanir_sanal(tmp_path):
    m, saat = _motor(tmp_path)
    _rejim(m, saat, "BTC", "trend_down", "trend_down")
    s = _ac(m, saat)
    assert (s.karar, s.neden) == ("atlandi", "rejim_ters") and m.hesap.sz(adr(1), "BTC") == 0.0
    assert m.neden_say["rejim_ters"] == 1 and [x for x in kayitlar(tmp_path, "emir_yok") if x["neden"] == "rejim_ters"]


def test_rejim_ters_short_atlanir_tek_etiket_veya_bilinmeyen_atlamaz(tmp_path):
    m, saat = _motor(tmp_path)
    _rejim(m, saat, "BTC", "trend_up", "trend_up")
    assert _ac(m, saat, "A", no="x:1").neden == "rejim_ters"
    _rejim(m, saat, "BTC", "trend_down", "range")                 # yalnız biri ters
    assert _ac(m, saat, "B", no="x:2").karar == "emir"
    m2, saat2 = _motor(tmp_path / "b")
    _rejim(m2, saat2, "BTC", "trend_down", None)                  # bilinmeyen etiket
    assert _ac(m2, saat2).karar == "emir"


def test_rejim_ters_kapanisi_engellemez_ve_bayrak_kapaliysa_atlamaz(tmp_path):
    m, saat = _motor(tmp_path)
    assert _ac(m, saat).karar == "emir"
    _rejim(m, saat, "BTC", "trend_down", "trend_down")
    s = m.olay_isle(olay("x:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))[0]
    assert s.eylem == "kapat" and s.karar == "emir"
    m2, saat2 = _motor(tmp_path / "b", sanal_rejim_filtre=False)
    _rejim(m2, saat2, "BTC", "trend_down", "trend_down")
    assert _ac(m2, saat2).karar == "emir"


def test_sanal_filtreler_gercek_kipte_etkisiz(tmp_path):
    m, saat = _motor(tmp_path)
    _rejim(m, saat, "BTC", "trend_down", "trend_down")
    _haber(m, saat, "negatif", 3)
    m._golge_acik[adr(1)] = ["A_hesap_5k", "B_kaldirac_20x"]
    assert m._sanal_acilis_filtresi(adr(1), "BTC", True, saat())[0] == "rejim_ters"
    m.kip = "gercek"
    assert m._sanal_acilis_filtresi(adr(1), "BTC", True, saat()) == (None, 1.0)


# ---------------------------------------------------------------- 2) haber
def test_haber_ters_atlanir_ve_esikler(tmp_path):
    m, saat = _motor(tmp_path)
    _haber(m, saat, "negatif", 2)
    s = _ac(m, saat)
    assert (s.karar, s.neden) == ("atlandi", "haber_ters")
    _haber(m, saat, "negatif", 1)                                  # eşik altı
    assert _ac(m, saat, no="x:2").karar == "emir"
    m2, saat2 = _motor(tmp_path / "b")
    _haber(m2, saat2, "pozitif", 5)                                # long için pozitif = aynı yön: atlamaz
    assert _ac(m2, saat2).karar == "emir"
    m3, saat3 = _motor(tmp_path / "c")
    _haber(m3, saat3, "pozitif", 2)                                # short için pozitif = ters
    assert _ac(m3, saat3, "A").neden == "haber_ters"


def test_haber_ters_kapanis_engellenmez(tmp_path):
    m, saat = _motor(tmp_path)
    assert _ac(m, saat).karar == "emir"
    _haber(m, saat, "negatif", 4)
    s = m.olay_isle(olay("x:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))[0]
    assert s.eylem == "kapat" and s.karar == "emir"


# ---------------------------------------------------------------- 3) HIP-3
def test_hip3_sanalda_acik_gercekte_kapali(tmp_path):
    m, saat = _motor(tmp_path)
    assert m._hip3_acik() is True
    m.kip = "gercek"
    assert m._hip3_acik() is False                                 # canli_hip3_kopya=false
    m.kip = "sanal"
    m.rules["sanal_hip3_kopya"] = False
    assert m._hip3_acik() is False


# ---------------------------------------------------------------- 4) gölge kurallar
def test_golge_a_ve_b20_atlar_b5_kucultur_gercekte_etkisiz(tmp_path):
    m, saat = _motor(tmp_path)
    m._golge_acik[adr(1)] = ["A_hesap_5k"]
    assert _ac(m, saat).neden == "hesap_kucuk"
    m._golge_acik[adr(1)] = ["B_kaldirac_5x", "B_kaldirac_20x"]
    assert _ac(m, saat, no="x:2").neden == "kaldirac_cok_yuksek"
    m._golge_acik[adr(1)] = ["B_kaldirac_5x"]
    s = _ac(m, saat, no="x:3")
    assert s.karar == "emir"
    emir = [x for x in kayitlar(tmp_path, "emir") if x.get("golge_carpan") is not None][-1]
    assert emir["golge_carpan"] == 0.5
    m.kip = "gercek"
    assert m._sanal_acilis_filtresi(adr(1), "BTC", True, saat()) == (None, 1.0)


def test_golge_kapanis_engellenmez(tmp_path):
    m, saat = _motor(tmp_path)
    assert _ac(m, saat).karar == "emir"
    m._golge_acik[adr(1)] = ["A_hesap_5k", "B_kaldirac_20x"]
    s = m.olay_isle(olay("x:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))[0]
    assert s.eylem == "kapat" and s.karar == "emir"


def test_golge_bayrak_kapaliysa_yalniz_kayit(tmp_path):
    m, saat = _motor(tmp_path, sanal_golge_kurallar_etkin=False)
    m._golge_acik[adr(1)] = ["A_hesap_5k"]
    assert _ac(m, saat).karar == "emir"


# ---------------------------------------------------------------- 5) drift eylemi
def _ogrenme(tmp_path, kip="sanal"):
    olaylar = []
    return Ogrenme({}, tmp_path, kip, lambda: 1_700_000_000_000, olaylar.append), olaylar


def _drift_calistir(og, monkeypatch, simdi=1_700_000_000_000):
    from copytrade.canli import ogrenme_adaptor as oa
    monkeypatch.setattr(oa, "oku_jsonl", lambda yol: [])
    monkeypatch.setattr(oa.karne, "karne", lambda a: {})
    monkeypatch.setattr(oa.drift, "kurulum_drift", lambda a: {"T_abc123": {"durum": "uyari", "alarms": [7], "n": 20, "S": 4.2}})
    og.karne_guncelle(simdi)


def test_drift_sanal_egit_zorla_ve_carpan_yarim(tmp_path, monkeypatch):
    og, olaylar = _ogrenme(tmp_path)
    _drift_calistir(og, monkeypatch)
    assert og.uyg["egit_zorla"] is True and og.uyg["drift_carpan"]["T_abc123"]["deger"] == 0.5
    ev = [o for o in olaylar if o["olay"] == "drift_eylem"][0]
    assert ev["kurulum"] == "T_abc123" and ev["carpan"] == 0.5
    og.uyg["drift_carpan"][takma_ad("0xabc")] = {"deger": 0.5}
    assert og.agirlik("0xabc") == 0.5                              # min(1.0, 0.5); [0.5, 1.0] sınırı korunur
    og.hafta_degisti()
    assert og.agirlik("0xabc") == 1.0                              # haftalık değişimde biter


def test_drift_eylemi_daha_dusuk_dersi_yukseltmez_ve_gercekte_yok(tmp_path, monkeypatch):
    og, _ = _ogrenme(tmp_path)
    og.uyg["carpan"]["T_abc123"] = {"deger": 0.5}
    _drift_calistir(og, monkeypatch)
    assert og.agirlik_alias("T_abc123") == 0.5
    og2, _ = _ogrenme(tmp_path / "g", kip="gercek")
    assert og2.aktif is False and og2.agirlik("0xabc") == 1.0


# ---------------------------------------------------------------- 8) iz süren koruma
def _fiyat(m, saat, px):
    m.marks["BTC"] = px
    m._iz_suren_koruma(saat())


def test_iz_basabas_15_sonra_girise_donus_kapanir(tmp_path):
    m, saat = _motor(tmp_path)
    assert _ac(m, saat).karar == "emir"
    g = m.hesap.poz[adr(1)]["BTC"].giris
    _fiyat(m, saat, g * 1.16)
    assert m.hesap.sz(adr(1), "BTC") > 0 and m.hesap.poz[adr(1)]["BTC"].zirve_kar >= 0.15
    _fiyat(m, saat, g * 1.05)                                       # stop girişte; henüz üstünde
    assert m.hesap.sz(adr(1), "BTC") > 0
    _fiyat(m, saat, g * 0.999)
    assert m.hesap.sz(adr(1), "BTC") == 0.0
    ev = kayitlar(tmp_path, "iz_suren_koruma")
    assert len(ev) == 1 and ev[0]["stop_kar"] == 0.0 and ev[0]["kapandi"] is True


def test_iz_kilit_30_sonra_15e_donus_kapanir(tmp_path):
    m, saat = _motor(tmp_path)
    assert _ac(m, saat).karar == "emir"
    g = m.hesap.poz[adr(1)]["BTC"].giris
    _fiyat(m, saat, g * 1.31)
    _fiyat(m, saat, g * 1.20)                                       # +%15 üstü: açık
    assert m.hesap.sz(adr(1), "BTC") > 0
    _fiyat(m, saat, g * 1.149)
    assert m.hesap.sz(adr(1), "BTC") == 0.0
    assert kayitlar(tmp_path, "iz_suren_koruma")[0]["stop_kar"] == 0.15


def test_iz_short_yonu(tmp_path):
    m, saat = _motor(tmp_path)
    assert _ac(m, saat, "A").karar == "emir"
    g = m.hesap.poz[adr(1)]["BTC"].giris
    _fiyat(m, saat, g * 0.84)                                       # short +%16
    assert m.hesap.sz(adr(1), "BTC") < 0
    _fiyat(m, saat, g * 1.001)
    assert m.hesap.sz(adr(1), "BTC") == 0.0


def test_iz_yuzde14te_koruma_yok(tmp_path):
    m, saat = _motor(tmp_path)
    assert _ac(m, saat).karar == "emir"
    g = m.hesap.poz[adr(1)]["BTC"].giris
    _fiyat(m, saat, g * 1.14)
    _fiyat(m, saat, g * 0.99)                                       # girişin altı ama stop yok (felaket %20'ye kadar)
    assert m.hesap.sz(adr(1), "BTC") > 0 and not kayitlar(tmp_path, "iz_suren_koruma")


def test_iz_gercek_kipte_ve_bayrak_kapaliyken_etkisiz(tmp_path):
    m, saat = _motor(tmp_path)
    assert _ac(m, saat).karar == "emir"
    g = m.hesap.poz[adr(1)]["BTC"].giris
    m.kip = "gercek"
    _fiyat(m, saat, g * 1.20)
    _fiyat(m, saat, g * 0.99)
    assert m.hesap.sz(adr(1), "BTC") > 0 and m.hesap.poz[adr(1)]["BTC"].zirve_kar == 0.0
    m2, saat2 = _motor(tmp_path / "b", sanal_iz_suren=False)
    assert _ac(m2, saat2).karar == "emir"
    g2 = m2.hesap.poz[adr(1)]["BTC"].giris
    _fiyat(m2, saat2, g2 * 1.20)
    _fiyat(m2, saat2, g2 * 0.99)
    assert m2.hesap.sz(adr(1), "BTC") > 0


def test_iz_zirve_yeniden_baslatmada_korunur(tmp_path):
    m, saat = _motor(tmp_path)
    assert _ac(m, saat).karar == "emir"
    g = m.hesap.poz[adr(1)]["BTC"].giris
    _fiyat(m, saat, g * 1.20)
    m.durum_yaz()
    k = kadro([satir(1, 1)], 0)
    m2, _, saat2, _ = kur(tmp_path, kadro_=k, hl=SahteHL(), saat=saat)
    k["kosu_ms"] = saat2() - 3_600_000
    m2.baslat()
    assert m2.hesap.poz[adr(1)]["BTC"].zirve_kar >= 0.19
    _fiyat(m2, saat2, g * 0.999)
    assert m2.hesap.sz(adr(1), "BTC") == 0.0


# ---------------------------------------------------------------- 2b) duygu (Fear & Greed)
def _duygu(m, saat, deger, ms=None):
    m.haber_anlik = {**(m.haber_anlik or {}), "duygu": {"deger": deger, "sinif": "x", "ms": saat() if ms is None else ms}}


def test_duygu_ters_long_80_ve_short_20_atlanir_sanal(tmp_path):
    m, saat = _motor(tmp_path)
    _duygu(m, saat, 80)
    s = _ac(m, saat)
    assert (s.karar, s.neden) == ("atlandi", "duygu_ters") and m.neden_say["duygu_ters"] == 1
    assert _ac(m, saat, "A", no="x:2").karar == "emir"             # 80'de short serbest
    m2, saat2 = _motor(tmp_path / "b")
    _duygu(m2, saat2, 20)
    assert _ac(m2, saat2, "A").neden == "duygu_ters"
    assert _ac(m2, saat2, "B", no="x:2").karar == "emir"           # 20'de long serbest
    assert tg.ATLA_TR["duygu_ters"] == "piyasa duygusu ters"


def test_duygu_gercekte_ve_kapanista_ve_eksik_degerde_etkisiz(tmp_path):
    m, saat = _motor(tmp_path)
    _duygu(m, saat, 80)
    m.kip = "gercek"
    assert m._sanal_acilis_filtresi(adr(1), "BTC", True, saat()) == (None, 1.0)
    m2, saat2 = _motor(tmp_path / "b")
    assert _ac(m2, saat2).karar == "emir"                          # değer yok
    _duygu(m2, saat2, 90, ms=saat2() - 27 * 3600 * 1000)           # bayat
    assert m2._sanal_acilis_filtresi(adr(1), "BTC", True, saat2()) == (None, 1.0)
    m3, saat3 = _motor(tmp_path / "c")
    assert _ac(m3, saat3).karar == "emir"
    _duygu(m3, saat3, 95)                                          # kapanış engellenmez
    s = m3.olay_isle(olay("x:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat3))[0]
    assert s.eylem == "kapat" and s.karar == "emir"
    m4, saat4 = _motor(tmp_path / "d", sanal_duygu_filtre=False)
    _duygu(m4, saat4, 95)
    assert _ac(m4, saat4).karar == "emir"


# ---------------------------------------------------------------- filtre hata uyarısı
def _hata_yap(m, saat, monkeypatch):
    def patla(*a, **k):
        raise ValueError("deneme")
    monkeypatch.setattr(mt.rejim, "coin_rejimi", patla)
    assert m._sanal_acilis_filtresi(adr(1), "BTC", True, saat()) == (None, 1.0)      # hata açılışı engellemez


def _uyarilar(m):
    return [x for x in m.tg.gonderilen if "Sanal filtre" in x]


def test_filtre_hata_uyarisi_3_hatada_ve_6_saatte_bir(tmp_path, monkeypatch):
    m, saat = _motor(tmp_path)
    for _ in range(2):
        _hata_yap(m, saat, monkeypatch)
        saat.ms += 60_000
    assert not _uyarilar(m)
    _hata_yap(m, saat, monkeypatch)
    u = _uyarilar(m)
    assert len(u) == 1 and u[0].startswith("⚠️") and len(u[0].splitlines()) <= 5 and "Senden bir şey gerekmiyor" in u[0]
    saat.ms += 60_000
    _hata_yap(m, saat, monkeypatch)
    assert len(_uyarilar(m)) == 1                                  # 6 saat içinde tekrar yok
    saat.ms += 7 * 3600_000
    for _ in range(3):
        _hata_yap(m, saat, monkeypatch)
    assert len(_uyarilar(m)) == 2                                  # 6 saat sonra yine


def test_filtre_hata_uyarisi_pencere_disi_hatalar_sayilmaz(tmp_path, monkeypatch):
    m, saat = _motor(tmp_path)
    for _ in range(3):
        _hata_yap(m, saat, monkeypatch)
        saat.ms += 40 * 60_000                                     # aralık 40 dk: 1 saatte en çok 2 hata
    assert not _uyarilar(m)
