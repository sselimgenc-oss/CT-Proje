"""Rejim ve duygu x işlem sonucu (`ct.rejim_sonuc.v1`): giriş damgası (açılışta, kalıcı), toplama (saf), dosya çıktısı, yayım betikleri. Yalnız bilgi; ağsız."""
from __future__ import annotations

import json
from pathlib import Path

from copytrade.canli import rejim_sonuc as rs
from copytrade.canli.hesap import Hesap
from tests.test_canli_motor import adr, kayitlar, kur, olay

ROOT = Path(__file__).resolve().parent.parent
GUN = 86_400_000
NOW = 1_800_000_000_000


def _k(pnl, ctx, ms=NOW - 1000, eylem="kapat", durum="dolu"):
    return {"olay": "emir", "eylem": eylem, "durum": durum, "pnl_usd": pnl, "zaman_ms": ms, "giris_ctx": ctx}


def test_giris_ctx_bos_beslemede_none_ve_dolu_beslemede_alanlar():
    assert rs.giris_ctx({}, {}, "BTC", NOW) is None
    assert rs.giris_ctx(None, None, "BTC", NOW) is None
    ra = {"gecerli_son_ms": NOW + 1000, "rejimler": {"ADA": {"1d": "trend_down", "4h": "range"}}}
    ha = {"duygu": {"deger": 12, "sinif": "Extreme Fear", "ms": NOW}}
    assert rs.giris_ctx(ra, ha, "ADA", NOW) == {"r1d": "trend_down", "r4h": "range", "duygu": "Extreme Fear", "duygu_deger": 12}
    assert rs.giris_ctx(ra, {}, "BTC", NOW) is None                   # coin yok, duygu yok


def test_topla_kovalar_pencere_ve_bilinmiyor():
    ctx_a = {"r1d": "trend_up", "r4h": "range", "duygu": "Fear"}
    ks = [_k(10.0, ctx_a), _k(-4.0, ctx_a), _k(6.0, None), _k(1.0, {"r1d": None, "r4h": "range"}),
          _k(99.0, ctx_a, ms=NOW - 8 * GUN),                            # pencere dışı
          _k(5.0, ctx_a, eylem="azalt"), _k(5.0, ctx_a, durum="red"), _k(None, ctx_a)]
    t = rs.topla(ks, NOW)
    assert t["rejim_1d"] == [{"etiket": "trend_up", "n": 2, "kazanan": 1, "isabet_yuzde": 50.0, "toplam_pnl": 6.0, "ortalama_pnl": 3.0},
                             {"etiket": "bilinmiyor", "n": 2, "kazanan": 2, "isabet_yuzde": 100.0, "toplam_pnl": 7.0, "ortalama_pnl": 3.5}]
    assert [(r["etiket"], r["n"]) for r in t["rejim_4h"]] == [("range", 3), ("bilinmiyor", 1)]
    assert [(r["etiket"], r["n"]) for r in t["duygu"]] == [("Fear", 2), ("bilinmiyor", 2)]
    assert rs.topla([], NOW) == {"rejim_1d": [], "rejim_4h": [], "duygu": []}


def test_olustur_ve_markdown():
    v = rs.olustur([_k(2.0, None)], NOW)
    assert v["sema"] == "ct.rejim_sonuc.v1" and v["proje"] == "CT" and v["pencere_gun"] == 7 and v["uretim"].endswith("Z")
    assert set(v["tablolar"]) == {"rejim_1d", "rejim_4h", "duygu"} and any("bilinmiyor" in n for n in v["notlar"])
    md = rs.markdown(v)
    assert "| Rejim (1g) | İşlem | Kazanan | İsabet % | Toplam PnL $ | Ort. PnL $ |" in md and "| Duygu |" in md and "| bilinmiyor | 1 | 1 | 100.0 | 2.00 | 2.00 |" in md
    assert "|" in rs.markdown(rs.olustur([], NOW))


def test_poz_giris_ctx_kalici():
    h = Hesap(1000.0)
    h.slot_ac("a", 100.0)
    h.uygula("a", "BTC", "B", 1.0, 100.0, 0.0, NOW)
    h.poz["a"]["BTC"].giris_ctx = {"r1d": "range"}
    assert Hesap.from_json(json.loads(json.dumps(h.to_json()))).poz["a"]["BTC"].giris_ctx == {"r1d": "range"}
    eski = h.to_json()
    del eski["poz"]["a"]["BTC"]["giris_ctx"]                           # eski durum dosyası (alan yok) yüklenir
    assert Hesap.from_json(eski).poz["a"]["BTC"].giris_ctx is None


def test_motor_acilista_damgalar_kapanista_tasir(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.rejim_anlik = {"gecerli_son_ms": saat() + 10 * GUN, "rejimler": {"BTC": {"1d": "range", "4h": "trend_down"}}}
    m.haber_anlik = {"duygu": {"deger": 20, "sinif": "Extreme Fear", "ms": saat()}}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    beklenen = {"r1d": "range", "r4h": "trend_down", "duygu": "Extreme Fear", "duygu_deger": 20}
    assert kayitlar(tmp_path, "emir")[0]["giris_ctx"] == beklenen
    m.rejim_anlik = {}                                                # kapanışta besleme boşalsa da GİRİŞ damgası taşınır
    m.haber_anlik = {}
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 101.0, 300, saat))
    kapanis = [k for k in kayitlar(tmp_path, "emir") if k["eylem"] == "kapat"]
    assert kapanis and kapanis[0]["giris_ctx"] == beklenen and kapanis[0]["pnl_usd"] is not None
    t = rs.topla(kayitlar(tmp_path, "emir"), int(saat()) + 1000)
    assert t["rejim_1d"][0]["etiket"] == "range" and t["duygu"][0]["etiket"] == "Extreme Fear"


def test_motor_bos_beslemede_none(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert kayitlar(tmp_path, "emir")[0]["giris_ctx"] is None


def test_durum_yaz_dosyalari_yazar(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.durum_yaz()
    d = tmp_path / "durum" / "paylasim"
    v = json.loads((d / "rejim_sonuc_v1.json").read_text(encoding="utf-8"))
    assert v["sema"] == "ct.rejim_sonuc.v1" and (d / "rejim_sonuc_v1.md").read_text(encoding="utf-8").startswith("# CT")


def test_yayim_betikleri_dosyalari_kopyalar():
    for yol in (".github/scripts/canli_yayimla.sh", "deploy/sanal_yayimla.sh"):
        s = (ROOT / yol).read_text(encoding="utf-8")
        assert "rejim_sonuc_v1.json" in s and "rejim_sonuc_v1.md" in s
