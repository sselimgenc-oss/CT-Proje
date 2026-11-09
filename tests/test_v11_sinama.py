"""v1.1 aday sınaması (yalnız bilgi): saf seçim/özet fonksiyonları."""
from copytrade import v11_sinama as v
from copytrade.kurallar import load_rules

RULES = load_rules()


def _kadro(n=13):
    s = []
    for i in range(1, n + 1):
        s.append({"adres": f"0x{i:02d}", "sira": i, "katman": "ilk11" if i <= 11 else "yedek", "form": 100 - i,
                  "bilesenler": {"G": 100 - i, "K": 50, "I1": 50, "I2": 50, "Y": 50, "H": (100 if i <= 3 else 0)}})
    return {"satirlar": s}


def test_varyant_sec_v1_ve_filtreler():
    kadro = _kadro()
    olcu = {f"0x{i:02d}": {"kis": i, "t": 2.0 if i % 2 else 1.9, "karli": 3 / 7 if i > 2 else 2 / 7} for i in range(1, 14)}
    olcu["0x13"] = {"kis": None, "t": None, "karli": None}
    sec = v.varyant_sec(kadro, olcu, RULES)
    assert sec["v1"] == [f"0x{i:02d}" for i in range(1, 12)]
    assert sec["kopya_islem_5"] == [f"0x{i:02d}" for i in range(5, 13)]           # ölçü yok (None) → geçmez
    assert sec["t_2"] == [f"0x{i:02d}" for i in (1, 3, 5, 7, 9, 11)]              # t = 2,0 sınır dahil
    assert sec["karli_gun_3"] == [f"0x{i:02d}" for i in range(3, 13)]             # 3/7 sınır dahil
    assert len(sec["h_siz"]) == 11 and set(sec["h_siz"]) <= {s["adres"] for s in kadro["satirlar"]}


def test_kasa_getirisi_bos_koltuk_nakit():
    ileri = {"a": 0.11, "b": -0.022, "c": None}
    k, n, e = v.kasa_getirisi(["a", "b", "c"], ileri, 11)
    assert abs(k - 0.088 / 11) < 1e-12 and (n, e) == (2, 1)
    assert v.kasa_getirisi([], ileri, 11) == (0.0, 0, 0)
    assert v.kasa_getirisi(["c"], ileri, 11) == (None, 0, 1)


def test_ozet_ve_md():
    def gun(t, k1, k2):
        var = {x: {"secilen": ["a"], "kasa": k1} for x in v.VARYANTLAR}
        var["t_2"] = {"secilen": [], "kasa": k2}
        return {"tarih": t, "pencere_gun": 1.0, "varyant": var, "cikanlar": [{"grup": v.cikis_grubu("r0_disi"), "ileri": 0.01}, {"grup": v.cikis_grubu("r1:kopya_kotu"), "ileri": None}]}
    oz = v.ozet([gun("2026-11-05", 0.01, 0.0), gun("2026-11-06", -0.02, 0.0)])
    assert oz["varyant"]["t_2"]["iyi_gun"] == 1 and oz["varyant"]["t_2"]["kotu_gun"] == 1
    assert abs(oz["varyant"]["t_2"]["ort_fark_v1"] - 0.005) < 1e-12
    assert oz["varyant"]["v1"]["ort_fark_v1"] == 0.0
    assert list(oz["cikis"]) == ["r0_disi (v1.1'de kalırdı)"] and oz["cikis"]["r0_disi (v1.1'de kalırdı)"]["pozitif"] == 2
    md = v.ozet_md([gun("2026-11-05", 0.01, 0.0)], oz)
    assert "| 2026-11-05 |" in md and "t ≥ 2" in md


def test_cikis_grubu():
    assert v.cikis_grubu("r0_disi").startswith("r0_disi")
    assert v.cikis_grubu("r1:sans_riski").startswith("r1")
    assert v.cikis_grubu("soguyan") == "soguyan"
