"""Bağımsız denetim 14.11 (K-66): D-01 radar kasa ölçeği = motor sanal kasası, D-02 R1 elemesi aynı gün sonuçla düşer, BTC al-tut kıyası (ozet.json + pano)."""
from __future__ import annotations

import json
import re

import pytest
import yaml

from copytrade import boyut, radar_isabet, radar_kadro
from copytrade import radar_tarama as r
from copytrade.canli import kadro as kd
from copytrade.canli import motor as mt
from copytrade.canli import pano
from copytrade.kurallar import load_rules, load_rules_asil
from tests.test_canli_motor import GUN, SAAT, T0, SahteHL, adr, kadro, kayitlar, kur, n_kadro, satir
from tests.test_radar_tarama import A1, Sahte, lider, satir_al
from tests.test_radar_tarama import KOSU, dolum, ms

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
URETIM = load_rules_asil()                       # dosyadaki gerçek değerler (conftest v1 boyut değerlerini EZMEZ)


# ================================================================================================ D-01: radar kasası
def test_d01_uretim_radar_kasasi_motor_sanal_kasasiyla_ayni_gercek_para_degismez():
    assert URETIM["radar_kasa_usd"] == 10000 and URETIM["canli_sanal_kasa_ust_usd"] == 10000
    assert URETIM["canli_kasa_usd"] == 1000 and URETIM["canli_kasa_ust_usd"] == 1000                      # gerçek para sınırı değişmez
    wf = (ROOT / ".github/workflows/canli_vardiya.yml").read_text(encoding="utf-8")
    sanal = re.findall(r"--sanal-kasa-usd (\d+(?:\.\d+)?)", wf)
    assert sanal and all(float(x) == float(URETIM["radar_kasa_usd"]) for x in sanal)                     # motor sanal kasası = radar kasası
    assert "--kasa" not in (ROOT / ".github/workflows/radar.yml").read_text(encoding="utf-8")              # radar iş akışı kasayı kurallardan alır


def test_d01_radar_kasa_onceligi_arguman_kural_eski():
    assert boyut.radar_kasa(URETIM) == 10000.0
    assert boyut.radar_kasa(URETIM, 2500.0) == 2500.0                                                      # CLI argümanı önce
    assert boyut.radar_kasa({k: v for k, v in URETIM.items() if k != "radar_kasa_usd"}) == 1000.0        # anahtar yoksa eski canli_kasa_usd


def _senaryo():
    """Trader hesap 50.000 $, 10 BTC × 100 $ = 1.000 $ açar (oran 0,02), 110'dan kapatır.
    Üretim boyutu: kasa 1.000 → N = min(11, 1000/200) = 5, slot 200 $ → hedef 4 $ < yuvarlama alt sınırı 5,5 $ → ATLANIR (kopya işlemi yok).
    kasa 10.000 → N 11, slot 909,09 $ → hedef 18,18 $ ≥ 11 $ → AÇILIR (kâr 0,1818 BTC × 10 = 1,818 $ ayna)."""
    dolumlar = {A1: [dolum(ms("10:00:00"), "BTC", "B", 10, 0, 100), dolum(ms("11:00:00"), "BTC", "A", 10, 10, 110, kapanan=100.0)]}
    fiyat = lambda coin, t: 110.0 if t >= ms("11:00:00") else 100.0               # noqa: E731
    return Sahte([lider(A1, 50_000, 100, 5_000)], dolumlar, fiyat)


def _kos(tmp_path, rules, **kw):
    return r.kos(_senaryo(), KOSU, tmp_path / "radar", None, rules, log=lambda *_: None, **kw)


