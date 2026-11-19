"""Kullanıcı dostu Telegram standardı: `[CT]` ilk satır, en çok 6 satır, kod adı yok, INFO sessiz, bastırılan türler kayda gider, aynı uyarı 6 saatte bir + tek "Düzeldi"."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from copytrade.canli import telegram as tg

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


def _tum_ornekler() -> dict[str, str]:
    kasa = (1012.6, 1005.0, 1000.0)
    return {
        "emir_sanal": tg.msg_emir(ADR, "ETH", "B", 11.0, 2000.0, 0.00012, "dolu", "sanal", "ac"),
        "emir_gercek_sorun": tg.msg_emir(ADR, "BTC", "A", 27.3, None, None, "red", "gercek", "kapat", "hl_err: Invalid nonce"),
        "emir_ozeti_cok": tg.msg_emir_ozeti("sanal", _emirler(12), 5),
        "emir_ozeti_gercek_sorunlu": tg.msg_emir_ozeti("gercek", _emirler(9, "red"), 0.1),
        "saatlik": tg.msg_sanal_saatlik(0, 3_600_000, 60, _emirler(8, "kismi"), {"gec_acilis": 5, "slot_tavani": 9}, kasa, 7, {}, "📐 Kopya sapması: 4 coin"),
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
    assert ilkler == ["[CT] INFO", "[CT] CRIT", "[CT] WARN", "[CT] INFO"]
    assert [y["disable_notification"] for y in post.yukler] == [True, False, False, True]


def test_kritik_durdurma_mesajlari_hala_gider_ve_sesli():
    t, post, _ = _t()
    assert t.gonder(tg.alarm("Motor durdu", "Tüm pozisyonlar kapandı.", "🛑", senden="Yeniden açmak için sunucuda elle işlem gerekir."))
    assert t.gonder(tg.alarm("ALARM: günlük kayıp sınırı", "Bugün yeni pozisyon açılmıyor."))
    assert [y["disable_notification"] for y in post.yukler] == [False, False]
    assert all(y["text"].startswith("[CT] CRIT\n") for y in post.yukler)


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
    assert len(post.yukler) == 3 and post.yukler[-1]["text"].startswith("[CT] INFO\n✅ Düzeldi") and post.yukler[-1]["disable_notification"] is True
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
    assert len(satirlar) == 2 and satirlar[0] == f"🟢 SOL AL açıldı · trader {pano.kisa(ADR)} (sanal)"             # trader adı = pano.kisa
    assert satirlar[1] == "Giriş 150,25 · Tutar 27,3 $ · Stop 120,2" and "_" not in m and tg.kisa(ADR) == pano.kisa(ADR)
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
    assert all(y["disable_notification"] is False and y["text"].startswith("[CT] CRIT\n🔴 Bot durdu") for y in post.yukler)


def test_motor_bot_durdu_mesaji_ve_yeniden_calisinca_tek_duzeldi(tmp_path):
    from tests.test_canli_motor import kur, olay, adr
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dur_tetikle("komut")
    durdu = [x for x in tgp.gonderilen if x.startswith("🔴 Bot durdu")]
    assert durdu and "Açık pozisyon: 0 · Stop: gerekmiyor" in durdu[0] and "Neden: komut" in durdu[0] and not KOD_ADI.search(durdu[0])
    assert (tmp_path / "durum" / "tg_bot_durdu").exists()
    (tmp_path / "durum" / "DUR").unlink()                                # sorun giderildi, bot yeniden başlıyor
    m2, hl2, saat2, tgp2 = kur(tmp_path, saat=saat)
    m2.baslat()
    d = [x for x in tgp2.gonderilen if "Düzeldi" in x]
    assert len(d) == 1 and "bot yeniden çalışıyor" in d[0] and not (tmp_path / "durum" / "tg_bot_durdu").exists()
    m3, *_r = kur(tmp_path, saat=saat)
    m3.baslat()
    assert not [x for x in _r[2].gonderilen if "Düzeldi" in x]           # ikinci kez Düzeldi yok


def test_gunluk_kayip_yuzde_80_gunde_bir_uyari_ve_limit_doldu_acik_pozisyonu_soyler(tmp_path):
    from tests.test_canli_motor import kur, olay, adr
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    simdi = saat()
    m.risk.ozsermaye_isle(1000.0, simdi)
    m.risk.gun_basi = 1000.0
    sinir = float(m.rules["canli_gunluk_kayip_oran"])
    m.ozsermaye = lambda: 1000.0 * (1 - 0.8 * sinir)                      # kayıp = limitin %80'i
    m._risk(simdi)
    m._risk(simdi + 60_000)
    uy = [x for x in tgp.gonderilen if x.startswith("⚠️ Günlük kayıp limitine yaklaşıldı")]
    assert len(uy) == 1 and tg.onem_duzeyi(uy[0]) == "WARN" and "Senden bir şey gerekmiyor." in uy[0] and len(uy[0].splitlines()) + 1 <= 6
    m.ozsermaye = lambda: 1000.0 * (1 - sinir)                            # limit doldu
    m._risk(simdi + 120_000)
    dol = [x for x in tgp.gonderilen if "ALARM: günlük kayıp sınırı" in x]
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
