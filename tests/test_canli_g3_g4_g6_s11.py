"""Denetim G-3 (kaçan ters dönüş), G-4 (kapanışta kaldıraç ayarı yok), G-6 (perpDexs hatası önbelleğe alınmaz), S-11 (szDecimals önbelleği tazeleme, HIP-3 kapısı).
Ağsız; elle hesaplanmış altın örnekler."""
import sys
import types

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import yurutucu as yu
from tests.test_canli_motor import RULES, SahteHL, adr, kayitlar, kur, olay


# ================================================================================================ G-3
def test_g3_eylem_belirle_ters_pozisyonda_once_kapat_sonra_ac():
    e = mt.eylem_belirle
    assert e(-100, -300, 0.27) == ["kapat", "ac"]          # biz uzun, trader kısa ve kısayı büyütüyor (eskiden "artir" → ters yönde reduce-only OLMAYAN emir)
    assert e(-300, -100, 0.27) == ["kapat", "ac"]          # trader kısayı azaltıyor ama biz ters yöndeyiz
    assert e(100, 300, -0.27) == ["kapat", "ac"]
    assert e(10, 15, 5) == ["artir"] and e(-10, -4, -3) == ["azalt"] and e(10, -5, 4) == ["kapat", "ac"] and e(10, 0, -4) == ["kapat"]     # aynı yön: değişmedi


def test_g3_altin_kacan_ters_donus_once_27_dolar_reduce_only_kapat_sonra_hedefe_ac(tmp_path):
    """Kasa 1.000 → slot 1000/11 = 90,909 $; trader hesap 100.000 $.
    1) Trader 300 BTC alır @100 → biz 90,909 × 30.000 / 100.000 = 27,2727 $ uzun (ask 100 → 0,272727 BTC).
    2) Trader'ın ters dönüşü kaçtı: izleyici trader'ı −100 BTC (kısa) biliyor, biz hâlâ +0,272727 BTC uzun.
    3) Trader 200 BTC daha satar (−100 → −300). Beklenen: ÖNCE reduce-only SATIŞ 0,272727 BTC (27,27 $; bid 99,9), SONRA hedefe göre kısa açılış
       hedef = 90,909 × 300 × 100 / 100.000 = 27,2727 $ (reduce_only False, bid 99,9 → 27,2727 / 99,9 = 0,273000 BTC). Son pozisyon −0,273000 BTC.
       Eski davranış: "artir" → ters yönde reduce-only olmayan emir (borsada net ters pozisyon, defterle fark)."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    s1 = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert [(x.eylem, x.karar) for x in s1] == [("ac", "emir")] and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727, abs=1e-6)
    m.poz_tr[adr(1)]["BTC"] = -100.0                                                     # kaçan ters dönüş
    s2 = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 200, 100.0, -100.0, saat))
    assert [(x.eylem, x.karar) for x in s2] == [("kapat", "emir"), ("ac", "emir")]
    emirler = kayitlar(tmp_path, "emir")[1:]
    assert [(e["eylem"], e["yon"], e["reduce_only"]) for e in emirler] == [("kapat", "A", True), ("ac", "A", False)]
    assert emirler[0]["sz"] == pytest.approx(0.272727, abs=1e-6) and emirler[0]["usd_dolan"] == pytest.approx(0.272727 * 99.9, abs=1e-4)
    assert emirler[1]["usd_istenen"] == pytest.approx(27.2727, abs=1e-4) and emirler[1]["sz"] == pytest.approx(27.272727 / 99.9, abs=1e-6)
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(-0.273000, abs=1e-6)


def test_g3_ters_kapanis_teyitsizse_ters_yonde_acilis_yok(tmp_path):
    """Kapanış dolmazsa (defter boş) bizim uzun açık kalır → aynı olayda kısa açılış GÖNDERİLMEZ (ters emir yok); kapanış kuyrukta yeniden denenir."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    hl.kitaplar["BTC"] = {"levels": [[], [{"px": "100", "sz": "1000"}]]}                 # bid yok: satış dolmaz
    m.poz_tr[adr(1)]["BTC"] = -100.0
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 200, 100.0, -100.0, saat))
    assert [x.eylem for x in s] == ["kapat"] and m.hesap.sz(adr(1), "BTC") > 0
    assert all(e["reduce_only"] for e in kayitlar(tmp_path, "emir")[1:])                 # ters yönde reduce-only olmayan emir YOK
    assert f"{adr(1)}|BTC" in m.kapanis_kuyrugu


