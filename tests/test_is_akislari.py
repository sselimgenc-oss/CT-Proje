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
ISLER = ("radar.yml", "canli_vardiya.yml")   # 08.11 kullanıcı: eski deneme iş akışları (dinleyici/dolgu/gecikme_kar/izleme_deneme) silindi; K-66 (14.11): radar_deneme/isabet_deneme silindi


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
    for satir in (SCRIPTS / "izleme_yayimla.sh").read_text(encoding="utf-8").splitlines():
        if "git push" in satir:
            assert "HEAD:copytrade-izleme" in satir, satir


def test_s21_izleme_yml_silindi_ve_hicbir_is_akisi_silinmis_copytrade_izleme_dalina_yazmaz():
    """S-21 (denetim 08.11): `izleme.yml` (yalnız elle; T1'de cron'u kaldırılmıştı) silinmiş `copytrade-izleme` dalına yazıyordu; dal KARARLAR (05.11 akşam) ile silindi → iş akışı ölü, kaldırıldı.
    Önceki iki test (cron yok / timeout 300 + kuyruk) bu dosyanın içeriğini sınıyordu; dosya yok olduğundan yerine YOKLUK sınanır. `veri_tazelik_dk` kuralı (motor ayarı) korunur."""
    assert not (WF / "izleme.yml").exists()
    for yol in WF.glob("*.yml"):
        assert "copytrade-izleme" not in yol.read_text(encoding="utf-8"), yol.name
    assert yaml.safe_load((ROOT / "copytrade" / "kurallar.yaml").read_text(encoding="utf-8"))["veri_tazelik_dk"] == 270


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
def test_s21_izleme_motor_gz_acma_adimi_izleme_yml_ile_kalkti():
    """S-21: önceki iki test (`izleme.yml` 'Motor durumunu veri dalındaki ... aç' adımı: gz açılır / yoksa ilk koşu, bozuksa kırmızı) yalnız silinen `izleme.yml`'nin adımını koşturuyordu.
    Adım dosyayla birlikte kalktı; yerine hiçbir iş akışının o adımı (ölü veri dalının `izleme/motor.json.gz`'si) taşımadığı sınanır."""
    for yol in WF.glob("*.yml"):
        assert "izleme/motor.json.gz" not in yol.read_text(encoding="utf-8"), yol.name


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


def test_s21_izleme_yayimla_betigini_hicbir_is_akisi_cagirmaz():
    """S-21: önceki test `izleme.yml`'nin motor + `izleme_yayimla.sh` adımlarını sınıyordu; iş akışı silindi. Betik (ve test_izleme.py'deki davranış testleri) yerinde kalır
    ama artık HİÇBİR iş akışı onu çağırmaz (silinmiş dala yazım yolu kapalı)."""
    for yol in WF.glob("*.yml"):
        assert "izleme_yayimla.sh" not in yol.read_text(encoding="utf-8"), yol.name


# ---------------------------------------------------------------------------------------------------- artık dosya temizliği
def test_eski_sistem_is_akislari_ve_betikleri_yok():
    kalanlar = {"canli_vardiya.yml", "ci.yml", "radar.yml", "saglik.yml", "nabiz_yayim.yml"} | ({"dal_sil.yml"} if (WF / "dal_sil.yml").exists() else set())   # 08.11 kullanıcı: eski deneme iş akışları ve tek seferlik dal_sil.yml kaldırıldı; saglik.yml: sağlık kontrolü (test_saglik.py); nabiz_yayim.yml: G-10 dış ölü adam alarmı (test_nabiz.py)  # K-66 (14.11): radar_deneme, isabet_deneme, kalicilik, v11_sinama, secim_dogrulama silindi
    assert {p.name for p in WF.glob("*.yml")} == kalanlar          # eski sistem iş akışları (kapı, Pazar kadrosu, İlk 11 denemesi, v3 yan yana) geri gelmedi
    assert not (WF / "pano.yml").exists() and not (ROOT / "copytrade" / "pano_veri.py").exists() and not (ROOT / "pano").exists()     # eski GitHub Pages panosu (copytrade-izleme'ye bağlı) kaldırıldı; yeni pano `copytrade/canli/pano.py`
    assert not (SCRIPTS / "kapi_yayimla.sh").exists()
    assert not (WF / "sonnet_isci.yml").exists()                     # G-11: yazma yetkili ajan iş akışı geri gelmedi
    assert (SCRIPTS / "izleme_yayimla.sh").exists() and not (WF / "izleme.yml").exists()      # S-21: izleme.yml (silinmiş copytrade-izleme dalına yazan) kaldırıldı; betik test_izleme.py testleriyle duruyor


def test_silinen_deneme_is_akislarinin_olu_kodu_ve_tetik_dosyalari_yok():
    """09.11 temizlik: 08.11'de silinen deneme iş akışlarının (izleme/dolgu/gecikme_kar/dinleyici_deneme) yalnız onlarca çağrılan modül, betik ve CALISTIR dosyaları kaldırıldı."""
    for yol in ("copytrade/deneme_arac.py", "copytrade/dolgu_deneme.py", "copytrade/risk_deneme.py", ".github/scripts/h1_ozet.py",
                "copytrade/izleme_deneme", "copytrade/dinleyici_deneme"):
        assert not (ROOT / yol).exists(), yol
    for yol in [*WF.glob("*.yml"), *(p for p in SCRIPTS.glob("*") if p.is_file()), *(ROOT / "copytrade").rglob("*.py")]:
        assert not re.search(r"deneme_arac|dolgu_deneme|risk_deneme|h1_ozet", yol.read_text(encoding="utf-8")), yol


def test_k66_d_arti_ve_deneme_kalintilari_yok():
    """K-66 (14.11) temizlik: D/D+ seçimi, K-65 vetoları, elle çıkarma, seçim doğrulaması ve deneme iş akışlarına ait kod, tetik dosyası ve kural anahtarı kalmadı."""
    for yol in ("copytrade/secim_d.py", "copytrade/kalicilik_testi.py", "copytrade/v11_sinama.py", "copytrade/gecmis_funding.py", "copytrade/gecikme_kar.py",
                "copytrade/finans_mutabakat.py", "copytrade/mutabakat_raporu.py", "copytrade/portfoy_oynatma.py", "copytrade/radar/HARIC", "copytrade/radar_deneme",
                "copytrade/isabet_deneme", "copytrade/kalicilik", "copytrade/v11_sinama", "arastirma/secim_dogrulama"):
        assert not (ROOT / yol).exists(), yol
    assert not [k for k in yaml.safe_load((ROOT / "copytrade/kurallar.yaml").read_text(encoding="utf-8")) if k.startswith("secim_")]
    for yol in [*WF.glob("*.yml"), *(p for p in SCRIPTS.glob("*") if p.is_file()), *(ROOT / "copytrade").rglob("*.py")]:
        assert not re.search(r"secim_d\b|kalicilik_testi|v11_sinama|ANINDA_CIKIS|elle_cikarildi|veto_omur_zarar", yol.read_text(encoding="utf-8")), yol


