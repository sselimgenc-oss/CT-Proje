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
BIRIMLER = ("sg-sanal.service", "sg-sanal-yayim.service", "sg-sanal-yayim.timer", "sg-sanal-pano.service", "sg-sanal-pano.timer", "sg-sanal-alarm.service", "sg-sanal-kontrol.service", "sg-sanal-radar.service", "sg-sanal-radar.timer")


def _env(**ek):
    e = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "SUNUCU_AKTIF", "SUNUCU_MOD", "VERI_DALI", "KADRO_DALI", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")}
    e.update(ek)
    return e


def git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)


# ------------------------------------------------------------------------------------------------ birim dosyaları
def test_sanal_ana_birim_kip_kasa_ve_anahtarsiz():
    s = (DEPLOY / "sg-sanal.service").read_text(encoding="utf-8")
    assert "--kip sanal --sanal-kasa-usd 1000" in s and "--sure-sn" not in s                      # sürekli çalışır, vardiya süresi yok
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


@pytest.mark.parametrize("betik", ["sanal_baslat.sh", "sanal_yayimla.sh", "sanal_pano_cf.sh", "sanal_mod.sh", "sanal_radar.sh"])
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
    dal = "canli-durum"
    return subprocess.run(["bash", str(DEPLOY / "sanal_baslat.sh")], env=_env(SANAL_DEPO=str(calisma), SUNUCU_MOD=mod, VERI_DALI=dal, **ek), capture_output=True, text=True)


def test_baslat_uretim_durumu_kopyalar_ve_yerel_durum_varsa_dokunmaz(tmp_path):
    birakilmis = {"vardiya": "123", "nabiz_ms": int(time.time() * 1000), "birakildi": True}
    c = _depo(tmp_path, birakilmis)
    r = _baslat(c, "uretim", GECIS_BEKLE_SN="1")
    assert r.returncode == 0, r.stderr
    assert (c / "durum/motor.json").exists() and (c / "kayit/2026-11-18.jsonl").exists() and (c / "durum/kilit.json").exists()
    assert (c / "durum/donem.txt").read_text().strip() == "2026-01-01T00:00:00Z"
    (c / "durum/motor.json").write_text(json.dumps({"kip": "sanal", "isaret": "yerel"}), encoding="utf-8")
    r2 = _baslat(c, "uretim")                                                                         # yeniden başlatma: yerel durum asıl kaynak, geri yükleme YOK
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
    r = _baslat(c, "uretim", GECIS_BEKLE_SN="1")
    assert r.returncode == 0 and "YENİ DÖNEM" in r.stdout and not (c / "durum/motor.json").exists()
    assert (c / "durum/donem.txt").read_text().strip() == "2026-01-02T00:00:00Z"
    for mod, dal in (("deneme", "canli-durum"), ("deneme", "canli-durum-eski"), ("uretim", "canli-durum-eski")):   # deneme modu kaldırıldı (19.11): her çift kalıcı hata
        r = subprocess.run(["bash", str(DEPLOY / "sanal_baslat.sh")], env=_env(SANAL_DEPO=str(c), SUNUCU_MOD=mod, VERI_DALI=dal), capture_output=True, text=True)
        assert r.returncode == 3 and "geçersiz mod/dal" in r.stderr


