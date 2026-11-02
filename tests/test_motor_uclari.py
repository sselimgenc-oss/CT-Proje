"""Paket E2–E4 ve E6 (ikinci genel denetim): gölge V1/V2/flip uçları, miras pozisyon 0/0, işaret yaşı, bayrak önbelleği.
Her test önce hatayı yeniden üretir (altın örnekle), sonra düzeltmeyle yeşile döner."""
import pytest

from copytrade import izleme_motoru as m
from copytrade import secim
from copytrade.defter import DAY, HOUR, Market, copy_ledger
from copytrade.golge import calistir, kirp_pozisyon
from copytrade.kurallar import load_rules

RULES = load_rules()
T0 = 20_833 * DAY


def fill(minute, side, size, before, px, tid=1, coin="BTC"):
    return {"time": T0 + minute * 60_000, "coin": coin, "side": side, "sz": str(size), "startPosition": str(before), "px": str(px), "tid": tid}


def candles(*prices):
    return {"BTC": [{"t": T0 + hour * HOUR, "o": price, "c": price} for hour, price in enumerate(prices)]}


# ---------------------------------------------------------------- E3: miras pozisyon 0/0
@pytest.mark.parametrize("variant", ["V0", "V1", "V2"])
def test_e3_miras_pozisyonu_kapatan_ilk_dolum_sifira_bolmez(variant):
    """Trader etiketten önce 1 BTC long; etiket sonrası ilk dolum onu kapatıyor. Kopyada pozisyon yok → hiçbir şey olmaz (net 0)."""
    out = calistir([fill(10, "A", 1, 1, 100)], candles(100, 100), 1000, style="intraday", etiket_ms=T0, end_ms=T0 + HOUR, variant=variant, delay_min=0)
    assert out["defter"]["net"] == 0.0 and out["defter"]["executed"] == 0


# ---------------------------------------------------------------- E2: V1 yetim pozisyon
def test_e2_v1_atlanan_ekleme_sonrasi_kapanis_golgedeki_pozisyonu_kapatir():
    """1 BTC açılır (giriş 100, bantta); ikinci 1 BTC ekleme bandı aşar (110, %10 > %1) ve atlanır; trader 2 BTC'yi 120'de kapatır.
    Kapanış bastırılırsa 1 BTC gölgede yetim kalır. Doğrusu: gölge tamamen kapanır, net = 0,001 × (120 − 100) − maliyet."""
    rows = [fill(10, "B", 1, 0, 100), fill(70, "B", 1, 1, 100, 2), fill(130, "A", 2, 2, 120, 3)]
    out = calistir(rows, candles(100, 100, 110, 120, 120), 1000, style="intraday", etiket_ms=T0, end_ms=T0 + 4 * HOUR, variant="V1", delay_min=0)
    assert any(e["durum"] == "atlandi_bant" for e in out["olaylar"])
    assert not any(e.get("neden") == "giris_atlandi" for e in out["olaylar"])              # kapanış gölgede pozisyon varken bastırılmaz
    assert out["defter"]["unrealized_end"] == 0.0                                           # yetim pozisyon yok
    assert out["defter"]["net"] == pytest.approx(0.001 * 20 - 0.001 * 100 * 0.00095 - 0.001 * 120 * 0.00095)


def test_e2_v1_giris_tamamen_atlandiysa_kapanis_hala_atlanir():
    rows = [fill(10, "B", 1, 0, 100), fill(70, "A", 1, 1, 100, 2)]
    out = calistir(rows, candles(100, 110, 100), 1000, style="intraday", etiket_ms=T0, end_ms=T0 + 2 * HOUR, variant="V1", delay_min=0)
    assert any(e.get("neden") == "giris_atlandi" for e in out["olaylar"]) and out["defter"]["executed"] == 0


