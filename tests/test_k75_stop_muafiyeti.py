"""R4-2: kendi stopumuzla (felaket/iz_suren/tasfiye) kapanan pozisyon, trader hala acikken kacan_telafi tarafindan yeniden acilir."""
import pytest

from tests.test_canli_motor import adr, kayitlar, kur, olay
from tests.test_k75_kacan_telafi import HLGiris, _acilis_dolumu  # noqa: F401


def _kur(tmp_path, **kurallar):
    hl = HLGiris(pozlar={adr(1): {"BTC": 300.0}}, giris={"BTC": 100.0})
    m, hl, saat, tgp = kur(tmp_path, hl=hl, kurallar=kurallar)
    hl.rest = {adr(1): [_acilis_dolumu(saat)]}
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))      # normal yoldan acildi
    assert m.hesap.sz(adr(1), "BTC") > 0
    return m, hl, saat


def test_felaket_stop_sonrasi_ayni_trader_pozisyonu_yeniden_acilmamali(tmp_path):
    m, hl, saat = _kur(tmp_path)
    saat.ms += 600_000
    hl.mids["BTC"] = "79"
    hl.kitaplar["BTC"] = {"levels": [[{"px": "78.9", "sz": "1000"}], [{"px": "79", "sz": "1000"}]]}
    m.dakika()
    assert [k for k in kayitlar(tmp_path, "felaket_stop") if k["kapandi"]], "felaket stop tetiklenmeliydi"
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9), (
        "BEKLENEN: stopla kapanan pozisyon yeniden acilmaz (0); GERCEK: kacan_telafi ayni dakikada %d telafi emriyle yeniden acti" % len([e for e in kayitlar(tmp_path, "emir") if e["boyut_neden"] == "kacan_telafi"]))


def test_iz_suren_sonrasi_yeniden_acilmamali(tmp_path):
    m, hl, saat = _kur(tmp_path)
    p = m.hesap.poz[adr(1)]["BTC"]
    p.zirve_kar = 0.16                                       # basabas esigi: kar girise inerse kapanir
    saat.ms += 600_000
    m.dakika()                                                # mark 100 == giris -> kar 0 <= 0 : iz_suren kapatir
    assert any(k["kapandi"] for k in kayitlar(tmp_path, "iz_suren_koruma")), "iz suren kapatmaliydi"
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9), "BEKLENEN: 0; GERCEK: kacan_telafi yeniden acti"


def _felaket(tmp_path, m, hl, saat):
    saat.ms += 600_000
    hl.mids["BTC"] = "79"
    hl.kitaplar["BTC"] = {"levels": [[{"px": "78.9", "sz": "1000"}], [{"px": "79", "sz": "1000"}]]}
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)


def _telafi_emirleri(tmp_path):
    return [e for e in kayitlar(tmp_path, "emir") if e["boyut_neden"] == "kacan_telafi"]


def test_stop_muafiyeti_kayit_ve_sonraki_senkronlarda_surer(tmp_path):
    m, hl, saat = _kur(tmp_path)
    _felaket(tmp_path, m, hl, saat)
    assert f"{adr(1)}|BTC" in m.stop_muaf
    hl.mids["BTC"] = "100"                                   # fiyat geri geldi, trader hala tutuyor
    saat.ms += 600_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9) and not _telafi_emirleri(tmp_path)
    assert any(k["neden"] == "stop_muafiyeti" for k in kayitlar(tmp_path, "kacan_telafi_atlandi"))


def test_trader_kapatip_yeniden_acarsa_telafi_tekrar_serbest(tmp_path):
    m, hl, saat = _kur(tmp_path)
    _felaket(tmp_path, m, hl, saat)
    hl.mids["BTC"] = "100"
    hl.pozlar = {adr(1): {}}                                 # trader kapatti (senkronda sifir goruldu)
    saat.ms += 600_000
    m.dakika()
    assert f"{adr(1)}|BTC" not in m.stop_muaf
    hl.pozlar = {adr(1): {"BTC": 300.0}}                     # yeni acilis, biz kacirdik
    hl.rest = {adr(1): [_acilis_dolumu(saat, once_ms=60_000)]}
    m._telafi_dolum.clear()
    saat.ms += 600_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") > 0 and len(_telafi_emirleri(tmp_path)) == 1


def test_trader_sifirlanmadan_yeni_acilis_dolumu_muafiyeti_bitirir(tmp_path):
    m, hl, saat = _kur(tmp_path)
    _felaket(tmp_path, m, hl, saat)
    hl.mids["BTC"] = "100"
    saat.ms += 600_000
    hl.rest = {adr(1): [_acilis_dolumu(saat, once_ms=60_000)]}   # stoptan SONRA yeni acilis dolumu
    m._telafi_yas.clear(); m._telafi_dolum.clear()
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") > 0


def test_yeniden_baslatma_muafiyeti_korur(tmp_path):
    m, hl, saat = _kur(tmp_path)
    _felaket(tmp_path, m, hl, saat)
    m.durum_yaz()
    m2, _, _, _ = kur(tmp_path, hl=hl, saat=saat)
    assert f"{adr(1)}|BTC" in m2.stop_muaf
    hl.mids["BTC"] = "100"
    hl.rest = {adr(1): [_acilis_dolumu(saat)]}
    m2.baslat()
    saat.ms += 600_000
    m2.dakika()
    assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)


def test_lehte_yuzde_1_5_acilmaz_yuzde_0_9_acilir(tmp_path):
    for ad, giris, bekle in (("a", 101.5, False), ("b", 100.9, True)):
        hl = HLGiris(pozlar={adr(1): {"BTC": 300.0}}, giris={"BTC": giris})
        m, hl, saat, _ = kur(tmp_path / ad, hl=hl)
        hl.rest = {adr(1): [_acilis_dolumu(saat)]}
        m.baslat()
        m.dakika()
        assert (m.hesap.sz(adr(1), "BTC") > 0) is bekle
        if not bekle:
            assert any(k["neden"] == "kayma_lehte_fazla" for k in kayitlar(tmp_path / ad, "kacan_telafi_atlandi"))
