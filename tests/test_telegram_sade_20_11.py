"""Telegram sadeleştirme (20.11): rutin türler bastırılır; yalnız işlem/özet/uyarı gider. + O2/O5 ek güvenceler."""
from copytrade.canli import pano, telegram as tg
from copytrade.canli.hesap import Hesap


def test_rutin_turler_bastirilir_ve_gonderilmez():
    for t in ("haftalik_kadro", "kopya_kacan", "kadro_surum_bekleniyor", "ogrenme_ders", "saha_giris", "emir_ozeti"):
        assert t in tg.BASTIRILAN_TURLER
    gid = []
    k = tg.Telegram("T", "1", lambda u, y: gid.append(y["text"]) or {"ok": True}, saat_s=lambda: 1000.0, uyku=lambda s: None)
    assert k.gonder("🔄 Haftalık kadro değişti", tur="haftalik_kadro") is False and not gid


def test_islem_toplu_tek_satir_ve_tek_cikti():
    assert tg.msg_islem_toplu(4, 3, -2.1).startswith("🧾 +7 işlem daha")


def test_hesap_from_json_yeni_kaldirac_acik_pozisyon_kendi_kaldiracini_korur():
    h = Hesap(1000.0, 3.0)
    h.uygula("0xa", "BTC", "A", 1.0, 100.0, 0.0, 1)
    d = h.to_json()
    h2 = Hesap.from_json(d, 5.0)
    assert h2.kaldirac == 5.0 and h2.poz["0xa"]["BTC"].kaldirac == 3.0
    assert Hesap.from_json(d).kaldirac == 3.0


def test_pano_dinamik_stop_kapaliyken_sabit_oran():
    A = "0x" + "a1" * 20
    acik = [{"adres": A, "coin": "VVV", "sz": -10.0, "giris": 100.0, "mark": 100.0, "usd": 1000.0, "kz_usd": 0.0}]
    hesap = {"poz": {A: {"VVV": {"sz": -10.0, "giris": 100.0, "acilis_ms": 1, "kaldirac": 3.0}}}, "maks_kaldirac": {"VVV": 3.0}}
    s = pano.acik_satirlari(acik, hesap, {"canli_felaket_stop_oran": 0.20}, 2, "sanal")[0]
    assert "120" in s["stop"] and "%20" in s["stop"]
