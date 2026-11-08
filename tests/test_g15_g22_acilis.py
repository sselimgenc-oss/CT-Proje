"""Denetim 2026-11-08: G-9, G-15 (çıkış kodları), G-20 (`--kontrol` asıl durum dizini), G-21 (flock), G-22 (env dosyaları, kilitli bağımlılık, CI), S-21 (yayım betiği). Ağsız; anahtar/token sahte."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import ortam_dosyasi as od
from copytrade.canli import telegram as tg
from copytrade.kurallar import load_rules
from tests.test_canli_motor import CHAT, RULES, TOKEN, SahteHL, SahteTG, adr, kur_kip, n_kadro

KOK = Path(__file__).resolve().parent.parent
DEPLOY = KOK / "deploy"
HESAP, AGENT = adr(7), adr(9)
ANAHTAR = "gizli-anahtar-xyz"
ORTAM = {"HL_API_CUZDAN_ANAHTARI": ANAHTAR, "HL_HESAP_ADRESI": HESAP, "CANLI_KASA_USD": "300"}


# ================================================================================================ G-15 çıkış kodları
def test_api_cuzdan_hl_okunamadi_gecici_agent_yok_kalici():
    def kopuk(y):
        raise ConnectionError("ag")
    r = mt.api_cuzdan_dogrula(kopuk, ORTAM, turet=lambda k: AGENT)
    assert r["tamam"] is False and r["hl_okunamadi"] is True and "HL okunamadı" in r["neden"]
    h = SahteHL(hesap=300.0)
    h.agent_sahibi = None                                                     # userRole yanıt verdi: agent değil (extraAgents SahteHL'de yok → istisna)
    r2 = mt.api_cuzdan_dogrula(h, ORTAM, turet=lambda k: AGENT)
    assert r2["hl_okunamadi"] is False and r2["neden"] == "agent doğrulanamadı"

    def yalniz_liste(y):                                                      # userRole koptu, extraAgents boş liste döndü: agent GERÇEKTEN yok → kalıcı
        if y["type"] == "userRole":
            raise ConnectionError("ag")
        return []
    assert mt.api_cuzdan_dogrula(yalniz_liste, ORTAM, turet=lambda k: AGENT)["hl_okunamadi"] is False


def test_etkin_kasa_ag_hatasi_hl_okunamadi():
    def kopuk(y):
        raise ConnectionError("x")
    with pytest.raises(mt.HlOkunamadi):
        mt.etkin_kasa(RULES, "gercek", kopuk, {"CANLI_KASA_USD": "300", "HL_HESAP_ADRESI": HESAP})


def test_acilis_yeniden_dene_gecici_yeniden_kalici_hemen():
    uyku, cagri = [], []

    def bir_kez_kopuk():
        cagri.append(1)
        if len(cagri) == 1:
            raise OSError("ag")
        return "ok"
    assert mt.acilis_yeniden_dene(bir_kez_kopuk, (1.0, 2.0), uyu=uyku.append) == "ok" and uyku == [1.0] and len(cagri) == 2

    cagri.clear()

    def hep_429():
        cagri.append(1)
        raise mt.RateLimitError("429")
    with pytest.raises(mt.HlOkunamadi, match="RateLimitError"):
        mt.acilis_yeniden_dene(hep_429, (1.0, 2.0, 3.0), uyu=uyku.append)
    assert len(cagri) == 4                                                    # 1 + 3 yeniden deneme

    cagri.clear()

    def kalici():
        cagri.append(1)
        raise mt.KipHatasi("DUR dosyası var")
    with pytest.raises(mt.KipHatasi, match="DUR") as e:
        mt.acilis_yeniden_dene(kalici, (1.0,), uyu=uyku.append)
    assert not isinstance(e.value, mt.HlOkunamadi) and len(cagri) == 1


def _main_kur(monkeypatch, post, turet=lambda k: AGENT):
    from tests.test_g1_alarm import SahteTg as TabanTg

    class SahteTg(TabanTg):
        ornekler: list = []
        offset, kayit, maske = 0, None, []

    monkeypatch.setattr(TabanTg, "ornekler", [])
    monkeypatch.setattr(mt.tg, "Telegram", SahteTg)
    monkeypatch.setattr(mt, "rest_post_olustur", lambda rules: post)
    monkeypatch.setattr(mt, "kip_belirle", lambda rules, istenen=None, ortam=None: "gercek")
    monkeypatch.setattr(mt, "kasa_belirle", lambda rules, kip, ortam=None: (300.0, "ortam"))
    monkeypatch.setattr(mt, "ACILIS_BEKLEME_SN", (0.0, 0.0))
    monkeypatch.setenv("HL_API_CUZDAN_ANAHTARI", ANAHTAR)
    monkeypatch.setenv("HL_HESAP_ADRESI", HESAP)
    monkeypatch.setattr(mt, "anahtardan_adres", turet)
    olustu = []
    monkeypatch.setattr(mt, "gercek_yurutucu_olustur", lambda post, rules: olustu.append(1) or object())
    return TabanTg, olustu


def test_main_hl_kesintisi_75_yeniden_dener_motor_kurulmaz(monkeypatch, tmp_path):
    istek = []

    def kopuk(y):
        istek.append(y["type"])
        raise ConnectionError("ag")
    TabanTg, olustu = _main_kur(monkeypatch, kopuk)
    assert mt.main(["--durum-dizin", str(tmp_path / "durum")]) == mt.CIKIS_GECICI == 75
    assert not olustu and istek.count("userRole") == 3                        # 1 + 2 yeniden deneme (ACILIS_BEKLEME_SN iki adım)
    mesaj = TabanTg.ornekler[0].gonderilen[0]
    assert "Çıkış kodu 75" in mesaj and "geçici" in mesaj and "agent doğrulanamadı" not in mesaj and ANAHTAR not in mesaj


def test_main_kasa_okumasi_kopuk_75_sonra_duzelirse_acilir(monkeypatch, tmp_path):
    h = SahteHL(hesap=300.0)
    cagri = []

    def bazen(y):
        if y["type"] == "clearinghouseState" and len(cagri) < 1:
            cagri.append(1)
            raise ConnectionError("ag")
        return h(y)
    _main_kur(monkeypatch, bazen)
    yakalanan = {}

    class M:
        def __init__(self, rules, yur, post, tgram, durum, kayit, kadro_oku, vardiya_id="yerel"):
            yakalanan["kasa"], self.cikis_kodu = rules["canli_kasa_usd"], 0

        def baslat(self):
            yakalanan["kilit"] = mt.motor_kilidi_tutuluyor(tmp_path / "durum")

    async def calis(motor, sure_sn=None):
        return {}
    monkeypatch.setattr(mt, "Motor", M)
    monkeypatch.setattr(mt, "calis", calis)
    assert mt.main(["--durum-dizin", str(tmp_path / "durum")]) == 0
    assert yakalanan == {"kasa": 300.0, "kilit": True} and cagri == [1]
    assert mt.motor_kilidi_tutuluyor(tmp_path / "durum") is False            # çıkışta kilit bırakıldı


@pytest.mark.parametrize("hata, kod", [(ConnectionError("ag"), 75), (mt.HlOkunamadi("x"), 75), (mt.KipHatasi("DUR dosyası var: elle silinmeden yeniden açılmaz"), 3)])
def test_main_baslat_hatasi_kodu(monkeypatch, tmp_path, hata, kod):
    _main_kur(monkeypatch, SahteHL(hesap=300.0))

    class M:
        def __init__(self, *a, **k):
            pass

        def baslat(self):
            raise hata
    monkeypatch.setattr(mt, "Motor", M)
    assert mt.main(["--durum-dizin", str(tmp_path / "durum")]) == kod


def test_main_beklenmedik_hata_1_ve_alarm(monkeypatch, tmp_path):
    TabanTg, _ = _main_kur(monkeypatch, SahteHL(hesap=300.0))

    class M:
        def __init__(self, *a, **k):
            pass

        def baslat(self):
            pass

    async def calis(motor, sure_sn=None):
        raise ZeroDivisionError("gizli-anahtar-xyz")
    monkeypatch.setattr(mt, "Motor", M)
    monkeypatch.setattr(mt, "calis", calis)
    assert mt.main(["--durum-dizin", str(tmp_path / "durum")]) == 1
    mesaj = TabanTg.ornekler[0].gonderilen[-1]
    assert "ZeroDivisionError" in mesaj and ANAHTAR not in mesaj


def test_main_anahtar_yok_3_traceback_yok(monkeypatch, tmp_path):
    def yok(rules, istenen=None, ortam=None):
        raise mt.AnahtarYok("HL_API_CUZDAN_ANAHTARI ve HL_HESAP_ADRESI gerekli")
    from tests.test_g1_alarm import SahteTg
    monkeypatch.setattr(SahteTg, "ornekler", [])
    monkeypatch.setattr(mt.tg, "Telegram", SahteTg)
    monkeypatch.setattr(mt, "kip_belirle", yok)
    assert mt.main(["--durum-dizin", str(tmp_path)]) == 3


def test_main_sdk_kurulamazsa_3_anahtar_metni_yok(monkeypatch, tmp_path):
    TabanTg, _ = _main_kur(monkeypatch, SahteHL(hesap=300.0))

    def bozuk(post, rules):
        raise ValueError(f"bozuk anahtar {ANAHTAR}")
    monkeypatch.setattr(mt, "gercek_yurutucu_olustur", bozuk)
    assert mt.main(["--durum-dizin", str(tmp_path / "durum")]) == 3
    assert ANAHTAR not in TabanTg.ornekler[0].gonderilen[0] and "ValueError" in TabanTg.ornekler[0].gonderilen[0]


# ================================================================================================ G-21 tek süreç
def test_gercek_kip_goreli_durum_dizini_3_ag_yok(monkeypatch, tmp_path):
    istek = []
    _main_kur(monkeypatch, lambda y: istek.append(y) or SahteHL(hesap=300.0)(y))
    monkeypatch.chdir(tmp_path)
    assert mt.main(["--durum-dizin", "durum"]) == 3
    assert not istek and not (tmp_path / "durum").exists()


def test_flock_ayni_surecte_ikinci_kilit_reddedilir(tmp_path):
    d = tmp_path / "durum"
    assert mt.motor_kilidi_tutuluyor(d) is False and not d.exists()          # salt okunur: dizin/dosya OLUŞTURMAZ
    fd = mt.motor_kilidi_al(d)
    try:
        assert (d / "motor.lock").read_text().strip() == str(os.getpid())
        with pytest.raises(mt.KipHatasi, match="ikinci motor açılmaz"):
            mt.motor_kilidi_al(d)
        assert mt.motor_kilidi_tutuluyor(d) is True
    finally:
        os.close(fd)
    assert mt.motor_kilidi_tutuluyor(d) is False
    os.close(mt.motor_kilidi_al(d))                                          # bırakılınca yeniden alınır (bayat kilit yok)


def test_flock_baska_surec_tutarken_main_3(monkeypatch, tmp_path):
    d = tmp_path / "durum"
    d.mkdir()
    kod = ("import fcntl, os, sys, time\nfd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\nfcntl.flock(fd, fcntl.LOCK_EX)\nprint('hazir', flush=True)\ntime.sleep(30)\n")
    p = subprocess.Popen([sys.executable, "-c", kod, str(d / "motor.lock")], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "hazir"
        TabanTg, olustu = _main_kur(monkeypatch, SahteHL(hesap=300.0))
        assert mt.main(["--durum-dizin", str(d)]) == 3
        assert not olustu and "başka bir motor" in TabanTg.ornekler[0].gonderilen[0]
        assert mt.motor_kilidi_tutuluyor(d) is True
    finally:
        p.kill()
        p.wait()
    assert mt.motor_kilidi_tutuluyor(d) is False                             # süreç ölünce çekirdek bırakır


def test_sanal_kip_kilit_dosyasi_yazmaz(monkeypatch, tmp_path):
    class M:
        def __init__(self, *a, **k):
            self.cikis_kodu = 0

        def baslat(self):
            pass

    async def calis(motor, sure_sn=None):
        return {}
    monkeypatch.setattr(mt, "Motor", M)
    monkeypatch.setattr(mt, "calis", calis)
    monkeypatch.setattr(mt, "kip_belirle", lambda rules, istenen=None: "sanal")
    monkeypatch.chdir(tmp_path)
    assert mt.main(["--durum-dizin", "durum"]) == 0                          # sanal (Actions): göreli dizin serbest, kilit yok
    assert not (tmp_path / "durum" / "motor.lock").exists()


# ================================================================================================ G-20 --kontrol
def kont(post, durum=None, kadro=None, tgp=None, saat_ms=None):
    tgp = tgp or SahteTG()
    k = n_kadro(3) if kadro is None else kadro
    return mt.kontrol(RULES, "gercek", post, lambda: k, tg.Telegram(TOKEN, CHAT, tgp), ortam=ORTAM, turet=lambda x: AGENT, durum_dizin=durum, saat_ms=saat_ms), tgp


def _dosyalar(d: Path) -> dict:
    return {str(p.relative_to(d)): (p.stat().st_mtime_ns, p.stat().st_size) for p in d.rglob("*")} if d.exists() else {}


def test_kontrol_bos_dizin_tamam_deneme_mesaji_gider(tmp_path):
    d = tmp_path / "durum"
    r, tgp = kont(SahteHL(hesap=300.0), d)
    assert r["tamam"] is True, r
    assert r["durum"] == {"dizin": str(d), "dizin_var": False, "durum_var": False, "kayitli_kip": None, "kip_uyumu": True, "kip_neden": None, "dur": False, "mutabakat": False,
                          "risk_dur": False, "yerel_acik_poz": 0, "motor_calisiyor": False}
    assert (r["hl_acik_poz"], r["hl_acik_emir"], r["hl_acik_ok"], r["kadro"]["taze"], r["saat"]["ok"], r["telegram"]["deneme_gonderildi"]) == (0, 0, True, True, True, True)
    assert len(tgp.gonderilen) == 1 and tgp.gonderilen[0].startswith("🚨 DENEME") and "GERÇEK PARA" in tgp.gonderilen[0]
    ham = json.dumps(r)
    assert ANAHTAR not in ham and HESAP not in ham and TOKEN not in ham and not d.exists()


def test_kontrol_sanal_durum_dizini_kip_uyumsuz_ve_salt_okunur(tmp_path):
    m, _ = kur_kip(tmp_path, "sanal", 1000.0)
    m.baslat()
    m.durum_yaz()
    d = tmp_path / "durum"
    once = _dosyalar(d)
    r, _ = kont(SahteHL(hesap=300.0), d)
    assert r["tamam"] is False and r["durum"]["kip_uyumu"] is False and "sanal durum dizininde gerçek kip açılmaz" in r["durum"]["kip_neden"] and r["durum"]["kayitli_kip"] == "sanal"
    assert _dosyalar(d) == once                                               # hiçbir dosya yazılmadı/değişmedi


def _gercek_durum(d: Path, sz=0.1, kasa_ayar=300.0, risk=None, dur=False):
    d.mkdir(parents=True, exist_ok=True)
    (d / "motor.json").write_text(json.dumps({"kip": "gercek", "kasa_ayar_usd": kasa_ayar}))
    (d / "hesap.json").write_text(json.dumps({"kasa_usd": 300.0, "poz": {adr(1): {"BTC": {"sz": sz, "giris": 100.0, "acilis_ms": 0, "kaldirac": 3.0}}}}))
    (d / "risk.json").write_text(json.dumps(risk or {}))
    if dur:
        (d / "DUR").write_text(json.dumps({"neden": "kapat"}))


def test_kontrol_dur_mutabakat_kasa_degisimi(tmp_path):
    _gercek_durum(tmp_path / "a", dur=True)
    r, _ = kont(SahteHL(hesap=300.0, pozlar={HESAP: {"BTC": 0.1}}), tmp_path / "a")
    assert r["durum"]["dur"] is True and r["durum"]["yerel_acik_poz"] == 1 and r["hl_acik_poz"] == 1 and r["hl_acik_ok"] is True and r["tamam"] is False
    _gercek_durum(tmp_path / "b", risk={"acilis_durdu": {"mutabakat": True}})
    r, _ = kont(SahteHL(hesap=300.0), tmp_path / "b")
    assert r["durum"]["mutabakat"] is True and r["durum"]["kip_uyumu"] is True and r["tamam"] is False
    _gercek_durum(tmp_path / "c", kasa_ayar=500.0)                           # ayar 500 → 300, açık pozisyon var: motor açılmaz
    r, _ = kont(SahteHL(hesap=300.0), tmp_path / "c")
    assert r["durum"]["kip_uyumu"] is False and "kasa ayarı değişti" in r["durum"]["kip_neden"] and r["tamam"] is False
    _gercek_durum(tmp_path / "d")                                             # temiz gerçek dizin + HL'de pozisyon (motorun bildiği): tamam
    r, _ = kont(SahteHL(hesap=300.0, pozlar={HESAP: {"BTC": 0.1}}), tmp_path / "d")
    assert r["tamam"] is True and r["hl_acik_poz"] == 1


def test_kontrol_hl_yetim_pozisyon_acik_emir_saat_kadro(tmp_path):
    r, _ = kont(SahteHL(hesap=300.0, pozlar={HESAP: {"ETH": -2.0}}), tmp_path / "bos")
    assert r["hl_acik_poz"] == 1 and r["hl_acik_ok"] is False and r["tamam"] is False      # boş dizin + HL pozisyonu = yetim
    h = SahteHL(hesap=300.0)
    h.acik_emirler = [{"coin": "BTC", "oid": 1}]
    r, _ = kont(h, tmp_path / "bos")
    assert r["hl_acik_emir"] == 1 and r["tamam"] is False
    h = SahteHL(hesap=300.0)
    h.hl_saat_ms = 1_000_000
    r, _ = kont(h, tmp_path / "bos", saat_ms=lambda: 1_000_000 + 2_600)     # sunucu 2,6 sn ileride (sınır 2 sn)
    assert r["saat"] == {"sapma_ms": 2600, "gidis_donus_ms": 0, "sinir_ms": 2000, "ok": False} and r["tamam"] is False
    r, _ = kont(h, tmp_path / "bos", saat_ms=lambda: 1_000_000 - 1_500)
    assert r["saat"]["ok"] is True and r["saat"]["sapma_ms"] == -1500
    bayat = n_kadro(3, int(time.time() * 1000) - int((float(RULES["canli_kadro_eski_saat"]) + 1) * 3_600_000))
    r, _ = kont(SahteHL(hesap=300.0), tmp_path / "bos", kadro=bayat)
    assert r["kadro"]["var"] is True and r["kadro"]["taze"] is False and r["tamam"] is False     # gerçek kipte taze ZORUNLU


def test_kontrol_telegram_gonderilemezse_tamam_degil(tmp_path):
    r, _ = kont(SahteHL(hesap=300.0), tmp_path / "bos", tgp=SahteTG(hata=True))
    assert r["telegram"] == {"yapilandirildi": True, "deneme_gonderildi": False} and r["tamam"] is False and TOKEN not in json.dumps(r)


def test_main_kontrol_gercek_durum_dizinine_yazmaz_rapor_istege_bagli(monkeypatch, tmp_path):
    _gercek_durum(tmp_path / "durum", sz=0.0)
    once = _dosyalar(tmp_path / "durum")
    gonderilen = []
    monkeypatch.setattr(mt.tg, "varsayilan_post", lambda url, yuk: gonderilen.append(yuk["text"]) or {"ok": True})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setenv("CANLI_KASA_USD", "300")
    monkeypatch.setenv("HL_API_CUZDAN_ANAHTARI", ANAHTAR)
    monkeypatch.setenv("HL_HESAP_ADRESI", HESAP)
    monkeypatch.setattr(mt, "kip_belirle", lambda rules, istenen=None: "gercek")
    monkeypatch.setattr(mt, "rest_post_olustur", lambda rules: SahteHL(hesap=300.0))
    monkeypatch.setattr(mt, "http_kadro_oku", lambda rules, dal=None: n_kadro(3))
    monkeypatch.setattr(mt, "anahtardan_adres", lambda k: AGENT)
    assert mt.main(["--kontrol", "--durum-dizin", str(tmp_path / "durum")]) == 0
    assert _dosyalar(tmp_path / "durum") == once and len(gonderilen) == 1
    assert mt.main(["--kontrol", "--durum-dizin", str(tmp_path / "durum"), "--rapor", str(tmp_path / "rapor.json")]) == 0
    r = json.loads((tmp_path / "rapor.json").read_text())
    assert r["tamam"] is True and r["durum"]["kayitli_kip"] == "gercek" and ANAHTAR not in json.dumps(r)


# ================================================================================================ G-9 / G-22 ortam dosyaları
def test_ortam_satir_ici_aciklama_ve_bicim_hatalari_degersiz():
    metin = ("HL_API_CUZDAN_ANAHTARI=" + "ab" * 32 + "\nHL_HESAP_ADRESI=" + HESAP + "\nCANLI_KIP=gercek\n"
             "CANLI_KASA_USD=300        # $; gerçek kipte ZORUNLU\nTELEGRAM_KOMUT=             # sunucuda boş bırak\n")
    s = od.denetle(metin, "motor")
    assert any("satır 4" in x and "'#'" in x for x in s) and any("satır 5" in x and "'#'" in x for x in s)
    assert any("CANLI_KASA_USD sayı değil" in x for x in s)                 # systemd değeri "300        # …" okur → motor açılmazdı
    assert not any(("ab" * 32) in x or HESAP in x for x in s)
    s = od.denetle("CANLI_KIP = gercek\nexport HL_HESAP_ADRESI=0x12\nHL_API_CUZDAN_ANAHTARI=\"x\"\n", "motor")
    assert any("'=' çevresinde boşluk" in x for x in s) and any("export" in x for x in s) and any("tırnaklı" in x for x in s) and any("biçimi geçersiz" in x for x in s)


def test_ortam_dogru_dosyalar_ve_ayirma_kurallari():
    motor = "\n".join(["# gerçek kip", "HL_API_CUZDAN_ANAHTARI=0x" + "ab" * 32, "HL_HESAP_ADRESI=" + HESAP, "CANLI_KIP=gercek", "CANLI_KASA_USD=300", "TELEGRAM_KOMUT="]) + "\n"
    assert od.denetle(motor, "motor") == []
    assert od.denetle("TELEGRAM_BOT_TOKEN=123:abc\nTELEGRAM_CHAT_ID=-4242\n", "telegram") == []
    assert od.denetle("", "yayim") == []
    assert any("OLAMAZ" in x for x in od.denetle("TELEGRAM_BOT_TOKEN=1:a\nTELEGRAM_CHAT_ID=1\nHL_API_CUZDAN_ANAHTARI=0x" + "ab" * 32 + "\n", "telegram"))
    assert any("OLAMAZ" in x for x in od.denetle("HL_API_CUZDAN_ANAHTARI=0x1\n", "yayim"))
    assert any("taşınmalı" in x for x in od.denetle(motor + "TELEGRAM_BOT_TOKEN=1:a\n", "motor"))
    assert any("1000" in x for x in od.denetle(motor.replace("CANLI_KASA_USD=300", "CANLI_KASA_USD=1500"), "motor"))
    assert any("zorunlu" in x for x in od.denetle(motor.replace("CANLI_KASA_USD=300\n", ""), "motor"))
    assert od.KASA_UST_USD == float(load_rules()["canli_kasa_ust_usd"])


def test_ortam_dosyasi_cli_izin_ve_deger_basilmaz(tmp_path, capsys):
    f = tmp_path / "sg-canli.env"
    f.write_text("HL_API_CUZDAN_ANAHTARI=0x" + "cd" * 32 + "\nHL_HESAP_ADRESI=" + HESAP + "\n")
    f.chmod(0o644)
    assert od.main(["motor", str(f)]) == 1
    cikti = capsys.readouterr().out
    assert "izin 644" in cikti and "cd" * 32 not in cikti and HESAP not in cikti
    f.chmod(0o600)
    assert od.main(["motor", str(f)]) == 0 and "tamam" in capsys.readouterr().out


def _kod_bloklari(md: str) -> list[list[str]]:
    return [[s for s in b.splitlines() if s.strip()] for b in re.findall(r"```[a-z]*\n(.*?)```", md, re.S)]          # girintili (liste içi) bloklar dahil


@pytest.mark.parametrize("belge", ["kurulum.md", "ACILIS_KONTROL.md"])
def test_belgelerdeki_ortam_sablonlari_systemd_uyumlu(belge):
    md = (DEPLOY / belge).read_text(encoding="utf-8")
    sablonlar = [[s.strip() for s in b] for b in _kod_bloklari(md) if b and all(re.match(r"\s*(HL_|CANLI_|TELEGRAM_|GERCEK_)\w*=", s) for s in b)]
    assert len(sablonlar) >= 2, belge
    for b in sablonlar:
        assert od.ayristir("\n".join(b) + "\n")[1] == [], b
        assert not any("#" in s for s in b), b


def test_kurulum_anahtar_komut_satirina_dusmez_ve_gecis_adimlari():
    md = (DEPLOY / "kurulum.md").read_text(encoding="utf-8")
    assert "xargs" not in md and "$(sudo cat" not in md and "env $(" not in md                  # G-9: anahtar argv/sudo kaydına düşmez
    assert "systemctl start sg-canli-kontrol" in md
    assert re.search(r"mv /var/lib/sg-canli /var/lib/sg-canli\.sanal-", md)                    # G-20 arşiv adımı
    guncelleme = md.split("## 6. Güncelleme", 1)[1].split("## 7.", 1)[0]
    assert "pip install --require-hashes -r /opt/sg-arge/requirements-canli.lock" in guncelleme   # G-22: güncelleme bağımlılığı kilitten kurar
    assert "requirements-canli.txt\n" not in md.split("## 2.", 1)[0].replace("`requirements-canli.txt` yalnız", "")
    ak = (DEPLOY / "ACILIS_KONTROL.md").read_text(encoding="utf-8")
    for parca in ("--require-hashes", "sg-canli-kontrol", "sg-canli.sanal-ARSIV", "ortam_dosyasi", "/kapat", "Revoke"):
        assert parca in ak, parca


# ================================================================================================ G-22 / G-15 birimler
def _birim(ad: str) -> str:
    return (DEPLOY / ad).read_text(encoding="utf-8")


def test_birimler_anahtar_yalniz_motor_ve_kontrolde_yeniden_baslatma():
    m = _birim("sg-canli.service")
    for satir in ("RestartSec=30", "RestartMaxDelaySec=600", "RestartPreventExitStatus=3", "Restart=on-failure", "EnvironmentFile=/etc/sg-canli.env", "EnvironmentFile=/etc/sg-canli-telegram.env"):
        assert re.search(rf"^{re.escape(satir)}$", m, re.M), satir
    k = _birim("sg-canli-kontrol.service")
    assert "--kontrol --durum-dizin /var/lib/sg-canli/durum" in k and "EnvironmentFile=/etc/sg-canli.env" in k and "ReadOnlyPaths=-/var/lib/sg-canli" in k
    assert "ReadWritePaths" not in k and "ProtectSystem=strict" in k
    for ad in ("sg-canli-alarm.service", "sg-canli-yayim.service"):
        assert "/etc/sg-canli.env" not in _birim(ad), ad                                     # G-22: HL anahtarı bu birimlere yüklenmez
    assert "EnvironmentFile=-/etc/sg-canli-telegram.env" in _birim("sg-canli-alarm.service")
    assert "sg-canli-telegram.env" not in _birim("sg-canli-yayim.service") and "EnvironmentFile=-/etc/sg-canli-yayim.env" in _birim("sg-canli-yayim.service")


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze yok")
def test_kontrol_birimi_systemd_analyze():
    r = subprocess.run(["systemd-analyze", "verify", str(DEPLOY / "sg-canli-kontrol.service")], capture_output=True, text=True)
    assert not re.search(r"Unknown key|Unknown section|Invalid|Failed to parse", r.stdout + r.stderr), r.stdout + r.stderr


def test_kilit_dosyasi_hashli_ve_txt_ile_uyumlu():
    kilit = (KOK / "requirements-canli.lock").read_text(encoding="utf-8")
    paketler = dict(re.findall(r"^([a-z0-9][a-z0-9._-]*)==([^\s\\]+)", kilit, re.M | re.I))
    bloklar = re.split(r"\n(?=[a-z0-9])", "\n".join(s for s in kilit.splitlines() if not s.startswith("#")), flags=re.I)        # her paket bloğu: ad==sürüm + hash satırları
    assert len(paketler) >= 25 and all("--hash=sha256:" in b for b in bloklar if b.strip())
    for satir in (KOK / "requirements-canli.txt").read_text(encoding="utf-8").splitlines():
        ad, _, surum = satir.split("#")[0].strip().partition("==")
        if ad:
            assert paketler.get(ad.lower()) == surum.strip(), ad


def test_ci_kilitten_kurar_ve_sdk_testi_kosar():
    import yaml
    ci = yaml.safe_load((KOK / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    adimlar = " ".join(str(s.get("run", "")) for s in ci["jobs"]["canli_sdk"]["steps"])
    assert "--require-hashes -r requirements-canli.lock" in adimlar and "tests/test_sdk_kablo.py" in adimlar
    assert any((s.get("env") or {}).get("SDK_ZORUNLU") == "1" for s in ci["jobs"]["canli_sdk"]["steps"])


# ================================================================================================ S-21 yayım betiği
@pytest.mark.skipif(shutil.which("git") is None, reason="git yok")
def test_yayim_token_argv_de_yok_hata_gizlenmez(tmp_path):
    from tests.test_deploy import _durum, _env
    gercek_git = shutil.which("git")
    kutuk = tmp_path / "git_kutuk.txt"
    sahte = tmp_path / "bin" / "git"
    sahte.parent.mkdir()
    sahte.write_text(f"""#!/bin/bash
