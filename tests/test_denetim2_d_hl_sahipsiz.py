"""2. denetim O-1 (HL okunamıyor → açılış bayrağı + alarm) ve O-2 (kozmetik çağrılar yalıtılır; gerçek kipte saha.json sıkı; sahipsiz pozisyon taraması: 600 sn kesintisiz → kapat; sanalda da aynı bekleme)."""
from __future__ import annotations

import json

import pytest

from copytrade.canli import kadro as kd
from copytrade.canli import motor as mt
from tests.test_canli_motor import adr, kayitlar, kur, olay
from tests.test_canli_t4b import HLADR, BorsaSim, kur_gercek


@pytest.fixture(autouse=True)
def _m():
    yield
    mt.MASKE.clear()


class HlHataSim(BorsaSim):
    hl_hata = False

    def post(self, y):
        if self.hl_hata and y["type"] == "clearinghouseState" and y.get("user") == HLADR:
            raise RuntimeError("HL down")
        return super().post(y)


# ------------------------------------------------------------------------------------------------ O-1
def test_hl_okunamiyor_3_ardisik_hatada_bayrak_alarm_basarili_okumada_kalkar(tmp_path, monkeypatch):
    sim = HlHataSim()
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.dakika()
    assert not m.risk.acilis_durdu.get("hl_okunamiyor")
    sim.hl_hata = True
    for n in (1, 2, 3, 4):
        saat.ms += 60_000
        m.dakika()
        assert bool(m.risk.acilis_durdu.get("hl_okunamiyor")) is (n >= 3)
    assert sum("HL okunamıyor" in x for x in tgp.gonderilen) == 1               # saatte bir
    assert m.risk.acilis_durdu["hl_okunamiyor"] is True and not m.risk.dur
    assert not m.risk.acilis_izni(adr(1), "BTC", True, saat())[0]
    saat.ms += 60_000
    sim.hl_hata = False
    m.dakika()
    assert m.risk.acilis_durdu["hl_okunamiyor"] is False


def test_hl_okunamiyor_iki_hata_bir_basari_sayaci_sifirlar(tmp_path, monkeypatch):
    sim = HlHataSim()
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.dakika()
    for hata in (True, True, False, True, True):
        sim.hl_hata = hata
        saat.ms += 60_000
        m.dakika()
    assert not m.risk.acilis_durdu.get("hl_okunamiyor") and not any("HL okunamıyor" in x for x in tgp.gonderilen)


def test_hl_okunamiyor_bayat_bayrak_yeniden_baslatmada_temizlenir(tmp_path, monkeypatch):
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, HlHataSim())
    m.baslat()
    m.risk.bayrak("hl_okunamiyor", True)
    m.durum_yaz()
    m2, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    assert m2.risk.acilis_durdu.get("hl_okunamiyor") is False


# ------------------------------------------------------------------------------------------------ O-2 kozmetik
def test_kozmetik_istisna_dus_inen_kapat_partisini_kesmez(tmp_path, monkeypatch):
    """`dus` kararında `donem_slot_cikis` istisna atsa da aynı listedeki `inen_kapat` (pozisyon kapanışı) ve sonraki kararlar uygulanır."""
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.sz(adr(1), "BTC") > 0 and sim.poz["BTC"] > 0

    def patla(*a, **k):
        raise KeyError("bozuk donem_seri")
    m.donem_slot_cikis = patla
    m.karar_uygula([kd.Karar("dus", adr(1), "test"), kd.Karar("inen_kapat", adr(1), "inen_test")], saat())
    assert m.hesap.sz(adr(1), "BTC") == 0.0 and sim.poz["BTC"] == pytest.approx(0.0, abs=1e-9)
    assert [k for k in kayitlar(tmp_path, "risk_yan_adim_hata") if k["adim"] == "donem_slot_cikis"]


def test_felaket_stop_donem_kilit_istisnasi_kapanisi_engellemez(tmp_path, monkeypatch):
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.donem_kilit = lambda *a: (_ for _ in ()).throw(ValueError("x"))
    m.marks["BTC"], m.mark_ms["BTC"] = 70.0, saat()                       # giriş 100 → −%30 ≥ felaket %20
    m._felaket_stop(saat())
    assert [k for k in kayitlar(tmp_path, "felaket_stop")] and any(x["reduce_only"] for x in sim.siparisler[1:])           # kapanış emri gitti (sahte defter fiyatı markla uyumsuz: kısmi dolum olabilir)
    assert [k for k in kayitlar(tmp_path, "risk_yan_adim_hata") if k["adim"] == "donem_kilit"]


