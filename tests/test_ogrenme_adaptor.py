"""CT ortak öğrenme adaptörü: takma ad (adres sızmaz), Aday kaydı (altın örnek), ders döngüsü (yalnız risk azaltır), emekli (açılış engel / kapanış serbest), çarpan sınırı, geri alma, saatlik sarma."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from copytrade.canli import ogrenme_adaptor as oa
from copytrade.canli.hesap import Hesap
from copytrade.ortak_ogrenme import notlar
from copytrade.ortak_ogrenme.kayit import Aday, aday_to_dict
from tests.test_canli_motor import SAAT, adr, kayitlar, kur, olay

GUN = 86_400_000


def ms(g, s=12):
    return int(datetime(2027, 1, g, s, tzinfo=timezone.utc).timestamp() * 1000)


def yeni(tmp_path, **kural):
    olaylar, mesajlar = [], []
    o = oa.Ogrenme({**kural}, tmp_path / "ogr", "sanal", lambda: ms(19), olaylar.append, mesajlar.append)
    return o, olaylar, mesajlar


def tum_metin(klasor: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in klasor.rglob("*") if p.is_file())


def hazirla(o, alias, kayiplar, ilk_gun=16):
    """Hafta sonu kayıpları yazar: doğum notu (16 Oca Cmt) + doğumdan sonraki (17 Oca Paz) `kayiplar` listesi (R). Dosyalar adaptörün kendi biçimiyle."""
    for i, r in enumerate([-2.0, *kayiplar]):
        gun = ilk_gun if i == 0 else ilk_gun + 1
        a = Aday(id=f"{alias}:{i}", proje="CT", kurulum=alias, enstruman="BTC/USD", varlik_sinifi="kripto", yon="long", ts=datetime(2027, 1, gun, 1 + i, tzinfo=timezone.utc),
                 alindi=True, r=r, seans="weekend")
        oa._ekle_satir(o.adaylar_yolu, aday_to_dict(a))
        et, metin = notlar.not_yaz(a) if r < 0 else (["sonuc:kazanc"], "")
        oa._ekle_satir(o.notlar_yolu, {"id": a.id, "note_date": f"2027-01-{gun}", "tags": et, "metin": metin})


# ---------------------------------------------------------------- kimlik
def test_takma_ad_adres_icermez_kararli_ve_ders_etiketi_uyumlu():
    a = oa.takma_ad(adr(1))
    assert re.fullmatch(r"T_[0-9a-f]{6}", a) and "0x" not in a
    assert a == oa.takma_ad(adr(1).upper().replace("0X", "0x")) == oa.takma_ad("  " + adr(1) + " ")       # büyük/küçük harf ve boşluk fark etmez
    assert a != oa.takma_ad(adr(2))
    assert notlar.valid_tag(f"ders:seans_kapali:{a}")


# ---------------------------------------------------------------- Aday kaydı (altın örnek)
def test_kapanan_islem_aday_olur_altin_ornek(tmp_path):
    """Long 1 BTC @100 (açılış 15 Oca Cum 08:00 UTC), 0,5 @110 (+5 $), kalan 0,5 @120 (+10 $), ücret 0,5+0,5 = 1 $. Net 14 $. 1R = en büyük nosyonel 100 $ × 0,02 = 2 $ → R = 7."""
    o, olaylar, _ = yeni(tmp_path)
    h = Hesap(1000.0, 3.0)
    h.dinleyici = o.dolum
    h.uygula(adr(1), "BTC", "B", 1.0, 100.0, 0.5, ms(15, 8))
    assert o.iz and not o.adaylar_yolu.exists()                                   # açık pozisyon: henüz Aday yok
    h.uygula(adr(1), "BTC", "A", 0.5, 110.0, 0.5, ms(15, 10))
    assert not o.adaylar_yolu.exists()
    h.uygula(adr(1), "BTC", "A", 0.5, 120.0, 0.0, ms(15, 12))
    satirlar = [json.loads(x) for x in o.adaylar_yolu.read_text(encoding="utf-8").splitlines()]
    assert len(satirlar) == 1 and not o.iz
    a = satirlar[0]
    assert a["proje"] == "CT" and a["kurulum"] == oa.takma_ad(adr(1)) and a["yon"] == "long" and a["alindi"] is True
    assert a["r"] == pytest.approx(7.0) and a["seans"] == "open" and a["ts"] == "2027-01-15T08:00:00Z"
    assert a["etiketler"] == ["coin:BTC", "yon:long", "kaldirac:k_dusuk", "sure:sure_orta"]
    assert a["cikis"]["net_usd"] == 14.0 and a["cikis"]["bars_held"] == 4.0 and a["ozellikler"]["kaldirac"] == 3.0
    n = json.loads(o.notlar_yolu.read_text(encoding="utf-8").splitlines()[0])
    assert n["note_date"] == "2027-01-15" and "sonuc:kazanc" in n["tags"]
    assert olaylar[-1]["olay"] == "ogrenme_aday"
    assert "0x" not in tum_metin(tmp_path / "ogr")                                 # hiçbir yeni dosyada adres yok


def test_hafta_sonu_acilan_zarar_seans_weekend_ve_ders_adayi(tmp_path):
    o, _, _ = yeni(tmp_path)
    h = Hesap(1000.0, 3.0)
    h.dinleyici = o.dolum
    h.uygula(adr(1), "ETH", "A", 2.0, 50.0, 0.0, ms(16, 8))                        # short, Cumartesi
    h.uygula(adr(1), "ETH", "B", 2.0, 51.0, 0.0, ms(16, 9))                        # −2 $ ; 1R = 100 × 0,02 = 2 → R = −1
    a = json.loads(o.adaylar_yolu.read_text(encoding="utf-8"))
    n = json.loads(o.notlar_yolu.read_text(encoding="utf-8"))
    assert a["yon"] == "short" and a["seans"] == "weekend" and a["r"] == pytest.approx(-1.0)
    assert f"ders:seans_kapali:{oa.takma_ad(adr(1))}" in n["tags"]


def test_dinleyici_hatasi_hesabi_bozmaz():
    h = Hesap(1000.0, 3.0)
    h.dinleyici = lambda e: 1 / 0
    h.uygula(adr(1), "BTC", "B", 1.0, 100.0, 0.0, ms(15))
    assert h.sz(adr(1), "BTC") == 1.0


def test_kapali_veya_gercek_kipte_hicbir_sey_yapmaz(tmp_path):
    o = oa.Ogrenme({}, tmp_path / "g", "gercek", lambda: ms(19))
    assert o.aktif is False and o.acilis_engeli(adr(1)) is None and o.agirlik(adr(1)) == 1.0
    k = oa.Ogrenme({"ogrenme_aktif": False}, tmp_path / "k", "sanal", lambda: ms(19))
    assert k.aktif is False


# ---------------------------------------------------------------- ders döngüsü
def test_agirlik_dersi_uygulanir_sinirli_bildirilir_ve_tekrar_etmez(tmp_path):
    """4 hafta sonu kaybı × −2 R: toplam 8, shrink 10 → etki 8 × 4/14 = 2,2857 R (≥ 1,0 çarpan eşiği, < 3,0 emekli eşiği): çarpan 1 − 0,5 × 2,2857/3 = 0,6190."""
    o, olaylar, mesaj = yeni(tmp_path)
    alias = "T_aaaaaa"
    hazirla(o, alias, [-2.0] * 4)
    sonuc = o.degerlendir(ms(19))
    assert sonuc["uygulandi"] == [alias] and alias not in o.uyg["emekli"]
    c = o.uyg["carpan"][alias]
    assert c["deger"] == pytest.approx(0.619, abs=1e-3) and 0.5 <= c["deger"] <= 1.0
    assert [e["olay"] for e in olaylar if e["olay"].startswith("ders_")] == ["ders_uygulandi"]
    assert len(mesaj) == 1 and "BİLGİ" in mesaj[0] and alias in mesaj[0] and "0x" not in mesaj[0]
    assert o.degerlendir(ms(19, 14))["uygulandi"] == [] and len(mesaj) == 1          # aynı durum: tekrar olay/Telegram yok
    assert json.loads(o.uyg_yolu.read_text(encoding="utf-8"))["carpan"][alias]["deger"] == c["deger"]


def test_emekli_dersi_ve_asla_artirmama(tmp_path):
    o, olaylar, mesaj = yeni(tmp_path)
    alias = "T_bbbbbb"
    hazirla(o, alias, [-2.0] * 8)                                                    # toplam 16 → etki 16 × 8/18 = 7,11 R ≥ 3
    o.degerlendir(ms(19))
    assert alias in o.uyg["emekli"] and o.uyg["carpan"][alias]["deger"] == 0.5
    assert len(mesaj) == 1 and "kopyalanmıyor" in mesaj[0]


def test_ders_olmayan_veya_yetersiz_ornek_uygulanmaz(tmp_path):
    o, olaylar, _ = yeni(tmp_path)
    hazirla(o, "T_cccccc", [-2.0, -2.0])                                             # n = 2 < ogrenme_min_n (3)
    o.degerlendir(ms(19))
    assert not o.uyg["emekli"] and not o.uyg["carpan"]
    o2, _, _ = yeni(tmp_path / "b")
    hazirla(o2, "T_dddddd", [3.0, 3.0, 3.0, 3.0])                                    # koşul kazandırıyor → ders emekli (retired) → uygulanmaz
    o2.degerlendir(ms(19))
    assert not o2.uyg["emekli"] and not o2.uyg["carpan"]


def test_geri_alma_uygulamadan_sonra_zarar_ettiren_ders_kalkar(tmp_path):
    o, olaylar, _ = yeni(tmp_path)
    alias = "T_eeeeee"
    hazirla(o, alias, [-2.0] * 4)
    o.degerlendir(ms(19))
    assert alias in o.uyg["carpan"]
    kid = f"seans_kapali:{alias}"
    a = Aday(id="son", proje="CT", kurulum=alias, enstruman="BTC/USD", varlik_sinifi="kripto", yon="long", ts=datetime(2027, 1, 23, 12, tzinfo=timezone.utc), alindi=True, r=4.0, seans="weekend")
    oa._ekle_satir(o.adaylar_yolu, aday_to_dict(a))                                  # uygulamadan SONRA aynı koşulda +4 R: ders etkisi −4 ≤ −3 → geri al
    o.degerlendir(ms(24))
    assert alias not in o.uyg["carpan"] and alias not in o.uyg["emekli"] and kid in o.uyg["geri_alinan"]
    assert o.agirlik(adr(1)) == 1.0
    ev = [e for e in olaylar if e["olay"] == "ders_geri_alindi"]
    assert ev and ev[-1]["neden"] == "geri_alma"
    o.degerlendir(ms(25))                                                            # geri alınan ders bir daha uygulanmaz
    assert alias not in o.uyg["carpan"]


def test_fren_hepsini_geri_alir(tmp_path):
    o, olaylar, _ = yeni(tmp_path)
    alias = "T_ffffff"
    hazirla(o, alias, [-2.0] * 8)
    o.degerlendir(ms(19))
    assert alias in o.uyg["emekli"]
    for i in range(2):
        oa._ekle_satir(o.adaylar_yolu, aday_to_dict(Aday(id=f"s{i}", proje="CT", kurulum=alias, enstruman="BTC/USD", varlik_sinifi="kripto", yon="long",
                                                          ts=datetime(2027, 1, 23, 12 + i, tzinfo=timezone.utc), alindi=True, r=6.0, seans="weekend")))      # toplam −12 ≤ −10
    o.degerlendir(ms(24))
    assert not o.uyg["emekli"] and not o.uyg["carpan"]
    assert [e["neden"] for e in olaylar if e["olay"] == "ders_geri_alindi"][0] == "fren"


def test_hafta_degisimi_emekliyi_bitirir_tekrar_emekli_yapmaz_carpan_kalir(tmp_path):
    o, olaylar, _ = yeni(tmp_path)
    alias = "T_999999"
    hazirla(o, alias, [-2.0] * 8)
    o.degerlendir(ms(19))
    assert alias in o.uyg["emekli"]
    o.hafta_degisti()
    assert not o.uyg["emekli"] and any(e.get("neden") == "hafta_degisimi" for e in olaylar)
    o.degerlendir(ms(19, 20))
    assert not o.uyg["emekli"] and alias in o.uyg["carpan"] and o.uyg["carpan"][alias]["deger"] >= 0.5


def test_carpan_sinirlari_yapilandirma_ne_derse_desin(tmp_path):
    o, _, _ = yeni(tmp_path)
    for deger, beklenen in ((0.1, 0.5), (5.0, 1.0), (0.75, 0.75), (-3.0, 0.5)):
        o.uyg["carpan"][oa.takma_ad(adr(1))] = {"deger": deger}
        assert o.agirlik(adr(1)) == beklenen
    assert o.agirlik(adr(2)) == 1.0                                                  # bilinmeyen trader: değişmez
    o.uyg["carpan"][oa.takma_ad(adr(1))] = {"deger": "bozuk"}
    assert o.agirlik(adr(1)) == 1.0                                                  # hata → etki yok
    o2, _, _ = yeni(tmp_path / "b", ogrenme_emekli_etki_r=0.001, ogrenme_agirlik_etki_r=0.0)      # uç yapılandırma
    hazirla(o2, "T_123456", [-2.0] * 4)
    o2.degerlendir(ms(19))
    assert all(0.5 <= c["deger"] <= 1.0 for c in o2.uyg["carpan"].values())


def test_saatlik_sinir_ve_hata_sarmasi(tmp_path, monkeypatch):
    o, olaylar, _ = yeni(tmp_path)
    cagri = []
    monkeypatch.setattr(o, "degerlendir", lambda simdi: cagri.append(simdi))
    o.adim(ms(19, 10))
    o.adim(ms(19, 10) + 30 * 60_000)
    assert cagri == [ms(19, 10)]                                                     # 60 dk dolmadan ikinci çalışma yok
    o.adim(ms(19, 10) + SAAT)
    assert len(cagri) == 2

    def patla(simdi):
        raise RuntimeError("boom")
    monkeypatch.setattr(o, "degerlendir", patla)
    o.adim(ms(19, 10) + 3 * SAAT)                                                    # istisna dışarı çıkmaz
    assert olaylar[-1]["olay"] == "ogrenme_hata" and olaylar[-1]["asama"] == "degerlendirme"


# ---------------------------------------------------------------- motor entegrasyonu
def alias1():
    return oa.takma_ad(adr(1))


def test_motor_emekli_trader_acilis_engellenir_kapanis_serbest(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))                       # emekli ÖNCESİ açılış
    assert m.hesap.sz(adr(1), "BTC") > 0
    m.ogrenme.uyg["emekli"][alias1()] = {"ms": saat(), "etki": 5.0, "kimlikler": [f"seans_kapali:{alias1()}"]}
    s = m.olay_isle(olay("a:2", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat))                   # YENİ açılış: engel
    assert s[0].karar == "engel" and s[0].neden == "ders_emekli"
    s_art = m.olay_isle(olay("a:3", adr(1), "BTC", "B", 100, 100.0, 300.0, saat))             # artırma da engel
    assert s_art[0].karar == "engel" and s_art[0].neden == "ders_emekli"
    s_az = m.olay_isle(olay("a:4", adr(1), "BTC", "A", 150, 100.0, 300.0, saat))              # azaltma serbest
    assert s_az[0].eylem == "azalt" and s_az[0].karar == "emir"
    s_kap = m.olay_isle(olay("a:5", adr(1), "BTC", "A", 150, 100.0, 150.0, saat))             # kapanış serbest
    assert s_kap[0].eylem == "kapat" and s_kap[0].karar == "emir" and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)
    assert not any(e["adres"] == adr(1) and e["coin"] == "ETH" for e in kayitlar(tmp_path, "emir"))
    # kapanış Aday oldu; adres hiçbir öğrenme dosyasında yok
    assert len(m.ogrenme.adaylar_yolu.read_text(encoding="utf-8").splitlines()) == 1
    assert "0x" not in tum_metin(tmp_path / "durum" / "ogrenme")


def test_motor_cakar_degil_carpan_acilis_boyutunu_yalniz_kucultur(tmp_path):
    """Altın örnek (test_uctan_uca_*): slot 90,909 $, 0,30 oran → 27,2727 $. Çarpan 0,5 → 13,6364 $; çarpansız hâlde değişmez."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.ogrenme.uyg["carpan"][alias1()] = {"deger": 0.5, "ms": saat(), "etki": 3.0, "kimlikler": []}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert kayitlar(tmp_path, "emir")[0]["usd_istenen"] == pytest.approx(13.6364, abs=1e-4)
    m.ogrenme.uyg["carpan"][alias1()]["deger"] = 7.0                                          # bozuk büyük değer bile 1,0'ı aşamaz → artırma yok
    m2, _, saat2, _ = kur(tmp_path / "b")
    m2.baslat()
    m2.ogrenme.uyg["carpan"][alias1()] = {"deger": 7.0}
    m2.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat2))
    assert kayitlar(tmp_path / "b", "emir")[0]["usd_istenen"] == pytest.approx(27.2727, abs=1e-4)


def test_motor_ogrenme_adimi_dakikalik_dongude_hata_vermez(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    def patla(simdi):
        raise RuntimeError("boom")
    m.ogrenme.degerlendir = patla
    m.dakika()
    assert not [x for x in kayitlar(tmp_path, "adim_hata") if x.get("adim") == "ogrenme"]
    assert [x for x in kayitlar(tmp_path, "ogrenme_hata") if x["asama"] == "degerlendirme"]
