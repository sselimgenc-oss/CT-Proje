"""Canlı motor (T4): saha kuralları, motor uçtan uca (sahte borsa / WS / Telegram), kip güvencesi, dayanıklılık, anahtar taraması. Ağsız; elle hesaplanmış altın örnekler."""
import asyncio
import json
import re
import subprocess
import time
from pathlib import Path

import pytest

from copytrade import dinleyici as d
from copytrade.canli import kadro as kd
from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from copytrade.canli import yurutucu as yu
from copytrade.kurallar import load_rules

RULES = load_rules()
ROOT = Path(__file__).resolve().parents[1]
T0 = 1_800_000_000_000                       # 2027-01-15 08:00 UTC (gece yarısı DEĞİL; UTC gün sınırı = (T0 // GUN + 1) * GUN)
GUN, SAAT = 86_400_000, 3_600_000


def adr(i: int) -> str:
    return "0x" + f"{i:040x}"


def satir(i, sira, form=50.0, kald=3.0):
    return {"adres": adr(i), "sira": sira, "katman": "ilk11" if sira <= 11 else "yedek", "form": form, "bilesenler": {}, "kopya_getiri_7g": 0.01, "max_kaldirac": kald}


def kadro(satirlar, kosu_ms=T0, kor=None):
    return {"sema": "radar-kadro-v1", "kosu_ms": kosu_ms, "kasa_usd": 1000.0, "slot_usd": 1000 / 11, "saha_n": 11, "gecti_sayisi": len(satirlar), "soguyan": [], "satirlar": satirlar,
            "korelasyon": kor or {"adresler": [], "gun_sayisi": 8, "matris": []}}


def n_kadro(n, kosu_ms=T0, form0=90.0):
    return kadro([satir(i, i, form0 - i) for i in range(1, n + 1)], kosu_ms)


# ================================================================================================ saha kuralları
def test_ilk_gun_ilk_n_sahaya_degisiklik_sayilmaz_kasa_100_n4():
    s = kd.Saha(RULES, 100.0)
    karar, durum = s.degerlendir(n_kadro(10), T0 + SAAT)
    assert durum == "ok" and s.n == 4 and s.slot == 25.0
    assert [k.adres for k in karar if k.tur == "giris"] == [adr(1), adr(2), adr(3), adr(4)] and s.degisiklik["adet"] == 0 and s.kurulu


def test_k33_kadro_n_den_kucukse_bos_slot_nakit_slot_tutari_degismez():
    s = kd.Saha(RULES, 1000.0)
    s.degerlendir(n_kadro(3), T0 + SAAT)
    assert len(s.uyeler) == 3 and s.n == 11 and s.slot == pytest.approx(1000 / 11)          # 8 slot nakit; slot tutarı kasa / 11 (3'e bölünmedi)
    karar, _ = s.degerlendir(n_kadro(5, T0 + GUN), T0 + GUN + SAAT)                          # kadro büyüdü: boş slot §5 giriş kuralıyla dolar (günde ≤ 2)
    assert [k.adres for k in karar if k.tur == "giris"] == [adr(4), adr(5)] and len(s.uyeler) == 5


def hazir_11():
    s = kd.Saha(RULES, 1000.0)
    s.degerlendir(n_kadro(11), T0 + SAAT)
    return s


def test_histerezis_form_farki_en_az_10_puan_sinirda_girer():
    """Üye adr(11) sıra 12 (> 11), form 40; aday adr(12) sıra 11, form 50 (= +10 puan: girer); 49,99 girmez."""
    def gun2(aday_form):
        rows = [satir(i, i, 90 - i) for i in range(1, 11)] + [satir(12, 11, aday_form), satir(11, 12, 40.0)]
        return kadro(rows, T0 + GUN)
    s = hazir_11()
    karar, _ = s.degerlendir(gun2(50.0), T0 + GUN + SAAT)
    assert [(k.tur, k.adres, k.neden, k.sonuc) for k in karar] == [("dus", adr(11), "daha_iyisi_geldi", False), ("giris", adr(12), "degistirme", False)]
    assert adr(12) in s.uyeler and adr(11) not in s.uyeler and adr(11) not in s.bekleme            # sonuç dışı: bekleme cezası YOK
    s2 = hazir_11()
    assert s2.degerlendir(gun2(49.99), T0 + GUN + SAAT)[0] == [] and adr(11) in s2.uyeler


def test_gunde_en_fazla_2_degisiklik_ve_sonuc_ile_dusene_14_gun_bekleme():
    """K‑39: kadro dışı İKİ FARKLI UTC gününde ister, sonuç dışıdır (bekleme yok). 14 gün bekleme sonuçla düşenlere (burada slot düşüşü) aynen kalır."""
    s = hazir_11()
    rows = [satir(i, i, 90 - i) for i in range(1, 9)] + [satir(12, 9), satir(13, 10), satir(14, 11)]          # 9, 10, 11 kadro dışı; 3 aday
    karar, _ = s.degerlendir(kadro(rows, T0 + GUN), T0 + GUN + SAAT)
    assert [k for k in karar if k.tur == "dus"] == [] and [k for k in karar if k.tur == "giris"] == []        # 1. gün: yalnız işaretlenir, düşme yok
    karar2, _ = s.degerlendir(kadro(rows, T0 + 2 * GUN), T0 + 2 * GUN + SAAT)                                  # 2. gün: üçü düşer (SONUÇ DIŞI)
    assert [k.adres for k in karar2 if k.tur == "dus"] == [adr(9), adr(10), adr(11)] and not any(k.sonuc for k in karar2 if k.tur == "dus")
    assert [k.adres for k in karar2 if k.tur == "giris"] == [adr(12), adr(13), adr(14)] and len(s.uyeler) == 11   # K‑44: boş slot doldurma günlük değişiklik sınırına SAYILMAZ → 3 boş slot aynı gün dolar
    assert s.degisiklik["adet"] == 0 and not s.bekleme                                                         # sınır sayacı artmadı; kadro dışı: bekleme YOK
    karar3, _ = s.degerlendir(kadro(rows, T0 + 3 * GUN), T0 + 3 * GUN + SAAT)
    assert [k.adres for k in karar3 if k.tur == "giris"] == []                                                 # zaten dolu
    sd = hazir_11()                                                                                            # sonuçla düşen (slot düşüşü) 14 gün bekler
    kd_ = sd.anlik(T0 + GUN + SAAT, lambda a: 10.0 if a == adr(1) else None)
    assert [(k.adres, k.neden, k.sonuc) for k in kd_] == [(adr(1), "slot_dusus", True)] and sd.bekleme[adr(1)] == T0 + GUN + SAAT + 14 * GUN
    bitis = T0 + GUN + SAAT + 14 * GUN
    assert sd._bekliyor(adr(1), bitis - 1) is True and sd._bekliyor(adr(1), bitis) is False                      # 14 gün: bitiş anında serbest


def test_k45_bos_slot_kor_kirpilinca_yedekten_sirayla_dolar():
    """K‑45 (lider denetimi 06.11): 2. gün 3 üye kadro dışı düşer. İlk 11'deki 2 aday (sıra 10, 11) sahadaki adr(1) ile r=0,9 → bileşen 3 kişi > 2 olur (kor_kirpildi);
    boş slotlar sıradaki Yedek ile dolar: sıra 9 (adr 12, İlk 11), sıra 12 (adr 15) ve 13 (adr 16). Eskiden yalnız sıra ≤ 11 alınırdı → saha 9/11 kalırdı."""
    s = hazir_11()
    rows = [satir(i, i, 90 - i) for i in range(1, 9)] + [satir(12, 9), satir(13, 10), satir(14, 11), satir(15, 12), satir(16, 13), satir(17, 14)]
    adresler = [adr(1), adr(2), adr(13), adr(14)]
    m = [[1, 0.9, 0.9, 0.9], [0.9, 1, 0.0, 0.0], [0.9, 0.0, 1, 0.0], [0.9, 0.0, 0.0, 1]]      # adr1–adr2 zaten bağlı (2 kişi); 13 ya da 14 eklenirse 3 kişi
    kor = {"adresler": adresler, "gun_sayisi": 8, "matris": m}
    s.degerlendir(kadro(rows, T0 + GUN, kor), T0 + GUN + SAAT)                                               # 1. gün: 9, 10, 11 yalnız işaretlenir
    karar, _ = s.degerlendir(kadro(rows, T0 + 2 * GUN, kor), T0 + 2 * GUN + SAAT)
    assert [k.adres for k in karar if k.tur == "dus"] == [adr(9), adr(10), adr(11)]
    assert [(k.adres, k.neden) for k in karar if k.tur == "giris_atlandi"] == [(adr(13), "kor_kirpildi"), (adr(14), "kor_kirpildi")]
    assert [(k.adres, k.neden) for k in karar if k.tur == "giris"] == [(adr(12), "bos_slot"), (adr(15), "bos_slot"), (adr(16), "bos_slot")]
    assert len(s.uyeler) == 11 and adr(17) not in s.uyeler and s.degisiklik["adet"] == 0


def test_k45_uygulanandan_eski_kadro_yok_sayilir_gun_kurallari_iki_kez_calismaz():
    """K‑45: D+1 kadrosu uygulandıktan sonra CDN önbelleğinden D kadrosu yeniden gelirse yok sayılır (gun_kadro ve son_kosu_ms değişmez; sıra/düşme sayaçları ikinci kez artmaz)."""
    s = hazir_11()
    rows_d1 = [satir(i, i, 90 - i) for i in range(1, 11)] + [satir(11, 25)]                                 # adr(11) sıra 25 (> 22: sira_ust +1)
    s.degerlendir(kadro(rows_d1, T0 + GUN), T0 + GUN + SAAT)
    assert s.uyeler[adr(11)]["sira_ust"] == 1
    s.degerlendir(n_kadro(11, T0), T0 + GUN + 2 * SAAT)                                                      # eski (D) kadro geri geldi
    assert s.gun_kadro["kadro"]["kosu_ms"] == T0 + GUN and s.son_kosu_ms == T0 + GUN
    s.degerlendir(kadro(rows_d1, T0 + GUN), T0 + GUN + 3 * SAAT)                                             # D+1 yine: yeni gün sayılmaz
    assert s.uyeler[adr(11)]["sira_ust"] == 1


def test_k44_gunluk_sinir_yalniz_uye_degistirmek_icin_gunde_2_degistirme():
    """K‑44: sahadaki üyeyi değiştirme (histerezis) günde ≤ 2; ertesi gün üçüncü. Boş slot doldurma sınıra girmez (üstteki test)."""
    s = hazir_11()
    rows = [satir(i, i, 90 - i) for i in range(1, 9)] + [satir(9, 12, 40.0), satir(10, 13, 40.0), satir(11, 14, 40.0)] + [satir(12, 9, 80.0), satir(13, 10, 80.0), satir(14, 11, 80.0)]
    k1, _ = s.degerlendir(kadro(rows, T0 + GUN), T0 + GUN + SAAT)
    assert [(k.adres, k.neden) for k in k1 if k.tur == "giris"] == [(adr(12), "degistirme"), (adr(13), "degistirme")] and s.degisiklik["adet"] == 2 and adr(14) not in s.uyeler
    k2, _ = s.degerlendir(kadro(rows, T0 + 2 * GUN), T0 + 2 * GUN + SAAT)
    assert [(k.adres, k.neden) for k in k2 if k.tur == "giris"] == [(adr(14), "degistirme")] and s.degisiklik["adet"] == 1


def test_k39_ayni_utc_gununde_ikinci_kadro_saha_kararini_tetiklemez_ilk_kadro_saklanir_ve_gecis_beklemesi_silinir():
    s = hazir_11()
    ilk = [satir(i, i, 90 - i) for i in range(1, 12)]                                                         # 11 üye de kadroda
    s.degerlendir(kadro(ilk, T0 + GUN + SAAT), T0 + GUN + 2 * SAAT)                                            # günün İLK kadrosu 09:00 UTC (T0 08:00 + 1 sa)
    ikinci = [satir(i, i, 90 - i) for i in range(1, 9)] + [satir(12, 9), satir(13, 10), satir(14, 11)]          # aynı UTC gününde 15:00'te geç/elle ikinci kadro: 9, 10, 11 yok
    karar, _ = s.degerlendir(kadro(ikinci, T0 + GUN + 7 * SAAT), T0 + GUN + 8 * SAAT)
    assert karar == [] and all(adr(i) in s.uyeler for i in (9, 10, 11)) and all(not u.get("disi_gunler") for u in s.uyeler.values())      # ikinci kadro yok sayıldı
    yeni = kd.Saha(RULES, 1000.0, s.to_json())                                                                  # yeniden başlatma: ilk kadro saklı, ikinci yine yok sayılır
    karar2, _ = yeni.degerlendir(kadro(ikinci, T0 + GUN + 7 * SAAT), T0 + GUN + 9 * SAAT)
    assert karar2 == [] and yeni.gun_kadro["kadro"]["kosu_ms"] == T0 + GUN + SAAT
    eski = kd.Saha(RULES, 1000.0, {"bekleme": {"0xf90c9e" + "0" * 34: T0 + 14 * GUN, "0xdddddd" + "0" * 34: T0 + 14 * GUN}, "kurulu": True})
    assert eski.gecis_silinen == ["0xf90c9e" + "0" * 34] and list(eski.bekleme) == ["0xdddddd" + "0" * 34] and eski.to_json()["k39_gecis"] is True      # tek seferlik; diğer bekleme kalır
    assert kd.Saha(RULES, 1000.0, eski.to_json()).gecis_silinen == []                                         # ikinci yüklemede tekrar silinmez


def test_k61_elle_cikarma_ayni_gun_ikinci_kadroda_hemen_uygulanir_slot_yeni_kadrodan_dolar():
    s = hazir_11()
    ilk = [satir(i, i, 90 - i) for i in range(1, 12)]
    s.degerlendir(kadro(ilk, T0 + GUN + SAAT), T0 + GUN + 2 * SAAT)                                             # günün ilk kadrosu
    ikinci = kadro([satir(i, i, 90 - i) for i in range(1, 11)] + [satir(12, 11)], T0 + GUN + 7 * SAAT)        # 11 elle çıkarıldı, yerine 12
    ikinci["cikanlar"] = {adr(11): "elle_cikarildi"}
    karar, _ = s.degerlendir(ikinci, T0 + GUN + 8 * SAAT)
    assert [(k.tur, k.adres, k.neden) for k in karar] == [("dus", adr(11), "elle_cikarildi"), ("giris", adr(12), "bos_slot")]
    assert adr(11) not in s.uyeler and s.bekleme[adr(11)] > T0 + GUN + 8 * SAAT and s.gun_kadro["kadro"]["kosu_ms"] == T0 + GUN + 7 * SAAT
    assert all(not u.get("disi_gunler") for u in s.uyeler.values())                                         # günlük kurallar ikinci kez çalışmadı
    assert s.degerlendir(ikinci, T0 + GUN + 9 * SAAT)[0] == []                                                 # aynı kadro tekrar okununca yeni karar yok


