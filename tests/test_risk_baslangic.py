"""H5b: trader başlangıç pozisyonu (REST clearinghouseState) -> risk defteri. Altın örnekler elle hesaplanmıştır."""
from __future__ import annotations

import asyncio
import json

import pytest

from copytrade import dinleyici as d
from copytrade.risk_defter import KararGunlugu, RiskDefteri
from tests.test_dinleyici import A, B, Saat, SahteWS
from tests.test_risk_defter import GUN_MS, T, dolum, kurallar, yeni


def durum(*pozlar):
    """clearinghouseState yanıtı: pozlar = (coin, szi)."""
    return {"assetPositions": [{"type": "oneWay", "position": {"coin": c, "szi": str(s)}} for c, s in pozlar]}


# ------------------------------------------------------------------ (a) miras: elde pozisyon varken ekleme
def test_a_elde_pozisyon_varken_gelen_ekleme_miras_pozisyon_yeni_acilis_degil():
    rd = yeni(islem=50.0)
    rd.baslangic_ayarla("aaaa", {"BTC": 10.0}, T)                  # trader zaten 10 BTC long; bizde kopya yok
    k = dolum(rd, sz=5, bas=None, t=T + 1000)                      # trades kanalı: startPosition yok
    assert [(x["aksiyon"], x["kabul"], x["nedenler"]) for x in k] == [("add", False, ["miras_pozisyon"])]
    o = rd.ozet()
    assert (o["niyet"], o["kabul"], o["acik_pozisyon"], o["lider_pozisyon_varsayimi"], o["baslangic_bilinen_trader"]) == (1, 0, 0, 0, 1)
    assert rd.lider[("aaaa", "BTC")] == 15.0                       # izleme 10 + 5
    # bilinen trader'ın REST'te olmayan coin'i DÜZDÜR: gerçek açılış, varsayım sayacı artmaz
    k = dolum(rd, coin="ETH", sz=5, bas=None, t=T + 2000)
    assert k[0]["aksiyon"] == "open" and k[0]["kabul"] and rd.ozet()["lider_pozisyon_varsayimi"] == 0


def test_a2_okumadan_once_gerceklesen_dolum_cift_sayilmaz():
    rd = yeni()
    rd.baslangic_ayarla("aaaa", {"BTC": 10.0}, T + 5000)           # okuma T+5 sn; 2 BTC'lik alış T+4 sn (okumaya dahil)
    k = dolum(rd, sz=2, bas=None, t=T + 4000)
    assert rd.lider[("aaaa", "BTC")] == 10.0 and k[0]["nedenler"] == ["miras_pozisyon"]    # 10 (8 + 2), 12 DEĞİL
    dolum(rd, sz=2, bas=None, t=T + 6000)                          # okumadan sonra: yeni dolum eklenir
    assert rd.lider[("aaaa", "BTC")] == 12.0


def test_a3_miras_kapanisi_kopya_yok_ve_trader_bilinen_kapaniyor():
    rd = yeni()
    rd.baslangic_ayarla("aaaa", {"BTC": 10.0}, T)
    k = dolum(rd, yon="A", sz=10, bas=None, t=T + 1000)[0]         # trader miras 10 BTC'yi kapatıyor
    assert k["aksiyon"] == "exit" and k["nedenler"] == ["acik_pozisyon_yok"] and rd.lider[("aaaa", "BTC")] == 0.0


# ------------------------------------------------------------------ REST ayrıştırma (ana dex + HIP-3)
def test_clearinghouse_ana_dex_ve_hip3_birlestirilir_kisa_pozisyon_isaretli():
    cagrilar = []

    def post(yuk):
        cagrilar.append(yuk)
        if yuk.get("dex") == "xyz":
            return durum(("xyz:GOLD", -3.5))
        return durum(("BTC", 10.0), ("ETH", -2.0))
    sonuc = d.clearinghouse_pozisyonlari(post, A, ["xyz"])
    assert sonuc == {"BTC": 10.0, "ETH": -2.0, "xyz:GOLD": -3.5}
    assert cagrilar == [{"type": "clearinghouseState", "user": A}, {"type": "clearinghouseState", "user": A, "dex": "xyz"}]


