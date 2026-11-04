"""T4b (K‑37) motor sağlamlaştırma testleri: kapanış teyidi, niyet + cloid, gerçek özsermaye / sanal funding, gecikmiş açılış, öncelikli kuyruk, Telegram, vardiya boşluğu, sanal derinlik,
herkese açık veri. Ağsız; gerçek kip YALNIZ sahte borsa (`BorsaSim`) ile sınanır, ÇALIŞTIRILMAZ. Sayılar elle hesaplanmıştır."""
import asyncio
import hashlib
import json
import time

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import niyet as ny
from copytrade.canli import telegram as tg
from copytrade.canli import yurutucu as yu
from copytrade.kurallar import load_rules
from tests.test_canli_motor import CHAT, GUN, SAAT, TOKEN, SahteHL, SahteTG, Saat, T0, adr, kadro, kayitlar, kur, olay, satir, tg_mesaj

RULES = load_rules()
HLADR = "0x" + "ab" * 20                       # kendi HL hesap adresimiz (gizli kalmalı)


class BorsaSim:
    """Sahte HL: info (`post`) + SDK `exchange` (update_leverage / order) AYNI durumu paylaşır. `doluluk`: her `order` çağrısında dolan oran (son değer tekrarlanır)."""

    def __init__(self, deger=1000.0, doluluk=(1.0,), trader_hesap=100_000.0):
        self.poz: dict[str, float] = {}
        self.siparisler: list[dict] = []
        self.doluluk, self.deger, self.trader_hesap = list(doluluk), deger, trader_hesap
        self.trader_poz: dict[str, dict[str, float]] = {}
        self.durumlar: dict[str, dict] = {}
        self.istekler: list[dict] = []
        self.funding = {"BTC": "0.0001", "ETH": "-0.00005"}

    def post(self, y):
        self.istekler.append(y)
        t = y["type"]
        if t == "allMids":
            return {"BTC": "100", "ETH": "2000"}
        if t == "l2Book":
            return {"levels": [[{"px": "99.9", "sz": "1000"}], [{"px": "100", "sz": "1000"}]]} if y["coin"] == "BTC" else {"levels": [[{"px": "1999", "sz": "1000"}], [{"px": "2000", "sz": "1000"}]]}
        if t == "clearinghouseState":
            if y["user"] == HLADR:
                return {"marginSummary": {"accountValue": str(self.deger)}, "assetPositions": [{"position": {"coin": c, "szi": str(v)}} for c, v in self.poz.items() if v]}
            return {"marginSummary": {"accountValue": str(self.trader_hesap)}, "assetPositions": [{"position": {"coin": c, "szi": str(v)}} for c, v in self.trader_poz.get(y["user"], {}).items()]}
        if t == "spotClearinghouseState":
            return {"balances": [{"coin": "USDC", "total": "0"}]}
        if t == "meta":
            return {"universe": [{"name": "BTC", "szDecimals": 5}, {"name": "ETH", "szDecimals": 4}]}
        if t == "perpDexs":
            return [None]
        if t == "userFillsByTime":
            return []
        if t == "metaAndAssetCtxs":
            return [{"universe": [{"name": c} for c in self.funding]}, [{"funding": v} for v in self.funding.values()]]
        if t == "orderStatus":
            return self.durumlar.get(y["oid"], {"status": "unknownOid"})
        raise AssertionError(y)

    def update_leverage(self, lev, coin, is_cross):
        return {"status": "ok"}

    def order(self, coin, is_buy, sz, px, tif, reduce_only, cloid=None):
        oran = self.doluluk.pop(0) if len(self.doluluk) > 1 else self.doluluk[0]
        dolan = round(sz * oran, 5)
        self.siparisler.append({"coin": coin, "is_buy": is_buy, "sz": sz, "px": px, "reduce_only": reduce_only, "cloid": cloid, "dolan": dolan})
        if dolan <= 0:
            return {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"error": "Order could not immediately match"}]}}}
        self.poz[coin] = round(self.poz.get(coin, 0.0) + (dolan if is_buy else -dolan), 5)
        return {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {"totalSz": str(dolan), "avgPx": str(100.0 if coin == "BTC" else 2000.0), "oid": 1}}]}}}


