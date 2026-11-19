"""Ortak öğrenme paketi parça 2 (kopya, 84f6cad) temel testleri: karne + sanal kasa, CUSUM drift, ridge filtre (numpy). Elle hesaplı."""
from datetime import datetime, timezone

import pytest

from copytrade.ortak_ogrenme import drift, karne
from copytrade.ortak_ogrenme.kayit import Aday


def aday(i, ts, r, seans="open", **kw):
    return Aday(id=f"a{i}", proje="CT", kurulum="T_abc123", enstruman="BTC/USD", varlik_sinifi="kripto", yon="long", ts=ts, alindi=True, r=r, seans=seans, **kw)


def dt(g, s=12):
    return datetime(2027, 1, g, s, tzinfo=timezone.utc)


def test_karne_ve_sanal_kasa_altin_ornek():
    """r = +1, −0,5, +2; risk %1: 1000 → 1010 → 1004,95 → 1025,049 (1025,05). Getiri %2,505 (paket 2 ondalığa yuvarlar: 2.51); en derin (1010 − 1004,95)/1010 = %0,5."""
    a = [aday(1, dt(16, 1), 1.0), aday(2, dt(16, 2), -0.5), aday(3, dt(16, 3), 2.0), aday(4, dt(16, 4), None)]
    k = karne.karne(a)["T_abc123"]
    assert (k["aday"], k["alinan"], k["cozulen"]) == (4, 4, 3) and k["ort_r_alinan"] == pytest.approx(2.5 / 3)
    assert k["kasa"]["alinan"] == {"n": 3, "kasa": 1025.05, "getiri_pct": 2.51, "en_derin_pct": 0.5}
    with pytest.raises(ValueError):
        karne.sanal_kasa(a, baslangic=0)


def test_cusum_ve_kurulum_drift():
    assert drift.cusum([0.5] * 25)["alarms"] == []
    r = drift.cusum([-1.5] * 20)          # her adım S += 1,1344 − 0,5 → 20. işlemde alarm (MIN_N = 20)
    assert r["alarms"] == [20] and r["S"] == 0.0 and r["cooldown"] == 30
    d = drift.kurulum_drift([aday(i, dt(1 + i // 10, i % 10 + 1), -1.5) for i in range(20)])
    assert d["T_abc123"]["durum"] == "uyari" and d["T_abc123"]["alarms"] == [20]


def test_filtre_egit_kaydet_yukle_puan_ve_butunluk(tmp_path):
    pytest.importorskip("numpy")
    from copytrade.ortak_ogrenme import filtre
    adaylar = [aday(i, dt(1 + i // 24, i % 24), 1.0 if i % 2 else -1.0, ozellikler={"x": 2.0 if i % 2 else 10.0}) for i in range(60)]
    p = filtre.egit("T_abc123", adaylar, olusturma=dt(20))
    assert p["meta"]["n_egitim"] == 60 and p["meta"]["taban_oran"] == 0.5 and p["esik"] == pytest.approx(0.45)
    assert filtre.puan(p, {"x": 10.0}) < 0.45 < filtre.puan(p, {"x": 2.0})
    yol = filtre.kaydet(p, tmp_path)
    assert filtre.yukle(yol, simdi=dt(21))["meta"]["model_hash"] == p["meta"]["model_hash"]
    with pytest.raises(filtre.PaketHatasi):
        filtre.yukle(yol, simdi=datetime(2027, 2, 15, tzinfo=timezone.utc))        # 21 gün doldu
    assert filtre.egit("T_abc123", [aday(1, dt(2), 1.0), aday(2, dt(3), 2.0)]) is None       # tek sınıf
    kilitli = filtre.egit("T_abc123", adaylar, olusturma=dt(20), kilit=[(dt(1, 0), dt(1, 23))])
    assert kilitli["meta"]["kilit_dusen"] == 24 and kilitli["meta"]["n_egitim"] == 36
