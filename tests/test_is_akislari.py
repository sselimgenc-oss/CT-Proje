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


YASAK = "|".join(["KARAR_" + "URL", "GECIKME_" + "URL", "TELE" + "GRAM", "CLOUD" + "FLARE", r"copytrade\.kararlar", r"copytrade\.gecikme\b", "degisim_rapor"])
YASAK_DEPO = "|".join(["R" + "2_", "aws s" + "3", "cloud" + "flare", "wrang" + "ler", "AWS_"])


def test_worker_telegram_adimlari_geri_gelmedi_k13():
    for ad in ISLER:
        metin = (WF / ad).read_text(encoding="utf-8")
        assert not re.search(YASAK, metin), ad


# ---------------------------------------------------------------------------------------------------- izleme: motor durumu geri yükleme, kısmi sonuç, hepsi hatalı
def motor_ac(tmp_path: Path, gz: bytes | None):
    """izleme.yml'deki 'Motor durumunu ... aç' adımını çalıştırır (K-20; veri dalındaki `izleme/motor.json.gz`)."""
    (tmp_path / "izleme").mkdir(exist_ok=True)
    if gz is not None:
        (tmp_path / "izleme/motor.json.gz").write_bytes(gz)
    run = adim(yukle("izleme.yml"), "izleme", "Motor durumunu veri dalındaki")["run"]
    return subprocess.run(["bash", "-euo", "pipefail", "-c", run], cwd=tmp_path, capture_output=True, text=True)


def test_izleme_motor_durumu_veri_dalindaki_gz_den_acilir(tmp_path):
    import gzip
    sonuc = motor_ac(tmp_path, gzip.compress(b'{"surum": 1, "traderlar": {}, "olaylar": {}}'))
    assert sonuc.returncode == 0, sonuc.stderr
    assert json.loads((tmp_path / "izleme/motor.json").read_text())["surum"] == 1


def test_izleme_motor_durumu_yoksa_ilk_kosu_ama_bozuk_dosya_isi_kirmizi_yapar(tmp_path):
    yok = motor_ac(tmp_path, None)
    assert yok.returncode == 0 and not (tmp_path / "izleme/motor.json").exists()                 # ilk koşu: motor sıfırdan başlar
    bozuk = motor_ac(tmp_path, b"gzip degil")
    assert bozuk.returncode != 0                                                                 # sessizce sıfırlanıp üzerine yazılmaz


def test_is_akislari_harici_depo_ve_sunucusuz_servis_kullanmaz():
    for ad in ISLER:
        metin = (WF / ad).read_text(encoding="utf-8")
        assert not re.search(YASAK_DEPO, metin, re.I), ad


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
    kalanlar = {"ci.yml", "dinleyici_deneme.yml", "dolgu_deneme.yml", "gecikme_kar_deneme.yml", "izleme.yml", "izleme_deneme.yml", "pano.yml", "sonnet_isci.yml"}
    assert {p.name for p in WF.glob("*.yml")} == kalanlar          # eski sistem iş akışları (kapı, Pazar kadrosu, İlk 11 denemesi, v3 yan yana) geri gelmedi
    assert not (SCRIPTS / "kapi_yayimla.sh").exists()
    assert (SCRIPTS / "izleme_yayimla.sh").exists() and ".github/scripts/izleme_yayimla.sh" in (WF / "izleme.yml").read_text(encoding="utf-8")