# ------------------------------------------------------------------------------------------------ sanal_yayimla.sh / sanal_pano_cf.sh
def test_yayimla_uretim_canli_durum_dalina_yazar_deneme_reddedilir(tmp_path):
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
    r = subprocess.run(["bash", str(DEPLOY / "sanal_yayimla.sh")], cwd=calisma, env=_env(SUNUCU_MOD="uretim", VERI_DALI="canli-durum", **ortak), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    dosyalar = subprocess.run(["git", "ls-tree", "-r", "--name-only", "canli-durum"], cwd=bare, capture_output=True, text=True).stdout.split()
    assert {"durum/ozet.json", "durum/kilit.json", "pano/index.html", "pano/OZET.md", "kayit/2026-11-19.jsonl"} <= set(dosyalar)
    assert "canli-durum-eski" not in subprocess.run(["git", "branch", "--list"], cwd=bare, capture_output=True, text=True).stdout
    for mod, dal in (("deneme", "canli-durum"), ("deneme", "canli-durum-eski"), ("uretim", "canli-durum-eski")):   # deneme kaldırıldı / çapraz çift: ret
        r = subprocess.run(["bash", str(DEPLOY / "sanal_yayimla.sh")], cwd=calisma, env=_env(SUNUCU_MOD=mod, VERI_DALI=dal, **ortak), capture_output=True, text=True)
        assert r.returncode == 1 and "Geçersiz mod/dal" in r.stderr



def test_yayimla_kadro_dalini_her_yayimda_tazeler(tmp_path):
    """20.11: pano radarı `origin/radar`dan okuyor, yayım betiği o dalı çekmiyordu -> pano/sağlık 'radar gelmedi' (kadro bayat) gösterdi; motor HTTP ile tazeydi."""
    bare, calisma, baska = tmp_path / "origin.git", tmp_path / "calisma", tmp_path / "radar_yazar"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    calisma.mkdir()
    git(calisma, "init", "-q", "-b", "main")
    git(calisma, "remote", "add", "origin", str(bare))
    (calisma / "OKU.md").write_text("x")
    git(calisma, "add", "OKU.md")
    git(calisma, "commit", "-q", "-m", "x")
    git(calisma, "push", "-q", "origin", "main:radar")
    git(calisma, "fetch", "-q", "origin", "radar")                                     # yerel origin/radar = eski uç
    eski = subprocess.run(["git", "rev-parse", "origin/radar"], cwd=calisma, capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "clone", "-q", "-b", "radar", str(bare), str(baska)], check=True)
    (baska / "radar/son").mkdir(parents=True)
    (baska / "radar/son/kadro.json").write_text(json.dumps({"kosu_ms": 2, "satirlar": []}))
    for a in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "yeni kadro"], ["push", "-q", "origin", "radar"]):
        subprocess.run(["git", *a], cwd=baska, check=True)
    yeni = subprocess.run(["git", "rev-parse", "radar"], cwd=bare, capture_output=True, text=True).stdout.strip()
    os.symlink(ROOT / "copytrade", calisma / "copytrade")
    (calisma / "durum").mkdir()
    (calisma / "durum/kilit.json").write_text(json.dumps({"vardiya": "sunucu", "nabiz_ms": 1, "birakildi": False}))
    r = subprocess.run(["bash", str(DEPLOY / "sanal_yayimla.sh")], cwd=calisma, env=_env(SUNUCU_MOD="uretim", VERI_DALI="canli-durum", KADRO_DALI="radar", YAYIM_KILIT=str(tmp_path / "yayim.lock"), VARDIYA_ID="sunucu", PYTHON="python"), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    simdi = subprocess.run(["git", "rev-parse", "origin/radar"], cwd=calisma, capture_output=True, text=True).stdout.strip()
    assert simdi == yeni and simdi != eski

def test_pano_cf_mod_pano_adi_ciftini_zorlar_ve_secretsiz_yayimlamaz(tmp_path):
    (tmp_path / "pano").mkdir()
    (tmp_path / "pano/index.html").write_text("<html></html>")
    e = dict(SANAL_DEPO=str(tmp_path), PANO_SON=str(tmp_path / "son.sha"))
    r = subprocess.run(["bash", str(DEPLOY / "sanal_pano_cf.sh")], env=_env(SUNUCU_MOD="deneme", PANO_ISIM="sg-pano", **e), capture_output=True, text=True)
    assert r.returncode == 3 and "geçersiz mod/pano adı" in r.stderr                                    # deneme modu kaldırıldı (19.11)
    for mod, isim in (("deneme", "sg-pano-eski"), ("uretim", "sg-pano-eski")):
        r = subprocess.run(["bash", str(DEPLOY / "sanal_pano_cf.sh")], env=_env(SUNUCU_MOD=mod, PANO_ISIM=isim, **e), capture_output=True, text=True)
        assert r.returncode == 3 and "geçersiz mod/pano adı" in r.stderr
    r = subprocess.run(["bash", str(DEPLOY / "sanal_pano_cf.sh")], env=_env(SUNUCU_MOD="uretim", PANO_ISIM="sg-pano", **e), capture_output=True, text=True)
    assert r.returncode == 0 and "secret'ları yok" in r.stdout
    # sahte wrangler: içerik değişince bir kez yayımlar, aynı içerikte yeniden yayımlamaz
    sahte = tmp_path / "wrangler"
    sahte.write_text('#!/usr/bin/env bash\necho "$@" >> "$(dirname "$0")/cagrilar.txt"\n')
    sahte.chmod(0o755)
    ek = dict(e, WRANGLER=str(sahte), CLOUDFLARE_API_TOKEN="x", CLOUDFLARE_ACCOUNT_ID="y")
    for _ in range(2):
        r = subprocess.run(["bash", str(DEPLOY / "sanal_pano_cf.sh")], env=_env(SUNUCU_MOD="uretim", PANO_ISIM="sg-pano", **ek), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    cagrilar = (tmp_path / "cagrilar.txt").read_text().splitlines()
    assert len(cagrilar) == 1 and "--name sg-pano " in cagrilar[0] + " " and "CLOUDFLARE" not in cagrilar[0]


# ------------------------------------------------------------------------------------------------ otomatik güncelleme (sanal_guncelle.sh / sanal_geri_al.sh)
GUNCELLE = DEPLOY / "sanal_guncelle.sh"
GERI_AL = DEPLOY / "sanal_geri_al.sh"
BETIK_G = GUNCELLE.read_text(encoding="utf-8")


@pytest.mark.parametrize("betik", ["sanal_guncelle.sh", "sanal_geri_al.sh"])
def test_guncelle_betikleri_bash_sozdizimi(betik):
    assert subprocess.run(["bash", "-n", str(DEPLOY / betik)], capture_output=True, text=True).returncode == 0


def test_guncelle_birimleri_alanlar_ve_sir_yok():
    s = (DEPLOY / "sg-sanal-guncelle.service").read_text(encoding="utf-8")
    t = (DEPLOY / "sg-sanal-guncelle.timer").read_text(encoding="utf-8")
    assert re.search(r"^Type=oneshot$", s, re.M) and "ExecStart=/bin/bash /var/lib/sg-sanal/depo/deploy/sanal_guncelle.sh" in s
    assert re.findall(r"^OnCalendar=(.*)$", t, re.M) == ["*-*-* 07:30:00 UTC", "*-*-* 19:30:00 UTC"] and re.search(r"^RandomizedDelaySec=3min$", t, re.M)   # K-80: 10:30 ve 22:30 TSİ and re.search(r"^Persistent=true$", t, re.M) and "WantedBy=timers.target" in t
    for ad in ("sg-sanal-guncelle.service", "sg-sanal-guncelle.timer"):
        assert not re.search(r"TELEGRAM_BOT_TOKEN=\S|BEGIN [A-Z ]*PRIVATE KEY|0x[0-9a-fA-F]{40}", (DEPLOY / ad).read_text(encoding="utf-8")), ad


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze yok")
def test_guncelle_birimleri_systemd_analyze_verify():
    r = subprocess.run(["systemd-analyze", "verify", str(DEPLOY / "sg-sanal-guncelle.service"), str(DEPLOY / "sg-sanal-guncelle.timer")], capture_output=True, text=True)
    assert not re.search(r"Unknown key|Unknown section|Invalid|Failed to parse", r.stdout + r.stderr), r.stdout + r.stderr


def test_guncelle_statik_guvenceler():
    kod = re.sub(r"(?m)^\s*#.*$", "", BETIK_G)
    assert "--ff-only" in kod and "merge-base --is-ancestor" in kod                                  # yalnız fast-forward
    assert "check-runs" in kod and 'ZORUNLU_CI="test canli_sdk"' in kod and "completed" in kod and "success" in kod   # CI kapısı
    assert "reset -q --hard" in kod and "geri_al" in kod and "birimleri_geri" in kod and "pip_kur" in kod      # geri alma yolu
    assert "--require-hashes -r" in kod and "requirements-canli.lock" in kod
    assert '"tamam": true' in kod and "sg-sanal-kontrol" in kod and "flock" in kod
    assert "durum kayit pano" in kod                                                                  # yerel durum koruması
    assert "[CT] $2" in kod and "bildir_rutin" not in kod and "WARN" in kod and "[CT] $1" not in kod and "Sunucu güncellendi" not in kod
    # token: yalnız stdin'den curl --config'e; echo/log yok, set -x yok
    assert "--config -" in kod and not re.search(r"set -[a-z]*x", kod)
    assert not re.search(r"(echo|log)\b[^\n]*\$\{?tok\b", kod)
    assert "git push" not in kod and "git pull" not in kod
    g = GERI_AL.read_text(encoding="utf-8")
    assert "evet" in g and "SANAL_HEDEF_SHA" in g and "dondur" in g


class _Sunucu:
    pass


@pytest.fixture
def sunucu(tmp_path):
    """Sahte sunucu: bare origin + depo klonu (deploy/ birimi + kilit dosyası), sahte systemctl/journalctl/curl, sırsız ortam."""
    bare, tohum, depo = tmp_path / "origin.git", tmp_path / "tohum", tmp_path / "depo"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    tohum.mkdir()
    git(tohum, "init", "-q", "-b", "main")
    (tohum / "deploy").mkdir()
    (tohum / "deploy/sg-sanal.service").write_text("[Service]\n# v1\n")
    (tohum / "requirements-canli.lock").write_text("a==1\n")
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "v1")
    git(tohum, "remote", "add", "origin", str(bare))
    git(tohum, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", str(bare), str(depo)], check=True)
    v1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=depo, capture_output=True, text=True).stdout.strip()
    bin_, birim, durum, log = tmp_path / "bin", tmp_path / "birim", tmp_path / "durum", tmp_path / "cagri.log"
    for d in (bin_, birim):
        d.mkdir()
    (birim / "sg-sanal.service").write_text("[Service]\n# v1\n")
    (bin_ / "systemctl").write_text(
        '#!/usr/bin/env bash\necho "systemctl $*" >> "$CAGRI_LOG"\n'
        'case "$1" in is-active) exit 0;; show) case "$*" in *Result*) echo "${SHOW_RESULT:-success}";; *) echo 0;; esac; exit 0;; esac\n'
        'if [ "$1" = start ] && [ "$2" = sg-sanal-kontrol ]; then exit "${KONTROL_RC:-0}"; fi\n'
        'if [ "$1" = start ] && [ "$2" = sg-sanal ] && [ -z "${MOTOR_YAZMAZ:-}" ]; then printf \'{"yazildi_ms": %s}\' "$(( $(date +%s) * 1000 ))" > "$SANAL_DEPO/durum/ozet.json"; fi\n'
        'case "$1:$2" in is-enabled:*) [ -n "${ETKIN_DEGIL:-}" ] && case "$*" in *"$ETKIN_DEGIL"*) exit 1;; esac;; esac\nexit 0\n')
    (bin_ / "journalctl").write_text('#!/usr/bin/env bash\ncase " $* " in *" -u sg-sanal "*) [ -n "${JOURNAL_SANAL:-}" ] && printf "%b" "$JOURNAL_SANAL"; exit 0;; esac\nif [ "${KONTROL_TAMAM:-1}" = 1 ]; then echo \'  "tamam": true,\'; else echo \'  "tamam": false,\'; fi\n')
    (bin_ / "curl").write_text(
        '#!/usr/bin/env bash\necho "curl $*" >> "$CAGRI_LOG"\n'
        'if [ "$1" != "-sSL" ]; then cat >/dev/null; for a in "$@"; do case "$a" in text=*) echo "TG:$a" >> "$CAGRI_LOG";; disable_notification=*) echo "NS:$a" >> "$CAGRI_LOG";; esac; done; exit 0; fi\n'
        'sha="$(printf "%s" "$*" | sed -nE "s#.*/commits/([0-9a-f]+)/check-runs.*#\\1#p")"; if [ -n "$sha" ] && [ -f "$CI_JSON.$sha" ]; then cat "$CI_JSON.$sha"; else cat "$CI_JSON"; fi\n')
    for f in bin_.iterdir():
        f.chmod(0o755)
    tg = tmp_path / "tg.env"
    tg.write_text("TELEGRAM_BOT_TOKEN=SIRTOKEN123\nTELEGRAM_CHAT_ID=42\n")
    ci_json = tmp_path / "ci.json"
    ortak = _env(PATH=f"{bin_}:{os.environ['PATH']}", SANAL_DEPO=str(depo), SANAL_SERIT=str(tmp_path / "serit"), SANAL_DURUM_DIZIN=str(durum), SANAL_BIRIM_DIZIN=str(birim),
                 SANAL_KULLANICI="", SANAL_TG_ENV=str(tg), SANAL_GUNCELLE_KILIT=str(tmp_path / "k.lock"), GUNCELLE_REPO="o/r", GUNCELLE_BEKLE_SN="0", CI_JSON=str(ci_json), CAGRI_LOG=str(log), SANAL_SAGLIK_JSON=str(tmp_path / "saglik.json"), SANAL_DOGRULA_SN="0", SANAL_OZ_DENETIM_SN="0", ALARM_DOGRULA_SN="0")
    s = _Sunucu()

    def ci(*runlar):
        ci_json.write_text(json.dumps({"check_runs": [{"name": a, "status": st, "conclusion": c} for a, st, c in runlar]}))

    def yeni_commit(icerik="v2", lock=None):
        git(tohum, "pull", "-q", "origin", "main")
        (tohum / "deploy/sg-sanal.service").write_text(f"[Service]\n# {icerik}\n")
        if lock:
            (tohum / "requirements-canli.lock").write_text(lock)
        git(tohum, "add", "-A")
        git(tohum, "commit", "-q", "-m", f"degisiklik {icerik}")
        git(tohum, "push", "-q", "origin", "main")
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=tohum, capture_output=True, text=True).stdout.strip()

    s.depo, s.birim, s.durum, s.log, s.v1, s.ci, s.yeni_commit, s.ortak = depo, birim, durum, log, v1, ci, yeni_commit, ortak
    s.calistir = lambda **ek: subprocess.run(["bash", str(GUNCELLE)], env={**ortak, **ek}, capture_output=True, text=True)
    s.head = lambda: subprocess.run(["git", "rev-parse", "HEAD"], cwd=depo, capture_output=True, text=True).stdout.strip()
    log.write_text("")
    (depo / "durum").mkdir()
    (depo / "durum/motor.json").write_text("{}")                                                      # yerel durum (izlenmez)
    return s


