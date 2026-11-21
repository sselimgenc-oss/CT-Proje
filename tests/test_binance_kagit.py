"""K-81 Aşama A: Binance KÂĞIT katmanı. Ağsız (sahte Binance HTTP + sahte HL); elle hesaplanmış örnekler.
Kapsam: eşleme, yuvarlama/minNotional, dolum fiyatı yönü, ücret, fonlama, K-74 Binance uyarlaması, erişim yokken HL motorunun etkilenmemesi, paralel defterlerin bağımsızlığı, fark parametresi (null/değerli)."""
import json

import pytest

from copytrade.canli import binance_kagit as bk
from copytrade.canli import hesap as hs
from copytrade.canli import motor as mt
from copytrade.canli import pano
from copytrade.canli import telegram as tg
from copytrade.canli.binance_eslesme import NEDEN_DOGRULANMADI, NEDEN_YOK, EslemeTablosu
from copytrade.canli.binance_piyasa import BinanceErisimYok, BinanceHata, BinancePiyasa, piyasa_post
from copytrade.canli.binance_yurutucu import BinanceKagitYurutucu, adim_yuvarla, tick_limit
from copytrade.canli.yurutucu import SanalYurutucu
from tests.test_canli_motor import RULES, SAAT, SahteHL, SahteTG, Saat, adr, kadro, olay, satir

TABLO = EslemeTablosu.yukle()


class SahteBinance:
    """`get(url, params) -> (kod, metin)`: exchangeInfo / premiumIndex / fundingInfo / depth / bookTicker. `kod` != 200 → o HTTP kodu (451 testi)."""

    def __init__(self):
        self.kod = 200
        self.istekler: list[str] = []
        self.semboller = {                                         # sembol -> (durum, tick, adım, min_qty, min_nosyonel)
            "BTCUSDT": ("TRADING", "0.1", "0.001", "0.001", "100"), "ETHUSDT": ("TRADING", "0.01", "0.001", "0.001", "20"), "SOLUSDT": ("TRADING", "0.01", "1", "1", "5"),
            "1000PEPEUSDT": ("TRADING", "0.0000001", "1", "1", "5"), "NVDAUSDT": ("TRADING", "0.01", "0.01", "0.01", "5"), "VADELIUSDT": ("TRADING", "0.01", "1", "1", "5"), "SETTLEUSDT": ("SETTLING", "0.01", "1", "1", "5")}
        self.defterler = {"ETHUSDT": {"bids": [("2000.00", "0.5"), ("1999.00", "50")], "asks": [("2001.00", "0.005"), ("2002.00", "100")]},
                          "BTCUSDT": {"bids": [("100.3", "50")], "asks": [("100.5", "50")]},
                          "SOLUSDT": {"bids": [("99.90", "5000")], "asks": [("100.10", "5000")]}}
        self.markalar = {"ETHUSDT": ("2000.50", "0.0008"), "BTCUSDT": ("100.40", "0.0001"), "SOLUSDT": ("100.00", "-0.0004")}
        self.aralik = [{"symbol": "ETHUSDT", "fundingIntervalHours": 4}]

    def __call__(self, url, params=None):
        self.istekler.append(url.rsplit("/fapi", 1)[-1])
        if self.kod != 200:
            return self.kod, "{}"
        yol = url.split("fapi.binance.com", 1)[1]
        if yol == "/fapi/v1/exchangeInfo":
            return 200, json.dumps({"symbols": [{"symbol": s, "status": d, "contractType": "TRADIFI_PERPETUAL" if s == "NVDAUSDT" else ("CURRENT_QUARTER" if s == "VADELIUSDT" else "PERPETUAL"), "quoteAsset": "USDT", "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": t}, {"filterType": "LOT_SIZE", "stepSize": st, "minQty": mq}, {"filterType": "MIN_NOTIONAL", "notional": mn}]}
                for s, (d, t, st, mq, mn) in self.semboller.items()]})
        if yol == "/fapi/v1/premiumIndex":
            return 200, json.dumps([{"symbol": s, "markPrice": m, "lastFundingRate": f, "nextFundingTime": 1} for s, (m, f) in self.markalar.items()])
        if yol == "/fapi/v1/fundingInfo":
            return 200, json.dumps(self.aralik)
        if yol == "/fapi/v1/depth":
            d = self.defterler[params["symbol"]]
            return 200, json.dumps({"bids": [list(x) for x in d["bids"]], "asks": [list(x) for x in d["asks"]]})
        if yol == "/fapi/v1/ticker/bookTicker":
            d = self.defterler[params["symbol"]]
            return 200, json.dumps({"bidPrice": d["bids"][0][0], "askPrice": d["asks"][0][0]})
        raise AssertionError(yol)


def kural(**ek):
    return {**RULES, "binance_kagit_gecikme_ms": 0, "binance_kagit_fark_bp": None, **ek}


def yurutucu(bn=None, **ek):
    bn = bn or SahteBinance()
    r = kural(**ek)
    return BinanceKagitYurutucu(BinancePiyasa(r, bn), TABLO, r, saat_ms=lambda: 1_000, uyku=lambda s: None), bn


