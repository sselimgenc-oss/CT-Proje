"""PBO (CSCV) + deflated Sharpe + PBO raporu: bilinen sentetik durumlar ve elle hesaplanmış altın örnekler. Ağsız."""
import json
import math

import numpy as np
import pytest

from copytrade import pbo as P
from copytrade import pbo_rapor as R


def test_altin_pbo_tam_asiri_uydurma_ve_tam_tutarli():
    # T=4, S=2 blok ([0,1] ve [2,3]), N=2, ölçüt ortalama. A=[3,3,1,1], B=[2,2,2,2]:
    # IS=blok0 → A (3>2); OOS blok1: A=1, B=2 → A sıra 1/3 → ω=1/3, λ=ln(0,5)<0. IS=blok1 → B (2>1); OOS blok0: B=2<A=3 → ω=1/3. PBO = 2/2 = 1.
    m = np.array([[3, 2], [3, 2], [1, 2], [1, 2]], dtype=float)
    r = P.pbo(m, s=2, olcut="ortalama")
    assert r["durum"] == "tamam" and r["bolunme"] == 2 and r["pbo"] == 1.0
    assert r["oos_sira_ort"] == pytest.approx(1 / 3) and r["lambda_medyan"] == pytest.approx(math.log(0.5))
    # A her blokta üstün → IS'te A, OOS'ta da en iyi (sıra 2/3, λ=ln 2 > 0) → PBO 0
    tutarli = np.array([[3, 1], [3, 1], [3, 1], [3, 1]], dtype=float)
    r2 = P.pbo(tutarli, s=2, olcut="ortalama")
    assert r2["pbo"] == 0.0 and r2["oos_sira_ort"] == pytest.approx(2 / 3)


def test_saf_gurultu_pbo_yaklasik_yarim():
    rng = np.random.default_rng(12345)
    degerler = [P.pbo(rng.normal(0, 1, (160, 12)), s=8)["pbo"] for _ in range(6)]
    assert 0.3 < float(np.mean(degerler)) < 0.7                # gürültüde ≈ 0,5 (tek koşu geniş dalgalanır; 6 koşunun ortalaması)


def test_tek_gercek_beceri_sutunu_pbo_dusuk():
    rng = np.random.default_rng(7)
    m = rng.normal(0, 1, (160, 10))
    m[:, 3] += 1.0                                              # sütun 3 her dönemde gerçekten üstün
    r = P.pbo(m, s=8)
    assert r["pbo"] < 0.1
    assert int(np.argmax(r["is_en_iyi_sayim"])) == 3


def test_yetersiz_veri_nazikce():
    r = P.pbo(np.zeros((15, 3)), s=8)                           # T=15 < 2*S=16
    assert r["durum"] == P.YETERSIZ and r["pbo"] is None
    assert P.pbo(np.zeros((40, 1)), s=8)["durum"] == P.YETERSIZ  # tek aday
    with pytest.raises(ValueError):
        P.pbo(np.array([[1.0, float("nan")]] * 20), s=8)


def test_t_s_katina_kirpilir_en_eski_atilir():
    rng = np.random.default_rng(1)
    r = P.pbo(rng.normal(size=(19, 4)), s=8)                    # 19 → 16 (2 gün/blok), 3 eski dönem atılır
    assert r["t"] == 16 and r["bolunme"] == 70


def test_deflated_sharpe_elle_hesap_ve_sinirlar():
    # N=1: SR0=0. sr=0,2, T=101 → z = 0,2·√100 / √(1 + (3−1)/4·0,04) = 2/√1,02 = 1,980295; Φ(1,980295) ≈ 0,97614
    assert P.deflated_sharpe(0.2, 1, 0.0, 101) == pytest.approx(0.97614, abs=2e-4)
    # çok denemede şans eşiği yükselir → DSR düşer
    assert P.deflated_sharpe(0.2, 100, 0.01, 101) < P.deflated_sharpe(0.2, 2, 0.01, 101) < 0.97614
    assert P.deflated_sharpe(0.2, 5, 0.01, 1) is None and P.deflated_sharpe(0.2, 0, 0.01, 50) is None
    assert 0.0 < P.deflated_sharpe(0.0, 10, 0.01, 60) < 0.5


