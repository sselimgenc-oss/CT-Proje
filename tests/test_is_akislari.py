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
    kalanlar = {"canli_vardiya.yml", "ci.yml", "dinleyici_deneme.yml", "dolgu_deneme.yml", "gecikme_kar_deneme.yml", "isabet_deneme.yml", "izleme.yml", "izleme_deneme.yml", "radar.yml", "radar_deneme.yml", "saglik.yml"}  # sonnet_isci.yml kaldırıldı (devir denetimi G-11, 06.11); saglik.yml: sağlık kontrolü (kullanıcı kararı 2026-11-05; salt okur, testi test_saglik.py)
    assert {p.name for p in WF.glob("*.yml")} == kalanlar          # eski sistem iş akışları (kapı, Pazar kadrosu, İlk 11 denemesi, v3 yan yana) geri gelmedi
    assert not (WF / "pano.yml").exists() and not (ROOT / "copytrade" / "pano_veri.py").exists() and not (ROOT / "pano").exists()     # eski GitHub Pages panosu (copytrade-izleme'ye bağlı) kaldırıldı; yeni pano `copytrade/canli/pano.py`
    assert not (SCRIPTS / "kapi_yayimla.sh").exists()
    assert not (WF / "sonnet_isci.yml").exists()                     # G-11: yazma yetkili ajan iş akışı geri gelmedi
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


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _radar_kosusu(tmp_path: Path, remote: Path, ad: str, gun: str, kosu_ms: int) -> Path:
    """Actions'taki gibi taze checkout (main'i taklit eden tek commit) + o koşunun radar/<gun>/{havuz,kadro}.json'u; radar_yayimla.sh'yi koşturur."""
    co = tmp_path / ad
    co.mkdir()
    _git(co, "init", "-q")
    _git(co, "config", "user.name", "Test")
    _git(co, "config", "user.email", "test@example.com")
    _git(co, "remote", "add", "origin", str(remote))
    (co / "kaynak.py").write_text("kaynak veri dalına girmez")
    _git(co, "add", ".")
    _git(co, "commit", "-qm", "kaynak")
    (co / "radar" / gun).mkdir(parents=True)
    (co / "radar" / gun / "havuz.json").write_text(json.dumps({"sema": "radar-havuz-v1", "kosu_ms": kosu_ms, "satirlar": []}))
    (co / "radar" / gun / "kadro.json").write_text(json.dumps({"sema": "radar-kadro-v1", "kosu_ms": kosu_ms, "satirlar": []}))
    s = subprocess.run(["bash", str(SCRIPTS / "radar_yayimla.sh")], cwd=co, env={**os.environ, "GITHUB_ACTIONS": "true", "VERI_DALI": "radar"}, capture_output=True, text=True)
    assert s.returncode == 0, s.stderr
    return co


def _dal_json(remote: Path, yol: str) -> dict | None:
    s = subprocess.run(["git", "-C", str(remote), "show", f"radar:{yol}"], capture_output=True, text=True)
    return json.loads(s.stdout) if s.returncode == 0 else None


def test_radar_yayimla_gunun_ilk_kadrosunu_korur_ikinci_yayim_ezmez(tmp_path):
    """Denetim R-1 (altın örnek 2026-11-05 deseni): 01:16Z koşusu (kosu 1) ilk yayım → kadro_ilk/havuz_ilk = 1; aynı gün 07:19Z koşusu (kosu 2) → kadro.json ve son/ = 2,
    kadro_ilk/havuz_ilk HÂLÂ 1. Ertesi gün (kosu 3) kendi kadro_ilk'ini alır; önceki günün dosyaları değişmez."""
    import datetime as dt
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare")
    bugun = dt.datetime.now(dt.UTC).date()
    gun, yarin = bugun.isoformat(), (bugun + dt.timedelta(days=1)).isoformat()     # 90 gün silmesine takılmasın diye bugün
    _radar_kosusu(tmp_path, remote, "kosu1", gun, 1)
    assert _dal_json(remote, f"radar/{gun}/kadro_ilk.json")["kosu_ms"] == 1 and _dal_json(remote, f"radar/{gun}/havuz_ilk.json")["kosu_ms"] == 1
    _radar_kosusu(tmp_path, remote, "kosu2", gun, 2)
    assert _dal_json(remote, f"radar/{gun}/kadro.json")["kosu_ms"] == 2 and _dal_json(remote, "radar/son/kadro.json")["kosu_ms"] == 2      # eski davranış korunur
    assert _dal_json(remote, f"radar/{gun}/kadro_ilk.json")["kosu_ms"] == 1 and _dal_json(remote, f"radar/{gun}/havuz_ilk.json")["kosu_ms"] == 1   # ilk kadro ezilmedi
    _radar_kosusu(tmp_path, remote, "kosu3", yarin, 3)
    assert _dal_json(remote, f"radar/{yarin}/kadro_ilk.json")["kosu_ms"] == 3 and _dal_json(remote, f"radar/{gun}/kadro_ilk.json")["kosu_ms"] == 1
    assert _git(remote, "rev-list", "--count", "radar") == "3"


