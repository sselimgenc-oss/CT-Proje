"""K‑41 (ters yönlü kopya pozisyonunda açılış atlanır: `ters_netlesme`) ve #5 (kendi hesabımızın yatırma/çekme kaydı → `hl_ofset` yeniden; `non_funding_ledger` sayfalama)."""
from __future__ import annotations

import json

import pytest

from copytrade import tarama
from copytrade.canli import hesap as hs
from copytrade.canli import motor as mt
from tests.test_canli_motor import adr, kadro, kayitlar, kur, olay, satir
from tests.test_canli_t4b import HLADR, BorsaSim, kur_gercek


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


# ---------------------------------------------------------------------------------------------------------------- K‑41
def test_hesap_ters_yonlu_var_yalniz_baska_traderin_zit_yonu():
    h = hs.Hesap(1000.0)
    assert not h.ters_yonlu_var(adr(2), "BTC", "A")                        # boş hesap
    h.uygula(adr(1), "BTC", "B", 1.0, 100.0, 0.0, 1)                       # adr(1) long
    assert h.ters_yonlu_var(adr(2), "BTC", "A") is True                    # başkası short açmak ister → ters
    assert h.ters_yonlu_var(adr(2), "BTC", "B") is False                   # aynı yön → serbest
    assert h.ters_yonlu_var(adr(1), "BTC", "A") is False                   # kendi pozisyonu ters sayılmaz (kapanış / ters dönüş ayrı yoldan)
    assert h.ters_yonlu_var(adr(2), "ETH", "A") is False                   # başka coin


def _iki_trader(tmp_path):
    k = kadro([satir(1, 1), satir(2, 2)], 0)
    m, hl, saat, _ = kur(tmp_path, kadro_=k)
    k["kosu_ms"] = saat() - 3_600_000
    m.baslat()
    return m, hl, saat


def test_ters_yonlu_acilis_atlanir_sayac_kayit_ve_ozet_altin_ornek(tmp_path):
    """Kasa 1.000, N 11, slot 90,909 $. T1 BTC long açar (30.000 / 100.000 = oran 0,30 → 27,27 $ emir). T2 BTC short açar: ters → emir YOK, neden ters_netlesme.
    T2'nin ETH short'u (farklı coin) serbest. T1 kapatınca (net 0) T2 BTC short açılabilir."""
    m, hl, saat = _iki_trader(tmp_path)
    s1 = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert [(x.eylem, x.karar) for x in s1] == [("ac", "emir")]
    s2 = m.olay_isle(olay("b:1", adr(2), "BTC", "A", 300, 100.0, 0.0, saat))
    assert [(x.eylem, x.karar, x.neden) for x in s2] == [("ac", "atlandi", "ters_netlesme")]
    assert m.hesap.sz(adr(2), "BTC") == 0.0 and m.hesap.sz(adr(1), "BTC") > 0
    assert m.ozet()["ters_netlesme"] == 1 and m.ozet()["neden_say"]["ters_netlesme"] == 1
    yok = [x for x in kayitlar(tmp_path, "emir_yok") if x["neden"] == "ters_netlesme"]
    assert len(yok) == 1 and yok[0]["adres"] == adr(2) and yok[0]["coin"] == "BTC"
    s3 = m.olay_isle(olay("b:2", adr(2), "ETH", "A", 15, 2000.0, 0.0, saat))
    assert s3[0].karar == "emir"
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))                  # T1 tam kapanış
    assert m.hesap.sz(adr(1), "BTC") == 0.0
    s4 = m.olay_isle(olay("b:3", adr(2), "BTC", "A", 300, 100.0, 0.0, saat))
    assert s4[0].karar == "emir" and m.hesap.sz(adr(2), "BTC") < 0


