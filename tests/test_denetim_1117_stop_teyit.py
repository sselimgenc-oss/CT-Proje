"""Denetim 2026-11-17 ADIM 1 (Fable onaylı): O2 (stop görünmüyor ≠ pozisyon kapandı) ve Kaçırılan-2 (boş pozisyon yanıtı tek okumayla defteri silmez)."""
import pytest

from tests.test_canli_motor import adr, kayitlar, olay
from tests.test_canli_t4b import HLADR, BorsaSim, kur_gercek


def _ac(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dakika()
    assert len(sim.acik) == 1
    return m, sim, saat, tgp


def test_o2_stop_gorunmuyor_ama_borsada_pozisyon_duruyor_kapatilmaz_stop_yeniden_kurulur(tmp_path, monkeypatch):
    """Eski hata: openOrders'ta stop yok → "tetiklendi" sayılıp pozisyon kapatılırdı. Şimdi borsa pozisyonu aynı yön/miktarda duruyorsa kapanış YOK, stop yeniden kurulur, alarm gider."""
    m, sim, saat, tgp = _ac(tmp_path, monkeypatch)
    ilk = sim.acik[0]["oid"]
    sim.acik.clear()                                                    # stop açık emirlerden düştü (boş/yanlış yanıt ya da dışarıda iptal); pozisyon borsada duruyor
    emir_once = len(sim.siparisler)
    saat.ms += 60_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.27273, abs=1e-5) and sim.poz["BTC"] == pytest.approx(0.27273, abs=1e-5)
    assert len(sim.siparisler) == emir_once and not kayitlar(tmp_path, "harici_kapanis")      # kapanış emri gitmedi
    assert len(sim.acik) == 1 and sim.acik[0]["oid"] != ilk and m.borsa_stop.stoplar["BTC"]["oid"] == sim.acik[0]["oid"]   # stop yeniden kuruldu
    assert kayitlar(tmp_path, "borsa_stop_kayip_poz_duruyor") and any("pozisyon borsada duruyor" in x for x in tgp.gonderilen)


def test_o2_borsa_pozisyonu_gercekten_kapanmissa_eski_akis_calisir(tmp_path, monkeypatch):
    m, sim, saat, tgp = _ac(tmp_path, monkeypatch)
    sim.stop_tetikle("BTC")
    saat.ms += 60_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9) and kayitlar(tmp_path, "harici_kapanis") and not kayitlar(tmp_path, "borsa_stop_kayip_poz_duruyor")


def test_o2_borsa_okunamazsa_kapatilmaz(tmp_path, monkeypatch):
    m, sim, saat, tgp = _ac(tmp_path, monkeypatch)
    sim.acik.clear()
    gercek = m.post

    def bozuk(y):
        if y["type"] == "clearinghouseState" and y["user"] == HLADR:
            raise OSError("ag")
        return gercek(y)
    m.post = bozuk
    emir_once = len(sim.siparisler)
    saat.ms += 60_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.27273, abs=1e-5) and len(sim.siparisler) == emir_once and kayitlar(tmp_path, "borsa_stop_kayip_teyitsiz")


def _kapat_hazir(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    sim.trader_poz[adr(1)] = {}
    return m, sim, saat, tgp


def test_kacirilan2_bos_okuma_ikinci_okumayla_curutulur_defter_silinmez_gercek_kapanis_gider(tmp_path, monkeypatch):
    """Eski hata: ilk pozisyon okuması geçerli ama BOŞ → "borsada yok" → defter emirsiz silinir. Şimdi ikinci okuma pozisyonu gösterir → gerçek reduce-only kapanış emri gider."""
    m, sim, saat, tgp = _kapat_hazir(tmp_path, monkeypatch)
    gercek, bos = m.post, [True]

    def post(y):
        if y["type"] == "clearinghouseState" and y["user"] == HLADR and bos:
            bos.pop()
            return {"marginSummary": {"accountValue": "1000"}, "assetPositions": []}
        return gercek(y)
    m.post = post
    emir_once = len(sim.siparisler)
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert not kayitlar(tmp_path, "harici_kapanis") and len(sim.siparisler) == emir_once + 1 and sim.siparisler[-1]["reduce_only"] is True
    assert sim.poz["BTC"] == pytest.approx(0.0, abs=1e-9) and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)    # emirle kapandı (silinmedi)
    assert kayitlar(tmp_path, "bos_okuma_teyitsiz") and m.risk.acilis_durdu.get("mutabakat") is True


def test_kacirilan2_ikinci_okuma_basarisizsa_defter_silinmez_mutabakat_bayragi_alarm(tmp_path, monkeypatch):
    m, sim, saat, tgp = _kapat_hazir(tmp_path, monkeypatch)
    gercek, sayac = m.post, [0]

    def post(y):
        if y["type"] == "clearinghouseState" and y["user"] == HLADR:
            sayac[0] += 1
            if sayac[0] == 1:
                return {"marginSummary": {"accountValue": "1000"}, "assetPositions": []}
            if sayac[0] == 2:
                raise OSError("ag")
        return gercek(y)
    m.post = post
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert not kayitlar(tmp_path, "harici_kapanis") and kayitlar(tmp_path, "bos_okuma_teyitsiz")[0]["ikinci_okuma"] is None
    assert m.risk.acilis_durdu.get("mutabakat") is True and any("okuması tutarsız" in x for x in tgp.gonderilen)


def test_kacirilan2_iki_okuma_da_bos_ise_eski_harici_kapanis_akisi_calisir(tmp_path, monkeypatch):
    m, sim, saat, tgp = _kapat_hazir(tmp_path, monkeypatch)
    sim.poz["BTC"] = 0.0                                                # borsada gerçekten yok (dışarıda kapanmış)
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert kayitlar(tmp_path, "harici_kapanis") and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9) and not kayitlar(tmp_path, "bos_okuma_teyitsiz")
