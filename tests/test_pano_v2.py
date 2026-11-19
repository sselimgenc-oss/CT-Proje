"""Pano v2 (6 sekme + üst şerit): sekme sırası, şerit kutuları, risk durumu eşikleri, görünür metinde teknik kelime yok, kapanışlar tek tek, ML "Henüz ölçülemedi", koyu tema değişkenleri."""
from __future__ import annotations

import html as html_mod
import re

from copytrade.canli import pano

A1 = "0x" + "a1" * 20
A2 = "0x" + "b2" * 20
SIMDI = 1_793_900_000_000                       # 2026-11-05 17:33 UTC
DK = 60_000
OZET = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1012.5, "getiri": 0.0125, "saha": 2, "saha_n": 11, "yazildi_ms": SIMDI - 2 * DK, "vardiya": "v",
        "dinleyici": {"kopma": 0}, "rest_429": 0, "duygu": {"deger": 10, "sinif": "Extreme Fear"},
        "acik": [{"adres": A1, "coin": "ETH", "sz": 0.5, "giris": 1800.0, "mark": 1790.0, "usd": 895.0, "kz_usd": -5.0},
                 {"adres": A2, "coin": "SOL", "sz": -10.0, "giris": 80.0, "mark": 78.0, "usd": 780.0, "kz_usd": 20.0}]}


def emir(ms, coin="ETH", adres=A1, eylem="kapat", pnl=-2.0, neden="tam_kapanis", **ek):
    return {"olay": "emir", "zaman_ms": ms, "adres": adres, "coin": coin, "eylem": eylem, "yon": "A", "usd_dolan": 100.0, "sz": 0.05, "reduce_only": eylem != "ac", "pnl_usd": pnl,
            "durum": "dolu", "boyut_neden": neden, "ucret": 0.05, "dolum_px": 1800.0, "kayma_trader": 0.0002, **ek}


KAYIT = [emir(SIMDI - 5 * 3_600_000, eylem="ac", pnl=0.0, neden="tamam"), emir(SIMDI - 4 * 3_600_000), emir(SIMDI - 3 * 3_600_000, pnl=1.5, neden="iz_suren_koruma"),
         emir(SIMDI - 2 * 3_600_000, pnl=-1.0, neden="uydurma_kod"), {"olay": "saha_giris", "zaman_ms": SIMDI - 3_600_000, "adres": A1, "neden": "ilk_gun"},
         {"olay": "emir_yok", "zaman_ms": SIMDI - 3_600_000, "adres": A1, "coin": "BTC", "neden": "kod_olmayan_neden"}]


def sayfa(ozet=None, risk=None, kayit=None, **kw):
    return pano.html_olustur(ozet or OZET, risk if risk is not None else {"gun_basi": 1000.0, "zirve": 1020.0}, kw.pop("hesap", {}), KAYIT if kayit is None else kayit, kw.pop("gecmis", []), SIMDI, **kw)


def gorunur(h: str) -> str:
    h = re.sub(r"<(script|style)\b.*?</\1>", "", h, flags=re.S)
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", h))


def test_alti_sekme_sirasi():
    h = sayfa()
    etiketler = re.findall(r'<label for="t\d">([^<]+)</label>', h)
    assert etiketler == ["ÖZET", "AÇIK", "KAPANAN", "K/Z", "ÖĞRENME", "TEKNİK"]
    assert len(re.findall(r'<section class="n\d">', h)) == 6


def test_ust_serit_alti_kutu_ve_sabit_sirasi():
    h = sayfa()
    serit = h[h.index('<div class="sirit s6"'):h.index('<div class="gn">')]
    assert serit.count('<div class="h">') == 6
    assert re.findall(r'<div class="hb">([^<]+)</div>', serit) == ["Kasa", "Bugün K/Z", "Toplam K/Z", "Açık poz.", "Zirveden düşüş", "Risk durumu"]
    assert h.index('class="sirit s6"') < h.index('<div class="tabs">')                      # şerit sekmelerden bağımsız, her sekmede üstte


