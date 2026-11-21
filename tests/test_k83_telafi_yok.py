"""K-83 (kullanıcı kararı 20.11): kaçan işlem telafisi YOK (K-75 kaldırıldı). Kopma / kapalı motor / geç görülme sonrası trader AÇILIŞ ve ARTIRMALARI sonradan alınmaz
(`emir_yok` / `gec_goruldu_alinmaz`, karşı-olgu yok); trader'ın o arada yaptığı AZALTMA / KAPATMA aynen uygulanır (sahipsiz pozisyon kalmaz). Senkron hiçbir zaman açılış/artırma üretmez.
Binance kâğıt motoru aynı kod yolunu kullanır. Ağsız; kasa 1.000 → slot 90,909 $; trader hesap 100.000 $, BTC 100 $."""
from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import pano
from copytrade.kurallar import load_rules
from tests.test_binance_kagit import SahteHL2, bin_motor
from tests.test_canli_motor import SAAT, SahteHL, Saat, adr, kayitlar, kur, olay

A = adr(1)
KOK = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _dolgu(saat, kimlik, coin, yon, sz, bas, px=100.0, yas_ms=5_000, kaynak="dolgu"):
    """Kopma sonrası REST dolgusundan (ya da açılış REST tamamlamasından) gelen trader dolumu. Dolum, önceki canlı olaydan SONRA olmuş sayılsın diye saat yaş + 1 sn ileri alınır."""
    saat.ms += yas_ms + 1_000
    return replace(olay(kimlik, A, coin, yon, sz, px, bas, saat, yas_ms=yas_ms), kaynak=kaynak)


def _canli(m, saat, kimlik, coin, yon, sz, bas, px=100.0):
    saat.ms += 10_000
    m.piyasa_oku(saat())
    return m.olay_isle(olay(kimlik, A, coin, yon, sz, px, bas, saat, yas_ms=500))


def _hazir(tmp_path, **k):
    m, hl, saat, _ = kur(tmp_path, **k)
    m.baslat()
    return m, hl, saat


def _emir_sayisi(tmp_path):
    return len(kayitlar(tmp_path, "emir"))


# ------------------------------------------------------------------ telafi kodu / anahtarı yok
def test_kurallar_yaml_ve_kodda_telafi_kalmadi():
    r = load_rules()
    assert not [k for k in r if "telafi" in k] and "sanal_kacan_acilis_telafi" not in r
    yaml_metin = (KOK / "copytrade" / "kurallar.yaml").read_text(encoding="utf-8")
    assert "kacan_telafi" not in yaml_metin and "sanal_kacan_acilis_telafi" not in yaml_metin
    kod = (KOK / "copytrade" / "canli" / "motor.py").read_text(encoding="utf-8")
    for iz in ("kacan_telafi", "TELAFI_YENIDEN_DENE", "STOP_MUAF_NEDENLER", "_telafi_", "stop_muaf", "son_atla"):
        assert iz not in kod, iz
    assert not hasattr(mt.Motor, "kacan_telafi")


