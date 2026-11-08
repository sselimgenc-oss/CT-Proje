"""Canlı motor — yürütücü, hesap, risk (T4). Elle hesaplanmış altın örnekler; ağsız (sahte borsa)."""
import pytest

from copytrade.canli import hesap as hs
from copytrade.canli import risk as rk
from copytrade.canli import yurutucu as yu
from copytrade.kurallar import load_rules

RULES = load_rules()
ASKS = [{"px": "100", "sz": "0.3"}, {"px": "101", "sz": "0.5"}, {"px": "103", "sz": "1.0"}]
BIDS = [{"px": "99.9", "sz": "0.2"}, {"px": "99", "sz": "0.5"}, {"px": "98", "sz": "1.0"}]


def kitap(coin="BTC"):
    return lambda y: {"coin": coin, "levels": [BIDS, ASKS]} if y["type"] == "l2Book" else {}


# ------------------------------------------------------------------------------------------------ defter yürüyüşü
def test_defter_yuru_bant_disi_kisim_dolmaz():
    """Alış 50 $, bant %0,5: limit 100 × 1,005 = 100,5 → yalnız 100'lük seviye (0,3 BTC = 30 $) dolar; 101 bant dışı → 20 $ dolmaz."""
    sz, usd, ref = yu.defter_yuru(ASKS, "B", 50.0, 0.005)
    assert (sz, usd, ref) == pytest.approx((0.3, 30.0, 100.0))


def test_defter_yuru_genis_bant_ortalama_fiyat():
    """Bant %2 (limit 102): 100'de 30 $ (0,3 BTC) + 101'de kalan 20 $ (20/101 = 0,19802 BTC) → sz 0,49802, ortalama 50 / 0,49802 = 100,3976."""
    sz, usd, ref = yu.defter_yuru(ASKS, "B", 50.0, 0.02)
    assert sz == pytest.approx(0.3 + 20 / 101) and usd == pytest.approx(50.0) and usd / sz == pytest.approx(100.3976, abs=1e-4)


def test_defter_yuru_satis_ve_reduce_only_tavani():
    """Satış 15 $, bid 99,9 (0,2 BTC = 19,98 $) → 15/99,9 = 0,15015 BTC tek seviyede; reduce-only tavanı 0,1 BTC → 0,1 BTC (9,99 $)."""
    sz, usd, ref = yu.defter_yuru(BIDS, "A", 15.0, 0.005)
    assert sz == pytest.approx(15 / 99.9) and ref == 99.9
    sz2, usd2, _ = yu.defter_yuru(BIDS, "A", 15.0, 0.005, acik_sz=0.1)
    assert sz2 == pytest.approx(0.1) and usd2 == pytest.approx(9.99)
    assert yu.defter_yuru([], "B", 10.0, 0.005) == (0.0, 0.0, 0.0)


def test_kayma_isareti_pozitif_aleyhimize():
    assert yu.kayma("B", 100.0, 100.4) == pytest.approx(0.004) and yu.kayma("A", 100.0, 99.6) == pytest.approx(0.004)
    assert yu.kayma("B", 100.0, 99.0) == pytest.approx(-0.01) and yu.kayma("B", None, 1.0) is None


def test_sanal_yurutucu_altin_ornek_alis_ucret_kayma():
    """50 $ alış, bant %2: ortalama 100,3976; ücret = 50 × 0,00045 = 0,0225 $; kayma = (100,3976 − 100) / 100 = 0,003976 (aleyhimize); IOC: tam doldu."""
    kurallar = {**RULES, "canli_ioc_bant": 0.02}
    d = yu.SanalYurutucu(kitap(), kurallar).emir("BTC", "B", 50.0)
    assert d.durum == "dolu" and d.px == pytest.approx(100.3976, abs=1e-4) and d.usd_dolan == pytest.approx(50.0) and d.ucret == pytest.approx(0.0225)
    assert d.kayma_oran == pytest.approx(0.003976, abs=1e-6) and d.referans_px == 100.0
    k = yu.SanalYurutucu(kitap(), RULES).emir("BTC", "B", 50.0)                   # varsayılan bant %0,5 → kısmi: 30 $
    assert k.durum == "kismi" and k.usd_dolan == pytest.approx(30.0) and k.sz == pytest.approx(0.3)


