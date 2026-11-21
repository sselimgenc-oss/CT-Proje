"""K‑42 → K-86: spot ve HIP‑3 coinleri sabit coin listesinde (`canli_coin_listesi`) yok → açılış/artırma `liste_disi` (sayılır); kapanış/azaltma engellenmez."""
from __future__ import annotations

import pytest

from copytrade.canli import motor as mt
from tests.test_canli_motor import SahteHL, adr, kadro, kayitlar, kur, olay, satir


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _motor(tmp_path, **kurallar):
    k = kadro([satir(1, 1)], 0)
    hl = SahteHL()
    hl.mids["xyz:GOLD"] = "100"
    hl.kitaplar["xyz:GOLD"] = {"levels": [[{"px": "99.9", "sz": "100000"}], [{"px": "100", "sz": "100000"}]]}
    m, hl, saat, _ = kur(tmp_path, kadro_=k, hl=hl, kurallar=kurallar)
    k["kosu_ms"] = saat() - 3_600_000
    m.baslat()
    return m, saat


def test_coin_sinifi():
    assert [mt.coin_sinifi(c) for c in ("BTC", "@142", "@0", "PURR/USDC", "xyz:GOLD", "flx:GOLD", "kPEPE")] == ["perp", "spot", "spot", "spot", "hip3", "hip3", "perp"]


def test_spot_ve_hip3_acilis_liste_disi_sayac_kayit_ozet(tmp_path):
    m, saat = _motor(tmp_path)
    s = m.olay_isle(olay("a:1", adr(1), "@142", "B", 300, 100.0, 0.0, saat))
    assert [(x.eylem, x.karar, x.neden) for x in s] == [("ac", "atlandi", "liste_disi")]
    s = m.olay_isle(olay("a:2", adr(1), "xyz:GOLD", "B", 300, 100.0, 0.0, saat))
    assert [(x.eylem, x.karar, x.neden) for x in s] == [("ac", "atlandi", "liste_disi")]
    assert m.hesap.sz(adr(1), "@142") == 0.0 and m.hesap.sz(adr(1), "xyz:GOLD") == 0.0 and m.sayac["emir"] == 0
    assert m.ozet()["liste_disi"] == 2 and m.ozet()["neden_say"]["liste_disi"] == 2
    assert len([x for x in kayitlar(tmp_path, "emir_yok") if x["neden"] == "liste_disi"]) == 2
    assert m.ozet()["trader_atlanan"] == {"liste_disi": {adr(1): 2}}
    s = m.olay_isle(olay("a:3", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))                 # listedeki perp normal
    assert s[0].karar == "emir"


def test_liste_disi_acik_pozisyonun_azaltma_ve_kapanisi_engellenmez(tmp_path):
    m, saat = _motor(tmp_path, canli_coin_listesi=["BTC", "xyz:GOLD"])
    m.olay_isle(olay("a:1", adr(1), "xyz:GOLD", "B", 600, 100.0, 0.0, saat))
    m.rules["canli_coin_listesi"] = ["BTC"]                                                 # liste daraldı; açık pozisyon duruyor
    ilk = m.hesap.sz(adr(1), "xyz:GOLD")
    assert ilk > 0
    s = m.olay_isle(olay("a:2", adr(1), "xyz:GOLD", "A", 300, 100.0, 600.0, saat))
    assert s[0].eylem == "azalt" and s[0].karar == "emir" and 0 < m.hesap.sz(adr(1), "xyz:GOLD") < ilk
    s = m.olay_isle(olay("a:3", adr(1), "xyz:GOLD", "B", 50, 100.0, 300.0, saat))           # artırma: liste dışı
    assert s[0].neden == "liste_disi"
    s = m.olay_isle(olay("a:4", adr(1), "xyz:GOLD", "A", 350, 100.0, 350.0, saat))          # tam kapanış
    assert s[0].eylem == "kapat" and m.hesap.sz(adr(1), "xyz:GOLD") == 0.0