def test_gercek_bozuk_saha_json_durum_bozuk_sanal_baslar(tmp_path, monkeypatch):
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    m.durum_yaz()
    (tmp_path / "durum" / "saha.json").write_text("{bozuk", encoding="utf-8")
    with pytest.raises(mt.DurumBozuk):
        kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    s, hl, saat2, _ = kur(tmp_path / "sanal")
    s.baslat()
    s.durum_yaz()
    (tmp_path / "sanal" / "durum" / "saha.json").write_text("{bozuk", encoding="utf-8")
    s2, *_ = kur(tmp_path / "sanal", saat=saat2)                           # sanal: eskisi gibi başlar
    assert s2.kip == "sanal"


# ------------------------------------------------------------------------------------------------ O-2 sahipsiz
def _sahipsiz_gercek(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert sim.poz["BTC"] > 0
    m.saha.uyeler.pop(adr(1))                                              # saha durumu kaybı / kozmetik istisna sonrası: ne uyeler ne inen
    return m, sim, saat, tgp


def test_sahipsiz_pozisyon_ilk_gorulmede_alarm_600_sn_kesintisiz_sonra_kapanir_gercek(tmp_path, monkeypatch):
    m, sim, saat, tgp = _sahipsiz_gercek(tmp_path, monkeypatch)
    m._sahipsiz_tara(saat())
    assert adr(1) in m.sahipsiz_ilk and kayitlar(tmp_path, "sahipsiz_pozisyon") and any("sahipsiz" in x for x in tgp.gonderilen)
    for _ in range(9):                                                     # 9 dk: henüz yok
        saat.ms += 60_000
        m._sahipsiz_tara(saat())
    assert sim.poz["BTC"] > 0 and m.hesap.sz(adr(1), "BTC") > 0
    saat.ms += 60_000                                                      # 10. dk: 600 sn doldu
    m._sahipsiz_tara(saat())
    assert sim.poz["BTC"] == pytest.approx(0.0, abs=1e-9) and m.hesap.sz(adr(1), "BTC") == 0.0
    assert kayitlar(tmp_path, "sahipsiz_kapat")[-1]["kapanan"] == ["BTC"]
    saat.ms += 60_000
    m._sahipsiz_tara(saat())
    assert adr(1) not in m.sahipsiz_ilk and kayitlar(tmp_path, "sahipsiz_bitti")


def test_sahipsiz_adres_sahaya_donerse_sayac_silinir_kapanmaz(tmp_path, monkeypatch):
    m, sim, saat, _ = _sahipsiz_gercek(tmp_path, monkeypatch)
    m._sahipsiz_tara(saat())
    saat.ms += 300_000
    m.saha.uyeler[adr(1)] = {}
    m._sahipsiz_tara(saat())
    assert adr(1) not in m.sahipsiz_ilk
    saat.ms += 700_000
    m._sahipsiz_tara(saat())
    assert sim.poz["BTC"] > 0


def test_sahipsiz_kapanis_kuyrugundaki_coin_haric_yagmur_yok(tmp_path, monkeypatch):
    m, sim, saat, _ = _sahipsiz_gercek(tmp_path, monkeypatch)
    m._sahipsiz_tara(saat())
    m._eksik_ekle(adr(1), "BTC", "kapat", 0.0, "x", saat(), deneme=0)
    saat.ms += 700_000
    m.sahipsiz_ilk[adr(1)]["ms"] = saat() - 700_000
    m._sahipsiz_tara(saat())
    assert not sim.siparisler[1:] and sim.poz["BTC"] > 0                   # kuyruk (kendi geri çekilmesiyle) yönetir; tarama dokunmaz


def test_sahipsiz_tarama_boslugu_kesintiyi_boler_ve_durum_kalicidir(tmp_path, monkeypatch):
    m, sim, saat, _ = _sahipsiz_gercek(tmp_path, monkeypatch)
    m._sahipsiz_tara(saat())
    m.durum_yaz()
    assert json.loads((tmp_path / "durum" / "motor.json").read_text())["sahipsiz_ilk"][adr(1)]["ms"] == m.sahipsiz_ilk[adr(1)]["ms"]
    m.dur_dosyasi.exists()
    saat.ms += 20 * 60_000                                                 # 20 dk tarama yok (yeniden başlatma / vardiya boşluğu): "kesintisiz 600 sn" SAYILMAZ
    m._sahipsiz_tara(saat())
    assert sim.poz["BTC"] > 0 and m.sahipsiz_ilk[adr(1)]["ms"] == saat()


def test_sahipsiz_sanalda_da_ayni_600_sn_beklemeyle(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.sz(adr(1), "BTC") > 0
    m.saha.uyeler.pop(adr(1))
    m._sahipsiz_tara(saat())
    for _ in range(9):
        saat.ms += 60_000
        m._sahipsiz_tara(saat())
    saat.ms += 59_000
    m._sahipsiz_tara(saat())
    assert m.hesap.sz(adr(1), "BTC") > 0                                   # 599 sn: toplu kapanış YOK
    saat.ms += 1_000
    m._sahipsiz_tara(saat())
    assert m.hesap.sz(adr(1), "BTC") == 0.0
