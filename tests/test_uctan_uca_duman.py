"""K-80 uçtan uca DUMAN testi (ağ yok): sahte HL (REST `post` taklidi + trader olayları motora enjekte; `SahteHL`/`kur` fikstürleri) + sahte Telegram (`SahteTG`) + GERÇEK motor + GERÇEK yayım betiği
(`deploy/sanal_yayimla.sh`: yerel bare origin) + GERÇEK pano üretimi (`copytrade.canli.pano` → pano/index.html) + GERÇEK güncelleme kapısı (`deploy/sanal_guncelle.sh`: sahte git origin/systemctl/curl) birlikte.
Denetlenen: trader açılış / ara dolum / kapanış; durum dosyaları + pano/index.html üretimi ve veri dalına yayımı; radar dalı çekimi; Telegram saatlik özet TEK mesaj; CI kapısı + kurulum sonrası öz-denetim + güncelleme işareti;
işaret varken ölümcül olmayan uyarının bekletilmesi; 60 dk bekçi sorunsuz izleme. İşaret: `pytest -m uctan_uca` (normal suite'te de koşar; birkaç sn)."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from copytrade.canli import motor as mt
from tests.test_canli_motor import SAAT, adr, kayitlar, kur, olay
from tests.test_deploy_sanal import BEKCI, DEPLOY, ROOT, YESIL, git, sunucu  # noqa: F401  (sunucu: pytest fikstürü)

pytestmark = pytest.mark.uctan_uca
A = adr(1)


def _git_cikti(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _radar_dali(srv):
    """origin'e `radar` dalı (radar/son/kadro.json) ekler: yayım betiği her yayımda çeker (pano/sağlık eski kadroyu görmesin)."""
    tohum = srv.depo.parent / "tohum"
    git(tohum, "checkout", "-q", "-b", "radar")
    (tohum / "radar/son").mkdir(parents=True)
    (tohum / "radar/son/kadro.json").write_text(json.dumps({"sema": "radar-kadro-v1", "kosu_ms": 1, "satirlar": []}))
    git(tohum, "add", "-A")
    git(tohum, "commit", "-q", "-m", "radar kadro")
    git(tohum, "push", "-q", "origin", "radar")
    git(tohum, "checkout", "-q", "main")