def test_d01_kucuk_acilis_1000_de_atlanir_10000_de_acilir_radar_kasa_usd_kullanilir(tmp_path):
    kurallar = {**URETIM, "radar_min_islem": 1, "radar_min_kopya_islem": 1}
    varsayilan = _kos(tmp_path / "a", kurallar)                                                            # argüman yok → radar_kasa_usd (10.000)
    s10 = satir_al(varsayilan, A1)
    assert varsayilan["kasa_usd"] == 10000.0
    assert s10["kopya_islem_sayisi"] == 1 and s10["ayna_getiri_7g"] == pytest.approx(0.1818182 * 10 / 10000, rel=1e-5)
    kucuk = _kos(tmp_path / "b", {**kurallar, "radar_kasa_usd": 1000})                                     # aynı veri, 1.000 $ ölçek
    s1 = satir_al(kucuk, A1)
    assert kucuk["kasa_usd"] == 1000.0 and not s1["kopya_islem_sayisi"] and not s1["ayna_getiri_7g"]
    arg = _kos(tmp_path / "c", kurallar, kasa_usd=1000.0)                                                  # CLI argümanı kuralın önünde
    assert arg["kasa_usd"] == 1000.0 and not satir_al(arg, A1)["kopya_islem_sayisi"]
    yazilan = json.loads(next((tmp_path / "a" / "radar").glob("*/havuz.json")).read_text(encoding="utf-8"))
    assert yazilan["kasa_usd"] == 10000.0                                                                  # havuz.json `kasa_usd`


def test_d01_kadro_ve_isabet_radar_kasasini_kullanir():
    havuz = {"sema": radar_kadro.HAVUZ_SEMA, "kosu_ms": 1, "satirlar": []}
    k = radar_kadro.kadro_olustur(havuz, URETIM)
    assert k["kasa_usd"] == 10000.0 and k["saha_n"] == 11 and k["slot_usd"] == pytest.approx(10000 / 11)
    assert radar_kadro.kadro_olustur(havuz, URETIM, 1000.0)["kasa_usd"] == 1000.0                        # --kasa önce
    assert r.Baglam(Sahte([], {}), 1, 0, URETIM).kasa_usd == 10000.0                                       # isabet `Baglam(client, bit, bas, rules)` ile aynı yol
    assert "radar_kasa_usd" in radar_isabet.__doc__


def test_d01_motor_kadro_kasasi_farkliysa_bir_kez_kayit_ve_uyari_durmaz(tmp_path):
    m, _, saat, tgp = kur(tmp_path, kasa=1000.0)
    k = {**n_kadro(3, saat() - SAAT), "kasa_usd": 10000.0}
    m._kadro_uygula((True, k), saat())
    m._kadro_uygula((True, k), saat() + 60_000)
    fark = kayitlar(tmp_path, "kadro_kasa_farkli")
    assert len(fark) == 1 and fark[0]["kadro_kasa_usd"] == 10000.0 and fark[0]["motor_kasa_usd"] == 1000.0
    assert sum("kadro kasası farklı" in x for x in tgp.gonderilen) == 1
    assert len(m.saha.uyeler) == 3 and not m.risk.dur                                                      # kadro uygulanır, motor durmaz
    m2, _, saat2, tgp2 = kur(tmp_path / "esit", kasa=1000.0)
    m2._kadro_uygula((True, n_kadro(3, saat2() - SAAT)), saat2())                                           # kasa 1.000 = motor: kayıt yok
    assert not kayitlar(tmp_path / "esit", "kadro_kasa_farkli")


# ================================================================================================ D-02: R1 elemesi
def _gun2(neden):
    """Gün 1: 11 üye sahada. Gün 2 kadrosunda adr(11) yok; `eski_uye_neden[adr(11)] = neden`."""
    s = kd.Saha(load_rules(), 1000.0)
    s.degerlendir(n_kadro(11), T0 + SAAT)
    for a in s.uyeler:
        s.islem_gordu(a, T0 + GUN)
    k2 = {**kadro([satir(i, i, 90 - i) for i in range(1, 11)], T0 + GUN), "eski_uye_neden": {adr(11): neden}}
    karar, _ = s.degerlendir(k2, T0 + GUN + SAAT)
    return s, karar


