"""Dolgu / REST hakem 429 koruması: arka plan, ortak istek aralığı, 3 yeniden deneme, kopma aralığı korunur, hata türü görünür."""
from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.error

import pytest

from copytrade import dinleyici as d
from tests.test_dinleyici import A, B, IZ, Saat, SahteWS, calistir, trades


def h429():
    return urllib.error.HTTPError("https://x/info", 429, "Too Many Requests", {}, None)


def ayar(**ek):
    return d.Ayar(**{**dict(rest_istek_ara_sn=0.0, rest_bekleme_sn=(0.01, 0.01, 0.01), sure_sn=0.5, geri_cekilme_ilk_sn=0.01, geri_cekilme_max_sn=0.02, rest_tolerans_ms=0), **ek})


class Canli(SahteWS):
    """Kuyruktaki mesajlar işlendikten sonra bağlantı AÇIK kalır (yeniden bağlanma fırtınası yok)."""
    async def recv(self):
        if self.mesajlar:
            return await super().recv()
        await asyncio.sleep(3600)


def kos(post, ws_listesi, tmp_path, ayar_, saat):
    sira = iter(ws_listesi)

    async def baglan():
        return next(sira, None) or Canli([], "bekle", saat)
    din = d.Dinleyici(IZ, ["BTC"], baglan, post, tmp_path, ayar_, saat.saat_ms)
    return din, asyncio.run(din.calis())


REST = {A: [{"tid": 11, "time": 1_000_150, "coin": "BTC"}, {"tid": 12, "time": 1_000_160, "coin": "BTC"}], B: []}
KOPMA = [[100, trades((1, 1_000_050, [A])), 400], []]            # 1. bağlantı kopar (son mesaj 1_000_100), 2. bağlantı dolguyu tetikler


# ------------------------------------------------------------------ hata türü ve istek aralığı (saf)
def test_hata_turu_siniflari_adres_icermez():
    assert d.hata_turu(h429()) == "HTTP 429"
    assert d.hata_turu(urllib.error.HTTPError("u", 503, "x", {}, None)) == "HTTP 503"
    assert d.hata_turu(TimeoutError("x")) == "Timeout"
    assert d.hata_turu(urllib.error.URLError(TimeoutError("timed out"))) == "Timeout"
    assert d.hata_turu(urllib.error.URLError("Name or service not known")) == "Ağ (URLError)"
    assert d.hata_turu(ValueError("bozuk 0x" + "a" * 40)) == "Geçersiz yanıt"
    assert d.hata_turu(RuntimeError("0x" + "a" * 40)) == "RuntimeError" and "0x" not in d.hata_turu(KeyError(A))


def test_istek_aralik_ortak_sayac_en_az_ara_birakir():
    r = d.IstekAralik(0.05)
    t0 = time.monotonic()
    r.bekle(); r.bekle(); asyncio.run(r.abekle())                  # eşzamanlı/ardışık üç kullanıcı aynı sayacı paylaşır
    assert time.monotonic() - t0 >= 0.1 - 0.005
    assert d.Ayar().rest_istek_ara_sn == 0.5 and d.Ayar().rest_bekleme_sn == (2.0, 5.0, 15.0)


# ------------------------------------------------------------------ (a) 429 -> yeniden deneme -> dolum kurtarılır
def test_a_429_yeniden_deneme_dolum_kurtarilir(tmp_path, capsys):
    cagri = {"a": 0}

    def post(yuk):
        if yuk["user"] == A:
            cagri["a"] += 1
            if cagri["a"] <= 2:
                raise h429()
        return REST[yuk["user"]]
    din, ws, ozet = calistir(IZ, KOPMA, tmp_path, saat=Saat(ms=1_000_000), post=post, ayar=ayar())
    g = ozet["genel"]
    assert g["dolgu"] == 2 and ozet["toplam"]["aaaa"]["dolgu"] == 2 and g.get("dolgu_hata", 0) == 0
    assert g["dolgu_yeniden_deneme"] == 2 and g["dolgu_bekleyen"] == 0 and g["dolgu_hata_tur"] == {}
    err = capsys.readouterr().err.strip().splitlines()
    assert err[:2] == ["UYARI REST hatası kaynak=dolgu trader=aaaa tur=HTTP 429"] * 2     # her hata journal'a tek satır; adres yok
    assert all("0x" not in satir for satir in err)


# ------------------------------------------------------------------ (b) 3 hata -> sonraki turda kurtarılır, kopma aralığı korunur
def test_b_uc_yeniden_deneme_hata_sonraki_rest_turunda_kurtarilir_kopma_araligi_korunur(tmp_path, capsys):
    cagri, baslangiclar = {"a": 0}, []

    def post(yuk):
        if yuk["user"] == A:
            cagri["a"] += 1
            baslangiclar.append(yuk["startTime"])
            if cagri["a"] <= 4:                                    # ilk deneme + 3 yeniden deneme hata
                raise h429()
        return REST[yuk["user"]]
    saat = Saat(ms=1_000_000)
    din, ozet = kos(post, [SahteWS([100, trades((1, 1_000_050, [A])), 400], "kes", saat)], tmp_path, ayar(rest_aralik_sn=0.15, sure_sn=0.8, ping_sn=0.05), saat)
    g = ozet["genel"]
    assert g["dolgu_hata"] == 1 and g["dolgu_hata_tur"] == {"HTTP 429": 1} and g["dolgu_yeniden_deneme"] == 3
    assert g["dolgu"] == 2 and ozet["toplam"]["aaaa"]["dolgu"] == 2 and g["dolgu_bekleyen"] == 0       # sonraki REST turunda kurtarıldı
    assert baslangiclar[0] == baslangiclar[3] == baslangiclar[4] == 1_000_100                          # kopma aralığı (son mesaj) unutulmadı: aynı başlangıç
    assert capsys.readouterr().err.count("kaynak=dolgu trader=aaaa tur=HTTP 429") == 4


