from copytrade.defter import DAY, HOUR
from copytrade.golge import Gecikme, calistir, kirp_pozisyon, saglama, v2_sinir
from copytrade.kurallar import load_rules
import pytest
import pandas as pd
from copytrade.tarama import PublicClient

T0 = 20_833 * DAY
RULES = load_rules()


def fill(minute, side, size, before, px, tid=1):
    return {"time": T0 + minute * 60_000, "coin": "BTC", "side": side, "sz": str(size), "startPosition": str(before), "px": str(px), "tid": tid}


def candles(*prices):
    return {"BTC": [{"t": T0 + hour * HOUR, "o": price, "c": price} for hour, price in enumerate(prices)]}


def test_altin_v0_kismi_kapama_flip_funding_ve_saglama():
    fills = [fill(10, "B", 10, 0, 100), fill(20, "A", 5, 10, 110, 2), fill(30, "A", 10, 5, 120, 3)]
    result = calistir(fills, candles(100, 110, 120, 120), 1000, style="intraday", etiket_ms=T0, end_ms=T0 + 3 * HOUR, variant="V0", delay_min=0)
    assert result["defter"]["executed"] == 3  # kısmi kapanış ve flip defterin tek motorunda
    check = saglama(fills, candles(100, 110, 120, 120), 1000, T0, T0 + 3 * HOUR)
    assert check["costs"] == 0 and check["missing"] == 0


def test_altin_v1_bant_ve_eksik_kacirilan_satiri_kaybolmaz():
    rows = [fill(10, "B", 1, 0, 100), fill(20, "A", 1, 1, 100, 2)]
    result = calistir(rows, candles(100, 103), 1000, style="intraday", etiket_ms=T0, end_ms=T0 + HOUR, variant="V1")
    assert any(event["durum"] == "atlandi_bant" for event in result["olaylar"])
    assert any(event["durum"] == "kacirildi" for event in result["olaylar"])


def test_sentetik_sifir_etkili_trader_saglamada_sifir_pnl_uretir():
    rows = [fill(10, "B", 1, 0, 100), fill(20, "A", 1, 1, 100, 2)]
    check = saglama(rows, candles(100, 100), 1000, T0, T0 + HOUR)
    assert check["net"] == 0.0


def test_sentetik_enjekte_edilmis_etki_pozitif_pnl_olarak_yakalanir():
    rows = [fill(10, "B", 1, 0, 100), fill(20, "A", 1, 1, 120, 2)]
    check = saglama(rows, candles(100, 120), 1_000, T0, T0 + HOUR)
    assert check["net"] == 0.02


def test_altin_v2_8_gunde_eksi31_cikar_6_gunde_eksi49_kalir():
    assert v2_sinir("swing", 8, -0.31) == "zarar_kes"
    assert v2_sinir("swing", 6, -0.49) is None
    assert v2_sinir("swing", 14, 0.40) == "kar_al"


def test_altin_v2_donmus_esikleri_kullanir():
    assert RULES["golge_v2"]["intraday"]["zarar_kes"] == -0.50
    assert RULES["golge_v2"]["swing"]["gun_7"] == {"zarar_kes": -0.30, "kar_al": 0.60}
    assert RULES["golge_v2"]["swing"]["gun_14"] == {"zarar_kes": -0.20, "kar_al": 0.40}


def test_altin_3x_asan_ekleme_kirpilir():
    clipped, event = kirp_pozisyon(fill(10, "B", 40, 0, 100), 20 / 1_000, 1_000)
    assert float(clipped["sz"]) == pytest.approx(10.0)
    assert event["durum"] == "kirpildi" and event["tavan_usd"] == 3.0


def test_altin_v2_8_gunde_eksi31_mumda_maliyetli_cikar():
    rows = [fill(10, "B", 1_000, 0, 100)]
    market = {"BTC": [{"t": T0 + h * HOUR, "o": 100 if h < 8 * 24 else 69, "c": 100 if h < 8 * 24 else 69}
                      for h in range(8 * 24 + 2)]}
    out = calistir(rows, market, 1_000, style="swing", etiket_ms=T0, end_ms=T0 + 9 * 24 * HOUR, variant="V2", delay_min=0)
    assert any(event["durum"] == "v2_cikis" for event in out["olaylar"])
    assert out["defter"]["costs"] > 0


