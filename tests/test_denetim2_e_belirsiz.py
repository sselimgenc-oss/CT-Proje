"""2. denetim O-4 + D-3 (+ belirsiz çözümün sıkılaştırılması): bozuk/boş 200 yanıtı ve belirsiz 4xx "red" DEĞİL "belirsiz"; `belirsiz_coz` yalnız açık `unknownOid` yanıtını ve İKİ ardışık okumada "emir yok" sayar;
hata / beklenmeyen biçim çözülmemiş kalır (açılış bayrağı sürer). D-2 (`set_expires_after`) YAPILMADI (Fable: stopları bozar)."""
from __future__ import annotations

import pytest
import requests

from copytrade.canli import motor as mt
from tests.test_canli_g12 import SZ, ZamanAsimiBorsa
from tests.test_canli_motor import adr, kayitlar, olay
from tests.test_canli_t4b import kur_gercek


@pytest.fixture(autouse=True)
def _m():
    yield
    mt.MASKE.clear()


class BozukGovdeBorsa(ZamanAsimiBorsa):
    """Emir HL'de doldu ama SDK 2xx gövdesini ayrıştıramadı: `{"error": "Could not parse JSON: ..."}` (SDK 0.24.0 `api.py` davranışı)."""
    def order(self, coin, is_buy, sz, px, tif, reduce_only, cloid=None):
        if isinstance(tif, dict) and "trigger" in tif:
            return super().order(coin, is_buy, sz, px, tif, reduce_only, cloid=cloid)
        gercek = super(ZamanAsimiBorsa, self).order(coin, is_buy, sz, px, tif, reduce_only, cloid=cloid)
        dolan = self.siparisler[-1]["dolan"]
        self.durumlar[str(cloid)] = {"status": "order", "order": {"order": {"coin": coin, "side": "B" if is_buy else "A", "limitPx": str(px), "sz": "0.0", "origSz": str(dolan), "oid": 9}, "status": "filled"}}
        del gercek
        return {"error": "Could not parse JSON: <html>502</html>"}


def test_bozuk_200_govdesi_belirsiz_borsada_acik_defterde_yok_orderstatus_cozer(tmp_path, monkeypatch):
    sim = BozukGovdeBorsa()
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert s[0].karar == "belirsiz" and s[0].neden == "yanit_bicimi" and m.sayac["red"] == 0
    assert sim.poz["BTC"] == pytest.approx(SZ) and m.hesap.sz(adr(1), "BTC") == 0.0
    assert len(m.hesap.belirsiz) == 1 and m.risk.acilis_durdu["belirsiz"] is True and len(m.niyet.sonucsuz()) == 1
    saat.ms += 60_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(SZ) and m.hesap.belirsiz == {} and m.risk.acilis_durdu["belirsiz"] is False       # orderStatus(cloid) filled → deftere TEK kez


class SiraliDurumBorsa(ZamanAsimiBorsa):
    """`orderStatus` yanıtları sırayla verilir (liste biter → unknownOid)."""
    def __init__(self, yanitlar, **k):
        super().__init__(ulasti=False, **k)
        self.yanitlar = list(yanitlar)

    def post(self, y):
        if y["type"] == "orderStatus" and self.yanitlar:
            self.istekler.append(y)
            r = self.yanitlar.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return super().post(y)


def _belirsiz_kur(tmp_path, monkeypatch, yanitlar):
    sim = SiraliDurumBorsa(yanitlar)
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert len(m.hesap.belirsiz) == 1
    return m, sim, saat, tgp


def _dk(m, saat, n=1):
    for _ in range(n):
        saat.ms += 60_000
        m.dakika()


def test_unknownoid_iki_ardisik_okumada_emir_yok_kesinlesir(tmp_path, monkeypatch):
    m, sim, saat, _ = _belirsiz_kur(tmp_path, monkeypatch, [{"status": "unknownOid"}, {"status": "unknownOid"}])
    _dk(m, saat)
    assert len(m.hesap.belirsiz) == 1 and m.risk.acilis_durdu["belirsiz"] is True and kayitlar(tmp_path, "belirsiz_emir_yok_ilk")
    _dk(m, saat)
    assert m.hesap.belirsiz == {} and kayitlar(tmp_path, "belirsiz_cozuldu")[0]["durum"] == "emir_yok" and m.risk.acilis_durdu["belirsiz"] is False


@pytest.mark.parametrize("tuhaf", [{"error": "rate limited"}, {}, [], "unknownOid", None, {"status": "baska"}, requests.exceptions.ConnectionError("x")])
def test_hata_ya_da_beklenmeyen_bicim_cozulmemis_kalir_sayac_sifirlanir(tmp_path, monkeypatch, tuhaf):
    m, sim, saat, _ = _belirsiz_kur(tmp_path, monkeypatch, [{"status": "unknownOid"}, tuhaf, {"status": "unknownOid"}])
    _dk(m, saat, 3)                                                           # unknownOid, tuhaf (sayaç sıfır), unknownOid (yeniden ilk)
    assert len(m.hesap.belirsiz) == 1 and m.risk.acilis_durdu["belirsiz"] is True and m.sayac["red"] == 0
    assert list(m.hesap.belirsiz.values())[0].get("yok_say") == 1
    _dk(m, saat)                                                              # ikinci ardışık unknownOid (liste bitti → sim varsayılanı)
    assert m.hesap.belirsiz == {}


def test_surekli_tuhaf_yanit_hic_cozmez_5_denemede_alarm(tmp_path, monkeypatch):
    m, sim, saat, tgp = _belirsiz_kur(tmp_path, monkeypatch, [{"error": "x"}] * 8)
    _dk(m, saat, 6)
    assert len(m.hesap.belirsiz) == 1 and m.risk.acilis_durdu["belirsiz"] is True and any("belirsiz emir çözülemiyor" in x.lower() for x in tgp.gonderilen)