def test_b2_bekleyen_kopma_araligi_ikinci_kopmada_en_eskiyle_birlesir():
    din = d.Dinleyici(IZ, ["BTC"], None, lambda y: [], __import__("pathlib").Path("."), ayar())

    async def dene():
        din._dolgu_baslat((5_000, 6_000))
        din._dolgu_baslat((9_000, 10_000))
        await asyncio.sleep(0)
        assert din._dolgu_bekleyen == {"aaaa": 5_000, "bbbb": 5_000} and din.olcum.genel["dolgu_bekleyen"] == 2   # en eski başlangıç korunur
        din._dolgu_gorevi.cancel()
    asyncio.run(dene())


# ------------------------------------------------------------------ hata türleri (karışık) ve hakem
def test_hata_tur_sayimi_dolgu_karisik_hatalar_adres_yok(tmp_path, capsys):
    def post(yuk):
        raise h429() if yuk["user"] == A else TimeoutError("zaman aşımı")
    din, ws, ozet = calistir(IZ, KOPMA, tmp_path, saat=Saat(ms=1_000_000), post=post, ayar=ayar(sure_sn=0.4))
    g = ozet["genel"]
    assert g["dolgu_hata"] == 2 and g["dolgu_hata_tur"] == {"HTTP 429": 1, "Timeout": 1}
    assert sum(g["dolgu_hata_tur"].values()) == g["dolgu_hata"] and g["dolgu_bekleyen"] == 2
    ciktilar = capsys.readouterr().err
    assert "kaynak=dolgu trader=bbbb tur=Timeout" in ciktilar and "0x" not in ciktilar
    assert "0x" not in (tmp_path / "ozet.json").read_text()


def test_hakem_hatasi_oturumu_koparmaz_hata_sayilir(tmp_path):
    """Eski davranış: tek 429 hakem turundan istisna çıkar, oturum 'kopma' sayılırdı (ve yeniden bağlanınca 92 adres dolgusu 429'u büyütürdü)."""
    def post(yuk):
        raise h429()
    saat = Saat(ms=1_000_000)
    din, ozet = kos(post, [Canli([], "bekle", saat)], tmp_path, ayar(rest_aralik_sn=0.05, sure_sn=0.4, ping_sn=0.02), saat)
    g = ozet["genel"]
    assert g["kopma"] == 0 and g["hakem_hata"] >= 2 and g["hakem_hata_tur"]["HTTP 429"] >= 2 and g["hakem_yeniden_deneme"] >= 3


# ------------------------------------------------------------------ (c) dolgu sürerken gelen dolumlar ölçülür
def test_c_dolgu_surerken_gelen_dolumlar_olculur(tmp_path):
    serbest = threading.Event()

    def post(yuk):
        if yuk["user"] == A and yuk["startTime"] == 1_000_100:     # dolgu isteği: canlı dolum işlenene dek BLOKLU (akış beklerse kilitlenir)
            assert serbest.wait(5), "WS akışı dolguyu bekledi (bloklandı)"
        return REST[yuk["user"]]
    saat = Saat(ms=1_000_000)

    class Canli(SahteWS):
        async def recv(self):
            if self.mesajlar:
                return await super().recv()
            await asyncio.sleep(3600)
    ws1 = SahteWS([100, trades((1, 1_000_050, [A])), 400], "kes", saat)
    ws2 = Canli([200, trades((2, 1_000_600, [A]))], "bekle", saat)
    sira = iter([ws1, ws2])

    async def baglan():
        return next(sira, None) or SahteWS([], "bekle", saat)
    din = d.Dinleyici(IZ, ["BTC"], baglan, post, tmp_path, ayar(), saat.saat_ms)
    olay = din.olcum.olay

    def izle(o):
        sonuc = olay(o)
        if len(din.olcum.toplam["aaaa"].gecikme) >= 2:
            serbest.set()
        return sonuc
    din.olcum.olay = izle
    ozet = asyncio.run(din.calis())
    assert ozet["toplam"]["aaaa"]["n"] == 2 and ozet["genel"]["trades_mesaj"] == 2           # dolgu sürerken gelen canlı dolum ölçüldü
    assert ozet["toplam"]["aaaa"]["gecikme_max_sn"] <= 0.5 and ozet["genel"]["dolgu"] == 2   # gecikme dolgu beklemesiyle şişmedi; dolgu sonra tamamlandı
