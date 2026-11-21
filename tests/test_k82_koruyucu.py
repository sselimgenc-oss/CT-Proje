"""K-82: CT yerel koruyucu (motordan bağımsız ikinci hat) + motor kancası + oto-kurulum."""
from __future__ import annotations

import json
from pathlib import Path


from copytrade import koruyucu as kr
from copytrade.canli import telegram as tg
from copytrade.kurallar import load_rules
from tests.test_canli_motor import CHAT, TOKEN, SahteTG, adr, kur, olay
from tests.test_deploy_sanal import YESIL, git, sunucu  # noqa: F401  (fixture)

RULES = load_rules()
T0 = 1_760_000_000_000
DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


class Saat:
    def __init__(self, ms=T0):
        self.ms = ms

    def __call__(self):
        return self.ms


def _yaz(yol, d):
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(d), encoding="utf-8")


def _motor_dosyalari(durum, oz, ms, kasa=1000.0, risk_ek=None):
    _yaz(durum / "risk.json", {"son_oz": oz, "zirve": kasa, "gun_basi": kasa, "gun": kr._gun(ms), "dur": False, **(risk_ek or {})})
    _yaz(durum / "motor.json", {"kasa_usd": kasa, "kip": "sanal", "yazildi_ms": ms})
    _yaz(durum / "kilit.json", {"vardiya": "x", "nabiz_ms": ms, "birakildi": False})


def _kur(tmp_path, saat=None):
    saat = saat or Saat()
    tgp = SahteTG()
    k = kr.Koruyucu(RULES, tmp_path / "durum", tmp_path / "kayit", tg.Telegram(TOKEN, CHAT, tgp), saat)
    return k, saat, tgp


def _bayrak(tmp_path):
    return json.loads((tmp_path / "durum/ortak/dur.json").read_text())["ct"]


def test_yuzde5_yeni_acilis_dur(tmp_path):
    k, saat, tgp = _kur(tmp_path)
    _motor_dosyalari(tmp_path / "durum", 1000.0, saat())
    k.adim()
    assert _bayrak(tmp_path)["yeni_acilis_dur"] is False
    _motor_dosyalari(tmp_path / "durum", 949.0, saat())             # %5,1 kayıp
    k.adim()
    b = _bayrak(tmp_path)
    assert b["yeni_acilis_dur"] and not b["kapat_dur"] and "gunluk_kayip" in b["nedenler"]
    assert sum(x.startswith("⚠️ Koruyucu: günlük kayıp") for x in tgp.gonderilen) == 1 and "\n" not in tgp.gonderilen[0]
    assert not (tmp_path / "durum/ortak/ct.json").exists()          # K-86: ct.json çıktısı kaldırıldı
    k.adim()
    assert len(tgp.gonderilen) == 1                                 # aynı gün tekrar mesaj yok
    saat.ms += 86_400_000                                           # UTC gün dönümü: yeni taban = son gözlem (949), açılış serbest
    _motor_dosyalari(tmp_path / "durum", 949.0, saat())
    k.adim()
    assert _bayrak(tmp_path)["yeni_acilis_dur"] is False


def test_yuzde20_kapat_ve_dur_mandal(tmp_path):
    k, saat, tgp = _kur(tmp_path)
    d = tmp_path / "durum"
    _motor_dosyalari(d, 1000.0, saat())
    k.adim()
    _motor_dosyalari(d, 799.0, saat())                              # zirveden %20,1
    k.adim()
    b = _bayrak(tmp_path)
    assert b["kapat_dur"] and b["yeni_acilis_dur"] and "zirve_dusus" in b["nedenler"]
    assert any(x.startswith("❌ Koruyucu: zirveden düşüş") for x in tgp.gonderilen)
    _motor_dosyalari(d, 900.0, saat())                              # toparlansa da mandal sürer
    k.adim()
    assert _bayrak(tmp_path)["kapat_dur"]
    (d / "DUR").write_text("{}")                                    # motor DUR yazdı
    k.adim()
    (d / "DUR").unlink()                                            # insan sildi
    _motor_dosyalari(d, 900.0, saat())
    k.adim()
    b = _bayrak(tmp_path)
    assert not b["kapat_dur"]
    assert json.loads((d / "ortak/koruyucu.json").read_text())["zirve"] == 900.0      # zirve güncel özsermayeye