def test_dal_sil_yalniz_listelenen_arsiv_dallari_elle_main():
    """Tek seferlik temizlik (kullanıcı onayı 09.11): yalnız iptal edilen 300 $ serinin arşiv dalları; canlı veri dalları, main ve oturum dalı listede olamaz; yalnız elle ve yalnız main'de."""
    if not (WF / "dal_sil.yml").exists():
        return
    wf = yukle("dal_sil.yml")
    assert set(wf["on"]) == {"workflow_dispatch"} and wf["permissions"] == {"contents": "read"} and wf["jobs"]["sil"]["permissions"] == {"contents": "write"}
    assert wf["jobs"]["sil"]["if"] == "${{ github.ref == 'refs/heads/main' }}"
    run = wf["jobs"]["sil"]["steps"][0]["run"]
    dallar = re.findall(r'^DALLAR="([^"]*)"', run, re.M)[0].split()
    assert dallar == ["canli-durum-300", "canli-durum-300-deneme"]
    for korunan in ("main", "canli-durum", "radar", "radar-deneme", "canli-durum-deneme", "claude/stoic-carson-w3xagz"):
        assert korunan not in dallar


# ---------------------------------------------------------------------------------------------------- radar (T3)
def test_radar_yml_gunluk_00_37_utc_kadro_ve_yayim_sirasi():
    wf = yukle("radar.yml")
    assert wf["on"]["schedule"] == [{"cron": "37 0 * * *"}, {"cron": "17 2 * * *"}] and "workflow_dispatch" in wf["on"] and wf["on"]["push"] == {"paths": ["copytrade/radar/CALISTIR"]}
    assert adim(wf, "radar", "Veri dalına yaz")["env"]["VERI_DALI"] == "${{ github.ref == 'refs/heads/main' && 'radar' || 'radar-deneme' }}"        # dal koşusu gerçek radar dalına yazmaz
    assert "inputs" not in (wf["on"]["workflow_dispatch"] or {})                              # donmuş kurallar: aday sayısı / kural_ust girdisi YOK
    assert wf["permissions"] == {"contents": "read"} and wf["jobs"]["radar"]["permissions"] == {"contents": "write"} and wf["concurrency"]["cancel-in-progress"] is False   # G-23: yazma yalnız radar işinde
    ad = adimlar(wf, "radar")
    # K-66 (14.11): Form Radarı adımları (tarama → kadro → isabet) geri; D+ (secim_d) adımı yok
    assert ad.index("Radar taraması (R0 + R1 + R2 girdileri)") < ad.index("Günlük kadro (R2 form puanı)") < ad.index("Seçim isabeti (§7b)") < ad.index("Veri dalına yaz (radar)")
    tarama, kadro = adim(wf, "radar", "Radar taraması")["run"], adim(wf, "radar", "Günlük kadro")["run"]
    assert "--aday-sayisi" not in tarama and "--kural-ust" not in tarama and "kural_ust" not in (WF / "radar.yml").read_text(encoding="utf-8").replace("`kural_ust`", "")
    assert "python -u -m copytrade.radar_tarama --cikti radar" in tarama and "copytrade.radar_kadro" in kadro and "copytrade.secim_d" not in (WF / "radar.yml").read_text(encoding="utf-8")
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


# ---------------------------------------------------------------------------------------------------- canlı vardiya (T4)
def test_canli_vardiya_yalniz_sanal_anahtarsiz_kuyruklu_ve_dal_ayrimi():
    metin = (WF / "canli_vardiya.yml").read_text(encoding="utf-8")
    wf = yukle("canli_vardiya.yml")
    assert wf["on"]["schedule"] == [{"cron": "7 */4 * * *"}, {"cron": "37 */4 * * *"}] and wf["on"]["push"] == {"paths": ["copytrade/canli/CALISTIR"]}
    assert wf["concurrency"] == {"group": "${{ github.ref == 'refs/heads/main' && 'canli-vardiya-uretim' || format('canli-vardiya-deneme-{0}', github.ref_name) }}", "cancel-in-progress": False}      # K-37 §8: üretim ≠ deneme kuyruğu
    assert wf["permissions"] == {"contents": "read"} and wf["jobs"]["vardiya"]["permissions"] == {"contents": "write"}         # G-23: yazma yalnız vardiya işinde
    assert "HL_API_CUZDAN_ANAHTARI" not in metin and "HL_HESAP_ADRESI" not in metin and "--kip gercek" not in metin and "--kip sanal" in metin             # gerçek kip Actions'ta ASLA
    env = wf["jobs"]["vardiya"]["env"]
    assert env["VERI_DALI"] == "${{ github.ref == 'refs/heads/main' && 'canli-durum' || 'canli-durum-deneme' }}"
    assert env["KADRO_DALI"] == "${{ github.ref == 'refs/heads/main' && 'radar' || 'radar-deneme' }}"
    assert wf["jobs"]["vardiya"]["timeout-minutes"] >= 285                                                                                                  # 4 sa 15 dk vardiya + kurulum payı
    ad = adimlar(wf, "vardiya")
    assert ad.index("Açılış kontrolü (anahtarsız, emir göndermez)") < ad.index("Canlı motor (sanal kip)") < ad.index("Durumu veri dalına yaz")
    assert adim(wf, "vardiya", "Durumu veri dalına yaz")["if"] == "${{ always() }}" and "255" in adim(wf, "vardiya", "Canlı motor")["run"]
    assert ad.index("Vardiya süresi (sınırlı)") < ad.index("Canlı motor (sanal kip)") and ad.index("Durumu veri dalından geri yükle (dönem kuralı)") < ad.index("Vardiya süresi (sınırlı)")   # S-20: donem_geri.sh'ın GIRDI_SURE_DK'sı da sınırlanır


def test_canli_yayimla_ayri_worktree_yalniz_canli_dallarina_14_gun():
    metin = (SCRIPTS / "canli_yayimla.sh").read_text(encoding="utf-8")
    for satir in metin.splitlines():
        if "push" in satir and "git" in satir:
            assert 'HEAD:$veri_dali' in satir, satir
    assert 'case "$veri_dali" in canli-durum|canli-durum-deneme)' in metin and "git worktree add" in metin and "14 days ago" in metin and "|| true" not in metin
    assert "git checkout -f" not in metin                                                                                  # motorun çalıştığı dizini değiştirmez


