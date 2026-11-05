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
    assert adimlar.index("Günlük kadro (R2 form puanı)") < adimlar.index("Seçim isabeti (§7b)") < adimlar.index("Veri dalına yaz (radar)")
    isabet = next(a for a in radar["jobs"]["radar"]["steps"] if a.get("name") == "Seçim isabeti (§7b)")
    assert "copytrade.radar_isabet" in isabet["run"] and "continue-on-error" not in isabet and radar["jobs"]["radar"]["timeout-minutes"] >= 180            # tarama 120 + isabet 30 dk bütçesi sığar


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
