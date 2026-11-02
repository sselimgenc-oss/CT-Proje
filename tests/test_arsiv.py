from datetime import UTC, datetime, timedelta

import pandas as pd

from copytrade.arsiv import Arsiv, collect, pool

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def test_altin_ornek_imlec_sonraki_milisaniyeden_baslar_ve_yol(tmp_path):
    archive = Arsiv(tmp_path, NOW)
    fill = {"adres": "0xabc", "tid": 7, "time": 123}
    assert archive.append("dolum", [fill], subject="0xabc", cursor=124) == 1
    assert archive.cursor_start("dolum", "0xabc", 0) == 124
    assert list((tmp_path / "tur=dolum" / "gun=2026-10-28").glob("*.parquet"))


def test_altin_ornek_44_dk_bosluk_degil_46_dk_bosluk(tmp_path):
    archive = Arsiv(tmp_path, NOW)
    archive.poll("pozisyon", "a", 900_000)
    archive.now = NOW + timedelta(minutes=44)
    archive.poll("pozisyon", "a", 900_000)
    assert archive.summary()["bosluk"] == 0
    archive = Arsiv(tmp_path / "x", NOW)
    archive.poll("pozisyon", "a", 900_000)
    archive.now = NOW + timedelta(minutes=46)
    archive.poll("pozisyon", "a", 900_000)
    try:
        archive.summary()
    except RuntimeError:
        pass
    else:
        raise AssertionError("%10 üstü boşluk kırmızı olmalı")


def test_altin_ornek_guncel_kapi_havuzu_ve_olay_semasi(tmp_path):
    (tmp_path / "copytrade").mkdir()
    (tmp_path / "copytrade" / "izleme_listesi.yaml").write_text("traderlar: []")
    gate = tmp_path / "kapi" / "2026-10-28"
    gate.mkdir(parents=True)
    pd.DataFrame([{"address": "0x" + "a" * 40, "adim1": "Geçti", "adim2": "Geçti"}]).to_csv(gate / "sonuc.csv", index=False)
    assert pool(tmp_path, tmp_path / "kapi") == ["0x" + "a" * 40]
    archive = Arsiv(tmp_path / "a", NOW)
    archive.empty_schema("olay")
    assert (tmp_path / "a" / "tur=olay" / "gun=2026-10-28" / "sema.parquet").exists()


def test_altin_ornek_acik_pozisyon_coini_1dk_muma_gider(tmp_path):
    (tmp_path / "copytrade").mkdir()
    (tmp_path / "copytrade" / "izleme_listesi.yaml").write_text("traderlar: []")
    gate = tmp_path / "kapi" / "2026-10-28"
    gate.mkdir(parents=True)
    pd.DataFrame([{"address": "0x" + "b" * 40, "adim1": "Geçti", "adim2": "Geçti"}]).to_csv(gate / "sonuc.csv", index=False)
    class Fake:
        limiter = type("L", (), {"weight_used": 2})()
        def info(self, payload, weight=20):
            return {"assetPositions": [{"position": {"coin": "HIP:TEST"}}]}
        def candles(self, coin, start, end, interval):
            assert (coin, interval) == ("HIP:TEST", "1m")
            return [{"coin": coin, "t": start}]
    collect(tmp_path, tmp_path / "out", {"pozisyon", "mum_1dk"}, gate_root=tmp_path / "kapi", client=Fake(), now=NOW)
    assert list((tmp_path / "out" / "tur=mum_1dk").rglob("*.parquet"))