printf '%s\\n' "ARGV: $*" >> "{kutuk}"
case " $* " in *" push "*) echo "fatal: kimlik reddedildi https://kisi:${{GERCEK_YAYIM_TOKEN}}@ornek.invalid/depo.git (${{GIT_CONFIG_VALUE_0}})" >&2; exit 128;; esac
exec "{gercek_git}" "$@"
""")
    sahte.chmod(0o755)
    uzak = tmp_path / "uzak.git"
    subprocess.run([gercek_git, "init", "-q", "--bare", str(uzak)], check=True)
    jeton = "ghp_SAHTEjeton1234567890"
    d, c = _durum(tmp_path), tmp_path / "yayim"
    r = subprocess.run(["bash", str(DEPLOY / "gercek_yayimla.sh")], capture_output=True, text=True,
                       env=_env(PATH=f"{sahte.parent}:{os.environ['PATH']}", DURUM_DIZIN=str(d), NABIZ_DIZIN=str(c), GERCEK_YAYIM_HEDEF=str(uzak), GERCEK_YAYIM_TOKEN=jeton))
    assert r.returncode == 1
    kayit = kutuk.read_text()
    assert jeton not in kayit and "extraheader" not in kayit and " push " in kayit                # token komut satırında YOK
    assert "kimlik reddedildi" in r.stderr and "itme başarısız" in r.stderr                        # hata gizlenmedi
    assert jeton not in r.stdout + r.stderr and "[gizli]" in r.stderr                              # maskeli
