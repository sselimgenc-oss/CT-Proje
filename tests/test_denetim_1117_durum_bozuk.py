"""Denetim 2026-11-17 ADIM 2 (K1): gerçek kipte bozuk/eksik durum dosyasıyla motor BAŞLAMAZ (borsa stopları iptal edilmez); `.bak` yalnız hesap.json; sanal kipte alarm + kayıt ile başlar."""
import json

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from copytrade.canli import yurutucu as yu
from tests.test_canli_motor import RULES, CHAT, TOKEN, SahteTG, Saat, adr, kadro, kayitlar, olay, satir, SAAT
from tests.test_canli_t4b import HLADR, BorsaSim, kur_gercek


def _gercek_motor(tmp_path, monkeypatch, sim):
    monkeypatch.setenv("HL_HESAP_ADRESI", HLADR)
    saat, tgp = Saat(), SahteTG()
    k = kadro([satir(1, 1)], saat() - SAAT)
    m = mt.Motor({**RULES, "canli_kasa_usd": 1000.0}, yu.GercekYurutucu(sim, sim.post, RULES), sim.post, tg.Telegram(TOKEN, CHAT, tgp), tmp_path / "durum", tmp_path / "kayit", lambda: k, saat)
    return m, tgp


def _durum_hazirla(tmp_path, monkeypatch):
    """Gerçek kipte 1 pozisyon + 1 borsa stopu olan sağlam durum dizini yazar."""
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dakika()
    m.durum_yaz()
    assert len(sim.acik) == 1
    return sim, tmp_path / "durum"


def test_gercek_bozuk_hesap_json_motor_baslamaz_stop_iptal_edilmez(tmp_path, monkeypatch):
    """Eski hata: bozuk hesap.json = "dosya yok" → boş defter → ilk dakikada borsa stopu "pozisyon_yok" diye iptal. Şimdi DurumBozuk; hiçbir iptal çağrısı yok."""
    sim, dizin = _durum_hazirla(tmp_path, monkeypatch)
    (dizin / "hesap.json").write_text("{", encoding="utf-8")
    iptal = []
    orijinal = sim.cancel
    sim.cancel = lambda coin, oid: (iptal.append((coin, oid)), orijinal(coin, oid))[1]
    with pytest.raises(mt.DurumBozuk):
        _gercek_motor(tmp_path, monkeypatch, sim)
    assert iptal == [] and len(sim.acik) == 1


@pytest.mark.parametrize("dosya", ["motor.json", "risk.json", "borsa_stop.json"])
def test_gercek_diger_durum_dosyalari_bozuksa_baslamaz(tmp_path, monkeypatch, dosya):
    sim, dizin = _durum_hazirla(tmp_path, monkeypatch)
    (dizin / dosya).write_text("[1, 2", encoding="utf-8")
    with pytest.raises(mt.DurumBozuk):
        _gercek_motor(tmp_path, monkeypatch, sim)


def test_gercek_json_nesne_degilse_bozuk_sayilir(tmp_path, monkeypatch):
    sim, dizin = _durum_hazirla(tmp_path, monkeypatch)
    (dizin / "hesap.json").write_text("[]", encoding="utf-8")
    with pytest.raises(mt.DurumBozuk):
        _gercek_motor(tmp_path, monkeypatch, sim)


def test_gercek_motor_json_var_hesap_json_yok_baslamaz(tmp_path, monkeypatch):
    sim, dizin = _durum_hazirla(tmp_path, monkeypatch)
    (dizin / "hesap.json").unlink()
    with pytest.raises(mt.DurumBozuk):
        _gercek_motor(tmp_path, monkeypatch, sim)


def test_gercek_dizin_bos_normal_baslar_ve_saglam_durum_yuklenir(tmp_path, monkeypatch):
    sim = BorsaSim()
    m, _ = _gercek_motor(tmp_path, monkeypatch, sim)                      # hiç dosya yok: ilk açılış
    assert m.durum_bozuk == []
    sim2, dizin = _durum_hazirla(tmp_path / "b", monkeypatch)
    m2, _ = _gercek_motor(tmp_path / "b", monkeypatch, sim2)               # sağlam dosyalar: açılır, pozisyon yüklü
    assert m2.hesap.sz(adr(1), "BTC") > 0 and "BTC" in m2.borsa_stop.stoplar


def test_bak_yalniz_hesap_json_icin_ve_bozuk_dosya_saglam_yedegi_ezmez(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    dizin = tmp_path / "durum"
    m.durum_yaz()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))    # _dolum_yaz → önceki sağlam hesap.json yedeklenir
    bak = json.loads((dizin / "hesap.json.bak").read_text(encoding="utf-8"))
    assert bak["poz"] == {} or not any(bak["poz"].values())                  # yedek = önceki (pozisyonsuz) sağlam sürüm
    assert not list(dizin.glob("motor.json.bak")) and not list(dizin.glob("risk.json.bak")) and not list(dizin.glob("saha.json.bak"))
    onceki_bak = (dizin / "hesap.json.bak").read_text(encoding="utf-8")
    (dizin / "hesap.json").write_text("{bozuk", encoding="utf-8")
    m.durum_yaz()                                                          # mevcut dosya bozuk: yedek EZİLMEZ
    assert (dizin / "hesap.json.bak").read_text(encoding="utf-8") == onceki_bak


def test_sanal_bozuk_dosya_alarm_kayit_ile_baslar_kilitlenmez(tmp_path):
    """Sanal kip (Actions): bozuk hesap.json vardiya zincirini kilitlemez; kayıt + alarm, bozuk kopya `.bozuk` olarak saklanır."""
    from tests.test_canli_motor import kur
    m0 = kur(tmp_path)[0]
    m0.baslat()
    m0.durum_yaz()
    (tmp_path / "durum" / "hesap.json").write_text("{", encoding="utf-8")
    m1, _, _, tgp = kur(tmp_path)
    assert m1.durum_bozuk == ["hesap.json"] and (tmp_path / "durum" / "hesap.json.bozuk").read_text(encoding="utf-8") == "{"
    m1.baslat()
    assert kayitlar(tmp_path, "durum_bozuk")[-1]["dosyalar"] == ["hesap.json"] and any("durum dosyası bozuk" in x.lower() for x in tgp.gonderilen)
