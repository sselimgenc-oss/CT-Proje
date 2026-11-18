"""2. denetim O-3: kilit altı REST okumaları için KISA MERDİVENLİ ("hızlı") istemci + paylaşılan 429 soğuması. Sürekli 429'da `olay_isle` < 10 sn döner (sahte saat: toplam uyku süresi sayılır);
başka iş parçacığı kilidi ≤ 10 sn bekler; soğuma bitmeden diğer istek gitmez; bekçi (180 sn) tetiklenmez. Kilit DIŞI okumalar uzun merdiveni korur."""
from __future__ import annotations

import threading
import time

import pytest
import requests

from copytrade import tarama
from copytrade.canli import motor as mt
from copytrade.tarama import PublicClient, RateLimitError
from tests.test_canli_motor import adr, olay
from tests.test_canli_t4b import BorsaSim, kur_gercek
from tests.test_tarama_5xx import Oturum, Yanit


@pytest.fixture(autouse=True)
def _m():
    yield
    mt.MASKE.clear()


class SahteSaat:
    """Sahte monotonik saat + uyku: uyku saati ilerletir ve süreyi toplar."""
    def __init__(self):
        self.t, self.uykular = 1000.0, []

    def clock(self):
        return self.t

    def sleep(self, sn):
        self.uykular.append(sn)
        self.t += sn


def _istemciler(oturum, saat):
    lim = mt.GuvenliLimiter(limit=10 ** 9, clock=saat.clock, sleep=saat.sleep)
    normal = PublicClient(session=oturum, limiter=lim, sleep=saat.sleep, yeniden_bekleme=tarama.KAPI_YENIDEN_BEKLEME)
    hizli = PublicClient(session=oturum, limiter=lim, sleep=saat.sleep, hizli=True)
    return normal, hizli, lim


def test_hizli_surekli_429_en_cok_2_sn_bekler_sonra_hata_ve_sogutma_baslar():
    saat = SahteSaat()
    oturum = Oturum(*[429] * 10)
    _, hizli, lim = _istemciler(oturum, saat)
    with pytest.raises(RateLimitError):
        hizli.info({"type": "x"})
    assert sum(saat.uykular) <= 3.0 and oturum.cagri == 2                      # bir deneme + bir yeniden deneme
    assert lim.soguma_kalan() > 0
    oturum.cagri = 0
    with pytest.raises(RateLimitError):                                         # soğuma sürerken: BEKLEMEDEN hata, istek bile gitmez
        hizli.info({"type": "x"})
    assert oturum.cagri == 0 and sum(saat.uykular) <= 3.0


def test_hizli_uzun_retry_after_hemen_hata_normal_istemci_eski_merdiveni_korur():
    saat = SahteSaat()
    oturum = Oturum(Yanit(429, headers={"Retry-After": "120"}))
    _, hizli, lim = _istemciler(oturum, saat)
    with pytest.raises(RateLimitError):
        hizli.info({"type": "x"})
    assert saat.uykular == [] and oturum.cagri == 1 and lim.soguma_kalan() >= 119
    saat2 = SahteSaat()
    oturum2 = Oturum(*[429] * 6)
    normal, _, _ = _istemciler(oturum2, saat2)
    with pytest.raises(RateLimitError):
        normal.info({"type": "x"})
    assert sum(saat2.uykular) >= 135                                            # kilit DIŞI okumalar: 5/10/20/40/60 sn merdiveni DEĞİŞMEDİ


def test_soguma_bitmeden_diger_istek_gitmez_normal_istemci_bekler():
    saat = SahteSaat()
    oturum = Oturum(429, 429)
    normal, hizli, lim = _istemciler(oturum, saat)
    with pytest.raises(RateLimitError):
        hizli.info({"type": "a"})                                              # hızlı: 2 sn bekler, ikinci 429 → hata + 5 sn soğuma
    kalan = lim.soguma_kalan()
    assert kalan > 0
    oturum.sonuclar = [200]
    t0, once = saat.t, len(saat.uykular)
    assert normal.info({"type": "b"}) == {"ok": 200}                           # başka istemci: soğumayı BEKLEDİ (istek ondan önce gitmedi)
    assert saat.t - t0 >= kalan - 1e-9 and len(saat.uykular) == once + 1