@pytest.mark.parametrize("neden", ["r1:kopya_zarar", "r1:kaldirac_yuksek"])
def test_d02_r1_elenen_ayni_gun_sonucla_duser_ve_bekler(neden):
    s, karar = _gun2(neden)
    assert [(k.adres, k.neden, k.sonuc) for k in karar if k.tur == "dus"] == [(adr(11), "r1_elendi", True)]
    assert s.bekleme[adr(11)] == T0 + GUN + SAAT + int(load_rules()["canli_bekleme_gun"]) * GUN
    assert adr(11) in s.inen and adr(11) not in s.uyeler


@pytest.mark.parametrize("neden", ["r0_disi", "sira_disi", "soguyan"])
def test_d02_r1_disi_neden_iki_gun_kuralinda_kalir(neden):
    s, karar = _gun2(neden)
    assert [k for k in karar if k.tur == "dus"] == [] and s.uyeler[adr(11)]["disi_gunler"]                 # ilk gün yalnız işaret
    for a in s.uyeler:
        s.islem_gordu(a, T0 + 2 * GUN)
    k3 = {**kadro([satir(i, i, 90 - i) for i in range(1, 11)], T0 + 2 * GUN), "eski_uye_neden": {}}
    karar3, _ = s.degerlendir(k3, T0 + 2 * GUN + SAAT)
    assert [(k.adres, k.neden, k.sonuc) for k in karar3 if k.tur == "dus"] == [(adr(11), "kadro_disi", False)] and adr(11) not in s.bekleme


def test_d02_motor_uctan_uca_r1_elenen_kayit_telegram_ve_bekleme(tmp_path):
    m, _, saat, tgp = kur(tmp_path)
    m._kadro_uygula((True, n_kadro(3, saat() - SAAT)), saat())
    assert adr(3) in m.saha.uyeler
    saat.ms += GUN
    for a in m.saha.uyeler:
        m.saha.islem_gordu(a, saat())
    k2 = {**kadro([satir(1, 1, 89), satir(2, 2, 88)], saat() - SAAT), "eski_uye_neden": {adr(3): "r1:kopya_zarar"}}
    m._kadro_uygula((True, k2), saat())
    dus = kayitlar(tmp_path, "saha_dus")
    assert [(d["adres"], d["neden"], d["sonuc"]) for d in dus] == [(adr(3), "r1_elendi", True)]
    assert m.saha.bekleme[adr(3)] > saat() + 13 * GUN
    assert any("R1" in x and "sonuçla" in x for x in tgp.gonderilen)


# ================================================================================================ BTC al-tut kıyası
class BtcHL(SahteHL):
    def __init__(self, mumlar=None, **kw):
        super().__init__(**kw)
        self.mumlar = mumlar if mumlar is not None else {"1m": [], "1h": []}

    def __call__(self, y):
        if y["type"] == "candleSnapshot":
            self.istekler.append(y)
            return self.mumlar.get(y["req"]["interval"], [])
        return super().__call__(y)


DONEM = "2027-01-15T07:00:00Z"                    # = T0 − 1 sa (T0 = 2027-01-15 08:00 UTC)
DONEM_MS = T0 - SAAT


