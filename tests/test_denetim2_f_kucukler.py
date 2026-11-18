"""2. denetim F: küçük sağlamlaştırmalar — D-4 (kapanış için HIP-3), D-6 (DUR dizin fsync), D-7 (Kayit yarım satır), D-8 (Retry-After HTTP-date / 5xx / 418), D-9 (açılışta ValueError),
D-10 (hesap değeri geçersiz), D-11 (HL > 1.500 $ iken açık pozisyonla yalnız kapanış modu), D-13 (.gitignore), D-14 (baslama_sayaci atomik)."""
from __future__ import annotations

import json
import math
import os
import subprocess
from argparse import Namespace
from email.utils import format_datetime
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests

from copytrade import dinleyici
from copytrade import tarama
from copytrade.canli import motor as mt
from copytrade.canli import yurutucu as yu
from copytrade.kurallar import load_rules_asil
from tests.test_canli_g3_g4_g6_s11 import SahteExchange, kitap_post
from tests.test_canli_motor import adr, kayitlar, olay
from tests.test_canli_t4b import BorsaSim, kur_gercek
from tests.test_tarama_5xx import Oturum, Yanit

RULES = load_rules_asil()
KOK = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _m():
    yield
    mt.MASKE.clear()


# ---------------------------------------------------------------------------------------------------- D-4
def test_d4_hip3_kapaliyken_kapanis_reduce_only_hip3_pozisyonunu_kapatir_acilis_kapali():
    post = kitap_post({"xyz": [("xyz:AAPL", 3)]})
    ex = SahteExchange()
    g = yu.GercekYurutucu(ex, post, {**RULES, "canli_hip3_kopya": False})
    acilis = g.emir("xyz:AAPL", "B", 11.0)
    assert acilis.durum == "red" and acilis.neden.startswith("bilinmeyen coin: xyz:AAPL")                  # açılış kapısı değişmedi
    kapanis = g.emir("xyz:AAPL", "A", 20.0, reduce_only=True, acik_sz=0.2)
    assert kapanis.dolu_mu and ex.cagrilar[-1]["reduce_only"] is True and ex.cagrilar[-1]["coin"] == "xyz:AAPL"
    assert g.lot_adim("xyz:AAPL") == pytest.approx(0.001)


# ---------------------------------------------------------------------------------------------------- D-6
def test_d6_dur_yazimi_dizin_fsync_yapar(tmp_path, monkeypatch):
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    acilan, fsyncler = [], []
    gercek_open, gercek_fsync = os.open, os.fsync
    monkeypatch.setattr(os, "open", lambda p, *a, **k: (acilan.append(str(p)), gercek_open(p, *a, **k))[1])
    monkeypatch.setattr(os, "fsync", lambda fd: (fsyncler.append(fd), gercek_fsync(fd))[1])
    assert m._dur_yaz_atomik("test", 1, False) is True
    assert str(m.dur_dosyasi.parent) in acilan and len(fsyncler) >= 2                  # dosya + dizin
    assert json.loads(m.dur_dosyasi.read_text())["neden"] == "test"


# ---------------------------------------------------------------------------------------------------- D-7
def test_d7_kayit_yarim_son_satiri_onarir_yeni_satir_yapismaz(tmp_path):
    ms = 1_800_000_000_000
    k = mt.Kayit(tmp_path, lambda: ms)
    k({"olay": "a"})
    yol = next(tmp_path.glob("*.jsonl"))
    with yol.open("ab") as f:
        f.write(b'{"zaman_ms":1,"olay":"yarim')                                         # çökme: '\n'siz yarım satır
    k2 = mt.Kayit(tmp_path, lambda: ms)                                                  # yeniden başlatma
    k2({"olay": "b"})
    k2({"olay": "c"})
    satirlar = yol.read_text(encoding="utf-8").split("\n")
    gecerli = []
    for x in satirlar:
        try:
            gecerli.append(json.loads(x)["olay"])
        except ValueError:
            pass
    assert gecerli == ["a", "b", "c"] and yol.read_bytes().endswith(b"\n")