def kur_gercek(tmp_path, monkeypatch, sim, kasa=1000.0, tgp=None, saat=None):
    monkeypatch.setenv("HL_HESAP_ADRESI", HLADR)
    rules = {**RULES, "canli_kasa_usd": kasa}
    saat = saat or Saat()
    tgp = tgp or SahteTG()
    k = kadro([satir(1, 1)], saat() - SAAT)
    sim.trader_poz[adr(1)] = {}
    m = mt.Motor(rules, yu.GercekYurutucu(sim, sim.post, rules), sim.post, tg.Telegram(TOKEN, CHAT, tgp), tmp_path / "durum", tmp_path / "kayit", lambda: k, saat)
    return m, sim, saat, tgp


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


# ================================================================================================ 1. kapanış teyidi
def test_kapanis_kismi_ioc_taze_defterle_yeniden_denenir_bant_merdiveni_ve_borsa_teyidi(tmp_path, monkeypatch):
    """Trader 300 BTC açar (100.000 $ hesap → oran 0,3 → 27,27 $ = 0,27273 BTC; sz 5 hane yuvarlama: 0,27273). Trader tam kapatır: 1. deneme (bant %0,5) %50 dolar → borsada 0,13637 kalır;
    2. deneme (bant %1) kalan 0,13637'yi kapatır → borsa 0 → teyit. İki emir, farklı cloid, bantlar [0,005; 0,01]; defter 0."""
    sim = BorsaSim(doluluk=(1.0, 0.5, 1.0))
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert sim.poz["BTC"] == pytest.approx(0.27273, abs=1e-5) and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.27273, abs=1e-5)
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    kapat = [x for x in sim.siparisler[1:]]
    assert len(kapat) == 2 and all(x["reduce_only"] for x in kapat) and kapat[0]["sz"] == pytest.approx(0.27273, abs=1e-5)
    assert kapat[1]["sz"] == pytest.approx(0.13637, abs=1e-5) and kapat[0]["cloid"] != kapat[1]["cloid"]
    assert sim.poz["BTC"] == pytest.approx(0.0, abs=1e-9) and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9) and not m.kapanis_kuyrugu and s[0].karar == "emir"
    assert [e["bant"] for e in kayitlar(tmp_path, "emir")[1:]] == [0.005, 0.01]


def test_kapanis_hic_dolmayan_5_denemede_kapanis_eksik_alarm_dakika_yeniden_dener(tmp_path, monkeypatch):
    """5 denemenin hepsi dolmaz: bantlar [0,005; 0,01; 0,02; 0,02; 0,02]; `kapanis_eksik` (alarm, sayaç 1), yeni açılış yok (bayrak); sonraki dakika likidite gelince kapanır."""
    sim = BorsaSim(doluluk=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert [e["bant"] for e in kayitlar(tmp_path, "emir")[1:]] == [0.005, 0.01, 0.02, 0.02, 0.02] and len(sim.siparisler) == 6
    assert m.sayac["kapanis_eksik"] == 1 and list(m.kapanis_kuyrugu) == [f"{adr(1)}|BTC"] and any("kapanış EKSİK" in x for x in tgp.gonderilen)
    assert sim.poz["BTC"] > 0 and m.hesap.sz(adr(1), "BTC") > 0
    saat.ms += 60_000
    m.dakika()
    assert m.risk.acilis_durdu["kapanis_eksik"] is False or not m.kapanis_kuyrugu                        # 7. çağrı doldu: kapandı
    assert not m.kapanis_kuyrugu and sim.poz["BTC"] == pytest.approx(0.0, abs=1e-9) and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)
    assert m.ozet()["kapanis_eksik"] == 1 and m.ozet()["min_nosyonel"] == 0