def test_durum_dosyasi_eski_anahtarlarla_acilir_ve_yenisine_yazilmaz(tmp_path):
    """Eski `motor.json` (son_atla / stop_muaf içerir) sorunsuz okunur; yeni yazımda bu anahtarlar yok."""
    m, _, saat = _hazir(tmp_path)
    m.durum_yaz()
    yol = tmp_path / "durum" / "motor.json"
    veri = json.loads(yol.read_text(encoding="utf-8"))
    assert "son_atla" not in veri and "stop_muaf" not in veri
    yol.write_text(json.dumps({**veri, "son_atla": {f"{A}|BTC": ["rejim_ters", 1]}, "stop_muaf": {f"{A}|BTC": [1, 2]}}), encoding="utf-8")
    m2, _, _, _ = kur(tmp_path, saat=saat)
    m2.baslat()
    m2.durum_yaz()
    assert "son_atla" not in json.loads(yol.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ kopma sırasında açılış / artırma: alınmaz
def test_kopmada_trader_acti_dolgu_gelince_acilmaz_neden_kaydi_karsi_olgu_yok(tmp_path):
    m, _, saat = _hazir(tmp_path)
    s = m.olay_isle(_dolgu(saat, "d:1", "BTC", "B", 300, 0.0))
    assert [(x.eylem, x.karar, x.neden) for x in s] == [("ac", "atlandi", "gec_goruldu_alinmaz")]
    assert m.hesap.sz(A, "BTC") == 0.0 and _emir_sayisi(tmp_path) == 0
    assert m.poz_tr[A]["BTC"] == 300                                                  # izleyici her durumda güncel
    y = kayitlar(tmp_path, "emir_yok")
    assert len(y) == 1 and y[0]["neden"] == "gec_goruldu_alinmaz" and y[0]["eylem"] == "ac"
    assert not m.karsi_olgu and not kayitlar(tmp_path, "karsi_olgu_hata")             # karşı-olgu kaydı yok
    assert m.neden_say["gec_goruldu_alinmaz"] == 1


def test_baglanti_gelince_canli_yeni_sinyalden_devam_edilir(tmp_path):
    """Kopmada açılış alınmadı; bağlantı gelince YENİ canlı açılış (başka coin) normal alınır."""
    m, _, saat = _hazir(tmp_path)
    m.olay_isle(_dolgu(saat, "d:1", "BTC", "B", 300, 0.0))
    s = _canli(m, saat, "a:2", "ETH", "B", 15, 0.0, px=2000.0)
    assert [(x.eylem, x.karar) for x in s] == [("ac", "emir")] and m.hesap.sz(A, "ETH") > 0 and m.hesap.sz(A, "BTC") == 0.0


def test_kopmada_trader_artirdi_dolgu_gelince_artirilmaz(tmp_path):
    m, _, saat = _hazir(tmp_path)
    _canli(m, saat, "a:1", "BTC", "B", 300, 0.0)
    biz = m.hesap.sz(A, "BTC")
    assert biz > 0
    s = m.olay_isle(_dolgu(saat, "d:2", "BTC", "B", 100, 300.0))
    assert [(x.eylem, x.karar, x.neden) for x in s] == [("artir", "atlandi", "gec_goruldu_alinmaz")]
    assert m.hesap.sz(A, "BTC") == biz and m.poz_tr[A]["BTC"] == 400 and _emir_sayisi(tmp_path) == 1


# ------------------------------------------------------------------ kopmada azaltma / kapatma: uygulanır
def test_kopmada_trader_azalti_dolgu_gelince_biz_de_azaltiriz(tmp_path):
    m, _, saat = _hazir(tmp_path)
    _canli(m, saat, "a:1", "BTC", "B", 300, 0.0)
    biz = m.hesap.sz(A, "BTC")
    s = m.olay_isle(_dolgu(saat, "d:2", "BTC", "A", 150, 300.0))
    assert [(x.eylem, x.karar) for x in s] == [("azalt", "emir")]
    assert 0 < m.hesap.sz(A, "BTC") < biz and kayitlar(tmp_path, "emir")[-1]["reduce_only"] is True


def test_kopmada_trader_kapatti_dolgu_gelince_biz_de_kapatiriz(tmp_path):
    m, _, saat = _hazir(tmp_path)
    _canli(m, saat, "a:1", "BTC", "B", 300, 0.0)
    s = m.olay_isle(_dolgu(saat, "d:2", "BTC", "A", 300, 300.0, yas_ms=20 * 60_000))   # yaş fark etmez
    assert [(x.eylem, x.karar) for x in s] == [("kapat", "emir")] and m.hesap.sz(A, "BTC") == pytest.approx(0.0, abs=1e-9)
    assert "BTC" not in m.poz_tr.get(A, {})


def test_kopmada_trader_ters_dondu_biz_kapatiriz_ters_yonde_acmayiz(tmp_path):
    m, _, saat = _hazir(tmp_path)
    _canli(m, saat, "a:1", "BTC", "B", 300, 0.0)
    s = m.olay_isle(_dolgu(saat, "d:2", "BTC", "A", 500, 300.0))                       # +300 → −200
    assert [(x.eylem, x.karar) for x in s] == [("kapat", "emir"), ("ac", "atlandi")] and s[1].neden == "gec_goruldu_alinmaz"
    assert m.hesap.sz(A, "BTC") == pytest.approx(0.0, abs=1e-9) and m.poz_tr[A]["BTC"] == -200


def test_acilista_rest_tamamlama_acilisi_almaz_kapanisi_uygular(tmp_path):
    """`kacanlari_tamamla` (REST): taze görünen açılış bile alınmaz; kaçan kapanış uygulanır; kaçan açılış sonrası kapanış da (ETH: önce bizde açık)."""
    saat = Saat()
    hl = SahteHL()
    m, _, _, _ = kur(tmp_path, hl=hl, saat=saat)
    m.baslat()
    m.olay_isle(olay("e:1", A, "ETH", "B", 15, 2000.0, 0.0, saat))
    assert m.hesap.sz(A, "ETH") > 0
    saat.ms += 60_000                                                                  # kapanış dolumu açılıştan SONRA
    hl.rest = {A: [
        {"tid": 21, "time": saat() - 30_000, "coin": "BTC", "px": "100", "sz": "300", "side": "B", "startPosition": "0"},       # 30 sn önce açtı: alınmaz
        {"tid": 22, "time": saat() - 20_000, "coin": "ETH", "px": "2000", "sz": "15", "side": "A", "startPosition": "15"},      # kapattı: uygulanır
    ]}
    m.kacanlari_tamamla(saat() - SAAT)
    assert m.hesap.sz(A, "BTC") == 0.0 and m.hesap.sz(A, "ETH") == pytest.approx(0.0, abs=1e-9)
    assert m.poz_tr[A]["BTC"] == 300 and "ETH" not in m.poz_tr[A]
    y = [e for e in kayitlar(tmp_path, "emir_yok") if e["coin"] == "BTC"]
    assert len(y) == 1 and y[0]["neden"] == "gec_goruldu_alinmaz" and not m.karsi_olgu
    assert [e["coin"] for e in kayitlar(tmp_path, "emir")] == ["ETH", "ETH"]


def test_canli_ws_cok_gecikmis_acilis_gec_acilis_esigiyle_alinmaz(tmp_path):
    """Canlı WS'ten gelen ama `canli_olay_stale_sn` (120 sn) üstü gecikmiş açılış alınmaz; eşik altı (normal medyan 0,7 sn) alınır."""
    m, _, saat = _hazir(tmp_path)
    assert m.rules["canli_olay_stale_sn"] == 120
    assert m.olay_isle(olay("a:1", A, "ETH", "B", 15, 2000.0, 0.0, saat, yas_ms=121_000))[0].neden == "gec_acilis"
    assert m.olay_isle(olay("a:2", A, "ETH", "B", 15, 2000.0, 0.0, saat, yas_ms=1_500))[0].karar == "emir"


# ------------------------------------------------------------------ senkron: kapat / azalt, asla aç / artır
def _senk(m, hl, saat, pozlar):
    hl.pozlar = {A: pozlar}
    saat.ms += 60_000
    return m.senkron_uygula(m.senkron_oku())


def test_senkron_trader_kapattiysa_kapatir(tmp_path):
    m, hl, saat = _hazir(tmp_path)
    _canli(m, saat, "a:1", "BTC", "B", 300, 0.0)
    _senk(m, hl, saat, {})
    assert m.hesap.sz(A, "BTC") == pytest.approx(0.0, abs=1e-9) and kayitlar(tmp_path, "senkron_kapanis")


def test_senkron_trader_azalttiysa_azaltir(tmp_path):
    m, hl, saat = _hazir(tmp_path)
    _canli(m, saat, "a:1", "BTC", "B", 300, 0.0)
    biz = m.hesap.sz(A, "BTC")
    _senk(m, hl, saat, {"BTC": 150.0})
    assert 0 < m.hesap.sz(A, "BTC") < biz and kayitlar(tmp_path, "senkron_azalt")[-1]["karar"] == "emir"


def test_senkron_trader_ters_dondu_kapatir_acmaz(tmp_path):
    m, hl, saat = _hazir(tmp_path)
    _canli(m, saat, "a:1", "BTC", "B", 300, 0.0)
    n = _emir_sayisi(tmp_path)
    _senk(m, hl, saat, {"BTC": -200.0})
    assert m.hesap.sz(A, "BTC") == pytest.approx(0.0, abs=1e-9) and _emir_sayisi(tmp_path) == n + 1 and kayitlar(tmp_path, "emir")[-1]["reduce_only"] is True
    assert m.poz_tr[A]["BTC"] == -200


def test_senkron_acilis_ya_da_artirma_uretmez(tmp_path):
    """Kopmada trader hem YENİ coin açtı (ETH) hem mevcut pozisyonu büyüttü (BTC 300 → 600): senkron izleyiciyi günceller, emir ÜRETMEZ."""
    m, hl, saat = _hazir(tmp_path)
    _canli(m, saat, "a:1", "BTC", "B", 300, 0.0)
    biz, n = m.hesap.sz(A, "BTC"), _emir_sayisi(tmp_path)
    _senk(m, hl, saat, {"BTC": 600.0, "ETH": 10.0})
    assert m.hesap.sz(A, "ETH") == 0.0 and m.hesap.sz(A, "BTC") == biz and _emir_sayisi(tmp_path) == n
    assert m.poz_tr[A] == {"BTC": 600.0, "ETH": 10.0}
    assert not [e for e in kayitlar(tmp_path, "senkron_azalt")]


def test_senkron_bizde_hic_pozisyon_yokken_trader_acik_emir_yok(tmp_path):
    m, hl, saat = _hazir(tmp_path)
    _senk(m, hl, saat, {"BTC": 300.0})
    assert m.hesap.sz(A, "BTC") == 0.0 and _emir_sayisi(tmp_path) == 0 and m.poz_tr[A] == {"BTC": 300.0}
    m.dakika()                                                                         # dakikalık adımlar da (eski telafi adımı yok) açmaz
    assert m.hesap.sz(A, "BTC") == 0.0 and _emir_sayisi(tmp_path) == 0


# ------------------------------------------------------------------ Binance kâğıt: aynı motor kodu
def test_binance_kagit_ayni_kural(tmp_path):
    saat, hl = Saat(), SahteHL2()
    m, _, _, _ = bin_motor(tmp_path, hl, saat)
    m.baslat()
    s = m.olay_isle(olay("b:1", A, "ETH", "B", 15, 2000.0, 0.0, saat))                 # canlı açılış: alınır
    assert [(x.eylem, x.karar) for x in s] == [("ac", "emir")]
    k = m.olay_isle(_dolgu(saat, "b:2", "ETH", "A", 15, 15.0, px=2000.0))               # kopmada kapattı: biz de
    assert [(x.eylem, x.karar) for x in k] == [("kapat", "emir")] and m.hesap.sz(A, "ETH") == pytest.approx(0.0, abs=1e-9)
    a = m.olay_isle(_dolgu(saat, "b:3", "ETH", "B", 15, 0.0, px=2000.0))                # kopmada yeniden açtı: alınmaz
    assert [(x.eylem, x.karar, x.neden) for x in a] == [("ac", "atlandi", "gec_goruldu_alinmaz")] and m.hesap.sz(A, "ETH") == 0.0
    assert not m.karsi_olgu


# ------------------------------------------------------------------ eski kayıtlarla pano / rapor / bekçi bozulmaz
ESKI_KAYITLAR = [
    {"zaman_ms": 1_799_999_000_000, "olay": "kacan_telafi", "adres": A, "coin": "BTC", "yon": "B", "trader_giris": 100.0, "mark": 100.0, "kayma": 0.0, "yas_sa": 2.0, "karar": "emir", "neden": "kacan_telafi"},
    {"zaman_ms": 1_799_999_000_001, "olay": "kacan_telafi_atlandi", "adres": A, "coin": "BTC", "neden": "filtre_atlamisti:rejim_ters"},
    {"zaman_ms": 1_799_999_000_002, "olay": "kacan_telafi_hata", "adres": A, "asama": "giris_px", "tur": "ConnectionError"},
    {"zaman_ms": 1_799_999_000_003, "olay": "emir", "adres": A, "coin": "BTC", "eylem": "ac", "yon": "B", "durum": "dolu", "boyut_neden": "kacan_telafi", "kaynak": "telafi", "telafi_boyut_neden": "tam",
     "telafi_trader_giris": 100.0, "telafi_kayma": 0.0, "telafi_yas_sa": 2.0, "kayma_trader": 0.0, "ucret": 0.01, "usd_istenen": 27.0, "sz": 0.27, "dolum_px": 100.0},
    {"zaman_ms": 1_799_999_000_004, "olay": "emir", "adres": A, "coin": "BTC", "eylem": "kapat", "yon": "A", "durum": "dolu", "boyut_neden": "tam_kapanis", "pnl_usd": 1.0, "ucret": 0.01, "sz": 0.27,
     "dolum_px": 101.0, "kalan": 0.0, "reduce_only": True},
]


def test_eski_telafi_kayitlari_pano_ve_rapor_kodunu_bozmaz():
    from copytrade.canli.gunluk_ozet import alinmayan_neden, kopya_kalite
    simdi = 1_800_000_000_000
    ozet = {"kip": "sanal", "vardiya": "1", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "getiri": 0.0, "saha": 1, "saha_n": 11, "inen": 0, "sure_dk": 10.0, "dinleyici": {}, "rest_429": 0, "acik": []}
    md, _ = pano.pano_olustur(ozet, {"gun_basi": 1000.0, "zirve": 1000.0}, {}, ESKI_KAYITLAR, [], [], simdi)
    assert isinstance(md, str) and md
    assert isinstance(pano.kapanan_islemler(ESKI_KAYITLAR), list)
    assert isinstance(alinmayan_neden(ESKI_KAYITLAR), list)
    assert isinstance(kopya_kalite(ESKI_KAYITLAR), dict)


def test_bekci_sayaci_eski_telafi_olaylarini_yok_sayar(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("sanal_bekci_say", KOK / "deploy" / "sanal_bekci_say.py")
    say_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(say_mod)
    kayit_dizini = tmp_path / "kayit"
    kayit_dizini.mkdir()
    (kayit_dizini / f"{time.strftime('%Y-%m-%d', time.gmtime())}.jsonl").write_text("\n".join(json.dumps(x) for x in ESKI_KAYITLAR) + "\n", encoding="utf-8")
    out = say_mod.say(kayit_dizini, 0.0)
    assert "kacan_telafi_hata" not in out and out["hata"] == 0