def test_risk_durumu_esikleri():
    # günlük kayıp sınırı %5 × 1.000 = 50 $; ≥ %70 kullanıldı (35 $) → sarı; ≥ %100 → kırmızı
    assert pano.risk_durumu(966.0, 1000.0, 0.05, False)[:2] == ("art", "Güvenli")
    assert pano.risk_durumu(965.0, 1000.0, 0.05, False)[:2] == ("bk", "Limite yakın")
    assert pano.risk_durumu(950.0, 1000.0, 0.05, False)[:2] == ("eks", "Durdu")
    assert pano.risk_durumu(1000.0, 1000.0, 0.05, True)[:2] == ("eks", "Durdu")              # motor durdu bayrağı
    assert pano.risk_durumu(970.0, 1000.0, 0.05, False)[2] == "günlük limite kalan 20,00 $"
    assert 'class="hd art">Güvenli' in sayfa()
    assert 'class="hd bk">Limite yakın' in sayfa(ozet={**OZET, "ozsermaye_usd": 960.0})
    assert 'class="hd eks">Durdu' in sayfa(risk={"gun_basi": 1000.0, "zirve": 1020.0, "acilis_durdu": {"gunluk_kayip": True}})


def test_gorunur_metinde_utc_bp_ve_kod_kelimeleri_yok():
    kadro = {"kosu_ms": SIMDI - 3_600_000, "saha_n": 11, "satirlar": [{"adres": A1, "sira": 1, "katman": "ilk11", "form": 80.0, "kopya_getiri_7g": 0.01, "max_kaldirac": 3.0}],
             "huni": {"evren": 10, "aday": 5, "islem_yeterli": 3, "gecen": 2, "kadro": 2, "neden": {"islem_az": 3, "bilinmeyen_kod": 1}}}
    h = sayfa(kadro=kadro, saha_durum={"uyeler": {A1: {"giris_ms": SIMDI - 3_600_000}}, "inen": {}}, hesap={"slot_bas": {A1: 909.0}, "realize": {A1: 5.0}, "ucret": {A1: 1.0}, "funding": {A1: 0.5}},
              donem_seri={"bas_ms": SIMDI - 2 * 86_400_000, "kasa_usd": 1000.0, "gunler": [{"gun": "2026-11-04", "ozsermaye_usd": 1005.0, "btc": 100.0}]})
    g = gorunur(h)
    assert "UTC" not in g and not re.search(r"\bbp\b", g)
    assert not re.search(r"\b[a-z]+_[a-z_]+\b", g), re.findall(r"\b[a-z]+_[a-z_]+\b", g)
    for kelime in ("funding", "Funding", "PnL", "R1", "slot", "Slot", "karşı-olgu", "Extreme", "yalnız bilgi", "yalnız kayıt"):
        assert kelime not in g, kelime
    assert not re.search(r"\d,\d{3,}", g)                                                   # 3+ ondalık yok (fiyatlar ≥ 1 $)
    assert "diğer" in g                                                                     # bilinmeyen kodlar "diğer"


def test_kapananlar_tek_tek_ve_neden_etiketleri():
    satirlar = pano.kapanan_islemler(KAYIT)
    assert len(satirlar) == 3                                                               # 3 kapanış dolumu = 3 ayrı satır (trader/gün toplamı yok)
    assert [r["neden"] for r in satirlar] == ["diğer", "İz süren", "Trader kapattı"]       # yeniden eskiye; bilinmeyen kod → diğer
    h = sayfa()
    per4 = h[h.index('class="per per4"'):]
    assert per4.count('<details class="r">') == 3
    assert "Bugün" in h and "7g" in h and "30g" in h and "Tümü" in h


def test_kapananlar_yirmi_satir_ve_daha_fazla():
    kayit = [emir(SIMDI - i * DK, pnl=1.0) for i in range(1, 31)]
    h = sayfa(kayit=kayit)
    per4 = h[h.index('class="per per4"'):]
    assert per4.count('<details class="r">') == 30 and "daha fazla (10)" in per4


def test_ml_henuz_olculemedi_yolu():
    og = [{"kurulum": "T_abcdef", "alinan": 8, "filtre": False, "carpan": None, "emekli": False}]
    h = sayfa(ozet={**OZET, "ogrenme": og}, gunluk_ozet={"ogrenme": {"aktif_ders": 0}})
    assert "Henüz ölçülemedi (8 işlem, en az 20 gerek)" in h
    assert "Açık, henüz eğitilmedi" in h
    assert "veri birikiyor" in h