# ===================================================================================== eşleme
def test_eslesme_ana_dex_k_coin_hip3_ve_yok_nedenleri():
    e, n = TABLO.coz("BTC")
    assert (e.binance, e.carpan, e.dogrulandi, e.tur, n) == ("BTCUSDT", 1.0, True, "kripto", None)
    e, n = TABLO.coz("kPEPE")
    assert (e.binance, e.carpan, n) == ("1000PEPEUSDT", 1.0, None)                              # çarpanlı: HL k = 1000, Binance 1000PEPE aynı birim
    e, n = TABLO.coz("xyz:NVDA")
    assert (e.binance, e.tur, n) == ("NVDAUSDT", "tradfi", None) and TABLO.coz("io:NVDA")[0].binance == "NVDAUSDT"          # io: ve xyz: aynı sembol
    e, n = TABLO.coz("xyz:SPCX")
    assert e is not None and e.dogrulandi is False and n == NEDEN_DOGRULANMADI and e.tur == "preipo"
    for c in ("PURR", "xyz:XYZ100", "@107", "PURR/USDC", "xyz:BILINMEYEN", "kXYZ"):
        assert TABLO.coz(c) == (None, NEDEN_YOK)
    assert TABLO.coz("kLUNC")[1] == NEDEN_DOGRULANMADI                                          # çarpanı doğrulanmamış k-coin


def test_eslesme_tablosu_gecersiz_carpan_reddedilir_ve_carpanli_birim():
    with pytest.raises(ValueError):
        EslemeTablosu({"satirlar": {"X": {"binance": "XUSDT", "carpan": 0}}})
    t = EslemeTablosu({"satirlar": {"kDOGS": {"binance": "DOGSUSDT", "carpan": 1000, "dogrulandi": True}}})
    assert t.coz("kDOGS")[0].carpan == 1000 and t.hl_coinleri("DOGSUSDT") == ["kDOGS"] and "DOGSUSDT" in t.semboller()


# ===================================================================================== yuvarlama / minNotional
def test_adim_ve_tick_yuvarlama():
    assert adim_yuvarla(0.01363, 0.001, "asagi") == pytest.approx(0.013) and adim_yuvarla(0.0135, 0.001, "yakin") == pytest.approx(0.014)
    assert adim_yuvarla(2003.014, 0.01, "yukari") == pytest.approx(2003.02) and adim_yuvarla(0.3, 0.1, "asagi") == pytest.approx(0.3)      # kayan nokta artığı bir adım kaydırmaz
    assert tick_limit(2001.0, 0.001, "B", 0.01) == pytest.approx(2003.0)                         # 2001 × 1,001 = 2003,001 → tick'e AŞAĞI
    assert tick_limit(2000.0, 0.001, "A", 0.01) == pytest.approx(1998.0)                         # 1998,0 → yukarı yuvarlama (zaten ızgarada)
    assert tick_limit(100.0, 0.0, "B", 0.1) == 100.0 and tick_limit(100.0, 0.0, "A", 0.1) == 100.0


def test_acilis_miktari_adima_asagi_yuvarlanir_slot_asilmaz():
    y, _ = yurutucu()
    d = y.emir("ETH", "B", 27.27, False)                                                         # ETH step 0,001: 27,27 / 2001 = 0,013627 → 0,013
    assert d.durum == "dolu" and d.sz == pytest.approx(0.013) and d.usd_dolan <= 27.27 and d.usd_dolan > 27.27 - 2.1


def test_min_nosyonel_alti_acilis_atlanir_reduceonly_muaf():
    y, _ = yurutucu()
    d = y.emir("BTC", "B", 27.27, False)                                                         # BTCUSDT minNotional 100 (arastirma §4 iddiası): 27 $ açılış yok
    assert d.durum == "dolmadi" and d.neden == "binance_min_nosyonel" and d.sz == 0 and y.neden_say["binance_min_nosyonel"] == 1
    d2 = y.emir("BTC", "A", 27.27, True, acik_sz=0.272)                                          # azaltma/kapanış reduceOnly: minNotional muaf (DOĞRULANMADI varsayım, bayrak true)
    assert d2.durum in ("dolu", "kismi") and d2.sz > 0
    y2, _ = yurutucu(binance_reduce_min_nosyonel_muaf=False)
    assert y2.emir("BTC", "A", 27.27, True, acik_sz=0.272).neden == "binance_min_nosyonel"
    d3 = y.emir("ETH", "B", 1.0, False)                                                          # 1 $ / 2001 = 0,0005 < adım 0,001 → miktar 0 → atlanır
    assert (d3.durum, d3.neden) == ("red", "binance_min_nosyonel")


def test_kapanis_pozisyonu_asmaz_ve_tam_kapanis_dolu():
    y, _ = yurutucu()
    d = y.emir("ETH", "A", 500.0, True, acik_sz=0.013)                                           # istenen 500 $ ama açık 0,013 ETH: kırpılır, TAM kapanış → dolu
    assert d.durum == "dolu" and d.sz == pytest.approx(0.013) and y.kapanis_say == 1


# ===================================================================================== dolum yönü + kayma + ücret
def test_alista_ask_satista_bid_yurunur_boyuta_gore_kayma():
    y, bn = yurutucu()
    a = y.emir("ETH", "B", 2001.0 * 0.005 + 2002.0 * 0.008, False)                               # 0,013 ETH: 0,005 @2001 + 0,008 @2002 (iki seviye)
    ort = (0.005 * 2001.0 + 0.008 * 2002.0) / 0.013
    assert a.px == pytest.approx(ort) and a.referans_px == 2001.0 and a.px > 2001.0              # alışta ASK tarafı: bid'den (2000) yüksek, en iyi ask'tan kötü
    assert a.kayma_oran == pytest.approx((ort - 2001.0) / 2001.0) and a.kayma_oran > 0           # + = aleyhimize
    y2, _ = yurutucu()
    s = y2.emir("ETH", "A", 2000.0 * 0.5 * 0.99, True, acik_sz=1.0)                              # satış: bid 2000 (0,5 ETH var) ≤ bid
    assert s.px <= 2000.0 and s.referans_px == 2000.0 and s.kayma_oran >= 0
    assert a.ek["binance_sembol"] == "ETHUSDT" and a.ek["yurutucu"] == "binance_kagit" and a.ek["binance_ask"] == 2001.0 and a.ek["binance_bid"] == 2000.0