def test_sanal_yurutucu_defter_okunamazsa_emir_yok():
    def bozuk(y):
        raise RuntimeError("ağ")
    d = yu.SanalYurutucu(bozuk, RULES).emir("BTC", "B", 50.0)
    assert d.durum == "red" and d.sz == 0 and "l2Book" in d.neden


# ------------------------------------------------------------------------------------------------ gerçek yürütücü (sahte exchange; ÇALIŞTIRILMAZ)
class SahteExchange:
    def __init__(self, yanit=None, hata=None, kaldirac_yanit=None):
        self.cagrilar, self.yanit, self.hata = [], yanit, hata
        self.kaldirac_yanit = kaldirac_yanit or {"status": "ok"}
        self.kaldiraclar = []

    def update_leverage(self, lev, coin, is_cross):
        self.kaldiraclar.append((lev, coin, is_cross))
        return self.kaldirac_yanit

    def order(self, coin, is_buy, sz, px, tif, reduce_only, cloid=None):
        if self.hata:
            raise self.hata
        self.cagrilar.append({"coin": coin, "is_buy": is_buy, "sz": sz, "px": px, "tif": tif, "reduce_only": reduce_only})
        self.cloidler = getattr(self, "cloidler", []) + [cloid]
        return self.yanit


def meta_post(y):
    if y["type"] == "meta":
        return {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}]}
    return {"levels": [BIDS, ASKS]}


def dolu(sz="0.11", px="100.1"):
    return {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {"totalSz": sz, "avgPx": px, "oid": 1}}]}}}


def test_gercek_yurutucu_ioc_izole_3x_ve_fiyat_bandi():
    """Alış 11 $: en iyi ask 100 → limit 100 × 1,005 = 100,5 (alışta aşağı yuvarlanır; zaten tick üzerinde), sz = 11 / 100 = 0,11 (≥ 10 $ minimum); IOC; reduce_only False; kaldıraç: 3x İZOLE (is_cross False), coin başına bir kez."""
    ex = SahteExchange(dolu())
    g = yu.GercekYurutucu(ex, meta_post, RULES)
    d = g.emir("BTC", "B", 11.0)
    c = ex.cagrilar[0]
    assert c == {"coin": "BTC", "is_buy": True, "sz": 0.11, "px": 100.5, "tif": {"limit": {"tif": "Ioc"}}, "reduce_only": False}
    assert ex.kaldiraclar == [(3, "BTC", False)]
    assert d.durum == "dolu" and d.px == 100.1 and d.sz == 0.11 and d.kayma_oran == pytest.approx(0.001)
    g.emir("BTC", "B", 11.0)
    assert len(ex.kaldiraclar) == 1                                              # bir kez


def test_gercek_yurutucu_satis_reduce_only_ve_limit_asagi():
    ex = SahteExchange(dolu("0.1", "99.9"))
    d = yu.GercekYurutucu(ex, meta_post, RULES).emir("BTC", "A", 50.0, reduce_only=True, acik_sz=0.1)
    c = ex.cagrilar[0]
    assert c["is_buy"] is False and c["reduce_only"] is True and c["px"] == 99.5 and c["sz"] == 0.1          # 99,9 × 0,995 = 99,4005 → tick 0,1 (6 − szDecimals 5 = 1 ondalık); satışta YUKARI → 99,5 (eski yuvarlama 99,4 verirdi: bant aşılırdı); açık pozisyon tavanı 0,1; 9,99 $ < 10 $ ama TAM kapanış (reduce-only) → minimum aranmaz
    assert d.durum == "dolu"                                                     # M-3: istenen 50 $ > açık pozisyon (9,99 $) → sz pozisyonla (0,1) kırpıldı ve 0,1'in tamamı doldu = TAM kapanış (eskiden yanlışlıkla "kismi")


