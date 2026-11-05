"""Canlı motor (T4): saha kuralları, motor uçtan uca (sahte borsa / WS / Telegram), kip güvencesi, dayanıklılık, anahtar taraması. Ağsız; elle hesaplanmış altın örnekler."""
import asyncio
import json
import re
import subprocess
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
T0 = 1_800_000_000_000
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
    s = hazir_11()
    rows = [satir(i, i, 90 - i) for i in range(1, 9)] + [satir(12, 9), satir(13, 10), satir(14, 11)]          # 9, 10, 11 kadro dışı → sonuçla düşer; 3 aday
    karar, _ = s.degerlendir(kadro(rows, T0 + GUN), T0 + GUN + SAAT)
    assert [k.adres for k in karar if k.tur == "dus"] == [adr(9), adr(10), adr(11)] and all(k.sonuc for k in karar if k.tur == "dus")
    assert [k.adres for k in karar if k.tur == "giris"] == [adr(12), adr(13)] and adr(14) not in s.uyeler           # günde 2 giriş
    assert s.bekleme[adr(9)] == T0 + GUN + SAAT + 14 * GUN
    karar2, _ = s.degerlendir(kadro(rows, T0 + 2 * GUN), T0 + 2 * GUN + SAAT)                                       # ertesi gün üçüncü girer
    assert [k.adres for k in karar2 if k.tur == "giris"] == [adr(14)]
    bitis = T0 + GUN + SAAT + 14 * GUN
    assert s._bekliyor(adr(9), bitis - 1) is True and s._bekliyor(adr(9), bitis) is False                              # 14 gün: bitiş anında serbest


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
    karar2, _ = s2.degerlendir(kadro([satir(i, i) for i in range(1, 11)] + [satir(11, 31)], T0 + GUN), T0 + GUN + SAAT)       # sıra 31 > 30: bir gün yeter
    assert [(k.neden, k.sonuc) for k in karar2 if k.tur == "dus"] == [("kadro_disi", True)]
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

    def __call__(self, y):
        self.istekler.append(y)
        t = y["type"]
        if t == "allMids":
            return self.mids
        if t == "l2Book":
            return self.kitaplar[y["coin"]]
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
    m, hl, saat, tgp = kur(tmp_path)
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
    assert any("EMİR[sanal]" in x for x in tgp.gonderilen) and any("SAHA giriş" in x for x in tgp.gonderilen)


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


def test_dur_komutu_hepsini_kapatir_dur_dosyasi_yeniden_baslatma_engeli(tmp_path):
    guncelleme = {"update_id": 5, "message": {"chat": {"id": int(CHAT)}, "text": "/dur"}}
    yabanci = {"update_id": 4, "message": {"chat": {"id": 999}, "text": "/dur"}}
    m, hl, saat, tgp = kur(tmp_path, tgp=SahteTG([yabanci]))
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dakika()
    assert not m.dur_istendi and not (tmp_path / "durum" / "DUR").exists()                    # yabancı sohbetten /dur kabul edilmedi
    tgp.guncellemeler.append(guncelleme)
    m.dakika()
    assert m.dur_istendi and (tmp_path / "durum" / "DUR").exists() and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)
    assert any(x["olay"] == "dur" and x["neden"] == "komut" for x in kayitlar(tmp_path)) and any(x.startswith("DUR:") for x in tgp.gonderilen)
    m2, *_ = kur(tmp_path)
    with pytest.raises(mt.KipHatasi):
        m2.baslat()                                                                           # DUR varken başlamaz


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


def test_kacan_dolum_rest_ile_tamamlanir_gec_goruldu_eski_dolum_emir_uretmez(tmp_path):
    saat = Saat()
    taze = {"tid": 11, "time": saat() - 5 * 60_000, "coin": "BTC", "px": "100", "sz": "300", "side": "B", "startPosition": "0"}
    eski = {"tid": 10, "time": saat() - 90 * 60_000, "coin": "ETH", "px": "2000", "sz": "10", "side": "B", "startPosition": "0"}
    hl = SahteHL(rest_dolumlar={adr(1): [eski, taze]})
    m, _, _, _ = kur(tmp_path, hl=hl, saat=saat)
    m.baslat()
    assert m.kacanlari_tamamla(saat() - 3 * SAAT) == 1                                         # pencere 60 dk: 90 dk'lık yalnız izleyiciyi günceller
    e = kayitlar(tmp_path, "emir")
    assert len(e) == 1 and e[0]["coin"] == "BTC" and e[0]["gec_goruldu"] is True and e[0]["kaynak"] == "rest" and m.sayac["gec_goruldu"] == 1
    assert m.poz_tr[adr(1)]["ETH"] == 10 and kayitlar(tmp_path, "eski_dolum_atlandi")


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
    t = tg.Telegram(TOKEN, CHAT, SahteTG([{"update_id": 1, "message": {"chat": {"id": int(CHAT)}, "text": "/durum@sg_bot"}}, {"update_id": 2, "message": {"chat": {"id": 7}, "text": "/dur"}},
                                           {"update_id": 3, "message": {"chat": {"id": int(CHAT)}, "text": "merhaba"}}]))
    assert t.komutlari_al() == ["/durum"] and t.offset == 4
    assert tg.msg_gunluk("sanal", 1000, 1012.5, 0.0125, 0.0125, 3, 11, ["0x12345678… BTC +0.1"]).startswith("GÜNLÜK ÖZET [sanal] kasa 1000$")
    assert tg.kisa(adr(255)) == "0x000000…"


