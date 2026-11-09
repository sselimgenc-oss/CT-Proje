"""08.11 seçim denetimi B6/B9 (isabet ek grupları) + B14 (G t-istatistiği): elle hesaplanmış altın örnekler ve "karar değişmez" testleri. Ağsız.

- B14: `g_t_istat` = bootstrap'a giren AYNI işlem başı getiri dizisinin ortalama / (s/√n); yalnız bilgi (`gecti`/`neden` değişmez).
- B6/B9: isabete `ilk11_fiili`, `kor_kirpildi`, `cikanlar`, `evren_ornek30` grupları; yalnız bilgi (havuz, IC, farklar, K‑46 girdileri değişmez).
"""
from __future__ import annotations

import json
import math
import random

import pytest

from copytrade import radar_isabet as ri, radar_kadro as rk, radar_tarama as r
from tests.test_radar_isabet import BAS as IBAS, GUN, SahteBaglam, SahteIstemci, adr, havuz_kadro
from tests.test_radar_tarama import A1, A2, RULES, RULES1, Sahte, dolum, kos, lider, ms, satir_al


# ================================================================================================ B14: t istatistiği
def test_t_istat_altin_ornekler():
    """[0,02; 0,03]: ort 0,025, s = 0,01/√2 = 0,0070711 → t = 0,025 / (0,0070711/√2) = 0,025 / 0,005 = 5,0.
    [0,01; −0,01; 0,03]: ort 0,01, sapmalar 0/−0,02/0,02 → s² = 0,0008/2 = 0,0004, s = 0,02 → t = 0,01 / (0,02/√3) = 0,8660254.
    n < 2 → None; s = 0 → None (tanımsız)."""
    assert r.t_istat([0.02, 0.03]) == pytest.approx(5.0)
    assert r.t_istat([0.01, -0.01, 0.03]) == pytest.approx(math.sqrt(3) / 2)
    assert r.t_istat([-0.02, -0.03]) == pytest.approx(-5.0)
    assert r.t_istat([]) is None and r.t_istat([0.05]) is None and r.t_istat([0.01, 0.01]) is None


def test_kopya_olculeri_g_t_istat_bootstrap_ile_ayni_dizi():
    """kapanan işlemler 20 $, 30 $ (geçerli), 99 $ (geçersiz → hariç) / kasa 1.000 → dizi [0,02; 0,03] (kopya_alt20 ile aynı) → t = 5,0. Boş / hesaplanamadı → None."""
    sonuc = {"getiri": 0.05, "ayna": {"getiri": 0.10}, "baslangic_usd": 1000.0,
             "kapanan_islemler": [{"sonuc_usd": 20.0, "gecerli": True}, {"sonuc_usd": 30.0, "gecerli": True}, {"sonuc_usd": 99.0, "gecerli": False}]}
    o = r.kopya_olculeri(sonuc, A1, RULES)
    assert o["g_t_istat"] == pytest.approx(5.0) and o["kopya_alt20"] == r.bootstrap_alt([0.02, 0.03], 1000, 0.20, r.adres_tohumu(A1))
    assert r.kopya_olculeri({**sonuc, "kapanan_islemler": []}, A1, RULES)["g_t_istat"] is None
    assert r.kopya_olculeri(None, A1, RULES)["g_t_istat"] is None
    assert r.kopya_olculeri({"durum": "hesaplanamadi"}, A1, RULES)["g_t_istat"] is None


def iki_islem_kosu(tmp_path, sub):
    """A1: iki BTC round trip (10 BTC, hesap 20.000 $): 08:00 100 → 09:00 105 ve 10:00 100 → 11:00 110. A2: 10:00 100 → 11:00 110 (tek işlem)."""
    d = {A1: [dolum(ms("08:00:00"), "BTC", "B", 10, 0, 100), dolum(ms("09:00:00"), "BTC", "A", 10, 10, 105, kapanan=50.0),
              dolum(ms("10:00:00"), "BTC", "B", 10, 0, 100), dolum(ms("11:00:00"), "BTC", "A", 10, 10, 110, kapanan=100.0)],
         A2: [dolum(ms("10:00:00"), "BTC", "B", 10, 0, 100), dolum(ms("11:00:00"), "BTC", "A", 10, 10, 110, kapanan=100.0)]}

    def fiyat(coin, t):
        if ms("08:00:00") <= t < ms("09:00:00") or ms("10:00:00") <= t < ms("11:00:00"):
            return 100.0
        if ms("09:00:00") <= t < ms("10:00:00"):
            return 105.0
        return 110.0
    c = Sahte([lider(A1, 20_000, 150, 5_000), lider(A2, 20_000, 100, 5_000)], d, fiyat)
    (tmp_path / sub).mkdir()
    return kos(c, tmp_path / sub, rules=RULES1)