def test_gercek_yurutucu_red_hata_ve_dolmayan_yanitlar_motoru_dusurmez():
    red = {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"error": "Order could not immediately match"}]}}}
    d = yu.GercekYurutucu(SahteExchange(red), meta_post, RULES).emir("BTC", "B", 11.0)
    assert d.durum == "red" and "match" in d.neden and d.sz == 0
    d2 = yu.GercekYurutucu(SahteExchange(hata=ConnectionError("x")), meta_post, RULES).emir("BTC", "B", 11.0)
    assert d2.durum == "belirsiz" and "sdk_hatasi" in d2.neden and d2.sz == 0     # G-1: emir isteği gittikten sonra bağlantı hatası → HL emri almış olabilir: "red" DEĞİL "belirsiz"
    d3 = yu.GercekYurutucu(SahteExchange({"beklenmedik": 1}), meta_post, RULES).emir("BTC", "B", 11.0)
    assert d3.durum == "red" and d3.neden == "yanit_bicimi"
    resting = {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 5}}]}}}
    d4 = yu.GercekYurutucu(SahteExchange(resting), meta_post, RULES).emir("BTC", "B", 11.0)
    assert d4.durum == "dolmadi" and d4.sz == 0                                  # IOC: resting yeniden denenmez
    d5 = yu.GercekYurutucu(SahteExchange(dolu(), kaldirac_yanit={"status": "err"}), meta_post, RULES).emir("BTC", "B", 11.0)
    assert d5.durum == "red"                                                     # kaldıraç ayarı reddedilirse emir YOK


# ------------------------------------------------------------------------------------------------ G-1 / G-12a: zaman aşımı → belirsiz
class ClientError(Exception):
    """SDK `hyperliquid.utils.error.ClientError` taklidi (HTTP 4xx: HL isteği açıkça reddetti; sınıf adıyla tanınır)."""


def test_g1_emir_cagrisinda_zaman_asimi_belirsiz_emir_oncesi_hata_ve_4xx_red():
    """Emir ÖNCESİ hata (defter okunamadı) → emir gitmedi → red; emir çağrısında zaman aşımı / 5xx → belirsiz (HL emri almış olabilir); HL 4xx (`ClientError`) → red."""
    import requests

    def bozuk_post(y):
        raise TimeoutError("l2Book")
    ex = SahteExchange(dolu())
    d = yu.GercekYurutucu(ex, bozuk_post, RULES).emir("BTC", "B", 11.0, cloid="0x" + "1" * 32)
    assert d.durum == "red" and ex.cagrilar == []                                # emir hiç gönderilmedi
    for hata, beklenen in [(requests.exceptions.ReadTimeout("zaman aşımı"), "belirsiz"), (requests.exceptions.ConnectionError("koptu"), "belirsiz"),
                           (RuntimeError("5xx"), "belirsiz"), (ClientError("422"), "red")]:
        d = yu.GercekYurutucu(SahteExchange(hata=hata), meta_post, RULES).emir("BTC", "B", 11.0, cloid="0x" + "1" * 32)
        assert (d.durum, d.sz, d.usd_dolan) == (beklenen, 0.0, 0.0) and d.neden == f"sdk_hatasi: {type(hata).__name__}"


def test_g12a_exchange_zaman_asimi_kurallardan_sdk_kurucusuna_gecer(monkeypatch):
    """`gercek_yurutucu_olustur` SDK `Exchange`'i `timeout=canli_emir_zaman_asimi_sn` (10 sn) ile kurar (SDK varsayılanı None = süresiz). SDK yerine sahte modüller (ağ/anahtar yok)."""
    import sys
    import types
    kurulan = {}

    class SahteEx:
        def __init__(self, wallet, base_url=None, meta=None, vault_address=None, account_address=None, spot_meta=None, perp_dexs=None, timeout=None):
            kurulan.update(wallet=wallet, base_url=base_url, account_address=account_address, timeout=timeout)
    hl = types.ModuleType("hyperliquid")
    hl_ex = types.ModuleType("hyperliquid.exchange")
    hl_ex.Exchange = SahteEx
    hl_ut = types.ModuleType("hyperliquid.utils")
    hl_ut.constants = types.SimpleNamespace(MAINNET_API_URL="https://api.hyperliquid.xyz")
    eth = types.ModuleType("eth_account")
    eth.Account = types.SimpleNamespace(from_key=lambda k: "cuzdan")
    for ad, mod in {"hyperliquid": hl, "hyperliquid.exchange": hl_ex, "hyperliquid.utils": hl_ut, "eth_account": eth}.items():
        monkeypatch.setitem(sys.modules, ad, mod)
    assert RULES["canli_emir_zaman_asimi_sn"] == 10
    g = yu.gercek_yurutucu_olustur(lambda y: {}, RULES, {"HL_API_CUZDAN_ANAHTARI": "anahtar", "HL_HESAP_ADRESI": "0xabc"})
    assert kurulan == {"wallet": "cuzdan", "base_url": "https://api.hyperliquid.xyz", "account_address": "0xabc", "timeout": 10.0} and isinstance(g, yu.GercekYurutucu)
    yu.gercek_yurutucu_olustur(lambda y: {}, {**RULES, "canli_emir_zaman_asimi_sn": 3}, {"HL_API_CUZDAN_ANAHTARI": "a", "HL_HESAP_ADRESI": "0xabc"})
    assert kurulan["timeout"] == 3.0