def test_k40_pano_yayini_yalniz_ana_dal_ve_anahtar_varsa_ve_hata_gorunur():
    """K-40 ek: Cloudflare yayını yalnız `canli-durum` dalından, yalnız iki secret de varsa, yalnız index.html; hata uyarı olarak görünür (|| true yok).
    G-23 (denetim 08.11): yayın artık AYRI `pano` işinde (`pano_cf_yayimla.sh`, contents: read); yazma yetkili vardiya işi ve canli_yayimla.sh Cloudflare/wrangler görmez."""
    metin = (SCRIPTS / "pano_cf_yayimla.sh").read_text(encoding="utf-8")
    assert "veri_dali=canli-durum" in metin and "CLOUDFLARE_API_TOKEN" in metin and "CLOUDFLARE_ACCOUNT_ID" in metin
    assert "contents/pano/index.html?ref=${veri_dali}" in metin and 'cp "$cf_dizin/yeni.html" "$cf_dizin/site/index.html"' in metin and "--assets=site" in metin and "--name sg-pano" in metin
    assert "npx" not in metin and "|| true" not in metin                                            # ağdan çözülen paket yok; kilit dosyasından kurulmuş yerel ikili
    assert "::warning::UYARI: Cloudflare pano yayını başarısız" in metin
    paket = json.loads((ROOT / ".github/pano/package.json").read_text(encoding="utf-8"))
    kilit = json.loads((ROOT / ".github/pano/package-lock.json").read_text(encoding="utf-8"))
    assert paket["devDependencies"] == {"wrangler": "4.158.0"}                                     # sürüm sabit (tedarik zinciri)
    assert kilit["packages"]["node_modules/wrangler"]["version"] == "4.158.0" and kilit["packages"]["node_modules/wrangler"]["integrity"].startswith("sha512-")
    assert all(p.get("resolved", "https://registry.npmjs.org/").startswith("https://registry.npmjs.org/") and ("integrity" in p or not p.get("resolved")) for p in kilit["packages"].values())
    yayim = (SCRIPTS / "canli_yayimla.sh").read_text(encoding="utf-8")
    assert not re.search("wrang" + "ler|npx|CLOUDFLARE|cf_yayin", yayim)                           # yazma kimlikli betik Cloudflare aracı çalıştırmaz
    wf = yukle("canli_vardiya.yml")
    metin_wf = (WF / "canli_vardiya.yml").read_text(encoding="utf-8")
    assert metin_wf.count("secrets.CLOUDFLARE_API_TOKEN") == 1 and metin_wf.count("secrets.CLOUDFLARE_ACCOUNT_ID") == 1
    assert "CLOUDFLARE" not in str(wf["jobs"]["vardiya"]) and "CLOUDFLARE" not in str(wf["jobs"]["zincir"]) and "CLOUDFLARE" not in str(wf["jobs"]["kontrol"])
    pano = wf["jobs"]["pano"]
    assert pano["permissions"] == {"contents": "read", "actions": "read"} and pano["needs"] == "kontrol" and "refs/heads/main" in pano["if"] and "atla != 'true'" in pano["if"]
    adim_ = adim(wf, "pano", "Pano yayını")
    assert adim_["run"] == "bash .github/scripts/pano_cf_yayimla.sh" and set(adim_["env"]) == {"CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "GH_TOKEN"}
    assert adim(wf, "pano", "kilit dosyasından kur")["run"] == "npm ci --prefix .github/pano --ignore-scripts --no-audit --no-fund"
    assert "env -u YAYIM_TOKEN python -u -m copytrade.canli.motor" in adim(wf, "vardiya", "Canlı motor")["run"]          # motor süreci push kimliğini görmez


def _pano_kos(tmp_path: Path, durumlar: list[str], htmller: list[str], wrangler_cikis: int = 0, cf: bool = True):
    """pano_cf_yayimla.sh'yi sahte gh + sahte wrangler ile koşturur. `durumlar`/`htmller`: sırayla her turda gh'nin döndürdüğü vardiya iş durumu / pano içeriği."""
    bin_ = tmp_path / "bin"
    bin_.mkdir(parents=True)
    (tmp_path / "durumlar").write_text("\n".join(durumlar) + "\n")
    (tmp_path / "htmller").write_text("\n".join(htmller) + "\n")
    (bin_ / "gh").write_text(f'''#!/usr/bin/env bash
echo "$@" >> "{tmp_path}/gh.txt"
case "$*" in
  *"/jobs"*) f="{tmp_path}/durumlar" ;;
  *) f="{tmp_path}/htmller" ;;
esac
satir="$(head -n1 "$f")"; [ "$(wc -l < "$f")" -gt 1 ] && sed -i 1d "$f"
[ "$satir" = HATA ] && exit 1
printf '%s' "$satir"
''', encoding="utf-8")
    (bin_ / "wrangler").write_text(f'#!/usr/bin/env bash\necho "$PWD $* $(cat site/index.html)" >> "{tmp_path}/wrangler.txt"\nexit {wrangler_cikis}\n', encoding="utf-8")
    for b in ("gh", "wrangler"):
        (bin_ / b).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "42", "PANO_ARALIK_SN": "0",
           "WRANGLER": str(bin_ / "wrangler"), "CLOUDFLARE_API_TOKEN": "CFTOK" if cf else "", "CLOUDFLARE_ACCOUNT_ID": "ACC" if cf else ""}
    r = subprocess.run(["bash", str(SCRIPTS / "pano_cf_yayimla.sh")], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    oku = lambda ad: (tmp_path / ad).read_text(encoding="utf-8").splitlines() if (tmp_path / ad).exists() else []
    return r, oku("gh.txt"), oku("wrangler.txt")


def test_g23_pano_isi_yalniz_degisince_yayimlar_vardiya_bitince_son_kez_yayimlayip_biter(tmp_path):
    """Tur 1: in_progress, <a> → yayım; tur 2: in_progress, <a> (aynı) → yayım YOK; tur 3: completed, <b> → son yayım ve çıkış 0."""
    r, gh, wr = _pano_kos(tmp_path, ["in_progress", "in_progress", "completed"], ["<a>", "<a>", "<b>"])
    assert r.returncode == 0, r.stderr
    assert [s.split()[-1] for s in wr] == ["<a>", "<b>"] and all("deploy --assets=site --name sg-pano --compatibility-date=2026-11-01" in s for s in wr)
    assert "repos/o/r/actions/runs/42/jobs" in gh[0] and "contents/pano/index.html?ref=canli-durum" in gh[1]       # durum ÖNCE, içerik SONRA (son içerik vardiya bittikten sonra okunur)
    assert "CFTOK" not in r.stdout + r.stderr and "vardiya işi bitti" in r.stdout


def test_g23_pano_isi_hata_gorunur_ama_kirmizi_degil_secret_yoksa_hic_yayimlamaz(tmp_path):
    r, gh, wr = _pano_kos(tmp_path / "a", ["completed"], ["<a>"], wrangler_cikis=1)
    assert r.returncode == 0 and len(wr) == 1 and "::warning::UYARI: Cloudflare pano yayını başarısız" in r.stdout
    r, gh, wr = _pano_kos(tmp_path / "b", ["HATA", "completed"], ["HATA", "<c>"])                     # gh okunamadı → sonraki turda yeniden dener
    assert r.returncode == 0 and [s.split()[-1] for s in wr] == ["<c>"] and "okunamadı" in r.stdout
    r, gh, wr = _pano_kos(tmp_path / "c", ["completed"], ["<a>"], cf=False)
    assert r.returncode == 0 and gh == [] and wr == [] and "secret'ları yok" in r.stdout


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
def _zincir_calistir(tmp_path: Path, gh_cikis: int, curl_cikis: int = 0, telegram: bool = False, yas_dk: int | None = 60, wf_adi: str = "canli_vardiya.yml", sonuc: str | None = None):
    """`zincir` işinin run: bloğunu sahte gh/curl ile gerçekten çalıştırır; (çıktı, gh çağrıları, curl çağrıları).
    `gh api …started_at` sahte yanıtı: yas_dk dakika önce (None = okunamaz, gh api başarısız). `gh api` çağrıları gh listesine yazılmaz (yalnız `workflow run`; api argümanları api.txt'ye).
    `sonuc`: VARDIYA_SONUC (needs.vardiya.result); None = tanımsız."""
    run = adim(yukle(wf_adi), "zincir", "tetikle")["run"]
    bin_ = tmp_path / "bin"
    bin_.mkdir(parents=True)
    for ad, cikis in (("gh", gh_cikis), ("curl", curl_cikis)):
        kayit = tmp_path / f"{ad}.txt"
        api = ""
        if ad == "gh":
            api = f'if [ "$1" = api ]; then echo "$@" >> "{tmp_path / "api.txt"}"; ' +('exit 1; ' if yas_dk is None else f'date -u -d "{yas_dk} minutes ago" +%Y-%m-%dT%H:%M:%SZ; exit 0; ') + 'fi\n'
        (bin_ / ad).write_text(f'#!/usr/bin/env bash\n{api}echo "$@" >> "{kayit}"\nexit {cikis}\n', encoding="utf-8")
        (bin_ / ad).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "RUN_URL": "http://x/run", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "1", "TELEGRAM_BOT_TOKEN": "TOK" if telegram else "", "TELEGRAM_CHAT_ID": "CH" if telegram else ""}
    env.pop("VARDIYA_SONUC", None)
    if sonuc is not None:
        env["VARDIYA_SONUC"] = sonuc
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
    # vardiya/kontrol: actions YAZMA yok (kontrol: O-2 yalnız okuma; A-2 (b) için actions: read). G-23: iş akışı düzeyi yalnız okuma, yazma yalnız vardiya işinde.
    assert wf["permissions"] == {"contents": "read"} and wf["jobs"]["kontrol"]["permissions"] == {"contents": "read", "actions": "read"} and wf["jobs"]["vardiya"]["permissions"] == {"contents": "write"}
    z = wf["jobs"]["zincir"]
    assert z["permissions"] == {"actions": "write", "contents": "read"} and metin.count("actions: write") == 1
    # Y-1 (denetim #3) + A-2 (c) (denetim 08.11): zincir vardiya başarısız ya da ZAMAN AŞIMI (`cancelled` sonucu) olsa da sürer; yalnız koşu kasıtlı iptal edildiyse (`cancelled()`) ya da vardiya atlandıysa çalışmaz.
    # always()/!cancelled() yasağı YALNIZ diğer işlerde kalır (zincir bilinçli istisna)
    assert z["needs"] == "vardiya" and z["if"] == "${{ !cancelled() && github.ref == 'refs/heads/main' && needs.vardiya.result != 'skipped' }}"
    assert "needs.vardiya.result != 'cancelled'" not in z["if"] and z["env"]["VARDIYA_SONUC"] == "${{ needs.vardiya.result }}"
    assert "failure()" not in z["if"] and "always()" not in str(wf["jobs"]["kontrol"].get("if", "")) and "always()" not in str(wf["jobs"]["vardiya"].get("if", ""))
    assert "cancelled()" not in str(wf["jobs"]["kontrol"].get("if", "")) and "cancelled()" not in str(wf["jobs"]["vardiya"].get("if", ""))
    assert wf["jobs"]["vardiya"]["env"]["TELEGRAM_KOMUT"] == "${{ vars.TELEGRAM_KOMUT }}"             # O-1: boş = komut alma açık
    assert "--canli-url" in adim(wf, "vardiya", "Canlı motor")["run"] and "copytrade.saglik" in adim(wf, "vardiya", "Canlı motor")["run"]
    assert all("uses" not in a for a in z["steps"])                                                    # checkout yok (kimlik bilgisi diske bırakılmaz)
    # vardiya işinde Actions token'ı YALNIZ yayım betiğine giden YAYIM_TOKEN olarak, yalnız iki adımda (G-23); GH_TOKEN (gh CLI) yok. kontrol: GH_TOKEN yalnız zamanlama adımında (salt okur izinler).
    assert "GH_TOKEN" not in str(wf["jobs"]["vardiya"]) and "github.token" not in str(wf["jobs"]["vardiya"].get("env", {}))
    jetonlu = [a.get("name") for a in wf["jobs"]["vardiya"]["steps"] if "github.token" in str(a)]
    assert jetonlu == ["Canlı motor (sanal kip)", "Durumu veri dalına yaz"]
    assert all(set(k for k, v in a.get("env", {}).items() if "github.token" in str(v)) <= {"YAYIM_TOKEN"} for a in wf["jobs"]["vardiya"]["steps"])
    assert [a.get("name") for a in wf["jobs"]["kontrol"]["steps"] if "github.token" in str(a)] == ["Zamanlama kontrolü (yedek cron)"]
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


