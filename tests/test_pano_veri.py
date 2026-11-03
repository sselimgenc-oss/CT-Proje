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
    return {"adres": adres, "takma_ad": ad, "hesap_degeri": hesap, "pozisyonlar": pozisyonlar, "sanal_kopya_v4": v3}


def durum():
    """v4 (1.000 $ sanal kopya, risk sınırlı). A (İlk 11): BTC long 150 $ (teminat 15 = 150/10x), ETH short 60 $ (12 = 60/5x). B (Yedek 11): SOL long 80 $ (8 = 80/10x)."""
    acik_a = [{"coin": "BTC", "yon": "long", "buyukluk_usd": 150.0, "teminat_usd": 15.0, "giris": 68000.0, "son": 69000.0, "kz_usd": 3.0, "kz_oran": 0.2, "acilis": "2026-11-03T02:00:00Z"},
              {"coin": "ETH", "yon": "short", "buyukluk_usd": 60.0, "teminat_usd": 12.0, "giris": 2600.0, "son": 2574.0, "kz_usd": 0.6, "kz_oran": 0.05, "acilis": "2026-11-02T20:00:00Z"}]
    acik_b = [{"coin": "SOL", "yon": "long", "buyukluk_usd": 80.0, "teminat_usd": 8.0, "giris": 150.0, "son": 151.5, "kz_usd": 0.8, "kz_oran": 0.1, "acilis": "2026-11-03T03:00:00Z"}]
    v4_a = {"surum": "v4", "baslangic_usd": 1000, "bakiye_usd": 1100.0, "getiri": 0.1, "toplam": 0.1, "acik_pozisyonlar": acik_a,
            "egri": [["2026-11-01", 1000.0], ["2026-11-02", 1050.0], ["2026-11-03", 1100.0]],
            "kapanan_islemler": [{"coin": "BTC", "acilis": "2026-11-03T01:00:00Z", "kapanis": "2026-11-03T05:00:00Z", "sonuc_usd": 20.0, "getiri": 0.2, "neden": "trader", "gecerli": True}]}
    v4_b = {"surum": "v4", "baslangic_usd": 1000, "bakiye_usd": 990.0, "getiri": -0.01, "toplam": -0.01, "acik_pozisyonlar": acik_b,
            "egri": [["2026-11-01", 1000.0], ["2026-11-02", 995.0], ["2026-11-03", 990.0]],
            "kapanan_islemler": [{"coin": "SOL", "acilis": "2026-11-02T08:00:00Z", "kapanis": "2026-11-02T10:00:00Z", "sonuc_usd": -5.0, "getiri": -0.05, "neden": "zarar_kes", "gecerli": True}]}
    return {"surum": 1, "uretildi": REF, "traderlar": [trader(A, "aaaa", 10000.0, [], v4_a), trader(B, "bbbb", 20000.0, [], v4_b)]}


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
                         "egri": [["2026-11-01T00:00:00Z", 1000.0], ["2026-11-02T00:00:00Z", 1050.0], ["2026-11-03T00:00:00Z", 1100.0]],
                         "olcek_notu": "1 × 1.000 $ sanal (trader başına)"}
    # açık KOPYA pozisyonları (v4): büyüklük 150 / teminat 15 → kaldıraç 10x; K/Z 3,0 $ (+%20 teminata)
    btc, eth = (next(a for a in i["acik"] if a["coin"] == c) for c in ("BTC", "ETH"))
    assert (btc["buyukluk_usd"], btc["teminat_usd"], btc["kz_usd"], btc["kz_oran"], btc["kaldirac"], btc["trader"]) == (150.0, 15.0, 3.0, 0.2, 10.0, "aaaa")
    assert (btc["yon"], btc["giris"], btc["son"], btc["acilis"]) == ("long", 68000.0, 69000.0, "2026-11-03T02:00:00Z")
    assert (eth["buyukluk_usd"], eth["teminat_usd"], eth["kz_usd"], eth["kz_oran"], eth["kaldirac"], eth["yon"]) == (60.0, 12.0, 0.6, 0.05, 5.0, "short")
    assert btc["likidasyona_uzaklik_oran"] is None                                                       # motorda yok -> null
    o = i["ozet"]
    assert (o["acik_islem"], o["acik_teminat_usd"], o["acik_kz_usd"], o["nakit_usd"]) == (2, 27.0, 3.6, 1073.0)       # nakit = bakiye 1.100 − teminat 27
    assert (o["bugun_acilan"], o["bugun_kapanan"], o["son24_islem"], o["son24_kazanma_orani"]) == (2, 1, 1, 1.0)       # BTC açık + BTC kapanan bugün açıldı
    assert (o["kadro_dolu"], o["kadro_toplam"], o["islem_basi_usd"]) == (1, 2, None)
    assert i["kasa"]["olcek_notu"] == "1 × 1.000 $ sanal (trader başına)" and "v4" in v["olcek"]["acik_islemler"]
    # kapanan: ana para = 20 / 0,2 = 100 $; neden trader -> trader_kapatti
    assert i["kapanan"] == [{"coin": "BTC", "yon": None, "kaldirac": None, "trader": "aaaa", "acilis": "2026-11-03T01:00:00Z", "kapanis": "2026-11-03T05:00:00Z",
                             "neden": "trader_kapatti", "ana_para_usd": 100.0, "kz_usd": 20.0, "kz_oran": 0.2}]
    m = i["metrik"]
    assert m["bugun_oran"] == pytest.approx(50 / 1050, abs=1e-6) and m["toplam_oran"] == 0.1 and m["hafta_oran"] is None and m["ay_oran"] is None
    assert m["maruziyet_oran"] == pytest.approx(27 / 1100, abs=1e-6) and (m["kazanma_orani"], m["ort_kazanc_oran"], m["beklenti_oran"], m["islem_sayisi"]) == (1.0, 0.2, 0.2, 1)
    assert m["kar_faktoru"] is None and m["ort_kayip_oran"] is None                                      # kayıp yok -> tanımsız
    assert i["seriler"]["bakiye"][-1] == ["2026-11-03", 1100.0] and i["seriler"]["kumulatif_kz"][-1] == ["2026-11-03", 100.0]
    assert i["seriler"]["gunluk_kz"] == [["2026-11-02", 0.05], ["2026-11-03", 0.047619]] and i["seriler"]["dusus"][-1] == ["2026-11-03", 0.0]
    assert i["traderlar"] == [{"ad": "aaaa", "islem": 1, "kazanma_orani": 1.0, "net_oran": 0.1, "son_islem": "2026-11-03T05:00:00Z"}]
    # Yedek 11: SOL açık (80 $ / teminat 8 → 10x; K/Z 0,8 $, +%10); kasa 1.000 -> 990 (−10 $, −%1); nakit 990 − 8 = 982
    assert (y["acik"][0]["coin"], y["acik"][0]["kaldirac"], y["acik"][0]["kz_usd"], y["acik"][0]["kz_oran"]) == ("SOL", 10.0, 0.8, 0.1) and y["ozet"]["nakit_usd"] == 982.0
    assert (y["kasa"]["bakiye_usd"], y["kasa"]["degisim_usd"], y["kasa"]["degisim_oran"]) == (990.0, -10.0, -0.01)
    assert (y["ozet"]["bugun_acilan"], y["ozet"]["bugun_kapanan"], y["ozet"]["son24_islem"], y["ozet"]["son24_kazanma_orani"]) == (1, 0, 0, None)
    assert (y["metrik"]["kazanma_orani"], y["metrik"]["kar_faktoru"], y["metrik"]["ort_kayip_oran"]) == (0.0, 0.0, -0.05)
    assert y["kapanan"][0]["neden"] == "stop" and y["kapanan"][0]["ana_para_usd"] == 100.0
    # toplam: 3 açık, 2 kapanmış
    assert sum(len(t["acik"]) for t in v["takimlar"]) == 3 and sum(len(t["kapanan"]) for t in v["takimlar"]) == 2