YESIL = (("test", "completed", "success"), ("canli_sdk", "completed", "success"))


def test_guncelle_ayni_sha_ve_kirmizi_ci_hicbir_sey_yapmaz(sunucu):
    r = sunucu.calistir()
    assert r.returncode == 0 and sunucu.head() == sunucu.v1 and "systemctl stop" not in sunucu.log.read_text()
    sunucu.yeni_commit()
    for runlar in ((("test", "completed", "success"),), (*YESIL, ("x", "in_progress", None)), (("test", "completed", "success"), ("canli_sdk", "completed", "failure")), ()):
        sunucu.ci(*runlar)
        r = sunucu.calistir()
        assert r.returncode == 0 and sunucu.head() == sunucu.v1 and "systemctl stop" not in sunucu.log.read_text(), r.stdout
    assert "CI yeşil değil" in r.stdout


def test_guncelle_birlestirme_commitinde_zamanli_kontrol_varsa_pr_ucu_degerlendirilir(sunucu, tmp_path):
    """20.11 olayı: zamanlanmış iş akışları main ucuna (birleştirme commit'i) 'radar'/'kontrol' ekleyince zorunlu test/canli_sdk eksik görünüyordu → güncelleme hiç uygulanmadı. Artık 2. ebeveyn (PR ucu) değerlendirilir."""
    tohum = sunucu.depo.parent / "tohum"
    git(tohum, "pull", "-q", "origin", "main")
    git(tohum, "checkout", "-q", "-b", "pr")
    (tohum / "deploy/sg-sanal.service").write_text("[Service]\n# v3\n")
    git(tohum, "commit", "-qam", "pr")
    pr_ucu = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tohum, capture_output=True, text=True).stdout.strip()
    git(tohum, "checkout", "-q", "main")
    git(tohum, "merge", "-q", "--no-ff", "-m", "Merge pr", "pr")
    git(tohum, "push", "-q", "origin", "main")
    birlesme = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tohum, capture_output=True, text=True).stdout.strip()
    ci = tmp_path / "ci.json"
    Path(f"{ci}.{birlesme}").write_text(json.dumps({"check_runs": [{"name": "radar", "status": "completed", "conclusion": "skipped"}, {"name": "kontrol", "status": "completed", "conclusion": "success"}]}))
    Path(f"{ci}.{pr_ucu}").write_text(json.dumps({"check_runs": [{"name": a, "status": st, "conclusion": c} for a, st, c in YESIL]}))
    sunucu.ci()
    r = sunucu.calistir()
    assert r.returncode == 0 and sunucu.head() == birlesme, r.stdout + r.stderr
    assert "PR ucu" in r.stdout


def test_guncelle_basari_yolu_ff_birim_telegram_ve_yerel_durum_korunur(sunucu):
    yeni = sunucu.yeni_commit("v2")
    sunucu.ci(*YESIL)
    r = sunucu.calistir()
    assert r.returncode == 0, r.stdout + r.stderr
    assert sunucu.head() == yeni and "# v2" in (sunucu.birim / "sg-sanal.service").read_text()      # birim değişti -> kopyalandı
    log = sunucu.log.read_text()
    assert "daemon-reload" in log and log.index("stop sg-sanal") < log.index("start sg-sanal-kontrol") < log.rindex("start sg-sanal")
    assert f"güncellendi: {sunucu.v1[:7]}→{yeni[:7]} (degisiklik v2)" in r.stdout        # başarılı güncelleme Telegram'a HİÇ mesaj atmaz (yalnız günlük)
    assert "Sunucu güncellendi" not in log and "TG:" not in log
    assert "SIRTOKEN123" not in r.stdout + r.stderr + log                                             # token argv'ye/günlüğe girmez
    assert (sunucu.depo / "durum/motor.json").exists()                                                # yerel durum dokunulmadı
    assert sunucu.calistir().returncode == 0 and (sunucu.durum / "uygulanan_sha").read_text().strip() == yeni


def test_guncelle_duman_testi_basarisizsa_geri_alir_ve_crit_bildirir(sunucu):
    sunucu.yeni_commit("v2")
    sunucu.ci(*YESIL)
    r = sunucu.calistir(KONTROL_TAMAM="0")
    assert r.returncode == 1, r.stdout + r.stderr
    assert sunucu.head() == sunucu.v1 and "# v1" in (sunucu.birim / "sg-sanal.service").read_text()   # git + birim geri
    log = sunucu.log.read_text()
    assert "[CT] ⚠️ Bot güncellemesi başarısız, eski sürümle devam ediyor" in log and log.count("TG:") == 1 and "CRIT" not in log and "NS:disable_notification=false" in log and (sunucu.depo / "durum/motor.json").exists()
    assert "start sg-sanal\n" in log                                                                  # servisler yeniden başlatıldı
    assert "SIRTOKEN123" not in r.stdout + r.stderr + log
    r2 = sunucu.calistir()                                                                           # aynı bozuk commit saatlik döngüde tekrar denenmez
    assert r2.returncode == 0 and "daha önce başarısız" in r2.stdout and sunucu.head() == sunucu.v1


def test_guncelle_ff_olmayan_ve_dondurulmus_reddedilir(sunucu):
    sunucu.yeni_commit("v2")
    sunucu.ci(*YESIL)
    sunucu.durum.mkdir(exist_ok=True)
    (sunucu.durum / "dondur").write_text("abc\n")
    r = sunucu.calistir()
    assert r.returncode == 0 and "DONDURULMUŞ" in r.stdout and sunucu.head() == sunucu.v1
    (sunucu.durum / "dondur").unlink()
    git(sunucu.depo, "commit", "-q", "--allow-empty", "-m", "yerel sapma")                           # HEAD origin'den ayrıldı
    r = sunucu.calistir()
    assert r.returncode == 0 and "fast-forward" in r.stdout and "systemctl stop" not in sunucu.log.read_text()


