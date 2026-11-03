"""İş akışı kuralları (docs/ILK11_SECIM_SARTNAME.md §5.5a): YAML metni + çalışma davranışı. 870974e'de silinen iş akışı testlerinin kuralları yeniden kurulur."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pandas as pd
import pytest
import yaml

from copytrade import izleme_motoru as m
from copytrade.ilk11_deneme import hazirla, sec
from copytrade.kapi import read_universe_snapshot
from test_izleme import ADDRESS, NOW, Client, project

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows"
SCRIPTS = ROOT / ".github/scripts"
ISLER = ("copytrade_kapi.yml", "izleme.yml", "ilk11_pazar.yml", "ilk11_deneme.yml")


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
    hedef = {"copytrade_kapi.yml": None, "izleme.yml": None, "ilk11_pazar.yml": "copytrade-kapi", "ilk11_deneme.yml": None}
    for ad in ISLER:
        for satir in (WF / ad).read_text(encoding="utf-8").splitlines():
            if "git push" in satir:
                assert hedef[ad] and f"HEAD:{hedef[ad]}" in satir, (ad, satir)
    assert (WF / "ilk11_deneme.yml").read_text(encoding="utf-8").count("permissions:\n  contents: read") == 1          # deneme yazamaz
    for betik, dal in (("kapi_yayimla.sh", "copytrade-kapi"), ("izleme_yayimla.sh", "copytrade-izleme")):
        for satir in (SCRIPTS / betik).read_text(encoding="utf-8").splitlines():
            if "git push" in satir:
                assert f"HEAD:{dal}" in satir, (betik, satir)


def test_zamanlamalar_sartnameyle_ayni():
    assert yukle("copytrade_kapi.yml")["on"]["schedule"] == [{"cron": "43 18 * * 6"}] and "workflow_dispatch" in yukle("copytrade_kapi.yml")["on"]
    assert yukle("izleme.yml")["on"]["schedule"] == [{"cron": "23 * * * *"}]
    assert yukle("ilk11_pazar.yml")["on"]["schedule"] == [{"cron": "7 10-18/2 * * 0"}]
    assert yukle("izleme.yml")["concurrency"]["cancel-in-progress"] is False and yukle("ilk11_pazar.yml")["concurrency"]["cancel-in-progress"] is False
    toplam = sum(yukle("copytrade_kapi.yml")["jobs"][j]["timeout-minutes"] for j in ("plan", "stage1", "publish"))
    # A2-3b: plan `--evren-yaz` 10 dk'yı aştı (prefilter satır başına YAML okuyordu: 48 bin satır ≈ 1.054 sn). Düzeltmeden sonra saniyeler sürmeli; sınır ≥ 30 dk (ölçüm × 2'nin altına inmez).
    assert yukle("copytrade_kapi.yml")["jobs"]["plan"]["timeout-minutes"] == 30 and toplam == 30 + 120 + 90
    assert toplam <= 4 * 60 + 40 and yukle("copytrade_kapi.yml")["jobs"]["stage1"]["timeout-minutes"] <= 120 and yukle("copytrade_kapi.yml")["jobs"]["publish"]["timeout-minutes"] <= 90


def test_izleme_ilk_okuma_icin_timeout_300_dk_kuyruk_bekler():
    wf = yukle("izleme.yml")
    assert wf["jobs"]["izleme"]["timeout-minutes"] == 300 <= 360                               # 86 trader ilk okuma ≈ 192 dk (ölçüm); GitHub sınırı 360
    assert wf["concurrency"] == {"group": "copytrade-izleme", "cancel-in-progress": False}      # saatlik koşular uzun ilk koşunun arkasında bekler


def test_worker_telegram_adimlari_geri_gelmedi_k13():
    for ad in ISLER:
        metin = (WF / ad).read_text(encoding="utf-8")
        assert not re.search(r"KARAR_URL|GECIKME_URL|TELEGRAM|CLOUDFLARE|copytrade\.kararlar|copytrade\.gecikme|degisim_rapor", metin), ad


# ---------------------------------------------------------------------------------------------------- kapı: plan günü, eksik koşu
def test_plan_gunu_tum_parcalara_ve_birlestirmeye_aynen_gecer():
    metin = (WF / "copytrade_kapi.yml").read_text(encoding="utf-8")
    assert metin.count("date -u +%F") == 1                                                    # gün yalnız plan işinde seçilir
    wf = yukle("copytrade_kapi.yml")
    assert wf["jobs"]["plan"]["outputs"]["day"] == "${{ steps.p.outputs.day }}"
    kosu = adim(wf, "stage1", "Kapı koşusu")["run"]
    assert "--tarih ${{ needs.plan.outputs.day }}" in kosu and "--shard-count ${{ needs.plan.outputs.count }}" in kosu
    assert adim(wf, "publish", "Veri dalına yaz")["env"]["DAY"] == "${{ needs.plan.outputs.day }}"
    assert "copytrade/kapi/${{ needs.plan.outputs.day }}/durum.json" in adim(wf, "publish", "Birleştir")["run"]
    assert "--beklenen-parca ${{ needs.plan.outputs.count }}" in adim(wf, "publish", "Birleştir")["run"] and "--mod tam" in adim(wf, "publish", "Birleştir")["run"]


def test_eksik_kosu_kirmizi_biter_ama_kismi_sonuc_yazilir_kesif_ve_snapshot_uretilmez():
    wf = yukle("copytrade_kapi.yml")
    sira = adimlar(wf, "publish")
    yaz, kirmizi, kesif = (next(i for i, ad in enumerate(sira) if parca in ad) for parca in ("Veri dalına yaz", "Eksik koşu işi kırmızı", "Keşif verisi"))
    assert yaz < kirmizi                                                                        # önce kısmi sonuç yayımlanır, sonra iş kırmızı biter
    assert "exit 1" in adim(wf, "publish", "Eksik koşu işi kırmızı")["run"] and "steps.birlestir.outputs.durum == 'eksik'" in adim(wf, "publish", "Eksik koşu işi kırmızı")["if"]
    assert "!cancelled()" in adim(wf, "publish", "Veri dalına yaz")["if"] and "steps.birlestir.outcome == 'success'" in adim(wf, "publish", "Veri dalına yaz")["if"]
    assert adim(wf, "publish", "Keşif verisi")["if"] == "steps.birlestir.outputs.durum == 'tamam'"          # eksik koşudan kesif.json üretilmez
    assert "!cancelled()" in adim(wf, "publish", "Eksik koşu işi kırmızı")["if"]
    # İlk 11 snapshot'ı eksik koşudan üretilmez: Pazar işi yalnız `durum == tamam` kapı klasörünü kullanır (ilk11_pazar.kapi_sec; testi test_ilk11_pazar.py)
    assert "kapi_sec" in (ROOT / "copytrade/ilk11_pazar.py").read_text(encoding="utf-8")


def kapi_yayimla_calistir(kok: Path, gun: str, durum: str, kanca: str | None = None):
    uzak, calisma = kok / "uzak.git", kok / "calisma"
    if not uzak.exists():
        uzak.mkdir(); calisma.mkdir()
        for komut in (["init", "--bare", "-q"],):
            subprocess.run(["git", *komut], cwd=uzak, check=True)
        for komut in (["init", "-q"], ["config", "user.name", "T"], ["config", "user.email", "t@t"], ["remote", "add", "origin", str(uzak)]):
            subprocess.run(["git", *komut], cwd=calisma, check=True)
        (calisma / ".github/scripts").mkdir(parents=True)
        (calisma / ".github/scripts/son_yaz.py").write_bytes((SCRIPTS / "son_yaz.py").read_bytes())
        (calisma / "kaynak.py").write_text("main kodu veri dalına gitmez")
        subprocess.run(["git", "add", "."], cwd=calisma, check=True)
        subprocess.run(["git", "commit", "-qm", "kaynak"], cwd=calisma, check=True)
        (kok / "ana.txt").write_text(subprocess.run(["git", "branch", "--show-current"], cwd=calisma, capture_output=True, text=True, check=True).stdout.strip())
        if kanca:
            (uzak / "hooks/pre-receive").write_text(kanca)
            os.chmod(uzak / "hooks/pre-receive", 0o755)
    else:                                                                    # Actions'ta her koşu temiz checkout'tur: önceki koşunun veri dalından ana dala dön
        subprocess.run(["git", "checkout", "-fq", (kok / "ana.txt").read_text()], cwd=calisma, check=True)
    klasor = calisma / "copytrade/kapi" / gun
    klasor.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"address": "0xa", "katman": "yok"}]).to_csv(klasor / "sonuc.csv", index=False)
    (klasor / "durum.json").write_text(json.dumps({"durum": durum, "neden": "parça eksik" if durum == "eksik" else ""}))
    (klasor / "RAPOR.md").write_text(f"# rapor {gun}\n")
    return subprocess.run(["bash", str(SCRIPTS / "kapi_yayimla.sh")], cwd=calisma, capture_output=True, text=True,
                          env={**os.environ, "GITHUB_ACTIONS": "true", "DAY": gun, "MOD": "tam"}), uzak, calisma


def dal_dosyasi(uzak: Path, yol: str) -> str:
    return subprocess.run(["git", "show", f"copytrade-kapi:{yol}"], cwd=uzak, capture_output=True, text=True, check=True).stdout


def test_kapi_yayimci_eksik_kosunun_kismi_sonucunu_yazar_ve_main_e_dokunmaz(tmp_path):
    sonuc, uzak, _ = kapi_yayimla_calistir(tmp_path, "2026-11-07", "eksik")
    assert sonuc.returncode == 0, sonuc.stderr
    assert json.loads(dal_dosyasi(uzak, "copytrade/kapi/2026-11-07/durum.json"))["durum"] == "eksik"           # kısmi sonuç + durum yayımlandı
    assert "rapor 2026-11-07" in dal_dosyasi(uzak, "copytrade/kapi/2026-11-07/RAPOR.md")
    assert json.loads(dal_dosyasi(uzak, "son.json"))["kapi"] == "2026-11-07"
    refs = subprocess.run(["git", "for-each-ref", "--format=%(refname)"], cwd=uzak, capture_output=True, text=True, check=True).stdout.split()
    assert refs == ["refs/heads/copytrade-kapi"]                                                 # yalnız veri dalı; main yok
    assert not any("kaynak.py" in dosya for dosya in subprocess.run(["git", "ls-tree", "-r", "--name-only", "copytrade-kapi"], cwd=uzak, capture_output=True,
                                                                  text=True, check=True).stdout.split())


def test_kapi_yayimci_yazim_yarisinda_yeniden_dener_ve_oncekileri_korur(tmp_path):
    kanca = "#!/bin/sh\nif [ ! -f \"$GIT_DIR/ilk_ret\" ]; then touch \"$GIT_DIR/ilk_ret\"; echo 'yarış: reddedildi' >&2; exit 1; fi\n"
    birinci, uzak, calisma = kapi_yayimla_calistir(tmp_path, "2026-10-31", "tamam", kanca)
    assert birinci.returncode == 0, birinci.stderr                                                  # ilk itme reddedildi, ikinci deneme geçti
    assert (uzak / "ilk_ret").exists() and json.loads(dal_dosyasi(uzak, "copytrade/kapi/2026-10-31/durum.json"))["durum"] == "tamam"
    # başka yazar (Pazar işi) son.json'a `ilk11` ekledi; sonraki kapı yayını bu anahtarı korur
    diger = tmp_path / "diger"
    subprocess.run(["git", "clone", "-q", "-b", "copytrade-kapi", str(uzak), str(diger)], check=True)
    son = json.loads((diger / "son.json").read_text())
    (diger / "son.json").write_text(json.dumps({**son, "ilk11": {"tarih": "2026-11-01"}}))
    subprocess.run(["git", "-C", str(diger), "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-qam", "ilk11"], check=True)
    subprocess.run(["git", "-C", str(diger), "push", "-q", "origin", "HEAD:copytrade-kapi"], check=True)
    ikinci, _, _ = kapi_yayimla_calistir(tmp_path, "2026-11-07", "tamam")
    assert ikinci.returncode == 0, ikinci.stderr
    son = json.loads(dal_dosyasi(uzak, "son.json"))
    assert son["kapi"] == "2026-11-07" and son["ilk11"] == {"tarih": "2026-11-01"}
    assert json.loads(dal_dosyasi(uzak, "copytrade/kapi/2026-10-31/durum.json"))["durum"] == "tamam"       # eski gün silinmedi


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


def test_izleme_listesi_veri_dalindan_okunur_main_listesi_yedek():
    adim_ = adim(yukle("izleme.yml"), "izleme", "İlk 11 izleme listesi")["run"]
    assert "ilk11/izleme_listesi.yaml" in adim_
    kosu = adim(yukle("izleme.yml"), "izleme", "sanal defteri güncelle")["run"]
    assert "--liste ilk11_izleme_listesi.yaml" in kosu and "copytrade.izleme_motoru --root . --output izleme" in kosu
    assert adim(yukle("izleme.yml"), "izleme", "veri dalına yaz")["run"] == "bash .github/scripts/izleme_yayimla.sh"


# ---------------------------------------------------------------------------------------------------- Pazar iş akışı
def test_pazar_isi_dosyalari_yalniz_basari_kodlarinda_yazar_kod_2_kirmizi_biter():
    wf = yukle("ilk11_pazar.yml")
    sira = adimlar(wf, "pazar")
    yaz = next(i for i, ad in enumerate(sira) if "Veri dalına yaz" in ad)
    kirmizi = next(i for i, ad in enumerate(sira) if "kırmızı bitir" in ad)
    assert yaz < kirmizi
    assert adim(wf, "pazar", "Veri dalına yaz")["if"] == "${{ steps.pazar.outputs.kod == '0' || steps.pazar.outputs.kod == '2' }}"
    assert adim(wf, "pazar", "kırmızı bitir")["if"] == "${{ steps.pazar.outputs.kod == '2' }}" and "exit 1" in adim(wf, "pazar", "kırmızı bitir")["run"]
    calis = adim(wf, "pazar", "Pazar işi")["run"]
    assert "|| kod=$?" in calis and 'exit "$kod"' in calis and "0|2) ;;" in calis                        # hata örtülmez, 1 -> kırmızı
    yazim = adim(wf, "pazar", "Veri dalına yaz")["run"]
    assert "git pull --rebase origin copytrade-kapi" in yazim and "1 2 3 4 5" in yazim and '[ "$pushed" = 1 ]' in yazim
    assert "--taban-liste copytrade/izleme_listesi.yaml" in calis and "--izleme-dali izleme-dali" in calis
    assert [a for a in wf["jobs"]["pazar"]["steps"] if a.get("uses") == "actions/checkout@v4"][2]["with"]["fetch-depth"] == 0      # durum.json git geçmişi


# ---------------------------------------------------------------------------------------------------- deneme: secret varlık kontrolü yalnız adla
def secret_kontrolu(**ortam):
    wf = yukle("ilk11_deneme.yml")
    ilk = wf["jobs"]["deneme"]["steps"][0]
    assert "secret" in ilk["name"] and "uses" not in ilk                                         # ilk adım
    temiz = {k: v for k, v in os.environ.items() if not k.startswith("R2_")}
    return subprocess.run(["bash", "-euo", "pipefail", "-c", ilk["run"]], capture_output=True, text=True, env={**temiz, **ortam})


GIZLI = "cok-gizli-DEGER-123"
TUMU = {"R2_ACCESS_KEY_ID": GIZLI + "a", "R2_ACCOUNT_ID": GIZLI + "b", "R2_BUCKET": GIZLI + "c", "R2_SECRET_ACCESS_KEY": GIZLI + "d"}


def test_deneme_ilk_adimi_eksik_secret_adini_yazar_kirmizi_biter_degeri_asla_yazdirmaz():
    tam = secret_kontrolu(**TUMU)
    assert tam.returncode == 0 and GIZLI not in tam.stdout + tam.stderr
    for eksik in TUMU:
        sonuc = secret_kontrolu(**{k: v for k, v in TUMU.items() if k != eksik})
        assert sonuc.returncode == 1 and eksik in sonuc.stderr, eksik
        assert GIZLI not in sonuc.stdout + sonuc.stderr                                          # mevcut secret'ların değeri yazılmaz
        assert sum(ad in sonuc.stderr for ad in TUMU) == 1                                       # yalnız eksik olanın adı
    bos = secret_kontrolu(**{**TUMU, "R2_BUCKET": ""})
    assert bos.returncode == 1 and "R2_BUCKET" in bos.stderr                                     # boş değer = eksik
    assert set(yukle("ilk11_deneme.yml")["jobs"]["deneme"]["env"]) == set(TUMU)


def test_deneme_secret_kontrolu_kirmiziysa_ozet_ve_artifact_adimlari_calismaz():
    wf = yukle("ilk11_deneme.yml")
    adimlar_ = wf["jobs"]["deneme"]["steps"]
    assert adimlar_[0]["id"] == "secret"
    for a in adimlar_:
        if "always()" in str(a.get("if", "")):
            assert "steps.secret.outcome == 'success'" in a["if"], a                              # gürültülü ikincil hata yanıltmasın


def test_deneme_kendi_dalindan_tetiklenebilir_ve_uretime_yazmaz():
    wf = yukle("ilk11_deneme.yml")
    assert wf["on"]["push"] == {"paths": ["copytrade/ilk11_deneme/CALISTIR"]} and "workflow_dispatch" in wf["on"]
    assert (ROOT / "copytrade/ilk11_deneme/CALISTIR").exists() and wf["permissions"] == {"contents": "read"}
    metin = (WF / "ilk11_deneme.yml").read_text(encoding="utf-8")
    assert "s3 cp" not in metin and "git push" not in metin and "--deneme" in metin


# ---------------------------------------------------------------------------------------------------- artık dosya temizliği
def test_artik_dosyalar_temizlendi_ve_kalanlar_gercekten_kullaniliyor():
    assert not (ROOT / "copytrade/kapi/CALISTIR").exists() and not (ROOT / "copytrade/secim/CALISTIR").exists()      # hiçbir iş akışı tetiklemiyor
    metin = "".join((WF / a).read_text(encoding="utf-8") for a in ISLER)
    assert "copytrade/kapi/CALISTIR" not in metin and "copytrade/secim/CALISTIR" not in metin
    for betik in ("kapi_yayimla.sh", "izleme_yayimla.sh"):
        assert f".github/scripts/{betik}" in metin, betik                                        # kullanılan betik, testli (test_a14_baglantilar / test_izleme)
    assert ".github/scripts/son_yaz.py" in (SCRIPTS / "kapi_yayimla.sh").read_text(encoding="utf-8")            # son_yaz.py kapı yayımcısından çağrılır (test_son_json)


# ---------------------------------------------------------------------------------------------------- deneme adres seçimi
def aday(i, tarz, hesap, katman="izleme_adayi"):
    return {"address": f"0x{i:040x}", "tarz": tarz, "katman": katman, "hesap_degeri_bugun": hesap}


def tablo():
    satirlar = [aday(1, "intraday", 2_500_000), aday(2, "swing", 12_000), aday(3, "intraday", 80_000), aday(4, "intraday", 150_000, "kopyalanabilir"),
                aday(5, "swing", 90_000), aday(6, "swing", 400_000, "kopyalanabilir"), aday(7, "intraday", 300_000), aday(8, "swing", 200_000),
                aday(9, "intraday", 1_000, "yok"), aday(10, "scalp", 1_200_000)]
    return pd.DataFrame(satirlar)


def test_deneme_secimi_dagilim_ve_buyuk_kucuk_hesap():
    secilen = sec(tablo())
    assert len(secilen) == 5 and len({s["address"] for s in secilen}) == 5
    assert sum(s["tarz"] == "intraday" for s in secilen[:4]) == 2 and sum(s["tarz"] == "swing" for s in secilen[:4]) == 2
    assert max(s["hesap"] for s in secilen) >= 1_000_000 and min(s["hesap"] for s in secilen) < 50_000
    assert secilen[0]["address"] == f"0x{1:040x}" and secilen[1]["address"] == f"0x{2:040x}"            # en büyük / en küçük hesap
    assert secilen[4]["katman"] == "kopyalanabilir" and f"0x{9:040x}" not in {s["address"] for s in secilen}   # katman_yok ve scalp seçilmez
    assert sec(tablo().iloc[::-1]) == secilen                                                      # girdi sırasından bağımsız (deterministik)


def test_sure_tahmini_iki_sure_ayri_ve_butce_asimi_uyarisi():
    from copytrade.ilk11_deneme import sure_tahmini
    # 5 trader: ilk okuma 670 sn -> 134 sn/trader -> 86 trader ≈ 192 dk; artımlı 60 sn -> 12 sn/trader -> 86 trader ≈ 17 dk (bütçe içinde)
    ilk, artimli = sure_tahmini(5, 670, 60)
    assert "ilk okuma" in ilk and "≈ 192 dk" in ilk and "artımlı" in artimli and "≈ 17 dk" in artimli
    assert not any("UYARI" in x for x in sure_tahmini(5, 670, 60))
    # artımlı 200 sn -> 40 sn/trader -> 86 trader ≈ 57 dk > 55: açık uyarı
    assert any("UYARI" in x and "55 dk" in x for x in sure_tahmini(5, 670, 200))
    assert sure_tahmini(5, None, None) == ["- süre ölçülmedi"]


def test_deneme_secimi_yetersiz_aday_net_hata_verir():
    with pytest.raises(ValueError, match="hesap yok"):
        sec(tablo()[tablo()["hesap_degeri_bugun"] < 1_000_000])
    with pytest.raises(ValueError, match="kopyalanabilir"):
        sec(tablo().assign(katman="izleme_adayi"))


def test_deneme_hazirla_dosyalari_kapi_ve_izleme_formatinda_yazar(tmp_path):
    from datetime import UTC, datetime
    csv = tmp_path / "sonuc.csv"
    tablo().to_csv(csv, index=False)
    cikti = hazirla(csv, tmp_path / "deneme", datetime(2026, 11, 4, 12, 0, tzinfo=UTC))
    assert cikti["tarih"] == "2026-10-31"                                                         # son Pazar (11-01) − 1 gün: ilk11_pazar'ın kapı kuralına uyar
    liderler = read_universe_snapshot(tmp_path / "deneme/evren.json")
    assert len(liderler) == 5 and all(x["kaynak"] == "leaderboard" for x in liderler)             # dis_aday olsaydı yalniz_adim5 plaseboyu hesaplamazdı
    onceki = pd.read_csv(tmp_path / "deneme/onceki_sonuc.csv")
    assert set(onceki["address"]) == {x["address"] for x in liderler} and (onceki[["adim1", "adim2", "adim3", "adim4"]] == "Geçti").all().all()
    liste = m.load_list(tmp_path / "deneme/izleme_listesi.yaml")
    assert [r["id"] for r in liste] == ["D1", "D2", "D3", "D4", "D5"] and {r["t0"] for r in liste} == {"2026-10-05"}
    assert (tmp_path / "deneme/tarih.txt").read_text().strip() == "2026-10-31"