def test_tick_yuvarlama_5_anlamli_basamak():
    assert yu.tick_yuvarla(100.50001, 5) == 100.5 and yu.tick_yuvarla(1234.5678, 5) == 1234.6 and yu.tick_yuvarla(0.123456789, 0) == 0.12346


def test_anahtar_yoksa_gercek_yurutucu_kurulamaz():
    with pytest.raises(yu.AnahtarYok):
        yu.gercek_yurutucu_olustur(meta_post, RULES, ortam={})
    with pytest.raises(yu.AnahtarYok):
        yu.gercek_yurutucu_olustur(meta_post, RULES, ortam={"HL_API_CUZDAN_ANAHTARI": "x"})          # hesap adresi yok
    with pytest.raises(yu.AnahtarYok):
        yu.gercek_yurutucu_olustur(meta_post, RULES, ortam={"HL_API_CUZDAN_ANAHTARI": "  ", "HL_HESAP_ADRESI": "0x1"})


# ------------------------------------------------------------------------------------------------ hesap
def test_hesap_altin_ornek_uzun_kar_ucret_ve_ozsermaye():
    """Kasa 1.000: 0,5 BTC @100 alış (ücret 0,05×… = 0,0225), mark 110: gerçekleşmemiş +5; 0,3 BTC @120 satış → gerçekleşen 0,3 × 20 = 6; kalan 0,2 BTC mark 130: +6.
    Özsermaye = 1000 + 6 − (0,0225 + ücret2) + 0,2 × 30 = …"""
    h = hs.Hesap(1000.0)
    h.slot_ac("a", 90.9)
    h.uygula("a", "BTC", "B", 0.5, 100.0, 0.0225, 1)
    assert h.gerceklesmemis("a", {"BTC": 110.0}) == pytest.approx(5.0) and h.ozsermaye({"BTC": 110.0}) == pytest.approx(1000 + 5 - 0.0225)
    pnl = h.uygula("a", "BTC", "A", 0.3, 120.0, 0.0162, 2)
    assert pnl == pytest.approx(6.0) and h.sz("a", "BTC") == pytest.approx(0.2)
    assert h.ozsermaye({"BTC": 130.0}) == pytest.approx(1000 + 6 - (0.0225 + 0.0162) + 0.2 * 30)
    assert h.slot_ozsermaye("a", {"BTC": 130.0}) == pytest.approx(90.9 + 6 - 0.0387 + 6) and h.brut_coin("BTC", {"BTC": 130.0}) == pytest.approx(26.0)