def test_geri_al_onay_ister_ve_onayla_dondurur(sunucu):
    yeni = sunucu.yeni_commit("v2")
    git(sunucu.depo, "pull", "-q", "--ff-only")
    r = subprocess.run(["bash", str(GERI_AL), sunucu.v1[:7]], env=sunucu.ortak, input="hayir\n", capture_output=True, text=True)
    assert r.returncode == 1 and "İptal" in r.stdout and sunucu.head() == yeni
    r = subprocess.run(["bash", str(GERI_AL), "zzz"], env=sunucu.ortak, input="evet\n", capture_output=True, text=True)
    assert r.returncode == 2
    r = subprocess.run(["bash", str(GERI_AL), sunucu.v1[:7]], env=sunucu.ortak, input="evet\n", capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sunucu.head() == sunucu.v1 and (sunucu.durum / "dondur").exists() and "TG:text=[CT] ⚠️ Bot önceki sürüme döndürüldü" in sunucu.log.read_text() and sunucu.log.read_text().count("TG:") == 1 and "Sunucu güncellendi" not in sunucu.log.read_text()


# ------------------------------------------------------------------------------------------------ kaynak sınırları ve haftalık bakım
def _ayar(birim: str) -> dict:
    s = (DEPLOY / birim).read_text(encoding="utf-8")
    return dict(re.findall(r"^(\w+)=(\S+)$", re.sub(r"(?m)^#.*$", "", s), re.M))



@pytest.mark.parametrize("birim,beklenen", [
    ("sg-sanal.service", {"MemoryHigh": "225M", "MemoryMax": "300M"}),
    ("sg-sanal-pano.service", {"MemoryMax": "400M", "Nice": "10", "CPUQuota": "50%"}),
    ("sg-sanal-yayim.service", {"MemoryMax": "300M", "Nice": "5"}),
    ("sg-sanal-kontrol.service", {"MemoryMax": "400M"}),
    ("sg-sanal-guncelle.service", {"MemoryMax": "400M"}),
    ("sg-sanal-radar.service", {"MemoryHigh": "550M", "MemoryMax": "700M", "Nice": "15", "CPUQuota": "60%", "IOSchedulingClass": "idle"}),
])
def test_sanal_birimlerinde_kaynak_siniri(birim, beklenen):
    a = _ayar(birim)
    for k, v in beklenen.items():
        assert a.get(k) == v, (birim, k)


def test_canli_ve_dinleyici_birimlerine_sinir_eklenmedi():
    for ad in ("sg-canli.service", "sg-canli-yayim.service", "sg-canli-kontrol.service", "sg-canli-alarm.service", "sg-dinleyici.service"):
        assert not re.search(r"(?m)^(MemoryHigh|MemoryMax|CPUQuota)=", (DEPLOY / ad).read_text(encoding="utf-8")), ad


def test_guncelle_haftalik_git_bakimi():
    s = GUNCELLE.read_text(encoding="utf-8")
    assert "gc --auto" in s and "worktree prune" in s and "bakim_sn" in s and "604800" in s


# ------------------------------------------------------------------------------------------------ sunucu dayanıklılık alarmı (alarm_kontrol)
def _yeniden(n):
    return "Scheduled restart job, restart counter is at 1.\n" * n


def _tg(sunucu):
    satirlar, cikti = sunucu.log.read_text().splitlines(), []
    for i, s in enumerate(satirlar):                                                                  # sahte curl mesajı ilk satıra keser: sonraki satırlar (başka çağrı başlayana dek) metindir
        if s.startswith("TG:"):
            j = i + 1
            while j < len(satirlar) and not satirlar[j].startswith(("curl ", "systemctl ", "journalctl ", "NS:", "TG:", "git ")):
                s += " " + satirlar[j]
                j += 1
            cikti.append(s)
    return cikti


def test_alarm_yeniden_baslama_siniri_tek_crit_ve_6_saat_siniri(sunucu):
    r = sunucu.calistir(JOURNAL_SANAL=_yeniden(2))                                                  # sınır 2: tam 2 alarm DEĞİL
    assert r.returncode == 0 and _tg(sunucu) == []
    r = sunucu.calistir(JOURNAL_SANAL=_yeniden(4))
    assert r.returncode == 0, r.stdout
    tg = _tg(sunucu)
    assert len(tg) == 1 and "[CT] 🔴 Bot durdu" in tg[0] and "CRIT" not in tg[0] and "Açık pozisyon: " in tg[0] and "Stop: " in tg[0] and "4 kez yeniden başladı (sınır 2)" in tg[0] and "bellek taşması olmadı" in tg[0] and "Senden" not in tg[0].split("\n")[0] and "Sorun sürerse bana haber ver" in tg[0] and "journalctl" not in tg[0]
    assert "NS:disable_notification=false" in sunucu.log.read_text()                                  # CRIT sesli
    assert "SIRTOKEN123" not in sunucu.log.read_text()
    sunucu.calistir(JOURNAL_SANAL=_yeniden(5))                                                      # 6 saat dolmadan tekrar YOK
    assert len(_tg(sunucu)) == 1
    (sunucu.durum / "alarm_yeniden").write_text(str(int(time.time()) - 7 * 3600) + "\n")           # 6 saat geçti
    sunucu.calistir(JOURNAL_SANAL=_yeniden(5))
    assert len(_tg(sunucu)) == 2
    json_ = json.loads((sunucu.ortak["SANAL_SAGLIK_JSON"] and Path(sunucu.ortak["SANAL_SAGLIK_JSON"])).read_text())
    assert json_["yeniden_baslama_1s"] == 5 and json_["oom_son"] is False


def test_alarm_duzeldi_tek_info_ve_durum_temizlenir(sunucu):
    sunucu.calistir(JOURNAL_SANAL=_yeniden(3))
    assert len(_tg(sunucu)) == 1 and (sunucu.durum / "alarm_yeniden").exists()
    sunucu.calistir(JOURNAL_SANAL=_yeniden(1))
    tg = _tg(sunucu)
    assert len(tg) == 2 and "[CT] ✅ Düzeldi" in tg[1] and "INFO" not in tg[1] and "NS:disable_notification=true" in sunucu.log.read_text() and not (sunucu.durum / "alarm_yeniden").exists()
    sunucu.calistir()                                                                               # tekrar düzeldi mesajı YOK
    assert len(_tg(sunucu)) == 2


def test_alarm_oom_crit_gunlukten_ve_systemctl_sonucundan(sunucu):
    sunucu.calistir(JOURNAL_SANAL="sg-sanal.service: Failed with result 'oom-kill'.\n")
    tg = _tg(sunucu)
    assert len(tg) == 1 and "[CT] 🔴 Bot durdu" in tg[0] and "bellek tavanı" in tg[0]
    sunucu.calistir(JOURNAL_SANAL="x\n")                                                           # düzeldi
    assert len(_tg(sunucu)) == 2
    sunucu.calistir(SHOW_RESULT="oom-kill")                                                         # systemctl Result=oom-kill
    assert len(_tg(sunucu)) == 3 and "bellek tavanı" in _tg(sunucu)[2]


def test_alarm_commit_olmasa_da_calisir_donmusken_de_ve_guncellemeyi_bozmaz(sunucu):
    (sunucu.durum).mkdir(exist_ok=True)
    (sunucu.durum / "dondur").write_text("x\n")                                                     # donmuş: erken çıkış, alarm yine çalışır
    r = sunucu.calistir(JOURNAL_SANAL=_yeniden(9))
    assert r.returncode == 0 and len(_tg(sunucu)) == 1 and "systemctl stop" not in sunucu.log.read_text()
    (sunucu.durum / "dondur").unlink()
    yeni = sunucu.yeni_commit("v2")
    sunucu.ci(*YESIL)
    r = sunucu.calistir(JOURNAL_SANAL=_yeniden(9), SANAL_SAGLIK_JSON="/yok/dizin/x.json")           # JSON yazılamasa da güncelleme sürer
    assert r.returncode == 0 and sunucu.head() == yeni


def test_alarm_betik_statik():
    s = GUNCELLE.read_text(encoding="utf-8")
    assert s.index("\nalarm_kontrol ||") < s.index('-s "$DURUM/dondur"') and "21600" in s and "oom-kill" in s


def test_alarm_bot_durdu_acik_pozisyon_sayisi_defterden(sunucu):
    (sunucu.depo / "durum").mkdir(exist_ok=True)
    (sunucu.depo / "durum" / "hesap.json").write_text(json.dumps({"poz": {"0xa": {"BTC": {}, "ETH": {}}}}))
    sunucu.calistir(JOURNAL_SANAL=_yeniden(4))
    tg = _tg(sunucu)
    assert len(tg) == 1 and "Açık pozisyon: 2 · Stop: bot kapalıyken yazılım stopu çalışmıyor" in tg[0]


def test_guncelleme_sayaci_saglik_jsona_yazilir_gunluk_rapor_icin(sunucu):
    sunucu.yeni_commit("v2")
    sunucu.ci(*YESIL)
    assert sunucu.calistir().returncode == 0
    assert (sunucu.durum / "guncelleme_gunlugu").read_text().split() == [time.strftime("%Y-%m-%d", time.gmtime())]
    sunucu.calistir()                                                                               # sonraki çalışma sağlık JSON'unu yazar
    assert json.loads(Path(sunucu.ortak["SANAL_SAGLIK_JSON"]).read_text())["guncelleme_bugun"] == 1


# ------------------------------------------------------------------------------------------------ sunucu radarı (K-78): sg-sanal-radar.service/.timer + sanal_radar.sh
RADAR_BETIK = DEPLOY / "sanal_radar.sh"


def test_radar_birimleri_saat_oncelik_zaman_asimi_ve_sirsiz():
    t = (DEPLOY / "sg-sanal-radar.timer").read_text(encoding="utf-8")
    s = (DEPLOY / "sg-sanal-radar.service").read_text(encoding="utf-8")
    assert re.search(r"^OnCalendar=\*-\*-\* 00:37:00 UTC$", t, re.M) and re.search(r"^Persistent=true$", t, re.M) and "WantedBy=timers.target" in t   # 00:37 UTC = 03:37 TSİ
    assert 0 < int(re.search(r"^RandomizedDelaySec=(\d+)$", t, re.M).group(1)) <= 300                # küçük rastgele gecikme
    assert re.search(r"^Type=oneshot$", s, re.M) and re.search(r"^User=sgsanal$", s, re.M) and "ExecStart=/bin/bash /var/lib/sg-sanal/depo/deploy/sanal_radar.sh" in s
    assert re.search(r"^TimeoutStartSec=\S+$", s, re.M) and re.search(r"^OOMPolicy=continue$", s, re.M)
    assert "EnvironmentFile=-/etc/sg-sanal-telegram.env" in s and "sg-sanal-pano.env" not in s         # Telegram isteğe bağlı; Cloudflare anahtarı yok
    assert "/etc/sg-sanal-mod.env" not in s                                                           # mod dosyasındaki VERI_DALI (canli-durum) radar dalını ezmesin
    assert "GIT_SSH_COMMAND=ssh -i /var/lib/sg-sanal/.ssh/id_ed25519" in s                           # push kimliği = SSH deploy anahtarı (sır repoda değil)
    assert "HL_API_CUZDAN_ANAHTARI" not in s and "CANLI_KIP" not in re.sub(r"(?m)^#.*$", "", s)


def test_radar_betigi_statik_guvenceler():
    kod = re.sub(r"(?m)^\s*#.*$", "", RADAR_BETIK.read_text(encoding="utf-8"))
    assert "flock -n 9" in kod and "timeout --kill-after" in kod and "git worktree add" in kod and 'cd "$work"' in kod   # tek koşu, zaman aşımı, ayrı worktree
    assert "git push" not in kod and "git checkout" not in kod and "git reset" not in kod and "git merge" not in kod    # motorun deposuna dokunmaz (yayım radar_yayimla.sh'de, geçici worktree'de)
    assert "--config -" in kod and not re.search(r"set -[a-z]*x", kod) and not re.search(r"(echo|log)\b[^\n]*\$\{?tok\b", kod)   # token yalnız stdin'den
    assert "disable_notification" not in kod and kod.count("bildir ") <= 3                            # başarıda bildirim yok; yalnız başarısızlık yolu


def test_radar_betigi_adimlari_radar_yml_ile_ayni_sirada():
    import yaml
    wf = yaml.safe_load((ROOT / ".github/workflows/radar.yml").read_text(encoding="utf-8"))
    yml = [m for a in wf["jobs"]["radar"]["steps"] for m in re.findall(r"-m (copytrade\.\w+)", a.get("run", ""))]
    sh = re.findall(r"-m (copytrade\.\w+)", RADAR_BETIK.read_text(encoding="utf-8"))
    assert yml == sh and len(sh) == 2                                                                 # K-85: tarama, kadro (isabet/pbo/rastgele/holdout kaldırıldı)
    assert "radar_yayimla.sh" in RADAR_BETIK.read_text(encoding="utf-8") and "schedule" not in (wf.get("on") or wf.get(True))


def _radar_ortam(tmp_path, token=True):
    """Gerçek git: bare origin + depo klonu (main; radar_yayimla.sh, kilit dosyası, HOLDOUT yok), sahte python (adımları günlüğe yazar) ve sahte curl."""
    bare, tohum, depo, bin_ = tmp_path / "origin.git", tmp_path / "tohum", tmp_path / "depo", tmp_path / "bin"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    tohum.mkdir()
    git(tohum, "init", "-q", "-b", "main")
    (tohum / ".github/scripts").mkdir(parents=True)
    shutil.copy(ROOT / ".github/scripts/radar_yayimla.sh", tohum / ".github/scripts/radar_yayimla.sh")
    (tohum / "requirements-radar.lock").write_text("x==1\n")
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "v1")
    git(tohum, "remote", "add", "origin", str(bare))
    git(tohum, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", str(bare), str(depo)], check=True)
    bin_.mkdir()
    log = tmp_path / "cagri.log"
    log.write_text("")
    (bin_ / "python").write_text(
        '#!/usr/bin/env bash\necho "py $*" >> "$CAGRI_LOG"\nmod="$3"\n'
        '[ "${FAKE_BASARISIZ:-}" = "$mod" ] && exit 2\n'
        'case "$mod" in\n'
        '  copytrade.radar_tarama) d="radar/$(date -u +%F)"; mkdir -p "$d"; echo \'{"kosu_ms": 1}\' > "$d/havuz.json";;\n'
        '  copytrade.radar_kadro) echo \'{"satirlar": []}\' > "$(dirname "$5")/kadro.json";;\n'
        'esac\nexit 0\n')
    (bin_ / "curl").write_text('#!/usr/bin/env bash\necho "curl" >> "$CAGRI_LOG"\ncat >/dev/null; for a in "$@"; do case "$a" in text=*) echo "TG:$a" >> "$CAGRI_LOG";; esac; done; exit 0\n')
    for f in bin_.iterdir():
        f.chmod(0o755)
    tg = tmp_path / "tg.env"
    if token:
        tg.write_text("TELEGRAM_BOT_TOKEN=SIRTOKEN123\nTELEGRAM_CHAT_ID=42\n")
    env = _env(PATH=f"{bin_}:{os.environ['PATH']}", SANAL_DEPO=str(depo), RADAR_PYTHON=str(bin_ / "python"), RADAR_KILIT=str(tmp_path / "radar.lock"), RADAR_TG_ENV=str(tg), CAGRI_LOG=str(log))
    return bare, depo, log, env


def _radar_kos(env, **ek):
    return subprocess.run(["bash", str(RADAR_BETIK)], env={**env, **ek}, capture_output=True, text=True)


def _dal_dosyalari(bare, dal="radar"):
    return set(subprocess.run(["git", "ls-tree", "-r", "--name-only", dal], cwd=bare, capture_output=True, text=True).stdout.split())


def test_radar_betigi_ayri_worktreede_radar_dalina_yazar_motor_dizinine_dokunmaz_ve_mesaj_atmaz(tmp_path):
    bare, depo, log, env = _radar_ortam(tmp_path)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=depo, capture_output=True, text=True).stdout.strip()
    r = _radar_kos(env)
    assert r.returncode == 0, r.stdout + r.stderr
    gun = time.strftime("%Y-%m-%d", time.gmtime())
    assert {f"radar/{gun}/havuz.json", f"radar/{gun}/kadro.json", "radar/son/kadro.json", f"radar/{gun}/kadro_ilk.json"} <= _dal_dosyalari(bare)
    adimlar = re.findall(r"-m (copytrade\.\w+)", log.read_text())
    assert adimlar == ["copytrade.radar_tarama", "copytrade.radar_kadro"]
    assert "curl" not in log.read_text() and "TG:" not in log.read_text()                              # başarıda Telegram mesajı YOK
    assert not (depo / "radar").exists() and not (depo / "durum").exists()                            # motorun çalışma dizininde iz yok
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=depo, capture_output=True, text=True).stdout.strip() == head
    assert subprocess.run(["git", "status", "--porcelain"], cwd=depo, capture_output=True, text=True).stdout.strip() == ""
    assert len(subprocess.run(["git", "worktree", "list"], cwd=depo, capture_output=True, text=True).stdout.strip().splitlines()) == 1   # geçici worktree temizlendi
    assert "sg-sanal-sunucu" in subprocess.run(["git", "log", "-1", "--format=%an", "radar"], cwd=bare, capture_output=True, text=True).stdout
    n = log.read_text().count("copytrade.radar_tarama")
    r2 = _radar_kos(env)                                                                             # aynı gün ikinci tetik (Persistent/çift): iş yapılmaz
    assert r2.returncode == 0 and "zaten var" in r2.stdout and log.read_text().count("copytrade.radar_tarama") == n
    r3 = _radar_kos(env, RADAR_ZORLA="1")
    assert r3.returncode == 0 and log.read_text().count("copytrade.radar_tarama") == n + 1