def test_deflated_sharpe_matris():
    rng = np.random.default_rng(3)
    m = rng.normal(0, 1, (80, 6))
    m[:, 2] += 0.8
    d = P.deflated_sharpe_matris(m)
    assert d["sutun"] == 2 and d["dsr"] > 0.9
    assert P.deflated_sharpe_matris(np.zeros((3, 2)))["dsr"] is None


def isabet(tarih, **g):
    gr = {ad: {"n": 5, "ortalama": v} for ad, v in g.items() if ad != "havuz"}
    return {"tarih": tarih, "pencere_tam": True, "gruplar": gr, "havuz": {"n": 20, "ortalama": g.get("havuz", 0.0)}}


def test_rapor_yetersiz_veri_ve_json_yazilabilir():
    r = R.rapor_olustur([isabet("2026-11-20", ilk11=0.01, havuz=0.0, elenen=-0.01)], "2026-11-27")
    assert r["durum"] == "yetersiz veri" and r["pbo"] is None and r["t"] == 1
    assert "yetersiz veri" in R.ozet_satiri(r)
    json.dumps(r, allow_nan=False)


def test_rapor_matris_kisimi_eksik_adayi_atar_ve_tamam_hesaplar():
    rng = np.random.default_rng(5)
    gunler = []
    for k in range(20):
        i = isabet(f"2026-12-{k + 1:02d}", ilk11=float(rng.normal(0.01, 0.02)), havuz=float(rng.normal(0, 0.02)), elenen=float(rng.normal(-0.01, 0.02)),
                   evren_ornek30=float(rng.normal(0, 0.02)))
        if k % 2:
            i["gruplar"]["ilk11_fiili"] = {"n": 0, "ortalama": None}       # her günde yok → sütun atılır
        gunler.append(i)
    gunler.append({**isabet("2026-12-31", ilk11=1, havuz=1, elenen=1), "pencere_tam": False})     # kısmi pencere sayılmaz
    r = R.rapor_olustur(gunler, "2026-12-31", s=8)
    assert r["durum"] == "tamam" and r["t"] == 20 and set(r["adaylar"]) == {"ilk11", "havuz", "elenen", "evren_ornek30"}
    assert "ilk11_fiili" in r["atlanan_aday"] and any("kısmi" in x for x in r["atlanan_gun"])
    assert 0.0 <= r["pbo"] <= 1.0 and r["dsr"]["aday"] in r["adaylar"]
    assert "PBO (CSCV, S=8, T=16" in R.ozet_satiri(r)
    json.dumps(r, allow_nan=False)


def test_rapor_ek_aday_ml_filtresi_sutunu():
    gunler = [isabet(f"2026-12-{k + 1:02d}", ilk11=0.01 * (k % 3), havuz=0.0, elenen=-0.01) for k in range(18)]
    ek = {"ml_acik": {g["tarih"]: 0.005 * (k % 4) for k, g in enumerate(gunler)}}
    r = R.rapor_olustur(gunler, "2026-12-18", s=8, ek_aday=ek)
    assert "ml_acik" in r["adaylar"]


def test_rapor_main_yerel_dosyalar(tmp_path):
    for k in range(18):
        d = tmp_path / f"2026-12-{k + 1:02d}"
        d.mkdir()
        (d / "isabet.json").write_text(json.dumps(isabet(f"2026-12-{k + 1:02d}", ilk11=0.01 * (k % 3), havuz=0.001 * k, elenen=-0.01 * (k % 2))), encoding="utf-8")
    md = tmp_path / "OZET.md"
    assert R.main(["--kok", str(tmp_path), "--cikti", str(tmp_path), "--ozet-md", str(md)]) == 0
    p = json.loads((tmp_path / "2026-12-18" / "pbo.json").read_text(encoding="utf-8"))
    assert p["durum"] == "tamam" and p["sema"] == "pbo-v1"
    assert md.read_text(encoding="utf-8").startswith("PBO (CSCV")