def test_bekleme_suresince_sahaya_donemez_bitince_girer():
    kosu = T0 + 14 * GUN - 2 * SAAT
    s1 = kd.Saha(RULES, 1000.0, {"bekleme": {adr(1): T0 + 14 * GUN}, "kurulu": True})
    karar, _ = s1.degerlendir(n_kadro(2, kosu), T0 + 14 * GUN - 1)
    assert [k.adres for k in karar if k.tur == "giris"] == [adr(2)] and adr(1) not in s1.uyeler               # bekleme bitmedi: yalnız sıra 2 girer
    s2 = kd.Saha(RULES, 1000.0, {"bekleme": {adr(1): T0 + 14 * GUN}, "kurulu": True})
    karar2, _ = s2.degerlendir(n_kadro(2, kosu), T0 + 14 * GUN)
    assert [k.adres for k in karar2 if k.tur == "giris"] == [adr(1), adr(2)]


def test_sonuc_disi_dusen_hemen_donebilir_islem_yok_72_saat():
    s = hazir_11()
    for i in range(1, 11):
        s.islem_gordu(adr(i), T0 + GUN + SAAT)                      # 10 üye yakın zamanda işlem yaptı; adr(11) yapmadı
    karar, _ = s.degerlendir(n_kadro(11, T0 + 4 * GUN), T0 + 4 * GUN)                       # 72 sa+ sonra (giriş T0+1sa → 4 gün)
    dus = [k for k in karar if k.tur == "dus"]
    assert [k.adres for k in dus] == [adr(11)] and dus[0].neden == "islem_yok" and dus[0].sonuc is False and adr(11) not in s.bekleme


def test_sira_iki_gun_ust_uste_22_den_kotu_ve_kadro_disi_ve_kaldirac():
    s = hazir_11()
    def aktif(t):
        for a in s.uyeler:
            s.islem_gordu(a, t)
    rows = lambda sira, k=3.0: kadro([satir(i, i, 90 - i) for i in range(1, 11)] + [satir(11, sira, 10.0, k)], T0 + gun_no * GUN)       # noqa: E731
    gun_no = 1
    aktif(T0 + GUN)
    assert s.degerlendir(rows(23), T0 + GUN + SAAT)[0] == [] and s.uyeler[adr(11)]["sira_ust"] == 1
    gun_no = 2
    aktif(T0 + 2 * GUN)
    assert s.degerlendir(rows(20), T0 + 2 * GUN + SAAT)[0] == [] and s.uyeler[adr(11)]["sira_ust"] == 0       # araya iyi gün girdi: sayaç sıfırlanır
    gun_no = 3
    aktif(T0 + 3 * GUN)
    s.degerlendir(rows(23), T0 + 3 * GUN + SAAT)
    gun_no = 4
    aktif(T0 + 4 * GUN)
    karar, _ = s.degerlendir(rows(25), T0 + 4 * GUN + SAAT)
    assert [(k.adres, k.neden, k.sonuc) for k in karar if k.tur == "dus"] == [(adr(11), "sira", True)]
    s2 = hazir_11()
    k1 = [satir(i, i) for i in range(1, 11)] + [satir(11, 31)]
    assert [k for k in s2.degerlendir(kadro(k1, T0 + GUN), T0 + GUN + SAAT)[0] if k.tur == "dus"] == []                          # sıra 31 > 30: K‑39 bir gün yetmez
    karar2, _ = s2.degerlendir(kadro(k1, T0 + 2 * GUN), T0 + 2 * GUN + SAAT)                                                     # ikinci FARKLI UTC günü: sonuç dışı düşme
    assert [(k.neden, k.sonuc) for k in karar2 if k.tur == "dus"] == [("kadro_disi", False)] and not s2.bekleme
    s3 = hazir_11()
    kar3 = s3.anlik(T0 + SAAT, lambda a: None, kadro([satir(i, i, kald=25.0 if i == 4 else 3.0) for i in range(1, 12)]))
    assert [(k.adres, k.neden, k.sonuc) for k in kar3] == [(adr(4), "kaldirac_ihlali", True)]


def test_slot_dusus_anlik_tam_yuzde_10_dusurur():
    s = hazir_11()
    esik = s.slot * 0.9                                             # 81,818
    assert s.anlik(T0 + 2 * SAAT, lambda a: esik + 0.01) == []
    k = s.anlik(T0 + 2 * SAAT, lambda a: esik if a == adr(3) else s.slot)
    assert [(x.adres, x.neden, x.sonuc) for x in k] == [(adr(3), "slot_dusus", True)] and adr(3) in s.inen and s.bekleme[adr(3)] > T0


def test_inen_24_saat_sonra_kapatilir():
    s = hazir_11()
    s.anlik(T0 + 2 * SAAT, lambda a: 0.0 if a == adr(3) else s.slot)
    assert s.inenleri_kapat(T0 + 2 * SAAT + 23 * SAAT) == []
    k = s.inenleri_kapat(T0 + 2 * SAAT + 24 * SAAT)
    assert [(x.tur, x.adres) for x in k] == [("inen_kapat", adr(3))] and adr(3) not in s.inen


def test_kadro_yok_ya_da_bayat_yeni_giris_yok_dusme_calisir():
    s = hazir_11()
    assert s.degerlendir(None, T0 + SAAT) == ([], "kadro_yok")
    assert s.degerlendir(n_kadro(11, T0), T0 + 37 * SAAT) == ([], "kadro_bayat")                # 37 sa > 36 sa
    assert s.degerlendir(n_kadro(11, T0), T0 + 36 * SAAT)[1] == "ok"                           # tam 36 sa taze
    s.uyeler[adr(3)]["son_islem_ms"] = None
    assert s.anlik(T0 + 40 * SAAT, lambda a: 0.0 if a == adr(3) else s.slot)[0].neden == "slot_dusus"        # anlık düşme kadro olmadan da çalışır


def test_korelasyon_en_fazla_2_kisi_bagli_bilesen_kor_kirpildi():
    """a1–a2 0,8, a2–a3 0,75 → a1,a2,a3 tek bileşen (3 kişi > 2): a3 atlanır; a4 ilişkisiz girer. Kasa 100 → N 4."""
    adresler = [adr(i) for i in range(1, 5)]
    m = [[1, 0.8, 0.1, 0.0], [0.8, 1, 0.75, 0.0], [0.1, 0.75, 1, 0.0], [0.0, 0.0, 0.0, 1]]
    s = kd.Saha(RULES, 100.0)
    karar, _ = s.degerlendir(kadro([satir(i, i) for i in range(1, 5)], kor={"adresler": adresler, "gun_sayisi": 8, "matris": m}), T0 + SAAT)
    assert set(s.uyeler) == {adr(1), adr(2), adr(4)}
    assert [(k.tur, k.adres, k.neden) for k in karar if k.tur == "giris_atlandi"] == [("giris_atlandi", adr(3), "kor_kirpildi")]
    assert kd.kor_bilesen_boyutu(adresler[:3], {"adresler": adresler, "matris": m}, 0.7) == 3 and kd.kor_bilesen_boyutu(adresler[:2], {"adresler": adresler, "matris": m}, 0.7) == 2
    assert kd.kor_bilesen_boyutu(adresler, None, 0.7) == 1 and kd.kor_bilesen_boyutu([adr(9), adr(1)], {"adresler": adresler, "matris": m}, 0.7) == 1       # bilinmeyen çift ilişkisiz
    m_bos = [[1.0, None], [None, 1.0]]
    assert kd.kor_bilesen_boyutu(adresler[:2], {"adresler": adresler[:2], "matris": m_bos}, 0.7) == 2                        # F11: ikisi matriste, r ölçülemedi → benzer (temkinli)


# ================================================================================================ motor uçtan uca
class Saat:
    def __init__(self, ms=T0 + SAAT):
        self.ms = ms

    def __call__(self):
        return self.ms


class SahteHL:
    """info `post`: allMids, l2Book, clearinghouseState, meta, perpDexs, userFillsByTime."""
    def __init__(self, mids=None, asks=None, bids=None, hesap=100_000.0, pozlar=None, rest_dolumlar=None, spot=0.0):
        self.mids = mids or {"BTC": "100", "ETH": "2000", "SOL": "100"}
        self.kitaplar = {"BTC": {"levels": [bids or [{"px": "99.9", "sz": "1000"}], asks or [{"px": "100", "sz": "1000"}]]},
                         "ETH": {"levels": [[{"px": "1999", "sz": "1000"}], [{"px": "2000", "sz": "1000"}]]},
                         "SOL": {"levels": [[{"px": "99.9", "sz": "100000"}], [{"px": "100", "sz": "100000"}]]}}
        self.hesap, self.pozlar, self.rest, self.spot = hesap, pozlar or {}, rest_dolumlar or {}, spot
        self.istekler = []
        self.agent_sahibi = adr(7)
        self.acik_emirler: list = []                       # G-20: openOrders (kendi hesabımız; --kontrol sayar)
        self.hl_saat_ms = None                             # G-20: l2Book `time` (None: gerçek saat; --kontrol saat sapması)

    def __call__(self, y):
        self.istekler.append(y)
        t = y["type"]
        if t == "allMids":
            return self.mids
        if t == "l2Book":
            return {**self.kitaplar[y["coin"]], "time": int(time.time() * 1000) if self.hl_saat_ms is None else self.hl_saat_ms}       # gerçek HL yanıtı `time` (ms) taşır
        if t == "openOrders":
            return list(self.acik_emirler)
        if t == "clearinghouseState":
            return {"marginSummary": {"accountValue": str(self.hesap)}, "assetPositions": [{"position": {"coin": c, "szi": str(sz)}} for c, sz in self.pozlar.get(y["user"], {}).items()]}
        if t == "spotClearinghouseState":
            return {"balances": [{"coin": "USDC", "total": str(self.spot)}, {"coin": "PURR", "total": "999"}]}
        if t == "meta":
            return {"universe": [{"name": "BTC", "szDecimals": 5}, {"name": "ETH", "szDecimals": 4}]}
        if t == "perpDexs":
            return [None]
        if t == "userFillsByTime":
            return self.rest.get(y["user"], [])
        if t == "userRole":                                # G6: gerçek biçim {"role":"agent","data":{"user":<ana hesap>}}
            return {"role": "agent", "data": {"user": self.agent_sahibi}} if self.agent_sahibi else {"role": "user"}
        raise AssertionError(y)


class SahteTG:
    def __init__(self, guncellemeler=None, hata=False):
        self.gonderilen, self.guncellemeler, self.hata = [], list(guncellemeler or []), hata

    def __call__(self, url, yuk):
        if self.hata:
            raise ConnectionError(f"boom {url}")
        if url.endswith("sendMessage"):
            self.gonderilen.append(yuk["text"])
            return {"ok": True}
        sonuc, self.guncellemeler = self.guncellemeler, []
        return {"ok": True, "result": sonuc}


TOKEN, CHAT = "123456789:AAH-gizli-token-DEGERI_xxxxxxxxxxxxxxxxxxx", "4242"


def tg_mesaj(uid, metin, chat=CHAT, kimden=None, tarih=None):
    """Telegram güncellemesi: gerçek biçim (chat.id, from.id, date). `tarih` varsayılan: motor başlangıcından SONRA."""
    return {"update_id": uid, "message": {"chat": {"id": int(chat)}, "from": {"id": int(kimden if kimden is not None else chat)}, "date": time.time() + 60 if tarih is None else tarih, "text": metin}}


def kur(tmp_path, kadro_=None, kasa=1000.0, hl=None, tgp=None, saat=None, kurallar=None):
    rules = {**RULES, "canli_kasa_usd": kasa, **(kurallar or {})}
    hl = hl or SahteHL()
    saat = saat or Saat()
    tgp = tgp or SahteTG()
    tgr = tg.Telegram(TOKEN, CHAT, tgp)
    k = kadro_ if kadro_ is not None else kadro([satir(1, 1)], saat() - SAAT)
    m = mt.Motor(rules, yu.SanalYurutucu(hl, rules), hl, tgr, tmp_path / "durum", tmp_path / "kayit", lambda: k, saat)
    return m, hl, saat, tgp


def olay(kimlik, adres, coin, yon, sz, px, bas_poz, saat, yas_ms=1000):
    return d.Olay(kimlik, adres[:12], adres, saat() - yas_ms, saat(), "userFills", False, f"userFills:{adres}", coin, px, sz, yon, bas_poz)


def kayitlar(tmp_path, tur=None):
    satirlar = []
    for f in sorted((tmp_path / "kayit").glob("*.jsonl")):
        satirlar += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
    return [x for x in satirlar if tur is None or x["olay"] == tur]


def test_uctan_uca_altin_ornek_acilis_azaltma_kapanis(tmp_path):
    """Kasa 1.000 → N 11, slot 90,909 $. Trader hesap 100.000 $, 300 BTC × 100 $ = 30.000 $ açar (oran 0,30): emir 27,27 $, IOC ask 100 → 0,27273 BTC, ücret 27,27 × 0,00045 = 0,01227 $, kayma 0.
    Trader %50 azaltır: 13,636 $ SATIŞ (bid 99,9 → kayma aleyhimize +%0,1); kalanı kapatır: tüm pozisyon reduce-only."""
    m, hl, saat, tgp = kur(tmp_path, kurallar={"canli_telegram_sanal_ozet_dk": 0})          # 0 = eski 15 dk'lık özet davranışı (saatlik özet ayrı testlerde)
    m.baslat()
    assert list(m.saha.uyeler) == [adr(1)] and m.saha.slot == pytest.approx(1000 / 11)
    s1 = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert [(x.eylem, x.karar) for x in s1] == [("ac", "emir")]
    e = kayitlar(tmp_path, "emir")[0]
    assert e["usd_istenen"] == pytest.approx(27.2727, abs=1e-4) and e["yon"] == "B" and e["reduce_only"] is False and e["dolum_px"] == 100.0 and e["kayma_trader"] == 0.0
    assert e["ucret"] == pytest.approx(27.2727 * 0.00045, abs=1e-6) and e["gorme_ms"] == saat() and e["trader_dolum_ms"] == saat() - 1000
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727, abs=1e-6)
    m.piyasa_oku(saat())
    s2 = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 150, 100.0, 300.0, saat))
    e2 = kayitlar(tmp_path, "emir")[1]
    assert [(x.eylem, x.karar) for x in s2] == [("azalt", "emir")] and e2["yon"] == "A" and e2["reduce_only"] is True and e2["usd_istenen"] == pytest.approx(13.6364, abs=1e-4)
    assert e2["dolum_px"] == 99.9 and e2["kayma_trader"] == pytest.approx(0.001)                                      # satışta 99,9 < 100: aleyhimize %0,1
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727 - 13.6364 / 99.9, abs=1e-5)
    s3 = m.olay_isle(olay("a:3", adr(1), "BTC", "A", 150, 100.0, 150.0, saat))
    assert [(x.eylem, x.karar) for x in s3] == [("kapat", "emir")] and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9) and kayitlar(tmp_path, "emir")[2]["reduce_only"] is True
    assert m.sayac["emir"] == 3 and len(m.kayma_trader) == 3
    assert not any("Son " in x and "emir (" in x for x in tgp.gonderilen)                                         # emirler ayrı ayrı gitmez; biriktirilir
    m.emir_ozeti(saat(), zorla=True)
    assert any("Son 15 dakikada 3 emir (sanal · deneme parası)" in x for x in tgp.gonderilen) and any("Yeni trader takibe alındı" in x for x in tgp.gonderilen)


