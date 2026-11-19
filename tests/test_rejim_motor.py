"""ML rejim etiketi: motor bağlantısı (rejim_adimi + emir olayındaki `rejim` alanı). Yalnız kayıt; ağsız (getirici sahte)."""
from __future__ import annotations

import copy
from datetime import UTC, datetime

from copytrade.canli import rejim
from tests.test_canli_motor import adr, kayitlar, kur, olay
from tests.test_rejim import URL, _veri

ILK_KURAL = {"canli_telegram_sanal_ozet_dk": 0}


def _canli_yayin(ms: int, **degis) -> dict:
    """Motorun saatine göre taze yayın (uretim = şimdi − 10 dk)."""
    uretim = datetime.fromtimestamp(ms / 1000 - 600, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _veri(uretim_ts=uretim, **degis)


def test_kapali_adreste_motor_ag_cagirmaz_ve_emir_alani_none(tmp_path, monkeypatch):
    cagri = []
    monkeypatch.setattr(rejim, "_getir_varsayilan", lambda url: cagri.append(url) or _veri())
    m, hl, saat, _ = kur(tmp_path, kurallar={**ILK_KURAL, "rejim_kaynak_url": ""})
    m.baslat()
    m.rejim_adimi(saat())
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert cagri == []
    assert kayitlar(tmp_path, "rejim_degisti") == []
    assert kayitlar(tmp_path, "emir")[0]["rejim"] is None


def test_degisim_tekillestirme_ve_emir_alani(tmp_path, monkeypatch):
    yayin = {}
    cagri = []

    def sahte(url):
        cagri.append(url)
        return copy.deepcopy(yayin["v"])

    monkeypatch.setattr(rejim, "_getir_varsayilan", sahte)
    m, hl, saat, _ = kur(tmp_path, kurallar={**ILK_KURAL, "rejim_kaynak_url": URL, "rejim_okuma_dk": 30})
    yayin["v"] = _canli_yayin(saat())
    m.baslat()

    m.rejim_adimi(saat())                                   # ilk okuma: BTC ve ETH 4h değerleri kaydedilir
    olaylar = kayitlar(tmp_path, "rejim_degisti")
    assert {(x["coin"], x["onceki"], x["yeni"]) for x in olaylar} == {("BTC", None, "trend_up"), ("ETH", None, "volatile")}
    assert cagri == [URL]

    m.rejim_adimi(saat())                                   # 30 dk dolmadı: ağ yok
    assert cagri == [URL]

    saat.ms += 31 * 60_000                                  # 31 dk sonra yeniden okunur; değer aynı → yeni olay yok
    yayin["v"] = _canli_yayin(saat())
    m.rejim_adimi(saat())
    assert cagri == [URL, URL] and len(kayitlar(tmp_path, "rejim_degisti")) == 2

    saat.ms += 31 * 60_000
    yayin["v"] = _canli_yayin(saat(), varliklar={"BTC/USDT": {"baz": "BTC", "4h": {"rejim": "trend_down"}, "1d": {"rejim": "range"}}})
    m.rejim_adimi(saat())                                   # BTC 4h değişti → tek yeni olay
    son = kayitlar(tmp_path, "rejim_degisti")[-1]
    assert (son["coin"], son["onceki"], son["yeni"]) == ("BTC", "trend_up", "trend_down")

    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert [(x.eylem, x.karar) for x in s] == [("ac", "emir")]
    assert kayitlar(tmp_path, "emir")[0]["rejim"] == {"4h": "trend_down", "1d": "range"}


def test_getirici_hatasi_motoru_durdurmaz(tmp_path, monkeypatch):
    def patlar(url):
        raise TimeoutError("zaman aşımı")

    monkeypatch.setattr(rejim, "_getir_varsayilan", patlar)
    m, hl, saat, _ = kur(tmp_path, kurallar={**ILK_KURAL, "rejim_kaynak_url": URL})
    m.baslat()
    m.rejim_adimi(saat())                                   # istisna yok
    assert m.rejim_anlik == {} and kayitlar(tmp_path, "rejim_degisti") == []
