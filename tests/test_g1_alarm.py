"""G1 (Opus uçtan uca denetimi 05.11): vardiya başarısızlık alarmı (iş akışı + betik), Telegram urllib yedeği, motor çıkış-3 alarmı, kadro okuma yeniden denemesi."""
from __future__ import annotations

import builtins
import io
import os
import re
import subprocess
import sys
import urllib.request

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from test_is_akislari import SCRIPTS, adim, adimlar, yukle


@pytest.mark.parametrize("is_adi", ["kontrol", "vardiya"])
def test_basarisizlik_alarmi_failure_ve_main_kosullu(is_adi):
    wf = yukle("canli_vardiya.yml")
    a = adim(wf, is_adi, "Alarm (Telegram")
    assert a["if"] == "${{ failure() }}"
    assert a["env"]["TELEGRAM_BOT_TOKEN"] == "${{ github.ref == 'refs/heads/main' && vars.TELEGRAM_ACIK == 'evet' && secrets.TELEGRAM_BOT_TOKEN || '' }}"
    assert a["env"]["TELEGRAM_CHAT_ID"] == "${{ github.ref == 'refs/heads/main' && vars.TELEGRAM_ACIK == 'evet' && secrets.TELEGRAM_CHAT_ID || '' }}"
    assert "vardiya_alarm.sh" in a["run"] and "github.run_id" in a["env"]["RUN_URL"]
    if is_adi == "vardiya":
        assert adimlar(wf, is_adi)[-1] == a["name"]                              # son adım: önceki adımların sonucunu görür
        assert {"ADIM_GERI", "ADIM_ACILIS", "ADIM_MOTOR"} <= set(a["env"])


def test_alarm_betigi_curl_ile_tokensiz_sessiz_ve_secret_yazdirmaz(tmp_path):
    betik = SCRIPTS / "vardiya_alarm.sh"
    metin = betik.read_text(encoding="utf-8")
    assert "curl" in metin and "pip install" not in metin and not re.search(r"\|\|\s*true\b", metin)
    assert not re.search(r"echo[^\n]*TELEGRAM_BOT_TOKEN", metin)
    ortam = {"PATH": os.environ["PATH"], "RUN_URL": "https://x/run/1"}
    s = subprocess.run(["bash", str(betik), "vardiya"], env=ortam, capture_output=True, text=True)
    assert s.returncode == 0 and "atlandı" in s.stdout                           # token yok: sessiz geç
    (tmp_path / "curl").write_text('#!/usr/bin/env bash\necho "$@" > "$KAYIT"\n', encoding="utf-8")
    (tmp_path / "curl").chmod(0o755)
    kayit = tmp_path / "kayit.txt"
    ortam |= {"PATH": f"{tmp_path}:{os.environ['PATH']}", "KAYIT": str(kayit), "TELEGRAM_BOT_TOKEN": "GIZLI123", "TELEGRAM_CHAT_ID": "42", "ADIM_MOTOR": "failure"}
    s = subprocess.run(["bash", str(betik), "vardiya"], env=ortam, capture_output=True, text=True)
    assert s.returncode == 0 and "GIZLI123" not in s.stdout + s.stderr
    cagri = kayit.read_text(encoding="utf-8")
    assert "api.telegram.org/botGIZLI123/sendMessage" in cagri and "chat_id=42" in cagri and "https://x/run/1" in cagri and "canlı motor" in cagri
    (tmp_path / "curl").write_text("#!/usr/bin/env bash\nexit 22\n", encoding="utf-8")                       # gönderim hatası görünür: betik kırmızı
    s = subprocess.run(["bash", str(betik), "vardiya"], env=ortam, capture_output=True, text=True)
    assert s.returncode == 1 and "GIZLI123" not in s.stdout + s.stderr


def test_saglik_yml_requests_ve_pyyaml_kurar():
    wf = yukle("saglik.yml")
    kurulum = " ".join(a.get("run", "") for a in wf["jobs"]["saglik"]["steps"])
    assert "pip install" in kurulum and "requests==" in kurulum and "PyYAML==" in kurulum