def test_kucuk_acilis_11_dolara_yuvarlanir_ve_trader_hesap_yoksa_atlanir(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 50, 100.0, 0.0, saat))                       # 5.000 $ / 100.000 → 4,55 $ → 11 $
    assert kayitlar(tmp_path, "emir")[0]["usd_istenen"] == 11.0 and kayitlar(tmp_path, "emir")[0]["boyut_neden"] == "min_emir_yuvarlandi"
    m2, hl2, saat2, _ = kur(tmp_path / "b", hl=SahteHL(hesap=0.0))
    m2.baslat()
    s = m2.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat2))
    assert s[0].karar == "atlandi" and s[0].neden == "trader_hesap_yok" and m2.sayac["emir"] == 0


def test_trader_ters_donus_kapanis_ve_yeni_acilis_iki_emir(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))                      # long 300
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 500, 100.0, 300.0, saat))                # satış 500 → short 200 (kapat + aç)
    assert [(x.eylem, x.karar) for x in s] == [("kapat", "emir"), ("ac", "emir")]
    assert m.hesap.sz(adr(1), "BTC") < 0 and abs(m.hesap.sz(adr(1), "BTC")) == pytest.approx(18.1818 / 99.9, abs=1e-4)        # 20.000 $ / 100.000 × 90,909 = 18,18 $ short, bid 99,9'dan satıldı


def test_inen_trader_acilis_engel_kapanis_serbest_ve_saha_disi_trader_yok_sayilir(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.saha.anlik(saat(), lambda a: 0.0)                                                      # slot düşüşü: inene geçir
    assert adr(1) in m.saha.inen and adr(1) not in m.saha.uyeler
    s_ac = m.olay_isle(olay("a:2", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat))
    assert s_ac[0].karar == "engel" and s_ac[0].neden == "inen_trader"
    s_kapat = m.olay_isle(olay("a:3", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert [(x.eylem, x.karar) for x in s_kapat] == [("kapat", "emir")] and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)
    assert m.olay_isle(olay("a:4", adr(99), "BTC", "B", 300, 100.0, 0.0, saat)) == []        # sahada olmayan adres: emir yok


def test_risk_coin_tavani_engel_gunluk_kayip_acilis_engel_kapanis_serbest(tmp_path):
    kd_ = kadro([satir(1, 1), satir(2, 2)], T0)
    m, hl, saat, _ = kur(tmp_path, kd_)
    m.baslat()
    m.hesap.uygula(adr(2), "BTC", "B", 2.9, 100.0, 0.0, 1)                                    # adr(2) BTC'de 290 $ brüt: coin tavanı 300 → izin 10 < 11
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert s[0].karar == "engel" and s[0].neden == "coin_tavani"
    m.risk.bayrak("gunluk_kayip", True)
    s2 = m.olay_isle(olay("a:2", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat))
    assert s2[0].karar == "engel" and s2[0].neden == "gunluk_kayip"
    m.risk.bayrak("gunluk_kayip", False)
    m.olay_isle(olay("a:3", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat))                       # 20.000 $ → 18,18 $
    m.risk.bayrak("gunluk_kayip", True)
    assert m.olay_isle(olay("a:4", adr(1), "ETH", "A", 10, 2000.0, 10.0, saat))[0].karar == "emir"        # kapanış serbest
    assert any("coin_tavani" in x.get("neden", "") for x in kayitlar(tmp_path, "emir_yok"))


def test_kapat_komutu_hepsini_kapatir_dur_dosyasi_yeniden_baslatma_engeli(tmp_path):
    """Eski `/dur` davranışı `/kapat` oldu (kullanıcı kararı 2026-11-05): test aynı şeyi `/kapat` ile doğrular, zayıflatılmadı."""
    guncelleme = tg_mesaj(5, "/kapat")
    yabanci = tg_mesaj(4, "/kapat", chat=999)
    m, hl, saat, tgp = kur(tmp_path, tgp=SahteTG([yabanci]))
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dakika()
    assert not m.dur_istendi and not (tmp_path / "durum" / "DUR").exists()                    # yabancı sohbetten /kapat kabul edilmedi
    tgp.guncellemeler.append(guncelleme)
    m.dakika()
    assert m.dur_istendi and (tmp_path / "durum" / "DUR").exists() and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)
    assert any(x["olay"] == "dur" and x["neden"] == "komut" for x in kayitlar(tmp_path)) and any(x.startswith("🛑 DUR:") for x in tgp.gonderilen)
    m2, *_ = kur(tmp_path)
    with pytest.raises(mt.KipHatasi):
        m2.baslat()                                                                           # DUR varken başlamaz


def test_elle_dur_artirma_engeller_azaltma_serbest_yeniden_kurulunca_korunur_baska_bayrak_silmez(tmp_path):
    """Opus denetimi: mevcut coinde `artir` engellenir, kısmi `azalt` serbest, risk.json'dan yeni Motor kurulunca duraklatma korunur, başka bayrağın açılıp kapanması `elle_dur`'u silmez; `/devam` yanıtı başka engeli söyler."""
    m, hl, saat, tgp = kur(tmp_path, tgp=SahteTG([]))
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m._komutlar(["/dur"])
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "B", 100, 100.0, 300.0, saat))                      # mevcut coinde artırma
    assert s[0].karar == "engel" and s[0].neden == "elle_dur"
    onceki = m.hesap.sz(adr(1), "BTC")
    s2 = m.olay_isle(olay("a:3", adr(1), "BTC", "A", 150, 100.0, 300.0, saat))                     # kısmi azaltma (trader 300 → 150)
    assert s2[0].karar == "emir" and m.hesap.sz(adr(1), "BTC") < onceki
    m.risk.bayrak("mutabakat", True)
    m.risk.bayrak("mutabakat", False)
    assert m.risk.acilis_durdu["elle_dur"]                                                         # başka bayrak elle_dur'u silmedi
    m.durum_yaz()
    m2, *_ = kur(tmp_path)
    assert m2.risk.acilis_durdu.get("elle_dur") is True                                           # yeni Motor risk.json'dan yükledi
    m.risk.bayrak("gunluk_kayip", True)
    m._komutlar(["/devam"])
    assert any("hâlâ kapalı: gunluk_kayip" in x for x in tgp.gonderilen)                           # yanıltmaz