def test_btc_al_tut_donem_basi_bir_kez_kaydedilir_ozet_ve_fark(tmp_path):
    hl = BtcHL({"1m": [{"t": DONEM_MS - 60_000, "o": "79000"}, {"t": DONEM_MS, "o": "80000"}, {"t": DONEM_MS + 60_000, "o": "80100"}]}, mids={"BTC": "84000", "ETH": "2000", "SOL": "100"})
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.donem = DONEM
    assert m.ozet()["btc_al_tut_getiri"] is None                                                           # henüz okunmadı → "—"
    m.piyasa_oku(saat())
    m.btc_donem_uygula(m.btc_donem_oku(saat()))
    assert m.btc_donem["fiyat"] == 80000.0 and m.btc_donem["kaynak"] == "mum_1m" and m.btc_donem["bas_ms"] == DONEM_MS
    o = m.ozet()
    assert o["btc_al_tut_getiri"] == pytest.approx(0.05) and o["btc_fark"] == pytest.approx(o["getiri"] - 0.05) and o["donem"] == DONEM
    n = len([y for y in hl.istekler if y.get("type") == "candleSnapshot"])
    saat.ms += 10 * 60_000
    assert m.btc_donem_oku(saat()) is None and len([y for y in hl.istekler if y.get("type") == "candleSnapshot"]) == n   # bir kez: tekrar okunmaz
    assert len(kayitlar(tmp_path, "btc_donem")) == 1
    m.durum_yaz()
    m2, *_ = kur(tmp_path, hl=hl, saat=saat)                                                                # yeniden başlatma: motor.json'dan
    m2.donem = DONEM
    assert m2.btc_donem["fiyat"] == 80000.0 and m2.btc_donem_oku(saat()) is None
    m2.donem = "2027-02-01T00:00:00Z"                                                                       # yeni dönem: eski fiyat geçersiz
    assert m2.ozet()["btc_donem_fiyat"] is None


def test_btc_al_tut_veri_yoksa_tire_ve_pano_metni(tmp_path):
    hl = BtcHL({"1m": [], "1h": []})
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.donem = DONEM
    saat.ms = DONEM_MS + 2 * SAAT                                                                           # 15 dk'dan geç: mid yedeği yok
    m.piyasa_oku(saat())
    assert m.btc_donem_oku(saat()) is None
    o = m.ozet()
    assert o["btc_al_tut_getiri"] is None and o["btc_fark"] is None
    assert pano.btc_metni(o) == ("BTC al-tut: —", "fark: —")
    m.donem = None
    assert m.btc_donem_oku(saat()) is None and m.ozet()["donem"] is None


def test_btc_al_tut_saatlik_mum_ve_mid_yedegi(tmp_path):
    hl = BtcHL({"1m": [], "1h": [{"t": DONEM_MS, "o": "81000"}]})
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.donem = DONEM
    assert m.btc_donem_oku(saat())["kaynak"] == "mum_1h"
    hl2 = BtcHL({"1m": [], "1h": []}, mids={"BTC": "90000", "ETH": "2000", "SOL": "100"})
    m2, _, saat2, _ = kur(tmp_path / "b", hl=hl2)
    m2.donem = DONEM
    saat2.ms = DONEM_MS + 5 * 60_000
    m2.piyasa_oku(saat2())
    b = m2.btc_donem_oku(saat2())
    assert b["kaynak"] == "mid" and b["fiyat"] == 90000.0


def test_btc_al_tut_pano_ozet_md_ve_html(tmp_path):
    ozet = {"kip": "sanal", "kasa_usd": 10000.0, "ozsermaye_usd": 10500.0, "getiri": 0.05, "btc_al_tut_getiri": -0.032, "btc_fark": 0.082, "acik": []}
    md, _ = pano.pano_olustur(ozet, {}, {}, [], [], [], T0)
    assert "BTC al-tut: −%3,2" in md and "fark: +%8,2" in md
    html = pano.html_olustur(ozet, {}, {}, [], [], T0)
    assert "BTC al-tut (aynı dönem)" in html and "−%3,2" in html and "fark: +%8,2" in html
    bos, _ = pano.pano_olustur({**ozet, "btc_al_tut_getiri": None, "btc_fark": None}, {}, {}, [], [], [], T0)
    assert "BTC al-tut: — · fark: —" in bos


def test_donem_oku(tmp_path):
    y = tmp_path / "DONEM"
    y.write_text("2026-11-14T15:15:00Z\n", encoding="utf-8")
    assert mt.donem_oku(y) == "2026-11-14T15:15:00Z"
    y.write_text("bozuk", encoding="utf-8")
    assert mt.donem_oku(y) is None and mt.donem_oku(tmp_path / "yok") is None
    assert mt.donem_oku() is not None                                                                       # depodaki gerçek dosya geçerli


