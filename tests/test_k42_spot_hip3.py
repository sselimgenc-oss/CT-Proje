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
    assert [mt.coin_sinifi(c) for c in ("BTC", "@142", "@0", "PURR/USDC", "xyz:GOLD", "flx:GOLD", "kPEPE")] == ["perp", "spot", "spot", "spot", "hip3", "hip3", "perp"]


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
    m.olay_isle(olay("a:1", adr(1), "xyz:GOLD", "B", 600, 100.0, 0.0, saat))                 # K-38: hedef tabanlı azaltma; 11 $ altına inmesin diye 600
    m.rules["canli_hip3_kopya"] = False                                                     # bayrak kapandı; açık sanal pozisyon duruyor
    ilk = m.hesap.sz(adr(1), "xyz:GOLD")
    s = m.olay_isle(olay("a:2", adr(1), "xyz:GOLD", "A", 200, 100.0, 600.0, saat))          # azaltma (hedef 400/600 → fark ≈ 18 $ ≥ 11 $)
    assert s[0].eylem == "azalt" and s[0].karar == "emir" and 0 < m.hesap.sz(adr(1), "xyz:GOLD") < ilk
    s = m.olay_isle(olay("a:3", adr(1), "xyz:GOLD", "B", 50, 100.0, 400.0, saat))           # artırma: atlanır
    assert s[0].neden == "hip3_atlandi"
    s = m.olay_isle(olay("a:4", adr(1), "xyz:GOLD", "A", 450, 100.0, 450.0, saat))          # tam kapanış
    assert s[0].eylem == "kapat" and m.hesap.sz(adr(1), "xyz:GOLD") == 0.0


def test_patlama_freni_ayni_coin_parcalari_tetiklemez_motor_o1(tmp_path):
    """Gerçek kayıt örneği (0x323f5af4): yalnız BTC'de çok sayıda parça açılış. Eskiden 8. parçada fren; şimdi tek coin → fren yok."""
    m, saat = _motor(tmp_path)
    sonuc = [m.olay_isle(olay(f"a:{i}", adr(1), "BTC", "B", 30, 100.0, 30.0 * i, saat))[0] for i in range(12)]
    assert not [x for x in sonuc if x.neden == "patlama_freni"]
    assert len(m.risk.yeni_coin.get(adr(1), [])) <= 1


def test_eski_risk_json_yeni_coin_bicimi_okunur_ve_davranis_sabit():
    """Eski biçim `yeni_coin: {adres: [ms, ms, ms]}` -> `(ms, "")` kayıtları; pencere dışı düşer; boş-adlı kayıt tek 'farklı coin' sayılır ("" + 6 yeni + 1 istenen = 8 -> fren)."""
    from collections import deque

    from copytrade.canli.risk import Risk
    from tests.test_canli_yurutucu import RULES, T0
    r = Risk(RULES, 1000.0, {"yeni_coin": {"a": [T0, T0 + 1000, T0 + 2000]}})
    assert r.yeni_coin["a"] == deque([(T0, ""), (T0 + 1000, ""), (T0 + 2000, "")])
    yeni = Risk(RULES, 1000.0, {"yeni_coin": {"a": [[T0, "BTC"], [T0 + 5, "ETH"]]}})
    assert list(yeni.yeni_coin["a"]) == [(T0, "BTC"), (T0 + 5, "ETH")]
    simdi = T0 + 3000
    for i in range(6):
        assert r.acilis_izni("a", f"C{i}", True, simdi)[0] is True
        r.yeni_coin_kaydet("a", f"C{i}", simdi)
    assert r.acilis_izni("a", "C6", True, simdi) == (False, "patlama_freni")
    r2 = Risk(RULES, 1000.0, {"yeni_coin": {"a": [T0, T0 + 1000]}})
    assert r2.acilis_izni("a", "X", True, T0 + 11 * 60_000)[0] is True and not r2.yeni_coin["a"]       # 10 dk pencere dışı: eski kayıtlar düşer


def test_ozet_trader_basina_spot_hip3_atlanan_sayac(tmp_path):
    m, saat = _motor(tmp_path)
    m.olay_isle(olay("a:1", adr(1), "xyz:GOLD", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("a:2", adr(1), "xyz:GOLD", "B", 300, 100.0, 300.0, saat))
    m.olay_isle(olay("a:3", adr(1), "@142", "B", 300, 100.0, 0.0, saat))
    assert m.ozet()["trader_atlanan"] == {"spot_atlandi": {adr(1): 1}, "hip3_atlandi": {adr(1): 2}}
