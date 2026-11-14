"""08.11 seçim denetimi (B8, B3/B12) + 06.11 devir denetimi (R-2, R-6): elle hesaplanmış altın örnekler. Ağsız (sahte istemci).

- B8: kopya oynatmasında trader hesap paydası zamana bağlı (`portfolio` accountValueHistory; emir anındaki son değer); eski sabit payda `--payda-yan-yana` ile `_eski` alanlarında.
- B3/B12: `kopya_islem_sayisi`, `yuvarlanan_pay`, `oransal_ayna`, `koruma_boyut` (yalnız bilgi).
- R-2: `veri_hatasi` payı > `radar_veri_hatasi_pay_max` (0,10) olan koşu eksik (kadro yazılmaz, çıkış 2).
- R-6: kadro bayat/yokken de 72 sa işlem yok düşmesi çalışır.
"""
from __future__ import annotations

import json

import pytest
import requests

from copytrade import kopya_v5, radar_isabet as ri, radar_kadro as rk, radar_tarama as r
from copytrade.canli import kadro as kd
from copytrade.defter import HOUR
from tests.test_radar_tarama import A1, BAS, KOSU, RULES, RULES1, Sahte, dolum, kos, lider, ms, satir_al

GUN = 24 * HOUR


# ================================================================================================ B8: payda serisi
def test_payda_serisi_adim_fonksiyonu_nedensel_ve_ilk_noktadan_once_olculemez():
    """Noktalar (1.000 ms → 10.000 $), (5.000 ms → 20.000 $); ≤ 0 ve NaN atılır. t < 1.000 → 0,0 (F02: ölçülemez, gelecek değer yok); 1.000…4.999 → 10.000; ≥ 5.000 → 20.000."""
    p = kopya_v5.PaydaSerisi([(5_000, 20_000.0), (1_000, 10_000.0), (3_000, 0.0), (4_000, float("nan"))])
    assert [p(t) for t in (0, 999, 1_000, 4_999, 5_000, 10**13)] == [0.0, 0.0, 10_000.0, 10_000.0, 20_000.0, 20_000.0] and len(p) == 2
    with pytest.raises(ValueError):
        kopya_v5.PaydaSerisi([(1, 0.0), (2, -5.0)])
    assert kopya_v5.payda_fonk(20_000)(123) == 20_000.0 and kopya_v5.payda_fonk(p) is p              # sabit sayı = eski davranış


def portfoy(week, month=(), all_time=()):
    """Gerçek HL `portfolio` biçimi: [[dönem, {accountValueHistory: [[ms, "değer"], …], pnlHistory, vlm}], …] (perp* dönemleri kullanılmaz)."""
    f = lambda xs: {"accountValueHistory": [[t, str(v)] for t, v in xs], "pnlHistory": [], "vlm": "0"}        # noqa: E731
    return [["day", f([])], ["week", f(week)], ["month", f(month)], ["allTime", f(all_time)], ["perpWeek", f([(BAS, 1.0)])]]


def test_payda_noktalari_ince_donem_once_kaba_yalniz_daha_eskisi_bit_sonrasi_ve_bozuk_atilir():
    """week: BAS−1 sa 4.000, 09:00 5.000, 11:30 21.000, KOSU+1 sa 99 (bit sonrası → atılır). month: BAS−10 g 3.000 (week'ten eski → alınır), BAS−1 sa 999 (week'in ilk noktasıyla aynı an,
    daha eski değil → atılır), "x" (bozuk). allTime: BAS−40 g 2.000 (alınır), BAS−5 g 7 (month'un en eskisinden yeni → atılır). perpWeek kullanılmaz."""
    p = portfoy([(BAS - HOUR, 4_000), (ms("09:00:00"), 5_000), (ms("11:30:00"), 21_000), (KOSU + HOUR, 99)],
                [(BAS - 10 * GUN, 3_000), (BAS - HOUR, 999), (BAS - 2 * GUN, "x")], [(BAS - 40 * GUN, 2_000), (BAS - 5 * GUN, 7)])
    assert r.payda_noktalari(p, KOSU) == [(BAS - 40 * GUN, 2_000.0), (BAS - 10 * GUN, 3_000.0), (BAS - HOUR, 4_000.0), (ms("09:00:00"), 5_000.0), (ms("11:30:00"), 21_000.0)]
    assert r.payda_noktalari([], KOSU) == [] and r.payda_noktalari(None, KOSU) == [] and r.payda_noktalari("bozuk", KOSU) == []


