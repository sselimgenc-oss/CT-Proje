"""Denetim 2026-11-17 ADIM 6: O8 (dolum yanıtı ayrıştırma hatası = belirsiz), O5 (gerçek kipte mark bayatlığı), O3 (stop cloid kalıcı + orderStatus + her turda yetim taraması),
O9 (gerçek ücret sorgusu emir kilidi DIŞINDA; defter/K-Z özdeşliği)."""
import json

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import yurutucu as yu
from copytrade.canli.hesap import Hesap
from tests.test_canli_g7 import G7Sim
from tests.test_canli_motor import adr, kayitlar, olay
from tests.test_canli_t4b import BorsaSim, kur_gercek
from tests.test_canli_yurutucu import SahteExchange, meta_post


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


# ------------------------------------------------------------------ O8
def test_o8_yurutucu_dolum_yaniti_bozuksa_belirsiz_ham_ozet_ile():
    """Eski hata: totalSz 'abc' → float() ValueError yurutucudan SIZARDI (niyet açık, belirsiz bayrağı yok). Şimdi durum belirsiz + ham yanıt özeti."""
    bozuk = {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {"totalSz": "abc", "avgPx": "100", "oid": 1}}]}}}
    d = yu.GercekYurutucu(SahteExchange(bozuk), meta_post, {**yu.load_rules()}).emir("BTC", "B", 11.0)
    assert d.durum == "belirsiz" and d.neden.startswith("yanit_ayrisma") and d.sz == 0 and d.px is None and d.ucret == 0
    assert "abc" in d.ham["yanit"] and len(d.ham["yanit"]) <= 300
    eksik = {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {"avgPx": "100"}}]}}}
    assert yu.GercekYurutucu(SahteExchange(eksik), meta_post, {**yu.load_rules()}).emir("BTC", "B", 11.0).durum == "belirsiz"


class BozukYanitSim(BorsaSim):
    """Emir borsada DOLAR ama yanıt ayrıştırılamaz."""

    def order(self, coin, is_buy, sz, px, tif, reduce_only, cloid=None):
        yanit = super().order(coin, is_buy, sz, px, tif, reduce_only, cloid)
        if not (isinstance(tif, dict) and "trigger" in tif):
            yanit["response"]["data"]["statuses"][0]["filled"]["totalSz"] = "yarim"
        return yanit


def test_o8_motor_belirsiz_bayragi_orderstatus_ile_cozulur_defter_dolar(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BozukYanitSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert s[0].karar == "belirsiz" and sim.poz["BTC"] == pytest.approx(0.27272, abs=1e-5)         # borsada doldu, defterde yok
    (cloid,) = list(m.hesap.belirsiz)
    assert m.risk.acilis_durdu.get("belirsiz") is True and [x["cloid"] for x in m.niyet.sonucsuz()] == [cloid]      # niyet açık, "red" sayılmadı
    assert "yarim" in kayitlar(tmp_path, "emir")[-1]["ham"]
    sim.durumlar[cloid] = {"status": "order", "order": {"order": {"coin": "BTC", "side": "B", "limitPx": "100.5", "sz": "0.0", "origSz": "0.27272", "oid": 7}, "status": "filled"}}
    saat.ms += 60_000
    m.dakika()
    assert not m.hesap.belirsiz and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.27272, abs=1e-9)


# ------------------------------------------------------------------ O5
class MidSim(BorsaSim):
    mids_hata = False

    def post(self, y):
        if y["type"] == "allMids" and self.mids_hata:
            raise OSError("mids yok")
        return super().post(y)


def _acik_poz(tmp_path, monkeypatch):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, MidSim())
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    saat.ms += 60_000
    m.dakika()
    return m, sim, saat, tgp


def test_o5_eski_mark_mutabakatta_sorun_acilis_durur_taze_gelince_kalkar(tmp_path, monkeypatch):
    m, sim, saat, tgp = _acik_poz(tmp_path, monkeypatch)
    assert m.risk.acilis_durdu.get("mutabakat") is False
    sim.mids_hata = True                                                   # allMids okunamıyor: marklar donar
    for _ in range(6):                                                     # 6 dk > canli_mark_stale_sn (300 sn)
        saat.ms += 60_000
        m.dakika()
    assert m.risk.acilis_durdu.get("mutabakat") is True
    assert any(e["sorunlar"][0].get("neden") == "mark_eski" for e in kayitlar(tmp_path, "mutabakat_alarm"))
    sim.mids_hata = False
    saat.ms += 60_000
    m.dakika()
    assert m.risk.acilis_durdu.get("mutabakat") is False