def test_radar_betigi_kilit_doluysa_baslamaz(tmp_path):
    bare, depo, log, env = _radar_ortam(tmp_path)
    tutan = subprocess.Popen(["flock", env["RADAR_KILIT"], "sleep", "20"])
    try:
        time.sleep(0.5)
        r = _radar_kos(env)
        assert r.returncode == 0 and "sürüyor" in r.stdout and "copytrade.radar_tarama" not in log.read_text()
        assert "radar" not in subprocess.run(["git", "branch", "--list"], cwd=bare, capture_output=True, text=True).stdout
    finally:
        tutan.kill()
        tutan.wait()


@pytest.mark.parametrize("adim", ["copytrade.radar_tarama", "copytrade.radar_kadro"])
def test_radar_betigi_basarisizlikta_tek_uyari_yayimlamaz_ve_sonrakini_kosmaz(tmp_path, adim):
    bare, depo, log, env = _radar_ortam(tmp_path)
    r = _radar_kos(env, FAKE_BASARISIZ=adim)
    assert r.returncode == 1, r.stdout + r.stderr
    metin = log.read_text()
    assert metin.count("TG:") == 1 and "TG:text=[CT] ⚠️ Radar sunucuda çalışmadı" in metin             # tek ⚠️ satır
    assert "SIRTOKEN123" not in r.stdout + r.stderr + metin                                           # token argv'ye/günlüğe girmez
    assert "radar" not in subprocess.run(["git", "branch", "--list"], cwd=bare, capture_output=True, text=True).stdout   # kadro yayımlanmadı (son/ güncellenmez)
    sira = ["copytrade.radar_tarama", "copytrade.radar_kadro"]
    assert (len(sira) == sira.index(adim) + 1 or sira[sira.index(adim) + 1] not in metin) and not (depo / "radar").exists()