def test_kos_g_t_istat_altin_ornek_ve_karar_degismez(tmp_path, monkeypatch):
    """A1 kopya işlemleri (slot 90,909 $ → hedef 4,545 $ < 11 → 0,11 BTC; 1 dk gecikme, maliyet %0,095 her iki bacak):
    1) 0,11 × 5 = 0,55 $ − (11 + 11,55) × 0,00095 = 0,55 − 0,0214225 = 0,5285775 $ → 0,0005285775
    2) 0,11 × 10 = 1,10 $ − (11 + 12,1) × 0,00095 = 1,10 − 0,021945 = 1,078055 $ → 0,001078055
    n = 2 için t = (a + b) / |a − b| = 0,0016066325 / 0,0005494775 = 2,923926. A2 tek işlem → None.
    Karar: `g_t_istat` hesaplanmasa (None) da tüm satırlar (alan hariç) ve kadro BAYT BAYT aynı."""
    sonuc = iki_islem_kosu(tmp_path, "a")
    s1, s2 = satir_al(sonuc, A1), satir_al(sonuc, A2)
    assert s1["kopya_islem_sayisi"] == 2 and s1["g_t_istat"] == pytest.approx(0.0016066325 / 0.0005494775, rel=1e-6)
    assert s2["kopya_islem_sayisi"] == 1 and s2["g_t_istat"] is None
    monkeypatch.setattr(r, "t_istat", lambda x: None)                       # alan "yokmuş" gibi
    sonuc0 = iki_islem_kosu(tmp_path, "b")
    cikar = lambda h: [{k: v for k, v in s.items() if k != "g_t_istat"} for s in h["satirlar"]]        # noqa: E731
    assert json.dumps(cikar(sonuc), sort_keys=True) == json.dumps(cikar(sonuc0), sort_keys=True)
    assert [(s["gecti"], s["neden"]) for s in sonuc["satirlar"]] == [(s["gecti"], s["neden"]) for s in sonuc0["satirlar"]]
    assert any(s["gecti"] for s in sonuc["satirlar"])
    alansiz = {**sonuc, "satirlar": cikar(sonuc)}
    kadro_cikar = lambda kd: {**kd, "satirlar": [{k: v for k, v in s.items() if k != "g_t_istat"} for s in kd["satirlar"]]}     # noqa: E731 — v1.1: kadro satırı t'yi yalnız BİLGİ olarak taşır
    assert json.dumps(kadro_cikar(rk.kadro_olustur(sonuc, RULES)), sort_keys=True) == json.dumps(kadro_cikar(rk.kadro_olustur(alansiz, RULES)), sort_keys=True)


def test_degerlendir_g_t_istat_degerinden_bagimsiz():
    """Aynı satır: `g_t_istat` −10 / 0 / +10 / yok → `degerlendir` aynı (gecti, neden). `sans_riski` yalnız `kopya_alt20`'ye bakar (alt20 0 → elenir, t = 10 olsa bile)."""
    satir = {"hata": None, "devir_hafta": 1.0, "islem_sayisi": 20, "medyan_tutma_saat": 5.0, "kisa_islem_payi": 0.0, "max_kaldirac": 2.0, "likit_pay": 1.0,
             "kopya_getiri_7g": 0.05, "kopya_koruma": 0.9, "kopya_alt20": 0.01, "kopya_islem_sayisi": 12, "trader_getiri_7g": 0.05, "hesap_usd": 20_000.0}
    taban = r.degerlendir(satir, RULES)
    assert taban == (True, None)
    for t in (-10.0, 0.0, 10.0, None):
        assert r.degerlendir({**satir, "g_t_istat": t}, RULES) == taban
    assert r.degerlendir({**satir, "kopya_alt20": 0.0, "g_t_istat": 10.0}, RULES) == (False, "sans_riski")


# ================================================================================================ B9: fiili saha
K1, K2, K3, K4, K5, X = (adr(i) for i in (1, 2, 3, 4, 5, 900))
KADRO = {"kosu_ms": 1_000_000, "satirlar": [{"adres": a, "sira": i, "katman": "ilk11" if i <= 3 else "yedek"} for i, a in enumerate((K1, K2, K3, K4, K5), 1)]}