def test_dur_komutu_yalniz_yeni_giris_ve_artirmayi_durdurur_cikis_serbest_devam_acar(tmp_path):
    """Yeni `/dur`: açılış/artırma engellenir (`elle_dur`), kapanış serbest, motor çalışır, DUR dosyası YAZILMAZ; `/devam` (= `/baslat`) açar; kalıcıdır. (Komutlar `_komutlar` ile verilir:
    dakikalık trader pozisyon senkronu sahte HL'de trader pozisyonu görmediği için açık kopyayı kendisi kapatırdı.)"""
    m, hl, saat, tgp = kur(tmp_path, tgp=SahteTG([]))
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))                          # açık pozisyon var
    assert m.hesap.sz(adr(1), "BTC") > 0
    m._komutlar(["/dur"])
    assert m.risk.acilis_durdu["elle_dur"] and not m.dur_istendi and not m.risk.dur and not (tmp_path / "durum" / "DUR").exists()
    assert any("duraklatıldı" in x for x in tgp.gonderilen) and kayitlar(tmp_path, "elle_dur")
    s = m.olay_isle(olay("a:2", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat))
    assert s[0].karar == "engel" and s[0].neden == "elle_dur"                                  # yeni açılış engelli
    assert "Yeni işlem duraklatıldı" in m.durum_metni()
    assert json.loads((tmp_path / "durum" / "risk.json").read_text(encoding="utf-8"))["acilis_durdu"]["elle_dur"] is True       # kalıcı
    s2 = m.olay_isle(olay("a:3", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert s2[0].karar == "emir" and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)  # kapanış serbest
    m._komutlar(["/devam"])
    assert not m.risk.acilis_durdu["elle_dur"] and kayitlar(tmp_path, "elle_devam")
    assert m.olay_isle(olay("a:4", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat))[0].karar == "emir"
    m._komutlar(["/dur"])
    m._komutlar(["/baslat"])
    assert not m.risk.acilis_durdu["elle_dur"]                                                  # /baslat = /devam


def test_dur_ve_devam_telegramdan_gelir(tmp_path):
    tgp = SahteTG([])
    m, hl, saat, tgp = kur(tmp_path, tgp=tgp)
    m.baslat()
    tgp.guncellemeler.append(tg_mesaj(10, "/dur"))
    m.dakika()
    assert m.risk.acilis_durdu["elle_dur"]
    tgp.guncellemeler.append(tg_mesaj(11, "/devam"))
    m.dakika()
    assert not m.risk.acilis_durdu["elle_dur"]


def test_devam_kapat_sonrasi_motoru_acmaz(tmp_path):
    m, hl, saat, tgp = kur(tmp_path, tgp=SahteTG([]))
    m.baslat()
    m.dur_tetikle("komut")
    tgp.guncellemeler.append(tg_mesaj(20, "/devam"))
    m.dakika()
    assert m.risk.dur and any("Motor kapalı" in x for x in tgp.gonderilen)


def test_zirveden_20_dusus_dur_ve_gunluk_kayip_alarmi(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.dakika()                                                                                # gün başı özsermaye 1.000 kaydolur
    m.hesap.realize["x"] = -50.0                                                              # −%5: günlük kayıp
    m.dakika()
    assert m.risk.acilis_durdu["gunluk_kayip"] and any("günlük kayıp" in x for x in tgp.gonderilen) and not m.dur_istendi
    m.hesap.realize["x"] = -200.0                                                             # zirve 1.000 → 800 = −%20
    m.dakika()
    assert m.dur_istendi and m.risk.dur and (tmp_path / "durum" / "DUR").exists()


def test_yeniden_baslatma_cift_emir_yok_durum_kaldigi_yerden(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    o = olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat)
    assert m.olay_isle(o)[0].karar == "emir"
    m.durum_yaz()
    m2, hl2, saat2, _ = kur(tmp_path, saat=saat)
    m2.baslat()
    assert m2.olay_isle(o) == []                                                              # aynı dolum kimliği: ikinci emir YOK
    assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727, abs=1e-6) and list(m2.saha.uyeler) == [adr(1)] and m2.poz_tr[adr(1)]["BTC"] == 300
    assert m2.sayac["emir"] == 0 and len(kayitlar(tmp_path, "emir")) == 1


def test_kacan_dolum_rest_ile_tamamlanir_gec_acilis_emir_uretmez(tmp_path):
    """K‑37 §5: AÇILIŞ olay yaşı > 120 sn ise emir YOK (`gec_acilis`): 30 sn eski BTC açılışı işlenir (REST kaynaklı → `gec_goruldu`); 5 dk eski SOL ve 90 dk eski ETH açılışı emir ÜRETMEZ
    (yalnız trader pozisyon izleyicisi güncellenir)."""
    saat = Saat()
    taze = {"tid": 11, "time": saat() - 30_000, "coin": "BTC", "px": "100", "sz": "300", "side": "B", "startPosition": "0"}
    bes_dk = {"tid": 12, "time": saat() - 5 * 60_000, "coin": "SOL", "px": "100", "sz": "300", "side": "B", "startPosition": "0"}
    eski = {"tid": 10, "time": saat() - 90 * 60_000, "coin": "ETH", "px": "2000", "sz": "10", "side": "B", "startPosition": "0"}
    hl = SahteHL(rest_dolumlar={adr(1): [eski, bes_dk, taze]})
    m, _, _, _ = kur(tmp_path, hl=hl, saat=saat)
    m.baslat()
    assert m.kacanlari_tamamla(saat() - 3 * SAAT) == 3                                         # üçü de bir Sonuç döner: 1 emir + 2 atlandı
    e = kayitlar(tmp_path, "emir")
    assert len(e) == 1 and e[0]["coin"] == "BTC" and e[0]["gec_goruldu"] is True and e[0]["kaynak"] == "rest" and m.sayac["gec_goruldu"] == 3
    assert m.sayac["gec_acilis"] == 2 and m.neden_say["gec_acilis"] == 2 and m.hesap.sz(adr(1), "SOL") == 0.0 and m.hesap.sz(adr(1), "ETH") == 0.0
    assert m.poz_tr[adr(1)]["ETH"] == 10 and m.poz_tr[adr(1)]["SOL"] == 300                    # izleyici güncel


def test_gec_gelen_kapanis_yasa_bakmadan_islenir_ve_kuyruk_beklemesi_yasa_dahil(tmp_path):
    """K‑37 §5/§6: kapanış 100 dk eski olsa da kapatılır; açılış kuyrukta bekleyip 121 sn'ye ulaşırsa (işleme anı − trader zamanı) emir yok."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.sz(adr(1), "BTC") > 0
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat, yas_ms=100 * 60_000))
    assert [(x.eylem, x.karar) for x in s] == [("kapat", "emir")] and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)
    assert m.olay_isle(olay("a:3", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat, yas_ms=121_000))[0].neden == "gec_acilis"
    assert m.olay_isle(olay("a:4", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat, yas_ms=119_000))[0].karar == "emir"


def test_mutabakat_sanal_mark_eskiyse_alarm_ve_yeni_acilis_durur_sonra_duzelir(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    saat.ms += 10 * 60_000                                                                    # mark 10 dk eski (sınır 300 sn): ama dakika() allMids'i yeniler
    m.mark_ms["BTC"] = saat() - 10 * 60_000
    m._son.pop("mutabakat", None)
    m._mutabakat(saat())
    assert m.risk.acilis_durdu["mutabakat"] and any("mutabakat" in x for x in tgp.gonderilen)
    m.mark_ms["BTC"] = saat()
    m._son.pop("mutabakat", None)
    m._mutabakat(saat())
    assert not m.risk.acilis_durdu["mutabakat"]


def test_telegram_token_kayda_ve_hatalara_yazilmaz_ve_hata_motoru_durdurmaz(tmp_path):
    m, hl, saat, _ = kur(tmp_path, tgp=SahteTG(hata=True))
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))                       # Telegram hatasında emir yine işlendi
    assert m.tg.hata_sayisi >= 1 and m.sayac["emir"] == 1
    for f in (tmp_path / "kayit").glob("*") if (tmp_path / "kayit").exists() else []:
        assert TOKEN not in f.read_text(encoding="utf-8") and "AAH-gizli" not in f.read_text(encoding="utf-8")
    for f in (tmp_path / "durum").glob("*.json"):
        assert TOKEN not in f.read_text(encoding="utf-8")
    kapali = tg.Telegram("", "", ortam={})
    assert kapali.acik is False and kapali.gonder("x") is False and kapali.komutlari_al() == []


def test_telegram_komutlari_yalniz_yapilandirilmis_sohbetten_ve_biçim():
    t = tg.Telegram(TOKEN, CHAT, SahteTG([tg_mesaj(1, "/durum@sg_bot"), tg_mesaj(2, "/dur", chat=7), tg_mesaj(3, "merhaba")]))
    assert t.komutlari_al() == ["/durum"] and t.offset == 4
    acik = [{"coin": "BTC", "sz": 0.5, "usd": 1234.0, "kz_usd": 12.34}, {"coin": "ETH", "sz": -2.0, "usd": 80.0, "kz_usd": -1.5}]
    assert tg.msg_gunluk("sanal", 1000, 1012.5, 1000.0, 58, 9, 11, acik, -0.12) == (
        "☀️ Günaydın! Dünün sonucu (sanal · deneme parası)\n━━━━━━━━━━━━━━\n📈 Son 24 saat: +12,50 $ (+%1,25)\n💰 Kasa şimdi: 1.012,50 $ (başlangıç 1.000 $)\n🏁 Başlangıçtan beri: +%1,25\n━━━━━━━━━━━━━━\n"
        "🧾 Dün 58 emir verildi · 👥 takipte 9/11 trader\n💸 Funding (sanal): −0,12 $\n📌 Açık pozisyonlar (2):\n🟩 BTC · 1.234 $ · uzun · +12,34 $\n🟥 ETH · 80 $ · kısa · −1,50 $")
    assert tg.kisa(adr(255)) == "0x000000…"


# ================================================================================================ kip güvencesi
ANAHTAR = {"HL_API_CUZDAN_ANAHTARI": "k", "HL_HESAP_ADRESI": "0x1"}


def test_kip_varsayilan_sanal_gercek_yalniz_ortam_anahtar_ve_actions_degil():
    """G4: gerçek kip YALNIZ `CANLI_KIP=gercek` ortamıyla (eski `kurallar.yaml canli_kip: gercek` senaryosu ortama taşındı; yaml artık yalnız sanal)."""
    assert mt.kip_belirle(RULES, None, {}) == "sanal" and str(RULES["canli_kip"]) == "sanal"
    with pytest.raises(mt.KipHatasi):
        mt.kip_belirle(RULES, "gercek", dict(ANAHTAR))                                                          # ortamda CANLI_KIP yok: gercek istenemez
    with pytest.raises(yu.AnahtarYok):
        mt.kip_belirle(RULES, None, {"CANLI_KIP": "gercek"})
    assert mt.kip_belirle(RULES, None, {**ANAHTAR, "CANLI_KIP": "gercek"}) == "gercek"
    assert mt.kip_belirle(RULES, "sanal", {**ANAHTAR, "CANLI_KIP": "gercek"}) == "sanal"                      # açık --kip sanal kazanır
    with pytest.raises(mt.KipHatasi):
        mt.kip_belirle(RULES, None, {**ANAHTAR, "CANLI_KIP": "gercek", "GITHUB_ACTIONS": "true"})              # Actions'ta ASLA
    with pytest.raises(mt.KipHatasi):
        mt.kip_belirle(RULES, None, {"CANLI_KIP": "sanal", "GITHUB_ACTIONS": "true"})                           # Actions + herhangi CANLI_* → ret
    with pytest.raises(mt.KipHatasi):
        mt.kip_belirle(RULES, None, {"CANLI_KASA_USD": "300", "GITHUB_ACTIONS": "true"})
    assert mt.kip_belirle(RULES, None, {"GITHUB_ACTIONS": "true"}) == "sanal"                                   # CANLI_* yoksa sanal vardiya aynen
    with pytest.raises(mt.KipHatasi):
        mt.kip_belirle(RULES, "x", {})
    with pytest.raises(mt.KipHatasi):
        mt.kip_belirle(RULES, None, {"CANLI_KIP": "x"})


def test_kasa_siniri_asan_kasada_motor_baslamaz(tmp_path):
    m, *_ = kur(tmp_path, kasa=1000.0)
    m.rules = {**m.rules, "canli_kasa_ust_usd": 900}
    m.kasa = 1000.0
    with pytest.raises(mt.KipHatasi):
        m.baslat()
    r = __import__("copytrade.canli.risk", fromlist=["Risk"]).Risk(RULES, 1000.0)
    assert r.kasa_siniri_asildi(1500.0) is True


def test_kontrol_emir_gondermez_rapor_yazar(tmp_path):
    hl = SahteHL()
    cagri = []
    rapor = mt.kontrol(RULES, "sanal", hl, lambda: n_kadro(3, int(__import__("time").time() * 1000)), tg.Telegram(TOKEN, CHAT, SahteTG()), ortam={})
    assert rapor["emir_gonderildi"] is False and rapor["hl_baglanti"] is True and rapor["kadro"]["var"] and rapor["kadro"]["taze"] and rapor["anahtar"] is False and rapor["tamam"] is True
    assert all(i["type"] in ("meta",) for i in hl.istekler) and not cagri                    # yalnız meta okundu (anahtarsız): l2Book / emir yok
    gercek = mt.kontrol(RULES, "gercek", hl, lambda: None, tg.Telegram("", "", ortam={}), ortam={})
    assert gercek["tamam"] is False and gercek["kadro"]["var"] is False
    assert rapor["kasa_kaynagi"] == "yaml" and gercek["kasa_kaynagi"] == "yaml" and gercek["kasa_siniri_ok"] is False and "CANLI_KASA_USD" in gercek["kasa_hata"]      # G4: gerçek kip + ortam kasası yok
    ok = mt.kontrol(RULES, "gercek", hl, lambda: n_kadro(3), tg.Telegram(TOKEN, CHAT, SahteTG()), ortam={"HL_API_CUZDAN_ANAHTARI": "gizli-anahtar-xyz", "HL_HESAP_ADRESI": adr(7), "CANLI_KASA_USD": "1000"}, turet=lambda k: adr(9))
    assert ok["kasa_kaynagi"] == "ortam" and ok["bakiye_usd"] == 100_000.0 and ok["hl_hesap_degeri"] == 100_000.0 and ok["etkin_kasa_usd"] == 1000.0 and "gizli-anahtar-xyz" not in json.dumps(ok)                  # anahtar rapora yazılmaz
    assert ok["agent_dogrulandi"] is True and ok["hl_deger_siniri_ok"] is False and ok["tamam"] is False          # G6: HL değeri 100.000 $ > 1.000 $ (K‑22) → ret


# ================================================================================================ dayanıklılık (WS)
class SahteWS:
    def __init__(self, mesajlar, sonra="kes"):
        self.mesajlar, self.gonderilen, self.sonra = list(mesajlar), [], sonra

    async def send(self, ham):
        self.gonderilen.append(json.loads(ham))

    async def recv(self):
        if self.mesajlar:
            return json.dumps(self.mesajlar.pop(0))
        if self.sonra == "kes":
            raise ConnectionError("kapandı")
        await asyncio.sleep(3600)

    async def close(self):
        return None


def userfills(adres, tid, t, side="B", sz="300", start="0", px="100", coin="BTC", snapshot=False):
    return {"channel": "userFills", "data": {"isSnapshot": snapshot, "user": adres, "fills": [{"coin": coin, "px": px, "sz": sz, "side": side, "time": t, "tid": tid, "startPosition": start}]}}


def dinleyici_calistir(tmp_path, mesaj_listeleri, post):
    saat = Saat(1_000_000)
    ws = [SahteWS(m) for m in mesaj_listeleri]
    sira = {"i": 0}

    async def baglan():
        if sira["i"] >= len(ws):
            ws.append(SahteWS([], "bekle"))
        w = ws[sira["i"]]
        sira["i"] += 1
        return w
    kuyruk: asyncio.Queue = asyncio.Queue()
    din = mt.CanliDinleyici(kuyruk, [d.Izlenen(adr(1)[:12], adr(1))], ["BTC"], baglan, post, tmp_path, d.Ayar(rest_dolum_ara_sn=0.0, rest_poz_ara_sn=0.0, sure_sn=0.5, geri_cekilme_ilk_sn=0.01,
                           geri_cekilme_max_sn=0.02), saat.__call__ if False else (lambda: saat.ms))
    asyncio.run(din.calis())
    olaylar = []
    while not kuyruk.empty():
        olaylar.append(kuyruk.get_nowait())
    return olaylar, ws


def test_ws_olayi_motor_kuyruguna_adresle_ve_snapshot_canli_degil(tmp_path):
    olaylar, ws = dinleyici_calistir(tmp_path, [[userfills(adr(1), 1, 1_000_000), userfills(adr(1), 2, 999_000, snapshot=True)]], lambda y: [])
    assert [(o.adres, o.kimlik, canli) for o, canli in olaylar] == [(adr(1), f"{adr(1)}:1", True), (adr(1), f"{adr(1)}:2", False)]


def test_ws_kopmasi_sonrasi_kacan_dolum_rest_dolgusuyla_kuyruga_gelir(tmp_path):
    """1. bağlantı tid 1'i verir ve kopar; kopukken tid 2 gerçekleşti (REST'te var); yeniden bağlanınca dolgu REST ile tid 2'yi `dolgu` olarak motora verir (adres takma addan çözülür)."""
    def post(y):
        if y["type"] == "userFillsByTime":
            return [{"coin": "BTC", "px": "100", "sz": "300", "side": "B", "time": 1_000_000, "tid": 2, "startPosition": "300"}]
        return []
    olaylar, _ = dinleyici_calistir(tmp_path, [[userfills(adr(1), 1, 1_000_000)], []], post)
    kaynaklar = {o.kimlik or "dolgu": (o.kaynak, o.adres) for o, _ in olaylar}
    assert (("userFills", adr(1)) in kaynaklar.values()) and (("dolgu", adr(1)) in kaynaklar.values())


def test_motor_tuketici_kuyruktan_emir_uretir(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()

    async def kos():
        kuyruk, durdur = asyncio.Queue(), asyncio.Event()
        kuyruk.put_nowait((olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat), True))
        gorev = asyncio.create_task(mt._tuketici(m, kuyruk, durdur))
        son = time.monotonic() + 10.0                                       # S-24: sabit uyku yerine koşul beklemesi (zaman aşımı 10 sn; yavaş makinede de belirleyici)
        while m.sayac["emir"] < 1 and time.monotonic() < son and not gorev.done():
            await asyncio.sleep(0.01)
        durdur.set()
        await gorev
    asyncio.run(kos())
    assert m.sayac["emir"] == 1


def test_sdk_hatasi_ve_red_motoru_cokertmez_kayit_alir(tmp_path):
    class Bozuk:
        kip = "gercek"

        def hazirla(self, coin):
            return None

        def emir(self, coin, yon, usd, reduce_only=False, acik_sz=None, bant=None, cloid=None):          # GercekYurutucu: emir çağrısında ConnectionError → "belirsiz" (G-1)
            return yu.Dolum(coin, yon, usd, reduce_only=reduce_only, durum="belirsiz", neden="sdk_hatasi: ConnectionError")
    hl = SahteHL()
    m = mt.Motor(RULES, Bozuk(), hl, tg.Telegram("", "", ortam={}), tmp_path / "durum", tmp_path / "kayit", lambda: kadro([satir(1, 1)], T0), Saat())
    m.baslat()
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, Saat()))
    assert s[0].karar == "belirsiz" and "sdk_hatasi" in s[0].neden and m.hesap.sz(adr(1), "BTC") == 0.0 and kayitlar(tmp_path, "emir")[0]["red_neden"].startswith("sdk_hatasi")
    # G-1: "red" sayılmaz; niyet AÇIK kalır (sonuç satırı yok) ve `hesap.belirsiz`te bekler → orderStatus(cloid) ile çözülür; çözülene dek yeni açılış durur
    assert kayitlar(tmp_path, "emir")[0]["durum"] == "belirsiz" and m.sayac["red"] == 0 and m.sayac["belirsiz"] == 1
    assert [n["cloid"] for n in m.niyet.sonucsuz()] == list(m.hesap.belirsiz) and len(m.hesap.belirsiz) == 1 and m.risk.acilis_durdu["belirsiz"] is True


def test_eylem_belirle_tablosu():
    e = mt.eylem_belirle
    assert e(0, 10, 0) == ["ac"] and e(10, 15, 5) == ["artir"] and e(10, 15, 0) == ["ac"] and e(10, 5, 4) == ["azalt"] and e(10, 5, 0) == []
    assert e(10, 0, 4) == ["kapat"] and e(10, 0, 0) == [] and e(10, -5, 4) == ["kapat", "ac"] and e(10, -5, 0) == ["ac"] and e(-10, -4, -3) == ["azalt"]


# ================================================================================================ kod taraması
def test_repoda_anahtar_ya_da_telegram_tokeni_yok():
    dosyalar = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    ozel_anahtar = re.compile(r"(?i)(private[_ ]?key|HL_API_CUZDAN_ANAHTARI)\s*[=:]\s*['\"]?0x[0-9a-f]{64}")
    ham_hex = re.compile(r"\b0x[0-9a-fA-F]{64}\b")
    bot_tokeni = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")
    for f in dosyalar:
        if not f.endswith((".py", ".yml", ".yaml", ".md", ".sh", ".txt", ".service", ".json")):
            continue
        yol = ROOT / f
        if not yol.is_file() or yol.stat().st_size > 2_000_000 or "tests/fixtures" in f:
            continue
        metin = yol.read_text(encoding="utf-8", errors="ignore")
        assert not ozel_anahtar.search(metin), f
        assert not bot_tokeni.search(metin), f
        if f.startswith("copytrade/canli/") or f.startswith("deploy/") or f.endswith(".service"):
            assert not ham_hex.search(metin), f


# ================================================================================================ ek: kilit, mark (HIP-3), senkron, eşzamanlılık, Telegram arka planı
def test_kilit_baska_vardiya_aktifse_baslamaz_birakilmis_ya_da_eskiyse_devralir(tmp_path):
    saat = Saat()
    m1, *_ = kur(tmp_path, saat=saat)
    m1.vardiya_id = "A"
    m1.baslat()                                                            # kilit: A, nabız şimdi
    m2, *_ = kur(tmp_path, saat=saat)
    m2.vardiya_id = "B"
    with pytest.raises(mt.KipHatasi):
        m2.baslat()                                                        # A 20 dk içinde nabız attı
    saat.ms += 21 * 60_000                                                 # A'nın nabzı eskidi (çökme/zaman aşımı)
    m3, *_ = kur(tmp_path, saat=saat)
    m3.vardiya_id = "B"
    m3.baslat()
    assert json.loads((tmp_path / "durum" / "kilit.json").read_text())["vardiya"] == "B"
    m3.kilit_yaz(True)                                                     # temiz kapanış: bırakıldı
    m4, *_ = kur(tmp_path, saat=saat)
    m4.vardiya_id = "C"
    m4.baslat()                                                            # bırakılmış kilit hemen devralınır