# ---------------------------------------------------------------------------------------------------- D-8
def test_d8_retry_after_http_date_ve_saniye():
    gelecek = format_datetime(datetime.now(UTC) + timedelta(seconds=120), usegmt=True)
    r = tarama.PublicClient._retry_after(Yanit(429, headers={"Retry-After": gelecek}))
    assert 100 <= r <= 121
    assert tarama.PublicClient._retry_after(Yanit(429, headers={"Retry-After": "7"})) == 7.0
    assert tarama.PublicClient._retry_after(Yanit(429, headers={"Retry-After": "bozuk tarih"})) == 0.0
    gecmis = format_datetime(datetime.now(UTC) - timedelta(seconds=50), usegmt=True)
    assert tarama.PublicClient._retry_after(Yanit(429, headers={"Retry-After": gecmis})) == 0.0
    assert tarama.PublicClient._retry_after(Yanit(429, headers={"Retry-After": "99999"})) == tarama.RETRY_AFTER_MAX


def test_d8_5xx_retry_after_dikkate_alinir():
    bekleme = []
    c = tarama.PublicClient(session=Oturum(Yanit(503, headers={"Retry-After": "30"}), 200), limiter=tarama.RateLimiter(10 ** 9), sleep=bekleme.append, yeniden_bekleme=tarama.KAPI_YENIDEN_BEKLEME)
    assert c.info({"type": "x"}) == {"ok": 200} and bekleme == [30.0]                      # max(5, 30)


def test_d8_418_yeniden_denenmez_soguma_retry_after_yoksa_600():
    soguma = []

    class L(tarama.RateLimiter):
        def sogut(self, sn):
            soguma.append(sn)
    oturum = Oturum(418)
    c = tarama.PublicClient(session=oturum, limiter=L(10 ** 9), sleep=lambda s: None, yeniden_bekleme=tarama.KAPI_YENIDEN_BEKLEME)
    with pytest.raises(requests.HTTPError):
        c.info({"type": "x"})
    assert oturum.cagri == 1 and soguma == [600.0]
    soguma.clear()
    c2 = tarama.PublicClient(session=Oturum(Yanit(418, headers={"Retry-After": "45"})), limiter=L(10 ** 9), sleep=lambda s: None)
    with pytest.raises(requests.HTTPError):
        c2.info({"type": "x"})
    assert soguma == [45.0]


# ---------------------------------------------------------------------------------------------------- D-9
def _args(tmp_path):
    return Namespace(durum_dizin=tmp_path / "durum", kayit_dizin=None, vardiya="yerel", sure_sn=0.0, kadro_dali=None)


def test_d9_beklenmeyen_valueerror_gecici_kasa_boyut_valueerror_kalici(tmp_path, monkeypatch):
    kodlar = []
    monkeypatch.setattr(mt, "_baslamadi", lambda tgram, hata, kod: kodlar.append((kod, str(hata))) or kod)

    def hl_ayristirma(*a, **k):
        raise ValueError("HL ayrıştırma: beklenmeyen biçim")
    monkeypatch.setattr(mt, "acilis_hl_denetle", hl_ayristirma)
    assert mt._motor_calistir(_args(tmp_path), RULES, "gercek", lambda y: {}, lambda: None, None, {}) == mt.CIKIS_GECICI
    monkeypatch.setattr(mt, "acilis_hl_denetle", lambda *a, **k: (1000.0, 1000.0))
    monkeypatch.setattr(mt, "kasa_belirle", lambda *a, **k: (_ for _ in ()).throw(ValueError("kasa bozuk")))
    assert mt._motor_calistir(_args(tmp_path), RULES, "gercek", lambda y: {}, lambda: None, None, {}) == mt.CIKIS_KALICI
    monkeypatch.undo()
    monkeypatch.setattr(mt, "_baslamadi", lambda tgram, hata, kod: kodlar.append((kod, str(hata))) or kod)
    monkeypatch.setattr(mt, "acilis_hl_denetle", lambda *a, **k: (0.5, 0.5))                       # kasa 0,5 $ < slot alt sınırı: boyut.saha_sayisi ValueError → kalıcı
    monkeypatch.setattr(mt, "kasa_belirle", lambda *a, **k: (0.5, "ortam"))
    assert mt._motor_calistir(_args(tmp_path), RULES, "gercek", lambda y: {}, lambda: None, None, {}) == mt.CIKIS_KALICI