def test_radar_betigi_telegram_anahtari_yoksa_sessiz_atlar(tmp_path):
    bare, depo, log, env = _radar_ortam(tmp_path, token=False)
    r = _radar_kos(env, FAKE_BASARISIZ="copytrade.radar_tarama")
    assert r.returncode == 1 and "bildirim atlandı" in r.stdout and "TG:" not in log.read_text()


def test_radar_veri_dali_yalniz_radar_ya_da_deneme(tmp_path):
    bare, depo, log, env = _radar_ortam(tmp_path)
    r = _radar_kos(env, RADAR_VERI_DALI="canli-durum")
    assert r.returncode == 1 and "Geçersiz" in r.stderr and "copytrade.radar_tarama" not in log.read_text()


def test_guncelle_radar_zamanlayicisini_kurar_ve_etkinlestirir(sunucu):
    tohum = sunucu.depo.parent / "tohum"
    git(tohum, "pull", "-q", "origin", "main")
    (tohum / "deploy/sg-sanal-radar.service").write_text("[Service]\n# r1\n")
    (tohum / "deploy/sg-sanal-radar.timer").write_text("[Timer]\nOnCalendar=*-*-* 00:37:00 UTC\n")
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "radar birimleri")
    git(tohum, "push", "-q", "origin", "main")
    sunucu.ci(*YESIL)
    r = sunucu.calistir()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (sunucu.birim / "sg-sanal-radar.timer").exists() and (sunucu.birim / "sg-sanal-radar.service").exists()   # birimler kuruldu
    log = sunucu.log.read_text()
    assert "systemctl enable --now sg-sanal-radar.timer" in log and log.index("daemon-reload") < log.index("enable --now sg-sanal-radar.timer")
    assert "TG:" not in log                                                                           # kurulum mesaj atmaz


def test_guncelle_olcum_servisini_yalniz_bir_kez_baslatir(sunucu):
    tohum = sunucu.depo.parent / "tohum"
    git(tohum, "pull", "-q", "origin", "main")
    (tohum / "deploy/sg-sanal-olcum.service").write_text("[Service]\n# o1\n")
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "olcum birimi")
    git(tohum, "push", "-q", "origin", "main")
    sunucu.ci(*YESIL)
    r = sunucu.calistir()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (sunucu.birim / "sg-sanal-olcum.service").exists() and (sunucu.durum / "olcum_basladi").exists()
    assert sunucu.log.read_text().count("start --no-block sg-sanal-olcum.service") == 1
    sunucu.yeni_commit("v3")                                                       # sonraki güncelleme: işaret var -> yeniden başlatılmaz (96 sa bitince tekrar koşmasın)
    sunucu.ci(*YESIL)
    r = sunucu.calistir()
    assert r.returncode == 0, r.stdout + r.stderr
    assert sunucu.log.read_text().count("start --no-block sg-sanal-olcum.service") == 1
    assert "enable" not in "".join(l for l in sunucu.log.read_text().splitlines() if "olcum" in l)   # enable edilmez: yeniden açılışta kendiliğinden başlamaz


# ------------------------------------------------------------------------------------------------ K-80 kararlılık paketi (pencere, işaret, öz-denetim, 60 dk bekçi, çift doğrulama)
BEKCI = DEPLOY / "sanal_bekci.sh"


