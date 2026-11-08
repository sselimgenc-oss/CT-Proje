"""S-12: gerçek ↔ sanal dolum karşılaştırma raporu — elle hesaplanmış altın örnekler (taker 0,00045; bant 0,005; min nosyonel 10 $)."""
from __future__ import annotations

import json

import pytest

from copytrade.canli import gercek_sanal_karsilastir as gs
from copytrade.kurallar import load_rules

KURAL = {**load_rules(), "maliyet_taker": 0.00045, "canli_ioc_bant": 0.005, "canli_min_nosyonel_usd": 10, "canli_kasa_usd": 1000}
SZ_DEC = {"BTC": 5, "ETH": 4, "SOL": 2}


def _emir(**k):
    return {"olay": "emir", "kip": "gercek", "adres": "0xtr", "eylem": "ac", "reduce_only": False, "bant": 0.005, "red_neden": "", **k}


# 1) birebir: BTC alış 100 $, defter ask 100000 → sz 0,001 (5 ondalıkta tam), kayma 0, ücret 100 × 0,00045 = 0,045 (gerçek ücret tahmin: `ucret_tahmin` olayı var)
E1 = _emir(coin="BTC", yon="B", usd_istenen=100.0, usd_dolan=100.0, sz=0.001, durum="dolu", referans_px=100000.0, dolum_px=100000.0, kayma_ref=0.0, ucret=0.045,
           cloid="0xa", emir_ms=1000, trader_dolum_ms=900, defter={"levels": [[{"px": "99990", "sz": "1"}], [{"px": "100000", "sz": "1"}]]})
# 2) yuvarlama kaynaklı kısmi: SOL alış 20 $ @150 → 20/150 = 0,1333 → 2 ondalık 0,13 → 19,5 $ < 19,98 $ → kismi. Gerçek dolum 150,1 (kayma 0,1/150), ücret HL 0,0088.
#    Defter yok → sanal referans_tek_seviye: sz 0,13333…, 20 $, dolu, kayma 0, ücret 0,009.
E2 = _emir(coin="SOL", yon="B", usd_istenen=20.0, usd_dolan=19.513, sz=0.13, durum="kismi", referans_px=150.0, dolum_px=150.1, kayma_ref=0.1 / 150, ucret=0.0088,
           cloid="0xb", emir_ms=2000, trader_dolum_ms=1900)
# 3) red: ETH satış 30 $; sanal defter bid 3000 × 10 → sz 0,01, 30 $, dolu, ücret 0,0135
E3 = _emir(coin="ETH", yon="A", usd_istenen=30.0, usd_dolan=0.0, sz=0.0, durum="red", red_neden="Order could not immediately match", referans_px=3000.0, dolum_px=None,
           kayma_ref=None, ucret=0.0, cloid="0xc", emir_ms=3000, trader_dolum_ms=2900, defter={"levels": [[{"px": "3000", "sz": "10"}], [{"px": "3001", "sz": "10"}]]})
# 4) emir öncesi hata: referans_px yok → veri_yok
E4 = _emir(coin="ETH", yon="B", usd_istenen=15.0, usd_dolan=0.0, sz=0.0, durum="red", red_neden="sdk_hatasi: ConnectionError", referans_px=None, dolum_px=None,
           kayma_ref=None, ucret=0.0, cloid="0xd", emir_ms=4000, trader_dolum_ms=3900)
TAHMIN = {"olay": "ucret_tahmin", "adres": "0xtr", "coin": "BTC", "cloid": "0xa", "ucret": 0.045}


def _yaz(dizin, ad, satirlar):
    dizin.mkdir(parents=True, exist_ok=True)
    (dizin / ad).write_text("\n".join(json.dumps(s) for s in satirlar) + "\n", encoding="utf-8")


@pytest.fixture
def rapor(tmp_path):
    g = tmp_path / "gercek"
    _yaz(g, "2026-11-20.jsonl", [E3, E1, TAHMIN, {"olay": "emir_yok", "kip": "gercek"}])
    _yaz(g, "2026-11-21.jsonl", [E4, E2, "bozuk"])
    return gs.karsilastir(gs.kayit_oku(g), None, n=50, sz_decimals=SZ_DEC, rules=KURAL)