@pytest.mark.parametrize("yanit", [None, [], {"assetPositions": "x"}, {"assetPositions": [{"position": {"coin": "BTC", "szi": "nan"}}]}, {"assetPositions": [{"position": {"szi": "1"}}]}])
def test_clearinghouse_bozuk_yanit_kismi_sonuc_donmez(yanit):
    with pytest.raises(ValueError):
        d.clearinghouse_pozisyonlari(lambda y: yanit, A, [])


def test_clearinghouse_bos_hesap_bos_sozluk():
    assert d.clearinghouse_pozisyonlari(lambda y: durum(), A, ["xyz"]) == {}


# ------------------------------------------------------------------ Dinleyici düzeyi
IZ = [d.Izlenen("aaaa", A, "ilk11"), d.Izlenen("bbbb", B, "yedek11")]


def trades_a(tid, ms, yon="B", sz=5):
    kars = "0x" + "9" * 40
    return {"channel": "trades", "data": [{"coin": "BTC", "side": yon, "px": "100", "sz": str(sz), "time": ms, "tid": tid, "users": [A, kars] if yon == "B" else [kars, A]}]}


HIZLI = dict(baslangic_bekleme_sn=(0.01, 0.01, 0.01), rest_istek_ara_sn=0.0, baslangic_yeniden_sn=0.05)


def Http429(mesaj=""):
    import urllib.error
    return urllib.error.HTTPError("https://x/info", 429, "Too Many Requests", {}, None)


def kos(post, baglantilar, tmp_path, dex_adlari=None, sure=0.4, ayar_ek=None, ws_sinifi=None, mono_saat=None):
    saat = Saat(ms=T)
    ws_listesi = [(ws_sinifi or SahteWS)(m, "kes", saat) if not isinstance(m, SahteWS) else m for m in baglantilar]
    sira = {"i": 0}

    async def baglan():
        if sira["i"] >= len(ws_listesi):
            ws_listesi.append(SahteWS([], "bekle", saat))
        ws = ws_listesi[sira["i"]]
        sira["i"] += 1
        return ws
    risk = RiskDefteri({"aaaa"}, kurallar(50.0), baslangic_ms=T)
    din = d.Dinleyici(IZ, ["BTC"], baglan, post, tmp_path, d.Ayar(sure_sn=sure, geri_cekilme_ilk_sn=0.01, geri_cekilme_max_sn=0.02, **{**HIZLI, **(ayar_ek or {})}), saat.saat_ms,
                      risk=risk, risk_gunlugu=KararGunlugu(tmp_path), dex_adlari=dex_adlari)
    kos.din = din
    ozet = asyncio.run(din.calis())
    return din, ozet


def test_b_rest_hatasinda_varsayim_sayaci_artar_olcum_surer(tmp_path):
    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            raise ConnectionError("rest kapalı")
        return []
    din, ozet = kos(post, [[100, trades_a(1, T + 50)]], tmp_path)
    assert ozet["genel"]["baslangic_poz_hata"] >= 1 and ozet["genel"]["baslangic_poz_okundu"] == 0
    assert ozet["risk"]["lider_pozisyon_varsayimi"] == 1 and ozet["risk"]["baslangic_bilinen_trader"] == 0
    assert ozet["risk"]["niyet"] == 1 and ozet["risk"]["kabul"] == 1                 # "düz" varsayımıyla açılış (eski davranış)
    assert ozet["toplam"]["aaaa"]["n"] == 1 and ozet["genel"]["trades_mesaj"] == 1    # ölçüm sürdü


def _okuma_bitince_ver(mesaj, saat, kosul):
    """`mesaj` ancak `kosul()` (REST okuması bitti) sağlanınca WS'ten gelir; sonra bekler."""
    class GecikmeliWS(SahteWS):
        verildi = False

        async def recv(self):
            while not kosul():
                await asyncio.sleep(0.005)
            if not GecikmeliWS.verildi:
                GecikmeliWS.verildi = True
                self.saat.ms += 100                          # sahte saat: dolum (T+50) şimdiden önce olmalı
                return json.dumps(mesaj)
            await asyncio.sleep(3600)
    return GecikmeliWS