class SahteP(Sahte):
    """`Sahte` + `portfolio` (adres → yanıt ya da istisna)."""

    def __init__(self, *a, portfoyler=None, **k):
        super().__init__(*a, **k)
        self.portfoyler, self.portfoy_okuma = portfoyler or {}, 0

    def portfolio(self, adres):
        self.portfoy_okuma += 1
        v = self.portfoyler.get(adres, [])
        if isinstance(v, Exception):
            raise v
        return v


def test_payda_oku_yedekler_sabit_hesaba_duser_veri_hatasi_yapmaz():
    p = portfoy([(BAS, 4_000), (ms("09:00:00"), 5_000)])
    seri, bilgi = r.payda_oku(SahteP([], {}, portfoyler={A1: p}), A1, 20_000.0, BAS, KOSU, RULES)
    assert isinstance(seri, kopya_v5.PaydaSerisi) and bilgi == {"payda_kaynak": "portfolio", "payda_nokta": 2, "payda_bas_usd": 4_000.0, "payda_son_oran": 0.25}     # 5.000 / 20.000
    assert r.payda_oku(SahteP([], {}, portfoyler={A1: requests.ConnectionError("x")}), A1, 20_000.0, BAS, KOSU, RULES)[0] == 20_000.0
    assert r.payda_oku(SahteP([], {}, portfoyler={A1: requests.ConnectionError("x")}), A1, 20_000.0, BAS, KOSU, RULES)[1]["payda_kaynak"] == "sabit_yedek"
    assert r.payda_oku(SahteP([], {}), A1, 20_000.0, BAS, KOSU, RULES) == (20_000.0, {"payda_kaynak": "sabit_yedek", "payda_nokta": None, "payda_bas_usd": None, "payda_son_oran": None})   # boş seri
    assert r.payda_oku(Sahte([], {}), A1, 20_000.0, BAS, KOSU, RULES)[1]["payda_kaynak"] == "sabit_yedek"                 # istemcide portfolio yok
    c = SahteP([], {}, portfoyler={A1: p})
    assert r.payda_oku(c, A1, 20_000.0, BAS, KOSU, {**RULES, "radar_payda_zaman": False}) == (20_000.0, {"payda_kaynak": "sabit", "payda_nokta": None, "payda_bas_usd": None, "payda_son_oran": None})
    assert c.portfoy_okuma == 0                                                                                              # kural kapalı: okunmaz


def senaryo():
    """Trader 10 BTC'yi 10:00'da 100'den açar, 11:00'de 110'dan kapatır (test_radar_tarama'daki T2 altın örneği). Lider tablosu (koşu anı) hesabı 20.000 $;
    portfolio geçmişi: BAS−1 sa 4.000, 09:00 5.000, 11:30 21.000 → açılış anındaki (10:00 / 10:01) hesap 5.000 $."""
    dolumlar = {A1: [dolum(ms("10:00:00"), "BTC", "B", 10, 0, 100), dolum(ms("11:00:00"), "BTC", "A", 10, 10, 110, kapanan=100.0)]}
    fiyat = lambda coin, t: 110.0 if t >= ms("11:00:00") else 100.0               # noqa: E731
    p = portfoy([(BAS - HOUR, 4_000), (ms("09:00:00"), 5_000), (ms("11:30:00"), 21_000)])
    return SahteP([lider(A1, 20_000, 100, 5_000)], dolumlar, fiyat, portfoyler={A1: p})


