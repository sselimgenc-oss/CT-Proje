"""Ortak Telegram standardı (docs/TELEGRAM.md): proje etiketi + önem, iki adımlı onay (kod/süre/yanlış kod/denetim kaydı), eski ad eşlemesi, hız sınırı, tekrar önleme, 24 sa INFO,
3500 karakter, /yardim gecikme notu, haftalık özet. Ağsız; sahte saat."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from copytrade.canli import telegram as tg
from tests.test_canli_motor import CHAT, TOKEN, SahteTG, kur, tg_mesaj

SIMDI = 1_800_000_000.0


def yeni(guncellemeler=None, kayitlar=None, **kw):
    t = tg.Telegram(TOKEN, CHAT, SahteTG(guncellemeler), baslangic_s=SIMDI - 3600, saat_s=lambda: SIMDI, kayit=(kayitlar.append if kayitlar is not None else None), **kw)
    t.kod_uret = lambda: "4321"
    return t


def msj(uid, metin, dt=0.0):
    return tg_mesaj(uid, metin, tarih=SIMDI + dt)


# ----------------------------------------------------------------------------- etiket + önem
def test_ilk_satir_proje_etiketi_ve_onem():
    t = yeni()
    t.gonder("🧾 normal bilgi")
    t.gonder(tg.alarm("UYARI: kadro kasası farklı", "x", "⚠️"))
    t.gonder(tg.alarm("ALARM: API cüzdanı", "y"))
    assert [x.splitlines()[0] for x in t.post.ham] == ["[CT] INFO", "[CT] WARN", "[CT] CRIT"]
    assert t.post.ham[0] == "[CT] INFO\n🧾 normal bilgi"
    assert tg.onem_duzeyi("🛑 DUR: x") == "CRIT" and tg.onem_duzeyi("📭 x") == "WARN" and tg.onem_duzeyi("📊 x") == "INFO"
    t.gonder("açık", onem="WARN")
    assert t.post.ham[-1].startswith("[CT] WARN\n")


def test_mesaj_3500_karakteri_asmaz_baslik_sabit_kalir():
    t = yeni()
    t.gonder("🚨 ALARM: başlık\n" + "x" * 6000)
    gidecek = t.post.ham[-1]
    assert len(gidecek) <= 3500 and gidecek.startswith("[CT] CRIT\n🚨 ALARM: başlık\n") and gidecek.endswith("(kısaltıldı)")
    assert tg.mesaj_kirp("kısa") == "kısa"


# ----------------------------------------------------------------------------- hız sınırı, tekrar, 24 sa
def test_hiz_siniri_dakikada_15_fazlasi_bekler_kaybolmaz():
    uykular = []
    saat = [SIMDI]

    def uyku(sn):
        uykular.append(sn)
        saat[0] += sn
    t = tg.Telegram(TOKEN, CHAT, SahteTG(), saat_s=lambda: saat[0], uyku=uyku)
    for i in range(16):
        t.gonder(f"mesaj {i}")
    assert len(t.post.ham) == 16 and len(uykular) == 1 and uykular[0] == pytest.approx(60.0)       # 16. mesaj ilk gönderimden 60 sn sonra


def test_tekrar_onleme_ayni_uyari_5_dk_icinde_bir_kez():
    saat = [SIMDI]
    t = tg.Telegram(TOKEN, CHAT, SahteTG(), saat_s=lambda: saat[0])
    uyari = tg.alarm("UYARI: x", "ayrıntı", "⚠️")
    t.gonder(uyari)
    t.gonder(uyari)
    assert len(t.post.ham) == 1
    saat[0] += 301
    t.gonder(uyari)
    assert len(t.post.ham) == 2
    t.gonder("bilgi")
    t.gonder("bilgi")                                                      # INFO'da otomatik tekrar önleme yok (her dolum ayrı)
    assert len(t.post.ham) == 4
    t.gonder("a", onem="INFO", anahtar="k")
    t.gonder("b", onem="INFO", anahtar="k")                                # açık anahtar
    assert len(t.post.ham) == 5


def test_24_saatten_eski_info_atilir_warn_atilmaz():
    saat = [SIMDI]
    t = tg.Telegram(TOKEN, CHAT, SahteTG(), saat_s=lambda: saat[0])
    assert t._gonder_sync("eski bilgi", "INFO", None, SIMDI - 25 * 3600) is False and t.post.ham == []
    assert t._gonder_sync("eski uyarı", "WARN", None, SIMDI - 25 * 3600) is True and len(t.post.ham) == 1


# ----------------------------------------------------------------------------- iki adımlı onay
def test_iki_adimli_onay_dogru_kod_komutu_dondurur_ve_denetim_kaydi():
    kay = []
    t = yeni([msj(1, "/hepsini_kapat"), msj(2, "4321", 30)], kay)
    assert t.komutlari_al() == ["/hepsini_kapat"]
    istek = t.gonderilen[0]
    assert "🔐 /hepsini_kapat onayı" in istek and "Ne olacak" in istek and "120 sn" in istek and "4321" in istek
    olaylar = [(k["olay"], k.get("sonuc")) for k in kay if k["olay"].startswith("telegram_onay")]
    assert olaylar == [("telegram_onay_istendi", None), ("telegram_onay_sonuc", "onaylandi")]
    assert kay[[k["olay"] for k in kay].index("telegram_onay_istendi")]["kim"] == CHAT                 # kim


def test_iki_adimli_onay_komut_kod_gelmeden_yurutulmez():
    t = yeni([msj(1, "/durdur")])
    assert t.komutlari_al() == [] and "4321" in t.gonderilen[0]
    t.post.guncellemeler.append(msj(2, "/devam", 5))                       # yeni riskli komut öncekinin yerini alır
    assert t.komutlari_al() == [] and t._bekleyen["komut"] == "/devam"


def test_yanlis_kod_hicbir_sey_yapmaz_ve_bekleyen_iptal():
    kay = []
    t = yeni([msj(1, "/devam"), msj(2, "9999", 10), msj(3, "4321", 20)], kay)
    assert t.komutlari_al() == []
    assert any("kod yanlış" in x and "İŞLEM YAPILMADI" in x for x in t.gonderilen)
    assert any("Bekleyen onay yok" in x for x in t.gonderilen)             # doğru kod geç geldi: artık bekleyen yok
    assert ("telegram_onay_sonuc", "yanlis_kod") in [(k["olay"], k.get("sonuc")) for k in kay]


def test_sure_dolunca_dogru_kod_bile_uygulanmaz():
    kay = []
    t = yeni([msj(1, "/durdur"), msj(2, "4321", 121)], kay)                # kod 121 sn sonra yanıtlandı (mesaj tarihi)
    assert t.komutlari_al() == []
    assert any("süresi (120 sn) doldu" in x and "İŞLEM YAPILMADI" in x for x in t.gonderilen)
    assert ("telegram_onay_sonuc", "sure_doldu") in [(k["olay"], k.get("sonuc")) for k in kay]
    t2 = yeni([msj(1, "/durdur"), msj(2, "4321", 119)])                    # sınır içi: uygulanır
    assert t2.komutlari_al() == ["/durdur"]


def test_yetkisiz_kullanicinin_kodu_ve_komutu_islenmez():
    t = yeni([msj(1, "/durdur"), tg_mesaj(2, "4321", chat=999, tarih=SIMDI + 5)])
    assert t.komutlari_al() == [] and t.yetkisiz_sayisi == 1 and t._bekleyen is not None


def test_kodsuz_dort_hane_bekleyen_yokken_yanit_alir():
    t = yeni([msj(1, "1234")])
    assert t.komutlari_al() == [] and "Bekleyen onay yok" in t.gonderilen[0]


def test_risksiz_komutlar_onaysiz_gider():
    t = yeni([msj(1, "/durum"), msj(2, "/rapor")])
    assert t.komutlari_al() == ["/durum", "/rapor"] and t.gonderilen == []


# ----------------------------------------------------------------------------- eski adlar, yardım, olmayan komutlar
@pytest.mark.parametrize("eski,yeni_ad", [("/dur", "/durdur"), ("/kapat", "/hepsini_kapat"), ("/baslat", "/devam")])
def test_eski_ad_eslemesi(eski, yeni_ad):
    t = yeni([msj(1, eski), msj(2, "4321", 1)])
    assert t.komutlari_al() == [yeni_ad]


def test_yardim_gecikme_notu_ve_komut_listesi():
    t = yeni([msj(1, "/yardim"), msj(2, "/start")])
    assert t.komutlari_al() == [] and len(t.gonderilen) == 1 and t.gonderilen[0].count("GitHub Actions vardiya zincirinde") == 2
    y = tg.msg_yardim()
    assert "GitHub Actions vardiya zincirinde" in y and "GECİKEBİLİR" in y and "Sunucuya taşınınca bu gecikme kalkar" in y
    assert all(k in y for k in ("/durum", "/rapor", "/durdur", "/devam", "/hepsini_kapat", "/yardim"))


@pytest.mark.parametrize("komut", ["/kurulumlar", "/ders", "/kademe", "/kademe_devam", "/onayla", "/reddet"])
def test_olmayan_standart_komutlar_temiz_yanit(komut):
    t = yeni([msj(1, f"{komut} 5")])
    assert t.komutlari_al() == [] and t.gonderilen == [f"ℹ️ {komut}: CT'de henüz yok. Geçerli komutlar: {tg.GECERLI_KOMUT_METNI}"]


# ----------------------------------------------------------------------------- motor: /rapor, haftalık özet
def test_motor_rapor_komutu_gunluk_raporu_hemen_gonderir_durumu_degistirmez(tmp_path):
    m, hl, saat, tgp = kur(tmp_path, tgp=SahteTG([]))
    m.baslat()
    once = (m._ozet_gunu, m._ozet_oz, m._ozet_emir)
    m._komutlar(["/rapor"])
    assert tgp.gonderilen[-1].startswith("📋 Günlük rapor") and (m._ozet_gunu, m._ozet_oz, m._ozet_emir) == once


def utc_ms(*a):
    return int(datetime(*a, tzinfo=timezone.utc).timestamp() * 1000)


def test_gunluk_rapor_21_tsi_haftalik_pazar_18_10_utc(tmp_path):
    from tests.test_canli_motor import RULES
    assert int(RULES["canli_ozet_saat_utc"]) == 18                          # 18:00 UTC = 21:00 TSİ
    m, hl, saat, tgp = kur(tmp_path, tgp=SahteTG([]))
    m.baslat()
    m._gunluk_ozet(utc_ms(2026, 11, 19, 17, 59))
    assert not any(x.startswith("📋 Günlük rapor") for x in tgp.gonderilen)
    m._gunluk_ozet(utc_ms(2026, 11, 19, 18, 0))
    m._gunluk_ozet(utc_ms(2026, 11, 19, 18, 5))                             # aynı gün ikinci kez yok
    assert len([x for x in tgp.gonderilen if x.startswith("📋 Günlük rapor")]) == 1
    haftalik = lambda: [x for x in tgp.gonderilen if x.startswith("🗓️ Haftalık özet")]        # noqa: E731
    m._haftalik_ozet(utc_ms(2026, 11, 21, 18, 10))                          # Cumartesi: yok
    m._haftalik_ozet(utc_ms(2026, 11, 22, 18, 9))                           # Pazar 21:09 TSİ: henüz yok
    assert haftalik() == []
    m._haftalik_ozet(utc_ms(2026, 11, 22, 18, 10))
    m._haftalik_ozet(utc_ms(2026, 11, 22, 18, 30))
    assert len(haftalik()) == 1 and m._hafta_taban is not None


def test_haftalik_metin_altin_ornek():
    metin = tg.msg_haftalik("sanal", 1000.0, 1030.0, 1000.0, 105.0, 100.0, 42, [("0xaaaaaaaaaaaa", 20.0), ("0xbbbbbbbbbbbb", -5.5), ("0xcccccccccccc", 3.0)])
    assert metin.splitlines() == ["🗓️ Haftalık özet (sanal · deneme parası)", tg.AYRAC, "📈 Hafta: +30,00 $ (+%3,00)", "₿ BTC al-tut: +%5,00 · fark −%2,00",
                                  "🧾 Hafta içi 42 emir", "🏆 En iyi trader: 0xaaaaaa… · +20,00 $ (slot K/Z)", "🔻 En kötü trader: 0xbbbbbb… · −5,50 $ (slot K/Z)"]
    ilk = tg.msg_haftalik("sanal", 1000.0, 990.0, None, None, None, 3, [])
    assert "Başlangıçtan beri: −10,00 $" in ilk and "BTC kıyası: bu hafta için veri yok" in ilk and "Sahada trader yok" in ilk