def test_altin_v2_swing_esikleri_fiyat_ve_maliyetle_donuyor():
    rows = [fill(0, "B", 10, 0, 100)]
    market = {"BTC": [{"t": T0 + h * HOUR, "o": 100 if h < 8 * 24 else 69, "c": 100 if h < 8 * 24 else 69}
                      for h in range(9 * 24 + 1)]}
    out = calistir(rows, market, 1_000, style="swing", etiket_ms=T0, end_ms=T0 + 9 * DAY, variant="V2", delay_min=0)
    event = next(item for item in out["olaylar"] if item["durum"] == "v2_cikis")
    assert event["zaman_ms"] == T0 + 8 * DAY
    # 0,01 BTC: giriş 100, zorunlu çıkış 69; iki dolumun taker+kayma maliyeti.
    assert out["defter"]["costs"] == pytest.approx(0.01 * (100 + 69) * 0.00095)


def test_altin_v2_6_gun_eksi49_kalir_15_gun_artı41_kar_alir():
    rows = [fill(0, "B", 10, 0, 100)]
    six = {"BTC": [{"t": T0 + h * HOUR, "o": 51, "c": 51} for h in range(6 * 24 + 1)]}
    assert not any(x["durum"] == "v2_cikis" for x in calistir(rows, six, 1_000, style="swing", etiket_ms=T0,
                                                                 end_ms=T0 + 6 * DAY, variant="V2", delay_min=0)["olaylar"])
    fifteen = {"BTC": [{"t": T0 + h * HOUR, "o": 100 if h < 15 * 24 else 141, "c": 141}
                       for h in range(15 * 24 + 1)]}
    out = calistir(rows, fifteen, 1_000, style="swing", etiket_ms=T0, end_ms=T0 + 15 * DAY, variant="V2", delay_min=0)
    assert any(x["durum"] == "v2_cikis" and x["neden"] == "kar_al" for x in out["olaylar"])


def test_altin_v2_intraday_eksi50_cikar():
    rows = [fill(0, "B", 10, 0, 100)]
    out = calistir(rows, candles(100, 50), 1_000, style="intraday", etiket_ms=T0, end_ms=T0 + HOUR,
                   variant="V2", delay_min=0)
    assert any(x["durum"] == "v2_cikis" and x["neden"] == "zarar_kes" for x in out["olaylar"])


def test_altin_likidasyon_golgenin_kendi_teminat_ve_markiyla_cikar():
    rows = [fill(0, "B", 10, 0, 100)]
    out = calistir(rows, candles(100, 0), 1_000, style="intraday", etiket_ms=T0, end_ms=T0 + HOUR,
                   variant="V0", delay_min=0)
    assert any(x["durum"] == "likidasyon" and x["zaman_ms"] == T0 + HOUR for x in out["olaylar"])


def test_altin_gecikme_zinciri_kayit_yoksa_nedenle_bos_kalir_ve_kayitla_dolar():
    rows = [fill(0, "B", 1, 0, 100, 44)]
    empty = calistir(rows, candles(100), 1_000, style="intraday", etiket_ms=T0, end_ms=T0, delay_min=0)
    assert empty["gecikme_zinciri"] == [{"trader_ms": T0, "tespit_ms": None, "telegram_ms": None, "acti_ms": None, "neden": "karar_kaydi_yok"}]
    filled = calistir(rows, candles(100), 1_000, style="intraday", etiket_ms=T0, end_ms=T0, delay_min=0,
                      gecikmeler={44: Gecikme(T0, T0 + 1, T0 + 2, T0 + 3)})
    assert filled["gecikme_zinciri"][0] == {"trader_ms": T0, "tespit_ms": T0 + 1, "telegram_ms": T0 + 2, "acti_ms": T0 + 3, "neden": None}