def test_dinleyici_baslangicta_yalniz_ilk11_adreslerini_okur_ve_miras_ekleme_reddedilir(tmp_path):
    okunan = []

    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            okunan.append(yuk["user"])
            return durum(("BTC", 10.0))
        return []
    ws_sinifi = _okuma_bitince_ver(trades_a(1, T + 50), None, lambda: "aaaa" in kos.din.risk.bilinen)       # dolum REST okumasından SONRA gelir
    din, ozet = kos(post, [[]], tmp_path, ws_sinifi=ws_sinifi, sure=0.5)
    assert set(okunan) == {A} and ozet["genel"]["baslangic_poz_okundu"] >= 1 and ozet["genel"]["baslangic_poz_hata"] == 0
    assert ozet["risk"]["ret"] == {"miras_pozisyon": 1} and ozet["risk"]["lider_pozisyon_varsayimi"] == 0 and ozet["risk"]["acik_pozisyon"] == 0


def _once_bekle(kosul):
    """Bağlantı, `kosul()` sağlanana dek açık kalır, sonra kopar (deterministik yeniden bağlanma)."""
    class BekleyenWS(SahteWS):
        async def recv(self):
            if self.mesajlar:
                return await super().recv()                  # önce kuyruktaki mesajlar işlenir
            while not kosul():
                await asyncio.sleep(0.005)
            raise ConnectionError("kapandı")
    return BekleyenWS


def test_c_yeniden_baglanmada_pozisyonlar_tazelenir(tmp_path):
    sayac = {"n": 0}

    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            sayac["n"] += 1
            return durum(("BTC", 10.0)) if sayac["n"] == 1 else durum(("ETH", -4.0))      # ikinci okumada BTC kapanmış, ETH short açılmış
        return []
    ws_sinifi = _once_bekle(lambda: ("aaaa", "BTC") in kos.din.risk.lider)                 # 1. bağlantı ilk okuma bitince kopar
    din, ozet = kos(post, [[], []], tmp_path, ws_sinifi=ws_sinifi, sure=0.6)
    assert ozet["genel"]["yeniden_baglanma"] >= 1 and ozet["genel"]["baslangic_poz_okundu"] >= 2
    assert ("aaaa", "BTC") not in din.risk.lider and din.risk.lider[("aaaa", "ETH")] == -4.0   # eski izleme silindi, REST gerçek


def test_tazeleme_hatasi_onceki_izlemeyi_korur(tmp_path):
    sayac = {"n": 0}

    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            sayac["n"] += 1
            if sayac["n"] == 1:
                return durum(("BTC", 10.0))
            raise TimeoutError("x")
        return []
    ws_sinifi = _once_bekle(lambda: ("aaaa", "BTC") in kos.din.risk.lider)
    din, ozet = kos(post, [[], []], tmp_path, ws_sinifi=ws_sinifi, sure=0.6)
    assert din.risk.lider[("aaaa", "BTC")] == 10.0 and ozet["genel"]["baslangic_poz_hata"] >= 1 and ozet["genel"]["baslangic_poz_okundu"] == 1


def test_hip3_dex_pozisyonu_dinleyicide_okunur(tmp_path):
    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            return durum(("xyz:GOLD", 2.0)) if yuk.get("dex") == "xyz" else durum()
        return []
    din, ozet = kos(post, [[10]], tmp_path, dex_adlari=["xyz"])
    assert din.risk.lider[("aaaa", "xyz:GOLD")] == 2.0


def test_risk_kapaliyken_rest_okumasi_yapilmaz(tmp_path):
    cagri = []
    din = d.Dinleyici(IZ, ["BTC"], None, lambda y: cagri.append(y), tmp_path)

    async def dene():
        din._bas_baslat()
        await asyncio.sleep(0.05)
    asyncio.run(dene())
    assert cagri == [] and "baslangic_poz_hata" not in din.olcum.genel


def test_dinleyici_hala_pandas_gerektirmez():
    import subprocess
    import sys
    kod = "import sys, copytrade.dinleyici; assert 'pandas' not in sys.modules and 'numpy' not in sys.modules"
    assert subprocess.run([sys.executable, "-c", kod], capture_output=True, text=True).returncode == 0


