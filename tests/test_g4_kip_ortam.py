"""G4: kip ve kasa yalnız sunucu ortamından (CANLI_KIP / CANLI_KASA_USD); Telegram tek tüketici (TELEGRAM_KOMUT=kapali)."""
import json

import pandas as pd
import pytest

from copytrade import boyut, kopya_v5, radar_kadro
from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from copytrade.kurallar import load_rules

ANAHTAR = {"HL_API_CUZDAN_ANAHTARI": "k", "HL_HESAP_ADRESI": "0x" + "1" * 40}


def test_yaml_canli_kip_gercek_kipi_acamaz():
    gercek_kurallar = {**load_rules(), "canli_kip": "gercek"}
    for ortam in ({}, {**ANAHTAR, "CANLI_KIP": "gercek"}):
        with pytest.raises(mt.KipHatasi):
            mt.kip_belirle(gercek_kurallar, None, ortam)
        with pytest.raises(mt.KipHatasi):
            mt.kip_belirle(gercek_kurallar, "gercek", ortam)


def test_kasa_belirle_gercek_ortam_zorunlu_sanalda_yok_sayilir():
    rules = load_rules()
    assert mt.kasa_belirle(rules, "sanal", {"CANLI_KASA_USD": "300"}) == (1000.0, "yaml")             # sanal seri 1.000 $ kalır
    assert mt.kasa_belirle(rules, "gercek", {"CANLI_KASA_USD": "300"}) == (300.0, "ortam")
    assert mt.kasa_belirle(rules, "gercek", {"CANLI_KASA_USD": " 1000 "}) == (1000.0, "ortam")
    for kotu in (None, "", "abc", "0", "-5", "1000.01", "nan", "inf"):
        with pytest.raises(mt.KipHatasi):
            mt.kasa_belirle(rules, "gercek", {} if kotu is None else {"CANLI_KASA_USD": kotu})


def test_ortam_kasasi_radar_kopya_boyut_etkilemez_motor_300_ile_calisir(monkeypatch):
    """Altın örnek (elle): N = min(11, taban(1000 / slot_min)) = 11 → slot 1000/11 = 90,91 $; CANLI_KASA_USD=300 ortamında radar/kopya_v5/boyut yine 90,91 $; motor gerçek kipte 300/11 = 27,27 $."""
    monkeypatch.setenv("CANLI_KASA_USD", "300")
    monkeypatch.setenv("CANLI_KIP", "gercek")
    rules = load_rules()
    assert rules["canli_kasa_usd"] == 1000 and boyut.saha_sayisi(1000.0, rules) == 11
    assert boyut.slot_usd(None, rules) == pytest.approx(90.9091, abs=1e-4)
    kadro = radar_kadro.kadro_olustur({"sema": radar_kadro.HAVUZ_SEMA, "kosu_ms": 1, "satirlar": []}, rules)
    assert kadro["kasa_usd"] == 1000.0 and kadro["slot_usd"] == pytest.approx(90.9091, abs=1e-4) and kadro["saha_n"] == 11
    t0 = pd.Timestamp("2026-01-01", tz="UTC")
    v5 = kopya_v5.hesapla([], {}, {}, {}, [], t0, t0 + pd.Timedelta(days=7), 1, "intraday", rules, trader_hesap_usd=10_000.0)
    assert v5["kasa_usd"] == 1000.0 and v5["slot_usd"] == pytest.approx(90.9091, abs=1e-4)
    kasa, _ = mt.kasa_belirle(rules, "gercek")                                                            # os.environ'dan
    assert kasa == 300.0 and boyut.slot_usd(kasa, rules) == pytest.approx(27.2727, abs=1e-4)


def test_telegram_komut_kapali_getupdates_cagirmaz():
    cagrilar = []

    def post(url, yuk):
        cagrilar.append(url)
        return {"result": [{"update_id": 1, "message": {"text": "/durum", "date": 9e12, "chat": {"id": 5}, "from": {"id": 5}}}]}

    kapali = tg.Telegram("T", "5", post, ortam={"TELEGRAM_KOMUT": "kapali"})
    assert kapali.komutlari_al() == [] and not any("getUpdates" in c for c in cagrilar)
    kapali.gonder("merhaba")                                                                              # gönderim sürer
    assert any("sendMessage" in c for c in cagrilar)
    acik = tg.Telegram("T", "5", post, ortam={})
    acik.komutlari_al()
    assert any("getUpdates" in c for c in cagrilar)


def test_kontrol_kasa_kaynagi():
    def hl(y):
        if y["type"] == "meta":
            return {"universe": [{"name": "BTC"}]}
        raise ConnectionError("x")
    t = tg.Telegram("", "", ortam={})
    rules = load_rules()
    assert mt.kontrol(rules, "sanal", hl, lambda: None, t, ortam={"CANLI_KASA_USD": "300"})["kasa_kaynagi"] == "yaml"
    r = mt.kontrol(rules, "gercek", hl, lambda: None, t, ortam={**ANAHTAR, "CANLI_KASA_USD": "300"})
    assert r["kasa_kaynagi"] == "ortam" and r["kasa_usd"] == 300.0 and "0x1111" not in json.dumps(r)
