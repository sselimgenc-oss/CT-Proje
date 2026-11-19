"""Kadro seçimi rastgeleye karşı (radar_rastgele): ağsız, sayılar elle hesaplanmıştır. Yalnız bilgi; isabet gruplama/seçim davranışı değişmez."""
import pytest

from copytrade import radar_isabet as ri
from copytrade import radar_rastgele as rr


def satir(grup, v):
    return {"adres": "x", "grup": grup, "sonraki_7g": v}


def test_altin_ornek_tam_sayim():
    """Havuz {1,2,3,4,5}, seçilen {4,5} (ort 4,5). C(5,2)=10 alt küme ortalamaları: 1,5 · 2 · 2,5 · 3 · 2,5 · 3 · 3,5 · 3,5 · 4 · 4,5 → toplam 10.
    Gerçekten KÜÇÜK olan 9, eşit 1 → yüzdelik = 100·(9 + 0,5)/10 = 95; p = (≥ 4,5) = 1/10."""
    s = [satir("ilk11", 4), satir("ilk11", 5), satir("havuz_geri", 1), satir("havuz_geri", 2), satir("havuz_geri", 3)]
    g = rr.karsilastir(s, "2026-11-09")
    assert g["durum"] == "tamam" and g["yontem"] == "tam" and g["r"] == 10
    assert g["secilen_ortalama"] == pytest.approx(4.5)
    assert g["yuzdelik"] == pytest.approx(95.0) and g["p"] == pytest.approx(0.1)
    assert g["rastgele_medyan"] == pytest.approx(3.0)            # sıralı: 1,5 2 2,5 2,5 3 3 3,5 3,5 4 4,5 → (3+3)/2


def test_en_kotu_secim_yuzdelik_dusuk():
    s = [satir("ilk11", 1), satir("ilk11", 2), satir("havuz_geri", 3), satir("havuz_geri", 4), satir("havuz_geri", 5)]
    g = rr.karsilastir(s, "2026-11-09")
    assert g["yuzdelik"] == pytest.approx(5.0) and g["p"] == pytest.approx(1.0)


def test_havuz_yok_ve_olculmeyen_satirlar():
    assert rr.karsilastir([], "2026-11-09")["durum"] == "havuz_yok"
    assert rr.karsilastir([satir("ilk11", 1.0), satir("ilk11", 2.0)], "2026-11-09")["durum"] == "havuz_yok"     # havuz = seçilen: karşılaştırılacak şey yok
    s = [satir("ilk11", None), satir("ilk11", 3), satir("havuz_geri", 1), satir("havuz_geri", None), satir("elenen", 99.0), satir("evren_ornek30", 98.0)]
    g = rr.karsilastir(s, "2026-11-09")
    assert (g["havuz_n"], g["secilen_n"]) == (2, 1) and g["yuzdelik"] == pytest.approx(75.0)       # elenen/evren havuza girmez; {1,3} içinde 3: 1 küçük + 0 eşit... 3 eşit → (1+0,5)/2


def test_ornekleme_tekrarlanabilir_ve_sinirli():
    havuz = [i / 100 for i in range(30)]
    a, y = rr.bos_dagilim(havuz, 11, 1000, 20261109)
    b, _ = rr.bos_dagilim(havuz[::-1], 11, 1000, 20261109)
    assert y == "ornek" and len(a) == 1000 and a == b             # girdi sırası etkisiz, aynı tohum aynı sonuç
    assert min(havuz) <= min(a) and max(a) <= max(havuz)


def test_toplu_ve_tablo():
    gunler = []
    for t, v in (("2026-11-05", 4), ("2026-11-06", 1)):
        s = [satir("ilk11", v), satir("ilk11", v + 1 if v == 4 else 2), satir("havuz_geri", 1 if v == 4 else 3), satir("havuz_geri", 2 if v == 4 else 4), satir("havuz_geri", 3 if v == 4 else 5)]
        gunler.append({"tarih": t, "satirlar": s})
    gunler.append({"tarih": "2026-11-07", "satirlar": []})
    rp = rr.rapor(gunler)
    assert [g["durum"] for g in rp["gunler"]] == ["tamam", "tamam", "havuz_yok"]
    assert rp["toplu"]["gun_n"] == 2 and rp["toplu"]["yuzdelik_ort"] == pytest.approx((95.0 + 5.0) / 2)
    md = rr.md_tablo(rp)
    assert "| Hafta | Seçilen ort. % | Rastgele medyan % | Yüzdelik | p |" in md and "| 2026-11-07 | havuz yok |" in md
    assert rr.rapor([])["toplu"]["durum"] == "yok"


def test_isabet_olustur_bolumu_ekler_secimi_degistirmez():
    """isabet.json'a `rastgele_karsilastirma` eklenir; mevcut gruplar/özet aynı kalır."""
    from tests.test_radar_isabet import BAS, GUN, adr
    adresler = [adr(i) for i in range(1, 6)]
    havuz = {"kosu_ms": BAS, "satirlar": [{"adres": a, "gecti": True, "hesap_usd": 1000.0} for a in adresler]}
    kadro = {"kosu_ms": BAS, "satirlar": [{"adres": a, "katman": "ilk11" if i < 2 else "yedek", "sira": i, "form": 0.5} for i, a in enumerate(adresler)]}
    secim = ri.gruplari_sec(havuz, kadro, "2026-11-04")
    olcum = {a: {"sonraki_7g": v, "sonraki_7g_kotu": v, "hata": None} for a, v in zip(adresler, (0.04, 0.05, 0.01, 0.02, 0.03), strict=True)}
    i = ri.isabet_olustur("2026-11-04", havuz, kadro, secim, olcum, BAS, BAS + 7 * GUN, True, False, 0.0)
    r = i["rastgele_karsilastirma"]
    assert r["durum"] == "tamam" and r["yuzdelik"] == pytest.approx(95.0) and r["p"] == pytest.approx(0.1)
    assert i["gruplar"]["ilk11"]["ortalama"] == pytest.approx(0.045)