def test_mark_ana_dex_ve_hip3_dex_allmids_ile_okunur(tmp_path):
    class HL(SahteHL):
        def __call__(self, y):
            if y["type"] == "perpDexs":
                return [None, {"name": "xyz"}]
            if y["type"] == "allMids":
                return {"xyz:AAPL": "250.5"} if y.get("dex") == "xyz" else {"BTC": "100", "ETH": "2000"}
            return super().__call__(y)
    m, *_ = kur(tmp_path, hl=HL())
    m.piyasa_oku(T0)
    assert m.marks == {"BTC": 100.0, "ETH": 2000.0, "xyz:AAPL": 250.5}


def test_trader_pozisyon_senkronu_izleyiciyi_rest_gercegine_esitler(tmp_path):
    hl = SahteHL(pozlar={adr(1): {"BTC": 12.5}})
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()
    assert m.poz_tr[adr(1)] == {"BTC": 12.5}
    m.poz_tr[adr(1)] = {"BTC": 10.0, "ETH": 3.0}                           # WS'te kaçan dolum: izleyici gerçekten saptı
    assert m.senkron_uygula(m.senkron_oku()) == 1 and m.poz_tr[adr(1)] == {"BTC": 12.5}
    assert any(x["olay"] == "poz_senkron" and x["fark"]["BTC"] == [10.0, 12.5] for x in kayitlar(tmp_path))
    assert m.senkron_uygula(m.senkron_oku()) == 0                          # tutarlıyken düzeltme yok


def test_olay_isleme_ile_dakikalik_bakim_ayni_anda_calisabilir_kilitli(tmp_path):
    import threading
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    hatalar = []

    def olaylar():
        try:
            for i in range(30):
                m.olay_isle(olay(f"a:{i}", adr(1), "BTC" if i % 2 == 0 else "ETH", "B", 5, 100.0 if i % 2 == 0 else 2000.0, 0.0, saat))
        except Exception as e:                                             # noqa: BLE001
            hatalar.append(e)

    def bakim():
        try:
            for _ in range(15):
                m.dakika()
        except Exception as e:                                             # noqa: BLE001
            hatalar.append(e)
    t = [threading.Thread(target=olaylar), threading.Thread(target=bakim)]
    [x.start() for x in t]
    [x.join() for x in t]
    assert hatalar == [] and m.sayac["emir"] >= 1


def test_telegram_arka_planda_gonderilir_emir_hatti_beklemez():
    import threading
    import time as _t
    beklet = threading.Event()
    gonderildi = []

    def yavas(url, yuk):
        beklet.wait(2.0)
        gonderildi.append(yuk["text"])
        return {"ok": True}
    t = tg.Telegram(TOKEN, CHAT, yavas, arka_plan=True)
    bas = _t.monotonic()
    assert t.gonder("merhaba") is True
    assert _t.monotonic() - bas < 0.5 and gonderildi == []                  # çağıran beklemedi
    beklet.set()
    t._havuz.shutdown(wait=True)
    assert gonderildi == ["merhaba"]


def test_rest_post_agirliklar_ve_ortak_hiz_siniri():
    """Motor REST çağrıları `PublicClient.info`'dan, istek türüne göre ağırlıkla geçer (clearinghouseState 2, userFillsByTime 20, bilinmeyen 20); sınırlayıcı iş parçacığı güvenli."""
    cagrilar = []

    class Sahte:
        def info(self, yuk, weight=20):
            cagrilar.append((yuk["type"], weight))
            return {}
    post = mt.rest_post_olustur(RULES, Sahte())
    for t in ("clearinghouseState", "allMids", "l2Book", "userFillsByTime", "meta", "bilinmeyen"):
        post({"type": t})
    assert cagrilar == [("clearinghouseState", 2), ("allMids", 2), ("l2Book", 2), ("userFillsByTime", 20), ("meta", 20), ("bilinmeyen", 20)]
    lim = mt.GuvenliLimiter(limit=100, sleep=lambda s: None)
    lim.acquire(60)
    lim.acquire(40)
    assert lim.weight_used == 100 and isinstance(lim._kilit, type(__import__("threading").Lock()))
    assert RULES["canli_api_agirlik_dk"] <= 1100                                              # radar_api_agirlik_dk (1.100) ve HL IP sınırı (1.200) altında


# ================================================================================================ K‑35 (lider denetimi)
def test_k35_motor_slot_toplam_tavani_uc_coin_slot_tavani_sayaci(tmp_path):
    """Slot 90,909 → toplam tavan 272,727 $. Trader hesap 100.000 $: BTC 150.000 $ → 136,36 $ (tam); ETH 160.000 $ → hedef 145,45, kalan 136,36 → 136,36 $ (`slot_tavani`); SOL 50.000 $ → kalan 0 → emir YOK (`slot_tavani`)."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.piyasa_oku(saat())
    s1 = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 1500, 100.0, 0.0, saat))
    s2 = m.olay_isle(olay("a:2", adr(1), "ETH", "B", 80, 2000.0, 0.0, saat))
    s3 = m.olay_isle(olay("a:3", adr(1), "SOL", "B", 500, 100.0, 0.0, saat))
    e = kayitlar(tmp_path, "emir")
    assert [round(x["usd_istenen"], 2) for x in e] == [136.36, 136.36] and [x["boyut_neden"] for x in e] == ["tamam", "slot_tavani"]
    assert s3[0].karar == "atlandi" and s3[0].neden == "slot_tavani" and s1[0].karar == s2[0].karar == "emir"
    assert m.neden_say["slot_tavani"] == 2 and m.ozet()["slot_tavani"] == 2 and m.ozet()["marj_yok"] == 0
    toplam = sum(abs(p.sz) * m.marks[c] for c, p in m.hesap.poz[adr(1)].items())
    assert toplam == pytest.approx(272.7273, abs=1e-3)                                  # tüm coinlerde toplam 3 × slot


def test_k35_marj_kirp_altin_ornek():
    """Özsermaye 100, açık başlangıç marjı toplamı 90 (270 $ nosyonel / 3) → serbest 10 → yeni nosyonel en çok 30 $. 60 $ istenir → 30 $ (`marj_yok`); marj 99,5 → serbest 0,5 → 1,5 $ < 11 → 0."""
    from copytrade.canli.risk import Risk
    r = Risk(RULES, 1000.0)
    assert r.marj_kirp(60.0, 90.0, 100.0) == (pytest.approx(30.0), "marj_yok")
    assert r.marj_kirp(60.0, 99.5, 100.0) == (0.0, "marj_yok")
    assert r.marj_kirp(25.0, 90.0, 100.0) == (25.0, "")                                # sınır altı: kırpma yok
    assert r.marj_kirp(30.0, 90.0, 100.0) == (30.0, "")                                # tam sınır geçer
    assert r.marj_kirp(10.0, 120.0, 100.0) == (0.0, "marj_yok")                       # marj özsermayeyi aşmış: serbest 0


def test_k35_motor_marj_yok_kirpar_ve_engeller(tmp_path):
    """Kasa 100 → N 4, slot 25 $ (coin tavanı %30 = 30 $). Üç trader 70 $'lık pozisyonda (marj 210/3 = 70); gerçekleşen −25 → özsermaye 75, serbest 5 → yeni nosyonel en çok 15 $: istenen 50 $ → coin tavanı 30 → marj 15 $ (`marj_yok`).
    Özsermaye 40'a inerse serbest negatif → emir YOK."""
    kd_ = kadro([satir(i, i) for i in range(1, 5)], T0)
    m, hl, saat, _ = kur(tmp_path, kd_, kasa=100.0)
    m.baslat()
    m.piyasa_oku(saat())
    for i in (2, 3, 4):
        m.hesap.uygula(adr(i), "ETH", "B", 70 / 2000.0, 2000.0, 0.0, 1)
    m.hesap.realize["x"] = -25.0
    assert m.hesap.marj_toplam() == pytest.approx(70.0) and m.ozsermaye() == pytest.approx(75.0, abs=1e-6)
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 2000, 100.0, 0.0, saat))                # trader 200.000 $ / hesap 100.000 → 25 × 2 = 50 $ (tavan 75)
    e = kayitlar(tmp_path, "emir")[-1]
    assert s[0].karar == "emir" and e["usd_istenen"] == pytest.approx(15.0) and e["boyut_neden"] == "marj_yok"
    m.hesap.realize["x"] = -60.0
    s2 = m.olay_isle(olay("a:2", adr(1), "SOL", "B", 2000, 100.0, 0.0, saat))
    assert s2[0].karar == "engel" and s2[0].neden == "marj_yok" and m.neden_say["marj_yok"] == 2 and m.ozet()["marj_yok"] == 2


class BirlesikHL(SahteHL):
    """Trader hesabı: ana dex 60.000 + HIP‑3 dex `xyz` 30.000 + spot USDC 10.000 (PURR sayılmaz) = 100.000 $."""
    def __call__(self, y):
        if y["type"] == "perpDexs":
            return [None, {"name": "xyz"}]
        if y["type"] == "clearinghouseState":
            self.istekler.append(y)
            return {"marginSummary": {"accountValue": "30000" if y.get("dex") == "xyz" else "60000"}, "assetPositions": []}
        return super().__call__(y)


def test_k35_trader_hesap_paydasi_tum_perp_dex_ve_spot_usdc():
    post = BirlesikHL(spot=10_000.0)
    assert mt.hesap_degeri_oku(post, adr(1), ["xyz"]) == pytest.approx(100_000.0)
    assert mt.hesap_degeri_oku(post, adr(1), []) == pytest.approx(70_000.0)                         # ana dex + spot (HIP-3 dex yoksa)
    class SpotHatali(BirlesikHL):
        def __call__(self, y):
            if y["type"] == "spotClearinghouseState":
                raise ConnectionError("spot")
            return super().__call__(y)
    with pytest.raises(ConnectionError):
        mt.hesap_degeri_oku(SpotHatali(), adr(1), ["xyz"])                                          # kısmi toplam dönmez


def test_k35_motor_emir_boyutu_birlesik_hesap_paydasiyla(tmp_path):
    """Trader 300 BTC × 100 $ = 30.000 $ açar. Payda 100.000 $ (birleşik) → 27,27 $; yalnız ana dex (60.000 $) olsaydı 45,45 $ olurdu. Spot okunamazsa emir atlanır (`trader_hesap_yok`)."""
    m, hl, saat, _ = kur(tmp_path, hl=BirlesikHL(spot=10_000.0))
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert kayitlar(tmp_path, "emir")[0]["usd_istenen"] == pytest.approx(27.2727, abs=1e-4) and m.hesap_tr[adr(1)]["deger"] == pytest.approx(100_000.0)

    class SpotHatali(BirlesikHL):
        def __call__(self, y):
            if y["type"] == "spotClearinghouseState":
                raise ConnectionError("spot")
            return super().__call__(y)
    m2, *_ = kur(tmp_path / "b", hl=SpotHatali(spot=10_000.0))
    m2.baslat()
    m2.hesap_tr.clear()
    s = m2.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, Saat()))
    assert s[0].karar == "atlandi" and s[0].neden == "trader_hesap_yok" and m2.sayac["emir"] == 0


def test_k35_gercek_kipte_kasa_min_ayar_ve_hl_hesap_degeri():
    """Ayar 1.000: HL 600 → 600; HL 5.000 → 1.000 (hesapta fazla olsa da ayarın üstü kullanılmaz); sanal kip HL'ye bakmaz; okunamazsa KipHatasi."""
    assert mt.etkin_kasa(RULES, "gercek", BirlesikHL(spot=-89_400.0), {"CANLI_KASA_USD": "1000", "HL_HESAP_ADRESI": adr(7)}) == (600.0, 600.0)           # 60.000 + 30.000 − 89.400 (test girdisi) = 600
    assert mt.etkin_kasa(RULES, "gercek", BirlesikHL(spot=10_000.0), {"CANLI_KASA_USD": "1000", "HL_HESAP_ADRESI": adr(7)}) == (1000.0, 100_000.0)
    assert mt.etkin_kasa(RULES, "sanal", SahteHL(), {}) == (1000.0, None)
    def bozuk(y):
        raise ConnectionError("x")
    with pytest.raises(mt.KipHatasi):
        mt.etkin_kasa(RULES, "gercek", bozuk, {"CANLI_KASA_USD": "1000", "HL_HESAP_ADRESI": adr(7)})


def test_k35_kontrol_etkin_kasayi_raporlar():
    r = mt.kontrol(RULES, "gercek", BirlesikHL(spot=-89_400.0), lambda: n_kadro(3), tg.Telegram(TOKEN, CHAT, SahteTG()), ortam={"HL_API_CUZDAN_ANAHTARI": "k", "HL_HESAP_ADRESI": adr(7), "CANLI_KASA_USD": "1000"}, turet=lambda k: adr(9))
    assert r["kasa_kaynagi"] == "ortam" and r["hl_hesap_degeri"] == pytest.approx(600.0) and r["etkin_kasa_usd"] == pytest.approx(600.0) and r["kasa_usd"] == 1000.0 and r["tamam"] is True
    r2 = mt.kontrol(RULES, "sanal", BirlesikHL(spot=10_000.0), lambda: n_kadro(3), tg.Telegram(TOKEN, CHAT, SahteTG()), ortam={"HL_API_CUZDAN_ANAHTARI": "k", "HL_HESAP_ADRESI": adr(7)})
    assert r2["etkin_kasa_usd"] == 1000.0                                                           # sanal kip: ayar


def test_k35_etkin_kasa_degisince_hesap_kaydi_korunur(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.durum_yaz()
    m2, *_ = kur(tmp_path, kasa=600.0, saat=saat)                                                  # gerçek kip: etkin kasa 1.000 → 600
    assert m2.hesap.kasa_usd == 600.0 and m2.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727, abs=1e-6) and m2.saha.slot == pytest.approx(600 / 11)


