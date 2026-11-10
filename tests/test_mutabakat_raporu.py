"""F05: elle hesaplanmış fiyat, kayma, ücret ve gerçekleşen net örnekleri."""
import pytest

from copytrade.kopya_v3 import hedef_ms
from copytrade.mutabakat_raporu import markdown, raporla


def test_bir_trader_elle_mutabakat():
    rules = {"canli_kasa_usd": 1000, "maliyet_taker": 0.0004, "maliyet_kayma": 0.0006, "radar_kopya_gecikme_dk": 1}
    adres, zaman = "T1", 60_000
    kayit = [{"olay": "emir", "kip": "sanal", "adres": adres, "coin": "BTC", "yon": "B", "trader_dolum_ms": zaman,
              "durum": "dolu", "usd_dolan": 100, "dolum_px": 102, "kayma_trader": 0.02, "ucret": 0.04, "pnl_usd": 3},
             {"olay": "emir_yok", "kip": "sanal", "adres": adres, "coin": "ETH", "trader_dolum_ms": 80_000}]
    replay = {adres: {"dolumlar": [{"coin": "BTC", "time": zaman}],
                       "yurutme": {"BTC": {hedef_ms(zaman, 1): 100}},
                       "sonuc": {"maliyet": 0.001, "gerceklesen": 0.004, "funding": 0}}}
    out = raporla(kayit, replay, 0, 120_000, rules)
    u = out["uyeler"][adres]
    assert (u["emir"], u["atlanan"], u["fiyat_eslesme"]) == (1, 1, 1)
    assert u["fiyat_fark_oran_ort"] == pytest.approx(0.02)
    assert u["canli_kayma_usd"] == pytest.approx(2)
    assert u["oynatma_kayma_usd"] == pytest.approx(0.6)
    assert u["oynatma_ucret_usd"] == pytest.approx(0.4)
    assert u["canli_net_kz_usd"] == pytest.approx(2.96)
    assert u["oynatma_net_kz_usd"] == pytest.approx(4)
    assert u["net_kz_farki_usd"] == pytest.approx(-1.04)
    assert "TOPLAM" in markdown(out)


def test_fiyat_eslesmeyince_uydurulmaz_ve_eksik_pnl_net_olmaz():
    rules = {"canli_kasa_usd": 1000, "maliyet_taker": 0.0004, "maliyet_kayma": 0.0006, "radar_kopya_gecikme_dk": 1}
    kayit = [{"olay": "emir", "kip": "sanal", "adres": "T", "coin": "BTC", "eylem": "kapat", "trader_dolum_ms": 1,
              "durum": "dolu", "usd_dolan": 100, "dolum_px": 100, "pnl_usd": None, "ucret": 0.04}]
    out = raporla(kayit, {"T": {"sonuc": {"maliyet": 0, "gerceklesen": 0, "funding": 0}}}, 0, 10, rules)["uyeler"]["T"]
    assert out["fiyat_fark_oran_ort"] is None and out["fiyat_eslesme"] == 0
    assert out["canli_net_kz_usd"] is None and out["net_kz_farki_usd"] is None


def test_acilisin_null_pnl_i_neti_bozmaz():
    """İnceleme: `emir.pnl_usd` açılışta tanımı gereği null. Açılış (ücret 0,04) + kapanış (pnl +3, ücret 0,04) → net 3 − 0,08 = 2,92 $."""
    rules = {"canli_kasa_usd": 1000, "maliyet_taker": 0.0004, "maliyet_kayma": 0.0006, "radar_kopya_gecikme_dk": 1}
    kayit = [{"olay": "emir", "kip": "sanal", "adres": "T", "coin": "BTC", "eylem": "ac", "trader_dolum_ms": 1, "durum": "dolu", "usd_dolan": 100, "dolum_px": 100, "pnl_usd": None, "ucret": 0.04},
             {"olay": "emir", "kip": "sanal", "adres": "T", "coin": "BTC", "eylem": "kapat", "trader_dolum_ms": 5, "durum": "dolu", "usd_dolan": 103, "dolum_px": 103, "pnl_usd": 3, "ucret": 0.04}]
    out = raporla(kayit, {"T": {"sonuc": {"maliyet": 0, "gerceklesen": 0, "funding": 0}}}, 0, 10, rules)["uyeler"]["T"]
    assert out["canli_net_kz_usd"] == pytest.approx(2.92)
