"""Denetim 2026-11-17 ADIM 3 (O1): DUR/günlük kapanış kozmetik `donem_kilit` istisnasından ÖNCE ve izole; DUR dosyası hiç yazılmadıysa kurtarma; gerçek kipte yeniden başlatmada DUR sessizce silinmez."""
import json

import pytest

from tests.test_canli_motor import adr, kayitlar, kur, olay
from tests.test_canli_t4b import BorsaSim, kur_gercek


def _poz_ac(m, saat, hl=None):
    if hl is not None:
        hl.pozlar[adr(1)] = {"BTC": 300.0}                                         # trader pozisyonu açık (senkron kapatmasın: kapanışı yalnız risk adımı yapmalı)
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert any(m.hesap.poz.values())


def test_o1_donem_kilit_istisnasi_dur_kapanisini_engellemez(tmp_path):
    """Eski hata: `donem_kilit` (kozmetik) önce çalışıp istisna atınca DUR/kapanış hiç yapılmaz, `risk.dur` açık ama pozisyon açık + DUR dosyası yok kalırdı."""
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    _poz_ac(m, saat, hl)

    def bozuk(*a, **k):
        raise RuntimeError("pano")
    m.donem_kilit = bozuk
    m.hesap.kapanmis_net = -210.0                                                   # zirve düşüşü %21 ≥ %20
    saat.ms += 60_000
    m.dakika()
    assert m.risk.dur and (tmp_path / "durum" / "DUR").exists() and not any(m.hesap.poz.values())
    assert kayitlar(tmp_path, "risk_yan_adim_hata")[-1]["adim"] == "donem_kilit"


def test_o1_gunluk_kapat_donem_kilit_istisnasindan_etkilenmez(tmp_path):
    m, hl, saat, tgp = kur(tmp_path, kurallar={"canli_gunluk_kapat_oran": 0.05, "canli_gunluk_kayip_oran": 0.04})
    m.baslat()
    _poz_ac(m, saat, hl)
    saat.ms += 60_000
    m.dakika()                                                                      # gün tabanı (gun_basi) kurulur
    assert any(m.hesap.poz.values())

    def bozuk(*a, **k):
        raise RuntimeError("pano")
    m.donem_kilit = bozuk
    m.hesap.kapanmis_net = -60.0                                                    # günlük kayıp %6 ≥ %5 sert fren
    saat.ms += 60_000
    m.dakika()
    assert not any(m.hesap.poz.values()) and kayitlar(tmp_path, "gunluk_kapat")


def test_o1_kurtarma_risk_dur_acik_dur_dosyasi_hic_yok_pozisyonlar_kapanir(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    _poz_ac(m, saat, hl)
    m.risk.dur, m.risk.dur_neden, m.risk.dur_dosya = True, "zirve_dusus", False       # eski hatanın bıraktığı durum
    assert not (tmp_path / "durum" / "DUR").exists()
    saat.ms += 60_000
    m.dakika()
    assert (tmp_path / "durum" / "DUR").exists() and not any(m.hesap.poz.values()) and m.risk.dur_dosya is True
    assert kayitlar(tmp_path, "dur_kurtarma") and any("DUR kurtarılıyor" in x for x in tgp.gonderilen)


def test_o1_operator_dur_dosyasini_sildiyse_calisan_motor_yeniden_dur_yapmaz(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.dur_tetikle("komut")
    assert m.risk.dur_dosya is True
    (tmp_path / "durum" / "DUR").unlink()
    saat.ms += 600_000
    m.dakika()
    assert not (tmp_path / "durum" / "DUR").exists() and not kayitlar(tmp_path, "dur_kurtarma")


def _yarim_dur_durumu(tmp_path, monkeypatch, gercek):
    """risk.json: dur açık, dur_dosya False (DUR dosyası hiç yazılmadı), zirve 1.000; pozisyon açık."""
    if gercek:
        m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
        m.baslat()
        sim.trader_poz[adr(1)] = {"BTC": 300.0}
        _poz_ac(m, saat)
    else:
        m, sim, saat, tgp = kur(tmp_path)
        m.baslat()
        _poz_ac(m, saat, sim)
    m.risk.dur, m.risk.dur_neden, m.risk.dur_dosya = True, "zirve_dusus", False
    m.risk.zirve = 1234.0
    m.durum_yaz()
    m.kilit_yaz(True)
    return sim, saat


def test_o1_gercek_yeniden_baslatmada_dosyasiz_dur_sessizce_silinmez_zirve_korunur_ilk_adimda_kapanir(tmp_path, monkeypatch):
    """Eski hata: DUR dosyası yok → `dur_sifirlandi` + zirve sıfırlanır → DUR kaybolur, pozisyon açık. Gerçek kipte dosya HİÇ yazılmadıysa DUR korunur ve kurtarılır."""
    sim, saat = _yarim_dur_durumu(tmp_path, monkeypatch, True)
    m2, sim2, saat2, tgp2 = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    m2.baslat()
    assert m2.risk.dur and m2.risk.zirve == pytest.approx(1234.0) and not kayitlar(tmp_path, "dur_sifirlandi") and kayitlar(tmp_path, "dur_korundu")
    saat.ms += 60_000
    m2.dakika()
    assert (tmp_path / "durum" / "DUR").exists() and not any(m2.hesap.poz.values()) and sim.poz.get("BTC", 0.0) == pytest.approx(0.0, abs=1e-9)


def test_o1_gercek_operator_siler_dur_dosya_true_ise_eski_sifirlama_yolu_calisir(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    m.dur_tetikle("komut")
    assert m.risk.dur_dosya is True
    m.kilit_yaz(True)
    (tmp_path / "durum" / "DUR").unlink()
    m2, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    m2.baslat()
    assert not m2.risk.dur and kayitlar(tmp_path, "dur_sifirlandi")


def test_o1_sanal_yeniden_baslatma_davranisi_degismez_dosyasiz_dur_sifirlanir(tmp_path):
    """Sanal kip: `donem_geri` akışı / eski S-2 davranışı aynen (DUR dosyası yoksa bayat dur sıfırlanır)."""
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.risk.dur, m.risk.dur_neden, m.risk.dur_dosya = True, "zirve_dusus", False
    m.durum_yaz()
    m.kilit_yaz(True)
    m2, *_ = kur(tmp_path, hl=hl, saat=saat)
    m2.baslat()
    assert not m2.risk.dur and kayitlar(tmp_path, "dur_sifirlandi") and not kayitlar(tmp_path, "dur_korundu")


def test_risk_json_dur_dosya_alani_eski_bicim_uyumlu():
    from copytrade.canli.risk import Risk
    from tests.test_canli_motor import RULES
    assert Risk(RULES, 1000.0, {"dur": True}).dur_dosya is True and Risk(RULES, 1000.0, {}).dur_dosya is False and Risk(RULES, 1000.0, {"dur": True, "dur_dosya": False}).dur_dosya is False
    assert json.loads(json.dumps(Risk(RULES, 1000.0).to_json()))["dur_dosya"] is False