def test_k36_motor_artirma_trader_hesap_degerini_kullanir_hesap_yok_degil(tmp_path):
    """K‑36 gerçek vardiya bulgusu (194 × `hesap_yok`): motor artırmada hesap paydasını geçirmiyordu → her artırma atlandı. Slot 90,909, hesap 100.000 $: trader 300 BTC × 100 $ açar (hedef 27,27 $, açılış 27,27),
    sonra 600'e çıkarır (hedef 54,545 $) → artırma emri 54,545 − 27,273 = **27,27 $** (`tamam`)."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 300.0, saat))
    assert [(x.eylem, x.karar) for x in s] == [("artir", "emir")] and kayitlar(tmp_path, "emir")[1]["usd_istenen"] == pytest.approx(27.2727, abs=1e-3) and not m.neden_say.get("hesap_yok")


def test_telegram_mesajlari_sade_turkce_altin_ornek():
    a = "0x1234567890abcdef"
    assert tg.msg_emir(a, "ETH", "B", 11.0, 2000.0, 0.00012, "dolu", "sanal", "ac") == \
        "🟢 ETH AL: 11,0 $ (sanal · deneme parası)\n↳ Trader 0x123456… pozisyon açtı, biz de kopyaladık\n↳ Fiyat 2000 · trader'a göre fark +1.2 bp"
    assert tg.msg_emir(a, "BTC", "A", 272.73, 100.0, None, "dolmadi", "sanal", "kapat").startswith("⚠️ BTC SAT: emir tam dolmadı (dolmadi)")
    assert tg.msg_saha("giriş", a, "bos_slot (yerine 0xabcdef12…)") == "➕ Yeni trader takibe alındı: 0x123456…\n↳ Neden: boş yer açıldı (yerine 0xabcdef12…)"
    assert tg.msg_saha("çıkış", a, "kadro_disi (sonuçla, 14 gün bekleme)").startswith("➖ Trader takipten çıktı: 0x123456…\n↳ Neden: günlük kadrodan düştü")
    assert tg.msg_durum("sanal", 1000.71, 1000.0, 9, 11, 3, 8, 0, False) == (
        "📊 Anlık durum (sanal · deneme parası)\n━━━━━━━━━━━━━━\n💰 Özsermaye 1.000,71 $ (kasaya göre +%0,07)\n👥 Takipte 9/11 trader · 3 tanesi ayrılıyor (pozisyonları kapanıyor)\n📌 Açık pozisyon: 8\n🧾 Bu turda emir: 0\n🛡️ Risk: normal, motor çalışıyor")
    assert tg.tr_sayi(1234567.891) == "1.234.567,89" and tg.tr_yuzde(-0.0125) == "−%1,25"
    assert tg.alarm("ALARM: kasa sınırı aşıldı", "Kasa 1.200 $ > sınır 1.000 $.") == "🚨 ALARM: kasa sınırı aşıldı\n━━━━━━━━━━━━━━\nKasa 1.200 $ > sınır 1.000 $."


def test_telegram_emir_ozeti_toplar_tek_mesaj_ayni_satir_birlesir():
    a = "0xf43a34aaaaaaaa"
    emirler = [{"adres": a, "coin": "ETH", "yon": "B", "usd": 12.0, "px": 2393.5, "kayma": 0.0, "durum": "dolu", "eylem": "artir"},
               {"adres": a, "coin": "ETH", "yon": "B", "usd": 13.1, "px": 2393.5, "kayma": 0.0001, "durum": "dolu", "eylem": "artir"},
               {"adres": a, "coin": "BTC", "yon": "B", "usd": 34.6, "px": 79672.0, "kayma": 0.0, "durum": "dolu", "eylem": "ac"},
               {"adres": a, "coin": "NEAR", "yon": "B", "usd": 11.0, "px": 3.943, "kayma": 0.00015, "durum": "kismi", "eylem": "ac"}]
    assert tg.msg_emir_ozeti("sanal", emirler, 5) == (
        "🧾 Son 5 dakikada 4 emir (sanal · deneme parası)\n"
        "🟢 AL BTC: 35 $ · 0xf43a34… pozisyon açtı\n"                                                              # büyükten küçüğe sıralı
        "🟢 AL ETH: 25 $ (2 emir) · 0xf43a34… pozisyonunu artırdı\n"
        "🟢 AL NEAR: 11 $ · 0xf43a34… pozisyon açtı · ⚠️ 1 tanesi tam dolmadı\n"
        "↳ Trader'a göre ortalama fark 0.6 bp (küçük = iyi)")
    assert tg.msg_emir_ozeti("sanal", emirler[:1], 5).startswith("🟢 ETH AL: 12,0 $")                               # tek emir: ayrıntılı biçim


def test_k38_motor_azaltma_hedef_tabanli_atlanan_parca_sonra_yakalanir_hesap_yok_degil(tmp_path):
    """K‑38 (K‑36'daki hesap_yok dersiyle): motor azaltmada da trader hesap paydasını geçirir. Hesap 100.000 $, slot 90,909: trader 300 BTC × 100 $ açar (biz 27,2727 $). 300 → 250: hedef 22,7273 → fark 4,5455 < 11 → atlanır (eski oransal 4,5455 de atlardı).
    250 → 150: hedef 13,6364 → fark 13,6364 → **13,64 $ azaltma** (eski oransal: 27,27 × 100/250 = 10,9 < 11 → yine atlardı; fark hiç kapanmazdı)."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    s2 = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 50, 100.0, 300.0, saat))
    assert not any(x.karar == "emir" for x in s2)
    s3 = m.olay_isle(olay("a:3", adr(1), "BTC", "A", 100, 100.0, 250.0, saat))
    assert [(x.eylem, x.karar) for x in s3] == [("azalt", "emir")] and kayitlar(tmp_path, "emir")[-1]["usd_istenen"] == pytest.approx(13.6364, abs=1e-3) and not m.neden_say.get("hesap_yok")


def test_k38_oransal_yedek_sayaci_neden_say_ve_kayitta(tmp_path):
    """Lider onayı (05.11): trader hesabı bilinmiyorsa azaltma oransal yedeğe düşer ve `azalt_oransal_yedek` olarak SAYILIR (özet neden_say + emir kaydı boyut_neden)."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.hesap_tr[adr(1)] = {"deger": 0.0, "ms": saat()}                                   # hesap değeri 0 ⇒ bilinmiyor gibi (oransal yedek)
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 150, 100.0, 300.0, saat))
    assert [(x.eylem, x.karar) for x in s] == [("azalt", "emir")] and m.neden_say.get("azalt_oransal_yedek") == 1 and kayitlar(tmp_path, "emir")[-1]["boyut_neden"] == "azalt_oransal_yedek"
def test_k39_motor_gecis_beklemesi_silinir_ve_kayda_yazilir(tmp_path):
    import json as _j
    (tmp_path / "durum").mkdir()
    adres = "0x62edf4" + "1" * 34
    (tmp_path / "durum" / "saha.json").write_text(_j.dumps({"bekleme": {adres: 9_999_999_999_999}, "kurulu": True}))
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    assert adres not in m.saha.bekleme and any(x["olay"] == "bekleme_silindi" and x["adres"] == adres and x["neden"] == "K-39" for x in kayitlar(tmp_path))


def test_b7_periyodik_vardiya_boyunca_taze_ozet_json_yazar_pano_icin(tmp_path):
    """Pano 15 dakikada bir yenilensin (B7): motor `durum/ozet.json`'u yalnız vardiya sonunda değil her periyodik döngüde yazar (vardiya kimliği, acik, dinleyici alanlarıyla)."""
    import types
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    din = types.SimpleNamespace(izle_ekle=lambda a: None, durdur=lambda: None, ozet=lambda: {"genel": {"kopma": 3}})

    async def kos():
        durdur = asyncio.Event()
        gorev = asyncio.create_task(mt._periyodik(m, durdur, din, aralik_sn=60))
        await asyncio.sleep(0.5)
        durdur.set()
        await gorev
    asyncio.run(kos())
    ozet = json.loads((tmp_path / "durum" / "ozet.json").read_text())
    assert ozet["vardiya"] == m.vardiya_id and "acik" in ozet and ozet["dinleyici"] == {"kopma": 3} and ozet["kasa_usd"] == 1000.0 and ozet["yazildi_ms"] == saat()


# ================================================================================================ Telegram lider kararları (2026-11-05 akşam)
def test_baslat_dur_dosyasi_yoksa_risk_json_dur_sifirlanir_dosya_varsa_dokunulmaz(tmp_path):
    """/kapat → yalnız DUR silinip yeniden başlatılırsa risk.json `dur: true` kalırdı; DUR dosyası tek yetkili."""
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.dur_tetikle("komut")
    assert m.risk.dur and (tmp_path / "durum" / "DUR").exists()
    (tmp_path / "durum" / "DUR").unlink()                                                     # kullanıcı DUR'u elle sildi
    assert json.loads((tmp_path / "durum" / "risk.json").read_text(encoding="utf-8"))["dur"] is True
    m2, *_ = kur(tmp_path)
    assert m2.risk.dur is True
    m2.baslat()
    assert m2.risk.dur is False and m2.risk.dur_neden is None
    assert json.loads((tmp_path / "durum" / "risk.json").read_text(encoding="utf-8"))["dur"] is False        # kayda yazıldı
    ev = kayitlar(tmp_path, "dur_sifirlandi")
    assert len(ev) == 1 and ev[0]["neden"] == "komut"
    m3, *_ = kur(tmp_path)
    m3.baslat()
    assert len(kayitlar(tmp_path, "dur_sifirlandi")) == 1                                     # dur zaten yoktu: olay tekrarlanmaz


def test_baslat_dur_dosyasi_varsa_motor_baslamaz_risk_dur_sifirlanmaz(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.dur_tetikle("komut")
    m2, *_ = kur(tmp_path)
    with pytest.raises(mt.KipHatasi):
        m2.baslat()
    assert m2.risk.dur is True and not kayitlar(tmp_path, "dur_sifirlandi")


def test_vardiya_arasinda_gelen_komut_yanitlanir_calistirilmaz_bir_kez_yetki_ve_pencere(tmp_path):
    simdi = time.time()
    tgp = SahteTG([tg_mesaj(1, "/kapat", tarih=simdi - 300),                      # 5 dk önce: yanıt, ÇALIŞTIRILMAZ
                   tg_mesaj(2, "/dur", tarih=simdi - 14 * 60),                    # pencere içinde
                   tg_mesaj(3, "/devam", tarih=simdi - 16 * 60),                  # G-16: 15 dk dışında da YANIT alır (eskiden sessizdi), yürütülmez
                   tg_mesaj(4, "/kapat", tarih=simdi - 60, kimden=999),           # yetkisiz: yanıt yok
                   tg_mesaj(5, "merhaba", tarih=simdi - 60)])                     # komut değil
    m, hl, saat, _ = kur(tmp_path, tgp=tgp)
    m.baslat()
    m.dakika()
    yanit = [x for x in tgp.gonderilen if "İŞLENMEDİ" in x]
    assert len(yanit) == 1 and yanit[0].splitlines() == [
        "📭 /kapat 5 dk önce geldi, motor o sırada kapalıydı; İŞLENMEDİ. Hâlâ istiyorsan yeniden gönder.",
        "📭 /dur 14 dk önce geldi, motor o sırada kapalıydı; İŞLENMEDİ. Hâlâ istiyorsan yeniden gönder.",
        "📭 /devam 16 dk önce geldi, motor o sırada kapalıydı; İŞLENMEDİ. Hâlâ istiyorsan yeniden gönder."]
    assert not m.dur_istendi and not m.risk.dur and not m.risk.acilis_durdu.get("elle_dur") and not (tmp_path / "durum" / "DUR").exists()      # komut yürütülmedi
    m.dakika()
    assert len([x for x in tgp.gonderilen if "İŞLENMEDİ" in x]) == 1          # spam yok
    assert m.tg.yetkisiz_sayisi == 1
    t = tg.Telegram(TOKEN, CHAT, SahteTG([tg_mesaj(7, "/durum", tarih=simdi - 100)]), baslangic_s=simdi)
    assert t.komutlari_al() == [] and len(t.gonderilen) == 1
    t.post.guncellemeler.append(tg_mesaj(7, "/durum", tarih=simdi - 100))                  # aynı update_id yeniden gelse bile ikinci yanıt yok
    t.komutlari_al()
    assert len(t.gonderilen) == 1


def test_vardiya_arasi_yanit_telegram_kapaliysa_sessiz_gecer():
    t = tg.Telegram("", "", SahteTG([tg_mesaj(1, "/kapat", tarih=time.time() - 60)]), baslangic_s=time.time())
    assert t.komutlari_al() == [] and t.gonderilen == []


def test_durum_gercek_risk_bayraklarini_gosterir_bayrak_yoksa_normal(tmp_path):
    m, hl, saat, tgp = kur(tmp_path, tgp=SahteTG([]))
    m.baslat()
    assert "Risk: normal" in m.durum_metni()
    m.risk.bayrak("gunluk_kayip", True)
    m.risk.bayrak("mutabakat", True)
    m._komutlar(["/dur"])
    m.risk.fren_bitis[adr(1)] = saat() + 60_000
    metin = m.durum_metni()
    for parca in ("Günlük kayıp freni", "Mutabakat", "duraklatıldı", "Patlama freni"):
        assert parca in metin
    assert "Risk: normal" not in metin
    m.risk.fren_bitis[adr(1)] = saat() - 1
    m.risk.bayrak("gunluk_kayip", False)
    assert "Patlama freni" not in m.durum_metni() and "Günlük kayıp" not in m.durum_metni()
    m.risk.dur = True
    assert "DURDURULDU" in m.durum_metni()
    m._komutlar(["/durum"])
    assert tgp.gonderilen[-1] == m.durum_metni()


def test_dur_dosyasi_kapanislardan_once_yazilir_kapanis_istisnasi_dur_u_bozmaz_yeniden_baslatinca_acilis_yok(tmp_path, monkeypatch):
    """Lider denetimi: kapanış sırasında istisna (ör. HL okuması) olsa da `DUR` yazılı kalır; yeniden başlatma yalnız kapanış modunda başlar, açılış yapılmaz."""
    m, hl, saat, tgp = kur(tmp_path, tgp=SahteTG([]))
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))

    def patla(*a, **k):
        assert (tmp_path / "durum" / "DUR").exists()                                           # istisna anında DUR zaten yazılı
        raise ConnectionError("HL okuması patladı")
    monkeypatch.setattr(m, "_adres_kapat", patla)
    m.dur_tetikle("zirve_dusus")
    dur = json.loads((tmp_path / "durum" / "DUR").read_text(encoding="utf-8"))
    assert dur["neden"] == "zirve_dusus" and dur["kapanis_bekliyor"] is True and not (tmp_path / "durum" / "DUR.tmp").exists()
    assert m.risk.dur and m.dur_bekliyor and kayitlar(tmp_path, "dur_kapanis_hata") and any(x.startswith("🛑 DUR:") for x in tgp.gonderilen)
    m2, hl2, saat2, _ = kur(tmp_path, saat=saat)
    m2.baslat()                                                                                # kapanış modu: açık pozisyon var
    assert m2.risk.dur and m2.dur_bekliyor
    assert m2.olay_isle(olay("a:2", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat))[0].karar == "engel"


def test_dur_dosyasi_yazilamazsa_alarm_ve_kayit_sessiz_gecilmez(tmp_path):
    m, hl, saat, tgp = kur(tmp_path, tgp=SahteTG([]))
    m.baslat()
    (tmp_path / "durum" / "DUR.tmp").mkdir()                                                   # geçici dosya yazılamaz (dizin engeli) → OSError
    m.dur_tetikle("komut")
    assert kayitlar(tmp_path, "dur_yazim_hata") and any("DUR dosyası YAZILAMADI" in x for x in tgp.gonderilen) and m.risk.dur



