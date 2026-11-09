"""G7 (B4): GERÇEK kipte funding ve kesin ücret yerel deftere. Ağsız; sahte borsa (`BorsaSim` + `userFunding` / `userFillsByTime`). Sayılar elle hesaplanmıştır.
Birim: $ (HL hesabı = kasa ölçeği); funding işareti: + alınan / − ödenen."""
import json

import pytest

from tests.test_canli_motor import adr, olay
from tests.test_canli_t4b import BorsaSim, _maske_temizle, kur_gercek  # noqa: F401 (autouse fixture)

SAAT_MS = 3_600_000


class G7Sim(BorsaSim):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fills: list[dict] = []
        self.fund: list[dict] = []

    def post(self, y):
        if y["type"] == "userFillsByTime":
            self.istekler.append(y)
            return self.fills
        if y["type"] == "userFunding":
            self.istekler.append(y)
            return self.fund
        return super().post(y)


def fund_satir(t, coin, usdc):
    return {"time": t, "hash": "0x0", "delta": {"type": "funding", "coin": coin, "usdc": str(usdc), "szi": "0.27273", "fundingRate": "0.0001"}}


def fark(m, sim):
    return abs((sim.deger - m.hl_ofset) - m.yerel_ozsermaye())


def ac(tmp_path, monkeypatch, fee=None):
    sim = G7Sim()
    if fee is not None:
        sim.fills = [{"coin": "BTC", "oid": 1, "fee": str(fee), "sz": "0.27273", "px": "100.0"}]
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    sim.trader_poz[adr(1)] = {"BTC": 300.0}                                   # trader pozisyonu açık kalır: senkron kapanışı tetiklenmez
    m.baslat()
    return m, sim, saat


def test_gercek_ucret_tahmin_yerine_yazilir_altin_ornek(tmp_path, monkeypatch):
    """300 BTC açılışı (hesap 100.000 $ → oran 0,3 → 27,273 $ = 0,27273 BTC × 100). Tahmin: 27,273 × 0,00045 = 0,01227285; HL gerçek fee 0,012 $ → defterde 0,012."""
    m, sim, saat = ac(tmp_path, monkeypatch, fee=0.012)
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.ucret[adr(1)] == pytest.approx(0.012, abs=1e-12) and m.hesap.ucret[adr(1)] != pytest.approx(0.01227285, abs=1e-9)
    assert m.ucret_gercek_usd == pytest.approx(0.012) and m.ucret_tahmin_say == 0
    z = m.ozet()
    assert z["ucret_gercek_usd"] == pytest.approx(0.012) and z["ucret_tahmin_say"] == 0 and z["funding_gercek_usd"] == 0.0


def test_gercek_ucret_yoksa_tahmine_duser_ucret_tahmin_kaydi(tmp_path, monkeypatch):
    m, sim, saat = ac(tmp_path, monkeypatch, fee=None)
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.ucret[adr(1)] == pytest.approx(0.27273 * 100 * 0.00045, rel=1e-6)
    assert m.ucret_tahmin_say == 1 and m.ucret_gercek_usd == 0.0
    from tests.test_canli_motor import kayitlar
    assert len(kayitlar(tmp_path, "ucret_tahmin")) == 1


def test_baska_emrin_fee_satiri_eslesmez(tmp_path, monkeypatch):
    sim = G7Sim()
    sim.fills = [{"coin": "BTC", "oid": 99, "fee": "5", "cloid": "0xdead"}, {"coin": "ETH", "oid": 1, "fee": "5"}]
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.ucret_tahmin_say == 1 and m.hesap.ucret[adr(1)] < 0.1


