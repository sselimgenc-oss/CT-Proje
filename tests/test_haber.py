"""Haber/duygu etiketi (copytrade/canli/haber.py): yalnız kayıt; ağsız (sahte getirici), her hata sessiz."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from copytrade.canli import haber
from tests.test_canli_motor import adr, kayitlar, kur, olay

SIMDI = int(datetime(2026, 11, 19, 12, 0, tzinfo=UTC).timestamp() * 1000)
KURAL = {"duygu_kaynak_url": "https://fng.example/fng", "haber_kaynaklar": ["https://a.example/rss", "https://b.example/rss"]}


def _rss(*ogeler: tuple[str, str]) -> bytes:
    govde = "".join(f"<item><title>{b}</title><pubDate>{t}</pubDate></item>" for b, t in ogeler)
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{govde}</channel></rss>'.encode()


SAAT_ONCE = "Thu, 19 Nov 2026 10:00:00 +0000"
ESKI = "Tue, 17 Nov 2026 10:00:00 +0000"
RSS = _rss(("Bitcoin surges to record high", SAAT_ONCE), ("SOL jumps as Solana adoption grows", SAAT_ONCE),
           ("Exchange hack drains ETH", SAAT_ONCE), ("Solid quarter for banks", SAAT_ONCE), ("Old bitcoin story", ESKI))
FNG = {"data": [{"value": "25", "value_classification": "Extreme Fear", "timestamp": "1"}]}


def test_gecerli_okuma_ve_duygu_degisti():
    anlik, ol = haber.guncelle(KURAL, {}, SIMDI, lambda u: FNG, lambda u: RSS)
    assert anlik["duygu"]["deger"] == 25 and anlik["duygu"]["sinif"] == "Extreme Fear"
    assert ol == [{"olay": "duygu_degisti", "onceki": None, "yeni": "Extreme Fear", "deger": 25}]
    assert len(anlik["haberler"]) == 4                       # iki kaynakta aynı başlıklar tekilleşir; 2 günlük başlık atılır
    anlik2, ol2 = haber.guncelle(KURAL, anlik, SIMDI + 3600_000, lambda u: FNG, lambda u: RSS)
    assert ol2 == []                                         # sınıf aynı: olay yok
    fng2 = {"data": [{"value": "60", "value_classification": "Greed"}]}
    _, ol3 = haber.guncelle(KURAL, anlik2, SIMDI + 7200_000, lambda u: fng2, lambda u: RSS)
    assert ol3[0]["onceki"] == "Extreme Fear" and ol3[0]["yeni"] == "Greed"


def test_coin_eslesme_tam_kelime_ve_isim():
    anlik, _ = haber.guncelle(KURAL, {}, SIMDI, lambda u: FNG, lambda u: RSS)
    assert haber.coin_haber(anlik, "BTC", SIMDI) == {"BTC": {"adet_24s": 1, "ton": "pozitif"}}     # "Bitcoin" ismi; eski haber sayılmaz
    assert haber.coin_haber(anlik, "SOL", SIMDI) == {"SOL": {"adet_24s": 1, "ton": "pozitif"}}     # "SOL" ve "Solana" aynı başlıkta: 1 başlık
    assert haber.coin_haber(anlik, "ETH", SIMDI) == {"ETH": {"adet_24s": 1, "ton": "negatif"}}
    assert haber.coin_haber(anlik, "DOGE", SIMDI) == {"DOGE": {"adet_24s": 0, "ton": None}}
    assert not haber.eslesir("Solid quarter", "SOL") and not haber.eslesir("Resolve it", "SOL")     # tam kelime
    assert haber.eslesir("kPEPE rallies, PEPE up", "kPEPE")                                         # HL "k" öneki
    assert haber.coin_haber(anlik, "BTC", SIMDI + 30 * 3600_000) == {"BTC": {"adet_24s": 0, "ton": None}}   # 24 saat penceresi


def test_ton_kaba_anahtar_kelime():
    assert haber.ton("Prices surge") == "pozitif" and haber.ton("Exchange hack") == "negatif" and haber.ton("Fed meets") == "notr"


def test_bozuk_xml_ve_dtd_bos_doner():
    assert haber.rss_coz(b"<rss><item>", SIMDI) == [] and haber.rss_coz("", SIMDI) == [] and haber.rss_coz(None, SIMDI) == []
    assert haber.rss_coz(b'<!DOCTYPE x [<!ENTITY a "b">]><rss><channel><item><title>a</title><pubDate>' + SAAT_ONCE.encode() + b"</pubDate></item></channel></rss>", SIMDI) == []
    assert haber.rss_coz(_rss(("tarihsiz", "bozuk tarih")), SIMDI) == []


def test_zaman_asimi_onbellegi_korur():
    anlik, _ = haber.guncelle(KURAL, {}, SIMDI, lambda u: FNG, lambda u: RSS)

    def zaman_asimi(u):
        raise TimeoutError("5 sn")

    yeni, ol = haber.guncelle(KURAL, anlik, SIMDI + 3600_000, zaman_asimi, zaman_asimi)
    assert yeni["duygu"] == anlik["duygu"] and yeni["haberler"] == anlik["haberler"] and ol == []
    bos, ol = haber.guncelle(KURAL, {}, SIMDI, zaman_asimi, zaman_asimi)                            # önbellek yoksa null
    assert haber.emir_alanlari(bos, "BTC", SIMDI) == {"duygu": None, "haber": None} and ol == []


def test_bir_kaynak_bozuk_digeri_calisir():
    def metin(u):
        if "a.example" in u:
            return b"<bozuk"
        return RSS

    anlik, _ = haber.guncelle(KURAL, {}, SIMDI, lambda u: {"data": []}, metin)
    assert "duygu" not in anlik and len(anlik["haberler"]) == 4


def test_duygu_bayat_none():
    anlik, _ = haber.guncelle(KURAL, {}, SIMDI, lambda u: FNG, lambda u: RSS)
    assert haber.duygu_ozet(anlik, SIMDI + 27 * 3600_000) is None


@pytest.mark.parametrize("veri", [None, {}, {"data": []}, {"data": [{"value": "abc", "value_classification": "x"}]}, {"data": [{"value": "150", "value_classification": "x"}]}])
def test_duygu_bozuk_yanit(veri):
    assert haber.duygu_coz(veri) is None


def test_motor_ag_yok_testte_emir_alanlari_none(tmp_path):
    """conftest ağı kapatır: motor adımı hata yutar; emir kaydında `duygu`/`haber` null."""
    m, hl, saat, _ = kur(tmp_path, kurallar={"canli_telegram_sanal_ozet_dk": 0, **KURAL, "haber_aktif": True})
    m.baslat()
    m.haber_adimi(saat())
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    e = kayitlar(tmp_path, "emir")[0]
    assert e["duygu"] is None and e["haber"] is None
    assert kayitlar(tmp_path, "duygu_degisti") == []


def test_motor_etiket_emirde_ve_ozette(tmp_path, monkeypatch):
    monkeypatch.setattr(haber, "_getir_json", lambda u: FNG)
    m, hl, saat, _ = kur(tmp_path, kurallar={"canli_telegram_sanal_ozet_dk": 0, **KURAL, "haber_aktif": True})
    m.baslat()
    now = saat()
    monkeypatch.setattr(haber, "_getir_metin", lambda u: _rss(("Bitcoin surges", datetime.fromtimestamp(now / 1000 - 3600, UTC).strftime("%a, %d %b %Y %H:%M:%S +0000"))))
    m.haber_adimi(now)
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    e = kayitlar(tmp_path, "emir")[0]
    assert e["duygu"] == {"deger": 25, "sinif": "Extreme Fear"} and e["haber"] == {"BTC": {"adet_24s": 1, "ton": "pozitif"}}
    assert len(kayitlar(tmp_path, "duygu_degisti")) == 1
    assert m.pano_ek()["duygu"] == {"deger": 25, "sinif": "Extreme Fear"}


def test_kapali_ag_cagirmaz(tmp_path, monkeypatch):
    cagri = []
    monkeypatch.setattr(haber, "_getir_json", lambda u: cagri.append(u))
    m, hl, saat, _ = kur(tmp_path, kurallar={"canli_telegram_sanal_ozet_dk": 0, **KURAL, "haber_aktif": False})
    m.baslat()
    m.haber_adimi(saat())
    assert cagri == []


def test_pano_duygu_satiri():
    from copytrade.canli.pano import duygu_metni

    assert duygu_metni({"duygu": {"deger": 25, "sinif": "Extreme Fear"}}) == ("25", "Extreme Fear")
    assert duygu_metni({}) == ("—", "yalnız kayıt")


def test_pano_md_ve_html_duygu_satiri():
    from copytrade.canli import pano

    ozet = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "acik": [], "duygu": {"deger": 25, "sinif": "Extreme Fear"}}
    md, _ = pano.pano_olustur(ozet, {}, {}, [], [], [], SIMDI)
    assert "Piyasa duygusu (Fear & Greed 0-100; sanalda ≥75 yeni long, ≤25 yeni short atlatır; gerçekte yalnız kayıt): 25 · Extreme Fear" in md
    assert "Piyasa duygusu: <b>25</b> (aşırı korku)" in pano.html_olustur(ozet, {}, {}, [], [], SIMDI, None, None)