# ================================================================================================ kip güvencesi
def test_kip_varsayilan_sanal_gercek_yalniz_ayar_anahtar_ve_actions_degil():
    assert mt.kip_belirle(RULES, None, {}) == "sanal" and str(RULES["canli_kip"]) == "sanal"
    with pytest.raises(mt.KipHatasi):
        mt.kip_belirle(RULES, "gercek", {"HL_API_CUZDAN_ANAHTARI": "k", "HL_HESAP_ADRESI": "0x1"})                    # kurallar.yaml sanal: gercek istenemez
    gercek_kurallar = {**RULES, "canli_kip": "gercek"}
    with pytest.raises(yu.AnahtarYok):
        mt.kip_belirle(gercek_kurallar, None, {})
    assert mt.kip_belirle(gercek_kurallar, None, {"HL_API_CUZDAN_ANAHTARI": "k", "HL_HESAP_ADRESI": "0x1"}) == "gercek"
    with pytest.raises(mt.KipHatasi):
        mt.kip_belirle(gercek_kurallar, None, {"HL_API_CUZDAN_ANAHTARI": "k", "HL_HESAP_ADRESI": "0x1", "GITHUB_ACTIONS": "true"})        # Actions'ta ASLA
    with pytest.raises(mt.KipHatasi):
        mt.kip_belirle(RULES, "x", {})


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
    ok = mt.kontrol(RULES, "gercek", hl, lambda: n_kadro(3), tg.Telegram(TOKEN, CHAT, SahteTG()), ortam={"HL_API_CUZDAN_ANAHTARI": "gizli-anahtar-xyz", "HL_HESAP_ADRESI": adr(7)})
    assert ok["bakiye_usd"] == 100_000.0 and ok["hl_hesap_degeri"] == 100_000.0 and ok["etkin_kasa_usd"] == 1000.0 and ok["tamam"] is True and "gizli-anahtar-xyz" not in json.dumps(ok)                  # anahtar rapora yazılmaz


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
        await asyncio.sleep(0.3)
        durdur.set()
        await gorev
    asyncio.run(kos())
    assert m.sayac["emir"] == 1


def test_sdk_hatasi_ve_red_motoru_cokertmez_kayit_alir(tmp_path):
    class Bozuk:
        kip = "gercek"

        def hazirla(self, coin):
            return None

        def emir(self, coin, yon, usd, reduce_only=False, acik_sz=None):
            return yu.Dolum(coin, yon, usd, reduce_only=reduce_only, durum="red", neden="sdk_hatasi: ConnectionError")
    hl = SahteHL()
    m = mt.Motor(RULES, Bozuk(), hl, tg.Telegram("", "", ortam={}), tmp_path / "durum", tmp_path / "kayit", lambda: kadro([satir(1, 1)], T0), Saat())
    m.baslat()
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, Saat()))
    assert s[0].karar == "red" and "sdk_hatasi" in s[0].neden and m.hesap.sz(adr(1), "BTC") == 0.0 and kayitlar(tmp_path, "emir")[0]["red_neden"].startswith("sdk_hatasi")


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
    assert mt.etkin_kasa(RULES, "gercek", BirlesikHL(spot=-89_400.0), {"HL_HESAP_ADRESI": adr(7)}) == (600.0, 600.0)           # 60.000 + 30.000 − 89.400 (test girdisi) = 600
    assert mt.etkin_kasa(RULES, "gercek", BirlesikHL(spot=10_000.0), {"HL_HESAP_ADRESI": adr(7)}) == (1000.0, 100_000.0)
    assert mt.etkin_kasa(RULES, "sanal", SahteHL(), {}) == (1000.0, None)
    def bozuk(y):
        raise ConnectionError("x")
    with pytest.raises(mt.KipHatasi):
        mt.etkin_kasa(RULES, "gercek", bozuk, {"HL_HESAP_ADRESI": adr(7)})


def test_k35_kontrol_etkin_kasayi_raporlar():
    r = mt.kontrol(RULES, "gercek", BirlesikHL(spot=-89_400.0), lambda: n_kadro(3), tg.Telegram(TOKEN, CHAT, SahteTG()), ortam={"HL_API_CUZDAN_ANAHTARI": "k", "HL_HESAP_ADRESI": adr(7)})
    assert r["hl_hesap_degeri"] == pytest.approx(600.0) and r["etkin_kasa_usd"] == pytest.approx(600.0) and r["kasa_usd"] == 1000.0 and r["tamam"] is True
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
