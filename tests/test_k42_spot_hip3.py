"""K‑42: spot ve HIP‑3 açılışı kopyalanmaz (spot_atlandi / hip3_atlandi); kapanış/azaltma engellenmez; `canli_hip3_kopya` açıkken HIP‑3 açılır. O1: patlama freni farklı coin sayar."""
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
    assert [mt.coin_sinifi(c) for c in ("BTC", "@142", "PURR/USDC", "xyz:GOLD", "kPEPE")] == ["perp", "spot", "spot", "hip3", "perp"]


def test_spot_acilis_atlanir_sanal_ve_sayac_kayit_ozet(tmp_path):
    m, saat = _motor(tmp_path)
    s = m.olay_isle(olay("a:1", adr(1), "@142", "B", 300, 100.0, 0.0, saat))
    assert [(x.eylem, x.karar, x.neden) for x in s] == [("ac", "atlandi", "spot_atlandi")]
    assert m.hesap.sz(adr(1), "@142") == 0.0 and m.sayac["emir"] == 0
    assert m.ozet()["spot_atlandi"] == 1 and m.ozet()["neden_say"]["spot_atlandi"] == 1
    assert len([x for x in kayitlar(tmp_path, "emir_yok") if x["neden"] == "spot_atlandi"]) == 1


def test_hip3_acilis_atlanir_varsayilan_kapali(tmp_path):
    m, saat = _motor(tmp_path)
    assert m.rules["canli_hip3_kopya"] is False
    s = m.olay_isle(olay("a:1", adr(1), "xyz:GOLD", "B", 300, 100.0, 0.0, saat))
    assert [(x.eylem, x.karar, x.neden) for x in s] == [("ac", "atlandi", "hip3_atlandi")]
    assert m.hesap.sz(adr(1), "xyz:GOLD") == 0.0 and m.ozet()["hip3_atlandi"] == 1
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))                 # perp normal
    assert s[0].karar == "emir"


def test_hip3_bayrak_acikken_acilir(tmp_path):
    m, saat = _motor(tmp_path, canli_hip3_kopya=True)
    s = m.olay_isle(olay("a:1", adr(1), "xyz:GOLD", "B", 300, 100.0, 0.0, saat))
    assert s[0].karar == "emir" and m.hesap.sz(adr(1), "xyz:GOLD") > 0 and m.ozet()["hip3_atlandi"] == 0


def test_hip3_acik_pozisyonun_azaltma_ve_kapanisi_engellenmez(tmp_path):
    m, saat = _motor(tmp_path, canli_hip3_kopya=True)
    m.olay_isle(olay("a:1", adr(1), "xyz:GOLD", "B", 300, 100.0, 0.0, saat))
    m.rules["canli_hip3_kopya"] = False                                                     # bayrak kapandı; açık sanal pozisyon duruyor
    ilk = m.hesap.sz(adr(1), "xyz:GOLD")
    s = m.olay_isle(olay("a:2", adr(1), "xyz:GOLD", "A", 200, 100.0, 300.0, saat))          # azaltma (2/3 ≈ 18 $ ≥ 11 $)
    assert s[0].eylem == "azalt" and s[0].karar == "emir" and 0 < m.hesap.sz(adr(1), "xyz:GOLD") < ilk
    s = m.olay_isle(olay("a:3", adr(1), "xyz:GOLD", "B", 50, 100.0, 100.0, saat))           # artırma: atlanır
    assert s[0].neden == "hip3_atlandi"
    s = m.olay_isle(olay("a:4", adr(1), "xyz:GOLD", "A", 150, 100.0, 150.0, saat))          # tam kapanış
    assert s[0].eylem == "kapat" and m.hesap.sz(adr(1), "xyz:GOLD") == 0.0


def test_patlama_freni_ayni_coin_parcalari_tetiklemez_motor_o1(tmp_path):
    """Gerçek kayıt örneği (0x323f5af4): yalnız BTC'de çok sayıda parça açılış. Eskiden 8. parçada fren; şimdi tek coin → fren yok."""
    m, saat = _motor(tmp_path)
    sonuc = [m.olay_isle(olay(f"a:{i}", adr(1), "BTC", "B", 30, 100.0, 30.0 * i, saat))[0] for i in range(12)]
    assert not [x for x in sonuc if x.neden == "patlama_freni"]
    assert len(m.risk.yeni_coin.get(adr(1), [])) <= 1
