"""G8: sunucu nabzı + sessiz ölüm alarmı (deploy/ dosyaları) ve saglik.gercek_kontrol. Sunucu/anahtar gerekmez; GITHUB_ACTIONS gerektirmez."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from copytrade import saglik

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
ADRES = "0x" + "ab12cd34ef" * 4                     # 40 hane
ANAHTAR = "0x" + "9f" * 32                          # 64 hane (özel anahtar biçimi)
TOKEN = "123456:SAHTE-TOKEN-ABC"


def _env(**ek):
    e = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GERCEK_YAYIM_HEDEF", "GERCEK_YAYIM_TOKEN")}
    e.update(ek)
    return e


def test_ana_birim_onfailure_ve_cikis3():
    s = (DEPLOY / "sg-canli.service").read_text(encoding="utf-8")
    assert re.search(r"^OnFailure=sg-canli-alarm\.service$", s, re.M)
    assert re.search(r"^RestartPreventExitStatus=3$", s, re.M)
    assert re.search(r"^Restart=on-failure$", s, re.M) and "StartLimitBurst=5" in s


def test_alarm_ve_yayim_birimleri():
    a = (DEPLOY / "sg-canli-alarm.service").read_text(encoding="utf-8")
    assert "Type=oneshot" in a and "alarm.sh" in a and "EnvironmentFile=-/etc/sg-canli.env" in a
    y = (DEPLOY / "sg-canli-yayim.service").read_text(encoding="utf-8")
    assert "gercek_yayimla.sh" in y and "EnvironmentFile=-/etc/sg-canli.env" in y
    t = (DEPLOY / "sg-canli-yayim.timer").read_text(encoding="utf-8")
    assert "OnUnitActiveSec=15min" in t and "WantedBy=timers.target" in t
    for ad in ("sg-canli.service", "sg-canli-alarm.service", "sg-canli-yayim.service", "sg-canli-yayim.timer"):
        assert not re.search(r"0x[0-9a-fA-F]{40}|HL_API_CUZDAN_ANAHTARI=\S", (DEPLOY / ad).read_text(encoding="utf-8")), ad


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze yok")
def test_systemd_analyze_verify():
    # /opt/sg-arge ve kullanıcı sunucuda olur; yalnız sözdizimi/anahtar hataları aranır
    r = subprocess.run(["systemd-analyze", "verify", *(str(DEPLOY / a) for a in ("sg-canli.service", "sg-canli-alarm.service", "sg-canli-yayim.service", "sg-canli-yayim.timer"))],
                       capture_output=True, text=True)
    cikti = r.stdout + r.stderr
    assert not re.search(r"Unknown key|Unknown section|Invalid|Failed to parse", cikti), cikti


def test_alarm_token_yokken_atlanir_ve_sifir():
    r = subprocess.run(["bash", str(DEPLOY / "alarm.sh"), "sg-canli"], capture_output=True, text=True, env=_env())
    assert r.returncode == 0 and "atlandı" in r.stdout


def test_alarm_token_basilmaz_ve_curl_hatasi_sifir(tmp_path):
    sahte = tmp_path / "curl"
    sahte.write_text("#!/bin/sh\ncat >/dev/null\nexit 22\n")
    sahte.chmod(0o755)
    r = subprocess.run(["bash", str(DEPLOY / "alarm.sh")], capture_output=True, text=True, env=_env(PATH=f"{tmp_path}:{os.environ['PATH']}", TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID="42"))
    assert r.returncode == 0 and TOKEN not in r.stdout + r.stderr and "gönderilemedi" in r.stderr


def _durum(tmp_path):
    d = tmp_path / "durum"
    d.mkdir()
    (d / "ozet.json").write_text(json.dumps({"kip": "gercek", "yazildi_ms": 1_000_000, "vardiya": "v1", "kasa_usd": 300, "acik": [{"adres": ADRES, "coin": "BTC"}],
                                             "HL_API_CUZDAN_ANAHTARI": ANAHTAR, "not": f"anahtar {ANAHTAR}"}))
    (d / "kilit.json").write_text(json.dumps({"vardiya": "v1", "nabiz_ms": 999_000, "birakildi": False}))
    (d / "motor.json").write_text(json.dumps({"hl_ofset": 12.5, "kasa_usd": 300, "islenen": []}))
    (d / "risk.json").write_text(json.dumps({"dur": False, "acilis_durdu": {"mutabakat": True}}))
    return d


def test_yayim_maskeler_yerel_nabiz(tmp_path):
    d, c = _durum(tmp_path), tmp_path / "yayim"
    r = subprocess.run(["bash", str(DEPLOY / "gercek_yayimla.sh")], capture_output=True, text=True, env=_env(DURUM_DIZIN=str(d), NABIZ_DIZIN=str(c)))
    assert r.returncode == 0, r.stderr
    assert "yalnız yerel nabız" in r.stdout
    hepsi = r.stdout + r.stderr + "".join((c / a).read_text(encoding="utf-8") for a in ("ozet.json", "kilit.json", "nabiz.json"))
    assert ADRES not in hepsi and ANAHTAR not in hepsi and "9f9f9f" not in hepsi          # tam adres / anahtar yok
    oz = json.loads((c / "ozet.json").read_text(encoding="utf-8"))
    assert oz["acik"][0]["adres"] == ADRES[:6] + "…" + ADRES[-4:]
    assert oz["HL_API_CUZDAN_ANAHTARI"] == "[gizli]"
    nb = json.loads((c / "nabiz.json").read_text(encoding="utf-8"))
    assert nb["kip"] == "gercek" and nb["hl_ofset"] == 12.5 and nb["mutabakat"] is True and nb["dur"] is False
    assert not (c / "git").exists()                                                      # hedef yok: git yok


def test_yayim_ozet_yoksa_hata(tmp_path):
    r = subprocess.run(["bash", str(DEPLOY / "gercek_yayimla.sh")], capture_output=True, text=True, env=_env(DURUM_DIZIN=str(tmp_path / "yok"), NABIZ_DIZIN=str(tmp_path / "y")))
    assert r.returncode == 1


@pytest.mark.skipif(shutil.which("git") is None, reason="git yok")
def test_yayim_hedef_git_dali(tmp_path):
    uzak = tmp_path / "uzak.git"
    subprocess.run(["git", "init", "-q", "--bare", str(uzak)], check=True)
    d, c = _durum(tmp_path), tmp_path / "yayim"
    r = subprocess.run(["bash", str(DEPLOY / "gercek_yayimla.sh")], capture_output=True, text=True, env=_env(DURUM_DIZIN=str(d), NABIZ_DIZIN=str(c), GERCEK_YAYIM_HEDEF=str(uzak)))
    assert r.returncode == 0, r.stderr
    icerik = subprocess.run(["git", "--git-dir", str(uzak), "show", "canli-gercek:durum/ozet.json"], capture_output=True, text=True).stdout
    assert ADRES not in icerik and ANAHTAR not in icerik and "…" in icerik


# ---------------------------------------------------------------- saglik.gercek_kontrol
SIMDI = 10_000_000


def _kodlar(b):
    return {x.kod: x.seviye for x in b}


def test_gercek_saglikli():
    ozet = {"kip": "gercek", "yazildi_ms": SIMDI - 5 * 60_000, "kasa_usd": 300}
    nabiz = {"hl_ofset": 10.0, "kasa_usd": 300, "mutabakat": False, "dur": False}
    assert saglik.gercek_kontrol(SIMDI, ozet, nabiz, {"nabiz_ms": SIMDI - 60_000, "birakildi": False}) == []


def test_gercek_nabiz_eski_ofset_mutabakat_kritik():
    ozet = {"kip": "gercek", "yazildi_ms": SIMDI - 25 * 60_000, "kasa_usd": 300}
    nabiz = {"hl_ofset": -120.0, "kasa_usd": 300, "mutabakat": True}                      # sınır 75 $
    k = _kodlar(saglik.gercek_kontrol(SIMDI, ozet, nabiz, {"nabiz_ms": SIMDI - 21 * 60_000, "birakildi": False}))
    assert k == {"gercek_nabiz_eski": "KRITIK", "gercek_hl_ofset_buyuk": "KRITIK", "gercek_mutabakat": "KRITIK"}


def test_gercek_nabiz_19dk_ve_ofset_sinirda_temiz():
    ozet = {"kip": "gercek", "yazildi_ms": SIMDI - 19 * 60_000}
    assert saglik.gercek_kontrol(SIMDI, ozet, {"hl_ofset": 75.0, "kasa_usd": 300}, None) == []


def test_sanal_kip_ve_veri_yok():
    assert saglik.gercek_kontrol(SIMDI, {"kip": "sanal", "yazildi_ms": 0}, {"mutabakat": True}) == []          # sanal: gerçek kip bulgusu yok
    assert _kodlar(saglik.gercek_kontrol(SIMDI, None, None)) == {"gercek_nabiz_yok": "KRITIK"}


def test_uretim_sanal_kontrol_degismedi():
    ozet = {"kip": "gercek", "yazildi_ms": SIMDI - 5 * 60_000}
    kadro = {"kosu_ms": SIMDI - 60_000, "gecti_sayisi": 12, "saha_n": 11, "satirlar": [{"katman": "ilk11"}] * 11}
    assert "gercek_nabiz_eski" not in _kodlar(saglik.kontrol(SIMDI, ozet, kadro))