# ------------------------------------------------------------------ 429 koruması ve arka plan (lider kararı)
def test_varsayilan_bekleme_ve_aralik_lider_karari():
    a = d.Ayar()
    assert (a.baslangic_bekleme_sn, a.rest_istek_ara_sn, a.baslangic_yeniden_sn, a.rest_bekleme_sn) == ((2.0, 5.0, 15.0), 0.5, 300.0, (2.0, 5.0, 15.0))


def test_a_429_yeniden_deneme_basari(tmp_path):
    cagrilar = []

    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            cagrilar.append(1)
            if len(cagrilar) <= 2:
                raise Http429("HTTP Error 429")                    # 1. ve 2. istek 429
            return durum(("BTC", 10.0))
        return []
    din, ozet = kos(post, [[100, trades_a(1, T + 50)]], tmp_path)
    g = ozet["genel"]
    assert (g["baslangic_poz_okundu"], g["baslangic_poz_hata"], g["baslangic_poz_yeniden_deneme"], g["baslangic_poz_bekleyen"]) == (1, 0, 2, 0)
    assert len(cagrilar) == 3 and din.risk.lider[("aaaa", "BTC")] >= 10.0        # 3. deneme başarılı (+ varsa okumadan sonraki dolum)


def test_b_uc_hata_sonra_arka_plan_denemesiyle_basari(tmp_path):
    cagrilar = []

    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            cagrilar.append(1)
            if len(cagrilar) <= 4:                                 # ilk deneme + 3 yeniden deneme hep hata
                raise Http429("HTTP Error 429")
            return durum(("BTC", 10.0))                            # 5. istek = ilk arka plan denemesi
        return []
    # okuma bitmeden gelen dolum "düz varsayımı" ile işlenir; sonra başarılı okuma izlemeyi gerçeğe çevirir
    ws_sinifi = _once_bekle(lambda: ("aaaa", "BTC") in kos.din.risk.lider and kos.din.risk.bilinen)
    din, ozet = kos(post, [[trades_a(1, T + 50)]], tmp_path, ws_sinifi=ws_sinifi, sure=0.5)
    g = ozet["genel"]
    assert g["baslangic_poz_hata"] == 1 and g["baslangic_poz_yeniden_deneme"] == 3 and g["baslangic_poz_arka_plan"] == 1
    assert g["baslangic_poz_okundu"] >= 1 and g["baslangic_poz_bekleyen"] == 0
    assert ozet["risk"]["lider_pozisyon_varsayimi"] == 1 and ozet["risk"]["baslangic_bilinen_trader"] == 1       # varsayım yalnız okuma başarana kadar
    assert din.risk.lider[("aaaa", "BTC")] == 10.0


def test_b2_arka_plandaki_adres_bekleyen_sayilir(tmp_path):
    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            raise Http429("HTTP Error 429")
        return []
    din, ozet = kos(post, [[]], tmp_path, ayar_ek=dict(baslangic_yeniden_sn=10.0), sure=0.3)
    # çalışma bitince görevler iptal edilir: bekleyen göstergesi geri 0'a iner, hata bir kez sayılmıştır
    assert ozet["genel"]["baslangic_poz_hata"] == 1 and ozet["genel"]["baslangic_poz_bekleyen"] == 0 and ozet["genel"]["baslangic_poz_okundu"] == 0