def test_g3_senkron_trader_ters_donduyse_bizim_ters_pozisyon_kapatilir(tmp_path):
    """Biz +0,272727 BTC uzun; REST trader'ı −300 BTC kısa gösteriyor (izleyici +300) → senkron reduce-only kapatır (açılış yapmaz)."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    hl.pozlar = {adr(1): {"BTC": -300.0}}
    saat.ms += 60_000
    m.senkron_uygula(m.senkron_oku())
    assert m.hesap.sz(adr(1), "BTC") == 0.0 and m.poz_tr[adr(1)] == {"BTC": -300.0}
    son = kayitlar(tmp_path, "emir")[-1]
    assert (son["eylem"], son["yon"], son["reduce_only"]) == ("kapat", "A", True) and len(kayitlar(tmp_path, "emir")) == 2
    assert kayitlar(tmp_path, "senkron_ters_kapanis")[0]["coin"] == "BTC"


# ================================================================================================ G-4
class SahteExchange:
    def __init__(self, kaldirac=None):
        self.cagrilar, self.kaldiraclar, self.kaldirac = [], [], kaldirac

    def update_leverage(self, lev, coin, is_cross):
        self.kaldiraclar.append((lev, coin, is_cross))
        if isinstance(self.kaldirac, Exception):
            raise self.kaldirac
        return self.kaldirac or {"status": "ok"}

    def order(self, coin, is_buy, sz, px, tif, reduce_only, cloid=None):
        self.cagrilar.append({"coin": coin, "is_buy": is_buy, "sz": sz, "reduce_only": reduce_only})
        return {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {"totalSz": str(sz), "avgPx": "99.9", "oid": 1}}]}}}


def kitap_post(meta_coinler=None, sayac=None):
    tablo = {"": [("BTC", 5)], **(meta_coinler or {})}

    def post(y):
        if y["type"] == "meta":
            dex = y.get("dex", "")
            if sayac is not None:
                sayac.append(dex)
            return {"universe": [{"name": n, "szDecimals": d} for n, d in tablo[dex]]}
        return {"levels": [[{"px": "99.9", "sz": "100"}], [{"px": "100", "sz": "100"}]]}
    post.tablo = tablo
    return post


@pytest.mark.parametrize("hata", [RuntimeError("ağ"), {"status": "err"}])
def test_g4_kaldirac_hatasi_kapanisi_engellemez_acilisi_engeller(hata):
    """Kaldıraç ayarı istisna atar / reddedilir: reduce-only satış 0,1 BTC yine gider (update_leverage HİÇ çağrılmaz); açılış ise red (kaldıraçsız açılış yok)."""
    ex = SahteExchange(hata)
    g = yu.GercekYurutucu(ex, kitap_post(), RULES)
    d = g.emir("BTC", "A", 9.99, reduce_only=True, acik_sz=0.1)
    assert ex.kaldiraclar == [] and ex.cagrilar == [{"coin": "BTC", "is_buy": False, "sz": 0.1, "reduce_only": True}] and d.sz == pytest.approx(0.1)
    a = g.emir("BTC", "B", 11.0)
    assert a.durum == "red" and len(ex.cagrilar) == 1 and ex.kaldiraclar == [(3, "BTC", False)]


# ================================================================================================ G-6
class DexHL(SahteHL):
    """perpDexs ilk `hata` çağrıda bozuk; sonra [None, xyz]. Hesap: ana dex 60.000 $ + xyz dex 30.000 $ + spot 10.000 $ = 100.000 $."""
    def __init__(self, hata=1, **kw):
        super().__init__(spot=10_000.0, **kw)
        self.hata = hata

    def __call__(self, y):
        if y["type"] == "perpDexs":
            self.istekler.append(y)
            if self.hata > 0:
                self.hata -= 1
                raise ConnectionError("perpDexs")
            return [None, {"name": "xyz"}]
        if y["type"] == "clearinghouseState":
            self.istekler.append(y)
            return {"marginSummary": {"accountValue": "30000" if y.get("dex") == "xyz" else "60000"}, "assetPositions": []}
        return super().__call__(y)


def test_g6_perpdexs_hatasi_onbellege_alinmaz_kismi_toplam_yok(tmp_path):
    """1. okuma: perpDexs hata → hesap değeri BİLİNMİYOR (None; eskiden [] önbelleğe alınır, 60.000 + 10.000 = 70.000 $ kısmi toplam süreç boyunca kalırdı → emirler %43 şişerdi).
    2. okuma: perpDexs yeniden okunur → 60.000 + 30.000 + 10.000 = 100.000 $."""
    hl = DexHL(hata=1)
    m, *_ = kur(tmp_path, hl=hl)
    assert m.trader_hesap_usd(adr(1), 0) is None and kayitlar(tmp_path, "hesap_okuma_hata")[0]["tur"] == "ConnectionError"
    assert m.trader_hesap_usd(adr(1), 0) == pytest.approx(100_000.0)
    assert m._dexler() == ["xyz"] and sum(1 for y in hl.istekler if y["type"] == "perpDexs") == 2          # başarı önbellekte: üçüncü istek yok
    assert mt.hesap_degeri_oku(hl, adr(1), None) is None


def test_g6_dex_listesi_bilinmezken_acilis_trader_hesap_yok(tmp_path):
    hl = DexHL(hata=10)
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()
    m.hesap_tr.clear()
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert [(x.eylem, x.karar, x.neden) for x in s] == [("ac", "atlandi", "trader_hesap_yok")] and kayitlar(tmp_path, "emir") == []
    assert m.senkron_oku() == {}                                                         # pozisyonlar da eksik dex listesiyle OKUNMAZ (yanlış senkron_kapanis olmasın)


# ================================================================================================ S-11
def test_s11_yeni_listelenen_coin_meta_bir_kez_tazelenir_bilinmeyen_coin_acik_hata():
    sayac = []
    post = kitap_post(sayac=sayac)
    ex = SahteExchange()
    g = yu.GercekYurutucu(ex, post, RULES)
    assert g.emir("BTC", "B", 11.0).dolu_mu and sayac == [""]
    post.tablo[""] = [("BTC", 5), ("YENI", 2)]                                           # açılıştan sonra listelendi
    d = g.emir("YENI", "B", 11.0)
    assert d.dolu_mu and sayac == ["", ""] and ex.cagrilar[-1]["sz"] == 0.11              # 11 / 100 = 0,11 (szDecimals 2)
    assert g.emir("YENI", "B", 11.0).dolu_mu and sayac == ["", ""]                         # önbellekte: yeniden okuma yok
    y = g.emir("YOK", "B", 11.0)
    assert (y.durum, y.neden) == ("red", "bilinmeyen coin: YOK") and sayac == ["", "", ""]  # tek tazeleme, sonra açık metin
    assert len(ex.cagrilar) == 3


def test_s11_hip3_dex_tablosu_yalniz_canli_hip3_kopya_acikken():
    sayac = []
    post = kitap_post({"xyz": [("xyz:AAPL", 3)]}, sayac)
    kapali = yu.GercekYurutucu(SahteExchange(), post, {**RULES, "canli_hip3_kopya": False})
    d = kapali.emir("xyz:AAPL", "B", 11.0)
    assert d.durum == "red" and d.neden.startswith("bilinmeyen coin: xyz:AAPL") and sayac == []
    acik = yu.GercekYurutucu(SahteExchange(), post, {**RULES, "canli_hip3_kopya": True})
    assert acik.emir("xyz:AAPL", "B", 11.0).dolu_mu and sayac == ["xyz"]


def test_s11_sdk_perp_dexs_yalniz_hip3_kopya_acikken(monkeypatch):
    kurulan = {}

    class SahteEx:
        def __init__(self, wallet, base_url=None, meta=None, vault_address=None, account_address=None, spot_meta=None, perp_dexs=None, timeout=None):
            kurulan["perp_dexs"] = perp_dexs
    hl = types.ModuleType("hyperliquid")
    hl_ex = types.ModuleType("hyperliquid.exchange")
    hl_ex.Exchange = SahteEx
    hl_ut = types.ModuleType("hyperliquid.utils")
    hl_ut.constants = types.SimpleNamespace(MAINNET_API_URL="https://api.hyperliquid.xyz")
    eth = types.ModuleType("eth_account")
    eth.Account = types.SimpleNamespace(from_key=lambda k: "cuzdan")
    for ad, mod in {"hyperliquid": hl, "hyperliquid.exchange": hl_ex, "hyperliquid.utils": hl_ut, "eth_account": eth}.items():
        monkeypatch.setitem(sys.modules, ad, mod)
    ortam = {"HL_API_CUZDAN_ANAHTARI": "a", "HL_HESAP_ADRESI": "0xabc"}
    istek = []
    post = lambda y: istek.append(y) or [None, {"name": "xyz"}]                         # noqa: E731
    yu.gercek_yurutucu_olustur(post, {**RULES, "canli_hip3_kopya": False}, ortam)
    assert kurulan["perp_dexs"] is None and istek == []
    yu.gercek_yurutucu_olustur(post, {**RULES, "canli_hip3_kopya": True}, ortam)
    assert kurulan["perp_dexs"] == ["", "xyz"]