def test_motor_nabzi_bayat_alarm_ve_dur_sonra_duzelir(tmp_path):
    k, saat, tgp = _kur(tmp_path)
    d = tmp_path / "durum"
    _motor_dosyalari(d, 1000.0, saat())
    k.adim()
    saat.ms += 181_000
    k.adim()
    assert _bayrak(tmp_path)["yeni_acilis_dur"] and "motor_nabiz_bayat" in _bayrak(tmp_path)["nedenler"]
    assert any(x.startswith("⚠️ Koruyucu: motor nabzı") for x in tgp.gonderilen)
    _motor_dosyalari(d, 1000.0, saat())
    k.adim()
    assert _bayrak(tmp_path)["yeni_acilis_dur"] is False
    gunluk = list((tmp_path / "kayit/koruyucu").glob("*.jsonl"))[0].read_text()
    assert "motor_nabiz_bayat" in gunluk and "motor_nabiz_duzeldi" in gunluk


def test_motor_bilerek_durmussa_nabiz_alarmi_yok(tmp_path):
    k, saat, tgp = _kur(tmp_path)
    d = tmp_path / "durum"
    _motor_dosyalari(d, 1000.0, saat())
    (d / "DUR").write_text("{}")
    saat.ms += 600_000
    k.adim()
    assert not tgp.gonderilen and _bayrak(tmp_path)["yeni_acilis_dur"] is False


def _hazir_motor(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    return m, saat, tgp


def test_gecis_kurali_koruyucu_hic_yoksa_yalniz_uyari_gorulunce_bayatlarsa_acilis_durur(tmp_path):
    m, saat, tgp = _hazir_motor(tmp_path)
    kr.motor_kancasi(m, saat())
    assert not m.risk.acilis_durdu.get(kr.BAYRAK_NABIZ)
    assert m.risk.acilis_izni("a", "BTC", True, saat())[0]
    assert any("Koruyucu henüz çalışmıyor" in x for x in tgp.gonderilen)
    d = tmp_path / "durum"
    kr.yaz(d / "ortak/koruyucu.json", {"yazildi_ms": saat()})        # koruyucu göründü
    kr.motor_kancasi(m, saat())
    assert (d / "koruyucu_gorulen").exists() and m.risk.acilis_izni("a", "BTC", True, saat())[0]
    saat.ms += 181_000
    kr.motor_kancasi(m, saat())
    assert m.risk.acilis_izni("a", "BTC", True, saat()) == (False, kr.BAYRAK_NABIZ)
    kr.yaz(d / "ortak/koruyucu.json", {"yazildi_ms": saat()})        # koruyucu döndü
    kr.motor_kancasi(m, saat())
    assert m.risk.acilis_izni("a", "BTC", True, saat())[0]


def _taze_koruyucu(m, saat, bayrak):
    d = Path(m.durum_dizin)
    kr.yaz(d / "ortak/koruyucu.json", {"yazildi_ms": saat()})
    kr.yaz(d / "ortak/dur.json", {"sema": kr.SEMA_DUR, "ct": bayrak})


def test_motor_sanal_bayragi_uygular_acilis_durur_kapanis_serbest_bayrak_kalkinca_surer(tmp_path):
    m, saat, _ = _hazir_motor(tmp_path)
    _taze_koruyucu(m, saat, {"yeni_acilis_dur": True, "kapat_dur": False, "nedenler": ["gunluk_kayip"]})
    m.dakika()
    assert m.risk.acilis_durdu["koruyucu"] and m.kip == "sanal"
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert (s[0].karar, s[0].neden) == ("engel", "koruyucu") and m.hesap.sz(adr(1), "BTC") == 0.0
    _taze_koruyucu(m, saat, {"yeni_acilis_dur": False, "kapat_dur": False, "nedenler": []})
    m.dakika()
    assert not m.risk.acilis_durdu["koruyucu"]
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert s[0].karar == "emir" and m.hesap.sz(adr(1), "BTC") > 0
    _taze_koruyucu(m, saat, {"yeni_acilis_dur": True, "kapat_dur": False, "nedenler": ["x"]})
    m.dakika()
    s = m.olay_isle(olay("a:3", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))      # kapanış bayraktan etkilenmez
    assert s[0].karar == "emir" and m.hesap.sz(adr(1), "BTC") == 0.0


def test_motor_kapat_dur_bayragi_pozisyonlari_kapatir_ve_dur_yazar(tmp_path):
    m, saat, _ = _hazir_motor(tmp_path)
    assert m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))[0].karar == "emir"
    saat.ms += kr.MOTOR_ACILIS_BEKLEME_MS + 1000
    _taze_koruyucu(m, saat, {"yeni_acilis_dur": True, "kapat_dur": True, "nedenler": ["zirve_dusus"]})
    m.dakika()
    assert m.risk.dur and m.risk.dur_neden == "koruyucu" and (tmp_path / "durum/DUR").exists()
    assert m.acik_poz_sayisi() == 0