def test_eksik_alan_null_uydurulmaz():
    d = durum()
    del d["traderlar"][0]["sanal_kopya_v4"]["acik_pozisyonlar"][0]["teminat_usd"]               # BTC teminatı (HL azami kaldıracı bilinmiyor) yok
    del d["traderlar"][1]["sanal_kopya_v4"]["getiri"]
    d["traderlar"][1]["sanal_kopya_v4"]["kapanan_islemler"][0]["getiri"] = None
    v = pano_veri.pano_uret(d, LISTE, SNAP, SIMDI)
    btc = next(a for a in takim(v, "İlk 11")["acik"] if a["coin"] == "BTC")
    assert btc["teminat_usd"] is None and btc["kaldirac"] is None and btc["buyukluk_usd"] == 150.0
    o = takim(v, "İlk 11")["ozet"]
    assert o["acik_teminat_usd"] is None and o["nakit_usd"] is None and o["acik_islem"] == 2 and o["acik_kz_usd"] == 3.6      # biri eksikse toplam null; K/Z toplamı dolu
    assert takim(v, "İlk 11")["metrik"]["maruziyet_oran"] is None
    y = takim(v, "Yedek 11")
    assert y["traderlar"][0]["net_oran"] is None and y["kapanan"][0]["ana_para_usd"] is None and y["kapanan"][0]["kz_oran"] is None and y["kapanan"][0]["kz_usd"] == -5.0
    # v3 hiç yoksa takım verisi null (0 değil)
    d2 = durum()
    d2["traderlar"][0]["sanal_kopya_v4"] = {"surum": "v4", "durum": "hesaplanamadi"}
    t = takim(pano_veri.pano_uret(d2, LISTE, SNAP, SIMDI), "İlk 11")
    assert t["kasa"]["bakiye_usd"] is None and t["kasa"]["olcek_notu"] is None and t["ozet"]["acik_islem"] is None and t["acik"] == [] and t["ozet"]["kadro_dolu"] == 0


