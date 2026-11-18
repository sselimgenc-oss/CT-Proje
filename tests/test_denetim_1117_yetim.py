"""Denetim 2026-11-17 ADIM 5 (K2 / K-68): defter dışı borsa fazlası. (a) `canli_yetim_kapat_sn` kesintisiz sürerse reduce-only borsa teyitli kapatma (belirsiz emir varken yok),
(b) yetim fazla için İLK görülen mark'a SABİT referanslı ek borsa stopu (defter temelli stop değişmez)."""
import json

import pytest

from copytrade import kurallar
from copytrade.canli import motor as mt
from tests.test_canli_motor import adr, kayitlar, olay
from tests.test_canli_t4b import BorsaSim, kur_gercek


class MarkSim(BorsaSim):
    """BorsaSim + ETH mark'ı değiştirilebilir (stop referansı kovalamıyor mu sınanır)."""
    eth = "2000"

    def post(self, y):
        if y["type"] == "allMids":
            return {"BTC": "100", "ETH": self.eth}
        return super().post(y)


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _hazir(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, MarkSim())
    m.baslat()
    return m, sim, saat, tgp


def _dk(m, saat, n=1):
    for _ in range(n):
        saat.ms += 60_000
        m.dakika()


def test_uretim_degeri_600():
    assert kurallar.load_rules_asil()["canli_yetim_kapat_sn"] == 600


def test_yetim_tespit_alarm_kalici_durum_ve_sabit_referansli_stop(tmp_path, monkeypatch):
    """Altın örnek: borsada defterde olmayan 0,5 ETH (mark 2000 → 1.000 $). Tespit anı mark = 2000 → stop tetiği 2000 × (1 − 0,22) = 1560, sz 0,5, satış (long). Mark 2100'e çıksa da stop AYNI kalır (kovalamaz)."""
    m, sim, saat, tgp = _hazir(tmp_path, monkeypatch)
    sim.poz["ETH"] = 0.5
    t0 = saat()
    _dk(m, saat)                                                          # tespit (+ aynı dakikada borsa stopu eşitlemesi mutabakattan ÖNCE: ikinci dakikada stop)
    assert m.yetim_ilk["ETH"]["mark"] == 2000.0 and m.yetim_ilk["ETH"]["sz"] == pytest.approx(0.5) and m.yetim_ilk["ETH"]["ms"] == t0 + 60_000
    assert kayitlar(tmp_path, "yetim_tespit") and any("defter dışı borsa pozisyonu" in x for x in tgp.gonderilen)
    _dk(m, saat)
    st = [e for e in sim.acik if e["coin"] == "ETH"]
    assert len(st) == 1 and st[0]["side"] == "A" and st[0]["reduceOnly"] is True and st[0]["sz"] == pytest.approx(0.5) and float(st[0]["triggerPx"]) == pytest.approx(1560.0)
    sim.eth = "2100"
    _dk(m, saat, 3)
    st2 = [e for e in sim.acik if e["coin"] == "ETH"]
    assert [e["oid"] for e in st2] == [st[0]["oid"]] and float(st2[0]["triggerPx"]) == pytest.approx(1560.0)        # yeniden kurulmadı, referans ilk mark
    assert m.yetim_ilk["ETH"]["mark"] == 2000.0
    dosya = json.loads((tmp_path / "durum" / "motor.json").read_text())
    assert dosya["yetim_ilk"]["ETH"]["mark"] == 2000.0 and dosya["yetim_ilk"]["ETH"]["ms"] == t0 + 60_000           # kalıcı
    yeni, *_ = kur_gercek(tmp_path, monkeypatch, MarkSim())
    assert yeni.yetim_ilk["ETH"]["ms"] == t0 + 60_000 and yeni.yetim_ilk["ETH"]["mark"] == 2000.0                   # yeniden başlatmada sayaç ve referans korunur