def test_ioc_bandi_acilista_dolmayani_atlar_kapanista_bantsiz_yedek():
    bn = SahteBinance()
    bn.defterler["ETHUSDT"] = {"bids": [("2000.00", "0.001"), ("1900.00", "50")], "asks": [("2001.00", "0.001"), ("2100.00", "50")]}
    y, _ = yurutucu(bn)
    d = y.emir("ETH", "B", 2001.0 * 0.01, False)                                                 # 0,009 ETH ister: 0,001 @2001 band içi; 2100 band dışı (10 bp) → KISMİ
    assert d.durum == "kismi" and d.sz == pytest.approx(0.001) and d.px == pytest.approx(2001.0)
    c = y.emir("ETH", "A", 1900.0 * 0.003, True, acik_sz=0.003)                                  # kapanış: bid 2000 (0,001) + 1900 (0,002): band (10 bp) dışı kısım reduceOnly MARKET gibi dolar
    assert c.durum == "dolu" and c.sz == pytest.approx(0.003) and c.ek.get("market_yedek") is True and c.px < 2000.0


def test_ucret_binance_taker_anahtarindan_hl_anahtari_degil():
    y, _ = yurutucu()
    d = y.emir("ETH", "B", 27.27, False)
    assert d.ucret == pytest.approx(d.usd_dolan * 0.0005) and d.ucret != pytest.approx(d.usd_dolan * 0.00045)
    y2, _ = yurutucu(binance_taker=0.00045)
    d2 = y2.emir("ETH", "B", 27.27, False)
    assert d2.ucret == pytest.approx(d2.usd_dolan * 0.00045)


def test_k_coin_carpan_birimi_hl_birimine_cevrilir():
    t = EslemeTablosu({"satirlar": {"kXYZ": {"binance": "ETHUSDT", "carpan": 1000, "dogrulandi": True}}})      # Binance fiyatı × 1000 = HL fiyatı; HL miktarı = Binance / 1000
    bn = SahteBinance()
    r = kural()
    y = BinanceKagitYurutucu(BinancePiyasa(r, bn), t, r, saat_ms=lambda: 1_000, uyku=lambda s: None)
    d = y.emir("kXYZ", "B", 30.0, False)                                                          # 30 / 2001 = 0,01499 → 0,014 ETH (0,005 @2001 + 0,009 @2002)
    ort = (0.005 * 2001.0 + 0.009 * 2002.0) / 0.014
    assert d.px == pytest.approx(ort * 1000) and d.sz == pytest.approx(0.014 / 1000) and d.usd_dolan == pytest.approx(ort * 0.014)          # nosyonel $ aynı


def test_fark_parametresi_null_dogrudan_fiyat_deger_aleyhe_uygulanir():
    y0, _ = yurutucu()
    assert y0.emir("ETH", "B", 27.27, False).ek["fark_bp_uygulanan"] is None
    px_ham = yurutucu()[0].emir("ETH", "B", 27.27, False).ek["binance_dolum_px"]               # taze yürütücü: ardışık emirler defter seviyelerini düşer (T4b §9)
    y1, _ = yurutucu(binance_kagit_fark_bp=10.0)                                                  # 10 bp aleyhimize
    al = y1.emir("ETH", "B", 27.27, False)
    assert al.ek["binance_dolum_px"] == pytest.approx(px_ham * 1.001) and al.ek["fark_bp_uygulanan"] == 10.0
    y2, _ = yurutucu(binance_kagit_fark_bp=10.0)
    sat = y2.emir("ETH", "A", 20.0, True, acik_sz=0.5)
    y3, _ = yurutucu()
    assert sat.px == pytest.approx(y3.emir("ETH", "A", 20.0, True, acik_sz=0.5).px * 0.999)       # satışta fiyat DÜŞER (aleyhimize)
    y4, _ = yurutucu(binance_kagit_fark_bp="saçma")
    assert y4.ozet()["binance"]["fark_bp"] is None and y4.emir("ETH", "B", 27.27, False).ek["fark_bp_uygulanan"] is None          # geçersiz değer = düzeltme yok


def test_gecikme_defterden_once_beklenir():
    uyunan = []
    bn = SahteBinance()
    r = kural(binance_kagit_gecikme_ms=250)
    y = BinanceKagitYurutucu(BinancePiyasa(r, bn), TABLO, r, saat_ms=lambda: 1_000, uyku=uyunan.append)
    y.emir("ETH", "B", 27.27, False)
    assert uyunan == [0.25] and bn.istekler.index("/v1/depth") > 0


def test_islem_yok_status_acilis_atlanir_kapanis_denenir():
    bn = SahteBinance()
    bn.semboller["ETHUSDT"] = ("BREAK", "0.01", "0.001", "0.001", "20")
    y, _ = yurutucu(bn)
    assert y.acilis_kapisi("ETH") == "binance_islem_yok" and y.emir("ETH", "B", 27.27, False).neden == "binance_islem_yok"
    assert y.emir("ETH", "A", 20.0, True, acik_sz=0.01).durum in ("dolu", "kismi")                # kapanış status'a bakmaz (açık pozisyon çıkabilmeli)


def test_acilis_kapisi_eslemesiz_ve_dogrulanmamis():
    y, _ = yurutucu()
    assert y.acilis_kapisi("PURR") == "binance_eslesme_yok" and y.acilis_kapisi("xyz:SPCX") == "binance_eslesme_dogrulanmadi" and y.acilis_kapisi("ETH") is None
    assert y.emir("xyz:SPCX", "B", 50.0, False).neden == "binance_eslesme_dogrulanmadi" and y.emir("PURR", "A", 50.0, True, acik_sz=1).neden == "binance_eslesme_yok"