def test_hesap_artirma_ortalama_giris_kisa_pozisyon_ve_ters_donus_hatasi():
    h = hs.Hesap(1000.0)
    h.slot_ac("a", 90.9)
    h.uygula("a", "ETH", "A", 1.0, 2000.0, 0.0, 1)                       # short 1 ETH @2000
    h.uygula("a", "ETH", "A", 1.0, 2200.0, 0.0, 2)                       # ekleme: ortalama 2100
    assert h.poz["a"]["ETH"].giris == pytest.approx(2100.0) and h.sz("a", "ETH") == pytest.approx(-2.0)
    assert h.uygula("a", "ETH", "B", 2.0, 2000.0, 0.0, 3) == pytest.approx(200.0)        # short kapanış: (2100 − 2000) × 2
    assert h.sz("a", "ETH") == 0.0
    h.uygula("a", "ETH", "B", 1.0, 2000.0, 0.0, 4)
    with pytest.raises(ValueError):
        h.uygula("a", "ETH", "A", 2.0, 2000.0, 0.0, 5)                    # ters dönüş tek dolumda uygulanamaz
    with pytest.raises(ValueError):
        h.uygula("a", "ETH", "B", 0.0, 2000.0, 0.0, 6)


def test_tasfiye_fiyati_formulu_elle_ve_tasfiye_olayi():
    """Long, giriş 100, 3x, azami kaldıraç 40: mmr = 1/80 = 0,0125; liq = 100 × (1 − 1/3) / (1 − 0,0125) = 66,6667 / 0,9875 = 67,5105. Short: 100 × (4/3) / 1,0125 = 131,6872."""
    assert hs.tasfiye_fiyati(True, 100.0, 3.0, 40.0) == pytest.approx(67.5105, abs=1e-4)
    assert hs.tasfiye_fiyati(False, 100.0, 3.0, 40.0) == pytest.approx(131.6872, abs=1e-4)
    h = hs.Hesap(1000.0, maks_kaldirac={"BTC": 40.0})
    h.slot_ac("a", 90.9)
    h.uygula("a", "BTC", "B", 1.0, 100.0, 0.0, 1)
    assert h.tasfiye_kontrol({"BTC": 70.0}, 2) == []                                            # liq 67,51'in üstü
    ev = h.tasfiye_kontrol({"BTC": 67.0}, 3)
    assert len(ev) == 1 and ev[0]["tasfiye_px"] == pytest.approx(67.5105, abs=1e-4) and h.sz("a", "BTC") == 0.0
    assert ev[0]["pnl"] == pytest.approx(67.5105 - 100.0, abs=1e-4)


def test_hesap_json_gidis_donus_ve_slot_kapat_ozsermaye_surekli():
    h = hs.Hesap(1000.0)
    h.slot_ac("a", 90.9)
    h.uygula("a", "BTC", "B", 1.0, 100.0, 0.1, 1)
    h.uygula("a", "BTC", "A", 1.0, 105.0, 0.1, 2)
    oz = h.ozsermaye({})
    h2 = hs.Hesap.from_json(h.to_json())
    assert h2.ozsermaye({}) == pytest.approx(oz) and h2.slot_bas == {"a": 90.9}
    h2.slot_kapat("a")
    assert "a" not in h2.slot_bas and h2.ozsermaye({}) == pytest.approx(oz) == pytest.approx(1000 + 5 - 0.2)        # kayıt silinse de özsermaye sürekli


# ------------------------------------------------------------------------------------------------ risk
HOUR = 3_600_000
T0 = 1_800_000_000_000


def test_coin_tavani_kirpma_ve_sifir():
    """Kasa 1.000 → coin tavanı %30 = 300 $. Mevcut brüt 250: 100 $'lık emir → izin 50 → 50 $'a kırpılır; mevcut 295 → izin 5 < 11 → 0; mevcut 100 → 100 $ tam."""
    r = rk.Risk(RULES, 1000.0)
    assert r.coin_tavani(100.0, 250.0) == (pytest.approx(50.0), "coin_tavani_kirpildi")
    assert r.coin_tavani(100.0, 295.0) == (0.0, "coin_tavani")
    assert r.coin_tavani(100.0, 100.0) == (100.0, "") and r.coin_tavani(100.0, 400.0) == (0.0, "coin_tavani")