def test_600sn_dolmadan_kapatma_yok_dolunca_reduce_only_kapanir_sonra_stop_temizlenir(tmp_path, monkeypatch):
    m, sim, saat, tgp = _hazir(tmp_path, monkeypatch)
    sim.poz["ETH"] = 0.5
    _dk(m, saat)                                                          # t=60 sn: tespit
    _dk(m, saat, 9)                                                       # 9 dk daha: toplam 540 sn kesintisiz
    assert sim.poz["ETH"] == 0.5 and not any(x["coin"] == "ETH" for x in sim.siparisler)
    _dk(m, saat)                                                          # 600 sn: vadesi doldu
    kap = [x for x in sim.siparisler if x["coin"] == "ETH"]
    assert kap and all(x["reduce_only"] and not x["is_buy"] for x in kap) and sim.poz["ETH"] == pytest.approx(0.0, abs=1e-9)
    assert "ETH" not in m.yetim_ilk and kayitlar(tmp_path, "yetim_kapat") and any("kapatıldı" in x for x in tgp.gonderilen)
    _dk(m, saat)
    assert not any(e["coin"] == "ETH" for e in sim.acik)                  # yetim stopu da kalktı


def test_kesinti_sayaci_sifirlar(tmp_path, monkeypatch):
    m, sim, saat, tgp = _hazir(tmp_path, monkeypatch)
    sim.poz["ETH"] = 0.5
    _dk(m, saat, 6)
    sim.poz["ETH"] = 0.0                                                  # fazla kayboldu (ör. elle kapatıldı)
    _dk(m, saat)
    assert "ETH" not in m.yetim_ilk and kayitlar(tmp_path, "yetim_bitti")
    sim.poz["ETH"] = 0.5
    _dk(m, saat, 5)                                                       # yeniden belirdi: sayaç sıfırdan; 5 dk < 10 dk
    assert sim.poz["ETH"] == 0.5 and not any(x["coin"] == "ETH" for x in sim.siparisler)


def test_belirsiz_emir_varken_kapatilmaz_cozulunce_kapanir(tmp_path, monkeypatch):
    m, sim, saat, tgp = _hazir(tmp_path, monkeypatch)
    sim.poz["ETH"] = 0.5
    _dk(m, saat)
    m.hesap.belirsiz["0xabc"] = {"ms": saat(), "deneme": 0, "adres": adr(1), "coin": "ETH"}
    sim.durumlar["0xabc"] = {"status": "unknownOid"}
    m.belirsiz_coz = lambda simdi: 0                                      # çözüm bu testte devre dışı: belirsiz kalır
    _dk(m, saat, 11)
    assert sim.poz["ETH"] == 0.5 and not any(x["coin"] == "ETH" for x in sim.siparisler) and kayitlar(tmp_path, "yetim_kapat_ertelendi")
    m.hesap.belirsiz.clear()
    _dk(m, saat)
    assert sim.poz["ETH"] == pytest.approx(0.0, abs=1e-9)                 # eşik zaten geçmişti: çözülür çözülmez (bir sonraki dakikada) kapanır


def test_defterli_coinde_borsa_fazlasi_ek_stop_defter_stopu_degismez_ve_yalniz_fazla_kapanir(tmp_path, monkeypatch):
    """Defter BTC 0,27272 (giriş 100); borsada 0,5 → fazla 0,22728. Defter stopu (sz 0,27272, tetik 78) AYNEN; ek yetim stopu sz 0,22728, tetik 78. 10 dk sonra yalnız 0,22728 satılır, defter payı kalır."""
    m, sim, saat, tgp = _hazir(tmp_path, monkeypatch)
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert sim.poz["BTC"] == pytest.approx(0.27272, abs=1e-5)
    sim.poz["BTC"] = 0.5
    _dk(m, saat, 2)
    st = sorted((e for e in sim.acik if e["coin"] == "BTC"), key=lambda e: e["sz"])
    assert [round(e["sz"], 5) for e in st] == [0.22728, 0.27272] and all(float(e["triggerPx"]) == pytest.approx(78.0) for e in st)
    assert m.borsa_stop.stoplar["BTC"]["sz"] == pytest.approx(0.27272, abs=1e-5)
    _dk(m, saat, 9)
    assert sim.poz["BTC"] == pytest.approx(0.27272, abs=1e-5) and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.27272, abs=1e-5)


def test_sanal_kip_yetim_izlemez(tmp_path):
    from tests.test_canli_motor import kur
    m, *_ = kur(tmp_path)
    assert m.kip == "sanal" and m.yetim_ilk == {}
