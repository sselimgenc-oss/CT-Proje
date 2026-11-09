"""G-10 (denetim 08.11): dış ölü adam alarmı `sg-nabiz` (Cloudflare Worker, .github/nabiz/worker.js). Karar ve tur mantığı node ile koşturulur.
node yoksa yerelde atlanır; CI'da (CI=true) atlama YOK: test kırmızı olur (ci.yml test işi node'u kurar)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
NABIZ = ROOT / ".github/nabiz"
WORKER = NABIZ / "worker.js"
DK = 60_000
T0 = 1_794_173_454_051          # gerçek kilit.json nabiz_ms (canli-durum, 2026-11-08T21:30:54Z)


def _node(govde: str) -> object:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("node yok: CI'da nabız testi atlanamaz")
        pytest.skip("node yok (yerel)")
    betik = f"const w = await import({json.dumps(WORKER.as_uri())});\n{govde}"
    r = subprocess.run([node, "--input-type=module", "-e", betik], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _karar(yas_dk: float, **ek) -> dict:
    return _node(f"console.log(JSON.stringify(w.karar({T0 + yas_dk * DK}, {T0}, 45, 180, {json.dumps(ek)})));")


# ---------------------------------------------------------------------------------------------------- altın örnekler (elle: eşik 45, tekrar 180, tik 10)
@pytest.mark.parametrize("yas, alarm, durum", [
    (0, False, "taze"), (44, False, "taze"), (44.99, False, "taze"),
    (45, True, "bayat"), (54, True, "bayat"), (54.99, True, "bayat"),     # ilk tik penceresi [45, 55)
    (55, False, "bayat"), (100, False, "bayat"), (224.99, False, "bayat"),
    (225, True, "bayat"), (234, True, "bayat"), (235, False, "bayat"),    # 45 + 180: yineleme
    (405, True, "bayat"), (415, False, "bayat"),                         # 45 + 360
])
def test_karar_altin_ornekler(yas, alarm, durum):
    k = _karar(yas)
    assert (k["alarm"], k["durum"]) == (alarm, durum)
    assert k["yas_dk"] == pytest.approx(yas)


def test_karar_her_pencerede_tam_bir_tik_alarm_verir():
    """10 dk'lık tik ızgarası hangi kaymada olursa olsun, 24 saatlik bayatlıkta alarm sayısı = ceil((1440-45)/180) = 8 (45, 225, …, 1305)."""
    sonuc = _node(f"""
      const say = [];
      for (const kayma of [0, 1, 3.5, 7, 9.99]) {{
        let n = 0;
        for (let t = kayma; t <= 1440; t += 10) if (w.karar({T0} + t * {DK}, {T0}).alarm) n++;
        say.push(n);
      }}
      console.log(JSON.stringify(say));""")
    assert sonuc == [8, 8, 8, 8, 8]


def test_karar_gelecek_zaman_saat_kaymasi_alarm_vermez():
    assert _karar(-5) == {"alarm": False, "durum": "taze", "yas_dk": 0}


def test_karar_donem_oncesi_bekleme_normal_sonra_yas_donem_basindan():
    donem = T0 + 60 * DK                                                  # dönem 60 dk sonra başlıyor; veri ondan da eski
    assert _karar(59, donem_ms=donem) == {"alarm": False, "durum": "donem_bekleniyor", "yas_dk": None}
    assert _karar(60 + 44, donem_ms=donem)["alarm"] is False               # dönem başından 44 dk: henüz normal (ilk yayım ~15-20 dk)
    k = _karar(60 + 45, donem_ms=donem)
    assert k["alarm"] is True and k["yas_dk"] == pytest.approx(45)
    k = _karar(30, donem_ms=T0 - 10 * DK)                                  # dönem geçmişte, veri yeni: yaş veriden
    assert k["yas_dk"] == pytest.approx(30) and k["alarm"] is False


def test_karar_bilinmiyor_yalniz_3_saatlik_utc_izgarasinin_ilk_tikinde():
    gece = 1_794_096_000_000                                               # 2026-11-08T00:00:00Z (180'e bölünür dakika)
    assert gece % (180 * DK) == 0
    sonuc = _node(f"""console.log(JSON.stringify([0, 5, 9.99, 10, 60, 179, 180, 185, 190].map(d => w.karar({gece} + d * {DK}, null))));""")
    assert [s["alarm"] for s in sonuc] == [True, True, True, False, False, False, True, True, False]
    assert {s["durum"] for s in sonuc} == {"bilinmiyor"}
    assert _node(f"console.log(JSON.stringify(w.karar({gece}, NaN)))")["durum"] == "bilinmiyor"