# ---------------------------------------------------------------------------------------------------- D-10
@pytest.mark.parametrize("deger", [math.nan, math.inf, 0.0, -5.0])
def test_d10_hesap_degeri_gecersizse_reddedilir(deger):
    def post(y):
        if y["type"] == "userAbstraction":
            return "default"
        if y["type"] == "spotClearinghouseState":
            return {"balances": []}
        return {"marginSummary": {"accountValue": str(deger)}}
    with pytest.raises(ValueError, match="geçersiz"):
        mt.hesap_degeri_oku(post, adr(1), [])
    assert mt.hesap_degeri_oku(lambda y: ({"marginSummary": {"accountValue": "12.5"}} if y["type"] == "clearinghouseState" else ("default" if y["type"] == "userAbstraction" else {"balances": []})), adr(1), []) == 12.5


# ---------------------------------------------------------------------------------------------------- D-11
def _acilis(monkeypatch, sim, izin):
    monkeypatch.setenv("CANLI_KASA_USD", "1000")
    monkeypatch.setenv("HL_HESAP_ADRESI", "0x" + "ab" * 20)
    monkeypatch.setattr(mt, "api_cuzdan_dogrula", lambda post, ortam, turet=None: {"tamam": True})
    return mt.acilis_hl_denetle(RULES, "gercek", sim.post, {}, kapanis_modu_izni=izin)


def test_d11_hl_1600_pozisyon_varsa_kapanis_modunda_baslar_yoksa_ret_izin_yoksa_ret(monkeypatch):
    sim = BorsaSim(deger=1600.0)
    sim.poz["BTC"] = 0.1
    assert _acilis(monkeypatch, sim, True) == (1000.0, 1600.0)                                   # açık pozisyon: reddedilmez (çağıran kapanış modu kurar)
    with pytest.raises(mt.KipHatasi, match="K‑22"):
        _acilis(monkeypatch, sim, False)                                                         # izin yok: eskisi gibi
    sim.poz.clear()
    with pytest.raises(mt.KipHatasi, match="K‑22"):
        _acilis(monkeypatch, sim, True)                                                          # pozisyon yok: bugünkü ret (çıkış 3)
    sim2 = BorsaSim(deger=1012.0)
    assert _acilis(monkeypatch, sim2, True) == (1000.0, 1012.0)                                  # tavan altı: normal


def test_d11_kapanis_modunda_yeni_acilis_yok_kapanis_calisir(tmp_path, monkeypatch):
    sim = BorsaSim()
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.sz(adr(1), "BTC") > 0
    m.durum_yaz()
    m2, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat, tgp=tgp)
    m2.kapanis_modu = True
    m2.baslat()
    assert m2.risk.acilis_durdu["kapanis_modu"] is True and kayitlar(tmp_path, "kapanis_modu") and any("yalnız kapanış modu" in x for x in tgp.gonderilen)
    s = m2.olay_isle(olay("a:2", adr(1), "ETH", "B", 15, 2000.0, 0.0, saat))                       # yeni açılış
    assert s[0].karar == "engel" and s[0].neden == "kapanis_modu"
    s2 = m2.olay_isle(olay("a:3", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))                     # trader kapatır → bizim kapanış
    assert s2[0].karar == "emir" and m2.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)
    m3, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)                                       # normal yeniden başlatma: bayrak bayat kalmaz
    assert m3.risk.acilis_durdu.get("kapanis_modu") is False


# ---------------------------------------------------------------------------------------------------- D-13 / D-14
def test_d13_gitignore_sir_desenleri_ornek_dosyalar_bozulmaz():
    def yoksayilan(yol):
        return subprocess.run(["git", "check-ignore", "-q", yol], cwd=KOK, capture_output=True).returncode == 0
    for yol in (".env", "deploy/sg-canli.env", "x.pem", "a/b.key", "secrets.json", "secrets_prod.txt"):
        assert yoksayilan(yol), yol
    for yol in ("deploy/sg-canli.env.ornek", "deploy/sg-canli.service", "deploy/ACILIS_KONTROL.md"):
        assert not yoksayilan(yol), yol


def test_d14_baslama_sayaci_atomik_artar_tmp_kalmaz(tmp_path):
    yol = tmp_path / "cikti" / "durum.json"
    assert [dinleyici.baslama_sayaci(yol) for _ in range(3)] == [0, 1, 2]
    assert json.loads(yol.read_text())["baslama"] == 2 and not list(yol.parent.glob("*.tmp"))