def test_k80_birimleri_zamanlayici_desenleri_ve_betik_sozdizimi():
    for ad in ("sanal_bekci.sh",):
        assert subprocess.run(["bash", "-n", str(DEPLOY / ad)], capture_output=True, text=True).returncode == 0
    t = (DEPLOY / "sg-sanal-bekci.timer").read_text(encoding="utf-8")
    assert "OnBootSec=5min" in t and "OnUnitActiveSec=5min" in t and "WantedBy=timers.target" in t     # ikinci-alarm deseni
    s = (DEPLOY / "sg-sanal-bekci.service").read_text(encoding="utf-8")
    assert "Type=oneshot" in s and "sanal_bekci.sh" in s and "StateDirectory=sg-sanal-guncelle" in s
    d = (DEPLOY / "sg-sanal-denetim.service").read_text(encoding="utf-8")
    assert "SANAL_YALNIZ_ALARM=1" in d and "sanal_guncelle.sh" in d and "OnCalendar=hourly" in (DEPLOY / "sg-sanal-denetim.timer").read_text(encoding="utf-8")
    for ad in ("sg-sanal-bekci.service", "sg-sanal-bekci.timer", "sg-sanal-denetim.service", "sg-sanal-denetim.timer"):
        assert not re.search(r"TELEGRAM_BOT_TOKEN=\S|BEGIN [A-Z ]*PRIVATE KEY", (DEPLOY / ad).read_text(encoding="utf-8")), ad


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze yok")
def test_k80_pencere_takvimi_ve_birimler_systemd_analyze():
    r = subprocess.run(["systemd-analyze", "calendar", "*-*-* 07:30:00 UTC", "*-*-* 19:30:00 UTC"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["systemd-analyze", "verify", *(str(DEPLOY / a) for a in ("sg-sanal-bekci.service", "sg-sanal-bekci.timer", "sg-sanal-denetim.service", "sg-sanal-denetim.timer"))], capture_output=True, text=True)
    assert not re.search(r"Unknown key|Unknown section|Invalid|Failed to parse", r.stdout + r.stderr), r.stdout + r.stderr


def _k80_birimler_ekle(sunucu):
    tohum = sunucu.depo.parent / "tohum"
    git(tohum, "pull", "-q", "origin", "main")
    for ad in ("sg-sanal-bekci.service", "sg-sanal-bekci.timer", "sg-sanal-denetim.service", "sg-sanal-denetim.timer"):
        (tohum / "deploy" / ad).write_text("[Unit]\n# k80\n")
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "k80 birimleri")
    git(tohum, "push", "-q", "origin", "main")


def test_k80_guncelle_isaret_bekci_ve_yeni_zamanlayicilari_kurar(sunucu):
    _k80_birimler_ekle(sunucu)
    sunucu.ci(*YESIL)
    r = sunucu.calistir()
    assert r.returncode == 0, r.stdout + r.stderr
    log = sunucu.log.read_text()
    assert "enable --now sg-sanal-bekci.timer" in log and "enable --now sg-sanal-denetim.timer" in log and "öz-denetim tamam" in r.stdout
    isaret = (sunucu.depo / "durum/guncelleme_zamani").read_text().split()                          # motor/Telegram bunu okur: epoch + sha
    assert abs(int(isaret[0]) - time.time()) < 60 and isaret[1] == sunucu.head()
    b = (sunucu.durum / "bekci").read_text().split()                                                  # 60 dk bekçi işareti: epoch / yeni / önceki / motor aktifti
    assert b[1] == sunucu.head() and b[2] == sunucu.v1 and b[3] == "1" and "TG:" not in log           # sessiz kurulum


def test_k80_oz_denetim_basarisizsa_geri_alir_ve_tek_uyari(sunucu):
    sunucu.yeni_commit("v2")
    sunucu.ci(*YESIL)
    r = sunucu.calistir(MOTOR_YAZMAZ="1")                                                            # servis başladı ama durum dosyaları yazılmıyor
    assert r.returncode == 1, r.stdout + r.stderr
    assert sunucu.head() == sunucu.v1 and "öz-denetim başarısız: durum-dosyalari-yazilmiyor" in r.stdout
    assert (sunucu.durum / "kotu_sha").exists() and not (sunucu.durum / "bekci").exists()
    log = sunucu.log.read_text()
    assert log.count("TG:") == 1 and "Bot güncellemesi başarısız" in log


def test_k80_oz_denetim_zamanlayici_etkin_degilse_geri_alir(sunucu):
    tohum = sunucu.depo.parent / "tohum"
    git(tohum, "pull", "-q", "origin", "main")
    (tohum / "deploy/sg-sanal-radar.timer").write_text("[Timer]\n")
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "radar")
    git(tohum, "push", "-q", "origin", "main")
    sunucu.ci(*YESIL)
    r = sunucu.calistir(ETKIN_DEGIL="sg-sanal-radar.timer")
    assert r.returncode == 1 and "sg-sanal-radar.timer-etkin-degil" in r.stdout and sunucu.head() == sunucu.v1


def _bekci_hazirla(sunucu):
    sunucu.yeni_commit("v2")
    sunucu.ci(*YESIL)
    assert sunucu.calistir().returncode == 0
    yeni = sunucu.head()
    (sunucu.depo / "kayit").mkdir(exist_ok=True)
    sunucu.log.write_text("")
    return yeni


def _kayit_yaz(sunucu, olaylar):
    yol = sunucu.depo / "kayit" / f"{time.strftime('%Y-%m-%d', time.gmtime())}.jsonl"
    ms = int(time.time() * 1000)
    with yol.open("a", encoding="utf-8") as f:
        for o in olaylar:
            f.write(json.dumps({"zaman_ms": ms, **o}) + "\n")


def _bekci(sunucu, **ek):
    return subprocess.run(["bash", str(BEKCI)], env={**sunucu.ortak, **ek}, capture_output=True, text=True)


def test_k80_bekci_sorunsuzsa_izler_60_dk_sonra_biter(sunucu):
    yeni = _bekci_hazirla(sunucu)
    r = _bekci(sunucu)
    assert r.returncode == 0 and "izleniyor" in r.stdout and sunucu.head() == yeni and (sunucu.durum / "bekci").exists()
    _kayit_yaz(sunucu, [{"olay": "adim_hata"}] * 7 + [{"olay": "telegram_hata"}] * 4)   # eşiklerin HEPSİ altında
    assert _bekci(sunucu).returncode == 0 and sunucu.head() == yeni
    b = (sunucu.durum / "bekci").read_text().split("\n")
    (sunucu.durum / "bekci").write_text("\n".join([str(int(time.time()) - 3700)] + b[1:]))
    r = _bekci(sunucu)
    assert "bekçi bitti" in r.stdout and not (sunucu.durum / "bekci").exists() and sunucu.head() == yeni and "TG:" not in sunucu.log.read_text()


@pytest.mark.parametrize("olaylar,neden", [
    ([{"olay": "bekci_tetik"}], "bekçi motoru 1 kez"),
    ([{"olay": "telegram_hata"}] * 3 + [{"olay": "telegram_yeniden", "tur": "CokIstek"}] * 2, "Telegram hata/429 5"),
    ([{"olay": "adim_hata"}] * 4 + [{"olay": "olay_hata"}] * 2 + [{"olay": "defter_hata"}] * 2, "hata olayı 8"),
])
def test_k80_bekci_esik_asilirsa_onceki_surume_doner_kotu_sha_ve_tek_uyari(sunucu, olaylar, neden):
    yeni = _bekci_hazirla(sunucu)
    _kayit_yaz(sunucu, olaylar)
    r = _bekci(sunucu)
    assert r.returncode == 0, r.stdout + r.stderr
    assert neden in r.stdout and sunucu.head() == sunucu.v1                                          # önceki sürüme dönüldü
    assert (sunucu.durum / "kotu_sha").read_text().strip() == yeni and not (sunucu.durum / "bekci").exists()
    log = sunucu.log.read_text()
    assert log.count("TG:") == 1 and "[CT] ⚠️ Yeni sürüm sorun çıkardı, önceki sürüme dönüldü (" in log and neden.split(" ")[0] in log
    assert not (sunucu.durum / "dondur").exists()                                                    # otomatik dönüş güncellemeyi dondurmaz (yeni commit gelince devam)
    r2 = sunucu.calistir()                                                                           # sonraki pencerede aynı bozuk sürüm yeniden kurulmaz
    assert "daha önce başarısız" in r2.stdout and sunucu.head() == sunucu.v1


def test_k80_bekci_yeniden_baslama_esigi(sunucu):
    yeni = _bekci_hazirla(sunucu)
    r = _bekci(sunucu, JOURNAL_SANAL=_yeniden(3))
    assert "motor 3 kez yeniden başladı" in r.stdout and sunucu.head() == sunucu.v1 and (sunucu.durum / "kotu_sha").read_text().strip() == yeni


