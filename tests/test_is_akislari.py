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
ISLER = ("izleme.yml", "dinleyici_deneme.yml", "izleme_deneme.yml", "radar_deneme.yml", "radar.yml", "canli_vardiya.yml", "isabet_deneme.yml")


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
    """Eski Worker/Telegram adımları (K‑13) geri gelmedi. İSTİSNA (T4, K‑19 canlı motor): yalnız `canli_vardiya.yml` motorun Telegram secret'larını ortam değişkeni olarak geçirir (bildirim/komut `copytrade/canli/telegram.py`);
    K-40 ek istisnası (kullanıcı onayı 2026-11-05): yine yalnız `canli_vardiya.yml` panoyu Cloudflare Workers `sg-pano`'ya yayımlamak için Cloudflare secret'larını geçirir; diğer yasaklı ifadeler orada da yasak."""
    for ad in ISLER:
        metin = (WF / ad).read_text(encoding="utf-8")
        yasak = YASAK.replace("TELE" + "GRAM|", "").replace("CLOUD" + "FLARE|", "") if ad == "canli_vardiya.yml" else YASAK       # K-40 ek istisnası (kullanıcı onayı 2026-11-05)
        assert not re.search(yasak, metin), ad


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
        depo = YASAK_DEPO.replace("cloud" + "flare|", "") if ad == "canli_vardiya.yml" else YASAK_DEPO       # K-40 ek istisnası: yalnız canli_vardiya.yml; R2/AWS/wrangler yine yasak
        assert not re.search(depo, metin, re.I), ad


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
    kalanlar = {"canli_vardiya.yml", "ci.yml", "dinleyici_deneme.yml", "dolgu_deneme.yml", "gecikme_kar_deneme.yml", "isabet_deneme.yml", "izleme.yml", "izleme_deneme.yml", "radar.yml", "radar_deneme.yml", "saglik.yml", "sonnet_isci.yml"}  # saglik.yml: sağlık kontrolü (kullanıcı kararı 2026-11-05; salt okur, testi test_saglik.py)
    assert {p.name for p in WF.glob("*.yml")} == kalanlar          # eski sistem iş akışları (kapı, Pazar kadrosu, İlk 11 denemesi, v3 yan yana) geri gelmedi
    assert not (WF / "pano.yml").exists() and not (ROOT / "copytrade" / "pano_veri.py").exists() and not (ROOT / "pano").exists()     # eski GitHub Pages panosu (copytrade-izleme'ye bağlı) kaldırıldı; yeni pano `copytrade/canli/pano.py`
    assert not (SCRIPTS / "kapi_yayimla.sh").exists()
    assert (SCRIPTS / "izleme_yayimla.sh").exists() and ".github/scripts/izleme_yayimla.sh" in (WF / "izleme.yml").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- radar (T3)
def test_radar_yml_gunluk_00_37_utc_kadro_ve_yayim_sirasi():
    wf = yukle("radar.yml")
    assert wf["on"]["schedule"] == [{"cron": "37 0 * * *"}, {"cron": "17 2 * * *"}] and "workflow_dispatch" in wf["on"] and wf["on"]["push"] == {"paths": ["copytrade/radar/CALISTIR"]}
    assert adim(wf, "radar", "Veri dalına yaz")["env"]["VERI_DALI"] == "${{ github.ref == 'refs/heads/main' && 'radar' || 'radar-deneme' }}"        # dal koşusu gerçek radar dalına yazmaz
    assert "inputs" not in (wf["on"]["workflow_dispatch"] or {})                              # donmuş kurallar: aday sayısı / kural_ust girdisi YOK
    assert wf["permissions"] == {"contents": "write"} and wf["concurrency"]["cancel-in-progress"] is False
    ad = adimlar(wf, "radar")
    assert ad.index("Radar taraması (R0 + R1 + R2 girdileri)") < ad.index("Günlük kadro (R2 form puanı)") < ad.index("Veri dalına yaz (radar)")
    tarama, kadro = adim(wf, "radar", "Radar taraması")["run"], adim(wf, "radar", "Günlük kadro")["run"]
    assert "--aday-sayisi" not in tarama and "--kural-ust" not in tarama and "kural_ust" not in (WF / "radar.yml").read_text(encoding="utf-8").replace("`kural_ust`", "")
    assert "copytrade.radar_kadro" in kadro
    assert adim(wf, "radar", "Veri dalına yaz")["run"] == "bash .github/scripts/radar_yayimla.sh" and "if" not in adim(wf, "radar", "Veri dalına yaz")      # yalnız başarıda (varsayılan success())
    artifact = next(a for a in wf["jobs"]["radar"]["steps"] if str(a.get("uses", "")).startswith("actions/upload-artifact"))
    assert artifact["if"] == "always()"                                                       # eksik koşuda da havuz.json artifact'ı kalır


