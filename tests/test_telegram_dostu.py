"""Kullanıcı dostu Telegram standardı: `[CT]` ilk satır, en çok 6 satır, kod adı yok, INFO sessiz, bastırılan türler kayda gider, aynı uyarı 6 saatte bir + tek "Düzeldi"."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from copytrade.canli import pano, telegram as tg

KOD_ADI = re.compile(r"(?<![/\w])[a-z]+_[a-z_]+")             # snake_case kod adı ("/hepsini_kapat" gibi komutlar hariç)
ADR = "0xf43a34aaaaaaaa"


class Post:
    def __init__(self):
        self.yukler: list[dict] = []

    def __call__(self, url, yuk):
        self.yukler.append(yuk)
        return {"ok": True}


def _t(**kw):
    post, kayit = Post(), []
    t = tg.Telegram("T", "5", post, kayit=kayit.append, **kw)
    return t, post, kayit


def _emirler(n, durum="dolu"):
    return [{"adres": ADR[:-1] + str(i), "coin": f"C{i}", "yon": "B" if i % 2 else "A", "usd": 10.0 + i, "px": 1.0, "kayma": 0.0001, "durum": durum, "eylem": ("ac", "artir", "azalt", "kapat")[i % 4]}
            for i in range(n)]


def _stoplu_emirler():
    return [{"adres": ADR, "coin": c, "yon": "B", "usd": 20.0, "durum": "dolu", "eylem": "ac"} for c in ("BTC", "ETH", "SOL", "ADA", "DOGE", "XRP")] + [
        {"adres": ADR, "coin": "BTC", "yon": "A", "usd": 20.0, "durum": "dolu", "eylem": "kapat", "kapandi": True, "kz": 1.2, "neden_kod": "tam_kapanis"},
        {"adres": ADR, "coin": "ETH", "yon": "A", "usd": 20.0, "durum": "dolu", "eylem": "kapat", "kapandi": True, "kz": -4.2, "neden_kod": "felaket_stop"},
        {"adres": ADR, "coin": "SOL", "yon": "A", "usd": 10.0, "durum": "dolu", "eylem": "azalt"}, {"adres": ADR, "coin": "ADA", "yon": "B", "usd": 10.0, "durum": "dolu", "eylem": "artir"}]


def _tum_ornekler() -> dict[str, str]:
    kasa = (1012.6, 1005.0, 1000.0)
    return {
        "emir_sanal": tg.msg_emir(ADR, "ETH", "B", 11.0, 2000.0, 0.00012, "dolu", "sanal", "ac"),
        "emir_gercek_sorun": tg.msg_emir(ADR, "BTC", "A", 27.3, None, None, "red", "gercek", "kapat", "hl_err: Invalid nonce"),
        "emir_ozeti_cok": tg.msg_emir_ozeti("sanal", _emirler(12), 5),
        "emir_ozeti_gercek_sorunlu": tg.msg_emir_ozeti("gercek", _emirler(9, "red"), 0.1),
        "saatlik": tg.msg_sanal_saatlik(0, 3_600_000, 60, _emirler(8, "kismi"), {"gec_acilis": 5, "slot_tavani": 9}, kasa, 7, {}, "📐 Kopya sapması: 4 coin"),
        "saatlik_stoplu": tg.msg_sanal_saatlik(0, 3_600_000, 60, _stoplu_emirler(), {}, kasa, None, None, "", "🔽 Zarar küçültme: Kartal-78 ½ (5 kapanış, −3,20 $)"),
        "saatlik_gercek": tg.msg_sanal_saatlik(0, 3_600_000, 60, _stoplu_emirler(), {}, kasa, kip="gercek"),
        "alarm": tg.alarm("ALARM: kasa sınırı aşıldı", "Kasa 1.200 $ > sınır 1.000 $.\nYeni pozisyon açılmıyor."),
        "alarm_eylemli": tg.alarm("ALARM: API cüzdanı süresi", "HL API cüzdanının süresi 5 gün sonra bitiyor.\nSüre dolunca emirler reddedilir.", senden="Yeni API cüzdanı kaydetmen gerekiyor."),
        "duzeldi": tg.duzeldi_metni("HL okuması", "Yeni pozisyonlar yeniden serbest."),
        "kapat_alindi": tg.msg_kapat_alindi("gercek"),
    }


def test_her_tur_en_cok_6_satir_ve_kod_adi_yok():
    for ad, metin in _tum_ornekler().items():
        gidecek = f"{tg.PROJE_ETIKETI} {tg.onem_duzeyi(metin)}\n{metin}"
        assert len(gidecek.splitlines()) <= 6, (ad, gidecek)
        assert "`" not in metin and "durum/" not in metin and not KOD_ADI.search(metin), (ad, KOD_ADI.findall(metin))
        assert "K‑41" not in metin and "(K-" not in metin, ad


def test_ilk_satir_ct_onem_ve_info_sessiz_warn_crit_sesli():
    t, post, _ = _t()
    t.gonder("🧾 Son 1 saat: 2 emir · sanal")
    t.gonder(tg.alarm("ALARM: kasa sınırı aşıldı", "x"))
    t.gonder(tg.alarm("UYARI: kadro kasası farklı", "x", "⚠️"))
    t.gonder(tg.duzeldi_metni("HL okuması", "ok"), "INFO")
    ilkler = [y["text"].split("\n")[0] for y in post.yukler]
    assert ilkler == ["[CT] 🧾 Son 1 saat: 2 emir · sanal", "[CT] 🚨 Kasa sınırı aşıldı", "[CT] ⚠️ Kadro kasası farklı", "[CT] ✅ Düzeldi: HL okuması"]       # seviye kelimesi yok
    assert not any(re.search(r"\b(INFO|WARN|CRIT)\b", y["text"]) for y in post.yukler)
    assert [y["disable_notification"] for y in post.yukler] == [True, False, False, True]


def test_kritik_durdurma_mesajlari_hala_gider_ve_sesli():
    t, post, _ = _t()
    assert t.gonder(tg.alarm("Motor durdu", "Tüm pozisyonlar kapandı.", "🛑", senden="Yeniden açmak için sunucuda elle işlem gerekir."))
    assert t.gonder(tg.alarm("ALARM: günlük kayıp sınırı", "Bugün yeni pozisyon açılmıyor."))
    assert [y["disable_notification"] for y in post.yukler] == [False, False]
    assert all(y["text"].startswith(("[CT] 🛑 ", "[CT] 🚨 ")) for y in post.yukler)


def test_bastirilan_tur_gitmez_ama_kayda_yazilir_ve_anahtarla_geri_acilir():
    t, post, kayit = _t()
    for tur in ("saha_giris", "saha_cikis", "saha_uyari", "saatlik_bos"):
        assert t.gonder(f"mesaj {tur}", tur=tur) is False
    assert post.yukler == [] and [k["tur"] for k in kayit if k["olay"] == "tg_bastirildi"] == ["saha_giris", "saha_cikis", "saha_uyari", "saatlik_bos"]
    t.bastirilan.discard("saha_giris")                                  # kod anahtarı: tür geri açılabilir
    assert t.gonder("mesaj", tur="saha_giris") is True and len(post.yukler) == 1


def test_ayni_uyari_6_saatte_bir_ve_duzelince_tek_duzeldi():
    saat = [1_000_000.0]
    t, post, kayit = _t(saat_s=lambda: saat[0])
    w = tg.alarm("ALARM: HL okunamıyor", "3 ardışık okuma başarısız.")
    assert t.uyar("hl", w) is True
    for dk in (10, 60, 200):                                        # 6 saat dolmadan tekrar YOK
        saat[0] += dk * 60
        assert t.uyar("hl", w) is False
    assert len(post.yukler) == 1 and any(k["olay"] == "telegram_tekrar_atlandi" for k in kayit)
    saat[0] = 1_000_000.0 + 6 * 3600 + 1                               # 6 saat doldu: bir kez daha
    assert t.uyar("hl", w) is True and len(post.yukler) == 2
    d = tg.duzeldi_metni("HL okuması", "Yeni pozisyonlar yeniden serbest.")
    assert t.duzeldi("hl", d) is True                                  # tek Düzeldi
    assert t.duzeldi("hl", d) is False                                 # ikinci kez yok
    assert t.duzeldi("hic_uyarilmadi", d) is False                     # hiç uyarılmayan için de yok
    assert len(post.yukler) == 3 and post.yukler[-1]["text"].startswith("[CT] ✅ Düzeldi") and post.yukler[-1]["disable_notification"] is True
    assert t.uyar("hl", w) is True                                     # düzelmiş sorun yeniden olursa hemen uyarılır


def test_motor_alarm_metinlerinde_kod_adi_geri_tirnak_ve_dosya_adi_yok():
    """motor.py içindeki tüm `tg.alarm(...)` sabit metinleri (f-string ifadeleri hariç): geri tırnak, `durum/DUR` dosya adı ve snake_case kod adı yok; 4 satırı (başlık + gövde + senden) aşmaz."""
    kaynak = (Path(__file__).resolve().parents[1] / "copytrade" / "canli" / "motor.py").read_text()
    agac = ast.parse(kaynak)

    def sabitler(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.value
        elif isinstance(n, ast.FormattedValue):
            return                                                      # {ifade}: kod değil, çalışma zamanı değeri
        else:
            for c in ast.iter_child_nodes(n):
                yield from sabitler(c)

    sayi = 0
    for n in ast.walk(agac):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "alarm":
            metin = " ".join(x for a in n.args for x in sabitler(a))
            sayi += 1
            assert "`" not in metin and "durum/DUR" not in metin and not KOD_ADI.search(metin), (n.lineno, metin)
            satir = 2 + sum(x.count("\n") for a in n.args for x in sabitler(a)) + 1
            assert satir <= 5, (n.lineno, satir)                        # başlık + gövde(≤3) + senden, `[CT]` satırı ayrıca
    assert sayi > 40


def test_tg_kapsami_bastirilan_turler_kod_anahtari():
    assert {"saha_giris", "saha_cikis", "saha_uyari", "saatlik_bos"} <= set(tg.BASTIRILAN_TURLER)


# ---------------------------------------------------------------------------------------------- koordinatör ek kuralları (a)-(g)
def test_acildi_mesaji_2_satir_trader_adi_panodaki_ile_ayni_ve_sade_coin():
    from copytrade.canli import pano
    m = tg.msg_acildi(ADR, "SOL", "B", 150.25, 27.3, 120.2, "sanal")
    satirlar = m.splitlines()
    assert len(satirlar) == 2 and satirlar[0] == f"🟢 SOL LONG açıldı · trader {pano.kisa(ADR)} (sanal)"             # trader adı = pano.kisa
    assert satirlar[1] == "Giriş 150,25 · Tutar 27,3 $ · Stop 120,20" and "_" not in m and tg.kisa(ADR) == pano.kisa(ADR)
    assert tg.onem_duzeyi(m) == "INFO"


def test_kapandi_mesaji_dolar_yuzde_neden_zararda_kirmizi_ucgen_kirmizi_daire_yok():
    z = tg.msg_kapandi(ADR, "BTC", -1.2, -0.044, "felaket_stop", "sanal")
    assert z.splitlines() == [f"🔻 BTC kapandı · trader {tg.kisa(ADR)} (sanal)", "−1,20 $ (−%4,40) · Neden: stop"] and "🔴" not in z
    k = tg.msg_kapandi(ADR, "ETH", 3.5, 0.02, "tam_kapanis", "gercek")
    assert k.startswith("✅ ETH kapandı") and "+3,50 $ (+%2,00) · Neden: trader kapattı" in k and "GERÇEK PARA" in k
    assert all(len(x.splitlines()) == 2 and "🔴" not in x and not KOD_ADI.search(x) for x in (z, k))
    assert tg.kapanis_nedeni_tr("borsa_stop") == "stop" and tg.kapanis_nedeni_tr("trader_kapali_senkron") == "trader kapattı"


def test_kirmizi_daire_yalniz_kritik_mesajlarda():
    for ad, metin in _tum_ornekler().items():
        assert "🔴" not in metin, ad
    assert tg.onem_duzeyi(tg.msg_bot_durdu("komut", 2, "borsada duruyor")) == "CRIT"


def test_bot_durdu_kritik_sesli_acik_pozisyon_ve_stop_6_saat_sinirina_takilmaz():
    m = tg.msg_bot_durdu("zirve_dusus", 3, "borsada duruyor")
    assert m.splitlines()[0] == "🔴 Bot durdu" and "Açık pozisyon: 3 · Stop: borsada duruyor" in m and not KOD_ADI.search(m) and len(m.splitlines()) + 1 <= 6
    saat = [1_000_000.0]
    t, post, _ = _t(saat_s=lambda: saat[0])
    assert t.gonder(m, "CRIT", anahtar="bot_durdu:3")
    saat[0] += 600                                                       # 10 dk sonra yeniden durursa (6 saat dolmadan) YİNE gider
    assert t.gonder(m, "CRIT", anahtar="bot_durdu:3") and len(post.yukler) == 2
    assert all(y["disable_notification"] is False and y["text"].startswith("[CT] 🔴 Bot durdu\n") for y in post.yukler)


def test_motor_bot_durdu_mesaji_ve_yeniden_calisinca_tek_duzeldi(tmp_path):
    from tests.test_canli_motor import kur, olay, adr
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dur_tetikle("komut")
    durdu = [x for x in tgp.gonderilen if x.startswith("🔴 Bot durdu")]
    assert durdu and "Açık pozisyon: 0 · Stop: gerekmiyor" in durdu[0] and "Neden: sen /hepsini_kapat ile durdurdun" in durdu[0] and not KOD_ADI.search(durdu[0])
    assert (tmp_path / "durum" / "tg_bot_durdu").exists()
    (tmp_path / "durum" / "DUR").unlink()                                # sorun giderildi, bot yeniden başlıyor
    m2, hl2, saat2, tgp2 = kur(tmp_path, saat=saat)
    m2.baslat()
    assert not (tmp_path / "durum" / "tg_bot_durdu").exists()
    m2.kesinti_duzeldi_bildir(dict(m2._say_gun))                         # açılış yetişmesi sonrası
    d = [x for x in tgp2.gonderilen if "Düzeldi" in x]
    assert len(d) == 1 and "0 dk kapalı kaldı; bu sürede kaçan işlem yok." in d[0] and d[0].startswith("✅ Düzeldi: bot yeniden çalışıyor")
    m2.kesinti_duzeldi_bildir(dict(m2._say_gun))
    assert len([x for x in tgp2.gonderilen if "Düzeldi" in x]) == 1       # ikinci kez Düzeldi yok


def test_gunluk_kayip_yuzde_80_gunde_bir_uyari_ve_limit_doldu_acik_pozisyonu_soyler(tmp_path):
    from tests.test_canli_motor import kur, olay, adr
    m, hl, saat, tgp = kur(tmp_path, kasa=10_000.0)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    simdi = saat()
    m.risk.ozsermaye_isle(10_000.0, simdi)
    m.risk.gun_basi = 10_000.0
    sinir = float(m.rules["canli_gunluk_kayip_oran"])
    m.ozsermaye = lambda: 10_000.0 * (1 - 0.8 * sinir)                    # sanal 10.000 $: %4 kayıp (limit %5'in %80'i) → özsermaye 9.600 $
    m._risk(simdi)
    m._risk(simdi + 60_000)
    uy = [x for x in tgp.gonderilen if x.startswith("⚠️ Günlük kayıp limitine yaklaşıldı")]
    assert len(uy) == 1 and tg.onem_duzeyi(uy[0]) == "WARN" and "Senden bir şey gerekmiyor." in uy[0] and len(uy[0].splitlines()) + 1 <= 6
    assert "özsermaye 9.600,00 $" in uy[0] and "Bugünkü kayıp %4,0 (limit %5)" in uy[0]
    m.ozsermaye = lambda: 10_000.0 * (1 - sinir)                          # limit doldu
    m._risk(simdi + 120_000)
    dol = [x for x in tgp.gonderilen if "Günlük kayıp sınırı" in x]
    assert len(dol) == 1 and "1 açık pozisyon izlenmeye devam ediyor" in dol[0] and "yeni pozisyon açılmıyor" in dol[0]


def test_senden_satiri_sunucu_journalctl_dosya_adi_icermez():
    """(e) 'Senden' satırı yalnız kodlama bilmeyenin yapabileceği şeyi söyler: motor.py `senden=` sabitleri ve sunucu betiğindeki 'Senden/Bana haber ver' satırlarında sunucu/journalctl/dosya adı yok."""
    kok = Path(__file__).resolve().parents[1]
    agac = ast.parse((kok / "copytrade" / "canli" / "motor.py").read_text())
    metinler = [k.value.value for n in ast.walk(agac) if isinstance(n, ast.Call) for k in n.keywords if k.arg == "senden" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)]
    sh = (kok / "deploy" / "sanal_guncelle.sh").read_text() + (kok / "deploy" / "alarm.sh").read_text()
    metinler += [s for s in sh.splitlines() if s.strip().startswith(("Senden", "Bana haber", "Sorun sürerse"))] + [tg.SENDEN_YOK]
    assert len(metinler) > 8
    yasak = re.compile(r"sunucu|journalctl|dosya|\.json|\.sh|durum/|systemctl|ssh", re.I)
    for t in metinler:
        assert not yasak.search(t) and not KOD_ADI.search(t), t


def tests_adr():
    from tests.test_canli_motor import adr
    return adr(1)


def test_baslik_ilk_satir_ct_ve_baslik_seviye_kelimesi_yok():
    t, post, _ = _t()
    t.gonder(tg.alarm("ALARM: kasa sınırı aşıldı", "x"))
    t.gonder(tg.msg_acildi(ADR, "SOL", "B", 150.25, 27.3, 120.2, "sanal"))
    t.gonder(tg.msg_bot_durdu("komut", 1, "borsada duruyor"))
    assert [y["text"].split("\n")[0] for y in post.yukler] == ["[CT] 🚨 Kasa sınırı aşıldı", f"[CT] 🟢 SOL LONG açıldı · trader {tg.kisa(ADR)} (sanal)", "[CT] 🔴 Bot durdu"]
    assert [y["disable_notification"] for y in post.yukler] == [False, True, False]            # seviye iç mantıkta: INFO sessiz, kritik sesli


def test_motor_kapali_bekci_ve_cokme_bot_durdu_biciminde(tmp_path):
    from copytrade.canli import motor as mt
    from tests.test_canli_motor import kur, olay, adr
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dur_tetikle("komut")
    m._duraklat(False)                                                    # /devam, motor /hepsini_kapat ile kapalıyken
    kapali = [x for x in tgp.gonderilen if x.startswith("🔴 Bot durdu") and "/devam bunu açmaz" in x]
    assert kapali and "Açık pozisyon: 0 · Stop: gerekmiyor (pozisyon yok)" in kapali[0]
    m2, _h, _s, tgp2 = kur(tmp_path / "x")
    m2.baslat()
    m2.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    cikis = []
    b = mt.Bekci(m2, 180, saat=lambda: 1000.0, cik=cikis.append, alarm_bekle_sn=1.0)
    b.son = 0.0
    b.kontrol()
    bd = [x for x in tgp2.gonderilen if x.startswith("🔴 Bot durdu")]
    assert bd and "Neden: motor dondu" in bd[0] and "Açık pozisyon: 1 · Stop: bot kapalıyken yazılım stopu çalışmıyor" in bd[0] and (tmp_path / "x" / "durum" / "tg_bot_durdu").exists()


# ---------------------------------------------------------------------------------------------- danışman düzeltmeleri (kopya doğruluğu, artırma/azaltma, bot durdu, güncelleme, işlem sınırı)
def _islem_satirlari(tmp_path) -> list[str]:
    """K-79: açıldı/kapandı AYRI Telegram mesajı değil; tek tek metin kayda (`tg_mesaj`, tür islem_satiri) ve saatlik özet satırına gider. Biçim denetimleri bu kayıttan okunur."""
    from tests.test_canli_motor import kayitlar
    return [k["metin"] for k in kayitlar(tmp_path, "tg_mesaj") if k.get("tur") == "islem_satiri"]


def _kur10k(tmp_path, **kurallar):
    from tests.test_canli_motor import kur
    m, hl, saat, tgp = kur(tmp_path, kasa=10_000.0, kurallar=kurallar or None)
    m.baslat()
    return m, saat, tgp


def test_acildi_trader_fiyati_fark_ve_gecikme_eki_yalniz_esik_asilinca():
    m = tg.msg_acildi(ADR, "SOL", "B", 150.25, 27.3, 120.2, "sanal", trader_px=150.10)
    assert m.splitlines()[1] == "Giriş 150,25 (trader 150,10 · fark %0,10) · Tutar 27,3 $ · Stop 120,20"
    g = tg.msg_acildi(ADR, "SOL", "B", 150.25, 27.3, 120.2, "sanal", trader_px=150.10, gecikme_sn=45)
    assert g.splitlines()[1].endswith("· Stop 120,20 · 45 sn geç") and len(g.splitlines()) == 2


def test_motor_acildi_gercek_trader_fiyati_ve_esik_alti_gecikmede_ek_yok(tmp_path):
    from tests.test_canli_motor import olay, adr
    m, saat, tgp = _kur10k(tmp_path)
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat, yas_ms=100_000))        # 100 sn < canli_olay_stale_sn (120)
    a = [x for x in _islem_satirlari(tmp_path) if x.startswith("🟢 BTC LONG açıldı")]
    assert len(a) == 1 and "(trader 100,00 · fark %" in a[0] and "sn geç" not in a[0] and len(a[0].splitlines()) == 2


def test_kapandi_toplam_tutar_artirma_ve_yuzde_toplam_tutara_gore(tmp_path):
    from tests.test_canli_motor import olay, adr
    m, saat, tgp = _kur10k(tmp_path)
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))            # açılış
    m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 300.0, saat))          # artırma
    m.olay_isle(olay("a:3", adr(1), "BTC", "A", 600, 100.0, 600.0, saat))          # tam kapanış
    k = [x for x in _islem_satirlari(tmp_path) if " BTC kapandı · trader " in x]
    assert len(k) == 1 and len(k[0].splitlines()) == 3
    ust = k[0].splitlines()
    import re as _re
    toplam = float(_re.search(r"Toplam tutar ([\d.,]+) \$ \(1 artırma\)", ust[2]).group(1).replace(".", "").replace(",", "."))
    kz = float(_re.search(r"([+−])([\d.,]+) \$", ust[1]).group(0).replace("+", "").replace("−", "-").replace(" $", "").replace(".", "").replace(",", "."))
    pct = float(_re.search(r"\(([+−])%([\d.,]+)\)", ust[1]).group(0).strip("()").replace("%", "").replace("+", "").replace("−", "-").replace(",", "."))
    assert toplam > 40 and abs(pct - round(kz / toplam * 100, 2)) < 0.011                 # yüzde TOPLAM tutara göre
    assert m._say_gun["artir"] == 1 and m._say_gun["ac"] == 1


def test_kapandi_kz_pano_ile_ayni_net_kapanis_ucreti_dusulur(tmp_path):
    """Kapandı mesajındaki $ = pozisyonun TÜM dolumlarının (gerçekleşen − ücret; giriş/artırma ücreti dahil) toplamı; pano KAPANAN neti ile aynı (D3)."""
    from tests.test_canli_motor import olay, adr
    m, saat, tgp = _kur10k(tmp_path)
    m.olay_isle(olay("b:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("b:2", adr(1), "BTC", "A", 150, 110.0, 300.0, saat))          # azaltma
    m.olay_isle(olay("b:3", adr(1), "BTC", "A", 150, 120.0, 150.0, saat))          # tam kapanış
    from tests.test_canli_motor import kayitlar
    kap = [e for e in kayitlar(tmp_path, "emir") if e.get("reduce_only") and e.get("durum") in ("dolu", "kismi")]
    tum = [e for e in kayitlar(tmp_path, "emir") if e.get("durum") in ("dolu", "kismi") and e.get("pnl_usd") is not None]
    beklenen = sum(float(e["pnl_usd"]) - float(e.get("ucret") or 0) for e in tum)
    tg_k = [x for x in kayitlar(tmp_path, "tg_mesaj") if x.get("neden") not in (None, "ac") and x.get("coin") == "BTC"]
    assert len(kap) == 2 and tg_k and abs(tg_k[-1]["pnl"] - beklenen) < 1e-6 and any(float(e.get("ucret") or 0) > 0 for e in kap)


def test_trader_acti_biz_acamadik_sessiz_6_saat_ve_kural_gereji_atlananlar_gonderilmez(tmp_path):
    from tests.test_canli_motor import olay, adr
    m, saat, tgp = _kur10k(tmp_path)
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat, yas_ms=130_000))        # geç görülen açılış = kaçırılan
    m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 0.0, saat, yas_ms=131_000))
    # Telegram sadeleştirme (20.11): geç görülen açılış RUTİN → Telegram'a gitmez (tür kopya_kacan, kayda tg_bastirildi); gerçek hata (emir reddedildi) aşağıdaki testte gider
    assert not [x for x in tgp.gonderilen if "biz açamadık" in x]
    m.olay_isle(olay("a:3", adr(1), "@142", "B", 300, 100.0, 0.0, saat))                       # spot = kural gereği atlanır
    assert not [x for x in tgp.gonderilen if "biz açamadık" in x]
    assert "kopya_kacan" in tg.BASTIRILAN_TURLER


def test_trader_acti_biz_acamadik_gercek_hata_gonderilir_6_saatte_bir(tmp_path):
    from tests.test_canli_motor import adr
    m, saat, tgp = _kur10k(tmp_path)
    m._kopya_hata("ac", adr(1), "BTC", "emir reddedildi")
    m._kopya_hata("ac", adr(1), "BTC", "emir reddedildi")
    k = [x for x in tgp.gonderilen if x.startswith("ℹ️ Trader açtı, biz açamadık")]
    assert len(k) == 1 and "emir reddedildi" in k[0] and "BTC · trader" in k[0]                # 6 saat kuralı: ikinci mesaj yok
    assert tg.onem_duzeyi(k[0]) == "INFO"


def test_trader_kapatti_biz_kapatamadik_mesaji(tmp_path):
    from tests.test_canli_motor import adr
    m, saat, tgp = _kur10k(tmp_path)
    m._eksik_ekle(adr(1), "BTC", "kapat", 0.0, "tam_kapanis", saat(), deneme=len(m.rules["canli_kapanis_bantlari"]))
    k = [x for x in tgp.gonderilen if x.startswith("ℹ️ Trader kapattı, biz kapatamadık")]
    assert len(k) == 1 and "kapanış emri doldurulamadı" in k[0]


def test_islem_mesaji_ayri_gitmez_ust_sinir_yok_saatlik_tek_ozet(tmp_path):
    """K-79: eski saatlik üst sınır + "+N işlem daha" satırı kalktı; hiçbir açıldı/kapandı ayrı gitmez, hepsi saatlik özet satırı (sınırsız kalem, satırda ilk 4 + "… +N")."""
    from tests.test_canli_motor import olay, adr
    m, saat, tgp = _kur10k(tmp_path, canli_telegram_islem_saat_max=2)
    for i, c in enumerate(("BTC", "ETH", "SOL", "BNB", "DOGE", "XRP")):
        m.olay_isle(olay(f"a:{i}", adr(1), c, "B", 300, 100.0, 0.0, saat))
    assert not [x for x in tgp.gonderilen if "açıldı · trader" in x or x.startswith("🧾 +")]
    assert len(_islem_satirlari(tmp_path)) == m._say_gun["ac"] >= 3
    saat.ms += 3_600_000 + 60_000
    m.emir_ozeti(saat())
    oz = [x for x in tgp.gonderilen if x.startswith("🧾 Son ")]
    assert len(oz) == 1 and oz[0].startswith("🧾 Son 1 saat: 6 emir (6 açılış)") and "… +" in oz[0]
    m.emir_ozeti(saat())
    assert len([x for x in tgp.gonderilen if x.startswith("🧾 Son ")]) == 1


def test_islem_mesajlari_sessiz_info(tmp_path):
    t, post, _ = _t()
    t.gonder(tg.msg_acildi(ADR, "SOL", "B", 150.25, 27.3, 120.2, "sanal"))
    t.gonder(tg.msg_kapandi(ADR, "SOL", -2.0, -0.05, "felaket_stop", "sanal"))
    t.gonder(tg.msg_kopya_hata("ac", "SOL", ADR, "geç görülen açılış"))
    assert [y["disable_notification"] for y in post.yukler] == [True] * 3


def test_gunluk_rapor_kopya_dogrulugu_artirma_azaltma_ve_guncelleme_ilk_3_satir():
    acik = [{"coin": "BTC", "sz": 0.5, "usd": 1234.0, "kz_usd": 12.34}]
    m = tg.msg_gunluk("sanal", 10_000, 10_025.0, 10_000.0, 12, 9, 11, acik, kopya_fark=0.0012, gecikme_sn=3.4, artir=5, azalt=2, guncelleme=2)
    s = m.splitlines()
    assert s[2].startswith("💰 Özsermaye: 10.025,00 $") and s[3].startswith("📈 Günün K/Z") and s[4].startswith("📌 Açık pozisyon")          # ilk 3 satır
    assert "🧾 Bugün 12 emir (5 artırma, 2 azaltma)" in m and "🎯 Kopya doğruluğu: ortalama fark %0,12 · ortalama gecikme 3 sn" in m and "🔄 Bot bugün 2 kez güncellendi" in m
    h = tg.msg_haftalik("sanal", 10_000.0, 10_100.0, 10_000.0, None, None, 5, [], acik_poz=3).splitlines()
    assert h[2].startswith("💰 Özsermaye") and h[3].startswith("📈 Hafta") and h[4] == "📌 Açık pozisyon: 3"


def test_motor_gunluk_metin_kopya_dogrulugu_ve_artirma_sayisi(tmp_path):
    from tests.test_canli_motor import olay, adr
    m, saat, tgp = _kur10k(tmp_path)
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 300.0, saat))
    metin = m._gunluk_metin()
    assert "(1 artırma, 0 azaltma)" in metin
    assert "🎯 Kopya doğruluğu: ortalama fark %" in metin and "ortalama gecikme" in metin


def test_guncelleme_bugun_saglik_dosyasindan(tmp_path):
    import json
    import time as _t2
    from copytrade.canli import gunluk_ozet
    yol = tmp_path / "s.json"
    yol.write_text(json.dumps({"zaman": _t2.time(), "guncelleme_bugun": 3}))
    assert gunluk_ozet.guncelleme_bugun({"SG_SAGLIK_SUNUCU": str(yol)}) == 3
    yol.write_text(json.dumps({"zaman": _t2.time() - 99_999, "guncelleme_bugun": 3}))
    assert gunluk_ozet.guncelleme_bugun({"SG_SAGLIK_SUNUCU": str(yol)}) is None
    assert gunluk_ozet.guncelleme_bugun({"SG_SAGLIK_SUNUCU": str(tmp_path / "yok.json")}) is None


def test_duzeldi_kesinti_suresi_ve_kacan_islem_varsa_sesli(tmp_path):
    m, saat, tgp = _kur10k(tmp_path)
    kayit = []
    gercek = m.tg.gonder
    m.tg.gonder = lambda metin, onem=None, anahtar=None, tur=None: (kayit.append((metin, onem)), gercek(metin, onem, anahtar, tur))[1]
    once = dict(m._say_gun)
    m._kesinti = {"sn": 12 * 60}
    m._say_gun["kapat"] += 1                                             # yetişmede trader'ın bir kapanışı bizde de uygulandı
    m.kesinti_duzeldi_bildir(once)
    assert kayit[-1][0].splitlines()[1] == "12 dk kapalı kaldı; bu sürede trader 1 pozisyon kapattı, bizde de kapatıldı." and kayit[-1][1] == "CRIT"      # kaçan işlem → sesli
    m._kesinti = {"sn": 5 * 60}
    m.kesinti_duzeldi_bildir(dict(m._say_gun))
    assert kayit[-1][0].splitlines()[1] == "5 dk kapalı kaldı; bu sürede kaçan işlem yok." and kayit[-1][1] == "INFO"                                  # kaçan yok → sessiz


def test_kasa_siniri_mesaji_olculen_seyin_adini_soyler(tmp_path):
    m, saat, tgp = _kur10k(tmp_path)
    m.kasa = 1_200.0
    m.risk.kasa_siniri_asildi = lambda kasa, ust=None: True
    m._risk(saat())
    x = [t for t in tgp.gonderilen if "Kasa sınırı aşıldı" in t]
    assert x and "Başlangıç sermayesi (kasa) 1.200 $ > izin verilen üst sınır" in x[0]


def _ikinci(tmp_path, yas_sn, aktif=False, **ek):
    import os as _os
    import subprocess as _sp
    import time as _tm
    kok = Path(__file__).resolve().parents[1]
    durum = tmp_path / "durum"
    durum.mkdir(exist_ok=True)
    (durum / "hesap.json").write_text('{"poz": {"0xa": {"BTC": {}, "ETH": {}}}}')
    if yas_sn is not None:
        (durum / "tg_bot_durdu").write_text(f"{int(_tm.time()) - yas_sn}\nsen /hepsini_kapat ile durdurdun\n")
    kayit = tmp_path / "kayit.txt"
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "curl").write_text(f'#!/bin/sh\ncat >/dev/null\nfor a in "$@"; do case "$a" in text=*) printf "%s" "$a" >> {kayit};; esac; done\nexit 0\n')
    (bin_ / "systemctl").write_text(f'#!/bin/sh\nexit {0 if aktif else 3}\n')
    for f in bin_.iterdir():
        f.chmod(0o755)
    env = {"PATH": f"{bin_}:{_os.environ['PATH']}", "ALARM_DURUM_DIZIN": str(durum), "TELEGRAM_BOT_TOKEN": "TOK123", "TELEGRAM_CHAT_ID": "42", "ALARM_DOGRULA_SN": "0", **ek}
    r = _sp.run(["bash", str(kok / "deploy" / "alarm_ikinci.sh")], env=env, capture_output=True, text=True)
    return r, kayit, durum


def test_bot_durdu_ikinci_mesaj_20_dk_sonra_orkestratore_yaz(tmp_path):
    r, kayit, durum = _ikinci(tmp_path, 100)                              # 100 sn: henüz erken
    assert r.returncode == 0 and not kayit.exists()
    r, kayit, durum = _ikinci(tmp_path, 1300)                             # 21+ dk: ikinci mesaj
    m = kayit.read_text()
    assert m.startswith("text=[CT] 🔴 Bot hâlâ kapalı (21 dk)\nNeden: sen /hepsini_kapat ile durdurdun\nAçık pozisyon: 2 · Stop: bot kapalıyken yazılım stopu çalışmıyor\n")
    assert m.endswith("Senden: orkestratöre 'CT botu durdu' yaz.") and (durum / "tg_bot_durdu_2").exists() and "TOK123" not in r.stdout + r.stderr
    kayit.unlink()
    _ikinci(tmp_path, 1300)                                               # yalnız bir kez
    assert not kayit.exists()


def test_bot_durdu_ikinci_mesaj_bot_calisiyorsa_yok(tmp_path):
    r, kayit, durum = _ikinci(tmp_path, 1300, aktif=True)
    assert not kayit.exists() and not (durum / "tg_bot_durdu_2").exists()


def test_acildi_kademeli_fiyat_ondalik():
    """Pano ile aynı kademeli ondalık: ≥1 $ → 2, <1 $ → 4, <0,01 $ → 6; Türkçe virgül + binlik nokta (Giriş, trader, Stop)."""
    assert tg.fiyat(115) == "115,00" and tg.fiyat(115.008) == "115,01" and tg.fiyat(26388) == "26.388,00" and tg.fiyat(21110.4) == "21.110,40"
    assert tg.fiyat(0.5) == "0,5000" and tg.fiyat(0.0123) == "0,0123" and tg.fiyat(0.00123456) == "0,001235"
    assert pano.fiyat is tg.fiyat
    m = tg.msg_acildi(ADR, "BTC", "B", 26388.0, 50.0, 21110.4, "sanal", trader_px=26388.0)
    assert "Giriş 26.388,00 (trader 26.388,00 · fark %0,00)" in m and m.endswith("Stop 21.110,40")
    m = tg.msg_acildi(ADR, "SOL", "B", 115.008, 50.0, 115.0, "sanal")
    assert "Giriş 115,01 " in m and "Stop 115,00" in m
    m = tg.msg_acildi(ADR, "DOGE", "A", 0.0834, 50.0, 0.0917, "sanal")
    assert "Giriş 0,0834" in m and "Stop 0,0917" in m
    assert "Fiyat 26.388,00" in tg.msg_emir(ADR, "BTC", "B", 50.0, 26388.0, None, "dolu", "sanal", "ac")
