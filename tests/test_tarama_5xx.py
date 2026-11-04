"""PublicClient 5xx / 429 / ağ hatası yeniden deneme ilkeleri (tarama.py). (T1: kapı veri bütünlüğü ve yeniden koşu testleri silindi.)"""
from __future__ import annotations

import pytest
import requests

from copytrade.kurallar import load_rules
from copytrade.tarama import KAPI_YENIDEN_BEKLEME, PublicClient, RateLimiter, RateLimitError

RULES = load_rules()


# ------------------------------------------------------------------ yeniden deneme (PublicClient)
class Yanit:
    def __init__(self, kod, veri=None, headers=None):
        self.status_code, self._veri, self.headers = kod, veri if veri is not None else {"ok": kod}, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._veri


class Oturum:
    def __init__(self, *sonuclar):
        self.sonuclar, self.cagri = list(sonuclar), 0

    def request(self, method, url, json=None, timeout=None):
        self.cagri += 1
        s = self.sonuclar.pop(0)
        if isinstance(s, Exception):
            raise s
        return s if isinstance(s, Yanit) else Yanit(s)


def istemci(*sonuclar, ilke=KAPI_YENIDEN_BEKLEME):
    bekleme = []
    oturum = Oturum(*sonuclar)
    return PublicClient(session=oturum, limiter=RateLimiter(10 ** 9), sleep=bekleme.append, yeniden_bekleme=ilke), oturum, bekleme


def test_a_500_500_basari_bekleme_5_15():
    c, oturum, bekleme = istemci(500, 500, 200)
    assert c.info({"type": "x"}) == {"ok": 200}
    assert bekleme == [5, 15] and oturum.cagri == 3 and c.stats["5xx"] == 2


def test_b_dort_kez_500_hata_yukselir_uc_yeniden_deneme():
    c, oturum, bekleme = istemci(500, 500, 500, 500)
    with pytest.raises(requests.HTTPError):
        c.info({"type": "x"})
    assert bekleme == [5, 15, 45] and oturum.cagri == 4


def test_429_toplam_bekleme_eskisinden_az_degil_5xx_ve_ag_icin_5_15_45_4xx_yeniden_denenmez():
    c, oturum, bekleme = istemci(429, 200)
    assert c.info({"type": "x"}) == {"ok": 200} and bekleme == [5]
    c, oturum, bekleme = istemci(*[429] * 6)                          # kapı istemcisi: 429 sabrı KISALMADI (eski ilke: 5/10/20/40/60 = 135 sn)
    with pytest.raises(RateLimitError):
        c.info({"type": "x"})
    eski = istemci(*[429] * 6, ilke=None)
    with pytest.raises(RateLimitError):
        eski[0].info({"type": "x"})
    assert bekleme == [5, 10, 20, 40, 60] and sum(bekleme) >= sum(eski[2]) == 135
    c, oturum, bekleme = istemci(500, 500, 500, 500)                  # 5/15/45 yalnız 5xx ve ağ hataları için
    with pytest.raises(requests.HTTPError):
        c.info({"type": "x"})
    assert bekleme == [5, 15, 45]
    c, oturum, bekleme = istemci(requests.ConnectionError("x"), requests.Timeout("y"), 200)
    assert c.info({"type": "x"}) == {"ok": 200} and bekleme == [5, 15] and c.stats["ag"] == 2
    c, oturum, bekleme = istemci(*[requests.ConnectionError("x")] * 4)
    with pytest.raises(requests.ConnectionError):
        c.info({"type": "x"})
    assert bekleme == [5, 15, 45] and oturum.cagri == 4
    for kod in (400, 404):                                   # 4xx (429 hariç): bekleme yok, tek istek
        c, oturum, bekleme = istemci(kod)
        with pytest.raises(requests.HTTPError):
            c.info({"type": "x"})
        assert bekleme == [] and oturum.cagri == 1


def test_429_retry_after_basligina_uyulur_takvimden_uzunsa_o_kadar_bekler():
    c, oturum, bekleme = istemci(Yanit(429, headers={"Retry-After": "90"}), Yanit(429, headers={"Retry-After": "1"}), Yanit(429, headers={"Retry-After": "abc"}), 200)
    assert c.info({"type": "x"}) == {"ok": 200}
    assert bekleme == [90, 10, 20]                                    # max(takvim, başlık); başlık takvimden kısa ya da geçersizse takvim
    c, oturum, bekleme = istemci(Yanit(429, headers={"Retry-After": "99999"}), 200)
    c.info({"type": "x"})
    assert bekleme == [300]                                           # uç değer RETRY_AFTER_MAX ile sınırlı


def test_eski_ilke_degismedi_diger_tuketiciler_icin():
    c, oturum, bekleme = istemci(500, 500, 500, ilke=None)
    with pytest.raises(requests.HTTPError):
        c.info({"type": "x"})
    assert bekleme == [2, 6] and oturum.cagri == 3                       # 5xx: 3 deneme (2/6 sn)
    c, oturum, bekleme = istemci(requests.ConnectionError("x"), ilke=None)
    with pytest.raises(requests.ConnectionError):
        c.info({"type": "x"})
    assert bekleme == [] and oturum.cagri == 1                           # ağ hatası yeniden denenmez
    c, oturum, bekleme = istemci(*[429] * 6, ilke=None)
    with pytest.raises(RateLimitError):
        c.info({"type": "x"})
    assert bekleme == [5, 10, 20, 40, 60]
