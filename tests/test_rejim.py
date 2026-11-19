"""ML Otonom rejim okuyucusu (copytrade/canli/rejim.py): yalnız kayıt; her hata `{}` / None döner, istisna yok."""
from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from copytrade.canli import rejim

URET = "2026-11-19T12:00:00Z"
URET_MS = int(datetime(2026, 11, 19, 12, 0, tzinfo=UTC).timestamp() * 1000)
GECERLI_MS = URET_MS + 90 * 60_000          # 13:30 UTC: son geçerli an
URL = "https://pano.example/rejim.json"


def _veri(**degis) -> dict:
    v = {
        "surum": 1,
        "kaynak": "ML",
        "uretim_ts": URET,
        "gecerlilik_dk": 90,
        "rejimler": ["trend_up", "trend_down", "range", "volatile", "unclear"],
        "varliklar": {
            "BTC/USDT": {"baz": "BTC", "varlik_sinifi": "kripto",
                         "4h": {"rejim": "trend_up", "bar_ts": "2026-11-19T08:00:00Z"},
                         "1d": {"rejim": "range", "bar_ts": "2026-11-18T00:00:00Z"}},
            "ETH/USDT": {"baz": "ETH", "varlik_sinifi": "kripto",
                         "4h": {"rejim": "volatile", "bar_ts": "2026-11-19T08:00:00Z"},
                         "1d": {"rejim": "unclear", "bar_ts": None}},
        },
    }
    v.update(degis)
    return v


class Sahte:
    """Sahte getirici: verilen yanıtı döner ya da hata fırlatır; çağrı sayar."""

    def __init__(self, yanit=None, hata: Exception | None = None):
        self.yanit = yanit
        self.hata = hata
        self.cagri: list[str] = []

    def __call__(self, url: str):
        self.cagri.append(url)
        if self.hata is not None:
            raise self.hata
        return copy.deepcopy(self.yanit)


# --- geçerli veri -----------------------------------------------------------

def test_gecerli_veri_rejimleri_coine_esler():
    sahte = Sahte(_veri())
    assert rejim.oku(URL, sahte, simdi_ms=URET_MS + 30 * 60_000) == {
        "BTC": {"4h": "trend_up", "1d": "range"},
        "ETH": {"4h": "volatile", "1d": "unclear"},
    }
    assert sahte.cagri == [URL]


def test_gecerlilik_siniri_dahil_gecerli_sonrasi_bayat():
    assert rejim.oku(URL, Sahte(_veri()), simdi_ms=GECERLI_MS) != {}
    assert rejim.oku(URL, Sahte(_veri()), simdi_ms=GECERLI_MS + 1) == {}


def test_bayat_veri_bilinmiyor_sayilir():
    """uretim_ts + gecerlilik_dk (90 dk) geçmişse tüm yanıt `{}`; motor için rejim None olur."""
    anlik = rejim.oku_tam(URL, Sahte(_veri()), simdi_ms=GECERLI_MS + 60_000)
    assert anlik == {}
    assert rejim.coin_rejimi(anlik, "BTC", GECERLI_MS + 60_000) is None


def test_eksik_zaman_dilimi_ve_sozluk_disi_etiket_none_olur():
    v = _veri()
    v["varliklar"]["BTC/USDT"]["1d"] = {"rejim": "bilinmeyen_etiket"}
    v["varliklar"]["ETH/USDT"]["4h"] = "yanlis_tip"
    sonuc = rejim.oku(URL, Sahte(v), simdi_ms=URET_MS)
    assert sonuc["BTC"] == {"4h": "trend_up", "1d": None}
    assert sonuc["ETH"] == {"4h": None, "1d": "unclear"}


# --- eşleme -----------------------------------------------------------------

def test_baz_hl_coinine_olduğu_gibi_eslenir():
    v = _veri(varliklar={
        "1000SHIB/USDT": {"baz": "1000SHIB", "4h": {"rejim": "range"}, "1d": {"rejim": "range"}},
        "SOL/USDC": {"baz": " SOL ", "4h": {"rejim": "trend_down"}, "1d": {"rejim": "range"}},
    })
    sonuc = rejim.oku(URL, Sahte(v), simdi_ms=URET_MS)
    assert set(sonuc) == {"1000SHIB", "SOL"}
    assert sonuc["SOL"]["4h"] == "trend_down"


