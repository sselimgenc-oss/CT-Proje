"""Pano v2 (6 sekme + üst şerit): sekme sırası, şerit kutuları, risk durumu eşikleri, görünür metinde teknik kelime yok, kapanışlar tek tek, ML "Henüz ölçülemedi", koyu tema değişkenleri."""
from __future__ import annotations

import html as html_mod

import pytest
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
    serit = h[h.index('<div class="sirit s6"'):h.index('<div class="tabs">')]
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
    assert "Veri birikiyor: 8/20 işlem" in h and "Henüz ölçülemedi" not in h
    assert "Açık, henüz eğitilmedi" in h


def test_ml_egitilmis_isabet_ve_karar_listesi():
    from copytrade.canli.ogrenme_adaptor import takma_ad
    og = [{"kurulum": takma_ad(A1), "alinan": 40, "filtre": True, "carpan": None, "emekli": False}]
    kayit = [{"olay": "ml_filtre_atla", "zaman_ms": SIMDI - 1000 * i, "kurulum": takma_ad(A1), "coin": "BTC"} for i in range(1, 13)]
    kayit += [{"olay": "karsi_olgu_kapandi", "zaman_ms": SIMDI - 500 * i, "coin": "BTC", "neden": "ml_filtre_atla", "pnl_usd": -1.0 if i % 3 else 2.0} for i in range(1, 13)]
    kayit += [{"olay": "ml_filtre_egitildi", "zaman_ms": SIMDI - 86_400_000, "kurulum": takma_ad(A1), "n_egitim": 42}]
    h = sayfa(ozet={**OZET, "ogrenme": og}, kayit=kayit)
    assert "son 12 kararın 8'i tuttu" in h
    assert "42 örnek" in h and "almadı" in h and "doğru karar" in h
    assert "ML'in atlattığı işlem: 12" in h and "küçültme" not in h


def test_ders_karti_durumlari():
    og = [{"kurulum": "T_x", "alinan": 5, "filtre": False, "carpan": None, "emekli": False}]
    assert 'rz bk">Açık, henüz ders çıkmadı' in sayfa(ozet={**OZET, "ogrenme": og})        # ders yok → sarı (kırmızı değil)
    og2 = [{**og[0], "carpan": 0.5}]
    assert 'rz eks">Açık ama işlemlere uygulanmıyor' in sayfa(ozet={**OZET, "ogrenme": og2})   # ders çıktı ama son 7 günde hiçbir işleme uygulanmadı → kırmızı
    uygulanan = [emir(SIMDI - 3_600_000, eylem="ac", pnl=0.0, neden="tamam", ders_carpan=0.5)]
    assert 'rz art">Açık, işlemleri etkiliyor' in sayfa(ozet={**OZET, "ogrenme": og2}, kayit=uygulanan)
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
    assert "~15 dakikada" not in h and "location.reload()},180000)" in h and 'id="bayat"' in h and 'classList.toggle("bayat"' in h


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