# ===================================================================================== fonlama
def hl_meta_ctx():
    return [{"universe": [{"name": "ETH"}, {"name": "SOL"}, {"name": "PURR"}]}, [{"funding": "0.0000125", "markPx": "1"}, {"funding": "0.0000125", "markPx": "1"}, {"funding": "0.0000125", "markPx": "1"}]]


def test_fonlama_binance_orani_saatlige_cevrilir_aralik_ve_yedek():
    bn = SahteBinance()
    piyasa = BinancePiyasa(kural(), bn)
    p = piyasa_post(lambda y: hl_meta_ctx() if y["type"] == "metaAndAssetCtxs" else {}, piyasa, TABLO)
    meta, ctx = p({"type": "metaAndAssetCtxs"})[:2]
    assert float(ctx[0]["funding"]) == pytest.approx(0.0008 / 4)                                  # ETH: fundingInfo 4 saat
    assert float(ctx[1]["funding"]) == pytest.approx(-0.0004 / 8)                                 # SOL: varsayılan 8 saat; işaret korunur (negatif = long alır)
    assert ctx[2]["funding"] == "0.0000125" and piyasa.fonlama_kaynak == "binance"                # PURR eşlemesiz: HL değeri
    bn.kod = 451
    piyasa2 = BinancePiyasa(kural(), bn)
    p2 = piyasa_post(lambda y: hl_meta_ctx(), piyasa2, TABLO)
    r = p2({"type": "metaAndAssetCtxs"})
    assert r[1][0]["funding"] == "0.0000125" and piyasa2.fonlama_kaynak == "hl_yedek"             # erişilemezse HL fonlaması + kaynak işareti


def test_motor_funding_oku_binance_orani_ve_kayit_kaynagi(tmp_path):
    m, hl, saat, _ = bin_motor(tmp_path)
    m.baslat()
    oranlar = m.funding_oku()
    assert oranlar["ETH"] == pytest.approx(0.0008 / 4) and oranlar["SOL"] == pytest.approx(-0.0004 / 8)
    m.hesap.poz[adr(1)] = {"ETH": __import__("copytrade.canli.hesap", fromlist=["Poz"]).Poz(sz=0.1, giris=2000.0, acilis_ms=0)}
    m.son_funding_saat = saat() // 3_600_000 - 1
    m.marks["ETH"] = 2000.0
    f = m.funding_uygula(oranlar, saat())
    assert f == pytest.approx(-0.1 * 2000.0 * 0.0002)                                             # long, pozitif oran: öder
    assert _kayit(tmp_path / "kayit" / "binance_kagit", "funding")[-1]["funding_kaynak"] == "binance"


# ===================================================================================== K-74 Binance uyarlaması
def test_tasfiye_binance_mmr_hl_formulunden_ayrisir_ve_hl_ayni_kalir():
    hl = hs.tasfiye_fiyati(True, 100.0, 3.0, 3.0)                                                 # HL: azami 3 → mmr 1/6 → 80
    assert hl == pytest.approx(80.0)
    assert hs.tasfiye_fiyati(True, 100.0, 3.0, 3.0, mmr=0.005) == pytest.approx(100 * (2 / 3) / 0.995)       # Binance varsayılan mmr %0,5: ≈ 67,00
    assert hs.tasfiye_fiyati(False, 100.0, 3.0, None, mmr=0.005) == pytest.approx(100 * (4 / 3) / 1.005)
    assert hs.tasfiye_fiyati(True, 100.0, 3.0, 3.0, mmr=0.005, cum_oran=0.0025) == pytest.approx(100 * (2 / 3 - 0.0025) / 0.995)           # kademe bakım tutarı (cum) etkisi
    assert hs.mmr_kademe_bul(2000.0, [[0, 1000, 0.004, 0], [1000, 1e9, 0.005, 5]], 0.005) == (0.005, 5.0) and hs.mmr_kademe_bul(None, [[0, 1000, 0.004, 0]], 0.005) == (0.004, 0.0)
    assert hs.mmr_kademe_bul(10.0, None, 0.005) == (0.005, 0.0)


def test_hesap_mmr_yalniz_binance_surecinde_json_hl_ayni(tmp_path):
    h = hs.Hesap(1000.0)
    assert "mmr_varsayilan" not in h.to_json() and "mmr_kademe" not in h.to_json() and h.mmr_cum("BTC", 100.0, 1.0) == (None, 0.0)            # HL: anahtarlar yok, eski formül
    h.mmr_varsayilan, h.mmr_kademe = 0.005, {"BTC": [[0, 1000, 0.004, 0], [1000, 1e9, 0.005, 5]]}
    h2 = hs.Hesap.from_json(h.to_json())
    assert h2.mmr_varsayilan == 0.005 and h2.mmr_cum("BTC", 100.0, 20.0) == (0.005, 5.0 / 2000.0) and h2.mmr_cum("BTC", 100.0, 5.0) == (0.004, 0.0) and h2.mmr_cum("ETH", 100.0, 5.0) == (0.005, 0.0)