def olay(t, tur, adres=None, **kw):
    return {"zaman_ms": t, "olay": tur, **({"adres": adres} if adres else {}), **kw}


def test_saha_fiili_altin_ornek():
    """Pencere [1.000.000, 2.000.000). Önce: kapanis (uyeler K3, X, K2) @500.000 → saha_dus K2 @600.000 → saha_giris K1 @700.000 ⇒ başta saha {K3, X, K1}.
    Kadro üyesi olanlar sıraya göre: K1 (1), K3 (3); X kadroda yok (sayılmaz). Pencerede: saha_giris K5 @1,1 M, X @1,2 M (sayılmaz), K1 tekrar @1,3 M (tekrar sayılmaz),
    K4 @1,4 M; kor_kirpildi K2 @1,5 M ve 1,6 M (tekil), X (kadroda yok); pencere dışı: K2 giriş @2,0 M (bit hariç), kor K4 @400.000 (önce).
    ⇒ oturanlar [K1, K3, K5, K4]; ilk_n = 3 → [K1, K3, K5]; kor_kirpildi [K2]."""
    kayit = [olay(500_000, "kapanis", ozet={"uyeler": [K3, X, K2]}), olay(600_000, "saha_dus", K2), olay(700_000, "saha_giris", K1), olay(400_000, "kor_kirpildi", K4),
             olay(1_100_000, "saha_giris", K5), olay(1_200_000, "saha_giris", X), olay(1_300_000, "saha_giris", K1), olay(1_400_000, "saha_giris", K4),
             olay(1_500_000, "kor_kirpildi", K2), olay(1_600_000, "kor_kirpildi", K2), olay(1_650_000, "kor_kirpildi", X), olay(2_000_000, "saha_giris", K2),
             {"olay": "tur"}]                                                                    # zaman_ms'siz satır atlanır
    fiili, kor, bilgi = ri.saha_fiili(kayit, KADRO, 1_000_000, 2_000_000, 3)
    assert fiili == [K1, K3, K5] and kor == [K2]
    assert bilgi == {"saha_bas_bilinen": True, "kayit_olay": 7, "oturan_toplam": 4}
    fiili11, _, _ = ri.saha_fiili(kayit, KADRO, 1_000_000, 2_000_000, 11)
    assert fiili11 == [K1, K3, K5, K4]


def test_saha_fiili_kapanis_yoksa_bos_baslar_ve_isaretler():
    fiili, kor, bilgi = ri.saha_fiili([olay(1_100_000, "saha_giris", K2), olay(1_200_000, "saha_giris", K1)], KADRO, 1_000_000, 2_000_000, 11)
    assert fiili == [K2, K1] and kor == [] and bilgi["saha_bas_bilinen"] is False


# ================================================================================================ B6: çıkanlar, evren örneği
def test_cikanlar_eski_uye_neden_once_yoksa_onceki_kadro_farki():
    """eski_uye_neden {K5: r0_disi, K4: soguyan} → [K5, K4] ("eski_uye_neden"). Alan yoksa önceki kadro (K4 sira 1, X sira 2, K1 sira 3) − bugün {K1, K2} → [K4, X] ("onceki_kadro"). Hiçbiri → ([], None)."""
    assert ri.cikanlar_sec({"satirlar": [], "eski_uye_neden": {K5: "r0_disi", K4: "soguyan"}}) == ([K5, K4], "eski_uye_neden")
    assert ri.cikanlar_sec({"satirlar": [], "eski_uye_neden": {}}, {"satirlar": [{"adres": X, "sira": 1}]}) == ([], "eski_uye_neden")       # alan var, boş: yedeğe düşülmez
    bugun = {"satirlar": [{"adres": K1, "sira": 1}, {"adres": K2, "sira": 2}]}
    onceki = {"satirlar": [{"adres": K1, "sira": 3}, {"adres": X, "sira": 2}, {"adres": K4, "sira": 1}]}
    assert ri.cikanlar_sec(bugun, onceki) == ([K4, X], "onceki_kadro")
    assert ri.cikanlar_sec(bugun, None) == ([], None)