def test_uctan_uca_motor_yayim_pano_guncelle_kapisi_telegram(sunucu):  # noqa: F811
    depo, bare = sunucu.depo, sunucu.depo.parent / "origin.git"
    _radar_dali(sunucu)
    (depo / "durum/motor.json").unlink()                                                              # fikstürün sahte yerel durumu: motor sıfırdan başlasın

    # ---- 1) motor: trader açılış + ara dolum + kapanış (sahte HL REST + sahte Telegram); durum dosyaları depo/durum'a yazılır
    m, hl, saat, tgp = kur(depo, kasa=1000.0)
    m.baslat()
    m.olay_isle(olay("a:1", A, "BTC", "B", 300, 100.0, 0.0, saat))                                    # açılış
    m.piyasa_oku(saat())
    saat.ms += 10_000
    m.piyasa_oku(saat())
    s = m.olay_isle(olay("a:2", A, "BTC", "B", 200, 100.0, 300.0, saat, yas_ms=0))                    # 1. ara dolum
    assert [(x.eylem, x.karar) for x in s] == [("artir", "emir")]
    saat.ms += 10_000
    m.piyasa_oku(saat())
    s = m.olay_isle(olay("a:3", A, "BTC", "A", 500, 100.0, 500.0, saat, yas_ms=0))                    # tam kapanış
    assert [(x.eylem, x.karar) for x in s] == [("kapat", "emir")] and abs(m.hesap.sz(A, "BTC")) < mt.EPS
    assert [e["eylem"] for e in kayitlar(depo, "emir")] == ["ac", "artir", "kapat"]

    # ---- 2) Telegram: işlem mesajı yok, saat dolunca TEK özet; uyarı anında
    ozetler = lambda: [x for x in tgp.gonderilen if x.startswith("🧾 Son ")]          # noqa: E731
    assert ozetler() == [] and not [x for x in tgp.gonderilen if " açıldı · trader " in x]
    saat.ms += SAAT
    m.emir_ozeti(saat())
    assert len(ozetler()) == 1 and "3 emir (1 açılış, 1 artırma, 1 kapanış)" in ozetler()[0], tgp.gonderilen
    m.emir_ozeti(saat() + SAAT)
    assert len(ozetler()) == 1                                                                         # ikinci mesaj yok

    # ---- 3) durum dosyaları (+ ozet.json: motor dakikada bir yazar) → yayım betiği → pano/index.html veri dalında
    m.durum_yaz()
    mt._yaz(m.durum_dizin / "ozet.json", {**m.ozet(), **m.pano_ek(), "yazildi_ms": m.saat_ms()})
    for ad in ("hesap.json", "motor.json", "risk.json", "ozet.json"):
        assert (depo / "durum" / ad).is_file(), ad
    env = {**sunucu.ortak, "SUNUCU_MOD": "uretim", "VERI_DALI": "canli-durum", "KADRO_DALI": "radar", "YAYIM_KILIT": str(depo.parent / "yayim.lock"), "PYTHON": sys.executable,
           "PYTHONPATH": str(ROOT), "VARDIYA_ID": m.vardiya_id}
    r = subprocess.run(["bash", str(DEPLOY / "sanal_yayimla.sh")], cwd=depo, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    dosyalar = set(_git_cikti(bare, "ls-tree", "-r", "--name-only", "canli-durum").split())
    assert {"durum/hesap.json", "durum/ozet.json", "durum/motor.json", "pano/index.html", "pano/OZET.md"} <= dosyalar, dosyalar
    assert any(d.startswith("kayit/") and d.endswith(".jsonl") for d in dosyalar)
    html = _git_cikti(bare, "show", "canli-durum:pano/index.html")
    assert 'id="bayat"' in html and "BTC" in html                                                      # pano üretildi ve veri zamanı işaretini taşıyor
    assert _git_cikti(depo, "rev-parse", "--verify", "refs/remotes/origin/radar").strip()             # radar dalı çekildi

    # ---- 4) güncelleme kapısı: kırmızı CI uygulanmaz; yeşil CI kurulur (öz-denetim + işaret + bekçi işareti)
    yeni = sunucu.yeni_commit("v2")
    sunucu.ci(("test", "completed", "success"), ("canli_sdk", "completed", "failure"))
    assert sunucu.calistir().returncode == 0 and sunucu.head() == sunucu.v1
    sunucu.ci(*YESIL)
    r = sunucu.calistir()
    assert r.returncode == 0 and sunucu.head() == yeni and "öz-denetim tamam" in r.stdout, r.stdout + r.stderr
    assert (depo / "durum/guncelleme_zamani").read_text().split()[1] == yeni and (sunucu.durum / "bekci").exists()

    # ---- 5) kurulumdan sonra 15 dk: ölümcül olmayan uyarı bekler, ölümcül gider (motorun Telegram'ı işareti okur)
    m.tg.guncelleme_isareti = depo / "durum/guncelleme_zamani"
    m.tg.gonder("🚨 ALARM: kayıtlar uyuşmuyor (mutabakat)\nYeni pozisyon açılmıyor.")
    m.tg.gonder("💥 Tasfiye (sanal)\nBTC pozisyonu tasfiye oldu.")
    assert not any("uyuşmuyor" in x for x in tgp.gonderilen) and any("Tasfiye" in x for x in tgp.gonderilen)
    assert kayitlar(depo, "tg_guncelleme_bekletildi")

    # ---- 6) 60 dk bekçi: sorunsuz → izlemeye devam, geri dönüş yok
    r = subprocess.run(["bash", str(BEKCI)], env=sunucu.ortak, capture_output=True, text=True)
    assert r.returncode == 0 and "izleniyor" in r.stdout and sunucu.head() == yeni