def test_altin_v2_cikis_sonrasi_kapanis_atlanir_yeni_acilis_kopyalanir():
    rows = [fill(0, "B", 10, 0, 100), fill(9 * 24 * 60, "A", 10, 10, 69, 2),
            fill(10 * 24 * 60, "B", 10, 0, 70, 3)]
    market = {"BTC": [{"t": T0 + h * HOUR, "o": 100 if h < 8 * 24 else 69 if h < 10 * 24 else 70, "c": 70}
                      for h in range(11 * 24 + 1)]}
    out = calistir(rows, market, 1_000, style="swing", etiket_ms=T0, end_ms=T0 + 11 * DAY, variant="V2", delay_min=0)
    assert any(x["durum"] == "atlandi_v2" and x["dolum"]["tid"] == 2 for x in out["olaylar"])
    # Zorunlu çıkış + ilk açılış + sıfırlama sonrası yeni açılış: ters yönlü kapanış yok.
    assert out["defter"]["executed"] == 3
    assert out["defter"]["unrealized_end"] == 0


def test_altin_v2_ekleme_gecmis_mumlari_yeniden_taramaz():
    rows = [fill(0, "B", 10, 0, 100), fill(8 * 24 * 60, "B", 10, 10, 100, 2)]
    market = {"BTC": [{"t": T0 + h * HOUR, "o": 51 if h == 6 * 24 else 100, "c": 100}
                      for h in range(8 * 24 + 1)]}
    out = calistir(rows, market, 1_000, style="swing", etiket_ms=T0, end_ms=T0 + 8 * DAY, variant="V2", delay_min=0)
    assert not any(x["durum"] == "v2_cikis" for x in out["olaylar"])


def test_altin_tavan_hesap_serisi_dolum_anindaki_olcekle_buyur():
    account = pd.Series([1_000.0, 2_000.0], index=pd.to_datetime([T0, T0 + DAY], unit="ms"))
    rows = [fill(0, "B", 30, 0, 100), fill(24 * 60, "B", 60, 30, 100, 2)]
    out = calistir(rows, candles(*([100] * 26)), account, style="intraday", etiket_ms=T0, end_ms=T0 + DAY,
                   variant="V0", delay_min=0)
    # İlk dolum 3x tavana tam gelir; iki kat hesaptaki ikinci ekleme de aynı 3x gölge tavanına göre kırpılır.
    clipped = [x for x in out["olaylar"] if x["durum"] == "kirpildi"]
    assert clipped and float(clipped[0]["yeni_sz"]) == pytest.approx(0.0)


def test_altin_10000_ustu_dolum_zaman_penceresiyle_sayfalanir():
    class Client:
        fills = PublicClient.fills

        def info(self, payload, weight=20):
            start = int(payload["startTime"])
            page_no = (start - T0) // 2_000
            if page_no >= 6:
                return []
            count = 2_000 if page_no < 5 else 1
            return [{"tid": page_no * 2_000 + i, "time": T0 + page_no * 2_000 + i, "coin": "BTC", "sz": "1"}
                    for i in range(count)]

    rows = Client().fills("0xabc", T0)
    assert len(rows) == 10_001 and rows[-1]["tid"] == 10_000














def test_v2_mark_eksik_olan_pozisyon_her_dolumda_bastan_taranmaz():
    """Canlı izlemede bulundu (2026-10-30): bir coin'in işareti hiç yoksa v2 denetimi onu "denetlendi" saymıyor, başka coin'deki HER dolum
    aynı büyüyen boşluğu baştan tarıyordu; saatlik koşu 150 dk zaman aşımına uğrayıp veri yayımlanamadı. Süre yerine mark sorgusu sayılır."""
    from copytrade.golge import v2_cikislari
    from copytrade.defter import Market

    class Sayan(Market):
        sorgu = 0

        def mark(self, coin, hour):
            Sayan.sorgu += 1
            return super().mark(coin, hour)

    market = Sayan({"BTC": [{"t": T0, "o": "100", "c": "100"}], "ETH": [{"t": T0 + h * HOUR, "o": "10", "c": "10"} for h in range(400)]})
    rows = [fill(0, "B", 10, 0, 100)]
    rows += [{**fill(i * 120, "B", 1 if i == 0 else 0.001, 0 if i == 0 else 1, 10, tid=2 + i), "coin": "ETH"} for i in range(200)]
    allowed, exits, events = v2_cikislari(rows, market, 1000, "intraday", 0, T0 + 400 * HOUR, RULES)
    assert len(allowed) == 201
    assert Sayan.sorgu < 2 * 400 + 200      # eski kod bu senaryoda ~30.000 sorgu yapardı