def test_evren_ornegi_sabit_tohum_tarih_arti_1():
    """Tohum = 20261104 + 1 = 20261105; adaylar adres sıralı, `random.Random(20261105).sample(adaylar, 30)`; aynı tarih aynı, başka tarih başka seçim; < 30 aday → hepsi."""
    havuz = {"satirlar": [{"adres": adr(i)} for i in range(100, 0, -1)]}                # ters sırada: sıralamadan bağımsız
    secilen, tohum, aday = ri.evren_ornegi(havuz, "2026-11-04")
    assert tohum == 20261105 and aday == 100 and len(secilen) == 30 == len(set(secilen)) and secilen == sorted(secilen)
    assert secilen == sorted(random.Random(20261105).sample([adr(i) for i in range(1, 101)], 30))
    assert ri.evren_ornegi(havuz, "2026-11-04")[0] == secilen and ri.evren_ornegi(havuz, "2026-11-05")[0] != secilen
    assert ri.evren_ornegi({"satirlar": [{"adres": adr(1)}, {"adres": adr(2)}]}, "2026-11-04")[0] == [adr(1), adr(2)]
    assert ri.evren_ornegi({"satirlar": []}, "2026-11-04") == ([], 20261105, 0)


# ================================================================================================ B6: isabet çıktısı (bilgi) + karar değişmez
def ek_secim():
    havuz, kadro = havuz_kadro(2)
    kadro["kosu_ms"] = IBAS
    kadro["eski_uye_neden"] = {adr(700): "r0_disi", adr(3): "sira_disi"}
    kayit = [olay(IBAS - 1000, "kapanis", ozet={"uyeler": [adr(1), adr(5)]}), olay(IBAS + 1000, "saha_giris", adr(3)), olay(IBAS + 2000, "kor_kirpildi", adr(2))]
    ek = ri.ek_gruplari_sec(havuz, kadro, "2026-11-04", kayit, None, 11, durum_dali="canli-durum")
    return havuz, kadro, ek


def test_ek_gruplar_isabet_altin_ornek_ve_ana_ciktilar_aynen():
    """ilk11_fiili = başta saha {adr1 (sıra 1), adr5 (sıra 5)} + giriş adr3 → [adr1, adr5, adr3]; sonraki_7g 0,04 / 0,0 / 0,01 → ort 0,05/3 = 0,0166667, medyan 0,01.
    kor_kirpildi [adr2] → 0,02. cikanlar [adr700, adr3]: adr700 ölçülemedi (hesap_yok) → n 1, ort 0,01. evren_ornek30 (17 satırlık havuz < 30 → hepsi).
    Ana gruplar, havuz, IC ve farklar ek gruplarla ve eksiz AYNI (bayt bayt)."""
    havuz, kadro, ek = ek_secim()
    secim0 = ri.gruplari_sec(havuz, kadro, "2026-11-04", 30)
    secim = ri.gruplari_sec(havuz, kadro, "2026-11-04", 30, ek=ek)
    g = secim["gruplar"]
    assert g["ilk11_fiili"] == [adr(1), adr(5), adr(3)] and g["kor_kirpildi"] == [adr(2)] and g["cikanlar"] == [adr(700), adr(3)] and len(g["evren_ornek30"]) == 17
    assert {k: secim["gruplar"][k] for k in ri.ANA_GRUPLAR} == secim0["gruplar"]
    iyi = {adr(1): 0.04, adr(2): 0.02, adr(3): 0.01, adr(4): -0.01, adr(5): 0.0}
    olcum = {a: {"sonraki_7g": v, "sonraki_7g_kotu": v - 0.01, "hata": None} for a, v in iyi.items()}
    for a in secim["gruplar"]["elenen"]:
        olcum[a] = {"sonraki_7g": -0.02, "sonraki_7g_kotu": -0.03, "hata": None}
    olcum[adr(700)] = {"sonraki_7g": None, "sonraki_7g_kotu": None, "hata": "hesap_yok"}
    i = ri.isabet_olustur("2026-11-04", havuz, kadro, secim, olcum, IBAS, IBAS + 7 * GUN, True, False, 1.0, eksik_ek=True)
    i0 = ri.isabet_olustur("2026-11-04", havuz, kadro, secim0, olcum, IBAS, IBAS + 7 * GUN, True, False, 1.0)
    f = i["gruplar"]["ilk11_fiili"]
    assert f["n"] == 3 and f["ortalama"] == pytest.approx(0.05 / 3) and f["medyan"] == pytest.approx(0.01) and f["kar_orani"] == pytest.approx(2 / 3)
    assert f["ortalama_kotu"] == pytest.approx(0.02 / 3)
    assert i["gruplar"]["kor_kirpildi"]["n"] == 1 and i["gruplar"]["kor_kirpildi"]["ortalama"] == pytest.approx(0.02)
    c = i["gruplar"]["cikanlar"]
    assert c["secilen"] == 2 and c["n"] == 1 and c["olculemeyen"] == 1 and c["ortalama"] == pytest.approx(0.01)
    assert i["ek_gruplar"] == list(ri.EK_GRUPLAR) and i["eksik_ek"] is True and i["eksik"] is False
    assert i["ek_kaynak"]["saha_kaynak"] == "canli-durum" and i["ek_kaynak"]["cikanlar_kaynak"] == "eski_uye_neden" and i["ek_kaynak"]["evren_tohum"] == 20261105
    karar = lambda x: json.dumps({k: v for k, v in x.items() if k not in ("gruplar", "satirlar", "ek_gruplar", "ek_kaynak", "eksik_ek")}, sort_keys=True)     # noqa: E731
    assert karar(i) == karar(i0)                                              # havuz, ic, farklar, eksik … aynı
    assert json.dumps({k: i["gruplar"][k] for k in ri.ANA_GRUPLAR}, sort_keys=True) == json.dumps(i0["gruplar"], sort_keys=True)
    assert [s for s in i["satirlar"] if s["grup"] in ri.ANA_GRUPLAR] == i0["satirlar"]
    md = ri.ozet_md(i)
    assert "| ilk11_fiili (bilgi) | 3 | 3 | +0.0167 |" in md and "| evren_ornek30 (bilgi) |" in md and "Ek gruplar (B6/B9" in md
    json.dumps(i, allow_nan=False)