def test_hizli_agirlik_butcesi_dolu_uzun_beklemez():
    saat = SahteSaat()
    lim = mt.GuvenliLimiter(limit=2, clock=saat.clock, sleep=saat.sleep)
    hizli = PublicClient(session=Oturum(200, 200), limiter=lim, sleep=saat.sleep, hizli=True)
    hizli.info({"type": "x"}, weight=2)
    with pytest.raises(RateLimitError):
        hizli.info({"type": "x"}, weight=2)                                    # bütçe için ~60 sn beklemek gerekir: BEKLEMEDEN hata
    assert saat.uykular == []


def test_hizli_ag_hatasi_tek_yeniden_deneme_sonra_hata_ve_kisa_soguma():
    saat = SahteSaat()
    oturum = Oturum(requests.exceptions.ConnectionError("x"), requests.exceptions.ConnectionError("y"))
    _, hizli, lim = _istemciler(oturum, saat)
    with pytest.raises(requests.exceptions.ConnectionError):
        hizli.info({"type": "x"})
    assert saat.uykular == [tarama.HIZLI_AG_BEKLEME] and lim.soguma_kalan() > 0


def _kilitli_motor(tmp_path, monkeypatch, saat):
    sim = BorsaSim()
    m, sim, ms, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    oturum = Oturum(*[429] * 100)
    _, hizli, _ = _istemciler(oturum, saat)
    m.post_hizli = lambda yuk: hizli.info(yuk, weight=mt.AGIRLIK.get(str(yuk.get("type")), 20))
    m.hesap_tr.clear()                                                         # önbellek yok: açılışta hesap değeri REST ile okunur (kilit altı)
    return m, sim, ms, oturum


def test_surekli_429da_olay_isle_10_sn_icinde_atlandi_doner_bekci_tetiklenmez(tmp_path, monkeypatch):
    saat = SahteSaat()
    m, sim, ms, oturum = _kilitli_motor(tmp_path, monkeypatch, saat)
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, ms))
    assert [(x.karar, x.neden) for x in s] == [("atlandi", "trader_hesap_yok")]
    assert sum(saat.uykular) < 10 and oturum.cagri <= 3                        # 135 sn merdiven yok; soğuma sonraki okumaları da engeller
    assert sum(saat.uykular) < float(m.rules.get("canli_bekci_sn", 180))
    assert m.hesap.sz(adr(1), "BTC") == 0.0


def test_baska_is_parcacigi_kilidi_en_cok_10_sn_bekler(tmp_path, monkeypatch):
    """Gerçek saat/uyku (kısaltılmış sabitler): A iş parçacığı `olay_isle` ile kilidi tutarken 429 alır; B (dakikalık bakım/risk) kilidi ≤ 10 sn içinde alır."""
    monkeypatch.setattr(tarama, "HIZLI_429_BEKLEME", 0.05)
    sim = BorsaSim()
    m, sim, ms, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    lim = mt.GuvenliLimiter(limit=10 ** 9)
    hizli = PublicClient(session=Oturum(*[429] * 100), limiter=lim, hizli=True)
    m.post_hizli = lambda yuk: hizli.info(yuk, weight=2)
    m.hesap_tr.clear()
    t = threading.Thread(target=lambda: m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, ms)))
    t0 = time.monotonic()
    t.start()
    time.sleep(0.01)
    with m._lock:
        bekleme = time.monotonic() - t0
    t.join(10)
    assert bekleme < 10 and not t.is_alive()


def test_rest_post_hizli_olustur_oturum_ve_limitleyiciyi_paylasir():
    saat = SahteSaat()
    oturum = Oturum(200)
    lim = mt.GuvenliLimiter(limit=10 ** 9, clock=saat.clock, sleep=saat.sleep)
    normal = mt.rest_post_olustur({}, PublicClient(session=oturum, limiter=lim, sleep=saat.sleep))
    hizli = mt.rest_post_hizli_olustur(normal)
    assert hizli is not normal and hizli.istemci.limiter is lim and hizli.istemci.session is oturum and hizli.istemci.hizli is True
    sade = lambda y: y                                                          # noqa: E731 — istemcisiz sahte `post`: aynen döner
    assert mt.rest_post_hizli_olustur(sade) is sade