def test_telegram_urllib_yedek_yolu_requests_yokken(monkeypatch):
    monkeypatch.delitem(sys.modules, "requests", raising=False)
    gercek = builtins.__import__

    def sahte_import(ad, *a, **k):
        if ad == "requests":
            raise ImportError("yok")
        return gercek(ad, *a, **k)

    cagrilar = []

    class Yanit(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def sahte_urlopen(istek, timeout=0):
        cagrilar.append((istek.full_url, istek.data, istek.get_method()))
        return Yanit(b'{"ok": true}')

    monkeypatch.setattr(builtins, "__import__", sahte_import)
    monkeypatch.setattr(urllib.request, "urlopen", sahte_urlopen)
    assert tg.varsayilan_post("https://api.telegram.org/botT/sendMessage", {"chat_id": "1", "text": "merhaba"}) == {"ok": True}
    assert cagrilar[0][0].endswith("/sendMessage") and cagrilar[0][2] == "POST" and b"merhaba" in cagrilar[0][1]


class SahteTg:
    ornekler: list = []

    def __init__(self, *a, **k):
        self.gonderilen, self.acik = [], True
        SahteTg.ornekler.append(self)

    def gonder(self, m):
        self.gonderilen.append(m)
        return True


def test_motor_main_baslamadi_yolu_telegram_alarmi_ve_cikis_3(monkeypatch, tmp_path):
    SahteTg.ornekler = []
    monkeypatch.setattr(mt.tg, "Telegram", SahteTg)
    monkeypatch.setattr(mt, "rest_post_olustur", lambda rules: None)

    def kasa_hatasi(*a, **k):
        raise mt.KipHatasi("HL hesap değeri okunamadı")

    monkeypatch.setattr(mt, "etkin_kasa", kasa_hatasi)
    assert mt.main(["--kip", "sanal", "--durum-dizin", str(tmp_path)]) == 3
    gonderilen = SahteTg.ornekler[0].gonderilen
    assert len(gonderilen) == 1 and "BAŞLAMADI" in gonderilen[0] and "HL hesap değeri okunamadı" in gonderilen[0] and gonderilen[0].startswith("🚨")


def test_motor_main_kip_hatasi_da_alarm_ve_cikis_3(monkeypatch, tmp_path):
    SahteTg.ornekler = []
    monkeypatch.setattr(mt.tg, "Telegram", SahteTg)
    assert mt.main(["--kip", "gercek", "--durum-dizin", str(tmp_path)]) == 3          # kurallar.yaml sanal: gerçek kip istenemez
    assert "BAŞLAMADI" in SahteTg.ornekler[0].gonderilen[0]


def test_baslamadi_alarmi_ayni_mesaj_zaten_gonderildiyse_tekrarlamaz():
    t = SahteTg()
    t.gonder("🚨 ALARM: tur başlayamadı\nVardiya 1 BAŞLAMADI: başka vardiya aktif")
    mt.baslamadi_alarmi(t, mt.KipHatasi("başka vardiya aktif"))
    assert len(t.gonderilen) == 1


def test_kadro_okuma_gecici_hatada_3_deneme(monkeypatch):
    import requests
    mt_rules = {"canli_kadro_repo": "o/r", "canli_kadro_dali": "radar"}
    cevaplar = [requests.ConnectionError("x"), "503", "ok"]
    uyku: list[float] = []

    class R:
        def __init__(self, kod, veri=None):
            self.status_code, self._v = kod, veri

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError("e", response=self)

        def json(self):
            return self._v

    def get(url, timeout=0):
        c = cevaplar.pop(0)
        if isinstance(c, Exception):
            raise c
        return R(503) if c == "503" else R(200, {"satirlar": []})

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(mt.time, "sleep", uyku.append)
    assert mt.http_kadro_oku(mt_rules) == {"satirlar": []} and len(uyku) == 2 and not cevaplar
    cevaplar[:] = [requests.ConnectionError("a"), requests.ConnectionError("b"), requests.ConnectionError("c")]
    with pytest.raises(requests.ConnectionError):
        mt.http_kadro_oku(mt_rules)                                                  # 3. denemede yükselir (motor kadro_okuma_hata kaydeder)
    monkeypatch.setattr(requests, "get", lambda url, timeout=0: R(404))
    uyku.clear()
    assert mt.http_kadro_oku(mt_rules) is None and not uyku                          # 404: yeniden deneme yok