def test_radar_yayimla_yalniz_radar_dalina_ve_90_gun():
    metin = (SCRIPTS / "radar_yayimla.sh").read_text(encoding="utf-8")
    for satir in metin.splitlines():
        if "git push" in satir:
            assert 'HEAD:$veri_dali' in satir, satir
    assert 'case "$veri_dali" in radar|radar-deneme)' in metin                               # yalnız bu iki veri dalı
    assert "90 days ago" in metin and "radar/son/kadro.json" in metin and '--orphan "$veri_dali"' in metin
    assert "|| true" not in metin


def test_radar_deneme_kural_ust_girdisi_var_yazamaz():
    wf = yukle("radar_deneme.yml")
    assert "kural_ust" in wf["on"]["workflow_dispatch"]["inputs"] and wf["permissions"] == {"contents": "read"}
    assert "--kural-ust" in adim(wf, "radar", "Radar taraması")["run"] and "--v4-yan-yana" in adim(wf, "radar", "Radar taraması")["run"]


# ---------------------------------------------------------------------------------------------------- canlı vardiya (T4)
def test_canli_vardiya_yalniz_sanal_anahtarsiz_kuyruklu_ve_dal_ayrimi():
    metin = (WF / "canli_vardiya.yml").read_text(encoding="utf-8")
    wf = yukle("canli_vardiya.yml")
    assert wf["on"]["schedule"] == [{"cron": "7 */4 * * *"}, {"cron": "37 */4 * * *"}] and wf["on"]["push"] == {"paths": ["copytrade/canli/CALISTIR"]}
    assert wf["concurrency"] == {"group": "${{ github.ref == 'refs/heads/main' && 'canli-vardiya-uretim' || format('canli-vardiya-deneme-{0}', github.ref_name) }}", "cancel-in-progress": False} and wf["permissions"] == {"contents": "write"}      # K-37 §8: üretim ≠ deneme kuyruğu
    assert "HL_API_CUZDAN_ANAHTARI" not in metin and "HL_HESAP_ADRESI" not in metin and "--kip gercek" not in metin and "--kip sanal" in metin             # gerçek kip Actions'ta ASLA
    env = wf["jobs"]["vardiya"]["env"]
    assert env["VERI_DALI"] == "${{ github.ref == 'refs/heads/main' && 'canli-durum' || 'canli-durum-deneme' }}"
    assert env["KADRO_DALI"] == "${{ github.ref == 'refs/heads/main' && 'radar' || 'radar-deneme' }}"
    assert wf["jobs"]["vardiya"]["timeout-minutes"] >= 285                                                                                                  # 4 sa 15 dk vardiya + kurulum payı
    ad = adimlar(wf, "vardiya")
    assert ad.index("Açılış kontrolü (anahtarsız, emir göndermez)") < ad.index("Canlı motor (sanal kip)") < ad.index("Durumu veri dalına yaz")
    assert adim(wf, "vardiya", "Durumu veri dalına yaz")["if"] == "${{ always() }}" and "255" in adim(wf, "vardiya", "Canlı motor")["run"]


def test_canli_yayimla_ayri_worktree_yalniz_canli_dallarina_14_gun():
    metin = (SCRIPTS / "canli_yayimla.sh").read_text(encoding="utf-8")
    for satir in metin.splitlines():
        if "push" in satir and "git" in satir:
            assert 'HEAD:$veri_dali' in satir, satir
    assert 'case "$veri_dali" in canli-durum|canli-durum-deneme)' in metin and "git worktree add" in metin and "14 days ago" in metin and "|| true" not in metin
    assert "git checkout -f" not in metin                                                                                  # motorun çalıştığı dizini değiştirmez


def test_k40_pano_yayini_yalniz_ana_dal_ve_anahtar_varsa_ve_hata_gorunur():
    """K-40 ek: Cloudflare yayını yalnız `canli-durum` dalında, yalnız iki secret de varsa, yalnız index.html; hata uyarı olarak görünür (|| true yok)."""
    metin = (SCRIPTS / "canli_yayimla.sh").read_text(encoding="utf-8")
    assert '[ "$veri_dali" = canli-durum ]' in metin and "CLOUDFLARE_API_TOKEN" in metin and "CLOUDFLARE_ACCOUNT_ID" in metin
    assert 'cp "$kaynak/pano/index.html" "$cf_dizin/site/index.html"' in metin and "--assets=site" in metin and "--name sg-pano" in metin
    assert "wrangler@4.158.0" in metin                                                              # sürüm sabit (tedarik zinciri)
    assert metin.index("git -C \"$work\" push -q") < metin.index("then cf_yayin; exit 0; fi", metin.index("git -C \"$work\" push -q"))  # yayın durum push'undan sonra
    assert 'echo "UYARI: Cloudflare pano yayını başarısız' in metin
    wf = (WF / "canli_vardiya.yml").read_text(encoding="utf-8")
    assert wf.count("secrets.CLOUDFLARE_API_TOKEN") == 2 and "secrets.CLOUDFLARE_ACCOUNT_ID" in wf
    assert "env -u CLOUDFLARE_API_TOKEN -u CLOUDFLARE_ACCOUNT_ID python -u -m copytrade.canli.motor" in wf   # motor süreci anahtarı görmez