def test_o5_eski_markla_acilis_atlanir_kapanis_serbest(tmp_path, monkeypatch):
    m, sim, saat, tgp = _acik_poz(tmp_path, monkeypatch)
    sim.mids_hata = True
    saat.ms += 400_000                                                     # mark 400 sn eski
    sim.trader_poz[adr(1)] = {"BTC": 600.0, "ETH": 100.0}
    s = m.olay_isle(olay("a:2", adr(1), "ETH", "B", 100, 2000.0, 0.0, saat))
    assert [(x.karar, x.neden) for x in s] == [("engel", "mark_eski")] and not sim.poz.get("ETH")
    kap = m.olay_isle(olay("a:3", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert kap[0].karar == "emir" and sim.poz["BTC"] == pytest.approx(0.0, abs=1e-9)            # kapanış serbest


# ------------------------------------------------------------------ O3
class StopSim(BorsaSim):
    """Stop emri HL'ye ULAŞIR ama istemci yanıtı alamaz (zaman aşımı). `durum_hata`: orderStatus de çözülemez. `gonderim`: stop gönderilirken çağrılır."""
    stop_zaman_asimi = 0
    durum_hata = False
    gonderim = None

    def order(self, coin, is_buy, sz, px, tif, reduce_only, cloid=None):
        yanit = super().order(coin, is_buy, sz, px, tif, reduce_only, cloid)
        if isinstance(tif, dict) and "trigger" in tif:
            if self.gonderim:
                self.gonderim()
            if self.stop_zaman_asimi > 0:
                self.stop_zaman_asimi -= 1
                raise TimeoutError("yanit yok")
        return yanit

    def post(self, y):
        if y["type"] == "orderStatus" and any(str(e["cloid"]).lower() == str(y["oid"]).lower() for e in self.acik):
            if self.durum_hata:
                raise OSError("orderStatus yok")
            e = next(e for e in self.acik if str(e["cloid"]).lower() == str(y["oid"]).lower())
            return {"status": "order", "order": {"order": {"coin": e["coin"], "oid": e["oid"], "sz": str(e["sz"])}, "status": "open"}}
        return super().post(y)


def _stopsim(tmp_path, monkeypatch, sim):
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    return m, sim, saat, tgp


def test_o3_stop_yaniti_kaybolursa_orderstatus_ile_bulunur_stoplar_yiginlanmaz(tmp_path, monkeypatch):
    """Eski hata: sdk_hatasi → oid yok → her dakika yeni (rastgele cloid'li) stop: 3 dakikada 3 stop. Şimdi orderStatus(cloid) ile mevcut stop benimsenir."""
    sim = StopSim()
    sim.stop_zaman_asimi = 1
    m, sim, saat, tgp = _stopsim(tmp_path, monkeypatch, sim)
    for _ in range(3):
        saat.ms += 60_000
        m.dakika()
    assert len(sim.acik) == 1 and m.borsa_stop.stoplar["BTC"]["oid"] == sim.acik[0]["oid"] and not m.borsa_stop.bekleyen
    assert kayitlar(tmp_path, "borsa_stop_konan_belirsiz")


def test_o3_orderstatus_de_calismazsa_sonraki_turda_acik_emirlerden_benimsenir(tmp_path, monkeypatch):
    sim = StopSim()
    sim.stop_zaman_asimi, sim.durum_hata = 1, True
    m, sim, saat, tgp = _stopsim(tmp_path, monkeypatch, sim)
    saat.ms += 60_000
    m.dakika()
    assert len(sim.acik) == 1 and "BTC" not in m.borsa_stop.stoplar and "BTC" in m.borsa_stop.bekleyen       # sonuç bilinmiyor: bekleyen cloid kayıtlı
    cloid = m.borsa_stop.bekleyen["BTC"]["cloid"]
    saat.ms += 60_000
    m.dakika()                                                                                                   # sonraki tur: bekleyen cloid openOrders'ta bulunur
    assert len(sim.acik) == 1 and m.borsa_stop.stoplar["BTC"]["cloid"] == cloid and not m.borsa_stop.bekleyen


def test_o3_cloid_gonderimden_once_diske_yazilir(tmp_path, monkeypatch):
    gorulen = {}
    sim = StopSim()

    def kanca():
        gorulen["bekleyen"] = json.loads((tmp_path / "durum" / "borsa_stop.json").read_text())["bekleyen"]
    sim.gonderim = kanca
    m, sim, saat, tgp = _stopsim(tmp_path, monkeypatch, sim)
    saat.ms += 60_000
    m.dakika()
    assert list(gorulen["bekleyen"]) == ["BTC"] and gorulen["bekleyen"]["BTC"]["cloid"].lower() == sim.acik[0]["cloid"].lower()      # gönderim anında dosyada
    assert json.loads((tmp_path / "durum" / "borsa_stop.json").read_text())["bekleyen"] == {}                                             # kuruldu: bekleyen temiz


def test_o3_yetim_taramasi_her_turda_bizim_onekli_bilinmeyen_stop_iptal(tmp_path, monkeypatch):
    m, sim, saat, tgp = _stopsim(tmp_path, monkeypatch, StopSim())
    for _ in range(2):
        saat.ms += 60_000
        m.dakika()
    assert len(sim.acik) == 1
    sim.acik.append({"coin": "BTC", "oid": 555, "cloid": "0x5354" + "ab" * 14, "side": "A", "sz": 0.1, "triggerPx": "70", "reduceOnly": True})   # üçüncü turda ortaya çıkan eski/yabancı bizim önekli stop
    saat.ms += 60_000
    m.dakika()
    assert [e["oid"] for e in sim.acik] == [m.borsa_stop.stoplar["BTC"]["oid"]] and kayitlar(tmp_path, "borsa_stop_yetim")[-1]["oid"] == 555


def test_o3_stop_durum_savunmaci_bilinmeyen_bicimde_none():
    post = lambda y: {"beklenmedik": 1}      # noqa: E731
    assert yu.GercekYurutucu(SahteExchange(), post, {**yu.load_rules()}).stop_durum("0x5354aa") is None
    post2 = lambda y: {"status": "order", "order": {"status": "filled", "order": {"oid": 3}}}      # noqa: E731
    assert yu.GercekYurutucu(SahteExchange(), post2, {**yu.load_rules()}).stop_durum("0x5354aa") is None
    post3 = lambda y: {"status": "order", "order": {"status": "open", "order": {"oid": 3}}}      # noqa: E731
    assert yu.GercekYurutucu(SahteExchange(), post3, {**yu.load_rules()}).stop_durum("0x5354aa") == 3


# ------------------------------------------------------------------ O9
class KilitSim(G7Sim):
    """userFillsByTime çağrısı anında motor kilidinin tutulup tutulmadığını kaydeder."""
    motor = None
    kilitli: list = []

    def post(self, y):
        if y["type"] == "userFillsByTime":
            self.kilitli.append(self.motor._lock._is_owned())
        return super().post(y)


def test_o9_gercek_ucret_sorgusu_kilit_disinda_defter_ve_ozsermaye_ozdesligi_altin_ornek(tmp_path, monkeypatch):
    """300 BTC açılışı: 0,27272 BTC × 100 = 27,273 $. Tahmin ücret 27,273 × 0,00045 = 0,01227285; HL fee 0,012. Emir sırasında userFillsByTime YOK (kilit içinde ağ yok);
    düzeltme dakikalık bakımda kilit dışı okumayla: ücret 0,012, özsermaye 1000 − 0,012 (Δ = −0,00027285 kadar artar), realize değişmez."""
    sim = KilitSim()
    sim.kilitli = []
    sim.fills = [{"coin": "BTC", "oid": 1, "fee": "0.012", "sz": "0.27272", "px": "100.0"}]
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    sim.motor = m
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.baslat()
    n0 = len([x for x in sim.istekler if x["type"] == "userFillsByTime"])
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert len([x for x in sim.istekler if x["type"] == "userFillsByTime"]) == n0                        # emir yolunda sorgu yok
    oz0, marks = m.hesap.ozsermaye(m.marks), m.marks
    assert oz0 == pytest.approx(1000.0 - 0.0122724, abs=1e-9) and len(m.ucret_bekleyen) == 1
    kayitli = json.loads((tmp_path / "durum" / "motor.json").read_text())["ucret_bekleyen"]
    assert kayitli and kayitli[0]["tahmin"] == pytest.approx(0.0122724)                                  # bekleyen düzeltme kalıcı
    realize0, slot0 = dict(m.hesap.realize), m.hesap.slot_ozsermaye(adr(1), marks)
    saat.ms += 60_000
    m.dakika()
    assert sim.kilitli and not any(sim.kilitli)                                                          # sorgu kilit DIŞINDA
    assert m.hesap.ucret[adr(1)] == pytest.approx(0.012, abs=1e-12) and m.hesap.realize == realize0
    assert m.hesap.ozsermaye(m.marks) == pytest.approx(1000.0 - 0.012, abs=1e-9) and m.hesap.ozsermaye(m.marks) - oz0 == pytest.approx(0.0122724 - 0.012, abs=1e-9)
    assert m.hesap.slot_ozsermaye(adr(1), m.marks) - slot0 == pytest.approx(0.0122724 - 0.012, abs=1e-9)
    assert not m.ucret_bekleyen and m.ucret_gercek_usd == pytest.approx(0.012) and m.ucret_tahmin_say == 0
    d = kayitlar(tmp_path, "ucret_duzeltildi")[0]
    assert d["gercek"] == pytest.approx(0.012) and d["tahmin"] == pytest.approx(0.0122724)


def test_o9_fee_bulunamazsa_tahmin_kalir_bekleyen_30dk_sonra_duser(tmp_path, monkeypatch):
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, G7Sim())
    sim.trader_poz[adr(1)] = {"BTC": 300.0}
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    saat.ms += 60_000
    m.dakika()
    assert len(m.ucret_bekleyen) == 1 and m.hesap.ucret[adr(1)] == pytest.approx(0.0122724)             # eşleşme yok: tahmin, tekrar denenir
    saat.ms += 1_800_000
    m.dakika()
    assert not m.ucret_bekleyen and m.ucret_tahmin_say == 1 and kayitlar(tmp_path, "ucret_duzeltme_vazgec")


def test_o9_hesap_ucret_duzelt_kapanmis_slotta_ozdeslik_korunur():
    h = Hesap(1000.0)
    h.slot_ac("a", 100.0)
    h.uygula("a", "BTC", "B", 1.0, 100.0, 0.045, 0)
    h.uygula("a", "BTC", "A", 1.0, 110.0, 0.0495, 1)
    h.slot_kapat("a")                                                                 # slot kayıtları silindi; net kapanmis_net'e: 10 − 0,0945
    oz = h.ozsermaye({})
    assert oz == pytest.approx(1000.0 + 10.0 - 0.0945)
    h.ucret_duzelt("a", -0.0095)                                                      # gerçek ücret 0,0095 az çıktı
    assert h.ozsermaye({}) == pytest.approx(oz + 0.0095)


def test_o9_karsilastir_sonradan_duzeltilen_ucreti_kesin_sayar():
    from copytrade.canli import gercek_sanal_karsilastir as gs
    e = {"olay": "emir", "kip": "gercek", "adres": "0xtr", "eylem": "ac", "reduce_only": False, "bant": 0.005, "red_neden": "", "coin": "BTC", "yon": "B", "usd_istenen": 100.0, "usd_dolan": 100.0,
         "sz": 0.001, "durum": "dolu", "referans_px": 100000.0, "dolum_px": 100000.0, "kayma_ref": 0.0, "ucret": 0.045, "cloid": "0xa", "emir_ms": 1000, "trader_dolum_ms": 900,
         "defter": {"levels": [[{"px": "99990", "sz": "1"}], [{"px": "100000", "sz": "1"}]]}}
    tahmin = {"olay": "ucret_tahmin", "adres": "0xtr", "coin": "BTC", "cloid": "0xa", "ucret": 0.045}
    duz = {"olay": "ucret_duzeltildi", "cloid": "0xa", "adres": "0xtr", "coin": "BTC", "tahmin": 0.045, "gercek": 0.04, "fark": -0.005}
    s0 = gs.karsilastir([e, tahmin], None, n=5, sz_decimals={"BTC": 5})["satirlar"][0]
    s1 = gs.karsilastir([e, tahmin, duz], None, n=5, sz_decimals={"BTC": 5})["satirlar"][0]
    assert s0["gercek_ucret_kesin"] is False and s0["gercek_ucret"] == pytest.approx(0.045)
    assert s1["gercek_ucret_kesin"] is True and s1["gercek_ucret"] == pytest.approx(0.04)
