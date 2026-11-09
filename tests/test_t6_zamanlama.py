"""T6 §4 zamanlama güvencesi (yedek cron) ve isabet adımının iş akışlarına bağlanması. Betik gerçek `git` ile geçici depolarda sınanır."""
import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows"
BETIK = ROOT / ".github/scripts/zamanlama_kontrol.sh"


def yukle(ad):
    veri = yaml.safe_load((WF / ad).read_text(encoding="utf-8"))
    veri["on"] = veri.pop(True, veri.get("on"))
    return veri


def git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)


def kur(tmp_path, dal, dosyalar):
    """Veri dalı `dal` (dosyalar: {yol: metin}) olan bir origin + `copytrade/kurallar.yaml` içeren çalışma dizini."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    bare, tohum, calisma = tmp_path / "origin.git", tmp_path / "tohum", tmp_path / "calisma"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    tohum.mkdir()
    git(tohum, "init", "-q", "-b", dal)
    for yol, metin in dosyalar.items():
        (tohum / yol).parent.mkdir(parents=True, exist_ok=True)
        (tohum / yol).write_text(metin, encoding="utf-8")
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "x")
    git(tohum, "remote", "add", "origin", str(bare))
    git(tohum, "push", "-q", "origin", dal)
    calisma.mkdir()
    git(calisma, "init", "-q")
    git(calisma, "remote", "add", "origin", str(bare))
    (calisma / "copytrade").mkdir()
    shutil.copy(ROOT / "copytrade/kurallar.yaml", calisma / "copytrade/kurallar.yaml")
    return calisma


def calistir(calisma, mod, dal, olay="schedule", zamanlama="17 2 * * *", yedek="17 2 * * *"):
    cikti = calisma / "cikti.txt"
    cikti.write_text("", encoding="utf-8")
    env = {**os.environ, "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": olay, "ZAMANLAMA": zamanlama, "YEDEK_CRON": yedek, "VERI_DALI": dal, "GITHUB_OUTPUT": str(cikti)}
    r = subprocess.run(["bash", str(BETIK), mod], cwd=calisma, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return cikti.read_text(encoding="utf-8").strip(), r.stdout


def test_radar_yedek_cron_bugunun_klasoru_varsa_atlar_yoksa_calisir_birincil_ve_elle_her_zaman_calisir(tmp_path):
    bugun = datetime.now(UTC).date().isoformat()
    c = kur(tmp_path / "a", "radar", {f"radar/{bugun}/havuz.json": "{}"})
    assert calistir(c, "radar", "radar")[0] == "atla=true"                                                    # klasör var → yedek hiçbir şey yapmaz
    assert calistir(c, "radar", "radar", zamanlama="37 0 * * *")[0] == "atla=true"                             # geç gelen birincil koşu da bugünün klasörü varsa atlar (kadro gün içinde ikinci kez yazılmaz)
    assert calistir(c, "radar", "radar", olay="workflow_dispatch")[0] == "atla=false"                          # elle: çalışır
    c2 = kur(tmp_path / "b", "radar", {"radar/2020-01-01/havuz.json": "{}"})
    assert calistir(c2, "radar", "radar")[0] == "atla=false"                                                  # bugünün klasörü yok → yedek çalışır
    assert calistir(c2, "radar", "radar", zamanlama="37 0 * * *")[0] == "atla=false"                           # birincil de klasör yoksa çalışır
    c3 = tmp_path / "c"
    c3.mkdir()
    git(c3, "init", "-q")
    git(c3, "remote", "add", "origin", str(tmp_path / "yok.git"))
    (c3 / "copytrade").mkdir()
    shutil.copy(ROOT / "copytrade/kurallar.yaml", c3 / "copytrade/kurallar.yaml")
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "yok.git")], check=True)
    assert calistir(c3, "radar", "radar")[0] == "atla=false"                                                  # veri dalı hiç yok → çalışır


@pytest.mark.parametrize("kilit, beklenen", [
    ({"birakildi": False, "nabiz_ms": int(time.time() * 1000) - 5 * 60_000}, "atla=true"),             # 5 dk önce nabız: taze → yedek başlamaz (alarm yok)
    ({"birakildi": True, "nabiz_ms": int(time.time() * 1000) - 1_000}, "atla=false"),                  # temiz bırakılmış: başlar
    ({"birakildi": False, "nabiz_ms": int(time.time() * 1000) - 21 * 60_000}, "atla=false"),            # 20 dk'dan eski (çökme): devralır
])
def test_canli_yedek_cron_kilit_taze_ise_baslamaz_alarm_yok(tmp_path, kilit, beklenen):
    c = kur(tmp_path, "canli-durum", {"durum/kilit.json": json.dumps({"vardiya": "A", **kilit})})
    cikti, stdout = calistir(c, "canli", "canli-durum", yedek="37 */4 * * *", zamanlama="37 */4 * * *")
    assert cikti == beklenen and "BAŞLAMADI" not in stdout
    if beklenen == "atla=true":
        assert "beklenen, alarm yok" in stdout
    assert calistir(c, "canli", "canli-durum", yedek="37 */4 * * *", zamanlama="7 */4 * * *")[0] == "atla=false"          # birincil cron kilide bakmaz (concurrency + motor kilidi korur)


def test_is_akislari_kontrol_isi_isabet_adimi_ve_zaman_butcesi():
    radar, canli = yukle("radar.yml"), yukle("canli_vardiya.yml")
    assert radar["jobs"]["radar"]["needs"] == "kontrol" and "atla != 'true'" in radar["jobs"]["radar"]["if"]
    assert canli["jobs"]["vardiya"]["needs"] == "kontrol" and "atla != 'true'" in canli["jobs"]["vardiya"]["if"]
    assert radar["on"]["schedule"][1] == {"cron": "17 2 * * *"} and radar["jobs"]["kontrol"]["steps"][1]["env"]["YEDEK_CRON"] == "17 2 * * *"
    assert canli["jobs"]["kontrol"]["steps"][1]["env"]["YEDEK_CRON"] == canli["on"]["schedule"][1]["cron"]
    adimlar = [a.get("name", a.get("uses", "")) for a in radar["jobs"]["radar"]["steps"]]
    secim = next(a for a in adimlar if a.startswith("Seçim yapısı D"))         # K-55: isabet adımı çıkarıldı
    assert adimlar.index(secim) < adimlar.index("Veri dalına yaz (radar)") and radar["jobs"]["radar"]["timeout-minutes"] >= 180     # secim_butce_dk 120 sığar


def test_isabet_deneme_salt_okunur_ve_kismi():
    wf = yukle("isabet_deneme.yml")
    assert wf["permissions"] == {"contents": "read"} and wf["on"]["push"] == {"paths": ["copytrade/isabet_deneme/CALISTIR"]}
    adim = next(a for a in wf["jobs"]["isabet"]["steps"] if "isabet" in a.get("name", "").lower())
    assert "--kismi" in adim["run"] and "git push" not in (WF / "isabet_deneme.yml").read_text(encoding="utf-8")


def test_radar_yayimla_isabet_dosyalarini_da_yayimlar():
    metin = (ROOT / ".github/scripts/radar_yayimla.sh").read_text(encoding="utf-8")
    assert "isabet.json" in metin and 'git add -f "radar/$g/isabet.json"' in metin and "|| true" not in metin


def test_canli_vardiya_pano_adimi_yayimdan_once_ve_gecmis_geri_yuklenir():
    wf = yukle("canli_vardiya.yml")
    adimlar = [a.get("name", a.get("uses", "")) for a in wf["jobs"]["vardiya"]["steps"]]
    assert adimlar.index("Canlı motor (sanal kip)") < adimlar.index("Günlük rapor (pano/OZET.md)") < adimlar.index("Durumu veri dalına yaz")
    pano = next(a for a in wf["jobs"]["vardiya"]["steps"] if a.get("name") == "Günlük rapor (pano/OZET.md)")
    assert "copytrade.canli.pano" in pano["run"] and "always()" in pano["if"]
    metin = (WF / "canli_vardiya.yml").read_text(encoding="utf-8")
    assert "pano/gecmis.json" in metin and "|| true" not in metin
    assert "pano/OZET.md" in (ROOT / ".github/scripts/canli_yayimla.sh").read_text(encoding="utf-8")


def test_b7_canli_yayimla_her_yayimda_pano_uretir_bayat_ozet_ile_uretmez(tmp_path):
    """B7: `canli_yayimla.sh` (15 dk'lık döngü) pano/index.html + OZET.md üretip veri dalına yazar; ozet.json başka vardiyadansa pano YAZILMAZ ama durum yayımı sürer. Gerçek git, gerçek pano.py."""
    bare, calisma = tmp_path / "origin.git", tmp_path / "calisma"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    calisma.mkdir()
    git(calisma, "init", "-q", "-b", "main")
    git(calisma, "remote", "add", "origin", str(bare))
    (calisma / "OKU.md").write_text("x")
    git(calisma, "add", "OKU.md")
    git(calisma, "commit", "-q", "-m", "x")                                                                    # Actions checkout'unda HEAD vardır (orphan veri dalı oluşturma için)
    os.symlink(ROOT / "copytrade", calisma / "copytrade")
    (calisma / "durum").mkdir()
    (calisma / "kayit").mkdir()
    for ad, v in {"hesap.json": {"poz": {}, "realize": {}, "ucret": {}, "slot_bas": {}}, "risk.json": {"gun_basi": 1000.0, "zirve": 1000.0}, "saha.json": {"uyeler": {}, "inen": {}}}.items():
        (calisma / "durum" / ad).write_text(json.dumps(v))
    (calisma / "durum" / "ozet.json").write_text(json.dumps({"kip": "sanal", "vardiya": "77", "kasa_usd": 1000.0, "ozsermaye_usd": 1001.5, "getiri": 0.0015, "saha": 9, "saha_n": 11, "acik": []}))
    (calisma / "kayit" / "2026-11-05.jsonl").write_text("")
    env = {**os.environ, "GITHUB_ACTIONS": "true", "VERI_DALI": "canli-durum-deneme", "GITHUB_RUN_ID": "77"}
    r = subprocess.run(["bash", str(ROOT / ".github/scripts/canli_yayimla.sh")], cwd=calisma, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    dosyalar = subprocess.run(["git", "ls-tree", "-r", "--name-only", "canli-durum-deneme"], cwd=bare, capture_output=True, text=True).stdout.split()
    assert "pano/index.html" in dosyalar and "pano/OZET.md" in dosyalar and "durum/ozet.json" in dosyalar and "pano/gecmis.json" in dosyalar
    html = subprocess.run(["git", "show", "canli-durum-deneme:pano/index.html"], cwd=bare, capture_output=True, text=True).stdout
    assert "1.001,50 $" in html and "COPY TRADE PANOSU" in html
    # bayat: yeni vardiya kimliği (88) ≠ ozet.json'daki (77) → pano dosyaları güncellenmez (eski içerik kalır), durum yayımı sürer
    (calisma / "durum" / "ozet.json").write_text(json.dumps({"kip": "sanal", "vardiya": "77", "kasa_usd": 1000.0, "ozsermaye_usd": 1234.0, "getiri": 0.234, "saha": 9, "saha_n": 11}))
    env2 = {**env, "GITHUB_RUN_ID": "88"}
    r2 = subprocess.run(["bash", str(ROOT / ".github/scripts/canli_yayimla.sh")], cwd=calisma, env=env2, capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    html2 = subprocess.run(["git", "show", "canli-durum-deneme:pano/index.html"], cwd=bare, capture_output=True, text=True).stdout
    assert "1.001,50 $" in html2 and "1.234,00 $" not in html2


@pytest.mark.parametrize("kilit, beklenen", [
    ({"birakildi": False, "nabiz_ms": int(time.time() * 1000) - 5 * 60_000}, "atla=true"),             # G3: zincir dispatch'i, kilit taze → çift vardiya olmaz
    ({"birakildi": True, "nabiz_ms": int(time.time() * 1000) - 1_000}, "atla=false"),                  # önceki vardiya kilidi bıraktı → yeni vardiya başlar
    ({"birakildi": False, "nabiz_ms": int(time.time() * 1000) - 21 * 60_000}, "atla=false"),            # 20 dk kuralı korunur: bayat kilit devralınır
])
def test_g3_canli_dispatch_taze_kilitte_atlar(tmp_path, kilit, beklenen):
    c = kur(tmp_path, "canli-durum", {"durum/kilit.json": json.dumps({"vardiya": "A", **kilit})})
    cikti, stdout = calistir(c, "canli", "canli-durum", olay="workflow_dispatch", zamanlama="", yedek="37 */4 * * *")
    assert cikti == beklenen and "BAŞLAMADI" not in stdout
    assert calistir(c, "canli", "canli-durum", olay="push", zamanlama="", yedek="37 */4 * * *")[0] == "atla=false"        # push (dal denemesi) her zaman çalışır


def test_g3_canli_dispatch_veri_dali_yoksa_calisir(tmp_path):
    c = tmp_path / "c"
    c.mkdir()
    git(c, "init", "-q")
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "yok.git")], check=True)
    git(c, "remote", "add", "origin", str(tmp_path / "yok.git"))
    (c / "copytrade").mkdir()
    shutil.copy(ROOT / "copytrade/kurallar.yaml", c / "copytrade/kurallar.yaml")
    assert calistir(c, "canli", "canli-durum", olay="workflow_dispatch", zamanlama="")[0] == "atla=false"