def test_ml_egitilmis_isabet_ve_karar_listesi():
    from copytrade.canli.ogrenme_adaptor import takma_ad
    og = [{"kurulum": takma_ad(A1), "alinan": 40, "filtre": True, "carpan": None, "emekli": False}]
    kayit = [{"olay": "ml_filtre_atla", "zaman_ms": SIMDI - 1000 * i, "kurulum": takma_ad(A1), "coin": "BTC"} for i in range(1, 7)]
    kayit += [{"olay": "karsi_olgu_kapandi", "zaman_ms": SIMDI - 500 * i, "coin": "BTC", "neden": "ml_filtre_atla", "pnl_usd": -1.0 if i % 3 else 2.0} for i in range(1, 13)]
    kayit += [{"olay": "ml_filtre_egitildi", "zaman_ms": SIMDI - 86_400_000, "kurulum": takma_ad(A1), "n_egitim": 42}]
    h = sayfa(ozet={**OZET, "ogrenme": og}, kayit=kayit)
    assert "son 12 tahminin 8'i tuttu" in h
    assert "42 örnek" in h and "almadı" in h and "doğru karar" in h


def test_ders_karti_durumlari():
    og = [{"kurulum": "T_x", "alinan": 5, "filtre": False, "carpan": None, "emekli": False}]
    assert "Açık ama işlemleri etkilemiyor" in sayfa(ozet={**OZET, "ogrenme": og})          # açık ama etkisiz → kırmızı rozet
    assert 'rz eks">Açık ama' in sayfa(ozet={**OZET, "ogrenme": og})
    og2 = [{**og[0], "carpan": 0.5}]
    assert "Açık, işlemleri etkiliyor" in sayfa(ozet={**OZET, "ogrenme": og2})
    assert "Kapalı" in sayfa(ozet={**OZET, "ogrenme": og}, kurallar={"canli_gunluk_kayip_oran": 0.05, "canli_zirve_dusus_oran": 0.2, "canli_coin_tavan_oran": 0.3, "ogrenme_aktif": False})


def test_koyu_tema_degiskenleri_kendine_baglanmaz():
    h = sayfa()
    css = h[h.index("<style>"):h.index("</style>")]
    assert not re.search(r"--([\w-]+):var\(--\1\)", css)                                    # eski hata: --c2:var(--c2) değeri geçersiz kılıyordu
    for ad in ("c2", "c3", "bg", "k", "cz"):
        assert len(re.findall(rf"--{ad}:#[0-9a-fA-F]{{6}}", css)) >= 3                      # koyu + açık + sistem açık: sabit renk
    assert ":root[data-theme=light]" in css and ":root[data-theme=dark]" in css and "data-theme=acik" not in css


def test_iframe_icinde_baslik_gizlenir_ve_yenileme_metni():
    h = sayfa()
    assert "window.self!==window.top" in h and ".ic .ust{display:none}" in h
    assert "~15 dakikada" not in h and "location.reload()},180000)" in h and 'id="gun"' in h


def test_durum_isigi_kirmizi_ustte_sari_rejim_haber():
    sarı = sayfa(rejim_anlik={"gecerli_son_ms": SIMDI - 1, "rejimler": {}}, kadro=None)
    g = gorunur(sarı)
    assert "Rejim verisi güncel değil" in g or "Teknik sorun" in g
    h = sayfa(ozet={**OZET, "yazildi_ms": SIMDI - 3 * 3_600_000})
    ozet_bolumu = h[h.index('<section class="n1">'):h.index('<section class="n2">')]
    assert ozet_bolumu.index("Durum ışığı") < ozet_bolumu.index("Ne yapmalıyım?")           # teknik sorun → kırmızı kart en üstte


def test_acik_satir_ayrintilari_ve_bos_veri():
    hesap = {"poz": {A1: {"ETH": {"acilis_ms": SIMDI - 90 * DK, "giris": 1800.0, "kaldirac": 3.0, "zirve_kar": 0.2, "sz": 0.5}}}}
    h = sayfa(hesap=hesap)
    n2 = h[h.index('<section class="n2">'):h.index('<section class="n3">')]
    assert "1 sa 30 dk" in n2 and "başa baş" in n2 and "1.440,00 (girişten %20 aleyhe)" in n2 and "3x" in n2
    bos = pano.html_olustur({"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0}, {}, {}, [], [], SIMDI)
    assert "Açık işlem yok" in bos and "veri birikiyor" in bos and "Ne yapmalıyım?" in bos