def test_son_zaman_kilit_ve_ozetin_buyugu_gecersizleri_atlar():
    sonuc = _node("""console.log(JSON.stringify([
      w.son_zaman({nabiz_ms: 100, birakildi: false}, {yazildi_ms: 250}),
      w.son_zaman({nabiz_ms: 300}, {yazildi_ms: 250}),
      w.son_zaman(null, {yazildi_ms: 250}),
      w.son_zaman({nabiz_ms: 0}, {}),
      w.son_zaman({nabiz_ms: "abc"}, null),
      w.son_zaman(null, null),
      w.son_zaman({nabiz_ms: "400"}, null)]));""")
    assert sonuc == [250, 300, 250, None, None, None, 400]


def test_ayarlar_varsayilan_ve_gecersiz_degerler():
    sonuc = _node("""console.log(JSON.stringify([w.ayarlar({}), w.ayarlar({ESIK_DK: "60", TEKRAR_DK: "120"}), w.ayarlar({ESIK_DK: "x", TEKRAR_DK: "5"})]));""")
    assert sonuc == [{"esik_dk": 45, "tekrar_dk": 180, "tik_dk": 10}, {"esik_dk": 60, "tekrar_dk": 120, "tik_dk": 10}, {"esik_dk": 45, "tekrar_dk": 180, "tik_dk": 10}]


# ---------------------------------------------------------------------------------------------------- tur: sahte fetch (ağ yok)
def _tur(kilit, ozet, donem, simdi_ms, env: dict, cagri: str = "calis", hata: int = 0) -> dict:
    """worker'ın `calis` (zamanlı tur) ya da `default.fetch` (elle) yolunu sahte fetch ile koşturur. kilit/ozet/donem None → HTTP 404; `hata`: ilk N ham istek ağ hatası."""
    return _node(f"""
      const veri = {{"kilit.json": {json.dumps(kilit)}, "ozet.json": {json.dumps(ozet)}, "DONEM": {json.dumps(donem)}}};
      const istek = []; let tg = []; let hata = {hata};
      globalThis.fetch = async (url, op) => {{
        url = String(url);
        if (url.startsWith("https://api.telegram.org/")) {{ tg.push({{url, govde: JSON.parse(op.body)}}); return new Response("{{}}", {{status: 200}}); }}
        istek.push(url);
        if (hata > 0) {{ hata--; throw new Error("ag"); }}
        const ad = url.split("?")[0].split("/").pop();
        const d = veri[ad];
        if (d === null) return new Response("yok", {{status: 404}});
        return new Response(typeof d === "string" ? d : JSON.stringify(d), {{status: 200}});
      }};
      let sonuc;
      if ({json.dumps(cagri)} === "calis") sonuc = await w.calis({json.dumps(env)}, {simdi_ms}, [0, 0]);
      else {{ const r = await w.default.fetch(new Request("https://sg-nabiz.example/"), {json.dumps(env)}); sonuc = {{...(await r.json()), cc: r.headers.get("cache-control")}}; }}
      console.log(JSON.stringify({{sonuc, istek, tg}}));""")


ACIK = {"TELEGRAM_ACIK": "evet", "TELEGRAM_BOT_TOKEN": "GIZLI_TOKEN_123", "TELEGRAM_CHAT_ID": "42", "ESIK_DK": "45", "TEKRAR_DK": "180"}
KILIT = {"vardiya": "42519882583", "nabiz_ms": T0, "birakildi": False}
OZET = {"yazildi_ms": T0 - 2 * DK, "kip": "sanal"}
DONEM = "2026-11-08T21:01:00Z\n"


def test_tur_bayat_veri_tek_telegram_mesaji_turkce_ve_actions_baglantili():
    r = _tur(KILIT, OZET, DONEM, T0 + 50 * DK, ACIK)
    s = r["sonuc"]
    assert (s["durum"], s["alarm"], s["gonderildi"], s["yas_dk"]) == ("bayat", True, True, 50)
    assert len(r["tg"]) == 1 and r["tg"][0]["url"] == "https://api.telegram.org/botGIZLI_TOKEN_123/sendMessage" and r["tg"][0]["govde"]["chat_id"] == "42"
    metin = r["tg"][0]["govde"]["text"]
    assert metin.startswith("🚨 ALARM: Sanal motor nabzı yok — son yayım 50 dk önce. Vardiya zinciri kopmuş olabilir: https://github.com/sselimgenc-oss/CT-Proje/actions/workflows/canli_vardiya.yml")
    assert all("?t=" in u for u in r["istek"]) and any("/canli-durum/durum/kilit.json" in u for u in r["istek"]) and any("/main/copytrade/canli/DONEM" in u for u in r["istek"])


