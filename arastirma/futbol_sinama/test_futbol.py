"""Futbol sınaması testleri: altın örnekler elle hesaplanmıştır."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import futbol as f  # noqa: E402


def test_kadro_getirisi_altin():
    # N=3, üyeler [0.10, -0.04]: kasa = 0.06/3 = 0.02 ; dolu = 0.06/2 = 0.03
    k, d = f.kadro_getirisi([0.10, -0.04], 3)
    assert k == pytest.approx(0.02)
    assert d == pytest.approx(0.03)


def test_yuzdelik_altin():
    # kadro 0.0; çekilişler [-1, 0, 1, 1]: altı 1/4, eşit 1/4 → 0.25 + 0.125
    assert f.yuzdelik(0.0, [-1, 0, 1, 1]) == pytest.approx(0.375)
    assert f.yuzdelik(-5, [-1, 0, 1]) == 0.0
    assert f.yuzdelik(5, [-1, 0, 1]) == 1.0


def test_kura_ic_ice_ve_deterministik():
    ad = [f"0x{i:02d}" for i in range(20)]
    a = f.kura(ad[::-1], 123)            # girdi sırası etkisiz (adrese göre sıralanır)
    assert a == f.kura(ad, 123)
    assert sorted(a) == ad and a != ad
    assert a[:3] == f.kura(ad, 123)[:3] and a[:5][:3] == a[:3]       # iç içe: N=3 ⊂ N=5
    assert a != f.kura(ad, 124)
    assert a == [ad[i] for i in np.random.default_rng([20261111, 123]).permutation(20)]


def test_t12_assert():
    tar = list(range(1000, 13000, 1000))        # 12 tarih
    assert f.t_ayir(tar[0], tar) == 0 and f.t_ayir(tar[10], tar) == 10
    with pytest.raises(AssertionError):
        f.t_ayir(tar[11], tar)                  # T12
    with pytest.raises(AssertionError):
        f.t_ayir(99999, tar)                    # bugün / dışı


def test_ac_sayimi_slot100():
    import yaml
    r = yaml.safe_load(open(Path(f.KOK_REPO) / "copytrade" / "kurallar.yaml", encoding="utf-8"))   # yaml doğrudan (başka testler load_rules önbelleğini değiştirebilir)
    assert float(r["radar_min_emir_usd"]) == 11 and float(r["radar_min_emir_yuvarla_alt"]) == 5.5
    rs = f.kural_slot(r, 100)
    assert rs["canli_kasa_usd"] == 500 and rs["radar_canli_slot_min_usd"] == 100 and r["canli_kasa_usd"] == 1000   # özgün sözlük değişmedi
    s = f.Sayac()

    def c(*a):                                          # boyutlayici.isle yerel değişkenlerini taklit eden çağıran
        coin, before_leader = "X", 0.0                  # noqa: F841 — Sayac çerçeveden okur
        return s.hedef_emir(*a)
    # hedef = slot × sonra × fiyat / hesap : 100×1×8000/1e5 = 8 $ → yuvarlandı ; 4 $ → atlandı ; 50 $ → tamam ; artır (ac değil) sayılmaz
    assert c("ac", 0, 1, 1e5, 0, 100, 8000, rs, 0) == (11.0, "min_emir_yuvarlandi")
    assert c("ac", 0, 1, 1e5, 0, 100, 4000, rs, 0) == (0.0, "min_emir_atlandi")
    assert c("ac", 0, 1, 1e5, 0, 100, 50000, rs, 0)[1] == "tamam"
    c("artir", 1, 2, 1e5, 20, 100, 50000, rs, 20)
    assert (s.ac["toplam"], s.ac["ac_yuv"], s.ac["ac_atl"], s.ac["ac_diger"]) == (3, 1, 1, 1)
    assert s.atlanan == pytest.approx(4.0)                 # ideal atlanan $
    assert f.Sayac.son is s


def _rec(getiri, ok=True):
    d = {"getiri": getiri, "dusus": 0.0, "islem": 1, "durum": "olculdu", "ac_toplam": 2, "ac_yuv": 1, "ac_atl": 0, "ideal_top": 20.0, "ideal_atl": 0.0,
         "tasfiye": False, "fiyatsiz": 0, **{k: 0 for k in f.AC_ALAN if k.startswith(("ac_slot", "ac_hesap", "ac_tavan", "ac_diger"))}, **{k: 0 for k in f.EP_ALAN}}
    return {"ornek50": True, "k50": True, "cikarildi": None, "kapi_gecti": ok, "veto": None, "kaynak": "onbellek", "oyna": True,
            "slot": {str(s): dict(d) for s in f.SLOTLAR}}


def test_aday_yok_ve_kontrol_kucuk():
    T = 5
    rec = {f"k{i}": {str(T): _rec(0.01 * i, ok=False)} for i in range(2)}      # kontrol 2 kişi, aday yok
    s = f._t_satiri("ornek700", 3, 100, T, 0, [], sorted(rec), rec)
    assert s["kadro_getiri"] == 0 and s["dolu_getiri"] is None and s["kadro_n"] == 0 and s["bos_koltuk"] == 3
    assert s["yuzdelik"] is None and s["dolu_yuzdelik"] is None and s["kontrol_n"] == 2       # kontrol havuzu < N
    o = f.hucre_ozeti([s])
    assert o["bos_koltuk_orani"] == 1 and o["bos_koltuk_payi_ort"] == 1 and o["birlesik_yuzdelik"] is None and o["dolu_ortalama"] is None


def test_t_satiri_dolu():
    T = 7
    rec = {f"a{i}": {str(T): _rec(0.1 * (i + 1))} for i in range(6)}            # hepsi aday ve kontrol
    ad = sorted(rec)
    s = f._t_satiri("genis", 3, 150, T, 2, ad, ad, rec)
    uyeler = f.kura(ad, T)[:3]
    assert s["kadro_getiri"] == pytest.approx(sum(rec[a][str(T)]["slot"]["150"]["getiri"] for a in uyeler) / 3)
    assert s["ac_toplam"] == 6 and s["ac_yuvarlanan"] == 3 and s["kontrol_n"] == 6
    assert 0 <= s["yuzdelik"] <= 1 and s["dolu_yuzdelik"] is not None
    # eşli çekiliş: slot'tan bağımsız indeks
    assert f.cekilis_idx([f.TOHUM, 3, 2], 6, 3) is f.cekilis_idx([f.TOHUM, 3, 2], 6, 3)


def test_temiz_tanimi():
    r = {"k50": True, "cikarildi": None, "kapi_gecti": True, "veto": None}
    assert f.temiz(r)
    for k, v in (("k50", False), ("cikarildi", "dolum_yok"), ("kapi_gecti", False), ("veto", "veto_omur_zarar")):
        assert not f.temiz({**r, k: v})


def test_epizot_poz_duzeyi_altin():
    """İki epizot, slot 100: A coin 8 $ hedef → 11 $'a yuvarlanıp açıldı; B coin 4 $ → hiç açılmadı (min). Paylar: yuvarlanan 1/1, atlanan 1/2."""
    import yaml
    from copytrade import kopya_v5
    r = f.kural_slot(yaml.safe_load(open(Path(f.KOK_REPO) / "copytrade" / "kurallar.yaml", encoding="utf-8")), 100)
    s = f.Sayac()
    isle = kopya_v5.boyutlayici(1e5, 100.0, r)
    eski = kopya_v5.boyut
    kopya_v5.boyut = s.mod
    try:
        isle(1, 1.0, 0.0, 0.0, 8000.0, 0, {}, {}, None, 0.0, 500.0, "A")      # 100×1×8000/1e5 = 8 $ → yuvarlandı
        isle(1, 1.0, 0.0, 0.0, 4000.0, 0, {}, {}, None, 0.0, 500.0, "B")      # 4 $ → atlandı
    finally:
        kopya_v5.boyut = eski
    o = s.ozet()
    assert (o["epizot_toplam"], o["epizot_acildi"], o["epizot_ilk_yuvarlandi"], o["epizot_hic_acilmadi_min"], o["epizot_hic_acilmadi_tavan"]) == (2, 1, 1, 1, 0)
    assert (o["ac_toplam"], o["ac_yuv"], o["ac_atl"]) == (2, 1, 1)
    row = {**o, "kadro_getiri": 0.0, "dolu_getiri": None, "yuzdelik": None, "dolu_yuzdelik": None, "kadro_n": 0, "aday_n": 0, "bos_koltuk": 3, "havuz": "genis", "N": 3,
           "slot": 100, "ac_yuvarlanan": o["ac_yuv"], "ac_atlanan": o["ac_atl"], "ideal_top": 1.0, "ideal_atl": 0.0, "kontrol_ortanca": None, "_c": None}
    h = f.hucre_ozeti([row])
    assert h["yuvarlanan_poz_pay"] == 1.0 and h["atlanan_poz_pay"] == 0.5
    # trader B epizotu sonra tekrar açılır (before=0): yeni epizot; ters dönüş de yeni epizot
    s2 = f.Sayac()
    kopya_v5.boyut = s2.mod
    try:
        isle(1, 1.0, 0.0, 0.0, 4000.0, 0, {}, {}, None, 0.0, 500.0, "B")
        isle(1, 1.0, 1.0, 0.0, 4000.0, 1, {}, {}, None, 0.0, 500.0, "B")      # aynı epizot (devam, hâlâ kopyada açık değil)
        isle(1, 1.0, 0.0, 0.0, 4000.0, 2, {}, {}, None, 0.0, 500.0, "B")      # trader düzdü → yeni epizot
    finally:
        kopya_v5.boyut = eski
    assert s2.ozet()["epizot_toplam"] == 2