def test_birebir_eslesme(rapor):
    s = rapor["satirlar"][0]
    assert (s["coin"], s["sanal_kaynak"], s["gercek_durum"], s["sanal_durum"], s["durum_ayni"]) == ("BTC", "defter", "dolu", "dolu", True)
    assert s["sanal_sz"] == pytest.approx(0.001)
    assert s["sanal_ucret"] == pytest.approx(0.045)
    assert s["sanal_kayma"] == pytest.approx(0.0)
    assert s["sz_fark"] == pytest.approx(0.0, abs=1e-15) and s["kayma_fark"] == pytest.approx(0.0) and s["ucret_fark"] == pytest.approx(0.0, abs=1e-12)
    assert s["gercek_ucret_kesin"] is False                                   # ucret_tahmin olayı var
    assert s["ucret_tahmini"] == pytest.approx(0.045)
    assert s["yuvarlanmis_sz"] == 0.001 and s["yuvarlama_kaynakli_kismi"] is False


def test_yuvarlama_kaynakli_kismi(rapor):
    s = rapor["satirlar"][1]
    assert (s["coin"], s["sanal_kaynak"], s["gercek_durum"], s["sanal_durum"], s["durum_ayni"]) == ("SOL", "referans_tek_seviye", "kismi", "dolu", False)
    assert s["sanal_sz"] == pytest.approx(20 / 150)
    assert s["sanal_usd_dolan"] == pytest.approx(20.0)
    assert s["sanal_ucret"] == pytest.approx(0.009)
    assert s["sz_fark"] == pytest.approx(0.13 - 20 / 150)                    # −0,0033333 coin
    assert s["sz_fark_usd"] == pytest.approx(-0.5)                            # × 150
    assert s["kayma_fark"] == pytest.approx(0.1 / 150)                        # 0,000666667 − 0
    assert s["ucret_fark"] == pytest.approx(-0.0002)                          # 0,0088 − 0,009
    assert s["gercek_ucret_kesin"] is True
    assert s["ucret_tahmini"] == pytest.approx(19.513 * 0.00045)              # 0,00878085
    assert s["yuvarlanmis_sz"] == 0.13 and s["yuvarlama_kaynakli_kismi"] is True


def test_red_ve_veri_yok(rapor):
    s3, s4 = rapor["satirlar"][2], rapor["satirlar"][3]
    assert (s3["gercek_durum"], s3["sanal_durum"], s3["sanal_kaynak"]) == ("red", "dolu", "defter")
    assert s3["sanal_sz"] == pytest.approx(0.01) and s3["sanal_ucret"] == pytest.approx(0.0135)
    assert s3["sz_fark_usd"] == pytest.approx(-30.0) and s3["ucret_fark"] == pytest.approx(-0.0135) and s3["kayma_fark"] is None
    assert s3["gercek_ucret_kesin"] is None and s3["ucret_tahmini"] == 0.0
    assert s4["sanal_kaynak"] == "veri_yok" and s4["sanal_durum"] is None and s4["ucret_fark"] is None and s4["yuvarlama_kaynakli_kismi"] is None


def test_toplam_tablo(rapor):
    t = rapor["toplam"]
    assert (t["emir"], t["sanal_verili"], t["veri_yok"]) == (4, 3, 1)
    assert t["sanal_kaynak"] == {"defter": 2, "sanal_kayit": 0, "referans_tek_seviye": 1, "veri_yok": 1}
    assert t["gercek_red_orani"] == 0.5 and t["gercek_kismi_orani"] == 0.25 and t["gercek_dolmadi_orani"] == 0.0
    assert t["sanal_red_orani"] == 0.0 and t["sanal_kismi_orani"] == 0.0
    assert t["durum_ayni_orani"] == pytest.approx(1 / 3)
    assert t["yuvarlama_kaynakli_kismi"] == 1
    assert t["kayma_fark_n"] == 2
    assert t["kayma_fark_medyan"] == pytest.approx(0.1 / 300)                 # medyan(0; 0,000666667) = 0,000333333
    assert t["kayma_fark_max"] == pytest.approx(0.1 / 150)
    assert t["ucret_fark_toplam_usd"] == pytest.approx(-0.0137)               # 0 − 0,0002 − 0,0135
    assert t["ucret_fark_toplam_1000"] == pytest.approx(-0.0137)              # kasa 1000 → çarpan 1
    assert t["ucret_kesin_olmayan"] == 1


