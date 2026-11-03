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


def kos(post, baglantilar, tmp_path, dex_adlari=None, sure=0.4):
    saat = Saat(ms=T)
    ws_listesi = [SahteWS(m, "kes", saat) for m in baglantilar]
    sira = {"i": 0}

    async def baglan():
        if sira["i"] >= len(ws_listesi):
            ws_listesi.append(SahteWS([], "bekle", saat))
        ws = ws_listesi[sira["i"]]
        sira["i"] += 1
        return ws
    risk = RiskDefteri({"aaaa"}, kurallar(50.0), baslangic_ms=T)
    din = d.Dinleyici(IZ, ["BTC"], baglan, post, tmp_path, d.Ayar(sure_sn=sure, geri_cekilme_ilk_sn=0.01, geri_cekilme_max_sn=0.02), saat.saat_ms,
                      risk=risk, risk_gunlugu=KararGunlugu(tmp_path), dex_adlari=dex_adlari)
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


def test_dinleyici_baslangicta_yalniz_ilk11_adreslerini_okur_ve_miras_ekleme_reddedilir(tmp_path):
    okunan = []

    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            okunan.append(yuk["user"])
            return durum(("BTC", 10.0))
        return []
    din, ozet = kos(post, [[100, trades_a(1, T + 50)]], tmp_path)
    assert set(okunan) == {A} and ozet["genel"]["baslangic_poz_okundu"] >= 1 and ozet["genel"]["baslangic_poz_hata"] == 0
    assert ozet["risk"]["ret"] == {"miras_pozisyon": 1} and ozet["risk"]["lider_pozisyon_varsayimi"] == 0 and ozet["risk"]["acik_pozisyon"] == 0


def test_c_yeniden_baglanmada_pozisyonlar_tazelenir(tmp_path):
    sayac = {"n": 0}

    def post(yuk):
        if yuk["type"] == "clearinghouseState":
            sayac["n"] += 1
            return durum(("BTC", 10.0)) if sayac["n"] == 1 else durum(("ETH", -4.0))      # ikinci okumada BTC kapanmış, ETH short açılmış
        return []
    din, ozet = kos(post, [[10], [10]], tmp_path)            # iki bağlantı da koptu, üçüncü bekler
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
    din, ozet = kos(post, [[10], [10]], tmp_path)
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
    asyncio.run(din.baslangic_pozisyonlari())
    assert cagri == [] and "baslangic_poz_hata" not in din.olcum.genel


def test_dinleyici_hala_pandas_gerektirmez():
    import subprocess
    import sys
    kod = "import sys, copytrade.dinleyici; assert 'pandas' not in sys.modules and 'numpy' not in sys.modules"
    assert subprocess.run([sys.executable, "-c", kod], capture_output=True, text=True).returncode == 0