def test_funding_uc_odeme_toplam_eksi_004_idempotent_ve_mutabakat_kapanir(tmp_path, monkeypatch):
    """3 saatlik ödeme −0,05 +0,02 −0,01 = −0,04 $; aynı satırlar tekrar dönerse çift sayılmaz; HL değeri −0,04 düşer, yerel defter funding'i işleyince mutabakat farkı 0."""
    m, sim, saat = ac(tmp_path, monkeypatch, fee=0.012)
    saat.ms += 60_000
    m.dakika()                                                                  # işaretçi sabitlenir (geçmiş okunmaz)
    t0 = m.son_funding_ms
    assert t0 == saat.ms and not [i for i in sim.istekler if i["type"] == "userFunding"]
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    saat.ms += 3 * SAAT_MS + 1000
    sim.fund = [fund_satir(t0 + SAAT_MS, "BTC", -0.05), fund_satir(t0 + 2 * SAAT_MS, "BTC", 0.02), fund_satir(t0 + 3 * SAAT_MS, "BTC", -0.01)]
    sim.deger = 1000.0 - 0.012 - 0.04                                           # HL: gerçek fee + funding düştü
    m.dakika()
    assert m.hesap.funding_toplam() == pytest.approx(-0.04, abs=1e-12) and m.funding_gercek_usd == pytest.approx(-0.04, abs=1e-12)
    assert m.hesap.funding[adr(1)] == pytest.approx(-0.04, abs=1e-12) and m.son_funding_ms == t0 + 3 * SAAT_MS
    assert fark(m, sim) < 0.01 and not m.risk.acilis_durdu.get("mutabakat")
    assert m.ozet()["funding_gercek_usd"] == pytest.approx(-0.04)
    saat.ms += SAAT_MS                                                          # aynı satırlar yine döner (sunucu startTime'ı yok sayarsa bile)
    m.dakika()
    assert m.hesap.funding_toplam() == pytest.approx(-0.04, abs=1e-12) and m.funding_gercek_usd == pytest.approx(-0.04, abs=1e-12)


def test_funding_islenmezse_fark_birikir_islenince_kapanir_onceki_sonraki(tmp_path, monkeypatch):
    m, sim, saat = ac(tmp_path, monkeypatch, fee=0.012)
    saat.ms += 60_000
    m.dakika()
    t0 = m.son_funding_ms
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    sim.deger = 1000.0 - 0.012 - 0.04
    assert fark(m, sim) == pytest.approx(0.04, abs=1e-9)                       # önce: funding toplamı kadar kayma
    m.funding_gercek_uygula([fund_satir(t0 + 1, "BTC", -0.04)], saat.ms)
    assert fark(m, sim) == pytest.approx(0.0, abs=1e-9)                        # sonra


def test_funding_iki_trader_ayni_coin_sz_payi_ve_pozisyonsuz_coin_kapanmis_nete(tmp_path, monkeypatch):
    """0,3 ve 0,1 BTC, HL funding −1,20 $ → −0,90 / −0,30 $. Yerelde ETH pozisyonu yok: +0,05 $ kapanmis_net'e."""
    m, sim, saat = ac(tmp_path, monkeypatch)
    m.son_funding_ms = 1000
    for a, sz in ((adr(1), 0.3), (adr(2), 0.1)):
        m.hesap.slot_ac(a, 100.0)
        m.hesap.uygula(a, "BTC", "B", sz, 100.0, 0.0, 0)
    m.funding_gercek_uygula([fund_satir(2000, "BTC", -1.20), fund_satir(2000, "ETH", 0.05)], 5000)
    assert m.hesap.funding[adr(1)] == pytest.approx(-0.90) and m.hesap.funding[adr(2)] == pytest.approx(-0.30)
    assert m.hesap.kapanmis_net == pytest.approx(0.05) and m.funding_gercek_usd == pytest.approx(-1.15)