# ---------------------------------------------------------------- G5: kip/kasa uyuşmazlığında başlama yok
def kur_kip(tmp_path, kip, ayar=300.0, saat=None):
    """Aynı durum dizinine `kip` kipinde Motor kurar (gerçek kip: ayarlı kasa `ayar`, etkin kasa = ayar)."""
    rules = {**RULES, "canli_kasa_usd": ayar, "canli_kasa_ayar_usd": ayar}
    hl, saat = SahteHL(), saat or Saat()
    yur = yu.SanalYurutucu(hl, rules)
    yur.kip = kip
    k = kadro([satir(1, 1)], saat() - SAAT)
    return mt.Motor(rules, yur, hl, tg.Telegram(TOKEN, CHAT, SahteTG()), tmp_path / "durum", tmp_path / "kayit", lambda: k, saat), saat


def test_g5_sanal_durum_dizininde_gercek_kip_acilmaz(tmp_path):
    m, saat = kur_kip(tmp_path, "sanal", 1000.0)
    m.baslat()
    m.durum_yaz()
    assert json.loads((tmp_path / "durum" / "motor.json").read_text())["kip"] == "sanal"
    g, _ = kur_kip(tmp_path, "gercek", 300.0, saat)
    with pytest.raises(mt.KipHatasi, match="sanal durum dizininde gerçek kip açılmaz"):
        g.baslat()
    assert kayitlar(tmp_path, "vardiya_baslamadi")[-1]["neden"] == "sanal durum dizininde gerçek kip açılmaz"


def test_g5_gercek_durum_dizininde_sanal_kip_acilmaz(tmp_path):
    g, saat = kur_kip(tmp_path, "gercek", 300.0)
    g.baslat()
    g.durum_yaz()
    s, _ = kur_kip(tmp_path, "sanal", 1000.0, saat)
    with pytest.raises(mt.KipHatasi, match="gerçek durum dizininde sanal kip açılmaz"):
        s.baslat()
    assert kayitlar(tmp_path, "vardiya_baslamadi")


def test_g5_gercek_farkli_kasa_acik_pozisyon_varsa_ret(tmp_path):
    g, saat = kur_kip(tmp_path, "gercek", 300.0)
    g.baslat()
    g.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert any(g.hesap.poz.values())
    g.durum_yaz()
    g2, _ = kur_kip(tmp_path, "gercek", 500.0, saat)
    with pytest.raises(mt.KipHatasi, match="açık pozisyon var"):
        g2.baslat()
    assert not kayitlar(tmp_path, "kasa_degisti") and kayitlar(tmp_path, "vardiya_baslamadi")


def test_g5_gercek_farkli_kasa_pozisyon_yoksa_kabul_ve_kasa_degisti(tmp_path):
    g, saat = kur_kip(tmp_path, "gercek", 300.0)
    g.baslat()
    g.durum_yaz()
    g2, _ = kur_kip(tmp_path, "gercek", 500.0, saat)
    g2.baslat()
    g2.durum_yaz()
    k = kayitlar(tmp_path, "kasa_degisti")
    assert len(k) == 1 and k[0]["eski_usd"] == 300.0 and k[0]["yeni_usd"] == 500.0
    assert json.loads((tmp_path / "durum" / "motor.json").read_text())["kasa_ayar_usd"] == 500.0
    g3, _ = kur_kip(tmp_path, "gercek", 500.0, saat)                                              # aynı ayar: kayıt yok
    g3.baslat()
    assert len(kayitlar(tmp_path, "kasa_degisti")) == 1


def test_g5_bos_dizin_serbest_gercek_de_sanal_da(tmp_path):
    g, _ = kur_kip(tmp_path / "a", "gercek", 300.0)
    g.baslat()
    g.durum_yaz()
    s, _ = kur_kip(tmp_path / "b", "sanal", 1000.0)
    s.baslat()
    s.durum_yaz()
    for alt, kip in (("a", "gercek"), ("b", "sanal")):                                            # S-24: boş dizinde iki kip de açılır (KipHatasi yok), kip kaydedilir, red kaydı yok
        assert json.loads((tmp_path / alt / "durum" / "motor.json").read_text())["kip"] == kip
        assert not kayitlar(tmp_path / alt, "vardiya_baslamadi")
    assert not g.risk.dur and not s.risk.dur


def test_g5_eski_bicim_kip_alani_yok_sanal_sayilir(tmp_path):
    m, saat = kur_kip(tmp_path, "sanal", 1000.0)
    m.baslat()
    m.durum_yaz()
    yol = tmp_path / "durum" / "motor.json"
    j = json.loads(yol.read_text())
    j.pop("kip")
    j.pop("kasa_ayar_usd")
    yol.write_text(json.dumps(j))
    s, _ = kur_kip(tmp_path, "sanal", 1000.0, saat)
    s.baslat()                                                                                    # sanal + eski biçim: aynen devam
    yol.write_text(json.dumps(j))
    g, _ = kur_kip(tmp_path, "gercek", 300.0, saat)
    with pytest.raises(mt.KipHatasi, match="sanal durum dizininde"):
        g.baslat()


def test_g5_main_uyusmazlikta_cikis_3_ve_telegram(monkeypatch, tmp_path):
    from tests.test_g1_alarm import SahteTg as TabanTg

    class SahteTg(TabanTg):
        ornekler: list = []
        offset, kayit, maske = 0, None, []

    SahteTg.ornekler = []
    m, saat = kur_kip(tmp_path, "sanal", 1000.0)
    m.baslat()
    m.durum_yaz()
    monkeypatch.setattr(mt.tg, "Telegram", SahteTg)
    monkeypatch.setattr(mt, "rest_post_olustur", lambda rules: SahteHL())
    monkeypatch.setattr(mt, "kip_belirle", lambda rules, istenen=None, ortam=None: "gercek")
    monkeypatch.setattr(mt, "etkin_kasa", lambda rules, kip, post, ortam=None: (300.0, 300.0))
    monkeypatch.setattr(mt, "kasa_belirle", lambda rules, kip, ortam=None: (300.0, "ortam"))
    monkeypatch.setenv("HL_API_CUZDAN_ANAHTARI", "test-anahtar")                                   # G6 doğrulaması geçsin (agent adr(9) → hesap adr(7))
    monkeypatch.setenv("HL_HESAP_ADRESI", adr(7))
    monkeypatch.setattr(mt, "anahtardan_adres", lambda anahtar: adr(9))
    hl = SahteHL()
    yur = yu.SanalYurutucu(hl, {**RULES, "canli_kasa_usd": 300.0})
    yur.kip = "gercek"
    monkeypatch.setattr(mt, "gercek_yurutucu_olustur", lambda post, rules: yur)
    assert mt.main(["--kip", "gercek", "--durum-dizin", str(tmp_path / "durum")]) == 3
    assert "sanal durum dizininde gerçek kip açılmaz" in TabanTg.ornekler[0].gonderilen[0]


def test_emir_kaydinda_boyut_girdileri_elle_denetim(tmp_path):
    """06.11 lider: emir kaydı boyut girdilerini taşır. Altın örnek (üstteki test): slot 90,909 $, trader hesap 100.000 $, BTC 300 × 100 $ açılış → hedef 90,909 × 300 × 100 / 100.000 = 27,2727 $."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.piyasa_oku(saat())
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 150, 100.0, 300.0, saat))
    e1, e2 = kayitlar(tmp_path, "emir")[:2]
    assert (e1["trader_poz_once"], e1["trader_poz_sonra"], e1["trader_hesap_usd"]) == (0.0, 300.0, 100000.0)
    assert e1["slot_usd"] == pytest.approx(1000 / 11) and e1["biz_poz_usd"] == 0.0 and e1["biz_slot_toplam_usd"] == 0.0 and e1["hedef_usd"] == pytest.approx(27.2727, abs=1e-4)
    assert (e2["trader_poz_once"], e2["trader_poz_sonra"]) == (300.0, 150.0) and e2["biz_poz_usd"] == pytest.approx(27.2727, abs=1e-3) and e2["hedef_usd"] == pytest.approx(13.6364, abs=1e-4)
    assert e2["biz_slot_toplam_usd"] == pytest.approx(27.2727, abs=1e-3)


def test_kor_kirpildi_kaydi_yalniz_durum_degisince(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    a, b = adr(7), adr(8)
    m.karar_uygula([kd.Karar("giris_atlandi", a, "kor_kirpildi", kor_kirpildi=[adr(1), adr(2)])], saat())
    m.karar_uygula([kd.Karar("giris_atlandi", a, "kor_kirpildi", kor_kirpildi=[adr(2), adr(1)])], saat())          # aynı durum (sıra farkı): yeni kayıt YOK
    assert len(kayitlar(tmp_path, "kor_kirpildi")) == 1
    m.karar_uygula([kd.Karar("giris_atlandi", a, "kor_kirpildi", kor_kirpildi=[adr(1), adr(3)])], saat())          # engelleyen küme değişti: yazılır
    m.karar_uygula([kd.Karar("giris_atlandi", b, "kor_kirpildi", kor_kirpildi=[adr(1), adr(3)])], saat())          # başka aday: yazılır
    assert len(kayitlar(tmp_path, "kor_kirpildi")) == 3


def test_tur_kaydi_14_dakikada_bir(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m._tur_kaydi(saat())
    m._tur_kaydi(saat() + 5 * 60_000)                                       # çok erken: yazılmaz
    m._tur_kaydi(saat() + 15 * 60_000)
    t = kayitlar(tmp_path, "tur")
    assert len(t) == 2 and t[0]["ozsermaye_usd"] == pytest.approx(1000.0, abs=1e-6)


def test_k45_eki_yedekten_giris_de_korelasyon_denetimine_tabi():
    """08.11 denetimi: Yedek (sıra 12) sahadaki iki bağlı üyeye r=0,94 benzer → üçüncü olurdu (bileşen 3 > 2): girmez, sıra 13 (ilişkisiz) girer.
    Önceden korelasyon matrisi yalnız İlk 11'i kapsıyordu ve Yedek 'ilişkisiz' sayılıp geçiyordu."""
    s = kd.Saha(RULES, 100.0)                                                                  # N = 4
    rows = [satir(1, 1), satir(2, 2), satir(3, 3), satir(4, 12), satir(5, 13)]
    adresler = [adr(i) for i in range(1, 6)]
    m = [[1, 0.9, 0.0, 0.94, 0.0], [0.9, 1, 0.0, 0.94, 0.0], [0.0, 0.0, 1, 0.0, 0.0], [0.94, 0.94, 0.0, 1, 0.0], [0.0, 0.0, 0.0, 0.0, 1]]
    karar, _ = s.degerlendir(kadro(rows, kor={"adresler": adresler, "gun_sayisi": 8, "matris": m}), T0 + SAAT)
    assert set(s.uyeler) == {adr(1), adr(2), adr(3), adr(5)}
    assert [(k.adres, k.neden) for k in karar if k.tur == "giris_atlandi"] == [(adr(4), "kor_kirpildi")]


# ================================================================================================ B15 / B11 düzeltmeleri
def test_b15_islem_yok_sayaci_trader_son_dolumundan_baslar_giristen_degil():
    """Altın örnek: üyeler T0+1 sa girer. adr(11)'in son dolumu girişten ÖNCE T0−50 sa (motor girişte REST'le okur → `islem_gordu`).
    72 sa sınırı T0−50 sa + 72 sa = T0+22 sa (T0 = 08:00 UTC → ertesi UTC günü, yeni kadro): T0+22 sa − 1 ms'de kalır, T0+22 sa'te `islem_yok` (sonuç dışı) düşer.
    Eski kod (temel = max(son dolum, giriş) = T0+1 sa) T0+73 sa'e kadar beklerdi. Son dolum bilinmiyorsa (None: REST okunamadı) sayaç giriş anından: T0+73 sa."""
    def kur_(son_dolum):
        s = hazir_11()
        for i in range(1, 11):
            s.islem_gordu(adr(i), T0 + 2 * SAAT)                    # 10 üye girişten sonra işlem yaptı (T0+73 sa − T0+2 sa = 71 sa < 72)
        if son_dolum is not None:
            s.islem_gordu(adr(11), son_dolum)                       # adr(11): girişten 51 sa önceki son dolum
        return s

    def dusen(son_dolum, t):
        s = kur_(son_dolum)
        karar, _ = s.degerlendir(n_kadro(11, t), t)
        return [(k.adres, k.neden, k.sonuc) for k in karar if k.tur == "dus"], s
    assert dusen(T0 - 50 * SAAT, T0 + 22 * SAAT - 1)[0] == []
    d, s = dusen(T0 - 50 * SAAT, T0 + 22 * SAAT)
    assert d == [(adr(11), "islem_yok", False)] and adr(11) not in s.bekleme
    assert kur_(None).uyeler[adr(11)]["son_islem_ms"] is None
    assert dusen(None, T0 + 73 * SAAT - 1)[0] == []
    assert dusen(None, T0 + 73 * SAAT)[0] == [(adr(11), "islem_yok", False)]


def test_b15_motor_giriste_son_dolumu_rest_ile_okur(tmp_path):
    """Giriş T0+1 sa. REST (`userFillsByTime`, startTime = T0+1 sa − 72 sa = T0−71 sa) dolumları T0−50 sa ve T0−40 sa → son_islem_ms = T0−40 sa.
    Dolum yoksa: son dolum ≤ pencere başı → T0−71 sa yazılır. Okuma hatası → None (bilinmiyor; sayaç girişten) + `son_islem_okuma_hata`."""
    hl = SahteHL(rest_dolumlar={adr(1): [{"coin": "BTC", "time": T0 - 50 * SAAT}, {"coin": "BTC", "time": T0 - 40 * SAAT}]})
    m, hl, saat, _ = kur(tmp_path / "a", hl=hl)
    m.baslat()
    assert m.saha.uyeler[adr(1)]["son_islem_ms"] == T0 - 40 * SAAT
    assert [y["startTime"] for y in hl.istekler if y["type"] == "userFillsByTime" and y["user"] == adr(1)] == [T0 + SAAT - 72 * SAAT]
    m2, _, _, _ = kur(tmp_path / "b")
    m2.baslat()
    assert m2.saha.uyeler[adr(1)]["son_islem_ms"] == T0 - 71 * SAAT

    class Kirik(SahteHL):
        def __call__(self, y):
            if y["type"] == "userFillsByTime":
                raise ConnectionError("ağ")
            return super().__call__(y)
    m3, _, _, _ = kur(tmp_path / "c", hl=Kirik())
    m3.baslat()
    assert m3.saha.uyeler[adr(1)]["son_islem_ms"] is None and [x["adres"] for x in kayitlar(tmp_path / "c", "son_islem_okuma_hata")] == [adr(1)]