def test_a2_zincir_zaman_asimi_iptalinde_de_tetikler_ve_alarm_verir(tmp_path):
    """A-2 (c): vardiya işi `cancelled` (zaman aşımı; koşu iptal edilmedi) → zincir sonrakini YİNE tetikler; ::warning + Telegram alarmı (token yazdırılmaz)."""
    r, gh, curl = _zincir_calistir(tmp_path, 0, telegram=True, yas_dk=290, sonuc="cancelled")
    assert r.returncode == 0 and gh == ["workflow run canli_vardiya.yml --ref main", "workflow run saglik.yml --ref main"]
    assert "::warning::vardiya işi 'cancelled'" in r.stdout and len(curl) == 1 and "iptal" in curl[0] and "TOK" not in r.stdout + r.stderr


def test_a2_zincir_basarisiz_vardiyada_iz_birakir_cift_alarm_yok_basarida_sessiz(tmp_path):
    r, gh, curl = _zincir_calistir(tmp_path / "f", 0, telegram=True, sonuc="failure")
    assert r.returncode == 0 and len(gh) == 2 and "::warning::vardiya işi 'failure'" in r.stdout and curl == []     # başarısızlık alarmı vardiya işinin kendi adımında
    r, gh, curl = _zincir_calistir(tmp_path / "s", 0, telegram=True, sonuc="success")
    assert r.returncode == 0 and len(gh) == 2 and "vardiya işi '" not in r.stdout and curl == []


