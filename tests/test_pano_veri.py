"""Pano verisi (`copytrade/pano_veri.py`): elle hesaplanmış altın örnek, eksik alan -> null, boş takım, tazelik, biçim ve gizlilik."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from copytrade import pano_veri

REF = "2026-11-03T12:00:00Z"
SIMDI = datetime(2026, 11, 3, 12, 30, tzinfo=UTC)
A, B = "0x" + "a" * 40, "0x" + "b" * 40


def trader(adres, ad, hesap, pozisyonlar, v3):
    return {"adres": adres, "takma_ad": ad, "hesap_degeri": hesap, "pozisyonlar": pozisyonlar, "sanal_kopya_v3": v3}


def durum():
    """A (İlk 11): hesap 10.000 $ -> ölçek 0,1. B (Yedek 11): hesap 20.000 $ -> ölçek 0,05."""
    poz_a = [{"coin": "BTC", "yon": "long", "giris": 68000.0, "buyukluk_usd": 50000.0, "kaldirac": 5.0, "anlik_kz_usd": 2000.0, "acilis": "2026-11-03T02:00:00Z"},
             {"coin": "ETH", "yon": "short", "giris": 2600.0, "buyukluk_usd": 20000.0, "kaldirac": 4.0, "anlik_kz_usd": -500.0, "acilis": "2026-11-02T20:00:00Z"}]
    poz_b = [{"coin": "SOL", "yon": "long", "giris": 150.0, "buyukluk_usd": 40000.0, "kaldirac": 10.0, "anlik_kz_usd": 1000.0, "acilis": "2026-11-03T03:00:00Z"}]
    v3_a = {"surum": "v3", "baslangic_usd": 1000, "bakiye_usd": 1100.0, "toplam": 0.1, "egri": [["2026-11-01", 1000.0], ["2026-11-02", 1050.0], ["2026-11-03", 1100.0]],
            "kapanan_islemler": [{"coin": "BTC", "acilis": "2026-11-03T01:00:00Z", "kapanis": "2026-11-03T05:00:00Z", "sonuc_usd": 20.0, "getiri": 0.2, "neden": "trader", "gecerli": True}]}
    v3_b = {"surum": "v3", "baslangic_usd": 1000, "bakiye_usd": 990.0, "toplam": -0.01, "egri": [["2026-11-01", 1000.0], ["2026-11-02", 995.0], ["2026-11-03", 990.0]],
            "kapanan_islemler": [{"coin": "SOL", "acilis": "2026-11-02T08:00:00Z", "kapanis": "2026-11-02T10:00:00Z", "sonuc_usd": -5.0, "getiri": -0.05, "neden": "zarar_kes", "gecerli": True}]}
    return {"surum": 1, "uretildi": REF, "traderlar": [trader(A, "aaaa", 10000.0, poz_a, v3_a), trader(B, "bbbb", 20000.0, poz_b, v3_b)]}


LISTE = {"traderlar": [{"id": "X1", "adres": A, "takma_ad": "aaaa", "takim": "ilk11"}, {"id": "X2", "adres": B, "takma_ad": "bbbb", "takim": "yedek11"},
                       {"id": "O1", "adres": "0x" + "c" * 40, "takma_ad": "cccc", "kol": "referans_oda"}]}
SNAP = {"kadro": [{"id": A, "takim": "ilk11"}, {"id": "0x1", "takim": "ilk11"}, {"id": B, "takim": "yedek11"}, {"id": "0x2", "takim": "paf"}]}


def takim(veri, ad):
    return next(t for t in veri["takimlar"] if t["ad"] == ad)


def test_altin_ornek_iki_takim_uc_acik_iki_kapanmis():
    v = pano_veri.pano_uret(durum(), LISTE, SNAP, SIMDI)
    assert [t["ad"] for t in v["takimlar"]] == ["İlk 11", "Yedek 11", "PAF"] and v["dinleyici"] is None and v["uretildi"] == REF
    i, y = takim(v, "İlk 11"), takim(v, "Yedek 11")
    # İlk 11 / kasa: 1.000 -> 1.100 (+100 $, +%10)
    assert i["kasa"] == {"baslangic_usd": 1000.0, "bakiye_usd": 1100.0, "degisim_usd": 100.0, "degisim_oran": 0.1,
                         "egri": [["2026-11-01T00:00:00Z", 1000.0], ["2026-11-02T00:00:00Z", 1050.0], ["2026-11-03T00:00:00Z", 1100.0]]}
    # açık işlemler (ölçek 0,1): BTC büyüklük 5.000, teminat 1.000, K/Z 200 $ (+%20 teminata); ETH 2.000 / 500 / −50 $ (−%10)
    btc, eth = (next(a for a in i["acik"] if a["coin"] == c) for c in ("BTC", "ETH"))
    assert (btc["buyukluk_usd"], btc["teminat_usd"], btc["kz_usd"], btc["kz_oran"], btc["kaldirac"], btc["trader"]) == (5000.0, 1000.0, 200.0, 0.2, 5.0, "aaaa")
    assert (eth["buyukluk_usd"], eth["teminat_usd"], eth["kz_usd"], eth["kz_oran"]) == (2000.0, 500.0, -50.0, -0.1)
    assert btc["son"] is None and btc["likidasyona_uzaklik_oran"] is None                              # motorda yok -> null
    o = i["ozet"]
    assert (o["acik_islem"], o["acik_teminat_usd"], o["acik_kz_usd"]) == (2, 1500.0, 150.0)
    assert (o["bugun_acilan"], o["bugun_kapanan"], o["son24_islem"], o["son24_kazanma_orani"]) == (2, 1, 1, 1.0)       # BTC açık + BTC kapanan bugün açıldı
    assert (o["kadro_dolu"], o["kadro_toplam"], o["nakit_usd"], o["islem_basi_usd"]) == (1, 2, None, None)
    # kapanan: ana para = 20 / 0,2 = 100 $; neden trader -> trader_kapatti
    assert i["kapanan"] == [{"coin": "BTC", "yon": None, "kaldirac": None, "trader": "aaaa", "acilis": "2026-11-03T01:00:00Z", "kapanis": "2026-11-03T05:00:00Z",
                             "neden": "trader_kapatti", "ana_para_usd": 100.0, "kz_usd": 20.0, "kz_oran": 0.2}]
    m = i["metrik"]
    assert m["bugun_oran"] == pytest.approx(50 / 1050, abs=1e-6) and m["toplam_oran"] == 0.1 and m["hafta_oran"] is None and m["ay_oran"] is None
    assert m["maruziyet_oran"] == pytest.approx(1500 / 1100, abs=1e-6) and (m["kazanma_orani"], m["ort_kazanc_oran"], m["beklenti_oran"], m["islem_sayisi"]) == (1.0, 0.2, 0.2, 1)
    assert m["kar_faktoru"] is None and m["ort_kayip_oran"] is None                                      # kayıp yok -> tanımsız
    assert i["seriler"]["bakiye"][-1] == ["2026-11-03", 1100.0] and i["seriler"]["kumulatif_kz"][-1] == ["2026-11-03", 100.0]
    assert i["seriler"]["gunluk_kz"] == [["2026-11-02", 0.05], ["2026-11-03", 0.047619]] and i["seriler"]["dusus"][-1] == ["2026-11-03", 0.0]
    assert i["traderlar"] == [{"ad": "aaaa", "islem": 1, "kazanma_orani": 1.0, "net_oran": 0.1, "son_islem": "2026-11-03T05:00:00Z"}]
    # Yedek 11 (ölçek 0,05): SOL büyüklük 2.000, teminat 200, K/Z 50 $ (+%25); kasa 1.000 -> 990 (−10 $, −%1)
    s = y["acik"][0]
    assert (s["buyukluk_usd"], s["teminat_usd"], s["kz_usd"], s["kz_oran"]) == (2000.0, 200.0, 50.0, 0.25)
    assert (y["kasa"]["bakiye_usd"], y["kasa"]["degisim_usd"], y["kasa"]["degisim_oran"]) == (990.0, -10.0, -0.01)
    assert (y["ozet"]["bugun_acilan"], y["ozet"]["bugun_kapanan"], y["ozet"]["son24_islem"], y["ozet"]["son24_kazanma_orani"]) == (1, 0, 0, None)
    assert (y["metrik"]["kazanma_orani"], y["metrik"]["kar_faktoru"], y["metrik"]["ort_kayip_oran"]) == (0.0, 0.0, -0.05)
    assert y["kapanan"][0]["neden"] == "stop" and y["kapanan"][0]["ana_para_usd"] == 100.0
    # toplam: 3 açık, 2 kapanmış
    assert sum(len(t["acik"]) for t in v["takimlar"]) == 3 and sum(len(t["kapanan"]) for t in v["takimlar"]) == 2


def test_eksik_alan_null_uydurulmaz():
    d = durum()
    p = d["traderlar"][0]["pozisyonlar"][0]
    del p["anlik_kz_usd"], p["kaldirac"]
    del d["traderlar"][1]["sanal_kopya_v3"]["toplam"]
    d["traderlar"][1]["sanal_kopya_v3"]["kapanan_islemler"][0]["getiri"] = None
    v = pano_veri.pano_uret(d, LISTE, SNAP, SIMDI)
    btc = next(a for a in takim(v, "İlk 11")["acik"] if a["coin"] == "BTC")
    assert (btc["kz_usd"], btc["kz_oran"], btc["teminat_usd"], btc["kaldirac"]) == (None, None, None, None) and btc["buyukluk_usd"] == 5000.0
    o = takim(v, "İlk 11")["ozet"]
    assert o["acik_teminat_usd"] is None and o["acik_kz_usd"] is None and o["acik_islem"] == 2          # biri eksikse toplam null; sayı sıfır değil
    assert takim(v, "İlk 11")["metrik"]["maruziyet_oran"] is None
    y = takim(v, "Yedek 11")
    assert y["traderlar"][0]["net_oran"] is None and y["kapanan"][0]["ana_para_usd"] is None and y["kapanan"][0]["kz_oran"] is None and y["kapanan"][0]["kz_usd"] == -5.0
    # v3 hiç yoksa takım verisi null (0 değil)
    d2 = durum()
    d2["traderlar"][0]["sanal_kopya_v3"] = {"surum": "v3", "durum": "hesaplanamadi"}
    t = takim(pano_veri.pano_uret(d2, LISTE, SNAP, SIMDI), "İlk 11")
    assert t["kasa"]["bakiye_usd"] is None and t["ozet"]["acik_islem"] is None and t["acik"] == [] and t["ozet"]["kadro_dolu"] == 0


def test_baslamamis_uye_t0_gelecekte_toplamlara_girmez():
    d = durum()
    d["traderlar"][0]["t0"] = "2026-11-08"                       # A'nın kopyası henüz başlamadı: pozisyonları kopya işlemi değil
    d["traderlar"][1]["t0"] = "2026-11-03"                       # B bugün başladı
    v = pano_veri.pano_uret(d, LISTE, SNAP, SIMDI)
    i, y = takim(v, "İlk 11"), takim(v, "Yedek 11")
    assert i["acik"] == [] and i["kasa"]["bakiye_usd"] is None and i["ozet"]["acik_islem"] is None and i["ozet"]["kadro_dolu"] == 1     # kadroda var, toplamlarda yok
    assert len(y["acik"]) == 1 and y["kasa"]["baslangic_usd"] == 1000.0


def test_acilis_bos_metin_null_olur():
    d = durum()
    d["traderlar"][0]["pozisyonlar"][0]["acilis"] = ""
    assert next(a for a in takim(pano_veri.pano_uret(d, LISTE, SNAP, SIMDI), "İlk 11")["acik"] if a["coin"] == "BTC")["acilis"] is None


def test_bos_takim():
    v = pano_veri.pano_uret(durum(), LISTE, SNAP, SIMDI)
    paf = takim(v, "PAF")
    assert paf["kasa"] == {"baslangic_usd": None, "bakiye_usd": None, "degisim_usd": None, "degisim_oran": None, "egri": []}
    assert paf["acik"] == [] and paf["kapanan"] == [] and paf["traderlar"] == [] and all(x == [] for x in paf["seriler"].values())
    assert (paf["ozet"]["kadro_dolu"], paf["ozet"]["kadro_toplam"], paf["ozet"]["acik_islem"]) == (0, 1, None)
    assert all(x is None for x in paf["metrik"].values())
    v0 = pano_veri.pano_uret({"traderlar": []}, {}, None, SIMDI)             # girdi tamamen boş: çökmez
    assert [t["ad"] for t in v0["takimlar"]] == ["İlk 11", "Yedek 11", "PAF"] and v0["uretildi"] is None and v0["tazelik"]["bayat"] is True


def test_tazelik_iki_saatten_eskiyse_bayat():
    taze = pano_veri.pano_uret(durum(), LISTE, SNAP, datetime(2026, 11, 3, 13, 59, tzinfo=UTC))["tazelik"]
    sinir = pano_veri.pano_uret(durum(), LISTE, SNAP, datetime(2026, 11, 3, 14, 0, tzinfo=UTC))["tazelik"]
    eski = pano_veri.pano_uret(durum(), LISTE, SNAP, datetime(2026, 11, 3, 14, 1, tzinfo=UTC))["tazelik"]
    assert (taze["bayat"], taze["yas_dk"]) == (False, 119.0) and sinir["bayat"] is False and (eski["bayat"], eski["yas_dk"]) == (True, 121.0)
    assert eski["kaynak_uretildi"] == REF and eski["pano_uretildi"] == "2026-11-03T14:01:00Z" and eski["esik_dk"] == 120


def test_bicim_ornek_veri_ile_ayni_ek_alanlar_haric_ve_gizlilik():
    ornek = json.loads((Path(__file__).parent.parent / "pano" / "ornek_veri.json").read_text(encoding="utf-8"))
    v = pano_veri.pano_uret(durum(), LISTE, SNAP, SIMDI)
    assert set(v) - set(ornek) == {"tazelik", "olcek"} and set(ornek) <= set(v)
    for ad in ("İlk 11", "Yedek 11"):
        t, o = takim(v, ad), ornek["takimlar"][0]
        assert set(t) == set(o) and all(set(t[k]) == set(o[k]) for k in ("kasa", "ozet", "metrik", "seriler"))
        assert t["acik"] == [] or set(t["acik"][0]) == set(o["acik"][0])
        assert t["kapanan"] == [] or set(t["kapanan"][0]) == set(o["kapanan"][0])
        assert t["traderlar"] == [] or set(t["traderlar"][0]) == set(o["traderlar"][0])
    metin = json.dumps(v, ensure_ascii=False)
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", metin) and "http" not in metin and "token" not in metin.lower()       # IP / URL / anahtar yok
    assert json.loads(metin) == v                                                                         # NaN / sonsuz yok: katı JSON


def test_main_dosyadan_uretir(tmp_path):
    (tmp_path / "ilk11" / "2026-11-02").mkdir(parents=True)
    (tmp_path / "ilk11" / "2026-11-08").mkdir()
    (tmp_path / "ilk11" / "2026-11-02" / "snapshot.json").write_text(json.dumps({"kadro": []}))
    (tmp_path / "ilk11" / "2026-11-08" / "snapshot.json").write_text(json.dumps(SNAP))
    (tmp_path / "durum.json").write_text(json.dumps(durum()))
    import yaml
    (tmp_path / "liste.yaml").write_text(yaml.safe_dump(LISTE))
    pano_veri.main(["--durum", str(tmp_path / "durum.json"), "--liste", str(tmp_path / "liste.yaml"), "--ilk11", str(tmp_path / "ilk11"), "--cikti", str(tmp_path / "pano.json")])
    cikti = json.loads((tmp_path / "pano.json").read_text(encoding="utf-8"))
    assert takim(cikti, "İlk 11")["ozet"]["kadro_toplam"] == 2                                            # en son tarihli snapshot