# ---------------------------------------------------------------- E2: V2 kısmi azaltma
def test_e2_v2_kismi_azaltmada_giris_agirlikli_ortalama_kalir():
    """10 BTC @200 açılır; 5 BTC @160'a azaltılır; kalan 5 BTC'nin girişi 200'dür (160'a sıfırlanmaz). Hesap 1000: kalan büyüklük 0,005.
    Saat 2'de fiyat 99: getiri = 0,005 × (99 − 200) = −0,505 ≤ −0,50 → zarar_kes. (Hatalı giriş 160 ile −0,305: çıkış yok.)"""
    rows = [fill(10, "B", 10, 0, 200), fill(70, "A", 5, 10, 160, 2)]
    out = calistir(rows, candles(200, 160, 99, 99), 1000, style="intraday", etiket_ms=T0, end_ms=T0 + 3 * HOUR, variant="V2", delay_min=0)
    exits = [e for e in out["olaylar"] if e["durum"] == "v2_cikis"]
    assert len(exits) == 1 and exits[0]["neden"] == "zarar_kes" and exits[0]["zaman_ms"] == T0 + 2 * HOUR


def test_e2_v2_kismi_azaltma_pozisyon_yasini_sifirlamaz():
    """Swing, hesap 1000: 11,2 BTC açılır, 7. günde 1,2 BTC azaltılır (kalan 10 BTC → büyüklük 0,01). 8. günde fiyat 69: getiri = 0,01 × (69 − 100) = −0,31.
    7. günden sonra sınır −%30 → çıkış. Azaltma pozisyon yaşını sıfırlarsa sınır −%50'ye döner ve çıkış kaçar."""
    rows = [fill(10, "B", 11.2, 0, 100), fill(60 * 24 * 7 + 10, "A", 1.2, 11.2, 100, 2)]
    prices = [100 if h < 8 * 24 else 69 for h in range(8 * 24 + 3)]
    out = calistir(rows, candles(*prices), 1000, style="swing", etiket_ms=T0, end_ms=T0 + (8 * 24 + 2) * HOUR, variant="V2", delay_min=0)
    assert any(e["durum"] == "v2_cikis" and e["neden"] == "zarar_kes" for e in out["olaylar"])


# ---------------------------------------------------------------- E2: flip yeni parça tavana tabi
def test_e2_flip_cikis_artı_yeni_giris_yeni_parca_tavana_tabi():
    """Gölge +0,02 (20 BTC / hesap 1000, fiyat 100). Trader 100 BTC satıp ters çevirir: yeni short parça 0,08 → 8 $ > tavan 3 $. Çıkış tam yapılır,
    yeni parça tavana kırpılır: izinli toplam = 0,02 (çıkış) + 0,03 (tavan 3 $ / 100) = 0,05 → sz 50."""
    clipped, event = kirp_pozisyon(fill(10, "A", 100, 20, 100), 20 / 1000, 1000)
    assert float(clipped["sz"]) == pytest.approx(50.0)
    assert event["durum"] == "kirpildi" and event["eski_sz"] == "100" and event["tavan_usd"] == 3.0
    small, none = kirp_pozisyon(fill(10, "A", 30, 20, 100), 20 / 1000, 1000)          # flip, yeni parça 0,01 → 1 $ ≤ 3 $: kırpma yok
    assert none is None and float(small["sz"]) == 30.0
    reduce, none2 = kirp_pozisyon(fill(10, "A", 10, 20, 100), 20 / 1000, 1000)         # saf azaltma: dokunulmaz
    assert none2 is None and float(reduce["sz"]) == 10.0


# ---------------------------------------------------------------- E4: işaret yaşı
def test_e4_market_mark_yas_siniri_asilirsa_none():
    market = Market({"BTC": [{"t": T0, "o": 100, "c": 100}]})
    limit = int(RULES["isaret_yas_max_dk"]) * 60_000
    assert market.mark_at("BTC", T0 + limit) == (T0, 100.0)                  # sınırda geçerli
    assert market.mark_at("BTC", T0 + limit + 1) is None and market.mark("BTC", T0 + limit + 1) is None


def test_e4_eski_isaret_mark_missing_sayilir_defter_ve_canli():
    fills = [dict(fill(0, "B", 10, 0, 100), _execution_time=T0, _execution_price=100.0)]
    market = Market({"BTC": [{"t": T0, "o": 100, "c": 100}]})
    old = copy_ledger(fills, market, 1000, 0, T0, T0 + 5 * HOUR)             # son işaret 5 saat önce
    assert old["mark_missing"] == 1 and old["unrealized_end"] == 0.0 and old["mark_time"] is None
    fresh = copy_ledger(fills, market, 1000, 0, T0, T0 + HOUR)
    assert fresh["mark_missing"] == 0 and fresh["mark_time"] == T0