def test_baslamamis_uye_t0_gelecekte_toplamlara_girmez():
    d = durum()
    d["traderlar"][0]["t0"] = "2026-11-08"                       # A'nın kopyası henüz başlamadı
    d["traderlar"][1]["t0"] = "2026-11-03"                       # B bugün başladı
    v = pano_veri.pano_uret(d, LISTE, SNAP, SIMDI)
    i, y = takim(v, "İlk 11"), takim(v, "Yedek 11")
    assert i["acik"] == [] and i["kasa"]["bakiye_usd"] is None and i["ozet"]["acik_islem"] is None and i["ozet"]["kadro_dolu"] == 1     # kadroda var, toplamlarda yok
    assert len(y["acik"]) == 1 and y["kasa"]["baslangic_usd"] == 1000.0


def test_acilis_bos_metin_null_olur():
    d = durum()
    d["traderlar"][0]["sanal_kopya_v4"]["acik_pozisyonlar"][0]["acilis"] = ""
    assert next(a for a in takim(pano_veri.pano_uret(d, LISTE, SNAP, SIMDI), "İlk 11")["acik"] if a["coin"] == "BTC")["acilis"] is None


def test_net_oran_getiri_kullanir_tasfiyede_toplam_degil():
    """Tasfiye olan kopyada `toplam` (gerçekleşen+açık) −0,888 olabilir ama bakiye 0'dır (`getiri` −1,0): pano bakiye ile tutarlı `getiri`'yi gösterir."""
    d = durum()
    d["traderlar"][0]["sanal_kopya_v4"].update({"bakiye_usd": 0.0, "getiri": -1.0, "toplam": -0.888, "tasfiye": True})
    assert takim(pano_veri.pano_uret(d, LISTE, SNAP, SIMDI), "İlk 11")["traderlar"][0]["net_oran"] == -1.0


def test_bos_takim():
    v = pano_veri.pano_uret(durum(), LISTE, SNAP, SIMDI)
    paf = takim(v, "PAF")
    assert paf["kasa"] == {"baslangic_usd": None, "bakiye_usd": None, "degisim_usd": None, "degisim_oran": None, "egri": [], "olcek_notu": None}
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
        assert set(t) == set(o) and all(set(t[k]) == set(o[k]) for k in ("ozet", "metrik", "seriler")) and set(t["kasa"]) - set(o["kasa"]) == {"olcek_notu"}
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