def test_motor_yeni_basladiysa_mandal_90sn_uygulanmaz(tmp_path):
    m, saat, _ = _hazir_motor(tmp_path)
    _taze_koruyucu(m, saat, {"yeni_acilis_dur": True, "kapat_dur": True, "nedenler": ["zirve_dusus"]})
    kr.motor_kancasi(m, saat())
    assert not m.risk.dur and m.risk.acilis_durdu["koruyucu"]          # açılış yine de durur


# ------------------------------------------------------------------ oto-kurulum
def test_birim_dosyasi_ve_kaynak_siniri():
    s = (DEPLOY / "sg-sanal-koruyucu.service").read_text(encoding="utf-8")
    assert "Type=simple" in s and "Restart=always" in s and "MemoryMax=100M" in s and "copytrade.koruyucu" in s and "WantedBy=multi-user.target" in s
    assert "TELEGRAM_BOT_TOKEN" not in s


def test_guncelle_koruyucu_servisini_kurar_etkinlestirir_ve_yeniden_baslatir(sunucu):   # noqa: F811
    tohum = sunucu.depo.parent / "tohum"
    git(tohum, "pull", "-q", "origin", "main")
    (tohum / "deploy/sg-sanal-koruyucu.service").write_text("[Service]\n# k1\n")
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "koruyucu birimi")
    git(tohum, "push", "-q", "origin", "main")
    sunucu.ci(*YESIL)
    r = sunucu.calistir()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (sunucu.birim / "sg-sanal-koruyucu.service").exists()
    log = sunucu.log.read_text()
    assert log.index("daemon-reload") < log.index("enable sg-sanal-koruyucu.service") < log.index("restart sg-sanal-koruyucu.service")
    assert "TG:" not in log


def test_yeni_donemde_eski_zirve_tasinmaz_yanlis_kapat_yok(tmp_path):
    k, saat, tgp = _kur(tmp_path)
    d = tmp_path / "durum"
    (d).mkdir(parents=True, exist_ok=True)
    (d / "donem.txt").write_text("2026-11-16T11:30:00Z\n")
    _motor_dosyalari(d, 13000.0, saat(), kasa=10000.0, risk_ek={"zirve": 13000.0})
    k.adim()
    (d / "donem.txt").write_text("2026-11-23T11:30:00Z\n")          # yeni dönem: kasa 10.000'e sıfırlandı
    _motor_dosyalari(d, 10000.0, saat(), kasa=10000.0)
    k.adim()
    b = _bayrak(tmp_path)
    assert not b["kapat_dur"] and not b["yeni_acilis_dur"]          # eski zirve (13.000) taşınsaydı %23 düşüş -> yanlış kapat
    assert json.loads((d / "ortak/koruyucu.json").read_text())["zirve"] == 10000.0
