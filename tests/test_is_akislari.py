"""İş akışı kuralları (kalan iş akışları): YAML metni + çalışma davranışı. 870974e'de silinen iş akışı testlerinin kuralları yeniden kurulur."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from copytrade import izleme_motoru as m
from test_izleme import ADDRESS, NOW, Client, project

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows"
SCRIPTS = ROOT / ".github/scripts"
ISLER = ("izleme.yml", "dinleyici_deneme.yml", "izleme_deneme.yml")


def yukle(ad: str) -> dict:
    veri = yaml.safe_load((WF / ad).read_text(encoding="utf-8"))
    veri["on"] = veri.pop(True, veri.get("on"))          # PyYAML `on:` anahtarını True yapar
    return veri


def adim(wf: dict, is_adi: str, ad_parcasi: str) -> dict:
    return next(a for a in wf["jobs"][is_adi]["steps"] if ad_parcasi in a.get("name", ""))


def adimlar(wf: dict, is_adi: str) -> list[str]:
    return [a.get("name", a.get("uses", "")) for a in wf["jobs"][is_adi]["steps"]]


# ---------------------------------------------------------------------------------------------------- ortak kurallar
@pytest.mark.parametrize("ad", ISLER)
def test_her_run_blogu_set_euo_pipefail_ile_calisir(ad):
    wf = yukle(ad)
    kabuk = wf["defaults"]["run"]["shell"]
    assert kabuk == "bash -euo pipefail {0}"                                                # her run: bloğu set -euo pipefail ile çalışır
    for is_ in wf["jobs"].values():
        for a in is_["steps"]:
            assert "shell" not in a or "pipefail" in a["shell"], a                          # adım kabuğu varsayılanı gevşetemez


def test_hata_or_true_ile_orulmez_ve_main_e_yazilmaz():
    for yol in [*(WF / a for a in ISLER), *SCRIPTS.glob("*.sh")]:
        metin = yol.read_text(encoding="utf-8")
        assert not re.search(r"\|\|\s*true\b|\|\|\s*:\s*($|;)|continue-on-error:\s*true", metin), yol.name
        assert not re.search(r"git push[^\n]*\bmain\b|push origin main|HEAD:main", metin), yol.name        # main'e doğrudan yazım yok


def test_veri_dali_yazimlari_yalniz_veri_dallarina():
    for ad in ISLER:
        for satir in (WF / ad).read_text(encoding="utf-8").splitlines():
            assert "git push" not in satir, (ad, satir)              # push yalnız betikte; iş akışları (deneme dahil) doğrudan push etmez
    assert (WF / "izleme_deneme.yml").read_text(encoding="utf-8").count("permissions:\n  contents: read") == 1          # deneme yazamaz
    for satir in (SCRIPTS / "izleme_yayimla.sh").read_text(encoding="utf-8").splitlines():
        if "git push" in satir:
            assert "HEAD:copytrade-izleme" in satir, satir


def test_izleme_zamanlamasi_t1de_kaldirildi_elle_calisir_ve_kuyruk_bekler():
    """T1 (K-19): izleme eski kadroyu izlediği için cron kaldırıldı; T4'te radar kadrosu için geri gelir. `veri_tazelik_dk` (270) = 2 × 120 dk aralık + 30 dk tampon."""
    on = yukle("izleme.yml")["on"]
    assert "schedule" not in on and "workflow_dispatch" in on
    assert yukle("izleme.yml")["concurrency"]["cancel-in-progress"] is False
    assert yaml.safe_load((ROOT / "copytrade" / "kurallar.yaml").read_text(encoding="utf-8"))["veri_tazelik_dk"] == 270


def test_izleme_ilk_okuma_icin_timeout_300_dk_kuyruk_bekler():
    wf = yukle("izleme.yml")
    assert wf["jobs"]["izleme"]["timeout-minutes"] == 300 <= 360                               # 86 trader ilk okuma ≈ 192 dk (ölçüm); GitHub sınırı 360
    assert wf["concurrency"] == {"group": "copytrade-izleme", "cancel-in-progress": False}      # sonraki koşular uzun ilk koşunun arkasında bekler


def test_worker_telegram_adimlari_geri_gelmedi_k13():
    for ad in ISLER:
        metin = (WF / ad).read_text(encoding="utf-8")
        assert not re.search(r"KARAR_URL|GECIKME_URL|TELEGRAM|CLOUDFLARE|copytrade\.kararlar|copytrade\.gecikme|degisim_rapor", metin), ad


