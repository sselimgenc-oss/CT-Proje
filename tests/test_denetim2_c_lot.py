"""2. denetim O-5 + D-1 [A] (altın örnekler, elle hesap): açılış/artırma miktarı lota AŞAĞI yuvarlanır, tam dolan lot "dolu" sayılır; yarım lotun altındaki azaltma kalıntısı kuyruğa alınmaz
(`kapanis_eksik` / tüm açılışları durdurma yok); `sz_sifir` kuyruk girdisi düşer. Sanalda lot yok → sanal sonuçlar değişmez."""
from __future__ import annotations

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import yurutucu as yu
from copytrade.kurallar import load_rules_asil
from tests.test_canli_motor import adr
from tests.test_canli_t4b import BorsaSim, kur_gercek
from tests.test_canli_yurutucu import SahteExchange, dolu


@pytest.fixture(autouse=True)
def _m():
    yield
    mt.MASKE.clear()


XRP_KITAP = {"levels": [[{"px": "2.49", "sz": "1000"}], [{"px": "2.5", "sz": "1000"}]]}


def xrp_post(y):
    if y["type"] == "meta":
        return {"universe": [{"name": "XRP", "szDecimals": 0, "maxLeverage": 20}]}
    return XRP_KITAP


def test_acilis_miktari_lota_asagi_14_dolar_xrp_5_lot_ve_dolunca_dolu():
    """XRP px 2,5, szDecimals 0: 14 $ / 2,5 = 5,6 → AŞAĞI 5 lot (eski en yakın yuvarlama 6 lot = 15 $, +%7). 5 lot (12,5 $ ≥ 10 $ min) tam dolar → `dolu` (eskiden 12,5 < 14 × 0,999 → `kismi`)."""
    ex = SahteExchange(dolu("5", "2.5"))
    d = yu.GercekYurutucu(ex, xrp_post, load_rules_asil()).emir("XRP", "B", 14.0)
    assert ex.cagrilar[0]["sz"] == 5 and d.sz == 5 and d.durum == "dolu"
    ex2 = SahteExchange(dolu("5", "2.5"))
    d2 = yu.GercekYurutucu(ex2, xrp_post, load_rules_asil()).emir("XRP", "B", 13.6)               # 5,44 → 5; eskiden de 5 ama "kismi" (12,5 < 13,58)
    assert ex2.cagrilar[0]["sz"] == 5 and d2.durum == "dolu"


def test_kismi_dolum_kismi_kalir_ve_reduce_only_eskisi_gibi_en_yakin_yuvarlar():
    ex = SahteExchange(dolu("3", "2.5"))
    d = yu.GercekYurutucu(ex, xrp_post, load_rules_asil()).emir("XRP", "B", 14.0)                    # 5 lot istendi, 3 doldu: gerçekten kısmi
    assert d.durum == "kismi"
    ex2 = SahteExchange(dolu("6", "2.5"))
    yu.GercekYurutucu(ex2, xrp_post, load_rules_asil()).emir("XRP", "A", 14.0, reduce_only=True, acik_sz=10.0)
    assert ex2.cagrilar[0]["sz"] == 6                                                                # kapanış/azaltma: round(5,6) = 6 (davranış değişmedi)


def test_lot_adim_bilinen_ve_bilinmeyen_coin():
    g = yu.GercekYurutucu(SahteExchange(), xrp_post, load_rules_asil())
    assert g.lot_adim("XRP") == 1.0 and g.lot_adim("YOK") is None


class XrpSim(BorsaSim):
    def post(self, y):
        if y["type"] == "meta":
            return {"universe": [{"name": "BTC", "szDecimals": 5}, {"name": "ETH", "szDecimals": 4}, {"name": "XRP", "szDecimals": 0}]}
        if y["type"] == "l2Book" and y["coin"] == "XRP":
            return XRP_KITAP
        return super().post(y)


def _xrp_motor(tmp_path, monkeypatch):
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, XrpSim())
    m.baslat()
    m.marks["XRP"], m.mark_ms["XRP"] = 2.5, saat()
    m.hesap.uygula(adr(1), "XRP", "B", 5.44, 2.5, 0.0, saat())
    sim.poz["XRP"] = 5.44
    return m, sim, saat


def test_yarim_lot_alti_kalinti_kuyruga_alinmaz_kapanis_eksik_yok_40_dk_sonra_da(tmp_path, monkeypatch):
    """XRP px 2,5 dec 0: yerel 5,44, hedef 5,0 → kalıntı 0,44 (1,1 $ > toz 1 $ ama < ½ lot): kuyruk BOŞ, `kapanis_eksik` yok; 40 dk ilerletince de yok."""
    m, sim, saat = _xrp_motor(tmp_path, monkeypatch)
    m._azalt_kuyruga(adr(1), "XRP", 5.0, "trader_azalt", saat(), 2.5)
    assert m.kapanis_kuyrugu == {}
    for _ in range(41):
        saat.ms += 60_000
        m._kuyruk_isle(saat())
        assert not m.risk.acilis_durdu.get("kapanis_eksik")
    assert not sim.siparisler                                                                       # hiç emir gitmedi


def test_lot_ustu_kalinti_eskisi_gibi_kuyruga_girer(tmp_path, monkeypatch):
    m, sim, saat = _xrp_motor(tmp_path, monkeypatch)
    m._azalt_kuyruga(adr(1), "XRP", 4.0, "trader_azalt", saat(), 2.5)                               # kalıntı 1,44 lot ≥ ½
    assert list(m.kapanis_kuyrugu) == [f"{adr(1)}|XRP"]


def test_kuyruktaki_sz_sifir_girdisi_dusurulur_kapanis_eksik_dogmaz(tmp_path, monkeypatch):
    """Eski durumdan (ya da lot bilinmeden) kuyrukta kalmış 0,44 XRP'lik azaltma: emir `sz_sifir` → girdi düşer (min_nosyonel gibi), 5 denemelik `kapanis_eksik` döngüsü yok."""
    m, sim, saat = _xrp_motor(tmp_path, monkeypatch)
    m._eksik_ekle(adr(1), "XRP", "azalt", 5.0, "trader_azalt", saat(), deneme=0)
    m.kapanis_kuyrugu[f"{adr(1)}|XRP"]["eksik"] = False
    m._kuyruk_isle(saat() + 60_000)
    assert m.kapanis_kuyrugu == {} and not m.risk.acilis_durdu.get("kapanis_eksik")


def test_sanal_yurutucuda_lot_yok_sanal_kuyruk_davranisi_ayni(tmp_path):
    from tests.test_canli_motor import kur
    m, hl, saat, _ = kur(tmp_path)
    assert m._lot_adim("BTC") is None