def test_b8_altin_ornek_zamana_bagli_payda_ve_eski_yan_yana(tmp_path):
    """Slot = 1.000 / 11 = 90,909 $. YENİ (payda 5.000 $): hedef = 90,909 × 1.000 / 5.000 = 18,1818 $ ≥ 11 → yuvarlanmaz (0,181818 BTC).
      ayna: kâr 0,181818 × 10 = 1,81818 $ → 0,00181818. kopya (10:01 @100, 11:01 @110): maliyet (18,1818 + 20,0) × 0,00095 = 0,0362727 $ → net 1,7819091 $ → 0,0017819091.
      kopya_koruma = 1,7819091 / 1,8181818 = 0,98005. yuvarlanan_pay 0/1 = 0; oransal_ayna = ayna (asgari emir devreye girmiyor) → koruma_boyut 1,0; kopya_islem_sayisi 1.
    ESKİ (sabit 20.000 $): hedef 4,545 $ < 11 → 11 $ (test_radar_tarama altın örneği): kopya 0,001078055, ayna 0,0011, koruma 0,98005.
    payda_bas_usd = BAS anındaki değer 4.000 (BAS−1 sa noktası); payda_son_oran = KOSU'daki 21.000 / 20.000 = 1,05; nokta 3."""
    sonuc = kos(senaryo(), tmp_path, rules=RULES1, payda_yan_yana=True)
    s = satir_al(sonuc, A1)
    assert s["payda_kaynak"] == "portfolio" and s["payda_nokta"] == 3 and s["payda_bas_usd"] == 4_000.0 and s["payda_son_oran"] == pytest.approx(1.05)
    assert s["ayna_getiri_7g"] == pytest.approx(0.00181818182, abs=1e-10)
    assert s["kopya_getiri_7g"] == pytest.approx(0.0017819091, abs=1e-9)
    assert s["kopya_koruma"] == pytest.approx(1.7819091 / 1.8181818, abs=1e-6)
    assert s["kopya_islem_sayisi"] == 1 and s["yuvarlanan_pay"] == 0.0
    assert s["oransal_ayna"] == pytest.approx(0.00181818182, abs=1e-10) and s["koruma_boyut"] == pytest.approx(1.0)
    assert s["kopya_getiri_7g_eski"] == pytest.approx(0.001078055, abs=1e-9) and s["ayna_getiri_7g_eski"] == pytest.approx(0.0011, abs=1e-9)
    assert s["kopya_koruma_eski"] == pytest.approx(0.98005, abs=1e-5) and s["kopya_alt20_eski"] == pytest.approx(0.001078055, abs=1e-9)
    assert s["gecti"] is True and s["gecti_eski"] is True and s["neden_eski"] is None and sonuc["payda_yan_yana"] is True
    assert s["kopya_getiri_72s"] == pytest.approx(0.0017819091 * 11, abs=1e-8)                             # F-03: aynı (yeni paydalı) oynatmanın eğrisinden, SLOT ölçeğinde (kasa getirisi × N)
    assert len(s["kopya_gunluk"]) == 7 and all(g == 0.0 for g in s["kopya_gunluk"])                     # F-08: işlemin olduğu son gün (27 Eki, 12 sa) kısmi → seriden atıldı
    md = r.ozet_md(sonuc)
    assert "Payda (B8): portfolio 1" in md and "gecti eski 1 → yeni 1" in md and "yalnız yeni 0; yalnız eski 0" in md
    assert "| yuvarlanan_pay | 1 | 0 | 0 | 0 |" in md and "| kopya_getiri_7g_eski | 1 |" in md
    assert json.loads((tmp_path / "radar/2026-10-27/havuz.json").read_text(encoding="utf-8")) == sonuc