def test_ters_netlesme_sonrasi_atlanan_traderin_kapanisi_net_pozisyonu_buyutmez(tmp_path):
    m, hl, saat = _iki_trader(tmp_path)
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("b:1", adr(2), "BTC", "A", 300, 100.0, 0.0, saat))                    # atlandı
    onceki = m.hesap.sz(adr(1), "BTC")
    m.olay_isle(olay("b:2", adr(2), "BTC", "B", 300, 100.0, -300.0, saat))                 # T2 short'u kapatır; bizde T2 pozisyonu yok
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(onceki) and m.hesap.sz(adr(2), "BTC") == 0.0


def test_karsi_yonde_pozisyon_tutan_traderin_azalt_ve_kapat_islemi_engellenmez(tmp_path):
    """T1 BTC long (kopya var). T2 short açamadı (ters_netlesme). Ayrıca T2 başka coinde (ETH) short tutuyken T1'in ETH long AÇILIŞI atlanır; ama T2'nin kendi ETH azaltma/kapatması çalışır."""
    m, hl, saat = _iki_trader(tmp_path)
    m.olay_isle(olay("b:1", adr(2), "ETH", "A", 30, 2000.0, 0.0, saat))                    # T2 ETH short açtı (K-38: azaltma hedef tabanlı; 11 $ altına inmesin diye 30)
    assert m.hesap.sz(adr(2), "ETH") < 0
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))                    # T1 long BTC
    s = m.olay_isle(olay("b:2", adr(2), "ETH", "B", 10, 2000.0, -30.0, saat))              # T2 azaltır (hedef 20/30 → fark ~18 $ ≥ 11 $)
    assert s[0].eylem == "azalt" and s[0].karar == "emir"
    s = m.olay_isle(olay("b:3", adr(2), "ETH", "B", 20, 2000.0, -20.0, saat))                # T2 kapatır
    assert s[0].eylem == "kapat" and m.hesap.sz(adr(2), "ETH") == 0.0
    assert not [x for x in kayitlar(tmp_path, "emir_yok") if x["neden"] == "ters_netlesme"]


def test_toz_kalintisi_ters_acilisi_bloklamaz(tmp_path):
    """Kopya pozisyon nosyoneli ≤ `canli_kapanis_toz_usd` (1 $) ise toz sayılır; 1,5 $ ise ters_netlesme."""
    h = hs.Hesap(1000.0)
    h.uygula(adr(1), "BTC", "B", 0.009, 100.0, 0.0, 1)                       # 0,9 $
    assert h.ters_yonlu_var(adr(2), "BTC", "A", {"BTC": 100.0}, 1.0) is False
    assert h.ters_yonlu_var(adr(2), "BTC", "A", {"BTC": 100.0}, 0.0) is True
    h.uygula(adr(1), "BTC", "B", 0.006, 100.0, 0.0, 2)                       # 1,5 $
    assert h.ters_yonlu_var(adr(2), "BTC", "A", {"BTC": 100.0}, 1.0) is True
    m, hl, saat = _iki_trader(tmp_path)
    m.hesap.uygula(adr(1), "BTC", "B", 0.009, 100.0, 0.0, 1)
    s = m.olay_isle(olay("b:1", adr(2), "BTC", "A", 300, 100.0, 0.0, saat))
    assert s[0].karar == "emir"                                              # motor, toz eşiğini kurallardan alır


def test_hip3_dex_coin_dizgesi_ayri_coin(tmp_path):
    h = hs.Hesap(1000.0)
    h.uygula(adr(1), "xyz:TSLA", "B", 1.0, 100.0, 0.0, 1)
    assert h.ters_yonlu_var(adr(2), "xyz:TSLA", "A") is True
    assert h.ters_yonlu_var(adr(2), "TSLA", "A") is False and h.ters_yonlu_var(adr(2), "abc:TSLA", "A") is False


def test_pano_atlanan_sinyaller_ters_netlesme_nedenini_gosterir():
    from copytrade.canli import pano
    html = pano._atlanan_html([{"olay": "emir_yok", "neden": "ters_netlesme"}] * 2 + [{"olay": "emir_yok", "neden": "marj_yok"}])
    assert "K‑41" in html and "<b>2</b>" in html


