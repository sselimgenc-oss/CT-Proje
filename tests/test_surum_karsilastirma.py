"""Sürüm karşılaştırma: günlük seri toplulaştırma (elle hesaplanmış altın örnek) + pano bölümü. Ağsız."""
from copytrade import surum_karsilastirma as SK
from copytrade.canli import pano

GUN = 24 * 3_600_000
T0 = 1_800_000_000_000                                   # 2027-01-15 08:00 UTC
G0 = SK._gun(T0)
G1 = SK._gun(T0 + GUN)


def emir(ms, pnl, ucret=0.0, **k):
    return {"olay": "emir", "zaman_ms": ms, "reduce_only": True, "pnl_usd": pnl, "ucret": ucret, "durum": "dolu", **k}


def test_altin_gunluk_seri_fiili_ve_taban():
    kayit = [
        emir(T0, 10.0, 0.5),                                                         # net +9,5
        emir(T0 + 1000, -4.0, 0.25),                                                 # net -4,25
        {**emir(T0 + 2000, 99.0), "reduce_only": False},                             # açılış: sayılmaz
        {**emir(T0 + 3000, None), "pnl_usd": None},                                  # pnl yok: sayılmaz
        {**emir(T0 + 4000, 7.0), "durum": "red"},                                    # dolmadı: sayılmaz
        {"olay": "emir_yok", "zaman_ms": T0 + 5000, "neden": SK.ML_NEDEN},          # atlanan (ML)
        {"olay": "emir_yok", "zaman_ms": T0 + 6000, "neden": "bant_ici"},            # ilgisiz neden
        {"olay": "karsi_olgu_kapandi", "zaman_ms": T0 + 7000, "neden": SK.ML_NEDEN, "pnl_usd": 3.0},
        {"olay": "karsi_olgu_kapandi", "zaman_ms": T0 + GUN, "neden": SK.DERS_NEDEN, "pnl_usd": -1.5},
        {"olay": "karsi_olgu_kapandi", "zaman_ms": T0 + GUN, "neden": "hip3_atlandi", "pnl_usd": 50.0},   # ML/ders değil: taban'a girmez
        emir(T0 + GUN, 2.0, 0.0),
    ]
    k = SK.karsilastir(kayit, {G0: "v4", G1: "v4"})
    d = k["surumler"]["v4"]["gunler"]
    assert [g["gun"] for g in d] == [G0, G1]
    assert d[0]["v4_ml"] == 5.25 and d[0]["ml_hayali"] == 3.0 and d[0]["v4_taban"] == 8.25 and d[0]["kapanis"] == 2 and d[0]["atlanan"] == 1
    assert d[1]["v4_ml"] == 2.0 and d[1]["ders_hayali"] == -1.5 and d[1]["v4_taban"] == 0.5
    t = k["surumler"]["v4"]["toplam"]
    assert t["v4_ml"] == 7.25 and t["v4_taban"] == 8.75 and t["kapanis"] == 3 and t["atlanan"] == 1
    assert k["filtre_var"] is True


def test_surum_atamasi_gun_haritasi_olay_alani_ve_bilinmeyen():
    kayit = [emir(T0, 1.0), emir(T0 + GUN, 2.0), emir(T0 + GUN + 1, 4.0, surum="v5")]
    k = SK.karsilastir(kayit, {G0: "v4"})                                            # 2. gün haritada yok → "?"; olay `surum` alanı önceliklidir
    assert set(k["surumler"]) == {"v4", "?", "v5"}
    assert k["surumler"]["v4"]["toplam"]["v4_ml"] == 1.0 and k["surumler"]["?"]["toplam"]["v4_ml"] == 2.0 and k["surumler"]["v5"]["toplam"]["v4_ml"] == 4.0


def test_filtre_yokken_iki_seri_ayni_ve_rapor_bunu_soyler():
    k = SK.karsilastir([emir(T0, 5.0, 1.0), emir(T0 + 10, -1.0)], {G0: "v4"})
    assert k["filtre_var"] is False
    g = k["surumler"]["v4"]["gunler"][0]
    assert g["v4_ml"] == g["v4_taban"] == 3.0
    md = "\n".join(SK.md_bolum(k))
    assert "iki seri aynı" in md and "| " + G0 + " | +3.00 $ | +3.00 $ | 2 | 0 |" in md
    assert "aynı" in SK.html_tablo(k)


def test_bos_kayit_ve_bozuk_olaylar():
    assert SK.karsilastir([], None) == {"surumler": {}, "filtre_var": False}
    assert SK.karsilastir([{"olay": "emir"}, {"zaman_ms": "x", "olay": "emir"}], {})["surumler"] == {}      # zaman yok / bozuk: atlanır
    assert "kapanan işlem kaydı yok" in "\n".join(SK.md_bolum(SK.karsilastir([])))
    assert "henüz yok" in SK.html_tablo(SK.karsilastir([]))


def test_pano_markdown_bolumu():
    ozet = {"kip": "sanal", "vardiya": "1", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "getiri": 0.0, "saha": 0, "saha_n": 11, "inen": 0, "sure_dk": 1.0}
    kayit = [emir(T0, 5.0, 1.0), {"olay": "karsi_olgu_kapandi", "zaman_ms": T0 + 5, "neden": SK.ML_NEDEN, "pnl_usd": 2.0}]
    md, _ = pano.pano_olustur(ozet, {}, {}, kayit, [], T0 + 3_600_000, surum_gun={G0: "v4"})
    assert "## Sürüm karşılaştırma" in md and "**v4** · dönem: fiili +4.00 $ · taban +6.00 $" in md
    assert "PBO" not in md
    md2, _ = pano.pano_olustur(ozet, {}, {}, [], [], T0 + 3_600_000)
    assert "kapanan işlem kaydı yok" in md2