def test_ayni_baz_iki_ciftte_ilk_gelen_kazanir():
    v = _veri(varliklar={
        "BTC/USDT": {"baz": "BTC", "4h": {"rejim": "trend_up"}, "1d": {"rejim": "range"}},
        "BTC/USDC": {"baz": "BTC", "4h": {"rejim": "range"}, "1d": {"rejim": "range"}},
    })
    assert rejim.oku(URL, Sahte(v), simdi_ms=URET_MS)["BTC"]["4h"] == "trend_up"


# --- bozuk biçim ------------------------------------------------------------

@pytest.mark.parametrize("bozuk", [
    None,
    [],
    "metin",
    _veri(surum=2),
    _veri(surum=True),
    _veri(surum="1"),
    _veri(uretim_ts="19.11.2026 12:00"),
    _veri(uretim_ts="2026-11-19T12:00:00"),          # saat dilimi yok
    _veri(uretim_ts=None),
    _veri(gecerlilik_dk=0),
    _veri(gecerlilik_dk=-5),
    _veri(gecerlilik_dk=True),
    _veri(gecerlilik_dk="90"),
    _veri(varliklar=None),
    _veri(varliklar=["BTC"]),
])
def test_bozuk_yanit_bos_doner(bozuk):
    assert rejim.oku(URL, Sahte(bozuk), simdi_ms=URET_MS) == {}


def test_bozuk_varlik_girdisi_digerlerini_bozmaz():
    v = _veri(varliklar={
        "BOZUK": "dict-degil",
        "SIZ/USDT": {"4h": {"rejim": "range"}},          # baz yok
        "BTC/USDT": {"baz": "BTC", "4h": {"rejim": "trend_up"}, "1d": {"rejim": "range"}},
    })
    assert rejim.oku(URL, Sahte(v), simdi_ms=URET_MS) == {"BTC": {"4h": "trend_up", "1d": "range"}}


@pytest.mark.parametrize("hata", [TimeoutError("zaman aşımı"), ConnectionError("yok"), ValueError("json değil"), RuntimeError("beklenmeyen")])
def test_getirici_hatasi_istisna_fırlatmaz(hata):
    assert rejim.oku(URL, Sahte(hata=hata), simdi_ms=URET_MS) == {}
    assert rejim.oku_tam(URL, Sahte(hata=hata), simdi_ms=URET_MS) == {}


# --- kapalı kaynak ----------------------------------------------------------

@pytest.mark.parametrize("adres", ["", "   ", None, 0])
def test_bos_adres_ag_cagrisi_yapmaz(adres):
    sahte = Sahte(_veri())
    assert rejim.oku(adres, sahte, simdi_ms=URET_MS) == {}
    assert rejim.oku_tam(adres, sahte, simdi_ms=URET_MS) == {}
    assert sahte.cagri == []


# --- motor için: sipariş anında bayatlık ------------------------------------

def test_coin_rejimi_bayat_ve_bilinmeyen_coin_icin_none():
    anlik = rejim.oku_tam(URL, Sahte(_veri()), simdi_ms=URET_MS)
    assert rejim.coin_rejimi(anlik, "BTC", URET_MS) == {"4h": "trend_up", "1d": "range"}
    assert rejim.coin_rejimi(anlik, "DOGE", URET_MS) is None
    assert rejim.coin_rejimi(anlik, "BTC", GECERLI_MS + 1) is None      # önbellek okunduktan sonra bayatladı
    assert rejim.coin_rejimi({}, "BTC", URET_MS) is None
    assert rejim.coin_rejimi({"bozuk": 1}, "BTC", URET_MS) is None


def test_oku_tam_gecerli_son_ms_gecerlilik_penceresi():
    anlik = rejim.oku_tam(URL, Sahte(_veri()), simdi_ms=URET_MS)
    assert anlik["gecerli_son_ms"] == GECERLI_MS