# ---------------------------------------------------------------------------------------------------- izleme: R2 geri yükleme, kısmi sonuç, hepsi hatalı
def r2_kabuk(tmp_path: Path, mod: str):
    aws = tmp_path / "bin/aws"
    aws.parent.mkdir(exist_ok=True)
    aws.write_text("""#!/bin/sh
case "$1 $2" in
  "s3api head-object")
    case "$FAKE_MOD" in
      var) exit 0 ;;
      yok) echo "An error occurred (404) when calling the HeadObject operation: Not Found" >&2; exit 254 ;;
      *) echo "Could not connect to the endpoint URL" >&2; exit 255 ;;
    esac ;;
  "s3 cp") printf '{"surum": 1, "traderlar": {}, "olaylar": {}}' | gzip -c > "$4" ;;
esac
""")
    os.chmod(aws, 0o755)
    (tmp_path / "izleme").mkdir(exist_ok=True)
    run = adim(yukle("izleme.yml"), "izleme", "R2'den indir")["run"]
    return subprocess.run(["bash", "-euo", "pipefail", "-c", run], cwd=tmp_path, capture_output=True, text=True,
                          env={**os.environ, "PATH": f"{aws.parent}:{os.environ['PATH']}", "FAKE_MOD": mod, "R2_ACCOUNT_ID": "hesap", "R2_BUCKET": "kova"})


def test_izleme_r2_motor_durumu_geri_yuklenir(tmp_path):
    sonuc = r2_kabuk(tmp_path, "var")
    assert sonuc.returncode == 0, sonuc.stderr
    assert json.loads((tmp_path / "izleme/motor.json").read_text())["surum"] == 1 and not (tmp_path / "motor.json.gz").exists()


def test_izleme_r2_yoksa_ilk_gecis_ama_baska_hata_isi_kirmizi_yapar(tmp_path):
    yok = r2_kabuk(tmp_path, "yok")
    assert yok.returncode == 0 and "R2'de motor durumu yok" in yok.stdout and not (tmp_path / "izleme/motor.json").exists()
    ag = r2_kabuk(tmp_path, "ag")
    assert ag.returncode == 1 and "okunamadı" in ag.stderr                                      # sessizce sıfırlanıp R2 üzerine yazılmaz


class Bozuk(Client):
    def fills(self, address, start):
        raise RuntimeError("429 sınır")


def test_izleme_tum_trader_hatali_ise_hicbir_dosya_yayimlanmaz(tmp_path):
    root = project(tmp_path)
    with pytest.raises(RuntimeError, match="Tüm trader verileri hatalı"):
        m.run(root, root / "out", Bozuk(), NOW)
    assert not (root / "out/durum.json").exists() and not (root / "out/motor.json").exists()


def test_izleme_tek_trader_hatasinda_kismi_sonuc_yazilir(tmp_path):
    satirlar = [{"id": "T1", "adres": ADDRESS, "takma_ad": "Bir", "durum": "izlemede", "t0": str(m.timestamp("2026-10-27").date())},
                {"id": "T2", "adres": "0x" + "2" * 40, "takma_ad": "İki", "durum": "izlemede", "t0": str(m.timestamp("2026-10-27").date())}]
    root = project(tmp_path, satirlar)

    class Biri(Client):
        def fills(self, address, start):
            if address == satirlar[1]["adres"]:
                raise RuntimeError("429")
            return super().fills(address, start)
    m.run(root, root / "out", Biri(), NOW)
    durum = json.loads((root / "out/durum.json").read_text())
    assert {t["id"]: t["gecerli"] for t in durum["traderlar"]} == {"T1": True, "T2": False}
    motor = json.loads((root / "out/motor.json").read_text())["traderlar"]
    assert "son_trader" in motor["T1"] and "son_trader" not in motor["T2"]                       # hatalı trader'ın başarılı yükü yok (yer tutucu yayımlandı)


def test_izleme_listesi_main_den_okunur_ve_veri_dalina_yazilir():
    kosu = adim(yukle("izleme.yml"), "izleme", "sanal defteri güncelle")["run"]
    assert kosu == "python -m copytrade.izleme_motoru --root . --output izleme"              # liste: main'deki copytrade/izleme_listesi.yaml (T1: veri dalı listesi kalktı)
    assert adim(yukle("izleme.yml"), "izleme", "veri dalına yaz")["run"] == "bash .github/scripts/izleme_yayimla.sh"


# ---------------------------------------------------------------------------------------------------- artık dosya temizliği
def test_eski_sistem_is_akislari_ve_betikleri_yok():
    kalanlar = {"ci.yml", "dinleyici_deneme.yml", "dolgu_deneme.yml", "gecikme_kar_deneme.yml", "izleme.yml", "izleme_deneme.yml", "pano.yml", "sonnet_isci.yml", "worker.yml"}
    assert {p.name for p in WF.glob("*.yml")} == kalanlar          # eski sistem iş akışları (kapı, Pazar kadrosu, İlk 11 denemesi, v3 yan yana) geri gelmedi
    assert not (SCRIPTS / "kapi_yayimla.sh").exists()
    assert (SCRIPTS / "izleme_yayimla.sh").exists() and ".github/scripts/izleme_yayimla.sh" in (WF / "izleme.yml").read_text(encoding="utf-8")
