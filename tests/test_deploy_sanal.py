"""Sunucu sanal motoru (deploy/sg-sanal*, sanal_*.sh) ve Actions -> sunucu geçiş anahtarı (SUNUCU_AKTIF). Sunucu/anahtar/ağ gerekmez; gerçek git ile yerel origin kullanılır."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
ZAMANLAMA = ROOT / ".github/scripts/zamanlama_kontrol.sh"
BIRIMLER = ("sg-sanal.service", "sg-sanal-yayim.service", "sg-sanal-yayim.timer", "sg-sanal-pano.service", "sg-sanal-pano.timer", "sg-sanal-alarm.service", "sg-sanal-kontrol.service")


def _env(**ek):
    e = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "SUNUCU_AKTIF", "SUNUCU_MOD", "VERI_DALI", "KADRO_DALI", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")}
    e.update(ek)
    return e


def git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)


# ------------------------------------------------------------------------------------------------ birim dosyaları
def test_sanal_ana_birim_kip_kasa_ve_anahtarsiz():
    s = (DEPLOY / "sg-sanal.service").read_text(encoding="utf-8")
    assert "--kip sanal --sanal-kasa-usd 10000" in s and "--sure-sn" not in s                      # sürekli çalışır, vardiya süresi yok
    assert "gercek" not in re.sub(r"(?m)^#.*$", "", s).lower()                                       # birim gerçek kipe işaret etmez
    assert "/etc/sg-canli.env" not in s and "HL_API_CUZDAN_ANAHTARI" not in s and "CANLI_KIP" not in re.sub(r"(?m)^#.*$", "", s)   # HL anahtarı/gerçek kip yüklenmez
    assert "EnvironmentFile=-/etc/sg-sanal-telegram.env" in s                                         # Telegram isteğe bağlı ('-')
    assert re.search(r"^OnFailure=sg-sanal-alarm\.service$", s, re.M) and re.search(r"^RestartPreventExitStatus=3$", s, re.M) and re.search(r"^Restart=on-failure$", s, re.M)
    assert "ExecStartPre=/bin/bash /var/lib/sg-sanal/depo/deploy/sanal_baslat.sh" in s and "ExecStopPost=-/bin/bash" in s and "sanal_yayimla.sh" in s


def test_sanal_birimlerde_sir_yok_ve_cloudflare_yalniz_pano_biriminde():
    for ad in BIRIMLER:
        metin = (DEPLOY / ad).read_text(encoding="utf-8")
        assert not re.search(r"0x[0-9a-fA-F]{40}|BEGIN [A-Z ]*PRIVATE KEY|CLOUDFLARE_API_TOKEN=\S|TELEGRAM_BOT_TOKEN=\S", metin), ad
        if ad != "sg-sanal-pano.service":
            assert "sg-sanal-pano.env" not in metin, ad                                                # Cloudflare anahtarı yalnız pano birimine yüklenir
    assert "sg-sanal-telegram.env" not in (DEPLOY / "sg-sanal-yayim.service").read_text(encoding="utf-8")   # yayım birimi Telegram'ı görmez
    assert "OnUnitActiveSec=15min" in (DEPLOY / "sg-sanal-yayim.timer").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze yok")
def test_sanal_systemd_analyze_verify():
    r = subprocess.run(["systemd-analyze", "verify", *(str(DEPLOY / a) for a in BIRIMLER)], capture_output=True, text=True)
    assert not re.search(r"Unknown key|Unknown section|Invalid|Failed to parse", r.stdout + r.stderr), r.stdout + r.stderr


@pytest.mark.parametrize("betik", ["sanal_baslat.sh", "sanal_yayimla.sh", "sanal_pano_cf.sh", "sanal_mod.sh"])
def test_sanal_betikleri_bash_sozdizimi(betik):
    assert subprocess.run(["bash", "-n", str(DEPLOY / betik)], capture_output=True, text=True).returncode == 0


# ------------------------------------------------------------------------------------------------ geçiş anahtarı (Actions tarafı)
def _zamanlama(calisma, olay="schedule", **ek):
    cikti = calisma / "cikti.txt"
    cikti.write_text("", encoding="utf-8")
    env = _env(GITHUB_ACTIONS="true", GITHUB_EVENT_NAME=olay, ZAMANLAMA="7 */4 * * *", YEDEK_CRON="37 */4 * * *", VERI_DALI="canli-durum", GITHUB_OUTPUT=str(cikti), **ek)
    r = subprocess.run(["bash", str(ZAMANLAMA), "canli"], cwd=calisma, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return cikti.read_text(encoding="utf-8").strip(), r.stdout


@pytest.mark.parametrize("olay", ["schedule", "workflow_dispatch", "push"])
def test_sunucu_aktif_degiskeni_her_olayda_vardiyayi_atlatir(tmp_path, olay):
    # git deposu bile gerekmez: anahtar kontrolü ağ/git'ten ÖNCE çıkar (primer cron dahil: 7 */4 yedek DEĞİL)
    cikti, stdout = _zamanlama(tmp_path, olay, SUNUCU_AKTIF="evet")
    assert cikti == "atla=true" and "sunucu aktif" in stdout


def test_sunucu_aktif_dosyasi_de_atlatir_ve_hayir_atlatmaz(tmp_path):
    (tmp_path / "copytrade/canli").mkdir(parents=True)
    (tmp_path / "copytrade/canli/SUNUCU_AKTIF").write_text("", encoding="utf-8")
    assert _zamanlama(tmp_path, "schedule")[0] == "atla=true"                                          # dosya yeter
    (tmp_path / "copytrade/canli/SUNUCU_AKTIF").unlink()
    # değişken 'hayir' (geri alma) ve dosya yok: normal yol (primer cron: yedek değil -> çalışır, git'e hiç bakmaz)
    cikti, stdout = _zamanlama(tmp_path, "schedule", SUNUCU_AKTIF="hayir")
    assert cikti == "atla=false" and "yedek cron değil" in stdout


def test_is_akisi_degiskeni_yalniz_main_de_kontrol_adimina_verir():
    import yaml
    wf = yaml.safe_load((ROOT / ".github/workflows/canli_vardiya.yml").read_text(encoding="utf-8"))
    adim = next(a for a in wf["jobs"]["kontrol"]["steps"] if a.get("id") == "k")
    assert adim["env"]["SUNUCU_AKTIF"] == "${{ github.ref == 'refs/heads/main' && vars.SUNUCU_AKTIF || '' }}"
    assert wf["jobs"]["zincir"]["needs"] == "vardiya" and "skipped" in wf["jobs"]["zincir"]["if"]    # atlanan vardiya zinciri sürdürmez


# ------------------------------------------------------------------------------------------------ sanal_baslat.sh (geçiş kapısı + geri yükleme)
def _depo(tmp_path, kilit, donem="2026-01-01T00:00:00Z", durum_donem=None):
    """origin (bare, `canli-durum` dalı: durum/kilit.json + motor.json [+ donem.txt]) ve çalışma dizini (kurallar.yaml + DONEM)."""
    bare, tohum, calisma = tmp_path / "origin.git", tmp_path / "tohum", tmp_path / "depo"
    tmp_path.mkdir(parents=True, exist_ok=True)
    git(tmp_path, "init", "-q", "--bare", str(bare))
    tohum.mkdir()
    git(tohum, "init", "-q", "-b", "canli-durum")
    (tohum / "durum").mkdir()
    (tohum / "durum/kilit.json").write_text(json.dumps(kilit), encoding="utf-8")
    (tohum / "durum/motor.json").write_text(json.dumps({"kip": "sanal", "isaret": "actions"}), encoding="utf-8")
    (tohum / "durum/donem.txt").write_text(durum_donem or donem, encoding="utf-8")
    (tohum / "kayit").mkdir()
    (tohum / "kayit/2026-11-18.jsonl").write_text("{}\n", encoding="utf-8")
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "x")
    git(tohum, "remote", "add", "origin", str(bare))
    git(tohum, "push", "-q", "origin", "canli-durum")
    calisma.mkdir()
    git(calisma, "init", "-q")
    git(calisma, "remote", "add", "origin", str(bare))
    (calisma / "copytrade/canli").mkdir(parents=True)
    shutil.copy(ROOT / "copytrade/kurallar.yaml", calisma / "copytrade/kurallar.yaml")
    (calisma / "copytrade/canli/DONEM").write_text(donem + "\n", encoding="utf-8")
    return calisma


def _baslat(calisma, mod, **ek):
    dal = "canli-durum-sunucu" if mod == "deneme" else "canli-durum"
    return subprocess.run(["bash", str(DEPLOY / "sanal_baslat.sh")], env=_env(SANAL_DEPO=str(calisma), SUNUCU_MOD=mod, VERI_DALI=dal, **ek), capture_output=True, text=True)


def test_baslat_deneme_durumu_kopyalar_kilidi_siler_ve_yerel_durum_varsa_dokunmaz(tmp_path):
    taze = {"vardiya": "123", "nabiz_ms": int(time.time() * 1000), "birakildi": False}              # Actions vardiyası CANLI: deneme modunu engellememeli
    c = _depo(tmp_path, taze)
    r = _baslat(c, "deneme")
    assert r.returncode == 0, r.stderr
    assert (c / "durum/motor.json").exists() and (c / "kayit/2026-11-18.jsonl").exists() and not (c / "durum/kilit.json").exists()
    assert (c / "durum/donem.txt").read_text().strip() == "2026-01-01T00:00:00Z"
    (c / "durum/motor.json").write_text(json.dumps({"kip": "sanal", "isaret": "yerel"}), encoding="utf-8")
    r2 = _baslat(c, "deneme")                                                                         # yeniden başlatma: yerel durum asıl kaynak, geri yükleme YOK
    assert r2.returncode == 0 and "yerel durum var" in r2.stdout
    assert json.loads((c / "durum/motor.json").read_text())["isaret"] == "yerel"


def test_baslat_uretim_actions_canliysa_baslamaz_birakildiysa_baslar(tmp_path):
    taze = {"vardiya": "123", "nabiz_ms": int(time.time() * 1000) - 60_000, "birakildi": False}
    c = _depo(tmp_path / "a", taze)
    r = _baslat(c, "uretim", GECIS_BEKLE_SN="1", GECIS_ARALIK_SN="1")
    assert r.returncode == 75 and "BAŞLAMADI" in r.stderr and not (c / "durum/motor.json").exists()    # çift motor yok
    for kilit in ({"vardiya": "123", "nabiz_ms": int(time.time() * 1000) - 60_000, "birakildi": True},       # temiz bırakılmış
                  {"vardiya": "123", "nabiz_ms": int(time.time() * 1000) - 25 * 60_000, "birakildi": False}):  # bayat (> canli_kilit_dk = 20)
        c2 = _depo(tmp_path / f"b{kilit['birakildi']}", kilit)
        r2 = _baslat(c2, "uretim", GECIS_BEKLE_SN="1")
        assert r2.returncode == 0, r2.stderr
        assert (c2 / "durum/motor.json").exists() and (c2 / "durum/kilit.json").exists()               # üretim: kilit korunur (sahiplik devri motorun kuralıyla)


def test_baslat_yeni_donemde_eski_durum_yuklenmez_ve_mod_dal_cifti_zorunlu(tmp_path):
    c = _depo(tmp_path / "a", {"vardiya": "1", "nabiz_ms": 0, "birakildi": True}, donem="2026-01-02T00:00:00Z", durum_donem="2026-01-01T00:00:00Z")
    r = _baslat(c, "deneme")
    assert r.returncode == 0 and "YENİ DÖNEM" in r.stdout and not (c / "durum/motor.json").exists()
    assert (c / "durum/donem.txt").read_text().strip() == "2026-01-02T00:00:00Z"
    r = subprocess.run(["bash", str(DEPLOY / "sanal_baslat.sh")], env=_env(SANAL_DEPO=str(c), SUNUCU_MOD="deneme", VERI_DALI="canli-durum"), capture_output=True, text=True)
    assert r.returncode == 3 and "geçersiz mod/dal" in r.stderr                                       # deneme ASLA üretim dalına eşlenemez (kalıcı hata)
    r = subprocess.run(["bash", str(DEPLOY / "sanal_baslat.sh")], env=_env(SANAL_DEPO=str(c), SUNUCU_MOD="uretim", VERI_DALI="canli-durum-sunucu"), capture_output=True, text=True)
    assert r.returncode == 3


# ------------------------------------------------------------------------------------------------ sanal_yayimla.sh / sanal_pano_cf.sh
def test_yayimla_deneme_sunucu_dalina_yazar_uretim_dalina_yazamaz(tmp_path):
    bare, calisma = tmp_path / "origin.git", tmp_path / "calisma"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    calisma.mkdir()
    git(calisma, "init", "-q", "-b", "main")
    git(calisma, "remote", "add", "origin", str(bare))
    (calisma / "OKU.md").write_text("x")
    git(calisma, "add", "OKU.md")
    git(calisma, "commit", "-q", "-m", "x")
    os.symlink(ROOT / "copytrade", calisma / "copytrade")
    (calisma / "durum").mkdir()
    (calisma / "kayit").mkdir()
    for ad, v in {"hesap.json": {"poz": {}, "realize": {}, "ucret": {}, "slot_bas": {}}, "risk.json": {"gun_basi": 1000.0, "zirve": 1000.0}, "saha.json": {"uyeler": {}, "inen": {}}}.items():
        (calisma / "durum" / ad).write_text(json.dumps(v))
    (calisma / "durum/ozet.json").write_text(json.dumps({"kip": "sanal", "vardiya": "sunucu", "kasa_usd": 10000.0, "ozsermaye_usd": 10015.0, "getiri": 0.0015, "saha": 9, "saha_n": 11, "acik": []}))
    (calisma / "durum/kilit.json").write_text(json.dumps({"vardiya": "sunucu", "nabiz_ms": 1, "birakildi": False}))
    (calisma / "kayit/2026-11-19.jsonl").write_text("")
    ortak = dict(YAYIM_KILIT=str(tmp_path / "yayim.lock"), VARDIYA_ID="sunucu", PYTHON="python")
    r = subprocess.run(["bash", str(DEPLOY / "sanal_yayimla.sh")], cwd=calisma, env=_env(SUNUCU_MOD="deneme", VERI_DALI="canli-durum-sunucu", **ortak), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    dosyalar = subprocess.run(["git", "ls-tree", "-r", "--name-only", "canli-durum-sunucu"], cwd=bare, capture_output=True, text=True).stdout.split()
    assert {"durum/ozet.json", "durum/kilit.json", "pano/index.html", "pano/OZET.md", "kayit/2026-11-19.jsonl"} <= set(dosyalar)
    assert "canli-durum" not in subprocess.run(["git", "branch", "--list"], cwd=bare, capture_output=True, text=True).stdout.replace("canli-durum-sunucu", "")   # üretim dalı oluşmadı
    for mod, dal in (("deneme", "canli-durum"), ("uretim", "canli-durum-sunucu")):                       # çapraz çift: ret
        r = subprocess.run(["bash", str(DEPLOY / "sanal_yayimla.sh")], cwd=calisma, env=_env(SUNUCU_MOD=mod, VERI_DALI=dal, **ortak), capture_output=True, text=True)
        assert r.returncode == 1 and "Geçersiz mod/dal" in r.stderr


def test_pano_cf_mod_pano_adi_ciftini_zorlar_ve_secretsiz_yayimlamaz(tmp_path):
    (tmp_path / "pano").mkdir()
    (tmp_path / "pano/index.html").write_text("<html></html>")
    e = dict(SANAL_DEPO=str(tmp_path), PANO_SON=str(tmp_path / "son.sha"))
    r = subprocess.run(["bash", str(DEPLOY / "sanal_pano_cf.sh")], env=_env(SUNUCU_MOD="deneme", PANO_ISIM="sg-pano", **e), capture_output=True, text=True)
    assert r.returncode == 3 and "geçersiz mod/pano adı" in r.stderr                                    # deneme canlı panoya (sg-pano) yazamaz
    r = subprocess.run(["bash", str(DEPLOY / "sanal_pano_cf.sh")], env=_env(SUNUCU_MOD="deneme", PANO_ISIM="sg-pano-sunucu", **e), capture_output=True, text=True)
    assert r.returncode == 0 and "secret'ları yok" in r.stdout
    # sahte wrangler: içerik değişince bir kez yayımlar, aynı içerikte yeniden yayımlamaz
    sahte = tmp_path / "wrangler"
    sahte.write_text('#!/usr/bin/env bash\necho "$@" >> "$(dirname "$0")/cagrilar.txt"\n')
    sahte.chmod(0o755)
    ek = dict(e, WRANGLER=str(sahte), CLOUDFLARE_API_TOKEN="x", CLOUDFLARE_ACCOUNT_ID="y")
    for _ in range(2):
        r = subprocess.run(["bash", str(DEPLOY / "sanal_pano_cf.sh")], env=_env(SUNUCU_MOD="deneme", PANO_ISIM="sg-pano-sunucu", **ek), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    cagrilar = (tmp_path / "cagrilar.txt").read_text().splitlines()
    assert len(cagrilar) == 1 and "--name sg-pano-sunucu" in cagrilar[0] and "CLOUDFLARE" not in cagrilar[0]