def _sahte_gh_ile(tmp_path, kilit, gh_govde):
    c = kur(tmp_path, "canli-durum", {"durum/kilit.json": json.dumps(kilit)})
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "gh").write_text(f'#!/usr/bin/env bash\necho "$@" >> "{tmp_path}/gh.txt"\n{gh_govde}\n', encoding="utf-8")
    (bin_ / "gh").chmod(0o755)
    cikti = c / "cikti.txt"
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch", "ZAMANLAMA": "", "YEDEK_CRON": "37 */4 * * *",
           "VERI_DALI": "canli-durum", "GITHUB_OUTPUT": str(cikti), "GITHUB_REPOSITORY": "o/r"}
    r = subprocess.run(["bash", str(BETIK), "canli"], cwd=c, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    gh = (tmp_path / "gh.txt").read_text().split() if (tmp_path / "gh.txt").exists() else []
    return cikti.read_text(encoding="utf-8").strip(), r.stdout, gh


@pytest.mark.parametrize("gh_govde, beklenen", [
    ("echo completed", "atla=false"),       # A-2 (b): kilit bırakılmamış ama sahibi koşu BİTMİŞ (son yayım düştü) → bayat kilit, vardiya başlar (zincir kopmaz)
    ("echo in_progress", "atla=true"),      # sahibi koşu sürüyor → gerçek taze kilit, atla (çift vardiya yok)
    ("exit 1", "atla=true"),                # durum okunamadı → güvenli yön: taze say, atla
])
def test_a2_canli_dispatch_kilit_sahibi_kosu_bittiyse_bayat_sayilir(tmp_path, gh_govde, beklenen):
    kilit = {"vardiya": "123456", "birakildi": False, "nabiz_ms": int(time.time() * 1000) - 2 * 60_000}
    cikti, stdout, gh = _sahte_gh_ile(tmp_path, kilit, gh_govde)
    assert cikti == beklenen and gh[:3] == ["api", "repos/o/r/actions/runs/123456", "--jq"]
    assert ("bayat kilit" in stdout) == (beklenen == "atla=false")


def test_a2_kilit_sahibi_sayisal_degilse_ya_da_kilit_bayatsa_gh_cagrilmaz(tmp_path):
    """Kilitteki `vardiya` run_id değilse (eski/yerel) davranış değişmez: taze kilit atlar, gh çağrılmaz. Zaten bayat/bırakılmış kilitte de gh çağrılmaz."""
    simdi = int(time.time() * 1000)
    cikti, _, gh = _sahte_gh_ile(tmp_path / "a", {"vardiya": "A", "birakildi": False, "nabiz_ms": simdi - 2 * 60_000}, "echo completed")
    assert cikti == "atla=true" and gh == []
    cikti, _, gh = _sahte_gh_ile(tmp_path / "b", {"vardiya": "99", "birakildi": True, "nabiz_ms": simdi}, "echo in_progress")
    assert cikti == "atla=false" and gh == []


def test_a2_kontrol_isi_salt_okur_actions_okuma_ve_gh_token():
    k = yukle("canli_vardiya.yml")["jobs"]["kontrol"]
    assert k["permissions"] == {"contents": "read", "actions": "read"} and k["steps"][1]["env"]["GH_TOKEN"] == "${{ github.token }}"
