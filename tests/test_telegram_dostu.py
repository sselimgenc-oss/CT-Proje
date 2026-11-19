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