def test_yaml_okunur():
    assert yaml.safe_load((ROOT / "copytrade/kurallar.yaml").read_text(encoding="utf-8"))["radar_kasa_usd"] == 10000


# ================================================================================================ F-03 / F-08 / F-09: radar R2 girdileri
GUN0 = 1_793_404_800_000                      # 2026-10-31 00:00 UTC
EGRI = [["2026-10-31", 10_000.0], ["2026-11-01", 10_000.0], ["2026-11-02", 10_100.0], ["2026-11-03", 10_300.0], ["2026-11-04", 10_200.0], ["2026-11-05", 10_120.0],
        ["2026-11-06", 10_110.0], ["2026-11-07", 10_100.0]]
KOSU7 = GUN0 + 7 * GUN + 37 * 60_000          # 2026-11-07 00:37 UTC


def test_f03_son_72_saat_egriden_slot_olceginde_eriyen_pozisyon_sayilir():
    """Kasa 10.000, slot 909,09. t = KOSU − 72 sa = 04.11 00:37 → başlangıç = 03.11 gün sonu 10.300 $ (03.11'de açılıp sonra eriyen pozisyon).
    Getiri = (10.100 − 10.300) / 909,09 = −0,22 (slot) → soğuyor (< −0,02). Eski ayrı boş başlayan oynatma 72 sa içinde işlem yoksa 0 görürdü (geçerdi)."""
    g, durum = r.son_saat_getirisi(EGRI, KOSU7, 72, 10_000.0, 10_000 / 11)
    assert durum == "egri" and g == pytest.approx(-200 / (10_000 / 11))
    from copytrade import radar_form
    assert radar_form.soguyor({"kopya_getiri_72s": g}, load_rules()) is True
    assert r.son_saat_getirisi(EGRI[:2], GUN0 + 36 * SAAT, 72, 10_000.0, 1_000.0) == (pytest.approx(0.0), "egri")    # gün sonu yok: başlangıç = kasa
    assert r.son_saat_getirisi([], KOSU7, 72, 10_000.0, 909.0) == (0.0, "hesaplanamadi")                               # eski davranış (0 = geçer), ama işaretli


def test_f08_kismi_son_gun_seriden_atilir():
    assert len(r.tam_gunler(EGRI, KOSU7)) == 7 and r.tam_gunler(EGRI, KOSU7)[-1][0] == "2026-11-06"           # 07.11 yalnız 37 dk
    assert r.tam_gunler(EGRI, GUN0 + 8 * GUN) == EGRI                                                       # 08.11 00:00: 07.11 tam gün


def test_f03_akil_sagligi_slot_getirisine_gore():
    kurallar = load_rules()
    temel = {"devir_hafta": 1.0, "islem_sayisi": 50, "medyan_tutma_saat": 5.0, "kisa_islem_payi": 0.0, "max_kaldirac": 3.0, "likit_pay": 1.0, "kopya_getiri_7g": 0.30,
             "kopya_koruma": 0.9, "kopya_islem_sayisi": 50, "kopya_alt20": 0.1, "hesap_usd": 10_000.0}
    assert r.degerlendir({**temel, "kopya_slot_kat": 1.0}, kurallar) == (True, None)                         # kasa %30 (kat yok) geçer
    assert r.degerlendir({**temel, "kopya_slot_kat": 11.0}, kurallar) == (False, "akil_sagligi")             # slot %330 > %300
    assert r.degerlendir({**temel, "kopya_getiri_7g": 0.25, "kopya_slot_kat": 11.0}, kurallar) == (True, None)   # slot %275