def test_b8_kural_kapali_eski_sayilar_birebir_ve_b3_yuvarlama_alanlari(tmp_path):
    """`radar_payda_zaman: false` = eski davranış birebir (portfolio okunmaz): kopya 0,001078055, ayna 0,0011.
    B3: tek açılış 4,545 $ → 11 $'a YUVARLANDI → yuvarlanan_pay 1/1 = 1,0. oransal_ayna (asgari emir 0): 4,545 $ = 0,0454545 BTC × 10 = 0,454545 $ → 0,000454545;
    koruma_boyut = 0,0011 / 0,000454545 = 2,42 (yuvarlama aynayı 2,42× şişiriyor). Yan yana kapalı: `_eski` alanı yok."""
    c = senaryo()
    s = satir_al(kos(c, tmp_path, rules={**RULES1, "radar_payda_zaman": False}), A1)
    assert c.portfoy_okuma == 0 and s["payda_kaynak"] == "sabit" and s["payda_nokta"] is None
    assert s["kopya_getiri_7g"] == pytest.approx(0.001078055, abs=1e-9) and s["ayna_getiri_7g"] == pytest.approx(0.0011, abs=1e-9)
    assert s["yuvarlanan_pay"] == 1.0 and s["kopya_islem_sayisi"] == 1
    assert s["oransal_ayna"] == pytest.approx(0.000454545, abs=1e-9) and s["koruma_boyut"] == pytest.approx(2.42, abs=1e-6)
    assert "kopya_getiri_7g_eski" not in s and "gecti_eski" not in s


def test_b8_portfolio_okunamazsa_sabit_yedek_sayilar_eskiyle_ayni_satir_gecerli(tmp_path):
    c = senaryo()
    c.portfoyler[A1] = requests.HTTPError("500")
    s = satir_al(kos(c, tmp_path, rules=RULES1, payda_yan_yana=True), A1)
    assert s["payda_kaynak"] == "sabit_yedek" and s["hata"] is None and s["neden"] is None
    assert s["kopya_getiri_7g"] == s["kopya_getiri_7g_eski"] == pytest.approx(0.001078055, abs=1e-9)


def test_b8_yan_yana_kopyaya_varmayan_satirda_eski_yeni_ayni_ve_karari_degisen_tabloda():
    """Kopyaya varmayan satır (dolum kuralıyla elenen) için `kos` eski = yeni yazar; özet kararı değişen adresi tabloya döker."""
    satirlar = [{"adres": "0x" + "a" * 40, "gecti": True, "neden": None, "gecti_eski": False, "neden_eski": "kopya_koruma_dusuk", "kopya_getiri_7g": 0.03, "kopya_getiri_7g_eski": 0.01,
                 "payda_kaynak": "portfolio", "payda_bas_usd": 5_000.0, "hesap_usd": 10_000.0},
                {"adres": "0x" + "b" * 40, "gecti": True, "neden": None, "gecti_eski": True, "neden_eski": None, "kopya_getiri_7g": 0.02, "kopya_getiri_7g_eski": 0.03, "payda_kaynak": "sabit_yedek"},
                {"adres": "0x" + "c" * 40, "gecti": False, "neden": "islem_az", "gecti_eski": False, "neden_eski": "islem_az", "kopya_getiri_7g": None, "kopya_getiri_7g_eski": None}]
    md = "\n".join(r.payda_ozeti(satirlar))
    assert "Payda (B8): portfolio 1, sabit_yedek 1" in md and "gecti eski 1 → yeni 2; ikisinde de 1; yalnız yeni 1; yalnız eski 0" in md
    assert "n 2, min -0.01, medyan +0.005, max +0.02" in md
    assert "| 0xaaaaaaaa… | False → True | kopya_koruma_dusuk → None | 0.01 → 0.03 | 0.5 |" in md and "0xbbbbbbbb" not in md.split("| adres |")[1]


