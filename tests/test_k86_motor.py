"""K-86 (CT yeni plan — motor): her kural için ÜRETİM değerleriyle (kurallar.yaml `load_rules_asil`) test. Ağsız; kasa 1.000 $ → slot 200 $; trader hesap 100.000 $ (SahteHL).
Boyut: kopya $ = slot × trader nosyonel / 100.000 (pozisyon başına en çok 1 × slot). BTC 100 $, ETH 2.000 $, SOL 100 $."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import pano
from copytrade.canli import telegram as tg
from copytrade.canli.risk import Risk
from copytrade.kurallar import load_rules_asil
from tests.test_canli_motor import T0, adr, kadro, kayitlar, kur, olay, satir

ASIL = load_rules_asil()
ANAHTARLAR = ("canli_slot_sayisi", "canli_pozisyon_tavan_slot", "canli_slot_toplam_tavan_carpan", "canli_coin_listesi", "kopya_artir_hak", "kopya_azalt_hak", "kopya_senk_hak",
              "kopya_hak_esik", "kopya_senk_esik", "kopya_kume_ms", "canli_gunluk_acilis_max", "net_yon_tavani_oran", "canli_min_emir_usd", "canli_min_emir_dogrulanmadi", "canli_olay_stale_sn", "canli_inen_saat", "canli_inen_tavan_oran")
PROD = {k: ASIL[k] for k in ANAHTARLAR}
A, B, C, D, E = (adr(i) for i in range(1, 6))


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _kur(tmp_path, n=1, **ek):
    k = kadro([satir(i, i) for i in range(1, n + 1)], T0)
    kur_ = {**PROD, "canli_min_nosyonel_usd": 1, **ek.pop("kurallar", {})}          # yürütücü (HL 10 $) asgarisi bu testlerde önemsiz: asgari emir kuralı motor tarafında sınanır
    m, hl, saat, tgp = kur(tmp_path, kadro_=k, kurallar=kur_, **ek)
    m.baslat()
    return m, hl, saat


def _ol(m, saat, kimlik, adres, coin, yon, sz, bas, px, yas_ms=1000, ilerle=10_000):
    saat.ms += ilerle                                      # her olay kendi 1 sn'lik küme penceresinin dışında
    m.piyasa_oku(saat())
    return m.olay_isle(olay(kimlik, adres, coin, yon, sz, px, bas, saat, yas_ms=yas_ms))


def _kd(s):
    return [(x.eylem, x.karar, x.neden) for x in s]


def _emirler(tmp_path):
    return kayitlar(tmp_path, "emir")


# ------------------------------------------------------------------ yapılandırma
def test_uretim_degerleri_ve_dogrulanmadi_bayragi():
    assert ASIL["canli_coin_listesi"] == ["BTC", "ETH", "BNB", "XRP", "SOL", "TRX"] and ASIL["canli_slot_sayisi"] == 5
    assert ASIL["canli_min_emir_usd"] == {"BTC": 100, "ETH": 20, "diger": 5} and ASIL["canli_min_emir_dogrulanmadi"] is True
    assert (ASIL["canli_pozisyon_tavan_slot"], ASIL["canli_marj_kaldirac"], ASIL["canli_gunluk_acilis_max"], ASIL["net_yon_tavani_oran"]) == (1.0, 3, 3, 0.60)
    assert (ASIL["kopya_hak_esik"], ASIL["kopya_senk_esik"], ASIL["canli_olay_stale_sn"], ASIL["canli_ioc_bant"]) == (0.10, 0.50, 120, 0.005)
    assert (ASIL["canli_gunluk_kayip_oran"], ASIL["canli_gunluk_kapat_oran"], ASIL["canli_zirve_dusus_oran"], ASIL["canli_felaket_stop_oran"], ASIL["canli_slot_dusus_oran"]) == (0.05, 0.10, 0.20, 0.20, 0.20)
    assert (ASIL["canli_inen_saat"], ASIL["canli_inen_tavan_oran"], ASIL["dinamik_stop"]) == (72, 0.15, True)


def test_silinen_ozellik_anahtarlari_yok():
    for k in ASIL:
        assert not k.startswith(("ogrenme_", "rejim_", "haber_", "duygu_", "sanal_rejim", "sanal_haber", "sanal_duygu", "trader_zarar_kucult", "kopya_ara_dolum", "canli_bant", "canli_patlama", "canli_sig_",
                                 "sanal_iz_", "iz_", "sanal_golge", "canli_hip3", "sanal_hip3")), k
    assert "golge_hesap_alt_usd" not in ASIL and "golge_kaldirac_uyari" not in ASIL and "golge_kaldirac_cikar" not in ASIL


# ------------------------------------------------------------------ kural 1: coin listesi
def test_kural1_liste_disi_acilmaz_sayilir_kapanis_azaltma_serbest(tmp_path):
    m, _, saat = _kur(tmp_path)
    assert _kd(_ol(m, saat, "a:1", A, "SOL", "B", 800, 0.0, 100.0)) == [("ac", "emir", "tamam")]
    m.rules["canli_coin_listesi"] = ["BTC"]                                   # SOL artık listede değil
    s = _ol(m, saat, "a:2", A, "SOL", "B", 400, 800.0, 100.0)
    assert _kd(s) == [("artir", "atlandi", "liste_disi")] and m.neden_say["liste_disi"] == 1 and m.atlanan_trader["liste_disi"][A] == 1
    s = _ol(m, saat, "a:3", A, "SOL", "A", 600, 1200.0, 100.0)               # azaltma serbest
    assert s[0].eylem == "azalt" and s[0].karar == "emir"
    s = _ol(m, saat, "a:4", A, "SOL", "A", 600, 600.0, 100.0)                # tam kapanış serbest
    assert _kd(s) == [("kapat", "emir", "tam_kapanis")] or s[0].karar == "emir"
    assert _ol(m, saat, "a:5", A, "DOGE", "B", 10, 0.0, 1.0)[0].neden == "liste_disi" and m.neden_say["liste_disi"] == 2


# ------------------------------------------------------------------ kural 2: slot ve boyut
def test_kural2_slot_kasa_bolu_5_orantili_boyut_pozisyon_tavani_1_slot(tmp_path):
    m, _, saat = _kur(tmp_path, n=2)
    assert m.saha.slot == pytest.approx(200.0)
    _ol(m, saat, "a:1", A, "BTC", "B", 500, 0.0, 100.0)                       # 50.000 $ / 100.000 × 200 = 100 $
    assert _emirler(tmp_path)[0]["usd_istenen"] == pytest.approx(100.0) and _emirler(tmp_path)[0]["boyut_neden"] == "tamam"
    _ol(m, saat, "b:1", B, "ETH", "B", 5000, 0.0, 2000.0)                    # 10 milyon $ → tavan: 1 × slot = 200 $
    e = _emirler(tmp_path)[1]
    assert e["usd_istenen"] == pytest.approx(200.0) and e["hedef_usd"] == pytest.approx(200.0)
    assert (e["trader_poz_sonra"], e["slot_usd"]) == (5000.0, 200.0)
    assert ASIL["canli_marj_kaldirac"] == 3 and m.hesap.kaldirac == 3


# ------------------------------------------------------------------ kural 3: kopya hakları
def test_kural3_haklar_ilk_artirma_ilk_azaltma_senk_ve_tam_kapanis(tmp_path):
    m, _, saat = _kur(tmp_path)
    assert _kd(_ol(m, saat, "a:1", A, "SOL", "B", 800, 0.0, 100.0)) == [("ac", "emir", "tamam")]            # 160 $
    # %5'lik artırma: yok sayılır, hak tüketmez
    s = _ol(m, saat, "a:2", A, "SOL", "B", 40, 800.0, 100.0)
    assert _kd(s) == [("artir", "atlandi", "kucuk_hareket")] and m.hak[f"{A}|SOL"]["artir"] == 0 and m.neden_say["kucuk_hareket"] == 1
    # ilk gerçek artırma (%25): kopyalanır
    s = _ol(m, saat, "a:3", A, "SOL", "B", 210, 840.0, 100.0)
    assert _kd(s) == [("artir", "emir", "tamam")] and m.hak[f"{A}|SOL"]["artir"] == 1
    assert m.hesap.sz(A, "SOL") * 100.0 == pytest.approx(200.0, abs=0.5)                                    # hedef = 1 slot tavanı
    # ikinci artırma: hak bitti
    s = _ol(m, saat, "a:4", A, "SOL", "B", 150, 1050.0, 100.0)
    assert _kd(s) == [("artir", "atlandi", "hak_bitti")] and m.neden_say["hak_bitti"] == 1
    # ilk azaltma (%16,7): kopyalanır (oran: biz/trader)
    s = _ol(m, saat, "a:5", A, "SOL", "A", 200, 1200.0, 100.0)
    assert _kd(s)[0][:2] == ("azalt", "emir") and m.hak[f"{A}|SOL"]["azalt"] == 1
    # ikinci azaltma (%10): hak bitti
    s = _ol(m, saat, "a:6", A, "SOL", "A", 100, 1000.0, 100.0)
    assert _kd(s) == [("azalt", "atlandi", "hak_bitti")]
    # pozisyonun %50'sinden fazlasının kapanması: BİR kez yeniden eşitleme
    onceki = m.hesap.sz(A, "SOL")
    s = _ol(m, saat, "a:7", A, "SOL", "A", 600, 900.0, 100.0)
    assert _kd(s)[0][:2] == ("azalt", "emir") and m.hak[f"{A}|SOL"]["senk"] == 1
    assert m.hesap.sz(A, "SOL") == pytest.approx(2.0 / 1050 * 300, rel=0.02) and m.hesap.sz(A, "SOL") < onceki                              # bizimki trader oranına ölçeklendi
    s = _ol(m, saat, "a:8", A, "SOL", "A", 200, 300.0, 100.0)               # ikinci büyük kapanış: hak yok
    assert _kd(s) == [("azalt", "atlandi", "hak_bitti")] and m.neden_say["hak_bitti"] == 3
    # tam kapanış her zaman
    s = _ol(m, saat, "a:9", A, "SOL", "A", 100, 100.0, 100.0)
    assert _kd(s)[0][:2] == ("kapat", "emir") and abs(m.hesap.sz(A, "SOL")) < 1e-9 and f"{A}|SOL" not in m.hak


def test_kural3_parcali_dolum_tek_hareket_sayilir(tmp_path):
    m, _, saat = _kur(tmp_path)
    _ol(m, saat, "a:1", A, "SOL", "B", 800, 0.0, 100.0)
    s1 = _ol(m, saat, "a:2", A, "SOL", "B", 30, 800.0, 100.0)               # %3,75: tek başına küçük
    assert s1[0].neden == "kucuk_hareket"
    saat.ms += 100                                                            # aynı emrin sonraki parçası (küme penceresi içinde)
    s2 = m.olay_isle(olay("a:3", A, "SOL", "B", 100, 100.0, 830.0, saat))
    assert _kd(s2) == [("artir", "emir", "tamam")], _kd(s2)                  # küme toplamı %16 → hak kullanıldı
    s3 = _ol(m, saat, "a:4", A, "SOL", "B", 200, 930.0, 100.0)
    assert s3[0].neden == "hak_bitti"


def test_kural3_hak_yalniz_emir_verilince_tukenir(tmp_path):
    m, _, saat = _kur(tmp_path)
    _ol(m, saat, "a:1", A, "SOL", "B", 800, 0.0, 100.0)
    s = _ol(m, saat, "a:2", A, "SOL", "B", 400, 800.0, 100.0, yas_ms=130_000)   # geç görülen artırma: emir yok, hak yanmaz
    assert s[0].neden == "gec_acilis" and m.hak[f"{A}|SOL"]["artir"] == 0
    s = _ol(m, saat, "a:3", A, "SOL", "B", 400, 1200.0, 100.0)
    assert s[0].karar == "emir" or s[0].neden in ("hedefte", "min_alti")


def test_kural3_acilisi_alinmayan_pozisyonun_artirmasi_telafi_acilis_degil(tmp_path):
    m, _, saat = _kur(tmp_path)
    s = _ol(m, saat, "a:1", A, "SOL", "B", 800, 0.0, 100.0, yas_ms=130_000)  # açılış geç görüldü
    assert s[0].neden == "gec_acilis"
    s = _ol(m, saat, "a:2", A, "SOL", "B", 400, 800.0, 100.0)
    assert _kd(s) == [("ac", "atlandi", "hak_bitti")] and abs(m.hesap.sz(A, "SOL")) < 1e-12


def test_kural3_hak_durumu_kalici(tmp_path):
    m, _, saat = _kur(tmp_path)
    _ol(m, saat, "a:1", A, "SOL", "B", 800, 0.0, 100.0)
    _ol(m, saat, "a:2", A, "SOL", "B", 400, 800.0, 100.0)
    m.durum_yaz()
    mj = json.loads((tmp_path / "durum" / "motor.json").read_text(encoding="utf-8"))
    assert mj["hak"][f"{A}|SOL"]["artir"] == 1 and mj["hak"][f"{A}|SOL"]["ac"] is True and "ara_dolum" not in mj


# ------------------------------------------------------------------ kural 4: günlük açılış sınırı
def test_kural4_trader_basina_utc_gunde_3_yeni_acilis(tmp_path):
    m, _, saat = _kur(tmp_path, n=2)
    saat.ms = (T0 // 86_400_000 + 1) * 86_400_000 + 3_600_000                # UTC günün başı + 1 sa
    for i, (coin, sz, px) in enumerate((("BTC", 500, 100.0), ("ETH", 30, 2000.0), ("SOL", 800, 100.0))):
        assert _kd(_ol(m, saat, f"a:{i}", A, coin, "B", sz, 0.0, px))[0][:2] == ("ac", "emir")
    _ol(m, saat, "a:k", A, "SOL", "A", 800, 800.0, 100.0)                   # SOL kapandı
    s = _ol(m, saat, "a:5", A, "SOL", "B", 800, 0.0, 100.0)                 # 4. yeni açılış
    assert _kd(s) == [("ac", "engel", "gunluk_acilis_siniri")] and m.neden_say["gunluk_acilis_siniri"] == 1
    assert m.risk.gunluk_acilis_say(A, saat()) == 3
    assert _kd(_ol(m, saat, "b:1", B, "SOL", "B", 800, 0.0, 100.0))[0][:2] == ("ac", "emir")                  # sayaç trader başına
    saat.ms += 86_400_000                                                    # ertesi UTC günü
    _ol(m, saat, "a:6", A, "SOL", "A", 800, 800.0, 100.0)
    s = _ol(m, saat, "a:7", A, "SOL", "B", 800, 0.0, 100.0)
    assert _kd(s)[0][:2] == ("ac", "emir")


def test_kural4_risk_birimi_kalici():
    r = Risk({**PROD, **{k: ASIL[k] for k in ("canli_gunluk_kayip_oran", "canli_gunluk_kapat_oran", "canli_zirve_dusus_oran")}}, 1000.0)
    ms = 1_800_000_000_000
    for _ in range(3):
        assert not r.gunluk_acilis_siniri("x", ms)
        r.gunluk_acilis_kaydet("x", ms)
    assert r.gunluk_acilis_siniri("x", ms) and not r.gunluk_acilis_siniri("x", ms + 86_400_000)
    r2 = Risk(r.rules, 1000.0, r.to_json())
    assert r2.gunluk_acilis_siniri("x", ms)


# ------------------------------------------------------------------ kural 5: net yön tavanı
def test_kural5_net_long_tavani_60_yuzde_kapanis_serbest(tmp_path):
    m, _, saat = _kur(tmp_path, n=4)
    assert _kd(_ol(m, saat, "a:1", A, "BTC", "B", 2000, 0.0, 100.0))[0][:2] == ("ac", "emir")               # 200 $
    assert _kd(_ol(m, saat, "b:1", B, "ETH", "B", 100, 0.0, 2000.0))[0][:2] == ("ac", "emir")               # 200 $
    assert _kd(_ol(m, saat, "c:1", C, "SOL", "B", 5000, 0.0, 100.0))[0][:2] == ("ac", "emir")               # 200 $ → net long 600 = tavan (aşmaz)
    s = _ol(m, saat, "d:1", D, "BTC", "B", 2000, 0.0, 100.0)                                                # +100 $ (coin tavanı kırpar) → 700 > 600
    assert _kd(s) == [("ac", "engel", "yon_tavani")] and m.neden_say["yon_tavani"] == 1
    assert "coin_tavani" not in m.neden_say and "yon_tavani" in m.ozet()["neden_say"]
    s = _ol(m, saat, "a:2", A, "BTC", "A", 1000, 2000.0, 100.0)                                             # azaltma tavandan etkilenmez
    assert s[0].karar == "emir"
    s = _ol(m, saat, "a:3", A, "BTC", "A", 1000, 1000.0, 100.0)
    assert s[0].eylem in ("kapat", "azalt") and s[0].karar in ("emir", "atlandi")


def test_kural5_yon_ayri_sayilir_short_serbest(tmp_path):
    m, _, saat = _kur(tmp_path, n=3, kurallar={"net_yon_tavani_oran": 0.30})
    assert _kd(_ol(m, saat, "a:1", A, "BTC", "B", 2000, 0.0, 100.0))[0][:2] == ("ac", "emir")               # long 200 ≤ 300
    assert _kd(_ol(m, saat, "b:1", B, "ETH", "B", 100, 0.0, 2000.0)) == [("ac", "engel", "yon_tavani")]     # long 400 > 300
    assert _kd(_ol(m, saat, "c:1", C, "SOL", "A", 5000, 0.0, 100.0))[0][:2] == ("ac", "emir")               # short 200 ≤ 300
    assert m._net_yon_usd() == (pytest.approx(200.0, abs=1), pytest.approx(200.0, abs=1))


def test_kural5_birimi_saf():
    r = Risk({**PROD, "canli_gunluk_kayip_oran": 0.05, "canli_gunluk_kapat_oran": 0.1, "canli_zirve_dusus_oran": 0.2}, 1000.0)
    assert not r.yon_tavani_asildi(500, 0, 100, True) and r.yon_tavani_asildi(500, 0, 101, True) and not r.yon_tavani_asildi(0, 500, 100, True) and r.yon_tavani_asildi(0, 500, 101, False)


# ------------------------------------------------------------------ kural 6: sembol başına asgari emir
@pytest.mark.parametrize("coin,px,sz,beklenen,neden", [("BTC", 100.0, 300, 100.0, "min_emir_yuvarlandi"),     # 60 $ ≥ 50 → 100
                                                        ("BTC", 100.0, 200, 0.0, "min_alti"),                  # 40 $ < 50 → yok
                                                        ("ETH", 2000.0, 3, 20.0, "min_emir_yuvarlandi"),       # 12 $ ≥ 10 → 20
                                                        ("ETH", 2000.0, 2, 0.0, "min_alti"),                   # 8 $ < 10
                                                        ("SOL", 100.0, 15, 5.0, "min_emir_yuvarlandi"),        # 3 $ ≥ 2,5 → 5
                                                        ("SOL", 100.0, 10, 0.0, "min_alti"),                   # 2 $ < 2,5
                                                        ("SOL", 100.0, 50, 10.0, "tamam"),                     # 10 $ ≥ 5 aynen
                                                        ("BTC", 100.0, 600, 120.0, "tamam")])
def test_kural6_asgari_emir_yuvarlama(tmp_path, coin, px, sz, beklenen, neden):
    m, _, saat = _kur(tmp_path)
    s = _ol(m, saat, "a:1", A, coin, "B", sz, 0.0, px)
    if beklenen:
        assert s[0].karar == "emir" and _emirler(tmp_path)[0]["usd_istenen"] == pytest.approx(beklenen) and _emirler(tmp_path)[0]["boyut_neden"] == neden
    else:
        assert _kd(s) == [("ac", "atlandi", "min_alti")] and m.neden_say["min_alti"] == 1


def test_kural6_birim_ve_ayarlar():
    from copytrade import boyut
    assert boyut.min_emir_usd(ASIL, "BTC") == 100 and boyut.min_emir_usd(ASIL, "ETH") == 20 and boyut.min_emir_usd(ASIL, "BNB") == 5 and boyut.min_emir_usd(ASIL) == 5
    assert boyut.min_yuvarla(50, 100) == (100, "min_emir_yuvarlandi") and boyut.min_yuvarla(49.99, 100) == (0.0, "min_alti") and boyut.min_yuvarla(100, 100) == (100, "")


# ------------------------------------------------------------------ kural 7: emir kuralları
def test_kural7_120_sn_eski_sinyalle_acilis_yok(tmp_path):
    m, _, saat = _kur(tmp_path)
    assert _kd(_ol(m, saat, "a:1", A, "BTC", "B", 500, 0.0, 100.0, yas_ms=121_000)) == [("ac", "atlandi", "gec_acilis")]
    assert _ol(m, saat, "a:2", A, "BTC", "B", 500, 0.0, 100.0, yas_ms=119_000)[0].karar == "emir"
    assert m.sayac["gec_acilis"] == 1


def test_kural7_ayni_coinde_ters_yon_yok_cikan_trader_engellemez(tmp_path):
    m, _, saat = _kur(tmp_path, n=2)
    assert _ol(m, saat, "a:1", A, "BTC", "B", 500, 0.0, 100.0)[0].karar == "emir"
    assert _kd(_ol(m, saat, "b:1", B, "BTC", "A", 500, 0.0, 100.0)) == [("ac", "atlandi", "ters_netlesme")]
    m.saha.uyeler.pop(A)                                                      # A sahadan çıktı (kadro dosyası `cikanlar`)
    m._cikanlari_uygula({"cikanlar": [{"adres": A, "cikis_ms": saat() - 1000}]})
    assert A in m.saha.inen
    assert _kd(_ol(m, saat, "b:2", B, "BTC", "A", 500, 0.0, 100.0))[0][:2] == ("ac", "emir")                  # çıkan trader'ın long'u yeni short'u engellemez


def test_kural7_ioc_ve_stop_ayarlari_degismedi(tmp_path):
    assert ASIL["canli_ioc_bant"] == 0.005 and ASIL["canli_felaket_stop_oran"] == 0.20 and ASIL["dinamik_stop"] is True
    from copytrade.canli.hesap import dinamik_stop_orani
    assert dinamik_stop_orani(True, 100.0, 3.0, 5.0, 0.20, 0.03) <= 0.20                                      # min(%20, tasfiyeden 3 puan önce)


# ------------------------------------------------------------------ kural 8: çıkan traderlar
def test_kural8_cikanlar_izlenir_artirma_yok_72_saatte_kapanir_tavan_15_yuzde(tmp_path):
    m, _, saat = _kur(tmp_path, n=3)
    _ol(m, saat, "a:1", A, "BTC", "B", 2000, 0.0, 100.0)                      # 200 $
    _ol(m, saat, "b:1", B, "ETH", "B", 25, 0.0, 2000.0)                       # 100 $
    cikis = saat() - 3_600_000
    m.saha.uyeler.pop(A)
    m.saha.uyeler.pop(B)
    m._cikanlari_uygula({"cikanlar": [{"adres": A, "cikis_ms": cikis}, {"adres": B, "cikis_ms": cikis + 60_000}, {"adres": "bozuk"}]})
    assert m.saha.inen[A]["inis_ms"] == cikis and m.saha.inen[B]["inis_ms"] == cikis + 60_000
    # yeni açılış / artırma yok
    assert _kd(_ol(m, saat, "a:2", A, "BTC", "B", 500, 2000.0, 100.0))[0][:3] == ("artir", "engel", "inen_trader")
    # kapanış / azaltma izlenir (haklara bakmadan)
    assert _ol(m, saat, "a:3", A, "BTC", "A", 1000, 2500.0, 100.0)[0].karar == "emir"
    assert _ol(m, saat, "b:2", B, "ETH", "A", 5, 25.0, 2000.0)[0].eylem in ("azalt", "kapat")  # B de izlenir
    # toplam çıkan nosyonel ≤ kasa × 0,15 = 150 $: fazlası en ESKİ çıkan trader'dan kapanır
    kalan = m._inen_nosyonel(A) + m._inen_nosyonel(B)
    m._inen_tavan(saat())
    assert A not in m.saha.inen and B in m.saha.inen and abs(m.hesap.sz(A, "BTC")) < 1e-9, (kalan, m.saha.inen)
    # 72 saat sonra kalan zorla kapanır
    kr = m.saha.inenleri_kapat(cikis + 60_000 + 72 * 3_600_000 - 1)
    assert not kr
    kr = m.saha.inenleri_kapat(cikis + 60_000 + 72 * 3_600_000)
    assert [k.adres for k in kr] == [B] and kr[0].tur == "inen_kapat"


def test_kural8_pozisyonsuz_cikan_kayda_alinmaz(tmp_path):
    m, _, saat = _kur(tmp_path)
    m._cikanlari_uygula({"cikanlar": [{"adres": E, "cikis_ms": saat()}]})
    assert E not in m.saha.inen


# ------------------------------------------------------------------ kural 9: kasa frenleri aynen
def test_kural9_gunluk_kayip_acilis_durur_zirve_dusus_dur(tmp_path):
    m, _, saat = _kur(tmp_path)
    m.risk.bayrak("gunluk_kayip", True)
    assert _kd(_ol(m, saat, "a:1", A, "BTC", "B", 500, 0.0, 100.0)) == [("ac", "engel", "gunluk_kayip")]
    m.risk.bayrak("gunluk_kayip", False)
    r = Risk({**PROD, "canli_gunluk_kayip_oran": 0.05, "canli_gunluk_kapat_oran": 0.10, "canli_zirve_dusus_oran": 0.20}, 1000.0)
    t = T0
    assert r.ozsermaye_isle(1000.0, t) == []
    assert r.ozsermaye_isle(949.0, t + 1000) == ["gunluk_kayip"]
    assert "gunluk_kapat" in r.ozsermaye_isle(899.0, t + 2000)
    assert "zirve_dusus" in r.ozsermaye_isle(799.0, t + 3000)


# ------------------------------------------------------------------ sayaç / pano / Telegram
def test_yeni_nedenler_sayaclarda_ve_etiketlerde():
    for n in ("liste_disi", "hak_bitti", "kucuk_hareket", "gunluk_acilis_siniri", "yon_tavani", "min_alti"):
        assert n in tg.ATLA_TR, n
    html = pano.html_olustur({"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "yazildi_ms": T0}, {}, {}, [], [], T0 + 1000)
    assert "ÖĞRENME" not in html and "Ders öğrenmesi" not in html


def test_ozet_yeni_neden_sayaclari(tmp_path):
    m, _, saat = _kur(tmp_path)
    _ol(m, saat, "a:1", A, "DOGE", "B", 10, 0.0, 1.0)
    oz = m.ozet()
    assert oz["liste_disi"] == 1 and oz["neden_say"]["liste_disi"] == 1
    for k in ("hak_bitti", "kucuk_hareket", "gunluk_acilis_siniri", "yon_tavani", "min_alti"):
        assert oz[k] == 0


def test_silinen_modul_ve_kimlik_takma_ad():
    import importlib
    for mod in ("copytrade.canli.rejim", "copytrade.canli.rejim_sonuc", "copytrade.canli.ogrenme_adaptor", "copytrade.canli.haber", "copytrade.ortak_ogrenme"):
        with pytest.raises(ImportError):
            importlib.import_module(mod)
    from copytrade.canli.kimlik import takma_ad
    assert takma_ad(A.upper()) == takma_ad(A) and takma_ad(A).startswith("T_") and len(takma_ad(A)) == 8 and "0x" not in takma_ad(A)


# ------------------------------------------------------------------ yeni dönem: elle_dur temizlenir (K-86 ek)
DONEM_ESKI, DONEM_YENI = "2026-11-16T11:30:00Z", "2026-11-21T07:30:00Z"


def _kayit_donem(tmp_path, donem, elle_dur=True, dur=False):
    m, _, saat = _kur(tmp_path)
    m.donem = donem
    m.donem_basla_kontrol()
    m.risk.bayrak("elle_dur", elle_dur)
    m.risk.bayrak("gunluk_kayip", True)
    if dur:
        m.risk.dur_ver("zirve_dusus")
    m.durum_yaz()
    return saat


def test_donem_degisince_elle_dur_ve_eski_gunluk_kayip_temizlenir(tmp_path):
    saat = _kayit_donem(tmp_path, DONEM_ESKI)
    rj = json.loads((tmp_path / "durum" / "risk.json").read_text(encoding="utf-8"))
    assert rj["acilis_durdu"]["elle_dur"] is True and rj["donem"] == DONEM_ESKI
    m2, _, _, _ = kur(tmp_path, kadro_=kadro([satir(1, 1)], T0), kurallar=PROD, saat=saat)
    m2.donem = DONEM_YENI
    assert m2.risk.acilis_izni(A, "BTC", True, saat())[0] is False                 # yeniden başlatma: hâlâ duraklatılmış (donem_basla_kontrol çağrılmadan)
    m2.baslat()
    assert m2.risk.acilis_izni(A, "BTC", True, saat()) == (True, "")
    ev = kayitlar(tmp_path, "donem_basladi_elle_dur_temizlendi")
    assert len(ev) == 1 and ev[0]["donem"] == DONEM_YENI and "elle_dur" in ev[0]["temizlenen"]
    assert m2.risk.donem == DONEM_YENI
    assert _kd(_ol(m2, saat, "a:1", A, "BTC", "B", 500, 0.0, 100.0))[0][:2] == ("ac", "emir")        # yeni CT işlem açar


def test_ayni_donemde_elle_dur_kalir(tmp_path):
    saat = _kayit_donem(tmp_path, DONEM_ESKI)
    m2, _, _, _ = kur(tmp_path, kadro_=kadro([satir(1, 1)], T0), kurallar=PROD, saat=saat)
    m2.donem = DONEM_ESKI
    m2.baslat()
    assert m2.risk.acilis_izni(A, "BTC", True, saat())[0] is False and m2.risk.acilis_durdu["elle_dur"] is True
    assert not kayitlar(tmp_path, "donem_basladi_elle_dur_temizlendi")


def test_donem_sert_dur_otomatik_temizlenmez(tmp_path):
    saat = _kayit_donem(tmp_path, DONEM_ESKI, dur=True)
    m2, _, _, _ = kur(tmp_path, kadro_=kadro([satir(1, 1)], T0), kurallar=PROD, saat=saat)
    m2.donem = DONEM_YENI
    m2.donem_basla_kontrol()
    assert m2.risk.dur is True and m2.risk.acilis_izni(A, "BTC", True, saat()) == (False, "dur")
    assert m2.risk.acilis_durdu["elle_dur"] is False


def test_donem_kayitli_donem_yoksa_son_yazimdan_sonraysa_yeni_sayilir(tmp_path):
    m, _, saat = _kur(tmp_path)
    m.risk.bayrak("elle_dur", True)
    m.durum_yaz()                                                              # risk.json'da `donem` yok (eski biçim)
    rj = json.loads((tmp_path / "durum" / "risk.json").read_text(encoding="utf-8"))
    rj.pop("donem")
    (tmp_path / "durum" / "risk.json").write_text(json.dumps(rj), encoding="utf-8")
    gelecek = datetime.fromtimestamp((saat() + 3_600_000) / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    gecmis = datetime.fromtimestamp((saat() - 86_400_000) / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    m_eski, _, _, _ = kur(tmp_path, kadro_=kadro([satir(1, 1)], T0), kurallar=PROD, saat=saat)
    m_eski.donem = gecmis                                                      # dönem başı son durum yazımından ÖNCE: erken temizleme yok
    m_eski.baslat()
    assert m_eski.risk.acilis_durdu["elle_dur"] is True
    m_yeni, _, _, _ = kur(tmp_path, kadro_=kadro([satir(1, 1)], T0), kurallar=PROD, saat=saat)
    m_yeni.risk.donem = None
    m_yeni.donem = gelecek                                                     # dönem başı son durum yazımından SONRA
    m_yeni.baslat()
    assert m_yeni.risk.acilis_durdu["elle_dur"] is False