def test_radar_yayimla_eski_gunde_kadro_varsa_yanlis_ilk_yazmaz(tmp_path):
    """Bu değişiklikten önce yayımlanmış gün (dalda kadro.json var, kadro_ilk.json yok): ikinci yayım kadro_ilk.json YAZMAZ (yazsa 2. kadroyu "ilk" sanırdı); isabet git geçmişinden kurar."""
    import datetime as dt
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare")
    gun = dt.datetime.now(dt.UTC).date().isoformat()
    co = _radar_kosusu(tmp_path, remote, "kosu1", gun, 1)
    _git(co, "rm", "-q", f"radar/{gun}/kadro_ilk.json", f"radar/{gun}/havuz_ilk.json")       # eski biçimli günü taklit et
    _git(co, "commit", "-qm", "eski biçim")
    _git(co, "push", "-q", "origin", "HEAD:radar")
    _radar_kosusu(tmp_path, remote, "kosu2", gun, 2)
    assert _dal_json(remote, f"radar/{gun}/kadro.json")["kosu_ms"] == 2 and _dal_json(remote, f"radar/{gun}/kadro_ilk.json") is None


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


# ---------------------------------------------------------------------------------------------------- B1: Telegram yalnız main
def _telegram_envleri(wf: dict):
    """(is, ad, değer) — iş ve adım düzeyindeki TELEGRAM_* ortam değişkenleri."""
    for is_adi, is_ in wf.get("jobs", {}).items():
        for ad, deger in (is_.get("env") or {}).items():
            if ad.startswith("TELEGRAM"):
                yield is_adi, ad, str(deger)
        for a in is_.get("steps", []):
            for ad, deger in (a.get("env") or {}).items():
                if ad.startswith("TELEGRAM"):
                    yield is_adi, ad, str(deger)


def test_telegram_secretlari_yalniz_main_dalinda_verilir_b1():
    """B1 (Opus denetimi 05.11): deneme/dal koşuları Telegram token/chat id görmez (iki getUpdates tüketicisi komut kaybettirir)."""
    bulunan = 0
    for dosya in sorted(WF.glob("*.yml")):
        metin = dosya.read_text(encoding="utf-8")
        for _, ad, deger in _telegram_envleri(yaml.safe_load(metin)):
            if ad == "TELEGRAM_KOMUT":                                     # O-1: secret DEĞİL, repo değişkeni; yalnız bu birebir ifade serbest (komut kapatma anahtarı)
                assert deger == "${{ vars.TELEGRAM_KOMUT }}", (dosya.name, deger)
                continue
            bulunan += 1
            assert f"secrets.{ad}" in deger and "github.ref == 'refs/heads/main'" in deger and deger.rstrip("} ").endswith("|| ''"), (dosya.name, ad, deger)
            assert "vars.TELEGRAM_ACIK == 'evet'" in deger, (dosya.name, ad, deger)      # kullanıcı kararı 08.11: Telegram varsayılan KAPALI; repo değişkeni TELEGRAM_ACIK=evet ile açılır
        for satir in metin.splitlines():                  # hiçbir yerde çıplak Telegram secret'ı yok
            if "secrets.TELEGRAM" in satir and not satir.lstrip().startswith("#"):
                assert "refs/heads/main" in satir, (dosya.name, satir)
    assert bulunan >= 4          # canli_vardiya (2) + saglik (2)