def test_saglik_mesajinda_dosya_adi_gorunmez():
    g = gorunur(pano.html_olustur({"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "yazildi_ms": SIMDI, "vardiya": "v"}, {}, {}, [], [], SIMDI))
    assert ".json" not in g and ".py" not in g and ".yml" not in g


def test_ml_aldi_kararlari_kayittan_ve_isabet():
    from copytrade.canli.ogrenme_adaptor import takma_ad
    al_ = takma_ad(A1)
    og = [{"kurulum": al_, "alinan": 40, "filtre": True, "carpan": None, "emekli": False}]
    kayit = []
    for i in range(1, 11):                                                                  # 10 onay: 7'si kazandı, 3'ü kaybetti
        ms = SIMDI - 100_000 * i
        kayit += [{"olay": "ml_filtre_al", "zaman_ms": ms, "kurulum": al_, "coin": f"C{i}", "puan": 0.7, "esik": 0.5, "n_egitim": 40},
                  {"olay": "ogrenme_aday", "zaman_ms": ms + 1000, "kurulum": al_, "coin": f"C{i}", "r": 1.0, "net_usd": 3.0 if i <= 7 else -2.0}]
    h = sayfa(ozet={**OZET, "ogrenme": og}, kayit=kayit)
    assert "son 10 kararın 7'si tuttu" in h and "10 işlem onaylandı" in h and "aldı" in h and "sonuç +3,00 $" in h
    yeni = pano.ogrenme_ozeti(kayit, {**OZET, "ogrenme": og}, None, {"ogrenme_aktif": True, "ogrenme_filtre_aktif": True}, SIMDI, {})
    assert yeni["onay7"] == 10 and yeni["isabet"] == (7, 10)


def test_kapanan_pozisyon_bazinda_kazanma_ve_kismi_kapanis_tek_sonuc():
    k = [emir(SIMDI - 9 * 3_600_000, eylem="ac", pnl=0.0, neden="tamam", sz=0.15), emir(SIMDI - 8 * 3_600_000, eylem="azalt", pnl=5.0, neden="tamam"), emir(SIMDI - 7 * 3_600_000, pnl=-3.0, sz=0.10),   # poz 1: +5 −3 → +2 (kazandı)
         emir(SIMDI - 6 * 3_600_000, eylem="ac", pnl=0.0, neden="tamam"), emir(SIMDI - 5 * 3_600_000, pnl=-4.0)]                                                                        # poz 2: −4 (kaybetti)
    s = pano.kapanan_islemler(k)
    assert len(s) == 3
    o = pano.kapanan_ozeti(s)
    assert o["kapanis"] == 3 and o["poz"] == 2 and o["kazanma"] == 0.5 and o["ort_kazanc"] == pytest.approx(1.9) and o["ort_kayip"] == pytest.approx(-4.05)      # komisyon 0,05 dolum başına
    h = sayfa(kayit=k)
    assert "2 pozisyon" in h and "pozisyon bazında" in h


def test_kapanan_satir_trader_adi_ve_fiyat_farki_ayrintisi():
    k = [emir(SIMDI - 3_600_000, eylem="ac", pnl=0.0, neden="tamam", sz=1.0, trader_px=100.0, dolum_px=100.1),
         emir(SIMDI - 1_000, pnl=2.0, neden="felaket_stop", sz=1.0, trader_px=110.0, dolum_px=109.89)]
    s = pano.kapanan_islemler(k, 0.2)[0]
    assert s["tr_giris"] == 100.0 and s["giris"] == 100.1 and abs(s["giris_fark"] - 0.001) < 1e-9 and abs(s["cikis_fark"] - 0.001) < 1e-9       # her ikisi bizim aleyhe %0,10
    assert s["ayrinti"] == "Zarar stopu (%20)" and s["neden"] == "Stop"
    h = sayfa(kayit=k)
    assert "uzun · 0xa1a1a1…" in h and "Giriş (trader → biz)" in h and "%0,10 aleyhe" in h and "Zarar stopu (%20)" in h
    assert pano.kapanan_islemler([emir(SIMDI, neden="borsa_stop")])[0]["ayrinti"] == "Borsa stopu"
    assert pano.kapanan_islemler([emir(SIMDI, neden="trader_ters_senkron")])[0]["neden"] == "Trader yön değiştirdi"
    assert pano.kapanan_islemler([emir(SIMDI, neden="inen_ters")])[0]["neden"] == "Konsensüs döndü"


def test_fiyat_kademeli_ondalik():
    assert pano.fiyat(1784.9129) == "1.784,91" and pano.fiyat(0.9847123) == "0,9847" and pano.fiyat(0.00512345) == "0,005123" and pano.fiyat(None) == "—"
    assert pano.tr_sayi(0.0051234, 6) == "0,005123"


def test_toplam_kz_dokumu_aciklanamayan_fark_yok():
    """Gerçek veriden öğrenilen kimlik: toplam = realize (zorla kapanma dahil) + açık − (komisyon: açılış+kapanış) + fonlama."""
    hesap = {"realize": {A1: -51.75}, "ucret": {A1: 10.75}, "funding": {A1: 0.07}, "tasfiyeler": [{"pnl": -14.97}], "kapanmis_net": 0.0}
    ozet = {**OZET, "kasa_usd": 10_000.0, "ozsermaye_usd": 10_000.0 - 51.75 + 53.46 - 10.75 + 0.07, "acik": [{"adres": A1, "coin": "ETH", "sz": 1.0, "giris": 1.0, "mark": 1.0, "usd": 1.0, "kz_usd": 53.46}]}
    h = sayfa(ozet=ozet, hesap=hesap)
    g = gorunur(h)
    assert "Toplam nasıl oluşuyor" in g and "Zorla kapanma" in g and "−14,97 $" in g and "Kapanışlar (gerçekleşen) −36,78 $" in g.replace("  ", " ").replace("   ", " ") or "−36,78 $" in g
    assert "Açıklanamayan fark" not in g
    assert "Açıklanamayan fark" in gorunur(sayfa(ozet={**ozet, "ozsermaye_usd": ozet["ozsermaye_usd"] + 5.0}, hesap=hesap))


def test_bugun_tutarliligi_ve_limit_gunu_aciklamasi():
    h = sayfa(risk={"gun_basi": 1000.0, "zirve": 1020.0})
    g = gorunur(h)
    assert "Bugün K/Z (gece yarısından, TSİ)" in g and "Bugün kapanışlar (net)" in g and "03:00 TSİ" in g


def test_bayat_veri_tek_sayi_risk_bilinmiyor_ve_gorev():
    taze = sayfa()
    assert 'class="gn"' in taze and "Bilinmiyor" in taze and "<html lang=\"tr\">" in taze                  # taze: başlık normal, "Bilinmiyor" varyantı gizli (CSS)
    eski = sayfa(ozet={**OZET, "yazildi_ms": SIMDI - 3 * 3_600_000})
    assert '<html lang="tr" class="bayat">' in eski and 'class="uy"' in eski and "Veri bayat: son güncelleme 3 sa 0 dk önce" in eski
    assert "orkestratöre 'CT panosu güncellenmiyor' yaz" in html_mod.unescape(eski)
    ozet_bolum = gorunur(eski[eski.index('<section class="n1">'):eski.index('<section class="n2">')])
    assert not re.search(r"\b\d+ (dk|sa)\b", ozet_bolum)                                                    # durum ışığı ve kartlar yaş sayısı yazmaz (tek yer: üst satır)
    assert "Kopya İşlem Panosu" in eski and "Copy Trade" not in eski


def test_koyu_temada_uyari_seridi_koyu_kirmizi():
    css = sayfa()[sayfa().index("<style>"):sayfa().index("</style>")]
    assert "--uyb:#7f1d1d" in css and "--uyy:#ffe4e4" in css and ".uy{background:var(--uyb);color:var(--uyy)" in css
