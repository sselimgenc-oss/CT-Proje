"""G-13 / G-2 (DENETIM_PROJE_2026-11-08, DENETIM_DEVIR_2026-11-06): gerçek kipte borsa pozisyonu defterden küçükken kapanış + DUR'un borsadaki defter dışı pozisyonu kapatması.
Ağsız; sahte borsa (`BorsaSim`, HL reduce-only kuralıyla). Sayılar elle hesaplanmıştır.
Birimler: sz = coin (işaretli; + long), fiyat/mark = $, özsermaye/realize = $ (HL hesabı = kasa ölçeği, 1.000 $)."""
import pytest

from copytrade.canli import motor as mt
from tests.test_canli_motor import SAAT, adr, kadro, kayitlar, olay, satir
from tests.test_canli_t4b import BorsaSim, _maske_temizle, kur_gercek  # noqa: F401 (autouse fixture)

A, B = adr(1), adr(2)
PAY = 0.27273          # trader 300 BTC / 100.000 $ hesap → oran 0,3 → slot 90,9 $ × 0,3 = 27,27 $ / 100 $ = 0,27273 BTC (test_canli_t4b ile aynı)


# ------------------------------------------------------------------------------------------------ sahte borsanın kendi testi
def test_sahte_borsa_hl_reduce_only_kurali():
    """HL: reduce-only emir pozisyon yoksa ya da pozisyonla aynı yöndeyse REDDEDİLİR; ters yönde |pozisyon|'dan büyükse |pozisyon| ile kırpılır (ters çevirmez)."""
    sim = BorsaSim(doluluk=(1.0,))
    r = sim.order("BTC", False, 0.2, 99.0, {}, True)                         # pozisyon yok → red
    assert "error" in r["response"]["data"]["statuses"][0] and sim.poz.get("BTC", 0.0) == 0.0 and sim.siparisler[-1]["red"] is True
    sim.order("BTC", True, 0.3, 101.0, {}, False)                            # normal alış: 0,3 long
    assert sim.poz["BTC"] == pytest.approx(0.3)
    r = sim.order("BTC", True, 0.1, 101.0, {}, True)                         # long'a reduce-only ALIŞ → red (büyütürdü)
    assert "error" in r["response"]["data"]["statuses"][0] and sim.poz["BTC"] == pytest.approx(0.3)
    r = sim.order("BTC", False, 0.5, 99.0, {}, True)                         # 0,5 satış reduce-only → 0,3 ile kırpılır; pozisyon 0 (−0,2'ye dönmez)
    assert r["response"]["data"]["statuses"][0]["filled"]["totalSz"] == "0.3" and sim.poz["BTC"] == pytest.approx(0.0)
    sim.order("ETH", False, 1.0, 1999.0, {}, False)                          # short −1
    r = sim.order("ETH", True, 0.4, 2001.0, {}, True)                        # short'a reduce-only alış: geçerli, kırpma yok
    assert r["response"]["data"]["statuses"][0]["filled"]["totalSz"] == "0.4" and sim.poz["ETH"] == pytest.approx(-0.6)


def test_sahte_borsa_red_doluluk_tuketmez():
    sim = BorsaSim(doluluk=(0.5, 1.0))
    sim.order("BTC", False, 0.2, 99.0, {}, True)                             # red: eşleşme yok → doluluk sırası değişmez
    sim.order("BTC", True, 0.2, 101.0, {}, False)                            # ilk doluluk 0,5 → 0,1
    assert sim.poz["BTC"] == pytest.approx(0.1)


# ------------------------------------------------------------------------------------------------ _kirp altın örnekleri
@pytest.mark.parametrize("yerel,k,beklenen", [
    (0.27273, 0.0, 0.0),                # HL tasfiye: pay yok
    (0.27273, -0.27273, 0.0),           # HL 0, diğer 0,27273 → k negatif: ters yön emir YOK (eski kod 0,27273 ALIŞ gönderirdi)
    (0.27273, 0.02727, 0.02727),        # HL 0,3 − diğer 0,27273
    (0.27273, 0.4, 0.27273),            # pay yerelden büyük: yerel kadar
    (-0.5, -0.2, -0.2),                 # short: işaret yerelin
    (-0.5, 0.2, 0.0),
    (0.0, 0.3, 0.0),
])
def test_kirp_altin(yerel, k, beklenen):
    assert mt.Motor._kirp(yerel, k) == pytest.approx(beklenen, abs=1e-12)