def test_telegram_tokensiz_kanal_kapali_ve_sessiz_b1():
    """Deneme dalında secret '' gelir: kanal kapalı, ağ çağrısı yok."""
    from copytrade.canli import telegram as tg

    def yasak(url, yuk):
        raise AssertionError("token yokken ağ çağrısı yapılmamalı")

    t = tg.Telegram(post=yasak, ortam={"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""})
    assert not t.token and not t.chat_id
    assert t.gonder("deneme") is False
    assert t.komutlari_al() == []



# ---------------------------------------------------------------------------------------------------- G3: vardiya zinciri (ayrı `zincir` işi)
def _zincir_calistir(tmp_path: Path, gh_cikis: int, curl_cikis: int = 0, telegram: bool = False, yas_dk: int | None = 60):
    """`zincir` işinin run: bloğunu sahte gh/curl ile gerçekten çalıştırır; (çıktı, gh çağrıları, curl çağrıları).
    `gh api …run_started_at` sahte yanıtı: yas_dk dakika önce (None = okunamaz, gh api başarısız). `gh api` çağrıları gh listesine yazılmaz (yalnız `workflow run`)."""
    run = adim(yukle("canli_vardiya.yml"), "zincir", "tetikle")["run"]
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for ad, cikis in (("gh", gh_cikis), ("curl", curl_cikis)):
        kayit = tmp_path / f"{ad}.txt"
        api = ""
        if ad == "gh":
            api = 'if [ "$1" = api ]; then ' + ('exit 1; ' if yas_dk is None else f'date -u -d "{yas_dk} minutes ago" +%Y-%m-%dT%H:%M:%SZ; exit 0; ') + 'fi\n'
        (bin_ / ad).write_text(f'#!/usr/bin/env bash\n{api}echo "$@" >> "{kayit}"\nexit {cikis}\n', encoding="utf-8")
        (bin_ / ad).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "RUN_URL": "http://x/run", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "1", "TELEGRAM_BOT_TOKEN": "TOK" if telegram else "", "TELEGRAM_CHAT_ID": "CH" if telegram else ""}
    r = subprocess.run(["bash", "-euo", "pipefail", "-c", run], env=env, capture_output=True, text=True)
    oku = lambda ad: (tmp_path / f"{ad}.txt").read_text(encoding="utf-8").splitlines() if (tmp_path / f"{ad}.txt").exists() else []
    return r, oku("gh"), oku("curl")


def test_g3_zincir_basarida_vardiya_ve_saglik_tetiklenir(tmp_path):
    r, gh, curl = _zincir_calistir(tmp_path, 0, telegram=True)
    assert r.returncode == 0 and gh == ["workflow run canli_vardiya.yml --ref main", "workflow run saglik.yml --ref main"] and curl == []
    assert "TOK" not in r.stdout + r.stderr                                                          # secret yazdırılmaz


def test_g3_zincir_hatasi_sessiz_yutulmaz_uyari_ve_telegram_ama_isi_kirmaz(tmp_path):
    r, gh, curl = _zincir_calistir(tmp_path, 1, telegram=True)
    assert r.returncode == 0 and "::warning::canli_vardiya.yml tetiklenemedi" in r.stdout and "::warning::saglik.yml tetiklenemedi" in r.stdout
    assert len(curl) == 1 and "sendMessage" in curl[0] and "TOK" not in r.stdout + r.stderr          # yalnız vardiya zinciri için alarm
    assert "TOK" in curl[0]                                                                          # (sahte curl argümanı; gerçek çıktıya yazılmaz)


def test_g3_zincir_hatasi_telegram_yoksa_sessiz_gecer_ama_uyari_kalir(tmp_path):
    r, gh, curl = _zincir_calistir(tmp_path, 1)
    assert r.returncode == 0 and curl == [] and "::warning::canli_vardiya.yml tetiklenemedi" in r.stdout


def test_g3_actions_write_yalniz_zincir_isinde_main_ve_basari_kosullu_checkoutsuz():
    wf = yukle("canli_vardiya.yml")
    metin = (WF / "canli_vardiya.yml").read_text(encoding="utf-8")
    assert wf["permissions"] == {"contents": "write"} and wf["jobs"]["kontrol"]["permissions"] == {"contents": "read"} and "permissions" not in wf["jobs"]["vardiya"]      # vardiya/kontrol: actions yazma yok (kontrol: O-2 yalnız okuma)
    z = wf["jobs"]["zincir"]
    assert z["permissions"] == {"actions": "write", "contents": "read"} and metin.count("actions: write") == 1
    # Y-1 (denetim #3): zincir vardiya başarısız olsa da sürer (always()), yalnız iptal/atlanmış vardiyada çalışmaz; always() yasağı YALNIZ diğer işlerde kalır (zincir bilinçli istisna)
    assert z["needs"] == "vardiya" and z["if"] == "${{ always() && github.ref == 'refs/heads/main' && needs.vardiya.result != 'cancelled' && needs.vardiya.result != 'skipped' }}"
    assert "failure()" not in z["if"] and "always()" not in str(wf["jobs"]["kontrol"].get("if", "")) and "always()" not in str(wf["jobs"]["vardiya"].get("if", ""))
    assert wf["jobs"]["vardiya"]["env"]["TELEGRAM_KOMUT"] == "${{ vars.TELEGRAM_KOMUT }}"             # O-1: boş = komut alma açık
    assert "--canli-url" in adim(wf, "vardiya", "Canlı motor")["run"] and "copytrade.saglik" in adim(wf, "vardiya", "Canlı motor")["run"]
    assert all("uses" not in a for a in z["steps"])                                                    # checkout yok (kimlik bilgisi diske bırakılmaz)
    assert "GH_TOKEN" not in str(wf["jobs"]["vardiya"]) and "github.token" not in str(wf["jobs"]["vardiya"]) and "github.token" not in str(wf["jobs"]["kontrol"])
    run = z["steps"][0]["run"]
    assert "echo \"$GH_TOKEN\"" not in run and "echo \"$TELEGRAM" not in run and "|| true" not in run
    assert z["env"]["TELEGRAM_BOT_TOKEN"].startswith("${{ github.ref == 'refs/heads/main' &&") and z["env"]["GH_REPO"] == "${{ github.repository }}"
    assert "workflow_dispatch" in wf["on"] and "workflow_dispatch" in yukle("saglik.yml")["on"]
    assert "zincir_tetikle" not in metin
    assert "pkill -P \"$yayim\"" in adim(wf, "vardiya", "Canlı motor")["run"]                          # çalışan yayım betiği sahipsiz kalmaz


def test_y1_zincir_genc_kosuda_tetiklemez_yalniz_alarm(tmp_path):
    """Koşu yaşı < 20 dk (motor hemen düştü): sonraki vardiya/sağlık TETİKLENMEZ, Telegram alarmı + ::warning, çıkış 0."""
    r, gh, curl = _zincir_calistir(tmp_path, 0, telegram=True, yas_dk=3)
    assert r.returncode == 0 and gh == [] and "::warning::vardiya 20 dk" in r.stdout
    assert len(curl) == 1 and "sendMessage" in curl[0] and "TOK" not in r.stdout + r.stderr


def test_y1_zincir_yas_okunamazsa_guvenli_yon_tetiklemez(tmp_path):
    r, gh, curl = _zincir_calistir(tmp_path, 0, telegram=True, yas_dk=None)
    assert r.returncode == 0 and gh == [] and len(curl) == 1


def test_y1_zincir_20_dk_ve_uzeri_iki_tetik(tmp_path):
    r, gh, curl = _zincir_calistir(tmp_path, 0, telegram=True, yas_dk=21)
    assert r.returncode == 0 and gh == ["workflow run canli_vardiya.yml --ref main", "workflow run saglik.yml --ref main"] and curl == []
