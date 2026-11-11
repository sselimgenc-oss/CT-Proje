"""K-64: gerçek kipte borsada duran felaket stopu (HL tetik emri; reduce-only, net pozisyona)."""
import pytest

from copytrade.canli import borsa_stop as bs
from copytrade.canli import motor as mt
from copytrade.canli import yurutucu as yu
from copytrade.canli.hesap import Poz
from tests.test_canli_motor import RULES, adr, kayitlar, olay
from tests.test_canli_t4b import HLADR, BorsaSim, kur_gercek


def test_hedefler_net_pozisyon_agirlikli_giris_min_nosyonel():
    poz = {adr(1): {"BTC": Poz(0.2, 100.0, 0), "ETH": Poz(-0.001, 2000.0, 0)}, adr(2): {"BTC": Poz(0.1, 130.0, 0)}}
    h = bs.hedefler(poz, {"BTC": 100.0, "ETH": 2000.0}, 0.22, 10.0)
    assert set(h) == {"BTC"}                                                   # ETH 2 $ < 10 $: stop yok
    assert h["BTC"]["long"] and h["BTC"]["sz"] == pytest.approx(0.3) and h["BTC"]["tetik"] == pytest.approx(110.0 * 0.78)     # giriş (0,2·100 + 0,1·130) / 0,3 = 110
    ters = {adr(1): {"SOL": Poz(-1.0, 100.0, 0)}, adr(2): {"SOL": Poz(0.4, 90.0, 0)}}
    h2 = bs.hedefler(ters, {"SOL": 100.0}, 0.22, 10.0)
    assert not h2["SOL"]["long"] and h2["SOL"]["sz"] == pytest.approx(0.6) and h2["SOL"]["tetik"] == pytest.approx(122.0)    # baskın taraf (short) girişi
    assert bs.degisti_mi({"long": True, "sz": 1.0, "tetik": 78.0}, {"long": True, "sz": 1.01, "tetik": 78.2}) is False
    assert bs.degisti_mi({"long": True, "sz": 1.0, "tetik": 78.0}, {"long": True, "sz": 1.05, "tetik": 78.0}) is True
    assert bs.degisti_mi({"long": True, "sz": 1.0, "tetik": 78.0}, {"long": False, "sz": 1.0, "tetik": 78.0}) is True


def test_yurutucu_stop_koy_yuvarlama_ve_iptal():
    sim = BorsaSim()
    y = yu.GercekYurutucu(sim, sim.post, RULES)
    oid, neden, tetik = y.stop_koy("BTC", True, 0.123456789, 78.123456, bs.stop_cloid())
    e = sim.acik[0]
    assert oid == e["oid"] and neden == "" and e["side"] == "A" and e["reduceOnly"] is True
    assert e["sz"] == pytest.approx(0.12345) and tetik == pytest.approx(78.1) and e["triggerPx"] == tetik and bs.bizim_mi(e["cloid"])   # sz aşağı; tetik long'da aşağı (BTC szDecimals 5 → 1 ondalık)
    oid2, _, t2 = y.stop_koy("BTC", False, 0.1, 121.00001, bs.stop_cloid())
    assert sim.acik[1]["side"] == "B" and t2 == pytest.approx(121.1)                                                                      # short: tetik yukarı
    assert y.stop_iptal("BTC", oid) is True and y.stop_iptal("BTC", oid) is False and len(sim.acik) == 1


def test_motor_gercek_stop_kurar_buyuyunce_yeniler_kapaninca_iptal(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}                                       # trader pozisyonu (senkron kapatmasın)
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))           # 0,27273 BTC
    m.dakika()
    assert len(sim.acik) == 1 and sim.acik[0]["side"] == "A" and sim.acik[0]["sz"] == pytest.approx(0.27273)
    assert sim.acik[0]["triggerPx"] == pytest.approx(m.hesap.poz[adr(1)]["BTC"].giris * 0.78, abs=0.1)
    ilk = sim.acik[0]["oid"]
    sim.trader_poz[adr(1)] = {"BTC": 600.0}
    m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 300.0, saat))         # artırma
    saat.ms += 60_000
    m.dakika()
    assert len(sim.acik) == 1 and sim.acik[0]["oid"] != ilk and sim.acik[0]["sz"] > 0.27273      # yeni konuldu, eski iptal
    sim.trader_poz[adr(1)] = {}
    m.olay_isle(olay("a:3", adr(1), "BTC", "A", 600, 100.0, 600.0, saat))         # tam kapanış
    saat.ms += 60_000
    m.dakika()
    assert sim.acik == [] and kayitlar(tmp_path, "borsa_stop_iptal")[-1]["neden"] == "pozisyon_yok"
    m.durum_yaz()
    assert (tmp_path / "durum" / "borsa_stop.json").exists()