def test_f09_h_agirligi_sifirsa_hype_mumu_cekilmez(tmp_path):
    kurallar = {**URETIM, "radar_min_islem": 1, "radar_min_kopya_islem": 1}
    assert kurallar["radar_agirlik_h"] == 0
    istemci = _senaryo()
    mum_cagrilari: list = []
    asil = istemci.candles
    istemci.candles = lambda coin, bas, son, interval="1m": (mum_cagrilari.append(coin), asil(coin, bas, son, interval))[1]
    s = satir_al(r.kos(istemci, KOSU, tmp_path / "radar", None, kurallar, log=lambda *_: None), A1)
    assert s["gecti"] is True and s["hype_payi"] is None and set(mum_cagrilari) == {"BTC"}                 # H olsaydı tüm ana coinler (ETH, ALT) okunurdu
    mum_cagrilari.clear()
    s2 = satir_al(r.kos(istemci, KOSU, tmp_path / "radar2", None, {**kurallar, "radar_agirlik_h": 0.1}, log=lambda *_: None), A1)
    assert s2["hype_payi"] is not None and {"ETH", "ALT"} <= set(mum_cagrilari)


def test_f10_kontrol_adimi_da_sanal_kasa_10000():
    wf = (ROOT / ".github/workflows/canli_vardiya.yml").read_text(encoding="utf-8")
    satirlar = [s for s in wf.splitlines() if "copytrade.canli.motor" in s and "python" in s]
    assert any("--kontrol" in s for s in satirlar) and all("--sanal-kasa-usd 10000" in s for s in satirlar)


# ================================================================================================ F-06: dönem serisi ve aylık eşdeğer ölçütü
def test_f06_aylik_esdeger_formulu():
    assert mt.aylik_esdeger(0.02, 15.0) == pytest.approx(1.02 ** 2 - 1)                                     # 0,0404
    assert mt.aylik_esdeger(0.04, 30.0) == pytest.approx(0.04) and mt.aylik_esdeger(0.0816, 60.0) == pytest.approx(0.04, abs=1e-4)
    assert mt.aylik_esdeger(0.01, 0.5) is None and mt.aylik_esdeger(None, 10.0) is None and mt.aylik_esdeger(-1.0, 10.0) is None
    assert URETIM["basari_aylik_hedef"] == 0.04