def test_e4_canli_sonuc_eksik_isaretleme_notu_tasir():
    t0 = m.timestamp("2026-10-27")
    f = {"time": m.millis("2026-10-27T01:00:00Z"), "tid": 1, "oid": "1", "coin": "BTC", "side": "B", "sz": "10", "startPosition": "0", "px": "100", "closedPnl": "0", "fee": "0"}
    candles_live = {"BTC": [{"t": m.millis("2026-10-27T01:30:00Z"), "o": 100}]}           # tek yürütme mumu; sonraki işaret yok
    stale = m.copy_results([f], candles_live, [], 1000, t0, m.timestamp("2026-10-27T06:00:00Z"), {})
    assert stale["isaret_eksik"] == 1 and "eksik işaretleme" in stale["not"] and stale["son_isaret"] is None
    fresh = m.copy_results([f], candles_live, [], 1000, t0, m.timestamp("2026-10-27T02:00:00Z"), {})
    assert fresh["isaret_eksik"] == 0 and "not" not in fresh


# ---------------------------------------------------------------- E6: bayrak önbelleği
def secim_sonucu(adaylar):
    return {"secim_surumu": "v1.3", "kapi_tarihi": "2026-10-28",
            "adresler": {"0x" + n * 40: {"kollar": ["aday", "havuz"], "hesap_degeri": 1000.0} for n in adaylar}}


def test_e6_bayrak_onbellegi_yeniden_kosuda_cagri_tekrarlamaz():
    calls = []

    def fn(address, value):
        calls.append(address)
        return {"bayrak_rol": "x"}
    result = secim_sonucu("abc")
    saved = []
    first = secim.bayrak_hesapla(result, fn, kaydet=lambda body: saved.append(dict(body, bayraklar=dict(body["bayraklar"]))))
    assert len(calls) == 3 and first["tamam"] is True and len(first["bayraklar"]) == 3
    assert [len(s["bayraklar"]) for s in saved] == [1, 2, 3, 3] and [s["tamam"] for s in saved] == [False, False, False, True]   # her adresten sonra checkpoint
    again = secim.bayrak_hesapla(result, fn, onbellek=first)
    assert len(calls) == 3 and again["bayraklar"] == first["bayraklar"]                    # tüm çağrılar önbellekten


def test_e6_yarim_kalan_kosu_yalniz_eksikleri_hesaplar_ve_surum_degisince_gecersiz():
    calls, state = [], {"fail": True}

    def fn(address, value):
        calls.append(address)
        if address == "0x" + "b" * 40 and state["fail"]:
            state["fail"] = False                      # yalnız ilk denemede 429
            raise RuntimeError("429")
        return {"bayrak_rol": "x"}
    result = secim_sonucu("abc")
    checkpoints = []
    with pytest.raises(RuntimeError):
        secim.bayrak_hesapla(result, fn, kaydet=lambda body: checkpoints.append(dict(body, bayraklar=dict(body["bayraklar"]))))
    partial = checkpoints[-1]
    assert list(partial["bayraklar"]) == ["0x" + "a" * 40] and partial["tamam"] is False
    calls.clear()
    done = secim.bayrak_hesapla(result, fn, onbellek=partial)
    assert calls == ["0x" + "b" * 40, "0x" + "c" * 40] and done["tamam"] is True            # a önbellekten; yalnız eksikler hesaplandı
    calls.clear()
    secim.bayrak_hesapla(result, fn, onbellek=dict(done, bayrak_surumu="eski-kod"))        # bayrak.py değişti: önbellek geçersiz
    assert len(calls) == 3
    calls.clear()
    secim.bayrak_hesapla(result, fn, onbellek=dict(done, kapi_tarihi="2026-10-21"))        # başka kapı/sürüm: önbellek geçersiz
    assert len(calls) == 3