def test_dur_pozisyon_duzlesmezse_motor_durmaz_dur_dosyasi_bekliyor_sonra_tamam(tmp_path, monkeypatch):
    sim = BorsaSim(doluluk=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dur_tetikle("komut")
    d = json.loads((tmp_path / "durum" / "DUR").read_text(encoding="utf-8"))
    assert m.dur_bekliyor and not m.dur_istendi and d["kapanis_bekliyor"] is True and m.risk.dur
    assert any("DÜZLEŞMEDİ" in x for x in tgp.gonderilen)
    ok, izin = m.risk.acilis_izni(adr(1), "BTC", True, saat()), None
    assert ok[0] is False                                                                      # yeni açılış yok
    saat.ms += 60_000
    m.dakika()
    assert m.dur_istendi and not m.dur_bekliyor and json.loads((tmp_path / "durum" / "DUR").read_text(encoding="utf-8"))["kapanis_bekliyor"] is False and sim.poz["BTC"] == pytest.approx(0.0, abs=1e-9)


def test_dur_yarim_kalirsa_yeniden_baslatma_yalniz_kapanis_modunda_baslar(tmp_path, monkeypatch):
    sim = BorsaSim(doluluk=(1.0, 0.0))
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dur_tetikle("komut")
    assert m.dur_bekliyor
    sim.doluluk = [1.0]
    m2, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    m2.baslat()                                                                                 # KipHatasi YOK: pozisyon açıkta
    assert m2.risk.dur and m2.dur_bekliyor
    m2.dakika()
    assert m2.dur_istendi and sim.poz["BTC"] == pytest.approx(0.0, abs=1e-9)


def test_kapanis_sanal_sig_defter_kismi_dolum_kuyruga_sonra_likidite_gelince_kapanir(tmp_path):
    """Sanal kip, sığ defter: bid 99,9'da yalnız 0,1 BTC. Pozisyon 0,27273 BTC. Merdiven: 1. deneme 0,1 doldurur (kalan 0,17273); sonraki denemeler 5 sn içinde tüketilmiş seviyeyi göremez (T4b §9) → dolmaz.
    5 deneme sonunda `kapanis_eksik`; saat 6 sn ilerler + defter yenilenir → dakikalık yeniden denemede kalan kapanır."""
    hl = SahteHL()
    hl.kitaplar["BTC"] = {"levels": [[{"px": "99.9", "sz": "0.1"}], [{"px": "100", "sz": "1000"}]]}
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727 - 0.1, abs=1e-6) and f"{adr(1)}|BTC" in m.kapanis_kuyrugu and m.sayac["kapanis_eksik"] == 1
    hl.kitaplar["BTC"] = {"levels": [[{"px": "99.9", "sz": "1000"}], [{"px": "100", "sz": "1000"}]]}
    saat.ms += 6_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9) and not m.kapanis_kuyrugu


def test_azaltma_kismi_dolum_bir_sonraki_dakikada_yeniden_denenir(tmp_path):
    """Trader %50 azaltır → hedef 13,636 $ satış; sığ defter yalnız 0,01 BTC (0,999 $) doldurur → hedef pozisyon 0,136364; kalan 12,64 $ (≥ 10 $ minimum) sonraki dakikada (defter yenilenince, saat +6 sn) tamamlanır.
    (Kalan 10 $'ın altına düşseydi HL kısmi reduce-only emri reddeder: kuyruktan atılır, `min_nosyonel` sayılır.)"""
    hl = SahteHL(pozlar={adr(1): {"BTC": 150.0}})                                              # trader REST: 150 BTC kaldı (senkron kapatmasın)
    hl.kitaplar["BTC"] = {"levels": [[{"px": "99.9", "sz": "0.01"}], [{"px": "100", "sz": "1000"}]]}
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 150, 100.0, 300.0, saat))
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727 - 0.01, abs=1e-6) and f"{adr(1)}|BTC" in m.kapanis_kuyrugu
    hl.kitaplar["BTC"] = {"levels": [[{"px": "99.9", "sz": "1000"}], [{"px": "100", "sz": "1000"}]]}
    saat.ms += 6_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727 / 2, abs=1e-3) and not m.kapanis_kuyrugu          # hedef 0,13636; fiyat 99,9 vs mark 100 → ≤ %0,1 sapma (toz altı)