def test_motor_gercek_stop_tetiklenince_defter_temizlenir_alarm(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dakika()
    sim.stop_tetikle("BTC")                                                        # borsa stopu tetiklendi: borsada pozisyon 0
    saat.ms += 60_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9) and kayitlar(tmp_path, "borsa_stop_kayip")[0]["yerel_acik"] is True
    assert kayitlar(tmp_path, "harici_kapanis") and any("borsa stopu tetiklendi" in x for x in tgp.gonderilen) and sim.acik == []


def test_motor_gercek_ilk_esitlemede_yetim_stop_iptal_ve_y5_bizim_sayar(tmp_path, monkeypatch):
    sim = BorsaSim()
    sim.acik.append({"coin": "ETH", "oid": 77, "cloid": bs.stop_cloid(), "side": "A", "sz": 1.0, "triggerPx": 1500.0, "reduceOnly": True})
    mt.yabanci_emir_denetle(sim.post, HLADR, tmp_path / "niyet.jsonl")              # Y-5: bizim önekli stop yabancı sayılmaz (istisna yok)
    sim.acik.append({"coin": "ETH", "oid": 78, "cloid": "0x" + "ab" * 16, "side": "A", "sz": 1.0, "triggerPx": 1500.0, "reduceOnly": True})
    with pytest.raises(mt.KipHatasi):
        mt.yabanci_emir_denetle(sim.post, HLADR, tmp_path / "niyet.jsonl")
    sim.acik.pop()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.dakika()
    assert sim.acik == [] and kayitlar(tmp_path, "borsa_stop_yetim")[0]["oid"] == 77


def test_sanal_kipte_borsa_stopu_yok(tmp_path):
    from tests.test_canli_motor import kur
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dakika()
    assert not any(y["type"] == "openOrders" for y in hl.istekler) and m.borsa_stop.stoplar == {}


def test_k65_stop_2_saat_kurulamazsa_pozisyon_kapanir_yeni_acilis_durur(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    monkeypatch.setattr(m.yurutucu, "stop_koy", lambda *a, **k: (None, "red", None))     # borsa stopu her seferinde reddediyor
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") > 0 and "BTC" in m.borsa_stop.korumasiz and not m.risk.acilis_durdu.get("stop_korumasiz")
    saat.ms += 7200_000 - 60_000                                                    # 1 sa 59 dk: henüz kapatılmaz
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") > 0 and not kayitlar(tmp_path, "borsa_stop_korumasiz_kapat")
    saat.ms += 60_000                                                               # 2 sa doldu
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)
    assert kayitlar(tmp_path, "borsa_stop_korumasiz_kapat")[0]["coin"] == "BTC" and any("stopsuz pozisyon kapatıldı" in x for x in tgp.gonderilen)
    assert m.risk.acilis_izni(adr(1), "ETH", True, saat.ms) == (False, "stop_korumasiz")      # ceza: yeni açılış yok
    saat.ms += 21600_000                                                            # 6 sa sonra ceza kalkar
    m.dakika()
    assert not m.risk.acilis_durdu.get("stop_korumasiz")
    m.durum_yaz()
    assert bs.BorsaStop(__import__("json").loads((tmp_path / "durum" / "borsa_stop.json").read_text())).ceza_ms == m.borsa_stop.ceza_ms


def test_k65_stop_gecikmeli_kurulursa_kapatma_yok(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    asil = m.yurutucu.stop_koy
    monkeypatch.setattr(m.yurutucu, "stop_koy", lambda *a, **k: (None, "red", None))
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dakika()
    saat.ms += 3600_000
    monkeypatch.setattr(m.yurutucu, "stop_koy", asil)                               # 1 saat sonra borsa kabul ediyor
    m.dakika()
    assert m.borsa_stop.korumasiz == {} and "BTC" in m.borsa_stop.stoplar
    saat.ms += 7200_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") > 0 and not kayitlar(tmp_path, "borsa_stop_korumasiz_kapat")