def test_tur_birakilmis_kilit_mesajda_belirtilir():
    r = _tur({**KILIT, "birakildi": True}, OZET, DONEM, T0 + 46 * DK, ACIK)
    assert "son vardiya kilidi bıraktı, yenisi başlamadı" in r["tg"][0]["govde"]["text"]


@pytest.mark.parametrize("yas", [44, 55, 100])
def test_tur_pencere_disinda_mesaj_yok(yas):
    r = _tur(KILIT, OZET, DONEM, T0 + yas * DK, ACIK)
    assert r["sonuc"]["alarm"] is False and r["tg"] == []


@pytest.mark.parametrize("env", [{**ACIK, "TELEGRAM_ACIK": "hayir"}, {**ACIK, "TELEGRAM_BOT_TOKEN": ""}, {k: v for k, v in ACIK.items() if k != "TELEGRAM_CHAT_ID"}])
def test_tur_telegram_kapali_ya_da_secret_yoksa_gonderim_yok(env):
    r = _tur(KILIT, OZET, DONEM, T0 + 50 * DK, env)
    assert r["sonuc"]["alarm"] is True and r["sonuc"]["gonderildi"] is False and r["tg"] == []


def test_tur_tek_dosya_okunamazsa_digeriyle_karar_verir():
    r = _tur(None, OZET, DONEM, T0 + 50 * DK, ACIK)                        # kilit 404: ozet.yazildi_ms (T0-2) ile yaş 52
    assert r["sonuc"]["durum"] == "bayat" and r["sonuc"]["yas_dk"] == pytest.approx(52) and r["sonuc"]["okundu"] == {"kilit": False, "ozet": True, "donem": True}


def test_tur_gecici_ag_hatasi_yeniden_denenir_ve_alarm_yok():
    r = _tur(KILIT, OZET, DONEM, T0 + 10 * DK, ACIK, hata=2)                # ilk iki istek ağ hatası → yeniden deneme ile okunur
    assert r["sonuc"]["durum"] == "taze" and r["tg"] == [] and r["sonuc"]["okundu"]["kilit"] and r["sonuc"]["okundu"]["ozet"]


def test_tur_veri_hic_okunamazsa_bilinmiyor_izgara_disinda_sessiz_izgarada_tek_uyari():
    gece = 1_794_182_400_000                                                # 2026-11-09T00:00:00Z (dönem başından sonra): 3 saatlik ızgara
    assert gece % (180 * DK) == 0
    r = _tur(None, None, DONEM, gece + 30 * DK, ACIK)
    assert r["sonuc"]["durum"] == "bilinmiyor" and r["sonuc"]["alarm"] is False and r["tg"] == []
    assert sum("kilit.json" in u for u in r["istek"]) == 3                 # 3 deneme
    r = _tur(None, None, DONEM, gece + 2 * DK, ACIK)
    assert r["sonuc"]["alarm"] is True and len(r["tg"]) == 1 and r["tg"][0]["govde"]["text"].startswith("⚠️ UYARI: Sanal motor nabzı okunamadı")


def test_tur_donem_dosyasi_okunamazsa_veriyle_devam_bozuk_donem_yok_sayilir():
    for donem in (None, "bozuk"):
        r = _tur(KILIT, OZET, donem, T0 + 50 * DK, ACIK)
        assert r["sonuc"]["donem_ms"] is None and r["sonuc"]["alarm"] is True


def test_elle_sorgu_json_durum_doner_gondermez_secret_sizdirmaz():
    """fetch işleyicisi: tek deneme, Telegram'a GİTMEZ; yanıtta token/chat id yok, yalnız açık/kapalı."""
    r = _tur(KILIT, OZET, DONEM, 0, ACIK, cagri="fetch")
    s = r["sonuc"]
    assert r["tg"] == [] and s["telegram"] == "acik" and s["cc"] == "no-store" and s["okundu"]["kilit"] is True
    assert "GIZLI_TOKEN_123" not in json.dumps(r["sonuc"]) and not any(k.startswith("TELEGRAM_") for k in s)
    assert s["kaynak"]["kilit"] == "https://raw.githubusercontent.com/sselimgenc-oss/CT-Proje/canli-durum/durum/kilit.json"