def test_patlama_freni_zamanlamasi_8_yeni_coin_10_dk_30_dk_ara():
    """10 dk içinde 8. yeni coin → fren (o açılış dahil); 30 dk boyunca yeni açılış yok; 30 dk sonra serbest. 9 dk aralıklı açılışlar fren tetiklemez."""
    r = rk.Risk(RULES, 1000.0)
    t = T0
    sonuc = []
    for i in range(8):                                                                         # dakikada bir yeni coin; motor emir dolunca kaydeder (O1)
        sonuc.append(r.acilis_izni("a", f"C{i}", True, t + i * 60_000)[0])
        if sonuc[-1]:
            r.yeni_coin_kaydet("a", f"C{i}", t + i * 60_000)
    assert sonuc == [True] * 7 + [False]
    assert r.acilis_izni("a", "X", True, t + 7 * 60_000 + 29 * 60_000) == (False, "patlama_freni")
    assert r.acilis_izni("a", "X", False, t + 7 * 60_000 + 29 * 60_000)[0] is False                # artırma da (fren aktif)
    assert r.acilis_izni("a", "X", True, t + 7 * 60_000 + 30 * 60_000 + 1)[0] is True
    assert r.acilis_izni("b", "X", True, t + 8 * 60_000)[0] is True                                  # başka trader etkilenmez
    r2 = rk.Risk(RULES, 1000.0)
    ok = []
    for i in range(12):                                                                        # 9 dk arayla: pencerede hep 2 coin
        ok.append(r2.acilis_izni("a", f"C{i}", True, T0 + i * 9 * 60_000)[0])
        r2.yeni_coin_kaydet("a", f"C{i}", T0 + i * 9 * 60_000)
    assert all(ok)


def test_patlama_freni_ayni_coin_tekrari_ve_kaydedilmeyen_acilis_saymaz_o1():
    """Aynı coinde 20 parça açılış (BTC) tek coin sayılır; emir verilmeyen (kaydedilmeyen) farklı coin sayılmaz; 8 FARKLI coin kaydedilince 8. engellenir."""
    r = rk.Risk(RULES, 1000.0)
    for i in range(20):
        assert r.acilis_izni("a", "BTC", True, T0 + i * 1000)[0] is True
        r.yeni_coin_kaydet("a", "BTC", T0 + i * 1000)
    assert len(r.yeni_coin["a"]) == 1
    for i in range(10):                                                                        # slot_tavani vb. ile atlanan coinler: kaydedilmez
        assert r.acilis_izni("a", f"S{i}", True, T0 + 30_000 + i)[0] is True
    for i in range(6):
        r.yeni_coin_kaydet("a", f"D{i}", T0 + 40_000 + i)                                      # BTC + 6 = 7 farklı coin
    assert r.acilis_izni("a", "D6", True, T0 + 50_000) == (False, "patlama_freni")             # 8. farklı coin