def test_k74_motor_binance_stop_orani_ve_sanal_tasfiye(tmp_path):
    mb, hlb, saatb, _ = bin_motor(tmp_path / "b")
    mh, hlh, saath, _ = hl_motor(tmp_path / "h")
    mb.baslat(); mh.baslat()
    for m in (mb, mh):
        m.hesap.maks_kaldirac["ETH"] = 3.0                                                        # HL azami 3x coin (K-74 VVV örneği)
    assert mb.hesap.mmr_varsayilan == 0.005 and mh.hesap.mmr_varsayilan is None
    assert mh._stop_orani("ETH", True, 2000.0, 0.20, 0.03) == pytest.approx(1 - 80 / 100 - 0.03)            # HL: tasfiye mesafesi %20 → stop %17
    assert mb._stop_orani("ETH", True, 2000.0, 0.20, 0.03) == pytest.approx(0.20)                           # Binance: mesafe ≈ %33 → stop üst sınır %20
    for m in (mb, mh):
        m.hesap.poz[adr(1)] = {"ETH": hs.Poz(sz=1.0, giris=100.0, acilis_ms=0, kaldirac=3.0)}
    mark = 75.0                                                                                   # 80 ile 67,0 arası: HL (azami 3) tasfiye eder, Binance (mmr %0,5) etmez
    assert len(mh.hesap.tasfiye_kontrol({"ETH": mark}, 1)) == 1 and len(mb.hesap.tasfiye_kontrol({"ETH": mark}, 1)) == 0
    ev = mb.hesap.tasfiye_kontrol({"ETH": 66.0}, 2)
    assert len(ev) == 1 and ev[0]["tasfiye_px"] == pytest.approx(100 * (2 / 3) / 0.995)           # tasfiye fiyatı Binance formülüyle


# ===================================================================================== motor entegrasyonu: paralel defterler
class SahteHL2(SahteHL):
    """SahteHL + metaAndAssetCtxs (funding) ve ETH/SOL meta."""

    def __call__(self, y):
        if y["type"] == "metaAndAssetCtxs":
            return hl_meta_ctx()
        if y["type"] == "meta":
            return {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}, {"name": "ETH", "szDecimals": 4, "maxLeverage": 25}]}
        return super().__call__(y)


def hl_motor(tmp_path, hl=None, saat=None, kurallar=None):
    rules = {**RULES, "canli_kasa_usd": 1000.0, **(kurallar or {})}
    hl, saat = hl or SahteHL2(), saat or Saat()
    k = kadro([satir(1, 1)], saat() - SAAT)
    m = mt.Motor(rules, SanalYurutucu(hl, rules), hl, tg.Telegram("123:AAH-x", "42", SahteTG()), tmp_path / "durum", tmp_path / "kayit", lambda: k, saat)
    return m, hl, saat, None


def bin_motor(tmp_path, hl=None, saat=None, bn=None, kurallar=None):
    rules = {**kural(), "canli_kasa_usd": 1000.0, **(kurallar or {})}
    hl, saat, bn = hl or SahteHL2(), saat or Saat(), bn or SahteBinance()
    piyasa = BinancePiyasa(rules, bn, saat)
    post = piyasa_post(hl, piyasa, TABLO)
    yur = BinanceKagitYurutucu(piyasa, TABLO, rules, saat, uyku=lambda s: None)
    k = kadro([satir(1, 1)], saat() - SAAT)
    m = mt.Motor(rules, yur, post, bk.sessiz_telegram(rules, arka_plan=False), tmp_path / "durum" / "binance_kagit", tmp_path / "kayit" / "binance_kagit", lambda: k, saat)
    m.bn, m.piyasa = bn, piyasa
    return m, hl, saat, bn


def test_paralel_defterler_ayni_sinyalde_bagimsiz_acar_kapar(tmp_path):
    saat, hl = Saat(), SahteHL2()
    mh, _, _, _ = hl_motor(tmp_path, hl, saat)
    mb, _, _, bn = bin_motor(tmp_path, hl, saat)
    mh.baslat(); mb.baslat()
    o = olay("a:1", adr(1), "ETH", "B", 15, 2000.0, 0.0, saat)                                    # aynı Olay iki motora
    sh, sb = mh.olay_isle(o), mb.olay_isle(o)
    assert [(x.eylem, x.karar) for x in sh] == [("ac", "emir")] == [(x.eylem, x.karar) for x in sb]
    emir_h = [k for k in _kayit(tmp_path / "kayit", "emir")]
    emir_b = [k for k in _kayit(tmp_path / "kayit" / "binance_kagit", "emir")]
    assert len(emir_h) == 1 and len(emir_b) == 1
    assert emir_h[0]["dolum_px"] == pytest.approx(2000.0) and "yurutucu" not in emir_h[0]                       # HL: l2Book ask 2000; kayıtta yeni alan YOK
    assert emir_b[0]["yurutucu"] == "binance_kagit" and emir_b[0]["dolum_px"] > 2001.0 and emir_b[0]["binance_sembol"] == "ETHUSDT" and emir_b[0]["cloid"] == emir_h[0]["cloid"]       # aynı sinyal, aynı cloid, Binance fiyatı
    assert emir_b[0]["trader_px"] == 2000.0 and emir_b[0]["binance_ask"] == 2001.0 and emir_b[0]["ucret"] == pytest.approx(emir_b[0]["usd_dolan"] * 0.0005)
    sz_h, sz_b = mh.hesap.sz(adr(1), "ETH"), mb.hesap.sz(adr(1), "ETH")
    assert sz_h == pytest.approx(27.2727 / 2000.0, abs=1e-6) and sz_b == pytest.approx(0.013) and sz_h != sz_b          # defterler farklı (adım yuvarlaması + Binance fiyatı)
    mb.hesap.poz[adr(1)]["ETH"].giris += 1.0                                                      # Binance defterini oynat: HL etkilenmez
    assert mh.hesap.poz[adr(1)]["ETH"].giris == pytest.approx(2000.0)
    # kapanış: yalnız Binance kapatılır, HL açık kalır
    sk = mb.olay_isle(olay("a:2", adr(1), "ETH", "A", 15, 2000.0, 15.0, saat))
    assert sk[0].eylem == "kapat" and mb.hesap.sz(adr(1), "ETH") == pytest.approx(0.0, abs=1e-9) and mh.hesap.sz(adr(1), "ETH") == pytest.approx(sz_h)
    assert (tmp_path / "durum" / "binance_kagit" / "hesap.json").exists() and not (tmp_path / "durum" / "binance_kagit" / "hesap.json").samefile(tmp_path / "durum" / "hesap.json")