def test_f06_donem_seri_kalici_gun_sonu_ve_hedef(tmp_path):
    hl = BtcHL({"1m": [{"t": DONEM_MS, "o": "80000"}]}, mids={"BTC": "80800", "ETH": "2000", "SOL": "100"})
    m, _, saat, _ = kur(tmp_path, hl=hl, kasa=10_000.0)
    m.donem = DONEM
    m.piyasa_oku(saat())
    m.btc_donem_uygula(m.btc_donem_oku(saat()))
    m.donem_seri_guncelle(saat())
    saat.ms += 30 * 60_000
    m.donem_seri_guncelle(saat())                                                                           # aynı UTC günü: kayıt güncellenir (gün sonu = son değer)
    gun_sonu = (T0 // GUN + 1) * GUN
    saat.ms = gun_sonu + SAAT
    m.donem_seri_guncelle(saat())                                                                           # ertesi gün yeni satır
    m.durum_yaz()
    seri = json.loads((tmp_path / "durum" / "donem_seri.json").read_text(encoding="utf-8"))
    assert seri["donem"] == DONEM and seri["btc_donem_fiyat"] == 80000.0 and seri["bas_ms"] == DONEM_MS and seri["kasa_usd"] == 10_000.0
    assert [g["gun"] for g in seri["gunler"]] == ["2027-01-15", "2027-01-16"] and seri["gunler"][0]["btc"] == 80800.0
    m2, *_ = kur(tmp_path, hl=hl, saat=saat, kasa=10_000.0)                                                 # yeniden başlatma: seri dosyadan
    m2.donem = DONEM
    assert len(m2.donem_seri["gunler"]) == 2
    m2.donem = "2027-02-01T00:00:00Z"
    m2.donem_seri_guncelle(saat())
    assert m2.donem_seri["donem"] == "2027-02-01T00:00:00Z" and len(m2.donem_seri["gunler"]) == 1         # yeni dönem: sıfırdan
    m.hesap.realize["x"] = 300.0                                                                            # dönem getirisi +%3, BTC +%1
    saat.ms = DONEM_MS + 15 * GUN
    o = m.ozet()
    assert o["donem_gun"] == pytest.approx(15.0) and o["aylik_esdeger"] == pytest.approx(1.03 ** 2 - 1) and o["hedef_gecer"] is True
    assert pano.hedef_metni(o) == ("aylık eşdeğer: +%6,1", "hedef %4/ay: geçiyor")
    hl.mids["BTC"] = "84000"                                                                                # BTC +%5 > bizim +%3
    m.piyasa_oku(saat())
    assert m.ozet()["hedef_gecer"] is False and pano.hedef_metni(m.ozet())[1] == "hedef %4/ay: geçmiyor"
    assert pano.hedef_metni({}) == ("aylık eşdeğer: —", "hedef %4/ay: —")


def test_f06_pano_md_ve_html_aylik_ve_hedef():
    ozet = {"kip": "sanal", "kasa_usd": 10000.0, "ozsermaye_usd": 10300.0, "getiri": 0.03, "btc_al_tut_getiri": 0.01, "btc_fark": 0.02,
            "aylik_esdeger": 0.0609, "aylik_hedef": 0.04, "hedef_gecer": True, "acik": []}
    md, _ = pano.pano_olustur(ozet, {}, {}, [], [], [], T0)
    assert "aylık eşdeğer: +%6,1" in md and "hedef %4/ay: geçiyor" in md and "BTC al-tut: +%1,0" in md
    html = pano.html_olustur(ozet, {}, {}, [], [], T0)
    assert "Aylık eşdeğer" in html and "hedef %4/ay: geçiyor" in html


def test_f06_yayim_betigi_donem_serisini_tasir():
    assert "donem_seri.json" in (ROOT / ".github/scripts/canli_yayimla.sh").read_text(encoding="utf-8")


# ================================================================================================ E/F: saha hep dolu (kullanıcı 14.11)
def _saha_gun2(tmp_path, bekleyen=None, yedek=(12, 13, 14)):
    m, _, saat, _ = kur(tmp_path)
    m._kadro_uygula((True, n_kadro(11, saat() - SAAT)), saat())
    assert len(m.saha.uyeler) == 11
    if bekleyen:
        m.saha.bekleme[adr(bekleyen)] = saat() + 10 * GUN
    saat.ms += GUN
    for a in m.saha.uyeler:
        m.saha.islem_gordu(a, saat())
    k2 = {**kadro([satir(i, i, 90 - i) for i in range(1, 10)] + [satir(i, i, 70 - i) for i in yedek], saat() - SAAT),
          "eski_uye_neden": {adr(10): "r1:kopya_zarar", adr(11): "r1:kaldirac_yuksek"}, "gecti_sayisi": 42}
    m._kadro_uygula((True, k2), saat())
    return m


def test_saha_hep_dolu_ilk11_den_iki_cikan_ayni_gun_yedekle_dolar(tmp_path):
    m = _saha_gun2(tmp_path / "a")
    assert len(m.saha.uyeler) == 11 and {adr(12), adr(13)} <= set(m.saha.uyeler) and adr(14) not in m.saha.uyeler
    assert [x["neden"] for x in kayitlar(tmp_path / "a", "saha_giris")][-2:] == ["bos_slot", "bos_slot"] and m.saha.degisiklik["adet"] == 0    # K-44: sınıra sayılmaz
    assert m.saha.eksik is None and not kayitlar(tmp_path / "a", "saha_eksik")
    m2 = _saha_gun2(tmp_path / "b", bekleyen=12)                                                           # beklemedeki yedek atlanır, sıradaki girer
    assert len(m2.saha.uyeler) == 11 and adr(12) not in m2.saha.uyeler and {adr(13), adr(14)} <= set(m2.saha.uyeler)
    o = m2.ozet()
    assert o["saha"] == 11 and o["r1_gecen"] == 42 and o["saha_eksik_neden"] is None
    assert pano.saha_metni(o) == "saha 11/11 · bugün R1'i geçen trader: 42"


def test_saha_uygun_aday_yoksa_bos_kalir_kayit_ve_pano(tmp_path):
    m = _saha_gun2(tmp_path, yedek=(12,))
    assert len(m.saha.uyeler) == 10 and m.saha.eksik == {"saha": 10, "n": 11, "neden": "uygun_aday_yok"}
    m._kadro_uygula((True, m._son_kadro), m.saat_ms() + 60_000)                                             # aynı durum: tek kayıt
    eksik = kayitlar(tmp_path, "saha_eksik")
    assert len(eksik) == 1 and eksik[0]["saha"] == 10 and eksik[0]["n"] == 11
    o = m.ozet()
    assert pano.saha_metni(o) == "saha 10/11, uygun aday yok · bugün R1'i geçen trader: 42"
    md, _ = pano.pano_olustur(o, {}, {}, [], [], [], T0)
    assert "saha 10/11, uygun aday yok" in md
    html = pano.html_olustur(o, {}, {}, [], [], T0)
    assert "Saha doluluğu" in html and "10/11" in html and "uygun aday yok" in html and ("R1&#x27;i geçen trader: 42" in html or "R1'i geçen trader: 42" in html)


def test_saha_korelasyon_doldurmayi_engellemez_siradaki_girer():
    """Gün 2: 2 boş yer; aday 12 sahadaki 1 ve 2 ile benzer (r = 0,9; kor_max 2 → bileşen 3) → atlanır; 13 ve 14 girer."""
    s = kd.Saha(load_rules(), 1000.0)
    s.degerlendir(n_kadro(11), T0 + SAAT)
    for a in s.uyeler:
        s.islem_gordu(a, T0 + GUN)
    adresler = [adr(1), adr(2), adr(12)]
    kor = {"adresler": adresler, "gun_sayisi": 8, "matris": [[1.0, 0.9, 0.9], [0.9, 1.0, 0.9], [0.9, 0.9, 1.0]]}
    k2 = {**kadro([satir(i, i, 90 - i) for i in range(1, 10)] + [satir(i, i, 70 - i) for i in (12, 13, 14)], T0 + GUN, kor), "eski_uye_neden": {adr(10): "r1:x", adr(11): "r1:y"}}
    karar, _ = s.degerlendir(k2, T0 + GUN + SAAT)
    assert [k.adres for k in karar if k.tur == "giris"] == [adr(13), adr(14)] and any(k.tur == "giris_atlandi" and k.adres == adr(12) for k in karar)
    assert len(s.uyeler) == 11 and s.eksik is None


@pytest.mark.parametrize("neden", ["veri:veri_hatasi", "veri:payda_yok", "veri:zaman_yok", "r1:veri_hatasi", "r1:payda_yok", "r1:zaman_yok"])
def test_radar_hunisi_1411_veri_nedeni_sonucla_dusurmez_bekleme_yok(neden):
    """Kullanıcı 14.11: R1 çıkışında VERİ nedenleri (yeni `veri:` biçimi ve eski kadrodaki `r1:veri_hatasi` vb.) sonuçla düşme + 14 gün bekleme VERMEZ: K-39 iki gün kadro dışı kuralı."""
    assert kd.r1_elendi({"eski_uye_neden": {adr(11): neden}}, adr(11)) is False
    s, karar = _gun2(neden)
    assert [k for k in karar if k.tur == "dus"] == [] and adr(11) not in s.bekleme and s.uyeler[adr(11)]["disi_gunler"]