def test_gunluk_kayip_tam_sinirda_tetiklenir_ve_utc_gunu_sifirlar():
    r = rk.Risk(RULES, 1000.0)
    assert r.ozsermaye_isle(1000.0, T0) == [] and r.acilis_izni("a", "BTC", True, T0)[0] is True
    assert r.ozsermaye_isle(951.0, T0 + HOUR) == []                                                # −%4,9
    assert r.ozsermaye_isle(950.0, T0 + HOUR) == ["gunluk_kayip"] and r.acilis_izni("a", "BTC", True, T0 + HOUR) == (False, "gunluk_kayip")
    assert r.ozsermaye_isle(940.0, T0 + 2 * HOUR) == []                                            # tekrar tetiklenmez
    ertesi = (T0 // (24 * HOUR) + 1) * 24 * HOUR + HOUR                                            # sonraki UTC günü
    r.ozsermaye_isle(940.0, ertesi)
    assert r.acilis_izni("a", "BTC", True, ertesi)[0] is True and r.gun_basi == 940.0               # gün başı özsermaye yenilendi


def test_zirveden_yuzde_20_dusus_dur_tetikler():
    r = rk.Risk(RULES, 1000.0)
    r2 = rk.Risk(RULES, 1000.0)
    r2.ozsermaye_isle(1100.0, T0)
    assert "zirve_dusus" not in r2.ozsermaye_isle(881.0, T0)                                       # 1.100 × 0,8 = 880: 881 sınırın üstü
    assert r2.ozsermaye_isle(880.0, T0) == ["zirve_dusus"] and r2.dur and r2.acilis_izni("a", "BTC", True, T0) == (False, "dur")


def test_kasa_siniri_ve_bayrak():
    r = rk.Risk(RULES, 1000.0)
    assert r.kasa_siniri_asildi(1000.0) is False and r.kasa_siniri_asildi(1000.01) is True
    assert r.acilis_izni("a", "BTC", True, T0) == (False, "kasa_siniri")
    r.kasa_siniri_asildi(1000.0)
    r.bayrak("mutabakat", True)
    assert r.acilis_izni("a", "BTC", True, T0) == (False, "mutabakat")


# ------------------------------------------------------------------------------------------------ T4b (K‑37 §4): minimum nosyonel + tick içe yuvarlama
def test_limit_yuvarla_ice_dogru_alista_asagi_satista_yukari_altin_ornekler():
    """BTC szDecimals 5 → tick 0,1 (6 − 5 ondalık; 5 anlamlı basamak 100,xx için 0,01 → ikisinin kabası 0,1). Alış 100,4999 → 100,4; satış 100,4001 → 100,5; tam tick'te değişmez.
    Düşük fiyatlı coin (szDecimals 0): 0,123456 → 6 ondalık ve 5 anlamlı basamak (adım 1e‑5): alış 0,12345, satış 0,12346."""
    assert yu.limit_yuvarla(100.4999, 5, "B") == 100.4 and yu.limit_yuvarla(100.4001, 5, "A") == 100.5
    assert yu.limit_yuvarla(100.5, 5, "B") == 100.5 and yu.limit_yuvarla(100.5, 5, "A") == 100.5
    assert yu.limit_yuvarla(0.123456, 0, "B") == 0.12345 and yu.limit_yuvarla(0.123456, 0, "A") == 0.12346
    assert yu.limit_yuvarla(100 * 1.005, 5, "B") == 100.5                                         # kayan nokta artığı (100,49999999999999) tick kaydırmaz


def test_gercek_min_nosyonel_10_dolar_alti_emir_yok_ama_reduce_only_tam_kapanis_serbest():
    """sz = round(8 / 100, 5) = 0,08 → 8 $ < 10 $: emir YOK (`min_nosyonel`); 10 $ → 0,1 BTC verilir. Reduce‑only KISMİ 8 $ (açık 0,2) reddedilir; reduce‑only TAM kapanış (açık 0,05 = 5 $) verilir."""
    ex = SahteExchange(dolu("0.1", "100"))
    g = yu.GercekYurutucu(ex, meta_post, RULES)
    d = g.emir("BTC", "B", 8.0)
    assert d.durum == "red" and d.neden == "min_nosyonel" and ex.cagrilar == []
    assert g.emir("BTC", "B", 10.0).durum == "dolu" and len(ex.cagrilar) == 1
    assert g.emir("BTC", "A", 8.0, reduce_only=True, acik_sz=0.2).neden == "min_nosyonel" and len(ex.cagrilar) == 1
    ex.yanit = dolu("0.05", "99.9")
    d2 = g.emir("BTC", "A", 50.0, reduce_only=True, acik_sz=0.05)
    assert d2.dolu_mu and len(ex.cagrilar) == 2 and ex.cagrilar[1]["sz"] == 0.05 and ex.cagrilar[1]["reduce_only"] is True


def test_sanal_min_nosyonel_ayni_kural_ve_cloid_bant_gercek_emre_gecer():
    s = yu.SanalYurutucu(lambda y: {"levels": [BIDS, ASKS]}, RULES)
    assert s.emir("BTC", "B", 8.0).neden == "min_nosyonel" and s.emir("BTC", "B", 12.0).durum == "dolu"
    assert s.emir("BTC", "A", 5.0, reduce_only=True, acik_sz=0.05).dolu_mu                # tam kapanış serbest
    ex = SahteExchange(dolu("0.11", "100.1"))
    yu.GercekYurutucu(ex, meta_post, RULES).emir("BTC", "B", 11.0, bant=0.01, cloid="0x" + "ab" * 16)
    assert ex.cagrilar[0]["px"] == 101.0 and str(ex.cloidler[0]) == "0x" + "ab" * 16               # bant %1 (kapanış merdiveni): 100 × 1,01