def test_k80_bekci_bayat_isaret_dokunmaz(sunucu):
    yeni = _bekci_hazirla(sunucu)
    sunucu.durum.joinpath("bekci").write_text(f"{int(time.time())}\n{sunucu.v1}\n{sunucu.v1}\n1\n")  # HEAD işaretteki sürüm değil
    r = _bekci(sunucu, JOURNAL_SANAL=_yeniden(9))
    assert "bayat" in r.stdout and not (sunucu.durum / "bekci").exists() and sunucu.head() == yeni
    assert _bekci(sunucu).returncode == 0                                                           # işaret yok: hemen çıkar


def test_k80_bekci_motor_pasif_ust_uste_iki_turda(sunucu, tmp_path):
    yeni = _bekci_hazirla(sunucu)
    pasif = tmp_path / "pasifbin"
    pasif.mkdir()
    (pasif / "systemctl").write_text('#!/usr/bin/env bash\necho "systemctl $*" >> "$CAGRI_LOG"\ncase "$1" in is-active) exit 3;; esac\nif [ "$1" = start ] && [ "$2" = sg-sanal ]; then printf \'{"yazildi_ms": %s}\' "$(( $(date +%s) * 1000 ))" > "$SANAL_DEPO/durum/ozet.json"; fi\nexit 0\n')
    (pasif / "systemctl").chmod(0o755)
    ek = {"PATH": f"{pasif}:{sunucu.ortak['PATH']}"}
    r = _bekci(sunucu, **ek)
    assert "ilk tur" in r.stdout and sunucu.head() == yeni                                           # tek tur: yanlış alarm yok
    r = _bekci(sunucu, **ek)
    assert "motor aktif değil" in r.stdout and sunucu.head() == sunucu.v1


def test_k80_alarm_ikinci_dogrulamada_duzelen_alarm_gonderilmez(sunucu, tmp_path):
    """Çift doğrulama: ilk okumada >2 yeniden başlama, 1 sn sonraki ikinci okumada sayaç düşmüşse alarm GİTMEZ."""
    sayac = tmp_path / "sayac"
    sayac.write_text("0")
    (tmp_path / "bin/journalctl").write_text(
        '#!/usr/bin/env bash\ncase " $* " in *" -u sg-sanal "*) n=$(cat "$SAYAC"); echo $((n+1)) > "$SAYAC"; if [ "$n" = 0 ]; then printf "Scheduled restart job, restart counter is at 1.\\n%.0s" 1 2 3 4; fi; exit 0;; esac\nexit 0\n')
    r = sunucu.calistir(SAYAC=str(sayac), SANAL_DOGRULA_SN="1")
    assert r.returncode == 0 and "ikinci doğrulamada düzeldi" in r.stdout and _tg(sunucu) == []
    (tmp_path / "bin/journalctl").write_text('#!/usr/bin/env bash\ncase " $* " in *" -u sg-sanal "*) printf "Scheduled restart job, restart counter is at 1.\\n%.0s" 1 2 3 4; exit 0;; esac\nexit 0\n')
    r = sunucu.calistir(SANAL_DOGRULA_SN="1")                                                        # iki okumada da var: gider + bağlam satırı
    tg = _tg(sunucu)
    assert len(tg) == 1 and "Bot durdu" in tg[0] and "⏱ Son 1 saatte 4 yeniden başlama · son güncelleme: kayıt yok" in tg[0]


def test_k80_yalniz_alarm_kipi_guncelleme_yapmaz(sunucu):
    sunucu.yeni_commit("v2")
    sunucu.ci(*YESIL)
    r = sunucu.calistir(SANAL_YALNIZ_ALARM="1", JOURNAL_SANAL=_yeniden(4))
    assert r.returncode == 0 and sunucu.head() == sunucu.v1 and "systemctl stop" not in sunucu.log.read_text() and len(_tg(sunucu)) == 1


def test_guncelle_binance_kagit_motorunu_kurar_ve_baslatir_erisim_yoksa_tekrarlamaz(sunucu):
    tohum = sunucu.depo.parent / "tohum"
    git(tohum, "pull", "-q", "origin", "main")
    (tohum / "deploy/sg-sanal-binance-kagit.service").write_text("[Service]\n# b1\n")
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "binance kagit birimi")
    git(tohum, "push", "-q", "origin", "main")
    sunucu.ci(*YESIL)
    r = sunucu.calistir()
    assert r.returncode == 0, r.stdout + r.stderr
    log = sunucu.log.read_text()
    assert (sunucu.birim / "sg-sanal-binance-kagit.service").exists()
    assert "enable sg-sanal-binance-kagit.service" in log and "restart --no-block sg-sanal-binance-kagit.service" in log
    (sunucu.durum / "binance_kagit_kapali").write_text("")                      # kalıcı kapatma işareti: yeniden açılmaz
    sunucu.yeni_commit("v3")
    sunucu.ci(*YESIL)
    sunucu.log.write_text("")
    r = sunucu.calistir()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "sg-sanal-binance-kagit" not in sunucu.log.read_text()


# ------------------------------------------------------------------------------------------------ K-85: yeni dönem (durum sıfırlama) + radarın tek seferlik başlatılması
def test_k85_guncelle_yeni_donemde_yerel_durumu_sifirlar_arsiv_acmaz_ve_radari_bir_kez_baslatir(sunucu):
    tohum = sunucu.depo.parent / "tohum"
    git(tohum, "pull", "-q", "origin", "main")
    (tohum / "copytrade/canli").mkdir(parents=True)
    (tohum / "copytrade/canli/DONEM").write_text("2026-11-21T07:30:00Z\n")
    (tohum / "deploy/sg-sanal-radar.service").write_text("[Service]\n# r1\n")
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "yeni donem")
    git(tohum, "push", "-q", "origin", "main")
    (sunucu.depo / "durum").mkdir(exist_ok=True)
    (sunucu.depo / "kayit").mkdir(exist_ok=True)
    (sunucu.depo / "durum/hesap.json").write_text("{}")
    (sunucu.depo / "durum/donem.txt").write_text("2026-11-16T11:30:00Z\n")
    (sunucu.depo / "kayit/eski.jsonl").write_text("{}\n")
    sunucu.ci(*YESIL)
    r = sunucu.calistir()
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (sunucu.depo / "durum/hesap.json").exists() and not (sunucu.depo / "kayit/eski.jsonl").exists()          # eski dönem durumu sıfırlandı
    assert (sunucu.depo / "durum/donem.txt").read_text().strip() == "2026-11-21T07:30:00Z"                               # koruyucu/motor yeni dönemi buradan okur
    assert not (sunucu.depo.parent / "arsiv").exists() and not (sunucu.depo / "arsiv").exists()                          # arşiv klasörü YOK
    assert sunucu.log.read_text().count("start --no-block sg-sanal-radar.service") == 1
    assert (sunucu.durum / "radar_basladi").read_text().strip() == "2026-11-21T07:30:00Z"
    (sunucu.depo / "durum/hesap.json").write_text('{"canli": 1}')                                                        # aynı dönemde sonraki güncelleme: durum KORUNUR, radar yeniden başlamaz
    sunucu.yeni_commit("v3")
    sunucu.ci(*YESIL)
    r = sunucu.calistir()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (sunucu.depo / "durum/hesap.json").exists() and sunucu.log.read_text().count("start --no-block sg-sanal-radar.service") == 1


def test_k85_radar_betigi_yeni_donemde_bugunku_eski_kadro_olsa_da_kosar(tmp_path):
    bare, depo, log, env = _radar_ortam(tmp_path)
    (depo / "copytrade/canli").mkdir(parents=True, exist_ok=True)
    (depo / "copytrade/canli/DONEM").write_text("2026-11-21T07:30:00Z\n")
    git(depo, "add", "-A")
    git(depo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "donem")
    gun = time.strftime("%Y-%m-%d", time.gmtime())
    assert _radar_kos(env).returncode == 0                                                           # eski (sade olmayan) kadro bugün yayımlandı
    n = log.read_text().count("copytrade.radar_tarama")
    r = _radar_kos(env)
    assert r.returncode == 0 and log.read_text().count("copytrade.radar_tarama") == n + 1, r.stdout   # kadroda `sade`/`donem` yok → yeni dönem kadrosu sayılmaz: yeniden koşar
    assert f"radar/{gun}/kadro.json" in _dal_dosyalari(bare)