# ---------------------------------------------------------------------------------------------------------------- ledger sayfalama
def _satir(t, usdc=1.0, tur="deposit", h=None):
    return {"time": t, "hash": h or f"0x{t}", "delta": {"type": tur, "usdc": str(usdc)}}


class LedgerSahte:
    """500 satır sınırlı sahte uç: startTime ≤ time (≤ endTime), eskiden yeniye."""
    def __init__(self, satirlar, sayfa=500):
        self.satirlar, self.sayfa, self.istekler = sorted(satirlar, key=lambda s: s["time"]), sayfa, []

    def __call__(self, y):
        self.istekler.append(y)
        uygun = [s for s in self.satirlar if s["time"] >= y["startTime"] and ("endTime" not in y or s["time"] <= y["endTime"])]
        return uygun[: self.sayfa]


def test_ledger_bos():
    f = LedgerSahte([])
    assert tarama.ledger_sayfala(f, "0xabc", 0) == [] and len(f.istekler) == 1


def test_ledger_tam_sayfa_siniri_ve_ayni_ms_kaybolmaz():
    """1.250 satır, sayfa 500: tümü gelir, tekrar yok. 499. ms'de iki satır (sayfa sınırının son ms'si) ikisi de gelir."""
    rows = [_satir(1000 + i, h=f"h{i}") for i in range(1250)]
    rows.append(_satir(1000 + 499, h="ikiz"))
    f = LedgerSahte(rows)
    got = tarama.ledger_sayfala(f, "0xabc", 1000)
    assert len(got) == 1251 and len({(s["time"], s["hash"]) for s in got}) == 1251 and len(f.istekler) == 3


def test_ledger_tam_500_satir_son_bos_sayfayla_biter():
    f = LedgerSahte([_satir(10 + i) for i in range(500)])
    assert len(tarama.ledger_sayfala(f, "0xabc", 0)) == 500 and len(f.istekler) == 2


def test_ledger_tum_sayfa_ayni_ms_ilerler_ve_maks_sayfa_siniri():
    f = LedgerSahte([_satir(5, h=f"h{i}") for i in range(500)] + [_satir(6, h="son")])
    got = tarama.ledger_sayfala(f, "0xabc", 0)
    assert len(got) == 501 and f.istekler[1]["startTime"] == 6
    sonsuz = lambda y: [_satir(y["startTime"] + i, h=f"{y['startTime']}-{i}") for i in range(500)]       # noqa: E731  hiç bitmeyen uç
    assert len(tarama.ledger_sayfala(sonsuz, "0xabc", 0, maks_sayfa=3)) >= 1000


def test_ledger_end_ms_ve_istemci_sarmali():
    f = LedgerSahte([_satir(1), _satir(2), _satir(3)])
    assert [s["time"] for s in tarama.ledger_sayfala(f, "0xabc", 0, end_ms=2)] == [1, 2] and f.istekler[0]["endTime"] == 2
    c = tarama.PublicClient()
    c.info = lambda yuk, weight=20: f(yuk)
    assert len(c.non_funding_ledger("0xabc", 0)) == 3


# ---------------------------------------------------------------------------------------------------------------- #5 ofset
class LedgerSim(BorsaSim):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.ledger: list[dict] = []

    def post(self, y):
        if y["type"] == "userNonFundingLedgerUpdates":
            self.istekler.append(y)
            assert y["user"] == HLADR
            return [s for s in self.ledger if s["time"] >= y["startTime"]]
        return super().post(y)


