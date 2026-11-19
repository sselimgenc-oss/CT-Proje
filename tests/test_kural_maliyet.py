"""Kural maliyeti (`ct.kural_maliyet.v1`): neden başına toplama (saf, altın örnek), dosya çıktısı, yayım betikleri. Yalnız bilgi; ağsız."""
from __future__ import annotations

import json
from pathlib import Path

from copytrade.canli import kural_maliyet as km
from tests.test_canli_motor import kur

ROOT = Path(__file__).resolve().parent.parent
GUN = 86_400_000
NOW = 1_800_000_000_000


def _y(neden, adres, ms=NOW - 1000):
    return {"olay": "emir_yok", "neden": neden, "adres": adres, "zaman_ms": ms}


def _kap(neden, pnl, usd, ms=NOW - 1000):
    return {"olay": "karsi_olgu_kapandi", "neden": neden, "pnl_usd": pnl, "hayali_usd": usd, "zaman_ms": ms}


KAYIT = [_y("slot_tavani", "0xa"), _y("slot_tavani", "0xa"), _y("slot_tavani", "0xb"), _y("bant_ici", "0xa"),
         _y("slot_tavani", "0xc", ms=NOW - 8 * GUN),                          # pencere dışı
         _kap("slot_tavani", 2.5, 100.0), _kap("slot_tavani", -1.0, 50.0), _kap("hip3_atlandi", -4.0, 200.0),
         _kap("slot_tavani", 99.0, 99.0, ms=NOW - 8 * GUN),                   # pencere dışı
         {"olay": "ml_filtre_atla", "adres": "0xa", "zaman_ms": NOW - 5}, {"olay": "ml_filtre_atla", "adres": "0xd", "zaman_ms": NOW - 5},
         _y("ml_filtre_atla", "0xa"), _y("ml_filtre_atla", "0xd")]
ACIK = {"0xa|BTC": {"neden": "slot_tavani", "hayali_usd": 30.0, "son_pnl": 0.75}, "0xb|ETH": {"neden": "hip3_atlandi", "hayali_usd": 10.0, "son_pnl": -1.0},
        "0xc|SOL": {"neden": "slot_tavani", "hayali_usd": 20.0, "son_pnl": -0.25}}


def test_topla_altin_ornek():
    s = {r["neden"]: r for r in km.topla(KAYIT, ACIK, NOW)}
    assert s["slot_tavani"] == {"neden": "slot_tavani", "olay_adedi": 3, "trader_sayisi": 2, "karsi_olgu_kapanan_n": 2, "karsi_olgu_kapanan_pnl": 1.5,
                                "karsi_olgu_acik_n": 2, "karsi_olgu_acik_pnl": 0.5, "toplam_karsi_olgu_pnl": 2.0, "hayali_nosyonel": 200.0}
    assert s["hip3_atlandi"]["olay_adedi"] == 0 and s["hip3_atlandi"]["toplam_karsi_olgu_pnl"] == -5.0 and s["hip3_atlandi"]["hayali_nosyonel"] == 210.0
    assert s["ml_filtre_atla"]["olay_adedi"] == 2 and s["ml_filtre_atla"]["trader_sayisi"] == 2      # çift sayılmaz
    assert s["bant_ici"]["karsi_olgu_kapanan_n"] == 0
    assert [r["neden"] for r in km.topla(KAYIT, ACIK, NOW)][0] == "slot_tavani"                       # olay azalan
    assert km.topla([], None, NOW) == []


def test_olustur_sema_vurgu_ve_adres_yok():
    v = km.olustur(KAYIT, ACIK, NOW)
    assert v["sema"] == "ct.kural_maliyet.v1" and v["proje"] == "CT" and v["pencere_gun"] == 7
    assert v["vurgu"]["slot_tavani"]["olay_adedi"] == 3
    assert any("TEK" in n for n in v["notlar"])
    assert "0xa" not in json.dumps(v)
    assert km.olustur([], None, NOW)["vurgu"] == {"slot_tavani": None}


def test_markdown_baslik_ve_vurgu():
    md = km.markdown(km.olustur(KAYIT, ACIK, NOW))
    assert "**Slot tavanı:** 3 olay, 2 trader" in md
    assert "| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |" in md
    assert "kayıt yok" in km.markdown(km.olustur([], None, NOW))


def test_durum_yaz_dosyalari_yazar(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.durum_yaz()
    d = tmp_path / "durum" / "paylasim"
    v = json.loads((d / "kural_maliyet_v1.json").read_text(encoding="utf-8"))
    assert v["sema"] == "ct.kural_maliyet.v1" and "vurgu" in v
    assert (d / "kural_maliyet_v1.md").read_text(encoding="utf-8").startswith("# CT")


def test_yayim_betikleri_dosyalari_kopyalar():
    for yol in (".github/scripts/canli_yayimla.sh", "deploy/sanal_yayimla.sh"):
        s = (ROOT / yol).read_text(encoding="utf-8")
        assert "kural_maliyet_v1.json" in s and "kural_maliyet_v1.md" in s