def test_senkron_trader_pozisyonu_0_ise_eski_kapanis_kapatilir_ama_yeni_olay_varsa_dokunulmaz(tmp_path):
    """K‑37 §5: 60 dk penceresinden eski kapanış kaçtı → senkron REST'te trader BTC pozisyonu 0: bizdeki pozisyon teyitli kapatılır. Okumadan SONRA işlenen dolum varsa o coine dokunulmaz."""
    hl = SahteHL(pozlar={adr(1): {}})
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    okunan = m.senkron_oku()
    assert okunan[adr(1)] == {}
    saat.ms += 1_000
    m.olay_isle(olay("a:2", adr(1), "BTC", "B", 10, 100.0, 300.0, saat))                       # okumadan SONRA yeni dolum
    m.senkron_uygula(okunan)
    assert m.hesap.sz(adr(1), "BTC") > 0 and m.poz_tr[adr(1)]["BTC"] == 310                    # dokunulmadı
    m.senkron_uygula(m.senkron_oku())
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9) and kayitlar(tmp_path, "senkron_kapanis")


# ================================================================================================ 3. niyet + cloid
def test_cloid_deterministik_sha256_ilk_16_bayt():
    c = ny.cloid_uret("0xabc:123", "ac")
    assert c == "0x" + hashlib.sha256(b"0xabc:123|ac").digest()[:16].hex() and len(c) == 34
    assert c == ny.cloid_uret("0xabc:123", "ac") and c != ny.cloid_uret("0xabc:123", "kapat")


def test_gercek_emir_cloid_ile_verilir_ve_niyet_emirden_once_yazilir(tmp_path, monkeypatch):
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    sira = []
    asil = sim.order

    def izle(*a, **k):
        sira.append(("emir", [x for x in m.niyet.satirlar() if x["t"] == "niyet"][-1]["cloid"]))        # emir çağrıldığında niyet DİSKTE
        return asil(*a, **k)
    sim.order = izle
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    beklenen = ny.cloid_uret("a:1", "ac")
    assert sira == [("emir", beklenen)] and sim.siparisler[0]["cloid"] is not None and str(sim.siparisler[0]["cloid"]) == beklenen
    s = m.niyet.satirlar()
    assert [x["t"] for x in s] == ["niyet", "sonuc"] and s[0]["kimlik"] == "a:1" and s[1]["cloid"] == beklenen and s[1]["durum"] == "dolu"


class Cokus(BaseException):
    """İşlemi öldüren çökme benzetimi (Exception DEĞİL: motorun hata yakalayıcıları yutmaz)."""


@pytest.mark.parametrize("kip", ["sanal", "gercek"])
def test_emir_ile_durum_yazimi_arasinda_cokme_ayni_dolum_ikinci_emir_uretmez(tmp_path, monkeypatch, kip):
    """Çökme, emir gönderildikten SONRA ama `durum_yaz`/sonuç satırından ÖNCE: yeniden başlatmada aynı dolum ikinci emir üretmemeli. Gerçek: `orderStatus(cloid)` ile emrin var olduğu görülür,
    sonuç işlenir (yerel defter dolan miktarı alır); sanal: niyet `sonucsuz` kaydedilir, emir TEKRARLANMAZ."""
    if kip == "gercek":
        sim = BorsaSim()
        m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    else:
        m, hl, saat, _ = kur(tmp_path)
        sim = None
    m.baslat()
    m.durum_yaz()
    o = olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat)
    gercek_emir = m.yurutucu.emir

    def coktur(*a, **k):
        d = gercek_emir(*a, **k)                                                               # emir borsaya GİTTİ
        if sim:
            sim.durumlar[k["cloid"]] = {"status": "order", "order": {"order": {"coin": "BTC", "side": "B", "limitPx": "100.5", "sz": "0.0", "origSz": str(sim.siparisler[-1]["dolan"]), "oid": 7}, "status": "filled"}}
        raise Cokus()
    m.yurutucu.emir = coktur
    with pytest.raises(Cokus):
        m.olay_isle(o)
    emirler_once = len(sim.siparisler) if sim else None
    assert [x["t"] for x in m.niyet.satirlar()] == ["niyet"]                                   # sonuç satırı yok
    # yeniden başlatma: yeni süreç, aynı durum dizini
    if kip == "gercek":
        m2, _, _, _ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    else:
        m2, _, _, _ = kur(tmp_path, saat=saat)
    m2.baslat()
    assert m2.olay_isle(o) == []                                                               # aynı kimlik: İKİNCİ EMİR YOK
    if kip == "gercek":
        assert len(sim.siparisler) == emirler_once == 1
        assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(0.27273, abs=1e-5)                  # orderStatus ile işlendi
        assert kayitlar(tmp_path, "niyet_sonucsuz")[-1]["durum"] == "filled"
    else:
        assert m2.hesap.sz(adr(1), "BTC") == 0.0 and kayitlar(tmp_path, "niyet_sonucsuz")[-1]["durum"] == "sonucsuz"
    assert m2.niyet.sonucsuz() == [] and m2.sayac["emir"] == 0


