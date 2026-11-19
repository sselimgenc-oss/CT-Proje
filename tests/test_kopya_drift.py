"""Kopya drift alarmı: yalnız kayıt/uyarı. Elle hesaplanmış altın örnekler; ağsız."""
import json
from pathlib import Path

import pytest

from copytrade.canli import izleme
from copytrade.canli.hesap import Poz
from tests.test_canli_motor import SAAT, adr, kayitlar, kur

DK = 60_000


def hazir(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    a = adr(1)
    m.hesap_tr[a] = {"deger": 100_000.0, "ms": saat()}
    m.poz_tr[a] = {"BTC": 1000.0}                                  # 100.000 $ / 100.000 $ hesap → ideal = slot = 1000/11 = 90,909 $
    m.marks["BTC"] = 100.0
    return m, saat, tgp, a


def test_altin_drift_orani():
    assert izleme.drift_orani(0.0, 90.909, 50.0) == pytest.approx(1.0)
    assert izleme.drift_orani(72.0, 90.909, 50.0) == pytest.approx(0.2079, abs=1e-4)
    assert izleme.drift_orani(10.0, 20.0, 50.0) == pytest.approx(0.2)           # taban: |fark| / 50


def test_drift_30dk_sonra_tek_uyari_toparlaninca_bitti_ve_hiz_siniri(tmp_path):
    m, saat, tgp, a = hazir(tmp_path)
    m.rules["kopya_drift_telegram"] = True                          # ayrı uyarı yolu (üretimde 19.11'den beri kapalı)
    t = saat()
    m.kopya_drift_adimi(t)                                          # biz 0, ideal 90,9 → drift 1,0: sayaç başlar
    m.kopya_drift_adimi(t + 29 * DK)
    assert not kayitlar(tmp_path, "kopya_drift") and not any("Kopya sapması" in x for x in m.tg.gonderilen)
    m.kopya_drift_adimi(t + 31 * DK)
    m.kopya_drift_adimi(t + 32 * DK)                                # sürerken tekrar uyarı yok
    ev = kayitlar(tmp_path, "kopya_drift")
    assert len(ev) == 1 and ev[0]["coin"] == "BTC" and ev[0]["ideal_usd"] == pytest.approx(90.91) and ev[0]["biz_usd"] == 0.0 and ev[0]["drift"] == 1.0
    assert sum("Kopya sapması: BTC" in x for x in m.tg.gonderilen) == 1
    m.hesap.poz[a] = {"BTC": Poz(0.9, 100.0, t)}                      # 90 $ → drift 0,01: düzeldi
    m.kopya_drift_adimi(t + 33 * DK)
    assert kayitlar(tmp_path, "kopya_drift_bitti")[0]["coin"] == "BTC" and "BTC" not in m.kopya_drift
    del m.hesap.poz[a]                                                # yeniden sapma: kayıt var, Telegram 6 saat içinde YOK
    m.kopya_drift_adimi(t + 40 * DK)
    m.kopya_drift_adimi(t + 71 * DK)
    assert len(kayitlar(tmp_path, "kopya_drift")) == 2 and sum("Kopya sapması" in x for x in m.tg.gonderilen) == 1
    m.kopya_drift_adimi(t + 40 * DK + 7 * SAAT)                       # kapandı mı? hâlâ sapmada: aktif, yeni sayaç yok
    assert len(kayitlar(tmp_path, "kopya_drift")) == 2


def test_kucuk_ideal_izlenmez_ve_yeterli_kopya_alarm_vermez(tmp_path):
    m, saat, _, a = hazir(tmp_path)
    m.poz_tr[a] = {"BTC": 300.0}                                    # ideal 27,3 $ < 50 $ → izlenmez
    m.kopya_drift_adimi(saat())
    m.kopya_drift_adimi(saat() + 60 * DK)
    assert not m.kopya_drift and not kayitlar(tmp_path, "kopya_drift")
    m.poz_tr[a] = {"BTC": 1000.0}
    m.hesap.poz[a] = {"BTC": Poz(0.8, 100.0, saat())}                 # 80 $ vs 90,9 → drift 0,12 < 0,25
    m.kopya_drift_adimi(saat())
    m.kopya_drift_adimi(saat() + 60 * DK)
    assert not kayitlar(tmp_path, "kopya_drift")


def test_durum_kalici_ve_adimlar_dakikalik_listede(tmp_path):
    m, saat, _, _ = hazir(tmp_path)
    m.kopya_drift_adimi(saat())
    m.durum_yaz()
    d = json.loads((tmp_path / "durum" / "motor.json").read_text())
    assert "BTC" in d["kopya_drift"] and d["kopya_drift_tg_ms"] == {}
    kaynak = (Path(__file__).resolve().parents[1] / "copytrade/canli/motor.py").read_text(encoding="utf-8")
    assert '"kopya_drift", lambda' in kaynak and '"karsi_olgu", lambda' in kaynak


def test_slot_toplam_tavani_baglayinca_yanlis_alarm_yok(tmp_path):
    m, saat, _, a = hazir(tmp_path)
    m.poz_tr[a] = {"BTC": 10_000.0, "ETH": 500.0}                   # her biri 10 x slot; coin tavani 3 x slot = 272,7 $
    m.marks["ETH"] = 2000.0
    ideal = m._ideal_kopya()                                        # slot toplam tavani 272,7 $ -> orantili: 136,36 + 136,36
    assert ideal["BTC"] == pytest.approx(1000 / 11 * 1.5) and ideal["ETH"] == pytest.approx(1000 / 11 * 1.5)
    m.hesap.poz[a] = {"BTC": Poz(1000 / 11 * 1.5 / 100.0, 100.0, saat()), "ETH": Poz(1000 / 11 * 1.5 / 2000.0, 2000.0, saat())}
    for dk in (0, 31, 62):
        m.kopya_drift_adimi(saat() + dk * DK)
    assert not kayitlar(tmp_path, "kopya_drift") and not any("Kopya sapması" in x for x in m.tg.gonderilen)


def test_drift_telegram_uretimde_kapali_olay_surer(tmp_path):
    m, saat, tgp, a = hazir(tmp_path)
    assert m.rules.get("kopya_drift_telegram") is False
    t = saat()
    m.kopya_drift_adimi(t)
    m.kopya_drift_adimi(t + 31 * DK)
    assert kayitlar(tmp_path, "kopya_drift") and not any("Kopya sapması" in x for x in m.tg.gonderilen)