def test_ek_gruplar_saha_kaydi_yoksa_bos_ve_ilk11_ile_doldurulmaz():
    havuz, kadro = havuz_kadro(2)
    ek = ri.ek_gruplari_sec(havuz, kadro, "2026-11-04", None, None, 11)
    assert ek["gruplar"]["ilk11_fiili"] == [] and ek["gruplar"]["kor_kirpildi"] == [] and ek["gruplar"]["cikanlar"] == []
    assert ek["kaynak"]["saha_kaynak"] is None and ek["kaynak"]["cikanlar_kaynak"] is None and len(ek["gruplar"]["evren_ornek30"]) == 17


def test_calistir_ek_adresler_ana_gruplardan_sonra_butce_eksigi_eksik_ek_e(monkeypatch):
    """Bütçe 1.800 sn; saat her çağrıda +100 sn. Ana grup adresleri (5 + 2 elenen = 7) önce ölçülür; ek adreslerin bir kısmı bütçeye takılır → `eksik` false, `eksik_ek` true.
    Havuz dışı adres (adr 700, `cikanlar`) için sabit payda yedeği yok → `hesap_yok`. Ana grup sonuçları ek gruplarsız koşuyla aynı."""
    monkeypatch.setattr(ri.radar_tarama, "Baglam", SahteBaglam)
    havuz, kadro = havuz_kadro(2)
    kadro["eski_uye_neden"] = {adr(700): "r0_disi"}

    def saat_uret():
        t = {"t": 0.0}

        def saat():
            t["t"] += 100.0
            return t["t"]
        return saat
    kayit = [olay(IBAS - 1, "kapanis", ozet={"uyeler": [adr(1), adr(3)]})]
    i = ri.calistir(SahteIstemci(), havuz, kadro, "2026-11-04", IBAS + 8 * GUN, RULES, log=lambda *_: None, saat=saat_uret(), kayitlar=kayit, durum_dali="canli-durum")
    assert i["eksik"] is False and i["eksik_ek"] is True
    s = {(x["adres"], x["grup"]): x for x in i["satirlar"]}
    assert s[(adr(700), "cikanlar")]["hata"] == "hesap_yok" and s[(adr(700), "cikanlar")]["sonraki_7g"] is None
    assert s[(adr(1), "ilk11_fiili")]["sonraki_7g"] == s[(adr(1), "ilk11")]["sonraki_7g"] == pytest.approx(0.002)       # aynı adres bir kez ölçülür, iki grupta görünür
    havuz0, kadro0 = havuz_kadro(2)
    i0 = ri.calistir(SahteIstemci(), havuz0, kadro0, "2026-11-04", IBAS + 8 * GUN, RULES, log=lambda *_: None, saat=saat_uret())
    assert [x for x in i["satirlar"] if x["grup"] in ri.ANA_GRUPLAR] == [x for x in i0["satirlar"] if x["grup"] in ri.ANA_GRUPLAR]
    assert i["havuz"] == i0["havuz"] and i["ic"] == i0["ic"] and i["fark_ilk11_elenen"] == i0["fark_ilk11_elenen"]