def test_s20_zincir_yasi_kosunun_degil_vardiya_isinin_baslangicindan(tmp_path):
    """S-20: yaş `run_started_at` (kuyruk beklemesi dahil) ile DEĞİL, vardiya işinin `started_at`'i ile ölçülür."""
    r, gh, curl = _zincir_calistir(tmp_path, 0, yas_dk=30)
    api = (tmp_path / "api.txt").read_text(encoding="utf-8")
    assert r.returncode == 0 and "repos/o/r/actions/runs/1/jobs" in api and '.name == "vardiya"' in api and "started_at" in api and "run_started_at" not in api
    assert "vardiya işi yaşı: 30 dk" in r.stdout


def _sure_kos(tmp_path: Path, girdi: str | None, donem: str | None = None) -> tuple[subprocess.CompletedProcess, str]:
    run = adim(yukle("canli_vardiya.yml"), "vardiya", "Vardiya süresi (sınırlı)")["run"]
    genv = tmp_path / "genv"
    genv.write_text("")
    env = {k: v for k, v in os.environ.items() if k not in ("GIRDI_SURE_DK", "DONEM_SURE_DK")}
    env["GITHUB_ENV"] = str(genv)
    if girdi is not None:
        env["GIRDI_SURE_DK"] = girdi
    if donem is not None:
        env["DONEM_SURE_DK"] = donem
    r = subprocess.run(["bash", "-euo", "pipefail", "-c", run], env=env, capture_output=True, text=True)
    return r, genv.read_text()


@pytest.mark.parametrize("girdi, beklenen", [
    (None, 255), ("", 255), ("abc", 255), ("255", 255), ("120", 120), ("0120", 120),          # varsayılan / sayı değil / normal / baştaki sıfır (sekizlik sayılmaz)
    ("256", 255), ("9999", 255), ("123456789012345678901234567890", 255),                   # S-20: üst sınır (taşma yok)
    ("0", 1), ("20", 20),                                                                    # alt sınır 1; donem_geri.sh'ın en küçük kalanı (20) korunur
])
def test_s20_vardiya_suresi_ust_sinirli(tmp_path, girdi, beklenen):
    r, genv = _sure_kos(tmp_path, girdi)
    assert r.returncode == 0, r.stderr
    assert genv == f"SURE_DK={beklenen}\n"
    assert ("::warning::" in r.stdout) == (girdi is not None and girdi.isdigit() and int(girdi) > 255)


def test_s20_donem_kalan_butcesi_is_duzeyi_girdiden_once_gelir(tmp_path):
    """donem_geri.sh dönem başlangıcını bekleyince kalan bütçeyi DONEM_SURE_DK'ya da yazar; iş düzeyi `env: GIRDI_SURE_DK` (255) onu gölgeleyemez."""
    r, genv = _sure_kos(tmp_path, "255", donem="140")
    assert r.returncode == 0 and genv == "SURE_DK=140\n"
    r, genv = _sure_kos(tmp_path, "255", donem="999")
    assert genv == "SURE_DK=255\n"


def test_s20_motor_sinirli_sureyi_kullanir():
    run = adim(yukle("canli_vardiya.yml"), "vardiya", "Canlı motor")["run"]
    assert 'sure_dk="${SURE_DK:-255}"' in run and "GIRDI_SURE_DK" not in run and '--sure-sn "$((sure_dk * 60))"' in run