def test_b11_kor_kirpildi_degistirmede_uye_basina_tekrar_yazilmaz(tmp_path):
    """08.11 gerilemesi: aday adr(20) (sıra 9, form 80) sahadaki adr(1) ile r=0,9; adr(1)–adr(2) r=0,9. Değiştirilebilir 3 üye (adr(9..11), sıra 12..14, form 40) için
    `kalan` her seferinde farklı (3 farklı liste) ama hepsinde {adr(1), adr(2), adr(20)} bileşeni 3 kişi > 2 → 3 giris_atlandi. Aynı durum: tek kor_kirpildi satırı;
    5 dk sonraki ikinci değerlendirme ve aynı tam sahayla `_doldur` yolundan gelen karar da yazılmaz; saha değişince yeniden yazılır."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    s = hazir_11()
    for i in range(1, 12):
        s.islem_gordu(adr(i), T0 + 20 * SAAT)
    adresler = [adr(1), adr(2), adr(20)]
    kor = {"adresler": adresler, "gun_sayisi": 8, "matris": [[1, 0.9, 0.9], [0.9, 1, 0.1], [0.9, 0.1, 1]]}
    rows = [satir(i, i, 90 - i) for i in range(1, 9)] + [satir(20, 9, 80.0), satir(9, 12, 40.0), satir(10, 13, 40.0), satir(11, 14, 40.0)]
    k1, _ = s.degerlendir(kadro(rows, T0 + GUN, kor), T0 + GUN + SAAT)
    atl = [k for k in k1 if k.tur == "giris_atlandi"]
    assert [k.adres for k in atl] == [adr(20)] * 3 and len({tuple(sorted(k.kor_kirpildi)) for k in atl}) == 3          # eski imza (kalan) 3 farklı → 3 satır yazardı
    assert all(sorted(k.saha) == sorted(adr(i) for i in range(1, 12)) for k in atl) and len(s.uyeler) == 11
    m.karar_uygula(k1, saat())
    k2, _ = s.degerlendir(kadro(rows, T0 + GUN, kor), T0 + GUN + SAAT + 5 * 60_000)
    m.karar_uygula(k2, saat())
    tam = [adr(i) for i in range(1, 12)]
    m.karar_uygula([kd.Karar("giris_atlandi", adr(20), "kor_kirpildi", kor_kirpildi=tam, saha=tam)], saat())          # `_doldur` yolu, aynı tam saha
    assert len(kayitlar(tmp_path, "kor_kirpildi")) == 1
    yeni = [*tam[:10], adr(12)]
    m.karar_uygula([kd.Karar("giris_atlandi", adr(20), "kor_kirpildi", kor_kirpildi=yeni[1:], saha=yeni)], saat())    # saha gerçekten değişti: yazılır
    assert len(kayitlar(tmp_path, "kor_kirpildi")) == 2

# ---------------------------------------------------------------- 300 $ paralel sanal seri (`--sanal-kasa-usd`, 08.11 kullanıcı onayı)
def test_sanal_kasa_bayragi_yalniz_sanal_ve_sinir_icinde():
    assert mt.kasa_belirle(RULES, "sanal", {}, 300) == (300.0, "arg")
    assert mt.kasa_belirle(RULES, "sanal", {}, 1000) == (1000.0, "arg")                                    # sınır dahil
    assert mt.kasa_belirle(RULES, "sanal", {}) == (1000.0, "yaml")                                         # bayraksız: aynen yaml (1.000 $ seri)
    assert mt.kasa_belirle(RULES, "sanal", {"CANLI_KASA_USD": "500"}, 300) == (300.0, "arg")               # ortam kasası sanalda yine yok sayılır
    for kotu in (0, -1, 1000.01, 5000, float("nan"), float("inf"), "x"):
        with pytest.raises(mt.KipHatasi, match="--sanal-kasa-usd"):
            mt.kasa_belirle(RULES, "sanal", {}, kotu)
    with pytest.raises(mt.KipHatasi, match="yalnız sanal kipte"):                                         # gerçek kipte bayrak ret (ortam kasası olsa da)
        mt.kasa_belirle(RULES, "gercek", {"CANLI_KASA_USD": "300"}, 300)
    with pytest.raises(mt.KipHatasi, match="yalnız sanal kipte"):
        mt.etkin_kasa(RULES, "gercek", SahteHL(), {"CANLI_KASA_USD": "300", "HL_HESAP_ADRESI": adr(7)}, sanal_kasa=300)
    assert mt.etkin_kasa(RULES, "sanal", SahteHL(), {}, sanal_kasa=300) == (300.0, None)


def test_sanal_kasa_300_altin_ornek_n11_slot_27_27_ve_emir(tmp_path):
    """Altın örnek (elle): kasa 300 $ → N = min(11, taban(300 / 25 = 12)) = 11; slot = 300 / 11 = 27,2727 $.
    Trader hesap 100.000 $, 300 BTC × 100 $ açar (oran 0,30): hedef = 27,2727 × 0,30 = 8,1818 $ < `radar_min_emir_usd` 11 $; tavandan kalan (3 × 27,27 = 81,82 $) yeter → 11 $'a yuvarlanır: 0,11 BTC.
    1000 BTC (oran 1,0): hedef 27,2727 $ → 0,272727 BTC. (1.000 $ seride aynı olaylar 27,27 $ / 90,91 $ olur: küçük kasada min emir yuvarlaması ağırlığı artırır — ölçülmek istenen budur.)"""
    from copytrade import boyut
    assert boyut.saha_sayisi(300.0, RULES) == 11 and boyut.slot_usd(300.0, RULES) == pytest.approx(27.272727, abs=1e-6)
    s = kd.Saha(RULES, 300.0)
    assert s.n == 11 and s.slot == pytest.approx(300 / 11)
    for sz, hedef, dolan, coin in ((300, 8.1818, 11.0, 0.11), (1000, 27.2727, 27.2727, 0.272727)):
        t = tmp_path / str(sz)
        m, hl, saat, _ = kur(t, kasa=300.0, kurallar={"canli_kasa_ayar_usd": 300.0, "canli_kasa_kaynagi": "arg"})
        m.baslat()
        assert m.kasa == 300.0 and m.hesap.kasa_usd == 300.0 and m.saha.n == 11 and m.saha.slot == pytest.approx(27.272727, abs=1e-6)
        m.olay_isle(olay("a:1", adr(1), "BTC", "B", sz, 100.0, 0.0, saat))
        e = kayitlar(t, "emir")
        assert len(e) == 1 and e[0]["slot_usd"] == pytest.approx(300 / 11)
        assert e[0]["hedef_usd"] == pytest.approx(hedef, abs=1e-4) and e[0]["usd_dolan"] == pytest.approx(dolan, abs=1e-4) and e[0]["sz"] == pytest.approx(coin, abs=1e-6)


def test_g5_sanal_kasa_bayragi_farkli_kasali_dizinde_baslamaz(tmp_path):
    """300 $ koşusu 1.000 $ serisinin durum dizinine yazamaz (kayıtlı kasa_ayar_usd farklı ya da eksik → ret); kendi dizininde / boş dizinde başlar."""
    m, saat = kur_kip(tmp_path, "sanal", 1000.0)
    m.baslat()
    m.durum_yaz()
    s, _ = kur_kip(tmp_path, "sanal", 300.0, saat)
    s.rules = {**s.rules, "canli_kasa_kaynagi": "arg"}
    with pytest.raises(mt.KipHatasi, match="ayrı durum dizini"):
        s.baslat()
    assert "1000 $" in kayitlar(tmp_path, "vardiya_baslamadi")[-1]["neden"]
    yol = tmp_path / "durum" / "motor.json"                                                     # kayıtlı kasa bilinmiyor (eski biçim): güvenli yön, ret
    j = json.loads(yol.read_text())
    j.pop("kasa_ayar_usd")
    yol.write_text(json.dumps(j))
    s2, _ = kur_kip(tmp_path, "sanal", 300.0, saat)
    s2.rules = {**s2.rules, "canli_kasa_kaynagi": "arg"}
    with pytest.raises(mt.KipHatasi, match="bilinmiyor"):
        s2.baslat()
    b, saat_b = kur_kip(tmp_path / "b", "sanal", 300.0)                                          # boş dizin: serbest; sonra aynı kasa: devam
    b.rules = {**b.rules, "canli_kasa_kaynagi": "arg"}
    b.baslat()
    b.durum_yaz()
    assert json.loads((tmp_path / "b" / "durum" / "motor.json").read_text())["kasa_ayar_usd"] == 300.0
    b2, _ = kur_kip(tmp_path / "b", "sanal", 300.0, saat_b)
    b2.rules = {**b2.rules, "canli_kasa_kaynagi": "arg"}
    b2.baslat()


def _main_hazirla(monkeypatch, hl=None):
    for ad in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CANLI_KIP", "CANLI_KASA_USD", "HL_API_CUZDAN_ANAHTARI", "HL_HESAP_ADRESI"):
        monkeypatch.delenv(ad, raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")                                                   # Actions koşusu gibi
    hl = hl or SahteHL()
    monkeypatch.setattr(mt, "rest_post_olustur", lambda rules: hl)
    monkeypatch.setattr(mt, "http_kadro_oku", lambda rules, dal=None: n_kadro(3, int(time.time() * 1000)))
    return hl


def test_main_sanal_kasa_bayragi_reddi_cikis_3_ag_yok(monkeypatch, tmp_path):
    """Gerçek kip + bayrak, > 1.000 $, ≤ 0: motor başlamaz (çıkış 3), HL'ye istek gitmez; kontrol kipinde de ret."""
    def ag_yok(rules):
        raise AssertionError("ret öncesi ağ çağrısı olmamalı")
    _main_hazirla(monkeypatch)
    monkeypatch.setattr(mt, "rest_post_olustur", ag_yok)
    d = str(tmp_path / "durum")
    assert mt.main(["--sanal-kasa-usd", "1500", "--durum-dizin", d]) == 3
    assert mt.main(["--sanal-kasa-usd", "0", "--durum-dizin", d]) == 3
    assert mt.main(["--kontrol", "--sanal-kasa-usd", "2000", "--durum-dizin", d]) == 3
    assert mt.main(["--kip", "gercek", "--sanal-kasa-usd", "300", "--durum-dizin", d]) == 3                 # Actions: gerçek kip zaten ret
    monkeypatch.delenv("GITHUB_ACTIONS")
    monkeypatch.setattr(mt, "kip_belirle", lambda rules, istenen=None, ortam=None: "gercek")                # sunucuda gerçek kip olsa bile bayrak ret
    assert mt.main(["--kip", "gercek", "--sanal-kasa-usd", "300", "--durum-dizin", d]) == 3
    assert not (tmp_path / "durum").exists()


def test_main_sanal_kasa_300_kontrol_ve_motor_actions_ortaminda(monkeypatch, tmp_path):
    """Kuru argüman denetimi: Actions ortamında (CANLI_* yok) `--kip sanal --sanal-kasa-usd 300` → kontrol.json kasa 300 / "arg"; motor 300 $ kasa, N 11, slot 27,27 ile açılır, motor.json kasa_ayar_usd 300."""
    _main_hazirla(monkeypatch)
    assert mt.main(["--kontrol", "--kip", "sanal", "--sanal-kasa-usd", "300", "--durum-dizin", str(tmp_path / "kontrol")]) == 0
    r = json.loads((tmp_path / "kontrol" / "kontrol.json").read_text())
    assert (r["kip"], r["kasa_usd"], r["kasa_kaynagi"], r["etkin_kasa_usd"], r["kasa_siniri_ok"], r["emir_gonderildi"]) == ("sanal", 300.0, "arg", 300.0, True, False)
    yakalanan = {}

    async def sahte_calis(motor, sure_sn=None, **_):
        yakalanan["m"] = motor
        motor.durum_yaz()
        return {"tamam": True}
    monkeypatch.setattr(mt, "calis", sahte_calis)
    assert mt.main(["--kip", "sanal", "--sanal-kasa-usd", "300", "--durum-dizin", str(tmp_path / "durum"), "--kayit-dizin", str(tmp_path / "kayit"), "--sure-sn", "1"]) == 0
    m = yakalanan["m"]
    assert m.kip == "sanal" and m.kasa == 300.0 and m.kasa_ayar == 300.0 and m.saha.n == 11 and m.saha.slot == pytest.approx(300 / 11) and m.rules["canli_kasa_kaynagi"] == "arg"
    assert json.loads((tmp_path / "durum" / "motor.json").read_text())["kasa_ayar_usd"] == 300.0
    yakalanan.clear()                                                                                # aynı 300 $ dizinde bayrakla FARKLI kasa (1.000 $): G5 ret, motor kurulmaz
    assert mt.main(["--kip", "sanal", "--sanal-kasa-usd", "1000", "--durum-dizin", str(tmp_path / "durum"), "--kayit-dizin", str(tmp_path / "kayit")]) == 3
    assert "m" not in yakalanan


def test_main_bayraksiz_cagri_eskisiyle_ayni(monkeypatch, tmp_path):
    """1.000 $ üretim: bayrak yoksa kasa yaml (1.000 $), kaynak anahtarı rules'a eklenmez (G5 sanal kasa denetimi devreye girmez; davranış değişmez)."""
    _main_hazirla(monkeypatch)
    yakalanan = {}

    async def sahte_calis(motor, sure_sn=None, **_):
        yakalanan["m"] = motor
        return {}
    monkeypatch.setattr(mt, "calis", sahte_calis)
    assert mt.main(["--kip", "sanal", "--durum-dizin", str(tmp_path / "durum")]) == 0
    m = yakalanan["m"]
    assert m.kasa == 1000.0 and m.kasa_ayar == 1000.0 and m.saha.slot == pytest.approx(1000 / 11) and "canli_kasa_kaynagi" not in m.rules


def test_f10_bayat_hesap_onbellegi_acilista_kullanilmaz(tmp_path):
    """F10 (denetim 10.11): önbellek 10.000 $ ve 2 saat eski, gerçek 100.000 $. Taze okuma başarılıysa emir 100.000 $ paydayla (27,27 $);
    okunamıyorsa bayat paydayla (272,7 $ → tavanla kırpılmış büyük emir) AÇILMAZ (`trader_hesap_yok`). Taze önbellek yeniden okunmaz."""
    class Bozuk(BirlesikHL):
        bozuk = False

        def __call__(self, y):
            if self.bozuk and y["type"] in ("clearinghouseState", "spotClearinghouseState"):
                raise ConnectionError("hl")
            return super().__call__(y)
    hl = Bozuk(spot=10_000.0)
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()
    m.hesap_tr[adr(1)] = {"deger": 10_000.0, "ms": saat() - 2 * SAAT}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert kayitlar(tmp_path, "emir")[0]["usd_istenen"] == pytest.approx(27.2727, abs=1e-4)          # bayat → yeniden okundu
    m.hesap_tr[adr(1)] = {"deger": 10_000.0, "ms": saat() - 2 * SAAT}
    hl.bozuk = True
    s = m.olay_isle(olay("a:2", adr(1), "ETH", "B", 3000, 10.0, 0.0, saat))
    assert [(x.karar, x.neden) for x in s] == [("atlandi", "trader_hesap_yok")] and len(kayitlar(tmp_path, "emir")) == 1
    m.hesap_tr[adr(1)] = {"deger": 100_000.0, "ms": saat() - 60_000}                                # taze (1 dk): ağ bozukken de kullanılır
    s = m.olay_isle(olay("a:3", adr(1), "ETH", "B", 3000, 10.0, 0.0, saat))
    assert [x.karar for x in s] == ["emir"]
