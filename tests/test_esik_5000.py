"""Eşik kararı (kullanıcı, 2026-10-29): evren_min_hesap_degeri ve hesap_degeri_min_usd = 5000; yalnız yeni adresler eksik modda taranır;
kapsam ölçüsü evren adres kümesine göre (denetim B14)."""
import json
import re
from pathlib import Path

import pandas as pd

from copytrade.kapi import account_floor_pass, load_rules, merge_shards, missing_addresses

ROOT = Path(__file__).resolve().parents[1]
RULES = load_rules()


def test_hesap_degeri_esikleri_5000():
    assert RULES["evren_min_hesap_degeri"] == 5000 and RULES["hesap_degeri_min_usd"] == 5000
    assert not account_floor_pass(0.0, RULES) and not account_floor_pass(4999.0, RULES) and account_floor_pass(5000.0, RULES)    # eşik dahil


def test_kapi_v3_belgesinde_surum_3_2_notu():
    text = (ROOT / "docs/KAPI_V3.md").read_text(encoding="utf-8")
    assert "## Sürüm 3.2" in text and "13.660" in text and "15.005" in text and "5.000" in text


def test_eksik_modu_hesap_degeri_tabanindan_kalan_ama_yeni_esigi_gecenleri_de_alir():
    leaders = [{"address": a} for a in ("0xa", "0xb", "0xc", "0xd", "0xe")]
    reference = pd.DataFrame({"address": ["0xa", "0xb", "0xc", "0xd"],
                              "neden": [None, "hesap değeri tabanı", "hesap değeri tabanı", "veri hatası: HTTPError: 500"],
                              "hesap_degeri_bugun": [50_000.0, 7_500.0, 3_000.0, None]})
    # 0xb: eski eşikte (10.000) kaldı, yeni eşikte (5.000) geçer → yeniden değerlendirilir; 0xc hâlâ altında → korunur; 0xd veri hatası; 0xe yeni
    assert [x["address"] for x in missing_addresses(leaders, reference, RULES)] == ["0xb", "0xd", "0xe"]


def shard(base: Path, index: int, addresses: list[str], universe: int):
    folder = base / f"stage1-{index}" / "2026-10-28"
    folder.mkdir(parents=True)
    pd.DataFrame([{"address": a, "asama1": "Yetersiz"} for a in addresses]).to_csv(folder / "sonuc.csv", index=False)
    (folder / "evren.json").write_text(json.dumps({"evren": universe}))
    (folder / "bitti.json").write_text("{}")


def test_kapsam_evren_adres_kumesine_gore_ve_evren_disi_satir_isaretlenir(tmp_path):
    """Altın örnek: evren {a, b, c, d}; sonuç {a, b, x} → kesişim 2 / 4 = 0,5 (eski ölçü 3 / 4 = 0,75); x evren dışı."""
    shard(tmp_path / "shards", 0, ["0xa", "0xb", "0xx"], 4)
    status = merge_shards(tmp_path / "shards", tmp_path / "root", 1, "tam", {"0xa", "0xb", "0xc", "0xd"})["2026-10-28"]
    assert status["kapsam"] == 0.5 and status["kapsanan"] == 2 and status["islenen"] == 3 and status["evren_disi_satir"] == 1
    assert status["durum"] == "eksik" and "kapsam %50.0" in status["neden"]
    table = pd.read_csv(tmp_path / "root/kapi/2026-10-28/sonuc.csv")
    assert dict(zip(table.address, table.evren_disi)) == {"0xa": False, "0xb": False, "0xx": True}


def test_kapsam_bir_gecmez_evren_disi_satirlar_sayilmaz(tmp_path):
    shard(tmp_path / "shards", 0, ["0xa", "0xb", "0xx", "0xy"], 2)
    status = merge_shards(tmp_path / "shards", tmp_path / "root", 1, "tam", {"0xa", "0xb"})["2026-10-28"]
    assert status["kapsam"] == 1.0 and status["durum"] == "tamam" and status["evren_disi_satir"] == 2          # eski ölçü 4 / 2 = 2,0 idi


def test_evren_adresleri_verilmezse_eski_olcu_korunur(tmp_path):
    shard(tmp_path / "shards", 0, ["0xa", "0xb"], 2)
    assert merge_shards(tmp_path / "shards", tmp_path / "root", 1, "tam")["2026-10-28"]["kapsam"] == 1.0


def test_latest_day_ve_tarih_bayragi():
    from copytrade.kapi import latest_day
    assert latest_day(["copytrade/kapi/2026-10-27", "copytrade/kapi/2026-10-28", "copytrade/kapi/CALISTIR"]) == "2026-10-28"
    assert latest_day(["2026-10-28/", "2026-10-09"]) == "2026-10-28" and latest_day([]) is None and latest_day(["x"]) is None