def test_c_okuma_surerken_gelen_dolumlar_olculmeye_devam_eder(tmp_path):
    """REST okuması bir olay işlenene dek BLOKLU; WS akışı okumayı beklemiyorsa olay işlenir ve okuma serbest kalır (aksi halde kilitlenir -> test zaman aşımı)."""
    import threading
    islendi = threading.Event()

    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            assert islendi.wait(5), "WS akışı REST okumasını bekledi (bloklandı)"
            return durum(("BTC", 10.0))
        return []
    saat = Saat(ms=T)
    ws = SahteWS([100, trades_a(1, T + 50), trades_a(2, T + 60)], "bekle", saat)

    async def baglan():
        return ws
    risk = RiskDefteri({"aaaa"}, kurallar(50.0), baslangic_ms=T)
    din = d.Dinleyici(IZ, ["BTC"], baglan, post, tmp_path, d.Ayar(sure_sn=0.5, geri_cekilme_ilk_sn=0.01, **HIZLI), saat.saat_ms, risk=risk)
    olay = din.olcum.olay

    def izle(o):
        sonuc = olay(o)
        if din.olcum.toplam["aaaa"].gecikme:
            islendi.set()
        return sonuc
    din.olcum.olay = izle
    ozet = asyncio.run(din.calis())
    assert ozet["toplam"]["aaaa"]["n"] == 2 and ozet["genel"]["trades_mesaj"] == 2           # okuma sürerken iki dolum da ölçüldü
    assert ozet["toplam"]["aaaa"]["gecikme_max_sn"] <= 0.1                                    # gecikme okuma beklemesiyle şişmedi (sahte saat: 50-60 ms)
    assert ozet["genel"]["baslangic_poz_okundu"] == 1 and ozet["risk"]["lider_pozisyon_varsayimi"] == 1


def test_istekler_arasi_en_az_ara_suresi(tmp_path):
    zamanlar = []
    import time as _t

    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            zamanlar.append(_t.monotonic())
            return durum()
        return []
    kos(post, [[]], tmp_path, dex_adlari=["xyz", "flx"], ayar_ek=dict(rest_istek_ara_sn=0.05), sure=0.5)
    assert len(zamanlar) >= 3 and all(b - a >= 0.045 for a, b in zip(zamanlar, zamanlar[1:]))   # 3 dex isteği (ana + 2) en az 50 ms arayla


def test_okuma_ani_dex_basina_cift_sayim_korumasi():
    rd = yeni()
    rd.baslangic_ayarla("aaaa", {"BTC": 10.0, "xyz:GOLD": 2.0}, {"": T + 1000, "xyz": T + 6000})   # ana dex 1. sn, xyz 6. sn okundu
    dolum(rd, coin="xyz:GOLD", sz=1, bas=None, t=T + 4000)         # xyz okumasından ÖNCE: dahil, eklenmez
    dolum(rd, coin="BTC", sz=1, bas=None, t=T + 4000)              # ana dex okumasından SONRA: yeni dolum, eklenir
    assert rd.lider[("aaaa", "xyz:GOLD")] == 2.0 and rd.lider[("aaaa", "BTC")] == 11.0


def test_dolgu_eski_dolum_okumadan_tazeyi_ezmez():
    """Arka plan dolgusu (startPosition'lı, okumadan ÖNCEki dolum) REST okumasının tazeliğini bozmaz."""
    rd = yeni()
    rd.baslangic_ayarla("aaaa", {"BTC": 7.0}, T + 5000)
    k = dolum(rd, sz=2, bas=3.0, t=T + 1000)                       # eski dolum: o an trader 3 -> 5; izleme 7 kalmalı
    assert rd.lider[("aaaa", "BTC")] == 7.0 and k[0]["aksiyon"] == "add"
    dolum(rd, sz=1, bas=7.0, t=T + 9000)                           # okumadan sonraki dolum izlemeyi sürdürür
    assert rd.lider[("aaaa", "BTC")] == 8.0


def test_baslangic_hata_turu_sayilir_ve_journal_tek_satir_adres_yok(tmp_path, capsys):
    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            raise Http429()
        return []
    din, ozet = kos(post, [[]], tmp_path, ayar_ek=dict(baslangic_yeniden_sn=10.0), sure=0.3)
    g = ozet["genel"]
    assert g["baslangic_poz_hata"] >= 1 and g["baslangic_poz_hata_tur"] == {"HTTP 429": g["baslangic_poz_hata"]}       # tükenen tur başına, SON hatanın sınıfı
    assert sum(g["baslangic_poz_hata_tur"].values()) == g["baslangic_poz_hata"]
    satirlar = [s for s in capsys.readouterr().err.splitlines() if "kaynak=baslangic_poz" in s]
    assert len(satirlar) >= 4 and set(satirlar) == {"UYARI REST hatası kaynak=baslangic_poz trader=aaaa tur=HTTP 429"} and all("0x" not in s for s in satirlar)
    assert "0x" not in (tmp_path / "ozet.json").read_text()
