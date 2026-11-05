"""Telegram sanal kip saatlik özet (`canli_telegram_sanal_ozet_dk`): emirler pencerede TEK mesaj; emir yoksa mesaj yok; gerçek kip ve alarmlar anlık; vardiya sonu kalan gider; 0 = eski davranış."""
from __future__ import annotations

from copytrade.canli import telegram as tg
from tests.test_canli_motor import CHAT, RULES, SAAT, T0, TOKEN, SahteHL, SahteTG, Saat, adr, kadro, kur, mt, olay, satir, yu


def _ozetler(tgp):
    return [x for x in tgp.gonderilen if x.startswith("🧾 Son ")]


def _uc_emir_iki_atlama(m, saat):
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))            # açılış 27,27 $
    m.piyasa_oku(saat())
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 150, 100.0, 300.0, saat))          # azaltma 13,64 $
    m.olay_isle(olay("a:3", adr(1), "BTC", "A", 150, 100.0, 150.0, saat))          # kapanış
    m.olay_isle(olay("a:4", adr(1), "@142", "B", 300, 100.0, 0.0, saat))           # spot: atlanır
    m.olay_isle(olay("a:5", adr(1), "@142", "B", 300, 100.0, 0.0, saat))


def test_saatlik_toplama_tek_mesaj_pencere_motor_saatinden(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    assert float(RULES["canli_telegram_sanal_ozet_dk"]) == 60
    m.baslat()
    bas = saat()
    _uc_emir_iki_atlama(m, saat)
    saat.ms += 30 * 60_000
    m.emir_ozeti(saat())
    assert _ozetler(tgp) == []                                                      # pencere dolmadı: anlık emir mesajı da yok
    assert not any("BTC AL" in x or "BTC SAT" in x for x in tgp.gonderilen)
    saat.ms = bas + SAAT
    m.emir_ozeti(saat())
    oz = _ozetler(tgp)
    assert len(oz) == 1
    assert oz[0].startswith(f"🧾 Son 1 saat ({tg._tsi_saat(bas)}–{tg._tsi_saat(bas + SAAT)} TSİ): 3 emir · sanal")
    assert "➕ açılış 1 · ⬆️ artırma 0 · ⬇️ azaltma 1 · ✖️ kapanış 1" in oz[0]
    assert "🏆 En büyük: 27,3 $ (BTC, AL)" in oz[0] and "⏭️ Atlanan sinyal: 2 (en çok: spot coin 2)" in oz[0]
    assert "💵 Tutar toplamı: 55 $" in oz[0] and "kayma ort. %" in oz[0]
    print("\n" + oz[0])
    saat.ms += SAAT
    m.emir_ozeti(saat())
    assert len(_ozetler(tgp)) == 1                                                  # tampon boşaldı, aynı mesaj tekrar gitmez


def test_hic_emir_yok_mesaj_yok_atlanan_tek_basina_mesaj_uretmez(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:4", adr(1), "@142", "B", 300, 100.0, 0.0, saat))
    saat.ms += 2 * SAAT
    m.emir_ozeti(saat(), zorla=False)
    m.emir_ozeti(saat(), zorla=True)
    assert _ozetler(tgp) == [] and tg.msg_sanal_saatlik(T0, T0 + SAAT, 60, [], {"x": 1}) == ""


def test_vardiya_sonu_kalan_tampon_gider_kisa_pencere_dakika_yazar(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    saat.ms += 25 * 60_000
    m.emir_ozeti(saat(), zorla=True)                                                # vardiya sonu
    oz = _ozetler(tgp)
    assert len(oz) == 1 and oz[0].startswith("🧾 Son 25 dk (") and ": 1 emir" in oz[0] and "⏭️" not in oz[0]


def test_sifir_eski_davranis_15_dk_ozeti(tmp_path):
    m, hl, saat, tgp = kur(tmp_path, kurallar={"canli_telegram_sanal_ozet_dk": 0})
    m.baslat()
    _uc_emir_iki_atlama(m, saat)
    m.emir_ozeti(saat())
    assert any("Son 15 dakikada 3 emir (sanal · deneme parası)" in x for x in tgp.gonderilen) and not any("emir · sanal" in x for x in tgp.gonderilen)


def test_gercek_kip_emir_anlik(tmp_path):
    class Gercek:
        kip = "gercek"

        def hazirla(self, coin):
            return None

        def emir(self, coin, yon, usd, reduce_only=False, acik_sz=None, bant=None, cloid=None):
            return yu.Dolum(coin, yon, usd, reduce_only=reduce_only, durum="red", neden="sdk_hatasi: X")
    tgp = SahteTG()
    saat = Saat()
    m = mt.Motor(RULES, Gercek(), SahteHL(), tg.Telegram(TOKEN, CHAT, tgp), tmp_path / "durum", tmp_path / "kayit", lambda: kadro([satir(1, 1)], T0), saat)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert any(x.startswith("⚠️ BTC AL: emir tam dolmadı") for x in tgp.gonderilen)       # saat dolmadan, hemen
    assert _ozetler(tgp) == [] and m._emir_tampon == []


def test_alarm_ve_saha_mesaji_sanalda_da_anlik(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    assert any("Yeni trader takibe alındı" in x for x in tgp.gonderilen)                  # saha girişi anlık
    m.tg.gonder(tg.alarm("ALARM: deneme", "x"))
    assert any(x.startswith("🚨 ALARM: deneme") for x in tgp.gonderilen)


def test_mesaj_bicimi_altin_ornek():
    a = "0xf43a34aaaaaaaa"
    emirler = [{"adres": a, "coin": "ETH", "yon": "B", "usd": 12.0, "kayma": 0.0, "durum": "dolu", "eylem": "artir"},
               {"adres": a, "coin": "BTC", "yon": "A", "usd": 230.0, "kayma": 0.0002, "durum": "dolu", "eylem": "kapat"},
               {"adres": a, "coin": "NEAR", "yon": "B", "usd": 11.0, "kayma": -0.0004, "durum": "kismi", "eylem": "ac"}]
    bas = 1_794_135_600_000 - 1_794_135_600_000 % SAAT
    assert tg.msg_sanal_saatlik(bas, bas + SAAT, 60, emirler, {"gec_acilis": 5, "hip3_atlandi": 2}) == (
        f"🧾 Son 1 saat ({tg._tsi_saat(bas)}–{tg._tsi_saat(bas + SAAT)} TSİ): 3 emir · sanal\n"
        "➕ açılış 1 · ⬆️ artırma 1 · ⬇️ azaltma 0 · ✖️ kapanış 1\n"
        "🏆 En büyük: 230 $ (BTC, SAT) · 0xf43a34…\n"
        "⏭️ Atlanan sinyal: 7 (en çok: geç görülen açılış 5)\n"
        "⚠️ 1 emir tam dolmadı\n"
        "💵 Tutar toplamı: 253 $ · kayma ort. %0,020")                                    # |kayma| ort. = (0,02 + 0,04 + 0) / 3 = %0,02