# ---------------------------------------------------------------------------------------------------- yapılandırma ve yayın iş akışı
def test_wrangler_toml_adi_cron_ve_esikler():
    import tomllib
    t = tomllib.loads((NABIZ / "wrangler.toml").read_text(encoding="utf-8"))
    assert t["name"] == "sg-nabiz" and t["main"] == "worker.js" and t["triggers"]["crons"] == ["*/10 * * * *"]
    assert t["vars"] == {"ESIK_DK": "45", "TEKRAR_DK": "180"}                # secret / TELEGRAM_ACIK dosyada yok
    metin = (NABIZ / "wrangler.toml").read_text(encoding="utf-8") + WORKER.read_text(encoding="utf-8")
    assert not re.search(r"\d{8,10}:[A-Za-z0-9_-]{30,}", metin)              # Telegram bot token biçimi commit edilmez
    assert json.loads((NABIZ / "package.json").read_text(encoding="utf-8")).get("dependencies") is None    # bağımlılık yok; wrangler .github/pano kilidinden


def _wf() -> dict:
    veri = yaml.safe_load((ROOT / ".github/workflows/nabiz_yayim.yml").read_text(encoding="utf-8"))
    veri["on"] = veri.pop(True, veri.get("on"))
    return veri


def test_nabiz_yayim_is_akisi_yalniz_okur_yalniz_main_ve_kilitten_kurar():
    wf = _wf()
    assert wf["permissions"] == {"contents": "read"} and wf["jobs"]["yayim"]["permissions"] == {"contents": "read"}
    assert wf["defaults"]["run"]["shell"] == "bash -euo pipefail {0}"
    assert set(wf["on"]) == {"workflow_dispatch", "push"} and wf["on"]["push"] == {"branches": ["main"], "paths": [".github/nabiz/**"]}
    is_ = wf["jobs"]["yayim"]
    assert is_["if"] == "${{ github.ref == 'refs/heads/main' }}"
    adimlar = is_["steps"]
    assert adimlar[0]["uses"].startswith("actions/checkout@") and adimlar[0]["with"]["persist-credentials"] is False
    kur = next(a for a in adimlar if "kilit dosyasından kur" in a.get("name", ""))
    assert kur["run"] == "npm ci --prefix .github/pano --ignore-scripts --no-audit --no-fund"
    yayin = next(a for a in adimlar if "Worker yayını" in a.get("name", ""))
    assert "wrangler deploy --config .github/nabiz/wrangler.toml" in yayin["run"] and yayin["env"]["NABIZ_TG_ACIK"] == "${{ vars.TELEGRAM_ACIK == 'evet' && 'evet' || 'hayir' }}" and '--var "TELEGRAM_ACIK:${NABIZ_TG_ACIK}"' in yayin["run"]
    assert set(is_["env"]) == {"WRANGLER_SEND_METRICS", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"}
    metin = (ROOT / ".github/workflows/nabiz_yayim.yml").read_text(encoding="utf-8")
    assert not re.search(r"\|\|\s*true\b|continue-on-error", metin)


def test_nabiz_yayim_telegram_secretlari_kapili_stdin_ile_yazdirilmaz():
    is_ = _wf()["jobs"]["yayim"]
    sec = next(a for a in is_["steps"] if "Telegram secret" in a.get("name", ""))
    assert sec["if"] == "${{ vars.TELEGRAM_ACIK == 'evet' }}"
    for ad in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        assert sec["env"][ad] == f"${{{{ github.ref == 'refs/heads/main' && vars.TELEGRAM_ACIK == 'evet' && secrets.{ad} || '' }}}}"
    assert "printf '%s' \"${!ad}\" | .github/pano/node_modules/.bin/wrangler secret put \"$ad\" --config .github/nabiz/wrangler.toml >/dev/null" in sec["run"]
    for a in is_["steps"]:
        run = a.get("run", "")
        assert not re.search(r"(echo|printf)[^|\n]*(TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID|CLOUDFLARE_API_TOKEN)\}?\"?\s*($|>>|;)", run), run      # secret çıktıya basılmaz
        assert "secrets." not in run and "set -x" not in run


def test_ci_test_isi_node_kurar():
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    assert any(str(a.get("uses", "")).startswith("actions/setup-node@") for a in ci["jobs"]["test"]["steps"])


# ---------------------------------------------------------------------------------------------------- Y-3 (3. dış denetim): kaynak ayarı
HAM = "https://raw.githubusercontent.com/sselimgenc-oss/CT-Proje"


def test_y3_kaynak_varsayilan_canli_durum_dal_adi_ve_https_kok():
    sonuc = _node("""console.log(JSON.stringify([w.kaynak({}), w.kaynak({NABIZ_KAYNAK: "  "}), w.kaynak({NABIZ_KAYNAK: "canli-durum"}), w.kaynak({NABIZ_KAYNAK: "canli-gercek"}),
      w.kaynak({NABIZ_KAYNAK: "https://raw.githubusercontent.com/baska/depo/canli-gercek/"})]));""")
    assert [s["kilit"] for s in sonuc] == [f"{HAM}/canli-durum/durum/kilit.json"] * 3 + [f"{HAM}/canli-gercek/durum/kilit.json",
                                                                                     "https://raw.githubusercontent.com/baska/depo/canli-gercek/durum/kilit.json"]
    assert [s["ozel"] for s in sonuc] == [False, False, False, True, True]
    assert sonuc[3]["ozet"] == f"{HAM}/canli-gercek/durum/ozet.json" and sonuc[3]["donem"] == f"{HAM}/main/copytrade/canli/DONEM"


@pytest.mark.parametrize("deger", ["http://ornek.com/x", "canli gercek", "../baska", "a/../b", "https://x.com/a/../b", "canli-gercek?x=1", "javascript:alert(1)"])
def test_y3_kaynak_gecersiz_deger_varsayilana_duser(deger):
    s = _node(f"console.log(JSON.stringify(w.kaynak({{NABIZ_KAYNAK: {json.dumps(deger)}}})));")
    assert s["kilit"] == f"{HAM}/canli-durum/durum/kilit.json" and s["ozel"] is False


def test_y3_tur_gercek_kaynakta_gercek_dali_okur_mesaj_gercek_motor_sunucu_komutu():
    r = _tur(KILIT, {**OZET, "kip": "gercek"}, DONEM, T0 + 50 * DK, {**ACIK, "NABIZ_KAYNAK": "canli-gercek"})
    s = r["sonuc"]
    assert s["alarm"] is True and s["kip"] == "gercek" and s["kaynak_ozel"] is True
    assert any("/canli-gercek/durum/kilit.json" in u for u in r["istek"]) and not any("/canli-durum/" in u for u in r["istek"])
    metin = r["tg"][0]["govde"]["text"]
    assert metin.startswith("🚨 ALARM: Gerçek motor nabzı yok — son yayım 50 dk önce.") and "systemctl status sg-canli" in metin and "actions/workflows" not in metin


def test_y3_tur_ozel_kaynak_okunamazsa_motor_etiketi_ve_elle_sorgu_kaynagi():
    gece = 1_794_182_400_000
    r = _tur(None, None, DONEM, gece + 2 * DK, {**ACIK, "NABIZ_KAYNAK": "canli-gercek"})
    assert r["tg"][0]["govde"]["text"].startswith("⚠️ UYARI: Motor nabzı okunamadı") and "systemctl status sg-canli" in r["tg"][0]["govde"]["text"]
    r = _tur(KILIT, {**OZET, "kip": "gercek"}, DONEM, 0, {**ACIK, "NABIZ_KAYNAK": "canli-gercek"}, cagri="fetch")
    assert r["sonuc"]["kaynak"]["kilit"] == f"{HAM}/canli-gercek/durum/kilit.json" and r["sonuc"]["kaynak_ozel"] is True and r["sonuc"]["kip"] == "gercek"


def test_y3_yayin_kaynagi_github_degiskeninden_varsayilan_canli_durum():
    yayin = next(a for a in _wf()["jobs"]["yayim"]["steps"] if "Worker yayını" in a.get("name", ""))
    assert yayin["env"]["NABIZ_KAYNAK"] == "${{ vars.NABIZ_KAYNAK || 'canli-durum' }}" and '--var "NABIZ_KAYNAK:${NABIZ_KAYNAK}"' in yayin["run"]
    belge = (ROOT / "docs/NABIZ_ALARMI.md").read_text(encoding="utf-8") + (ROOT / "deploy/ACILIS_KONTROL.md").read_text(encoding="utf-8")
    assert belge.count("NABIZ_KAYNAK") >= 2 and "Gerçek paradan önce ön koşul" in belge and "Bu yapılmadan gerçek para AÇILMAZ" in belge