def test_eski_motor_json_alan_yok_guvenli_baslangic_gecmis_funding_okunmaz(tmp_path, monkeypatch):
    m, sim, saat = ac(tmp_path, monkeypatch)
    assert m.son_funding_ms is None and m.funding_gercek_usd == 0.0 and m.ucret_tahmin_say == 0
    sim.fund = [fund_satir(saat.ms - 10 * SAAT_MS, "BTC", -9.0)]               # geçmiş funding
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    saat.ms += 60_000
    m.dakika()
    assert m.son_funding_ms == saat.ms and m.funding_gercek_usd == 0.0 and m.hesap.funding_toplam() == 0.0
    saat.ms += SAAT_MS
    m.dakika()                                                                  # geçmiş satır startTime'dan eski; sunucu yine döndürse bile z < işaretçi → yok sayılır
    assert m.funding_gercek_usd == 0.0 and m.hesap.funding_toplam() == 0.0


def test_motor_json_kalicilik_yeniden_baslatmada_isaretci_ve_sayaclar(tmp_path, monkeypatch):
    m, sim, saat = ac(tmp_path, monkeypatch, fee=0.012)
    saat.ms += 60_000
    m.dakika()
    t0 = m.son_funding_ms
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    saat.ms += SAAT_MS + 1000
    sim.fund = [fund_satir(t0 + 1000, "BTC", -0.03)]
    m.dakika()
    d = json.loads((tmp_path / "durum" / "motor.json").read_text(encoding="utf-8"))
    assert d["son_funding_ms"] == t0 + 1000 and d["funding_gercek_usd"] == pytest.approx(-0.03) and d["ucret_gercek_usd"] == pytest.approx(0.012) and d["ucret_tahmin_say"] == 0
    assert d["funding_kimlik"] == [f"{t0 + 1000}:BTC"]
    m2, sim2, saat2, _ = kur_gercek(tmp_path, monkeypatch, G7Sim())
    assert m2.son_funding_ms == t0 + 1000 and m2.funding_gercek_usd == pytest.approx(-0.03) and m2.ucret_gercek_usd == pytest.approx(0.012) and m2.funding_kimlik == [f"{t0 + 1000}:BTC"]
    m2.funding_gercek_uygula([fund_satir(t0 + 1000, "BTC", -0.03)], saat.ms)    # yeniden başlatma sonrası aynı satır çift sayılmaz
    assert m2.funding_gercek_usd == pytest.approx(-0.03)


def test_funding_sayfa_siniri_500_satir_ikinci_sayfa(tmp_path, monkeypatch):
    m, sim, saat = ac(tmp_path, monkeypatch)
    m.son_funding_ms = 1000
    sayfa1 = [fund_satir(2000 + i, "BTC", -0.001) for i in range(500)]
    sayfa2 = [fund_satir(2499, "BTC", -0.001), fund_satir(3000, "BTC", -0.002)]       # son satır sayfa 2'de tekrar (aynı time:coin) + 1 yeni
    sayfalar = iter([sayfa1, sayfa2])
    istekler = []
    m.post = lambda y: (istekler.append(y), next(sayfalar))[1]
    s = m.funding_gercek_oku(saat.ms)
    assert len(s) == 501 and [i["startTime"] for i in istekler] == [1001, 2499]


def test_funding_okuma_hatasinda_isaretci_ilerlemez(tmp_path, monkeypatch):
    m, sim, saat = ac(tmp_path, monkeypatch)
    m.son_funding_ms = 1000

    def kotu(y):
        raise OSError("ag")
    m.post = kotu
    assert m.funding_gercek_oku(saat.ms) is None and m.son_funding_ms == 1000
    assert m._son.get("funding_gercek", 0) == 0                                   # sonraki dakika yeniden dener


def test_sanal_kip_etkilenmez(tmp_path):
    from tests.test_canli_motor import kur
    m = kur(tmp_path)[0] if isinstance(kur(tmp_path), tuple) else kur(tmp_path)
    assert m.kip == "sanal" and m.funding_gercek_oku(10**13) is None and m.funding_gercek_uygula([fund_satir(1, "BTC", -1)], 0) == 0.0
    assert m.ozet()["funding_gercek_usd"] == 0.0 and m.ozet()["ucret_tahmin_say"] == 0