def test_b8_yan_yana_dolumla_elenen_satir_eski_alanlari_yeniyle_ayni(tmp_path):
    c = senaryo()
    s = satir_al(kos(c, tmp_path, rules=RULES, payda_yan_yana=True), A1)                       # RULES: 1 işlem < 10 → islem_az, kopya oynatılmaz, portfolio okunmaz
    assert s["neden"] == "islem_az" and s["gecti_eski"] is False and s["neden_eski"] == "islem_az" and s["kopya_getiri_7g_eski"] is None and c.portfoy_okuma == 0


# ================================================================================================ B3/B12 saf fonksiyonlar
def test_yuvarlanan_pay_ve_kopya_islem_sayisi_koruma_boyut():
    kayit = [("ac", "min_emir_yuvarlandi", 11.0), ("ac", "tamam", 20.0), ("ac", "min_emir_atlandi", 0.0), ("artir", "tamam", 5.0), ("ac", "min_emir_yuvarlandi", 11.0), ("kapat", "tam_kapanis", 11.0)]
    assert r.yuvarlanan_pay(kayit) == pytest.approx(2 / 3) and r.yuvarlanan_pay([]) is None and r.yuvarlanan_pay([("ac", "min_emir_atlandi", 0.0)]) is None
    sonuc = {"getiri": 0.05, "ayna": {"getiri": 0.10}, "oransal_ayna": {"getiri": 0.05}, "yuvarlanan_pay": 0.5, "baslangic_usd": 1000.0,
             "kapanan_islemler": [{"sonuc_usd": 20.0, "gecerli": True}, {"sonuc_usd": 30.0, "gecerli": True}, {"sonuc_usd": 99.0, "gecerli": False}]}
    o = r.kopya_olculeri(sonuc, A1, RULES)
    assert o["kopya_islem_sayisi"] == 2 and o["yuvarlanan_pay"] == 0.5 and o["oransal_ayna"] == 0.05 and o["koruma_boyut"] == pytest.approx(2.0)      # 0,10 / 0,05
    assert r.kopya_olculeri({**sonuc, "oransal_ayna": {"getiri": 0.0}}, A1, RULES)["koruma_boyut"] is None
    assert r.kopya_olculeri({k: v for k, v in sonuc.items() if k != "oransal_ayna"}, A1, RULES)["koruma_boyut"] is None
    assert r.kopya_olculeri({**sonuc, "kapanan_islemler": []}, A1, RULES)["kopya_islem_sayisi"] == 0


# ================================================================================================ B8: isabet aynı paydayı kullanır
def test_isabet_ayni_zamana_bagli_paydayi_kullanir(monkeypatch):
    from tests.test_radar_isabet import BAS as IBAS, SahteBaglam, SahteIstemci, havuz_kadro

    gorulen = []

    class B(SahteBaglam):
        def kopya_oynat(self, dolumlar, hesap):
            gorulen.append(hesap)
            return super().kopya_oynat(dolumlar, hesap)

    class I(SahteIstemci):
        def portfolio(self, adres):
            return portfoy([(IBAS, 7_000), (IBAS + HOUR, 8_000)])

    monkeypatch.setattr(ri.radar_tarama, "Baglam", B)
    havuz, kadro = havuz_kadro(1)
    i = ri.calistir(I(), havuz, kadro, "2026-11-04", IBAS + 8 * GUN, RULES, log=lambda *_: None)
    assert gorulen and all(isinstance(h, kopya_v5.PaydaSerisi) and h(IBAS) == 7_000.0 and h(IBAS + 2 * HOUR) == 8_000.0 for h in gorulen)
    assert {x["payda_kaynak"] for x in i["satirlar"] if x["sonraki_7g"] not in (None, 0.0)} == {"portfolio"}
    gorulen.clear()
    i2 = ri.calistir(SahteIstemci(), havuz, kadro, "2026-11-04", IBAS + 8 * GUN, RULES, log=lambda *_: None)          # portfolio yok → havuz hesap_usd (sabit, eski)
    assert gorulen and all(isinstance(h, float) for h in gorulen) and {x["payda_kaynak"] for x in i2["satirlar"] if x["sonraki_7g"] not in (None, 0.0)} == {"sabit_yedek"}