def test_gercek_orderstatus_emir_yoksa_niyet_iptal(tmp_path, monkeypatch):
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.niyet.niyet_yaz(kimlik="z:1", eylem="ac", adres=adr(1), coin="BTC", yon="B", usd=27.0, reduce_only=False, cloid=ny.cloid_uret("z:1", "ac"), ms=saat())
    m2, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    m2.baslat()
    assert kayitlar(tmp_path, "niyet_sonucsuz")[-1]["durum"] == "emir_yok_iptal" and m2.hesap.sz(adr(1), "BTC") == 0.0 and m2.olay_isle(olay("z:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat)) == []


# ================================================================================================ 2. özsermaye + funding
def test_gercek_risk_temeli_hl_ozsermayesi_gunluk_kayip_fark_alarmi_ve_zirve_dur(tmp_path, monkeypatch):
    """Kasa 1.000, HL hesabı 1.000 (ofset 0). Yerel defter 1.000 kalırken HL 949'a düşer: özsermaye 949 → gün başı 1.000'e göre −%5,1 ≥ %5 → günlük kayıp bayrağı; yerel ↔ HL farkı 51 $ > kasa × %1
    = 10 $ → `ozsermaye_farki` mutabakat alarmı + yeni açılış yok. HL 790'a düşünce zirveden −%21 ≥ %20 → DUR."""
    sim = BorsaSim(deger=1000.0)
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.dakika()
    assert m.hl_ofset == pytest.approx(0.0) and m.ozsermaye() == pytest.approx(1000.0) and not m.risk.acilis_durdu.get("mutabakat")
    sim.deger = 949.0
    saat.ms += 60_000
    m.dakika()
    assert m.ozsermaye() == pytest.approx(949.0) and m.yerel_ozsermaye() == pytest.approx(1000.0)
    assert m.risk.acilis_durdu["gunluk_kayip"] and m.risk.acilis_durdu["mutabakat"] and any("ozsermaye_farki" in str(x) for x in kayitlar(tmp_path, "mutabakat_alarm"))
    sim.deger = 790.0
    saat.ms += 60_000
    m.dakika()
    assert m.dur_istendi and m.risk.dur


def test_gercek_kasa_hesaptan_kucukse_ofset_fazla_bakiyeyi_riske_katmaz(tmp_path, monkeypatch):
    """Kasa 1.000 ama HL hesabı 5.000: ofset 4.000. HL 4.950 → özsermaye 950 (−%5: günlük kayıp), HL'nin 5.000'i değil."""
    sim = BorsaSim(deger=5000.0)
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim, kasa=1000.0)
    m.baslat()
    m.dakika()
    assert m.hl_ofset == pytest.approx(4000.0) and m.ozsermaye() == pytest.approx(1000.0)
    sim.deger = 4950.0
    saat.ms += 60_000
    m.dakika()
    assert m.ozsermaye() == pytest.approx(950.0) and m.risk.acilis_durdu["gunluk_kayip"]


def test_gercek_hl_degeri_eskiyse_yerel_deger_kullanilir(tmp_path, monkeypatch):
    sim = BorsaSim(deger=1000.0)
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.dakika()
    sim.deger = 900.0
    m.hl_uygula(900.0, saat())
    assert m.ozsermaye() == pytest.approx(900.0)
    saat.ms += 4 * 60_000                                                                      # 3 × 60 sn'den eski
    assert m.ozsermaye() == pytest.approx(m.yerel_ozsermaye())


def test_sanal_funding_altin_ornek_isaret_ve_birim(tmp_path):
    """Long 2 BTC (mark 100, oran +0,0001/sa): −2 × 100 × 0,0001 = −0,02 $ (long öder). Short 1 ETH (mark 2000, oran −0,00005): −(−1) × 2000 × (−0,00005) = −0,10 $ (negatif oranda short öder).
    Bir saatte toplam −0,12 $; iki saat kaçtıysa −0,24 $. Özsermaye funding kadar düşer; `kayit`: `funding` olayı; günlük özet funding'i taşır."""
    class FHL(SahteHL):
        def __call__(self, y):
            if y["type"] == "metaAndAssetCtxs":
                return [{"universe": [{"name": "BTC"}, {"name": "ETH"}]}, [{"funding": "0.0001"}, {"funding": "-0.00005"}]]
            return super().__call__(y)
    hl = FHL(pozlar={adr(1): {"BTC": 50.0, "ETH": -5.0}})                                      # trader pozisyonu sürüyor: senkron kapatmaz
    m, _, saat, tgp = kur(tmp_path, hl=hl)
    m.baslat()
    m.dakika()                                                                                  # saat dilimi başlatılır (saat tam saat başında)
    m.hesap.uygula(adr(1), "BTC", "B", 2.0, 100.0, 0.0, saat())
    m.hesap.uygula(adr(1), "ETH", "A", 1.0, 2000.0, 0.0, saat())
    m.piyasa_oku(saat())
    oz0 = m.ozsermaye()
    saat.ms += SAAT + 60_000                                                                    # bir tam saat geçti
    m.dakika()
    assert m.hesap.funding_toplam() == pytest.approx(-0.12) and m.ozsermaye() == pytest.approx(oz0 - 0.12)
    f = kayitlar(tmp_path, "funding")[-1]
    assert f["funding_usd"] == pytest.approx(-0.12) and f["saat_adet"] == 1 and m.ozet()["funding_usd"] == pytest.approx(-0.12)
    saat.ms += 2 * SAAT                                                                         # 2 saat kaçtı (ör. yeniden başlatma): 2 kez
    m.dakika()
    assert m.hesap.funding_toplam() == pytest.approx(-0.12 - 0.24)
    m.dakika()
    assert m.hesap.funding_toplam() == pytest.approx(-0.36)                                    # aynı saat ikinci kez uygulanmaz
    m.hesap.poz.clear()
    saat.ms += SAAT
    m.dakika()
    assert m.hesap.funding_toplam() == pytest.approx(-0.36)                                    # pozisyon yok: funding yok


def test_funding_hesap_kaydi_kalici_ve_slot_ozsermayesine_girer():
    from copytrade.canli.hesap import Hesap
    h = Hesap(1000.0)
    h.slot_ac("a", 90.0)
    h.funding_isle("a", -0.5)
    h2 = Hesap.from_json(h.to_json())
    assert h2.funding == {"a": -0.5} and h2.slot_ozsermaye("a", {}) == pytest.approx(89.5) and h2.ozsermaye({}) == pytest.approx(999.5)
    h2.slot_kapat("a")
    assert h2.kapanmis_net == pytest.approx(-0.5) and "a" not in h2.funding


def test_funding_yalniz_sanal_kipte_gercekte_hl_hesaplar(tmp_path, monkeypatch):
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    assert m.funding_uygula({"BTC": 0.01}, saat() + 5 * SAAT) == 0.0 and not any(x["type"] == "metaAndAssetCtxs" for x in sim.istekler)


# ================================================================================================ 6. kuyruk
def test_oncelikli_kuyruk_kapat_azalt_once_taserken_acilislar_duser_kapanislar_kalir(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.poz_tr[adr(1)] = {"BTC": 300.0}
    kuyruk = mt.OncelikliKuyruk(m.kapanis_mi, 3, saat)
    ac1, ac2 = olay("a:1", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat), olay("a:2", adr(1), "SOL", "B", 5, 100.0, 0.0, saat)
    kapat, azalt = olay("c:1", adr(1), "BTC", "A", 300, 100.0, 300.0, saat), olay("c:2", adr(1), "BTC", "A", 100, 100.0, 300.0, saat)
    for o in (ac1, ac2, kapat):
        kuyruk.put_nowait((o, True))
    kuyruk.put_nowait((azalt, True))                                                            # dolu (3): kapanış gelince en eski açılış (ac1) atılır
    assert kuyruk.qsize() == 3 and kuyruk.dusen_acilis == 1
    kuyruk.put_nowait((olay("a:3", adr(1), "ETH", "B", 1, 2000.0, 0.0, saat), True))            # yine dolu: yeni AÇILIŞ düşer
    assert kuyruk.dusen_acilis == 2 and kuyruk.qsize() == 3
    sira = [kuyruk.get_nowait()[0].kimlik for _ in range(3)]
    assert sira == ["c:1", "c:2", "a:2"]                                                       # kapanışlar önce (kendi aralarında FIFO), sonra kalan açılış
    with pytest.raises(asyncio.QueueEmpty):
        kuyruk.get_nowait()


def test_tuketici_kuyruk_gecikmesi_p50_max_ve_tasma_alarmi(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()

    async def kos():
        kuyruk = mt.OncelikliKuyruk(m.kapanis_mi, 2, saat)
        kuyruk.put_nowait((olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat), True))
        saat.ms += 1_500                                                                        # 1,5 sn kuyrukta bekledi
        kuyruk.put_nowait((olay("a:2", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat, yas_ms=0), True))
        kuyruk.put_nowait((olay("a:3", adr(1), "SOL", "B", 5, 100.0, 0.0, saat), True))          # taştı: düşer
        durdur = asyncio.Event()
        gorev = asyncio.create_task(mt._tuketici(m, kuyruk, durdur))
        await asyncio.sleep(0.3)
        durdur.set()
        await gorev
    asyncio.run(kos())
    g = m.ozet()["kuyruk_gecikme_ms"]
    assert g["n"] == 2 and g["max"] == 1500 and g["p50"] == 1500 and any("kuyruğu doldu" in x for x in tgp.gonderilen) and kayitlar(tmp_path, "kuyruk_tasti")


# ================================================================================================ 7. telegram
def test_telegram_from_id_zorunlu_yetkisiz_kayda_eski_mesaj_yok_sayilir_offset_kalici(tmp_path):
    kayit = []
    simdi = time.time()
    t = tg.Telegram(TOKEN, CHAT, SahteTG([tg_mesaj(1, "/dur", kimden=999),                        # doğru sohbet, yabancı gönderen
                                          tg_mesaj(2, "/dur", chat=7),                           # yabancı sohbet
                                          tg_mesaj(3, "/dur", tarih=simdi - 3600),               # motor başlamadan ÖNCE tarihli (eski /dur)
                                          tg_mesaj(4, "/durum", tarih=simdi + 5),                # geçerli
                                          tg_mesaj(5, "merhaba")]), kayit=kayit.append, baslangic_s=simdi)
    assert t.komutlari_al() == ["/durum"] and t.offset == 6 and t.yetkisiz_sayisi == 2
    assert [k["olay"] for k in kayit] == ["telegram_yetkisiz", "telegram_yetkisiz", "telegram_eski_komut"]
    # offset motor.json'da kalıcı
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.tg.offset = 77
    m.durum_yaz()
    m2, *_ = kur(tmp_path, saat=saat)
    assert m2.tg.offset == 77
    assert json.loads((tmp_path / "durum" / "motor.json").read_text(encoding="utf-8"))["tg_offset"] == 77


# ================================================================================================ 8. vardiya
def test_vardiya_boslugu_30_dk_asan_nabiz_alarm_ve_kayit(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    (tmp_path / "durum").mkdir(parents=True, exist_ok=True)
    (tmp_path / "durum" / "kilit.json").write_text(json.dumps({"vardiya": "eski", "nabiz_ms": saat() - 45 * 60_000, "birakildi": True}), encoding="utf-8")
    m.baslat()
    k = kayitlar(tmp_path, "vardiya_boslugu")
    assert len(k) == 1 and k[0]["dk"] == 45.0 and any("vardiya boşluğu 45 dk" in x for x in tgp.gonderilen)
    m2, _, saat2, tgp2 = kur(tmp_path / "b")
    (tmp_path / "b" / "durum").mkdir(parents=True, exist_ok=True)
    (tmp_path / "b" / "durum" / "kilit.json").write_text(json.dumps({"vardiya": "eski", "nabiz_ms": saat2() - 29 * 60_000, "birakildi": True}), encoding="utf-8")
    m2.baslat()
    assert not kayitlar(tmp_path / "b", "vardiya_boslugu")


# ================================================================================================ 9. sanal derinlik
def test_sanal_derinlik_ardisik_emirler_tuketileni_dusurur_5_sn_sonra_yenilenir():
    """Ask 100'de 1,0 BTC. 60 $ (0,6 BTC) alış: tam dolar. Hemen ardından ikinci 60 $: yalnız kalan 0,4 BTC (40 $) → `kismi`. 6 sn sonra defter yeniden 1,0: tam. Satış tarafı ayrı (bid etkilenmez)."""
    saat = [0]
    post = lambda y: {"levels": [[{"px": "99.9", "sz": "1.0"}], [{"px": "100", "sz": "1.0"}]]}          # noqa: E731
    s = yu.SanalYurutucu(post, RULES, saat_ms=lambda: saat[0])
    d1 = s.emir("BTC", "B", 60.0)
    assert d1.durum == "dolu" and d1.sz == pytest.approx(0.6)
    d2 = s.emir("BTC", "B", 60.0)
    assert d2.durum == "kismi" and d2.sz == pytest.approx(0.4) and d2.usd_dolan == pytest.approx(40.0)
    d3 = s.emir("BTC", "B", 60.0)
    assert d3.durum == "dolmadi" and d3.neden == "band_disi_ya_da_bos_defter"
    assert s.emir("BTC", "A", 50.0).durum == "dolu"                                              # karşı yön: bid etkilenmedi
    saat[0] = 6_000
    assert s.emir("BTC", "B", 60.0).durum == "dolu"                                              # pencere (5 sn) doldu


# ================================================================================================ 10. herkese açık veri
def test_kendi_hesap_adresi_hicbir_dosyaya_ve_telegram_mesajina_yazilmaz(tmp_path, monkeypatch):
    sim = BorsaSim()
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.kayit({"olay": "deneme", "hata": f"HTTP hatası user={HLADR}"})                             # adres bir hata metnine sızsa bile
    m.tg.gonder(f"deneme {HLADR.upper()}")
    m.dakika()
    m.dur_tetikle("deneme")
    m.durum_yaz()
    for f in list((tmp_path / "durum").rglob("*")) + list((tmp_path / "kayit").rglob("*")):
        if f.is_file():
            assert HLADR.lower() not in f.read_text(encoding="utf-8").lower(), f
    assert all(HLADR.lower() not in x.lower() for x in tgp.gonderilen) and any("[hesap]" in x for x in tgp.gonderilen)
    assert adr(1) in (tmp_path / "durum" / "hesap.json").read_text(encoding="utf-8")           # trader adresi (halka açık) kalır