def _kayit(dizin, tur):
    out = []
    for f in sorted(dizin.glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
    return [x for x in out if x["olay"] == tur]


def test_binance_eslemesiz_dogrulanmamis_ve_min_nosyonel_atlanir_nedenle_hl_acar(tmp_path):
    saat, hl = Saat(), SahteHL2()
    mb, _, _, _ = bin_motor(tmp_path, hl, saat, kurallar={"canli_coin_listesi": ["BTC", "xyz:SPCX", "PURR"]})          # K-86: coin listesi kapısı Binance eşleme kapısından ÖNCE; ikisini de sınamak için listeye alındı
    mb.baslat()
    s = mb.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))                      # BTCUSDT minNotional 100 > 27 $
    assert (s[0].karar, s[0].neden) == ("red", "binance_min_nosyonel")
    e = _kayit(tmp_path / "kayit" / "binance_kagit", "emir")
    assert e and e[0]["red_neden"] == "binance_min_nosyonel" and e[0]["durum"] == "dolmadi" and mb.hesap.sz(adr(1), "BTC") == 0 and mb.sayac["min_nosyonel"] == 1
    mb.mark("xyz:SPCX")
    s2 = mb._emir_isle(olay("a:2", adr(1), "xyz:SPCX", "B", 10, 100.0, 0.0, saat), adr(1), "ac", 0.0, 10.0, 0.0, saat(), False)
    assert (s2.karar, s2.neden) == ("atlandi", "binance_eslesme_dogrulanmadi")
    s3 = mb._emir_isle(olay("a:3", adr(1), "PURR", "B", 10, 100.0, 0.0, saat), adr(1), "ac", 0.0, 10.0, 0.0, saat(), False)
    assert (s3.karar, s3.neden) == ("atlandi", "binance_eslesme_yok")
    ey = _kayit(tmp_path / "kayit" / "binance_kagit", "emir_yok")
    assert {x["neden"] for x in ey} >= {"binance_eslesme_dogrulanmadi", "binance_eslesme_yok"}      # neden kayıtlı; karşı-olgu yolu (K-73 `_atla`) aynen


def test_marklar_binance_markindan_gelir_hl_motoru_hl_midinden(tmp_path):
    saat, hl = Saat(), SahteHL2()
    mb, _, _, _ = bin_motor(tmp_path, hl, saat)
    mh, _, _, _ = hl_motor(tmp_path, hl, saat)
    mb.baslat(); mh.baslat()
    mb.piyasa_oku(saat()); mh.piyasa_oku(saat())
    assert mb.marks["ETH"] == pytest.approx(2000.50) and mh.marks["ETH"] == 2000.0 and mb.marks["BTC"] == pytest.approx(100.40)
    assert mb.marks["SOL"] == pytest.approx(100.0)


# ===================================================================================== erişim yokken
def test_erisim_yok_binance_motor_mark_okumaz_hl_motoru_etkilenmez(tmp_path):
    saat, hl = Saat(), SahteHL2()
    mb, _, _, bn = bin_motor(tmp_path, hl, saat)
    mh, _, _, _ = hl_motor(tmp_path, hl, saat)
    mb.baslat(); mh.baslat()
    mb.piyasa_oku(saat())
    eski = mb.marks["ETH"]
    bn.kod = 451                                                                                  # Binance erişimi kapandı (önbellek TTL sonrası)
    saat.ms += 60_000
    mb.piyasa_oku(saat.ms)                                                                        # istisna YUKARI çıkmaz; önceki mark kalır
    assert mb.marks["ETH"] == eski and _kayit(tmp_path / "kayit" / "binance_kagit", "mark_okuma_hata")
    mh.piyasa_oku(saat.ms)                                                                        # HL motoru HL fiyatıyla çalışır
    assert mh.marks["ETH"] == 2000.0
    s = mh.olay_isle(olay("a:9", adr(1), "ETH", "B", 15, 2000.0, 0.0, saat))
    assert s[0].karar == "emir" and mh.hesap.sz(adr(1), "ETH") > 0                                 # HL açar
    sb = mb.olay_isle(olay("a:9", adr(1), "ETH", "B", 15, 2000.0, 0.0, saat))                     # Binance defteri okunamaz → emir YOK, uydurma fiyat yok
    assert sb[0].karar == "red" and sb[0].neden == "binance_erisim_yok" and mb.hesap.sz(adr(1), "ETH") == 0


def test_hazirla_ilk_erisim_451_tek_uyari_ve_cikis_4(tmp_path):
    bn = SahteBinance()
    bn.kod = 451
    uyarilar = []
    post, hizli, fab, piyasa, kod = bk.hazirla(RULES, lambda y: {}, lambda y: {}, get=bn, uyar=uyarilar.append)
    assert kod == bk.CIKIS_ERISIM_YOK == 4 and len(uyarilar) == 1 and "⚠️" in uyarilar[0] and "HL sanal motoru etkilenmedi" in uyarilar[0]
    bn2 = SahteBinance()
    uyarilar2 = []
    _, _, fab2, _, kod2 = bk.hazirla(RULES, lambda y: {}, lambda y: {}, get=bn2, uyar=uyarilar2.append)
    assert kod2 == 0 and uyarilar2 == [] and isinstance(fab2(), BinanceKagitYurutucu)
    bn3 = SahteBinance()
    bn3.kod = 503                                                                                 # geçici hata başlamayı engellemez (bekçi kesinti süresini izler)
    assert bk.hazirla(RULES, lambda y: {}, lambda y: {}, get=bn3, uyar=uyarilar2.append)[4] == 0 and uyarilar2 == []