# ================================================================================================ R-2
def test_r2_veri_hatasi_payi_yuzde_10_dahil_tam_ustu_eksik(tmp_path):
    """10 satır (evren 10): 1 veri_hatasi = %10 → tam (sınır dahil); 2 = %20 > %10 → eksik, kadro yazılmaz, çıkış 2."""
    def havuz(hatali):
        satirlar = [{"adres": f"0x{i}", "gecti": False, "neden": "veri_hatasi" if i < hatali else "islem_az"} for i in range(10)]
        return {"sema": "radar-havuz-v1", "kosu_ms": 1_800_000_000_000, "pencere_bas_ms": 0, "evren_toplam": 10, "evren_kesilen": 0, "satirlar": satirlar}
    assert rk.kosu_tam_mi(havuz(1), RULES) == (True, None)
    tam, neden = rk.kosu_tam_mi(havuz(2), RULES)
    assert tam is False and "2/10 satır veri_hatasi" in neden
    assert rk.kosu_tam_mi(havuz(0), {**RULES, "radar_veri_hatasi_pay_max": 0.0}) == (True, None)
    yol = tmp_path / "havuz.json"
    yol.write_text(json.dumps(havuz(2)), encoding="utf-8")
    assert rk.main(["--havuz", str(yol)]) == 2 and not (tmp_path / "kadro.json").exists()
    yol.write_text(json.dumps(havuz(1)), encoding="utf-8")
    assert rk.main(["--havuz", str(yol)]) == 0 and (tmp_path / "kadro.json").exists()


# ================================================================================================ R-6
def test_r6_kadro_bayat_ya_da_yokken_islem_yok_72_saat_dusmesi_calisir():
    """Üyeler T0+1 sa girer (hazir_11). adr(11)'in son dolumu T0−50 sa → 72 sa sınırı T0+22 sa; diğerleri T0+2 sa'te işlem yaptı.
    Kadro T0'da koştu ve T0+37 sa'te bayat (36 sa): eski kod hiçbir şey yapmazdı; şimdi adr(11) `islem_yok` (sonuç dışı, bekleme yok) düşer, diğerleri (35 sa) kalır.
    Kadro hiç yoksa (okunamadı) aynı. Sınırın 1 ms öncesinde düşme yok."""
    from tests.test_canli_motor import RULES as MR, SAAT, T0, adr, hazir_11, n_kadro

    def kur():
        s = hazir_11()
        for i in range(1, 11):
            s.islem_gordu(adr(i), T0 + 2 * SAAT)
        s.islem_gordu(adr(11), T0 - 50 * SAAT)
        return s
    s = kur()
    karar, durum = s.degerlendir(n_kadro(11, T0), T0 + 37 * SAAT)
    assert durum == "kadro_bayat" and [(k.tur, k.adres, k.neden, k.sonuc) for k in karar] == [("dus", adr(11), "islem_yok", False)]
    assert adr(11) not in s.uyeler and adr(11) not in s.bekleme and len(s.uyeler) == 10 and adr(11) in s.inen
    s2 = kur()
    karar2, durum2 = s2.degerlendir(None, T0 + 22 * SAAT)
    assert durum2 == "kadro_yok" and [(k.adres, k.neden) for k in karar2] == [(adr(11), "islem_yok")]
    assert kur().degerlendir(None, T0 + 22 * SAAT - 1) == ([], "kadro_yok")
    assert kd.Saha(MR, 1000.0).degerlendir(None, T0) == ([], "kadro_yok")                       # üye yok: karar yok