# ------------------------------------------------------------------------------------------------ G-13 motor seviyesinde, 2 trader
def kur_iki(tmp_path, monkeypatch, sim=None):
    sim = sim or BorsaSim()
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    k = kadro([satir(1, 1), satir(2, 2)], saat() - SAAT)
    m.kadro_oku = lambda: k
    sim.trader_poz[B] = {}
    m.baslat()
    m.olay_isle(olay("a:1", A, "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("b:1", B, "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.sz(A, "BTC") == pytest.approx(PAY) and m.hesap.sz(B, "BTC") == pytest.approx(PAY) and sim.poz["BTC"] == pytest.approx(2 * PAY)
    sim.trader_poz[B] = {"BTC": 300.0}                                       # B'nin trader'ı hâlâ açık (REST senkronu B'yi kapatmasın)
    return m, sim, saat, tgp


def ozdeslik(m):
    """özsermaye = kasa + realize − ücret + funding + açık K/Z (+ kapanmış net)."""
    h = m.hesap
    return h.kasa_usd + sum(h.realize.values()) - sum(h.ucret.values()) + h.funding_toplam() + h.gerceklesmemis(None, m.marks) + h.kapanmis_net


@pytest.mark.parametrize("hl_btc", [0.0, 0.1])
def test_g13_hl_tasfiye_iki_trader_kapanis_emirsiz_defterden_duser(tmp_path, monkeypatch, hl_btc):
    """A ve B 0,27273 BTC long (HL 0,54546). HL coin pozisyonunu tasfiye eder (0) ya da 0,1'e indirir (k = 0,1 − 0,27273 < 0). A kapatır →
    0 emir; A defterden mark 110 ile düşülür: realize = 0,27273 × (110 − 100) = 2,7273 $; B dokunulmaz; kuyruk boş; kapanis_eksik yok; harici_kapanis kaydı + alarm.
    Özdeşlik: yerel özsermaye öncesi = sonrası (açık K/Z 2,7273 realize'a geçer)."""
    m, sim, saat, tgp = kur_iki(tmp_path, monkeypatch)
    sim.poz["BTC"] = hl_btc
    m.marks["BTC"] = 110.0
    oz_once = m.yerel_ozsermaye()
    assert oz_once == pytest.approx(ozdeslik(m))
    n0, t0 = len(sim.siparisler), len(tgp.gonderilen)
    m.olay_isle(olay("a:2", A, "BTC", "A", 300, 110.0, 300.0, saat))
    assert sim.siparisler[n0:] == []                                                     # eski kod: 5 reddedilen reduce-only ALIŞ
    assert m.hesap.sz(A, "BTC") == 0.0 and "BTC" not in m.hesap.poz.get(A, {}) and m.hesap.sz(B, "BTC") == pytest.approx(PAY)
    assert m.hesap.realize[A] == pytest.approx(PAY * 10.0, abs=1e-9)                       # 2,7273 $
    assert not m.kapanis_kuyrugu and m.sayac["kapanis_eksik"] == 0 and not m.risk.acilis_durdu.get("kapanis_eksik")
    assert m.sayac["harici_kapanis"] == 1
    ev = kayitlar(tmp_path, "harici_kapanis")
    assert len(ev) == 1 and ev[0]["adres"] == A and ev[0]["yerel_sz"] == pytest.approx(PAY) and ev[0]["borsa_pay_sz"] == 0.0 and ev[0]["hl_sz"] == pytest.approx(hl_btc) and ev[0]["mark"] == 110.0
    assert any("harici kapanış" in x for x in tgp.gonderilen[t0:])
    assert m.yerel_ozsermaye() == pytest.approx(oz_once, abs=1e-9) and m.yerel_ozsermaye() == pytest.approx(ozdeslik(m), abs=1e-9)
    saat.ms += 60_000
    m.dakika()                                                                            # kuyrukta sonsuz yeniden deneme yok
    assert sim.siparisler[n0:] == [] and not m.kapanis_kuyrugu and m.hesap.sz(B, "BTC") == pytest.approx(PAY)


def test_g13_kismi_hl_0_3_kapanis_payla_kirpilir(tmp_path, monkeypatch):
    """HL 0,3 (defter 0,54546). A kapatır: k = 0,3 − 0,27273 = 0,02727 → TEK reduce-only SATIŞ 0,02727 (eski kod da 0,02727 gönderirdi ama sonra yerel 0,24546 kalırdı
    → yeniden k = 0,27273 − 0,27273 = 0 → eski kod 0 sayar; yeni kod harici_kapanis ile 0,24546'yı mark'ta düşer). HL sonrası 0,27273 = B'nin payı."""
    m, sim, saat, tgp = kur_iki(tmp_path, monkeypatch)
    sim.poz["BTC"] = 0.3
    n0 = len(sim.siparisler)
    m.olay_isle(olay("a:2", A, "BTC", "A", 300, 100.0, 300.0, saat))
    yeni = sim.siparisler[n0:]
    assert len(yeni) == 1 and yeni[0]["is_buy"] is False and yeni[0]["reduce_only"] and yeni[0]["sz"] == pytest.approx(0.02727, abs=1e-9) and not yeni[0].get("red")
    assert sim.poz["BTC"] == pytest.approx(PAY, abs=1e-9) and m.hesap.sz(A, "BTC") == 0.0 and m.hesap.sz(B, "BTC") == pytest.approx(PAY)
    ev = kayitlar(tmp_path, "harici_kapanis")
    assert len(ev) == 1 and ev[0]["yerel_sz"] == pytest.approx(PAY - 0.02727, abs=1e-9) and ev[0]["borsa_pay_sz"] == 0.0
    assert not m.kapanis_kuyrugu and m.sayac["kapanis_eksik"] == 0


def test_g13_tek_trader_normal_kapanis_harici_yok(tmp_path, monkeypatch):
    """Gerileme: borsa = defter iken normal kapanış; harici_kapanis kaydı/sayacı YOK."""
    m, sim, saat, tgp = kur_iki(tmp_path, monkeypatch)
    n0 = len(sim.siparisler)
    m.olay_isle(olay("a:2", A, "BTC", "A", 300, 100.0, 300.0, saat))
    yeni = sim.siparisler[n0:]
    assert len(yeni) == 1 and yeni[0]["sz"] == pytest.approx(PAY) and sim.poz["BTC"] == pytest.approx(PAY) and m.hesap.sz(A, "BTC") == 0.0
    assert not kayitlar(tmp_path, "harici_kapanis") and m.sayac.get("harici_kapanis", 0) == 0


# ------------------------------------------------------------------------------------------------ G-2: DUR borsadaki defter dışı pozisyonu da kapatır
def test_g2_dur_borsadaki_defter_disi_eth_kapanir_mesaj_yalniz_duzken(tmp_path, monkeypatch):
    """Defter: A 0,27273 BTC. Borsa: ayrıca −0,5 ETH (defterde yok; elle/yetim). DUR → BTC kapanır (defter), ETH için reduce-only ALIŞ 0,5 (5 bant denemesi dolmaz)
    → "DÜZLEŞMEDİ … ETH -0.5", motor durmaz, "Tüm pozisyonlar kapandı" YOK. Sonraki dakika ETH dolar → borsa düz → "Tüm pozisyonlar kapandı"."""
    sim = BorsaSim(doluluk=(1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", A, "BTC", "B", 300, 100.0, 0.0, saat))
    sim.poz["ETH"] = -0.5
    n0 = len(sim.siparisler)
    m.dur_tetikle("komut")
    yeni = sim.siparisler[n0:]
    assert yeni[0]["coin"] == "BTC" and yeni[0]["is_buy"] is False and sim.poz["BTC"] == pytest.approx(0.0)
    eth = [x for x in yeni if x["coin"] == "ETH"]
    assert len(eth) == 5 and all(x["is_buy"] and x["reduce_only"] and x["sz"] == pytest.approx(0.5) for x in eth)
    assert sim.poz["ETH"] == pytest.approx(-0.5) and m.dur_bekliyor and not m.dur_istendi
    assert any("DÜZLEŞMEDİ" in x and "ETH -0.5" in x for x in tgp.gonderilen) and not any("Tüm pozisyonlar kapandı" in x for x in tgp.gonderilen)
    assert kayitlar(tmp_path, "dur")[-1]["borsa_fazla"] == {"ETH": -0.5}
    saat.ms += 60_000
    m.dakika()
    assert sim.poz["ETH"] == pytest.approx(0.0) and m.dur_istendi and not m.dur_bekliyor
    assert any("Tüm pozisyonlar kapandı" in x for x in tgp.gonderilen)
    son = kayitlar(tmp_path, "borsa_yetim_kapat")[-1]
    assert son["coin"] == "ETH" and son["sz"] == pytest.approx(0.5) and son["yon"] == "B"


def test_g2_dur_defter_bos_yalniz_borsada_eth_hemen_kapanir(tmp_path, monkeypatch):
    """Defter boş, borsada +0,25 ETH. DUR → tek reduce-only SATIŞ 0,25 dolar → borsa düz → motor durur, "kapatıldı, motor durdu"."""
    sim = BorsaSim()
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    sim.poz["ETH"] = 0.25
    m.dur_tetikle("komut")
    assert [(x["coin"], x["is_buy"], x["sz"]) for x in sim.siparisler] == [("ETH", False, 0.25)]
    assert sim.poz["ETH"] == pytest.approx(0.0) and m.dur_istendi and not m.dur_bekliyor
    assert any("Tüm pozisyonlar kapandı" in x for x in tgp.gonderilen) and not any("DÜZLEŞMEDİ" in x for x in tgp.gonderilen)


def test_g2_dur_borsa_okunamazsa_tamam_denmez(tmp_path, monkeypatch):
    """clearinghouseState okunamazsa düz SAYILMAZ: "DÜZLEŞMEDİ … borsa okunamadı", motor durmaz."""
    sim = BorsaSim()
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    asil = sim.post

    def bozuk(y):
        if y["type"] == "clearinghouseState":
            raise RuntimeError("ağ")
        return asil(y)
    m.post = bozuk
    m.dur_tetikle("komut")
    assert m.dur_bekliyor and not m.dur_istendi and any("borsa okunamadı" in x for x in tgp.gonderilen)
    assert not any("Tüm pozisyonlar kapandı" in x for x in tgp.gonderilen)