def test_bekci_kesinti_suresi_asilinca_tek_uyari_motoru_durdurur(tmp_path):
    saat = Saat()
    mb, _, _, bn = bin_motor(tmp_path, SahteHL2(), saat)
    mb.baslat()
    uyarilar = []
    bekci = bk.Bekci(mb.piyasa, mb, uyarilar.append, 180.0)
    assert bekci.kontrol() is False                                                               # kesinti yok
    bn.kod = 451
    saat.ms += 20_000
    with pytest.raises(BinanceErisimYok):
        mb.piyasa.defter("ETHUSDT")
    assert bekci.kontrol() is False and not mb.dur_istendi                                        # 180 sn dolmadı
    saat.ms += 200_000
    assert bekci.kontrol() is True and mb.dur_istendi and mb.cikis_kodu == 4 and len(uyarilar) == 1
    assert bekci.kontrol() is False and len(uyarilar) == 1                                        # ikinci kez uyarmaz
    assert any(k["olay"] == "binance_erisim_yok" for k in _kayit(tmp_path / "kayit" / "binance_kagit", "binance_erisim_yok"))


def test_gecici_hata_ve_bozuk_yanit_binance_hatasi():
    class Bozuk(SahteBinance):
        def __call__(self, url, params=None):
            return (200, "bozuk json{") if self.kod == 200 else (self.kod, "")
    p = BinancePiyasa(kural(), Bozuk())
    with pytest.raises(BinanceHata):
        p.bilgi_tablosu()
    assert p.durum()["hata"] == 1 and p.kesinti_sn() >= 0 and p.erisim_testi() == "hata"
    ok = SahteBinance()
    ok.kod = 403
    assert BinancePiyasa(kural(), ok).erisim_testi() == "yok"


# ===================================================================================== Telegram satırı + pano
def test_telegram_tek_satir_binance_kagit_ve_bayat_uyarisi(tmp_path):
    simdi = 10_000_000
    (tmp_path / "binance_kagit").mkdir()
    ozet = {"yazildi_ms": simdi - 1000, "acik_pozisyon": 3, "kasa_usd": 10000.0, "ozsermaye_usd": 10004.2, "binance": {"kapanan": 12, "kayma_bp_medyan": 0.8}}
    (tmp_path / "binance_kagit" / "ozet.json").write_text(json.dumps(ozet), encoding="utf-8")
    assert bk.ozet_satiri(tmp_path, simdi) == "🅱️ Binance kâğıt: 3 açık · 12 kapanan · net +4,20 $ · kayma 0,8 bp"
    assert bk.ozet_satiri(tmp_path, simdi + 3_600_000).startswith("⚠️ Binance kâğıt: durdu")
    assert bk.ozet_satiri(tmp_path / "yok", simdi) is None


def test_hl_motoru_saatlik_ozete_binance_satiri_ekler_dosya_yokken_dokunmaz(tmp_path):
    saat, hl = Saat(), SahteHL2()
    tgp = SahteTG()
    rules = {**RULES, "canli_kasa_usd": 1000.0}
    k = kadro([satir(1, 1)], saat() - SAAT)
    m = mt.Motor(rules, SanalYurutucu(hl, rules), hl, tg.Telegram("123:AAH-x", "42", tgp), tmp_path / "durum", tmp_path / "kayit", lambda: k, saat)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "ETH", "B", 15, 2000.0, 0.0, saat))
    m.emir_ozeti(saat() + 3 * SAAT, zorla=True)
    ilk = [x for x in tgp.gonderilen if "emir" in x and "Son" in x]
    assert ilk and not any("Binance kâğıt" in x for x in tgp.gonderilen)                          # Binance süreci yok: mesaj AYNI
    (tmp_path / "durum" / "binance_kagit").mkdir()
    (tmp_path / "durum" / "binance_kagit" / "ozet.json").write_text(json.dumps({"yazildi_ms": saat() + 6 * SAAT - 1000, "acik_pozisyon": 1, "kasa_usd": 10000.0, "ozsermaye_usd": 10001.0, "binance": {"kapanan": 2}}), encoding="utf-8")
    m.olay_isle(olay("a:2", adr(1), "ETH", "A", 15, 2000.0, 15.0, saat))
    m.emir_ozeti(saat() + 6 * SAAT, zorla=True)
    assert sum("Binance kâğıt: 1 açık · 2 kapanan" in x for x in tgp.gonderilen) == 1               # tek satır, ayrı mesaj değil


def test_pano_binance_kiyas_karti_ve_veri_yok():
    hl = {"acik_pozisyon": 5, "kasa_usd": 10000.0, "ozsermaye_usd": 10010.0, "ortalama_kayma_trader": 0.0004, "emir": {"emir": 20, "atlandi": 3}}
    bn = {"acik_pozisyon": 4, "kasa_usd": 10000.0, "ozsermaye_usd": 9995.0, "ortalama_kayma_trader": 0.0009, "emir": {"emir": 18, "atlandi": 5}, "yazildi_ms": 1_000_000,
          "binance": {"neden_say": {"binance_eslesme_yok": 2}, "kayma_bp_medyan": 0.9, "kayma_bp_p90": 4.0, "fark_bp": None, "piyasa": {"fonlama_kaynak": "binance"}, "mmr_dogrulandi": False}}
    k = pano.binance_kiyas(hl, [], {"ozet": bn, "kayit": []})
    assert k["hl"]["net"] == pytest.approx(10.0) and k["binance"]["net"] == pytest.approx(-5.0) and k["binance"]["acik"] == 4 and k["neden_say"] == {"binance_eslesme_yok": 2}
    html = pano._binance_kiyas_html(k, 1_000_000 + 1000)
    assert "HL 5 · Binance 4" in html and "Binance&#x27;te karşılığı yok" in html and "DOĞRULANMADI" in html and 'class="uy"' not in html
    assert 'class="uy"' in pano._binance_kiyas_html(k, 1_000_000 + 3_600_000)                      # bayat veri uyarısı
    assert pano.binance_kiyas(hl, [], None) is None and "kurulu değil" in pano._binance_kiyas_html(None, 0)