def test_yatirma_cekme_ofseti_net_kadar_kaydirir_hl_yerel_farki_korunur_altin_ornek(tmp_path, monkeypatch):
    """Yerel 1.000, HL 1.000 → ofset 0. HL 1.012 (birikmiş +12 gerçek fark). 300 $ yatırma → HL 1.312: ofset 300 (= 0 + 300), risk temeli 1.012 (fark 12 KORUNUR, silinmez).
    Aynı satır tekrar işlenmez. 100 $ çekme → HL 1.212: ofset 200, risk temeli yine 1.012."""
    sim = LedgerSim(deger=1000.0)
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.dakika()
    assert m.hl_ofset == pytest.approx(0.0) and m.ledger_son_ms is not None
    sim.deger = 1012.0
    saat.ms += 60_000
    m.dakika()                                                            # boş ledger: ofset aynı
    assert m.hl_ofset == pytest.approx(0.0) and not kayitlar(tmp_path, "ofset_yenilendi") and m.ozsermaye() == pytest.approx(1012.0)
    sim.deger = 1312.0
    sim.ledger.append(_satir(saat.ms + 59_000, 300.0, "deposit"))
    saat.ms += 60_000
    m.dakika()
    assert m.hl_ofset == pytest.approx(300.0) and m.ozsermaye() == pytest.approx(1012.0) and m.yerel_ozsermaye() == pytest.approx(1000.0)
    ev = kayitlar(tmp_path, "ofset_yenilendi")
    assert len(ev) == 1 and ev[0]["eski"] == pytest.approx(0.0) and ev[0]["yeni"] == pytest.approx(300.0) and ev[0]["net_usd"] == pytest.approx(300.0)
    saat.ms += 60_000
    m.dakika()
    assert len(kayitlar(tmp_path, "ofset_yenilendi")) == 1 and m.hl_ofset == pytest.approx(300.0)       # aynı satır tekrar işlenmez
    sim.deger = 1212.0
    sim.ledger.append(_satir(saat.ms + 59_000, 100.0, "withdraw"))
    saat.ms += 60_000
    m.dakika()
    assert m.hl_ofset == pytest.approx(200.0) and m.ozsermaye() == pytest.approx(1012.0)


def test_ledger_son_ms_ve_ofset_motor_jsonda_kalici_yeniden_baslatmada_yuklenir(tmp_path, monkeypatch):
    sim = LedgerSim(deger=1000.0)
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.dakika()
    sim.deger = 1500.0
    sim.ledger.append(_satir(saat.ms + 59_000, 500.0, "deposit"))
    saat.ms += 60_000
    m.dakika()
    motor = json.loads((tmp_path / "durum" / "motor.json").read_text(encoding="utf-8"))
    assert motor["hl_ofset"] == pytest.approx(500.0) and motor["ledger_son_ms"] == m.ledger_son_ms and m.ledger_son_ms is not None
    m2, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    assert m2.hl_ofset == pytest.approx(500.0) and m2.ledger_son_ms == m.ledger_son_ms


def test_ofset_yalniz_hl_degerinden_once_gerceklesen_satirlari_isler_diger_turler_sayilmaz_ama_kaydedilir(tmp_path, monkeypatch):
    sim = LedgerSim(deger=1000.0)
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.dakika()
    saat.ms += 60_000
    m.dakika()
    son = m.ledger_son_ms
    diger = [_satir(son + 5, 10.0, "internalTransfer"), _satir(son + 6, 10.0, "send"), _satir(son + 7, 10.0, "subAccountTransfer")]
    assert m.ofset_yenile(diger, saat()) is False and m.hl_ofset == pytest.approx(0.0)
    assert kayitlar(tmp_path, "ofset_atlanan_tur")[-1]["turler"] == {"internalTransfer": 1, "send": 1, "subAccountTransfer": 1}
    assert m.ofset_yenile([_satir(m.hl_oz_ms + 1000, 50.0, "deposit")], saat()) is False            # HL değeri okunduktan SONRA: sonraki okumaya kalır
    assert m.hl_ofset == pytest.approx(0.0)


def test_sanal_kipte_ofset_ve_ledger_yok(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.dakika()
    assert m.hl_ofset is None and m.ledger_son_ms is None and not any(i["type"] == "userNonFundingLedgerUpdates" for i in hl.istekler)