def test_kasa_olcegi_ve_ilk_n(tmp_path):
    g = tmp_path / "g"
    _yaz(g, "a.jsonl", [E3, E2, E1, E4])
    r = gs.karsilastir(gs.kayit_oku(g), n=2, kasa_usd=500, sz_decimals=SZ_DEC, rules=KURAL)
    assert [s["coin"] for s in r["satirlar"]] == ["BTC", "SOL"]               # emir_ms sırasıyla ilk 2
    assert r["olcek_1000"] == 2.0
    assert r["toplam"]["ucret_fark_toplam_usd"] == pytest.approx(-0.0002)
    assert r["toplam"]["ucret_fark_toplam_1000"] == pytest.approx(-0.0004)    # × 1000/500


def test_sanal_kayit_eslesmesi_ve_kip_suzgeci(tmp_path):
    sanal_ayni = {"olay": "emir", "kip": "sanal", "adres": "0xtr", "coin": "SOL", "eylem": "ac", "trader_dolum_ms": 1900, "durum": "dolu", "sz": 0.1332, "usd_dolan": 19.99,
                  "dolum_px": 150.075, "kayma_ref": 0.0005, "ucret": 0.009, "red_neden": ""}
    sanal_baska = {**sanal_ayni, "trader_dolum_ms": 1, "sz": 9.0}
    gercek_icinde_sanal = {**E1, "kip": "sanal", "emir_ms": 1}               # gerçek dizindeki sanal satır sayılmaz
    r = gs.karsilastir([E2, gercek_icinde_sanal], [sanal_baska, sanal_ayni], sz_decimals=None, rules=KURAL)
    assert len(r["satirlar"]) == 1
    s = r["satirlar"][0]
    assert s["sanal_kaynak"] == "sanal_kayit" and s["sanal_sz"] == 0.1332
    assert s["kayma_fark"] == pytest.approx(0.1 / 150 - 0.0005)
    assert s["ucret_fark"] == pytest.approx(-0.0002)
    assert s["sz_fark_usd"] == pytest.approx((0.13 - 0.1332) * 150)           # −0,48 $
    assert s["yuvarlanmis_sz"] is None                                        # szDecimals verilmedi


def test_reduce_only_acik_sz_ile_tam_kapanis():
    # reduce-only kapat: biz_poz_usd 12 $ @ ref 3000 → acik_sz 0,004; istenen 12,6 $ (×1,05) → sanal 0,004 ile kırpılır → TAM kapanış → dolu
    e = _emir(coin="ETH", yon="A", eylem="kapat", reduce_only=True, usd_istenen=12.6, usd_dolan=12.0, sz=0.004, durum="dolu", referans_px=3000.0, dolum_px=3000.0,
              kayma_ref=0.0, ucret=0.0054, cloid="0xe", emir_ms=1, trader_dolum_ms=1, biz_poz_usd=12.0)
    s = gs.karsilastir([e], rules=KURAL)["satirlar"][0]
    assert s["sanal_durum"] == "dolu" and s["sanal_sz"] == pytest.approx(0.004) and s["sanal_ucret"] == pytest.approx(0.0054)


def test_cli_md_json(tmp_path, capsys):
    g = tmp_path / "g"
    _yaz(g, "a.jsonl", [E1, E2, E3, E4])
    dec = tmp_path / "sz.json"
    dec.write_text(json.dumps(SZ_DEC))
    md, js = tmp_path / "r.md", tmp_path / "r.json"
    assert gs.main(["--gercek-kayit", str(g), "--sz-decimals", str(dec), "--md", str(md), "--json", str(js), "--kasa-usd", "1000"]) == 0
    veri = json.loads(js.read_text())
    assert veri["toplam"]["emir"] == 4 and veri["toplam"]["yuvarlama_kaynakli_kismi"] == 1
    metin = md.read_text()
    assert "| Red oranı | %50.00 | %0.00 |" in metin and "veri_yok" in metin
    bos = tmp_path / "bos"
    bos.mkdir()
    assert gs.main(["--gercek-kayit", str(bos)]) == 1