def test_hl_kayit_ve_hesap_json_binance_alani_icermez(tmp_path):
    saat, hl = Saat(), SahteHL2()
    mh, _, _, _ = hl_motor(tmp_path, hl, saat)
    mh.baslat()
    mh.olay_isle(olay("a:1", adr(1), "ETH", "B", 15, 2000.0, 0.0, saat))
    e = _kayit(tmp_path / "kayit", "emir")[0]
    assert not any(k.startswith("binance") or k in ("yurutucu", "carpan", "market_yedek") for k in e)
    h = json.loads((tmp_path / "durum" / "hesap.json").read_text(encoding="utf-8"))
    assert "mmr_varsayilan" not in h and "mmr_kademe" not in h and "yurutucu" not in mh.pano_ek()


# ===================================================================================== main: --borsa binance_kagit
def _main_ortam(monkeypatch, bn):
    from copytrade.canli import binance_piyasa as bp
    from tests.test_canli_motor import n_kadro
    import time
    for ad in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CANLI_KIP", "CANLI_KASA_USD", "HL_API_CUZDAN_ANAHTARI", "HL_HESAP_ADRESI"):
        monkeypatch.delenv(ad, raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    hl = SahteHL2()
    monkeypatch.setattr(mt, "rest_post_olustur", lambda rules: hl)
    monkeypatch.setattr(mt, "http_kadro_oku", lambda rules, dal=None: n_kadro(3, int(time.time() * 1000)))
    monkeypatch.setattr(bp, "http_get_varsayilan", bn)
    return hl


def test_main_borsa_binance_kagit_gercek_kipte_reddedilir_erisim_yoksa_cikis_4(monkeypatch, tmp_path):
    bn = SahteBinance()
    _main_ortam(monkeypatch, bn)
    d = str(tmp_path / "durum")
    assert mt.main(["--kip", "gercek", "--borsa", "binance_kagit", "--durum-dizin", d]) == 3                      # yalnız sanal kip
    bn.kod = 451
    cagrildi = []

    async def sahte_calis(motor, sure_sn=None, **_):
        cagrildi.append(1)
        return {}
    monkeypatch.setattr(mt, "calis", sahte_calis)
    assert mt.main(["--kip", "sanal", "--borsa", "binance_kagit", "--sanal-kasa-usd", "10000", "--durum-dizin", d, "--kayit-dizin", str(tmp_path / "kayit")]) == 4 and cagrildi == []    # motor HİÇ başlamaz, durum dizini oluşmaz
    assert not (tmp_path / "durum" / "motor.json").exists()


def test_main_borsa_binance_kagit_kurulumu_ayri_kasa_sessiz_telegram_bekci(monkeypatch, tmp_path):
    bn = SahteBinance()
    _main_ortam(monkeypatch, bn)
    yakalanan = {}

    async def sahte_calis(motor, sure_sn=None, **_):
        yakalanan["m"] = motor
        motor.durum_yaz()
        return {}
    monkeypatch.setattr(mt, "calis", sahte_calis)
    d = tmp_path / "durum" / "binance_kagit"
    assert mt.main(["--kip", "sanal", "--borsa", "binance_kagit", "--sanal-kasa-usd", "10000", "--durum-dizin", str(d), "--kayit-dizin", str(tmp_path / "kayit" / "binance_kagit"), "--sure-sn", "1"]) == 0
    m = yakalanan["m"]
    assert isinstance(m.yurutucu, BinanceKagitYurutucu) and m.kip == "sanal" and m.kasa == 10000.0 and m.hesap.mmr_varsayilan == 0.005
    assert m.tg.token == "" and m.tg.chat_id == "" and hasattr(m.post, "piyasa")                                  # Telegram kanalı kapalı: ayrı işlem mesajı yok
    assert (d / "motor.json").exists() and not (tmp_path / "durum" / "motor.json").exists()                       # HL durum dizinine dokunmaz
    yakalanan.clear()
    assert mt.main(["--kip", "sanal", "--sanal-kasa-usd", "10000", "--durum-dizin", str(tmp_path / "hl"), "--kayit-dizin", str(tmp_path / "hlk"), "--sure-sn", "1"]) == 0
    h = yakalanan["m"]
    assert type(h.yurutucu) is SanalYurutucu and h.hesap.mmr_varsayilan is None and not hasattr(h.post, "piyasa") and h.tg.token == ""          # bayraksız çağrı: HL yolu eskisi gibi


def test_exchangeinfo_tradfi_perpetual_dahil_vadeli_haric():
    p = BinancePiyasa(kural(), SahteBinance())
    t = p.bilgi_tablosu()
    assert "NVDAUSDT" in t and t["NVDAUSDT"]["min_nosyonel"] == 5.0 and "VADELIUSDT" not in t and t["ETHUSDT"] == {"durum": "TRADING", "tick": 0.01, "step": 0.001, "min_qty": 0.001, "min_nosyonel": 20.0}
    y, _ = yurutucu()
    assert y.acilis_kapisi("xyz:NVDA") is None