def test_s18_motor_adimi_arka_plan_yayimini_kesmeden_bekler(tmp_path):
    """S-18: motor bitince döngü dur dosyası + `sleep` çocuğu öldürülerek durdurulur ve `wait` ile beklenir; motorun çıkış kodu korunur, adım asılı kalmaz (sahte python/yayım)."""
    run = adim(yukle("canli_vardiya.yml"), "vardiya", "Canlı motor")["run"]
    assert 'wait "$yayim"' in run and 'touch "$yayim_dur"' in run and 'pkill -P "$yayim" -x sleep' in run and "kill -9" not in run
    assert run.index("cikis=$?") < run.index('touch "$yayim_dur"') < run.index('wait "$yayim"') < run.index('exit "$cikis"')
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "python").write_text(f'#!/usr/bin/env bash\necho "$@" >> "{tmp_path}/python.txt"\n[ -z "${{YAYIM_TOKEN:-}}" ] || echo TOKEN_SIZDI >> "{tmp_path}/python.txt"\nexit 3\n', encoding="utf-8")
    (bin_ / "python").chmod(0o755)
    (tmp_path / ".github/scripts").mkdir(parents=True)
    (tmp_path / ".github/scripts/canli_yayimla.sh").write_text(f'echo yayim >> "{tmp_path}/yayim.txt"\n', encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "SURE_DK": "1", "KADRO_DALI": "radar", "GITHUB_RUN_ID": "7", "GITHUB_REF": "refs/heads/x",
           "RUNNER_TEMP": str(tmp_path), "YAYIM_TOKEN": "GIZLI"}
    import time as _t
    t0 = _t.monotonic()
    r = subprocess.run(["bash", "-euo", "pipefail", "-c", run], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 3 and _t.monotonic() - t0 < 30                                          # motorun çıkış kodu; 900 sn uykuda asılı kalmaz
    cagri = (tmp_path / "python.txt").read_text()
    assert "--kip sanal" in cagri and "--sure-sn 60" in cagri and "--vardiya 7" in cagri and "TOKEN_SIZDI" not in cagri    # motor push kimliğini görmez
    assert "arka plan yayım döngüsü bitti" in r.stdout and "GIZLI" not in r.stdout + r.stderr
    assert not (tmp_path / "yayim.txt").exists()                                                   # 15 dk dolmadan yayım yok; son yayım ayrı adımda


def test_s18_yayim_betigi_tek_yazar_kilidi_flock(tmp_path):
    """S-18: canli_yayimla.sh kilidi başka bir yayım tutarken bekler; tavanı aşınca GÖRÜNÜR hata ile çıkar (sessiz çakışma yok)."""
    metin = (SCRIPTS / "canli_yayimla.sh").read_text(encoding="utf-8")
    assert 'exec 9>"$kilit_dosyasi"' in metin and 'flock -w "${YAYIM_KILIT_SN:-600}" 9' in metin
    assert metin.index("flock -w") < metin.index('git worktree add')                                # kilit, veri dalına dokunmadan ÖNCE
    kilit = tmp_path / "yayim.lock"
    tutucu = subprocess.Popen(["flock", str(kilit), "sleep", "20"], start_new_session=True)       # flock + sleep (kilit fd'si) birlikte öldürülsün
    try:
        import time as _t
        for _ in range(50):
            if subprocess.run(["flock", "-n", str(kilit), "true"]).returncode != 0:
                break
            _t.sleep(0.1)
        env = {**os.environ, "GITHUB_ACTIONS": "true", "VERI_DALI": "canli-durum", "YAYIM_KILIT": str(kilit), "YAYIM_KILIT_SN": "1"}
        r = subprocess.run(["bash", str(SCRIPTS / "canli_yayimla.sh")], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 1 and "yayım kilidi 1 sn'de alınamadı" in r.stderr
    finally:
        import signal
        os.killpg(tutucu.pid, signal.SIGKILL)
        tutucu.wait()
    r = subprocess.run(["bash", str(SCRIPTS / "canli_yayimla.sh")], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "yayımlanacak bir şey yok" in r.stdout                           # kilit boşalınca normal akış (durum/ yok → çıkış 0)


# ---------------------------------------------------------------------------------------------------- G-23: yazma kimliği yalnız yayım betiğinde; eylemler SHA ile sabit
def test_g23_canli_vardiya_checkoutlari_kimlik_birakmaz():
    wf = yukle("canli_vardiya.yml")
    for is_adi, is_ in wf["jobs"].items():
        for a in is_["steps"]:
            if str(a.get("uses", "")).startswith("actions/checkout@"):
                assert a["with"]["persist-credentials"] is False, is_adi
    assert all("uses" not in a for a in wf["jobs"]["zincir"]["steps"])


def test_g23_yayim_betigi_token_i_yalniz_git_ortamina_koyar_diske_ve_ciktiya_yazmaz(tmp_path):
    """YAYIM_TOKEN → yalnız betiğin git süreçleri için GIT_CONFIG_* `http.https://github.com/.extraheader` (actions/checkout biçimi); .git/config'e yazılmaz, çıktıya basılmaz, pano (python) görmez."""
    import base64
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare")
    co = _canli_checkout(tmp_path, remote, "co", "2026-01-02T00:00:00Z")
    (co / "durum").mkdir()
    (co / "durum" / "hesap.json").write_text("{}")
    (co / "durum" / "ozet.json").write_text("{}")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    gercek_git = subprocess.run(["bash", "-c", "command -v git"], capture_output=True, text=True).stdout.strip()
    (bin_ / "git").write_text(f'#!/usr/bin/env bash\necho "${{GIT_CONFIG_KEY_0:-yok}}|${{GIT_CONFIG_VALUE_0:-yok}}" >> "{tmp_path}/git_env.txt"\nexec {gercek_git} "$@"\n', encoding="utf-8")
    (bin_ / "python").write_text(f'#!/usr/bin/env bash\necho "${{GIT_CONFIG_VALUE_0:-yok}}|${{YAYIM_TOKEN:-yok}}" >> "{tmp_path}/python_env.txt"\nexit 0\n', encoding="utf-8")
    for b in ("git", "python"):
        (bin_ / b).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "GITHUB_ACTIONS": "true", "VERI_DALI": "canli-durum", "YAYIM_TOKEN": "GIZLI123", "YAYIM_KILIT": str(tmp_path / "k.lock")}
    r = subprocess.run(["bash", str(SCRIPTS / "canli_yayimla.sh")], cwd=co, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    beklenen = "http.https://github.com/.extraheader|AUTHORIZATION: basic " + base64.b64encode(b"x-access-token:GIZLI123").decode()
    git_env = (tmp_path / "git_env.txt").read_text().splitlines()
    assert git_env and all(s == beklenen for s in git_env)                                        # betiğin her git çağrısı kimlikli
    assert (tmp_path / "python_env.txt").read_text().splitlines() == ["yok|yok"]                   # pano üretimi kimliği görmez
    assert "GIZLI123" not in r.stdout + r.stderr and "GIZLI123" not in (co / ".git" / "config").read_text()
    assert base64.b64encode(b"x-access-token:GIZLI123").decode() not in (co / ".git" / "config").read_text() + r.stdout + r.stderr
    assert _git(remote, "show", "canli-durum:durum/hesap.json") == "{}"


def test_g23_radar_yazma_yalniz_radar_isinde_token_yalniz_yayim_adiminda():
    """G-23 (canli_vardiya.yml deseni): iş akışı düzeyi okuma; kontrol işi okuma; yazma yalnız `radar` işinde. Actions token'ı yalnız `Veri dalına yaz` adımına
    `YAYIM_TOKEN` olarak gider; tarama/kadro/isabet (python) adımları ve iş düzeyi ortam token görmez."""
    wf = yukle("radar.yml")
    assert wf["permissions"] == {"contents": "read"}
    assert wf["jobs"]["kontrol"]["permissions"] == {"contents": "read"} and wf["jobs"]["radar"]["permissions"] == {"contents": "write"}
    for is_adi, is_ in wf["jobs"].items():
        assert "github.token" not in str(is_.get("env", {})) and "secrets." not in str(is_.get("env", {})), is_adi
        for a in is_["steps"]:
            tokenli = {k for k, v in a.get("env", {}).items() if "github.token" in str(v) or "secrets." in str(v)}
            if a.get("name") == "Veri dalına yaz (radar)":
                assert tokenli == {"YAYIM_TOKEN"} and a["run"] == "bash .github/scripts/radar_yayimla.sh"
            else:
                assert not tokenli and "github.token" not in str(a) and "YAYIM_TOKEN" not in str(a), (is_adi, a)
    metin = (WF / "radar.yml").read_text(encoding="utf-8")
    assert metin.count("github.token") == 1 and "secrets." not in metin


@pytest.mark.parametrize("ad", sorted(p.name for p in WF.glob("*.yml")))
def test_g23_tum_is_akislarinda_checkout_kimlik_birakmaz(ad):
    """G-23: hiçbir iş akışının checkout'u token'ı .git/config'e yazmaz (`persist-credentials: false`); veri dalı push'u yalnız yayım betiğinin GIT_CONFIG_* ortamıyla."""
    wf = yukle(ad)
    sayi = 0
    for is_adi, is_ in wf["jobs"].items():
        for a in is_.get("steps", []):
            if str(a.get("uses", "")).startswith("actions/checkout@"):
                sayi += 1
                assert (a.get("with") or {}).get("persist-credentials") is False, (ad, is_adi)
    assert sayi == (WF / ad).read_text(encoding="utf-8").count("actions/checkout@")


@pytest.mark.parametrize("ad", ("saglik.yml", "ci.yml"))
def test_g23_salt_okur_is_akislari_yazma_izni_almaz(ad):
    """Sağlık/CI iş akışları yalnız okur: iş akışı düzeyi `contents: read`, hiçbir iş yazma izni almaz, push yok."""
    wf = yukle(ad)
    assert wf["permissions"] == {"contents": "read"}, ad
    for is_adi, is_ in wf["jobs"].items():
        assert "write" not in str(is_.get("permissions", {})), (ad, is_adi)
    assert "git push" not in (WF / ad).read_text(encoding="utf-8") and "github.token" not in (WF / ad).read_text(encoding="utf-8")


def test_g23_radar_yayim_betigi_token_i_yalniz_git_ortamina_koyar_diske_ve_ciktiya_yazmaz(tmp_path):
    """radar_yayimla.sh: YAYIM_TOKEN → yalnız betiğin git süreçleri için GIT_CONFIG_* `http.https://github.com/.extraheader`; .git/config'e yazılmaz, çıktıya basılmaz,
    betiğin kendisi python çalıştırmaz. Yayım davranışı (radar dalına havuz/kadro) aynı."""
    import base64
    import datetime as dt
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare")
    gun = dt.datetime.now(dt.UTC).date().isoformat()
    co = tmp_path / "co"
    co.mkdir()
    _git(co, "init", "-q")
    _git(co, "config", "user.name", "Test")
    _git(co, "config", "user.email", "test@example.com")
    _git(co, "remote", "add", "origin", str(remote))
    (co / "kaynak.py").write_text("kaynak")
    _git(co, "add", ".")
    _git(co, "commit", "-qm", "kaynak")
    (co / "radar" / gun).mkdir(parents=True)
    for ad in ("havuz", "kadro"):
        (co / "radar" / gun / f"{ad}.json").write_text(json.dumps({"sema": f"radar-{ad}-v1", "kosu_ms": 1, "satirlar": []}))
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    gercek_git = subprocess.run(["bash", "-c", "command -v git"], capture_output=True, text=True).stdout.strip()
    (bin_ / "git").write_text(f'#!/usr/bin/env bash\necho "${{GIT_CONFIG_KEY_0:-yok}}|${{GIT_CONFIG_VALUE_0:-yok}}|${{YAYIM_TOKEN:-yok}}" >> "{tmp_path}/git_env.txt"\nexec {gercek_git} "$@"\n', encoding="utf-8")
    (bin_ / "python").write_text(f'#!/usr/bin/env bash\necho cagrildi >> "{tmp_path}/python.txt"\nexit 0\n', encoding="utf-8")
    for b in ("git", "python"):
        (bin_ / b).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "GITHUB_ACTIONS": "true", "VERI_DALI": "radar", "YAYIM_TOKEN": "GIZLI456"}
    r = subprocess.run(["bash", str(SCRIPTS / "radar_yayimla.sh")], cwd=co, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    beklenen = "http.https://github.com/.extraheader|AUTHORIZATION: basic " + base64.b64encode(b"x-access-token:GIZLI456").decode() + "|yok"
    git_env = (tmp_path / "git_env.txt").read_text().splitlines()
    assert git_env and all(s == beklenen for s in git_env)                                        # her git çağrısı kimlikli; ham YAYIM_TOKEN alt süreçlere geçmez
    assert not (tmp_path / "python.txt").exists()
    gizli = ("GIZLI456", base64.b64encode(b"x-access-token:GIZLI456").decode())
    assert not any(g in r.stdout + r.stderr + (co / ".git" / "config").read_text() for g in gizli)
    assert _dal_json(remote, f"radar/{gun}/kadro.json")["kosu_ms"] == 1 and _dal_json(remote, "radar/son/kadro.json")["kosu_ms"] == 1


def test_ci_ruff_sabit_surumle_yalniz_hata_kurallari_ve_testten_once():
    """CI test işi `ruff check` koşar: sürüm sabit (==), requirements.txt'te değil; ruff.toml yalnız F + E9 seçer."""
    ci = yukle("ci.yml")
    ad = adimlar(ci, "test")
    ruff = adim(ci, "test", "Ruff check")["run"]
    assert re.search(r"pip install ruff==\d+\.\d+\.\d+\b", ruff) and "ruff check ." in ruff and "|| true" not in ruff
    assert ad.index("Ruff check (yalnız F + E9; ruff.toml)") < ad.index("Run unit and specification tests")
    assert "ruff" not in (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    import tomllib
    ayar = tomllib.loads((ROOT / "ruff.toml").read_text(encoding="utf-8"))
    assert ayar["lint"]["select"] == ["F", "E9"]


def test_requirements_kullanilmayan_paketleri_icermez():
    """09.11 temizlik: içe aktarılmayan paketler (yfinance, pynescript, antlr4, duckdb, pyarrow) requirements.txt'ten çıkarıldı; geri gelmez."""
    paketler = {s.split("==")[0].strip().lower() for s in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if s.strip() and not s.startswith("#")}
    assert paketler == {"pandas", "pytest", "requests", "pyyaml", "websockets"}          # websockets önce yfinance üzerinden dolaylı geliyordu; dinleyici/hl_public_adapter kullanır, açıkça sabitlendi (requirements-canli ile aynı sürüm)


def test_g23_ucuncu_taraf_eylemler_tam_commit_sha_ile_sabit():
    """G-23: tüm iş akışlarında `uses:` tam 40 haneli commit SHA + sürüm yorumu (git ls-remote ile çözüldü, 08.11)."""
    bilinen = {"actions/checkout": ("11d5960a326750d5838078e36cf38b85af677262", "v4.4.0"), "actions/setup-python": ("a26af69be951a213d495a4c3e4e4022e16d87065", "v5.6.0"),
               "actions/upload-artifact": ("ea165f8d65b6e75b540449e92b4886f43607fa02", "v4.6.2"), "actions/setup-node": ("49933ea5288caeca8642d1e84afbd3f7d6820020", "v4.4.0")}
    sayi = 0
    for yol in WF.glob("*.yml"):
        for satir in yol.read_text(encoding="utf-8").splitlines():
            m_ = re.match(r"\s*(?:-\s+)?uses:\s*(\S+)@(\S+)(?:\s+#\s*(\S+))?\s*$", satir)
            if not m_:
                continue
            sayi += 1
            eylem, ref, yorum = m_.groups()
            assert re.fullmatch(r"[0-9a-f]{40}", ref) and yorum, (yol.name, satir)
            assert bilinen[eylem] == (ref, yorum), (yol.name, satir)
    assert sayi >= 19 and sayi == sum(t.count("uses:") for t in (y.read_text(encoding="utf-8") for y in WF.glob("*.yml")))   # her `uses:` satırı yakalandı (08.11: 5 deneme iş akışı silindi, 30 → 25; K-66 14.11: 5 iş akışı daha silindi → 19)


def test_s19_radar_concurrency_ref_e_bagli():
    wf = yukle("radar.yml")
    assert wf["concurrency"] == {"group": "${{ github.ref == 'refs/heads/main' && 'radar' || format('radar-deneme-{0}', github.ref_name) }}", "cancel-in-progress": False}
    for ad in ("radar.yml", "canli_vardiya.yml"):
        assert "github.ref" in str(yukle(ad)["concurrency"]["group"]), ad                           # dal push'u üretim kuyruğunu yerinden edemez


# ---------------------------------------------------------------------------------------------------- 300 $ paralel seri KALDIRILDI (kullanıcı 08.11: tek sanal motor, 1.000 $)
def test_300_paralel_seri_kaldirildi_tek_sanal_motor():
    assert not (WF / "canli_vardiya_300.yml").exists() and not (ROOT / "copytrade/canli/CALISTIR_300").exists()
    assert "canli-durum-300" not in (SCRIPTS / "canli_yayimla.sh").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- dönem sıfırlama (kullanıcı kararı 08.11: 09.11 00:01 TSİ sıfırdan)
def _canli_checkout(tmp_path: Path, remote: Path, ad: str, donem: str) -> Path:
    co = tmp_path / ad
    (co / "copytrade" / "canli").mkdir(parents=True)
    _git(co, "init", "-q")
    _git(co, "config", "user.name", "Test")
    _git(co, "config", "user.email", "test@example.com")
    _git(co, "remote", "add", "origin", str(remote))
    (co / "copytrade" / "canli" / "DONEM").write_text(donem + "\n")
    _git(co, "add", ".")
    _git(co, "commit", "-qm", "kaynak")
    return co


def _kos(co: Path, betik: str, **ek) -> subprocess.CompletedProcess:
    env = {**os.environ, "GITHUB_ACTIONS": "true", "VERI_DALI": "canli-durum", "GITHUB_ENV": str(co / "genv"), **ek}
    return subprocess.run(["bash", str(SCRIPTS / betik)], cwd=co, env=env, capture_output=True, text=True)


def test_donem_yeni_donemde_eski_durum_yuklenmez_ve_dal_ucundan_silinir_ayni_donemde_devam(tmp_path):
    """Eski dönem (donem.txt yok) → donem_geri.sh hiçbir şey yüklemez, durum/donem.txt yazar; ilk yayım eski durum/kayıt/pano'yu dal ucundan siler (geçmişte kalır).
    Sonraki koşu aynı dönemde → durum ve kayıt geri yüklenir (normal devam)."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare")
    eski = _canli_checkout(tmp_path, remote, "eski", "2026-01-01T00:00:00Z")          # eski dönemin verisini dala koy (donem.txt olmadan: eski kod)
    _git(eski, "checkout", "-q", "--orphan", "canli-durum")
    _git(eski, "rm", "-rqf", ".")
    for yol, icerik in {"durum/hesap.json": '{"eski": 1}', "durum/saha.json": '{"uyeler": {"0xeski": {}}}', "kayit/2026-11-05.jsonl": "{}\n", "pano/gecmis.json": "[1]"}.items():
        (eski / yol).parent.mkdir(parents=True, exist_ok=True)
        (eski / yol).write_text(icerik)
    _git(eski, "add", "-f", "durum", "kayit", "pano")
    _git(eski, "commit", "-qm", "eski donem")
    _git(eski, "push", "-q", "origin", "canli-durum")
    yeni = _canli_checkout(tmp_path, remote, "yeni", "2026-01-02T00:00:00Z")           # geçmişte: bekleme yok
    s = _kos(yeni, "donem_geri.sh")
    assert s.returncode == 0, s.stderr
    assert "YENİ DÖNEM" in s.stdout and sorted(p.name for p in (yeni / "durum").iterdir()) == ["donem.txt"] and not any((yeni / "kayit").iterdir()) and not (yeni / "pano").exists()
    (yeni / "durum" / "hesap.json").write_text('{"yeni": 1}')
    import datetime as dt
    bugun = dt.datetime.now(dt.UTC).date().isoformat()                                                       # 14 günlük kayıt silmesine takılmasın
    (yeni / "kayit" / f"{bugun}.jsonl").write_text("{}\n")
    s = _kos(yeni, "canli_yayimla.sh")
    assert s.returncode == 0, s.stderr
    uc = _git(remote, "ls-tree", "-r", "--name-only", "canli-durum").splitlines()
    assert sorted(uc) == ["durum/donem.txt", "durum/hesap.json", f"kayit/{bugun}.jsonl"]                    # eski saha, kayıt, pano dal ucundan silindi
    assert _git(remote, "show", "canli-durum~1:durum/saha.json") == '{"uyeler": {"0xeski": {}}}'            # geçmişte arşivli
    devam = _canli_checkout(tmp_path, remote, "devam", "2026-01-02T00:00:00Z")
    s = _kos(devam, "donem_geri.sh")
    assert s.returncode == 0 and "YENİ DÖNEM" not in s.stdout
    assert (devam / "durum" / "hesap.json").read_text() == '{"yeni": 1}' and (devam / "kayit" / f"{bugun}.jsonl").exists()


def test_donem_baslangicindan_once_bekler_ve_motor_suresini_kisaltir_cok_uzaksa_hata(tmp_path):
    import datetime as dt
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare")
    yakin = (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    co = _canli_checkout(tmp_path, remote, "yakin", yakin)
    s = _kos(co, "donem_geri.sh")
    assert s.returncode == 0, s.stderr
    assert "bekleniyor" in s.stdout and "GIRDI_SURE_DK=250" in (co / "genv").read_text()                       # 255 − 0 dk − 5 pay
    assert "DONEM_SURE_DK=250" in (co / "genv").read_text()                                                     # S-20: süre adımı bu adı önce okur
    uzak = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    co2 = _canli_checkout(tmp_path, remote, "uzak", uzak)
    s = _kos(co2, "donem_geri.sh")
    assert s.returncode == 1 and "230 dk" in s.stderr


def test_motor_adimi_once_donem_suresini_okur():
    """İş düzeyi `env: GIRDI_SURE_DK` GITHUB_ENV'deki kısaltılmış süreyi ezebilir: motor adımı önce DONEM_SURE_DK'yı okur (bekleme + 255 dk > 290 dk zaman aşımı olmasın)."""
    adim = [a for a in yukle("canli_vardiya.yml")["jobs"]["vardiya"]["steps"] if a.get("id") == "sure"][0]       # S-20: süre adımı (motor adımı SURE_DK'yı okur)
    assert 'sure_dk="${DONEM_SURE_DK:-${GIRDI_SURE_DK:-255}}"' in adim["run"]
    s = subprocess.run(["bash", "-c", 'GIRDI_SURE_DK=""; DONEM_SURE_DK=196; sure_dk="${DONEM_SURE_DK:-${GIRDI_SURE_DK:-255}}"; echo $sure_dk'], capture_output=True, text=True)
    assert s.stdout.strip() == "196"


def test_iki_canli_is_akisi_donem_betigini_kullanir():
    for ad in ("canli_vardiya.yml",):
        geri = [a for a in yukle(ad)["jobs"]["vardiya"]["steps"] if a.get("id") == "geri"][0]
        assert geri["run"].strip() == "bash .github/scripts/donem_geri.sh", ad
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n?", (ROOT / "copytrade" / "canli" / "DONEM").read_text())
