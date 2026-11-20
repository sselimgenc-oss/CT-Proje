"""R5-6: pano AÇIK sekmesi 'Stop' satırı K-74 dinamik stopu (kurallar.yaml dinamik_stop: true) yok sayıp sabit %20 gösteriyor."""
from copytrade.canli import pano

A = "0x" + "a1" * 20


def test_acik_satiri_dinamik_stop():
    acik = [{"adres": A, "coin": "VVV", "sz": -10.0, "giris": 100.0, "mark": 100.0, "usd": 1000.0, "kz_usd": 0.0}]
    hesap = {"poz": {A: {"VVV": {"sz": -10.0, "giris": 100.0, "acilis_ms": 1, "kaldirac": 3.0}}}, "maks_kaldirac": {"VVV": 3.0}}
    kurallar = {"canli_felaket_stop_oran": 0.20, "dinamik_stop": True}
    s = pano.acik_satirlari(acik, hesap, kurallar, 2, "sanal")[0]
    # K-74 örneği: azami 3 short, 3x → tasfiye 114,2857, stop = %11,2857 (111,29)
    assert "111,29" in s["stop"], f"pano stop: {s['stop']!r} (motor gerçekte 111,29'da keser)"
