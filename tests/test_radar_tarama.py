"""Radar taraması (R0 evren + R1 kopyalanabilirlik; copytrade/radar_tarama.py): elle hesaplanmış altın örnekler ve uç durumlar. Ağsız (sahte istemci)."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from copytrade import radar_tarama as r
from copytrade.defter import HOUR
from copytrade.kurallar import load_rules
from copytrade.tarama import RateLimitError

RULES = load_rules()
MIN = 60_000
KOSU = int(datetime(2026, 10, 27, 12, 0, tzinfo=UTC).timestamp() * 1000)
BAS = KOSU - int(RULES["radar_pencere_saat"]) * HOUR
A1, A2, A3 = "0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40


def ms(saat: str) -> int:
    return int(pd.Timestamp(f"2026-10-27T{saat}Z").timestamp() * 1000)


def lider(adres, hesap, pnl, vlm):
    """Gerçek API biçimi: windowPerformances = [[pencere, {pnl, roi, vlm}], ...]."""
    return {"ethAddress": adres, "accountValue": str(hesap), "windowPerformances": [["day", {"pnl": "0", "roi": "0", "vlm": "0"}],
                                                                                      ["week", {"pnl": str(pnl), "roi": "0.1", "vlm": str(vlm)}]]}


# -------------------------------------------------------------------------------------------------------------------------------- R0
def test_evren_filtre_siniri_dahil_siralama_ve_kesilen():
    """Hafta başı sermaye = hesap − pnl ≥ 10.000 (tam sınır girer). 0xa 10.005−5 = 10.000 (girer, getiri 5e-4); 0xg 10.004,99−5 = 9.999,99 elenir; 0xb 9.499,99 elenir;
    0xe 9/49.991 = 1,80e-4; 0xf 5/29.995 = 1,67e-4; 0xc pnl 0 ve 0xd vlm 0 elenir."""
    satirlar = [lider("0xa", 10_005, 5, 1), lider("0xb", 9_999.99, 500, 1), lider("0xc", 20_000, 0, 1), lider("0xd", 20_000, 7, 0),
                lider("0xe", 50_000, 9, 3), lider("0xf", 30_000, 5, 2), lider("0xg", 10_004.99, 5, 1)]
    adaylar, toplam, kesilen = r.evren(satirlar, RULES)
    assert [a["adres"] for a in adaylar] == ["0xa", "0xe", "0xf"] and (toplam, kesilen) == (3, 0)
    adaylar, toplam, kesilen = r.evren(satirlar, RULES, aday_tavan=2)
    assert [a["adres"] for a in adaylar] == ["0xa", "0xe"] and (toplam, kesilen) == (3, 1)
    assert adaylar[0] == {"adres": "0xa", "hesap_usd": 10_005.0, "hafta_pnl_usd": 5.0, "hafta_vlm_usd": 1.0, "ay_pnl_usd": None}     # `month` penceresi yok → None (S1 kapısı uygulanmaz)


def test_evren_siralama_getiriye_gore_altin_ornek_k31():
    """K‑31 altın örnek (elle): A hesap 110.000 pnl 100.000 → sermaye 10.000 (sınırda girer), getiri 10,0 · C hesap 1.000.000 pnl 200.000 → sermaye 800.000, getiri 0,25 ·
    B hesap 50.000 pnl 5.000 → sermaye 45.000, getiri 0,1111 · D hesap 15.000 pnl 6.000 → sermaye 9.000 < 10.000 (yatırma şişirmesi) elenir.
    Beklenen sıra A, C, B (pnl $ sırası C, A, B olurdu)."""
    satirlar = [lider("0xB", 50_000, 5_000, 9), lider("0xC", 1_000_000, 200_000, 9), lider("0xD", 15_000, 6_000, 9), lider("0xA", 110_000, 100_000, 9)]
    adaylar, toplam, kesilen = r.evren(satirlar, RULES)
    assert [a["adres"] for a in adaylar] == ["0xA", "0xC", "0xB"] and (toplam, kesilen) == (3, 0)


def test_evren_eksik_alan_ve_bozuk_satir_evrene_girmez():
    bozuk = [{"ethAddress": "0xa", "windowPerformances": [["week", {"pnl": "5", "vlm": "1"}]]},                   # accountValue yok
             {"ethAddress": "0xb", "accountValue": "20000", "windowPerformances": []},                              # hafta penceresi yok
             {"accountValue": "20000", "windowPerformances": [["week", {"pnl": "5", "vlm": "1"}]]},               # adres yok
             {"ethAddress": "0xc", "accountValue": "abc", "windowPerformances": [["week", {"pnl": "5", "vlm": "1"}]]},
             lider("0xd", 20_000, 5, 1)]
    adaylar, toplam, _ = r.evren(bozuk, RULES)
    assert [a["adres"] for a in adaylar] == ["0xd"] and toplam == 1
    assert r.evren([], RULES) == ([], 0, 0)


# -------------------------------------------------------------------------------------------------------------------------------- trader getirisi, bootstrap
def test_trader_getirisi_altin_ornek_ve_payda_sinirlari():
    assert r.trader_getiri_7g(11_000, 1_000) == pytest.approx(0.10)         # 1.000 / (11.000 − 1.000)
    assert r.trader_getiri_7g(1_000, 1_000) is None                         # payda 0
    assert r.trader_getiri_7g(500, 1_000) is None                           # payda negatif


def test_bootstrap_alt_yuzdelik_elle_dagilim():
    """[+0,02, −0,01, +0,01], n = 3: 27 eşolasılıklı örnek toplamı; P(toplam < 0) = 4/27 ≈ 0,148 (−0,03 ×1, −0,01 ×3), P(toplam ≤ 0) = 7/27 ≈ 0,259 (+0,00 ×3)
    → %20 alt yüzdelik 0,00. 1.000 tekrar simülasyonu bu aralığın 4 σ içinde kalır; sabit tohum → aynı girdi aynı sonuç."""
    degerler = [0.02, -0.01, 0.01]
    sonuc = r.bootstrap_alt(degerler, 1000, 0.20, tohum=7)
    assert sonuc == pytest.approx(0.0, abs=1e-12)
    assert r.bootstrap_alt(degerler, 1000, 0.20, tohum=7) == sonuc
    assert r.bootstrap_alt(degerler, 1000, 0.10, tohum=7) == pytest.approx(-0.01, abs=1e-12)       # 4/27 = 0,148 > 0,10 → −0,01 kovası
    assert r.bootstrap_alt([], 1000, 0.20, tohum=7) is None
    assert r.bootstrap_alt([0.01] * 5, 1000, 0.20, tohum=1) == pytest.approx(0.05)                 # hepsi aynı: toplam sabit 5 × 0,01


def test_adres_tohumu_sabit():
    assert r.adres_tohumu("0x" + "f" * 40) == r.adres_tohumu("0x" + "F" * 40) == int("f" * 16, 16)


# -------------------------------------------------------------------------------------------------------------------------------- R1 kuralları: sınırın tam üstü / tam altı
def iyi():
    """Tüm R1 kurallarını sınırın TAM üstünde (geçecek biçimde) geçen satır."""
    return {"hesap_usd": 20_000.0, "islem_sayisi": 10, "medyan_tutma_saat": 1.0, "kisa_islem_payi": 0.25, "max_kaldirac": 20.0, "likit_pay": 0.80,
            "kopya_getiri_7g": 0.05, "kopya_koruma": 0.50, "devir_hafta": 100.0, "kopya_alt20": 0.001, "kopya_islem_sayisi": 10, "hata": None}


@pytest.mark.parametrize("alan,gecen,elenen,neden", [
    ("islem_sayisi", 10, 9, "islem_az"),
    ("medyan_tutma_saat", 1.0, 0.999, "tutma_kisa"),
    ("kisa_islem_payi", 0.25, 0.2501, "kisa_islem_fazla"),
    ("max_kaldirac", 20.0, 20.01, "kaldirac_yuksek"),
    ("likit_pay", 0.80, 0.7999, "likidite_dusuk"),
    ("kopya_getiri_7g", 0.0001, 0.0, "kopya_zarar"),                      # > 0 gerekir: tam 0 elenir
    ("kopya_koruma", 0.50, 0.4999, "kopya_koruma_dusuk"),
    ("devir_hafta", 100.0, 100.01, "devir_yuksek"),
    ("kopya_islem_sayisi", 10, 9, "kopya_islem_az"),                       # v1.1 (K-53) S2 mekanizması: eşik 10 iken ≥ 10 (sınır dahil); üretim değeri 0 (kullanıcı 14.11) ayrı testte
    ("kopya_alt20", 1e-9, 0.0, "sans_riski"),                              # alt yüzdelik tam 0 ELENİR
    ("kopya_getiri_7g", 3.0, 3.0001, "akil_sagligi"),                      # +%300 dahil geçer
])
def test_r1_kurali_sinirin_tam_ustu_gecer_tam_alti_elenir(alan, gecen, elenen, neden):
    satir = iyi()
    kurallar = {**RULES, "radar_min_kopya_islem": 10}                      # S2 kapısı açıkken (diğer kurallara etkisi yok)
    assert r.degerlendir({**satir, alan: gecen}, kurallar) == (True, None), alan
    assert r.degerlendir({**satir, alan: elenen}, kurallar) == (False, neden), alan


def test_radar_hunisi_1411_uretim_kopya_islem_kapisi_kapali_diger_kapilar_aynen():
    """Kullanıcı 14.11: `radar_min_kopya_islem` 10 → 0 (kapı kapalı): 1 kopya işlemli satır `kopya_islem_az` ile ELENMEZ; şans süzgeci (kural 8) aynen: alt yüzdelik 0 → `sans_riski`."""
    assert RULES["radar_min_kopya_islem"] == 0 and RULES["radar_aday_tavan"] == 900
    assert r.degerlendir({**iyi(), "kopya_islem_sayisi": 1}, RULES) == (True, None)
    assert r.degerlendir({**iyi(), "kopya_islem_sayisi": 1, "kopya_alt20": 0.0}, RULES) == (False, "sans_riski")
    assert r.degerlendir({**iyi(), "kopya_islem_sayisi": None}, RULES) == (True, None)          # kapı kapalıyken ölçü yokluğu kural değildir


def test_r1_eksik_olcu_basarisizdir_hata_veri_hatasi_ve_siralama_ilk_basarisiz():
    for alan in ("islem_sayisi", "medyan_tutma_saat", "kisa_islem_payi", "max_kaldirac", "likit_pay", "kopya_getiri_7g", "kopya_koruma", "devir_hafta", "kopya_alt20", "kopya_islem_sayisi"):
        assert r.degerlendir({**iyi(), alan: None}, {**RULES, "radar_min_kopya_islem": 10})[0] is False, alan        # S2 kapısı açıkken kopya_islem_sayisi da ölçü ister
    assert r.degerlendir({**iyi(), "hata": "429"}, RULES) == (False, "veri_hatasi")
    assert r.degerlendir({**iyi(), "islem_sayisi": 3, "likit_pay": 0.1}, RULES) == (False, "islem_az")                          # sırada ilk başarısız
    assert r.degerlendir({**iyi(), "islem_sayisi": 3, "devir_hafta": 500.0}, RULES) == (False, "devir_yuksek")                  # devir ucuz kural: en önce
    assert r.degerlendir({**iyi(), "kopya_getiri_7g": None}, RULES, yalniz_dolum=True) == (True, None)                          # yalnız dolum: kopya alanları bakılmaz
    assert r.degerlendir({**iyi(), "likit_pay": 0.1, "kopya_getiri_7g": None}, RULES, yalniz_dolum=True) == (False, "likidite_dusuk")
    assert r.degerlendir({**iyi(), "hesap_usd": 0.0}, RULES) == (False, "akil_sagligi")


# -------------------------------------------------------------------------------------------------------------------------------- işlem ölçüleri (elle)
def dolum(zaman_ms, coin, taraf, sz, onceki, px=100.0, kapanan=0.0, tid=None):
    return {"time": zaman_ms, "coin": coin, "side": taraf, "sz": str(sz), "startPosition": str(onceki), "px": str(px), "closedPnl": str(kapanan), "fee": "0",
            "tid": tid if tid is not None else zaman_ms, "oid": str(zaman_ms)}


def tur(baslangic_ms, sure_dk, coin="BTC", adet=1, px=100.0):
    """Tek round trip: long aç, `sure_dk` dakika sonra kapat (aynı fiyat; kâr 0)."""
    return [dolum(baslangic_ms, coin, "B", adet, 0, px, tid=baslangic_ms), dolum(baslangic_ms + sure_dk * MIN, coin, "A", adet, adet, px, tid=baslangic_ms + 1)]


def test_islem_olculeri_altin_ornek_tutma_kisa_pay_kaldirac_ve_likit_pay():
    """16 işlem: 4'ü 2 dk (< 5 dk → kısa), 12'si 60 dk → kısa pay 4/16 = 0,25; medyan 60 dk = 1,0 sa. Nosyonel: BTC 12 işlem × 200 $ = 2.400, ALT 4 × 200 = 800 → likit pay 0,75.
    Kaldıraç: 1 BTC @100 = 100 $ pozisyon / 100 $ hesap = 1,0x."""
    fills, t = [], BAS + HOUR
    for i in range(12):
        fills += tur(t, 60, "BTC"); t += 2 * HOUR
    for i in range(4):
        fills += tur(t, 2, "ALT"); t += 2 * HOUR
    o = r.islem_olculeri(fills, 100.0, {"BTC"}, RULES)
    assert o["islem_sayisi"] == 16 and o["medyan_tutma_saat"] == pytest.approx(1.0) and o["kisa_islem_payi"] == pytest.approx(0.25)
    assert o["max_kaldirac"] == pytest.approx(1.0) and o["likit_pay"] == pytest.approx(2400 / 3200)
    assert r.islem_olculeri(fills, 100.0, {"BTC", "ALT"}, RULES)["likit_pay"] == pytest.approx(1.0)


def test_islem_olculeri_bes_dakika_kisa_degil_ve_bos_liste():
    fills = tur(BAS + HOUR, 5) + tur(BAS + 3 * HOUR, 4)
    o = r.islem_olculeri(fills, 1000.0, {"BTC"}, RULES)
    assert o["kisa_islem_payi"] == pytest.approx(0.5)                          # tam 5 dk kısa değil; 4 dk kısa
    bos = r.islem_olculeri([], 1000.0, {"BTC"}, RULES)
    assert bos == {"islem_sayisi": 0, "medyan_tutma_saat": None, "kisa_islem_payi": None, "max_kaldirac": None, "likit_pay": None}


def test_pencere_basinda_acik_pozisyon_kapanisi_sayilir_tutma_bilinmez():
    """Pencere başından önce açılmış 5 BTC'nin kapanışı pencerede: işlem sayısına girer, tutma süresi bilinmediği için medyan / kısa paya girmez."""
    fills = [dolum(BAS + HOUR, "BTC", "A", 5, 5, 100, kapanan=50.0)] + tur(BAS + 2 * HOUR, 120)
    o = r.islem_olculeri(fills, 10_000.0, {"BTC"}, RULES)
    assert o["islem_sayisi"] == 2 and o["medyan_tutma_saat"] == pytest.approx(2.0) and o["kisa_islem_payi"] == 0.0


def test_iki_bin_uzeri_dolum_hepsi_sayilir():
    fills, t = [], BAS
    for i in range(1050):                                                        # 2.100 dolum, 1.050 işlem
        fills += tur(t, 10); t += 15 * MIN
    o = r.islem_olculeri(fills, 1_000_000.0, {"BTC"}, RULES)
    assert len(fills) == 2100 and o["islem_sayisi"] == 1050 and o["medyan_tutma_saat"] == pytest.approx(10 / 60)


# -------------------------------------------------------------------------------------------------------------------------------- sahte istemci: lider tablosu, vault, dolum, mum
class Sahte:
    """PublicClient'ın kullanılan yüzeyi. `fiyat(coin, ms)` dakikalık açılış fiyatı; None = mum yok (eksik mum)."""
    stats: dict = {}

    def __init__(self, liderler, dolumlar, fiyat=lambda coin, t: 100.0, vaultlar=(), hata=None, hacim=None):
        self.liderler, self.dolumlar, self.fiyat, self.vaultlar, self.hata = liderler, dolumlar, fiyat, set(vaultlar), hata or {}
        self.hacim = hacim or {"BTC": 5e8, "ETH": 3e8, "ALT": 1000.0}
        self.cagrilar: list = []
        self.dk_siniri = None

    def leaderboard(self):
        return self.liderler

    def vault_details(self, adres):
        self.__dict__.setdefault("vault_cagri", []).append(adres)
        return {"name": "vault"} if adres in self.vaultlar else {}

    def non_funding_ledger(self, adres, bas):
        """T6 §2: `userNonFundingLedgerUpdates` (yalnız startTime). `defterler[adres]` ya da boş."""
        return getattr(self, "defterler", {}).get(adres, [])

    def fills(self, adres, bas, max_rows=None, end_ms=None):
        self.cagrilar.append(("fills", adres, bas, end_ms))
        if adres in self.hata:
            raise self.hata[adres]
        return [f for f in self.dolumlar.get(adres, []) if int(f["time"]) >= bas and (end_ms is None or int(f["time"]) <= end_ms)]

    def candles(self, coin, bas, son, interval="1m"):
        adim = {"1m": MIN, "5m": 5 * MIN}.get(interval, HOUR)
        if interval == "1m" and self.dk_siniri:                                 # gerçek HL: 1 dk mum yalnız son 5.000 dakika
            bas = max(bas, son - self.dk_siniri * MIN)
        t = bas // adim * adim
        satirlar = []
        while t <= son:
            p = self.fiyat(coin, t)
            if p is not None:
                satirlar.append({"t": t, "o": str(p), "c": str(p), "h": str(p), "l": str(p)})
            t += adim
        return satirlar

    def info(self, payload, weight=20):
        tip = payload["type"]
        if tip == "perpDexs":
            return [None]
        if tip == "metaAndAssetCtxs":
            adlar = list(self.hacim)
            return [{"universe": [{"name": a} for a in adlar]}, [{"dayNtlVlm": str(self.hacim[a])} for a in adlar]]
        if tip == "meta":
            return {"universe": [{"name": a, "maxLeverage": 50} for a in self.hacim]}
        if tip == "fundingHistory":                                             # M-03: coin başına pencere funding'i (varsayılan yok)
            self.__dict__.setdefault("funding_cagri", []).append(payload["coin"])
            return getattr(self, "fonlama", {}).get(payload["coin"], [])
        raise AssertionError(payload)


RULES1 = {**RULES, "radar_min_islem": 1, "radar_min_kopya_islem": 1}          # tek işlemli senaryolarda dolum tabanlı kurallar ve v1.1 kopya işlem kapısı (S2) geçsin (kopya oynatma çalışsın); eşik testleri RULES ile ayrıca


def kos(istemci, tmp_path, adet=None, rules=RULES, **kw):
    return r.kos(istemci, KOSU, tmp_path / "radar", adet, rules, log=lambda *_: None, **kw)


def satir_al(sonuc, adres):
    return next(s for s in sonuc["satirlar"] if s["adres"] == adres)


def test_kopya_oynatma_altin_ornek_tek_coin_100_den_110a(tmp_path):
    """K‑28/K‑32 (v5). 10 BTC trader 10:00'da 100'den açar (nosyonel 1.000 $, hesap 20.000 $ → oran 0,05), 11:00'de 110'dan kapatır. Slot = 1.000/11 = 90,909 $ → hedef 4,545 $ < 11 → 11 $'a yuvarlanır (0,11 BTC).
    Ayna (gecikmesiz, maliyetsiz): kâr 0,11 × 10 = 1,10 $ → 0,0011. Kopya (1 dk gecikme; mum 10:01 → 100, 11:01 → 110): maliyet (11 + 12,1) × 0,00095 = 0,021945 $ → net 1,078055 $ → 0,001078055.
    kopya_koruma = 1,078055 / 1,10 = 0,98005 ≥ 0,50 → geçer (eski v4 sabit tutar ölçüsünde 0,40 ile elenirdi)."""
    dolumlar = {A1: [dolum(ms("10:00:00"), "BTC", "B", 10, 0, 100), dolum(ms("11:00:00"), "BTC", "A", 10, 10, 110, kapanan=100.0)]}
    fiyat = lambda coin, t: 110.0 if t >= ms("11:00:00") else 100.0               # noqa: E731
    c = Sahte([lider(A1, 20_000, 100, 5_000)], dolumlar, fiyat)
    s = satir_al(kos(c, tmp_path, rules=RULES1), A1)
    assert s["ayna_getiri_7g"] == pytest.approx(0.0011, abs=1e-9)
    assert s["kopya_getiri_7g"] == pytest.approx(0.001078055, abs=1e-9)
    assert s["kopya_koruma"] == pytest.approx(0.98005, abs=1e-5) and s["trader_getiri_7g"] == pytest.approx(100 / 19_900)
    assert s["islem_sayisi"] == 1 and s["fiyatsiz_eylem"] == 0 and s["yaklasik_fiyat_eylem"] == 0
    assert s["gecti"] is True and s["neden"] is None and s["hata"] is None and s["v4_kopya_getiri_7g"] is None
    # R2 ham girdileri (yalnız gecti satırı): işlem 27 Eki'de → günlük getiri serisi 8 gün (20–27 Eki), yalnız son gün 0,001078055 (= kopya net / kasa)
    # F-08 (14.11): son gün (27 Eki, koşu 12:00 → 12 sa) kısmi → İ1/korelasyon serisinden atılır: 7 tam gün (20–26 Eki), hepsi 0; aktif gün yok → İ1 0
    assert len(s["kopya_gunluk"]) == 7 and all(g == 0.0 for g in s["kopya_gunluk"])
    assert s["kopya_kazanc_gun_orani"] == 0.0 and s["kopya_dusus"] == 0.0 and s["yayilma"] == 0.0        # düşüş yok; tek işlem → 1 − 1/1
    # F-03 (14.11): son 72 sa = 7 günlük oynatmanın eğrisinden, SLOT ölçeğinde: net 1,078055 $ / slot 90,909 $ = 0,011858605
    assert s["kopya_getiri_72s"] == pytest.approx(1.078055 / (1000 / 11), abs=1e-8) and s["kopya_getiri_72s_durum"] == "egri"
    assert s["kopya_slot_kat"] == pytest.approx(11.0)
    assert s["hype_payi"] is None        # F-09: radar_agirlik_h = 0 → H için mum çekilmez
    sh = satir_al(kos(Sahte([lider(A1, 20_000, 100, 5_000)], dolumlar, fiyat), tmp_path / "h", rules={**RULES1, "radar_agirlik_h": 0.1}), A1)
    assert sh["hype_payi"] == 1.0        # tüm coinler +%10 (trend) ve long 100'den (hareketin %0'ı gerçekleşmeden = erken) açıldı: kârın tamamı erken-trend


def test_v4_yan_yana_bilgi_alani_hesabi_degistirmez(tmp_path):
    """`v4_yan_yana`: aynı dolumlar kopya_v4 (sabit tutar N = 5,2 × 5^0,86 $) ile de oynanır: net = N × (0,10 − 2,1 × 0,00095), getiri ≈ 0,002034 (T2 altın örneği); v5 sayıları aynı kalır."""
    dolumlar = {A1: [dolum(ms("10:00:00"), "BTC", "B", 10, 0, 100), dolum(ms("11:00:00"), "BTC", "A", 10, 10, 110, kapanan=100.0)]}
    fiyat = lambda coin, t: 110.0 if t >= ms("11:00:00") else 100.0               # noqa: E731
    s = satir_al(r.kos(Sahte([lider(A1, 20_000, 100, 5_000)], dolumlar, fiyat), KOSU, tmp_path / "radar", None, RULES1, log=lambda *_: None, v4_yan_yana=True), A1)
    assert s["v4_kopya_getiri_7g"] == pytest.approx(0.0020340, abs=1e-6) and s["kopya_getiri_7g"] == pytest.approx(0.001078055, abs=1e-9)
    assert s["v5_onceki_kopya_getiri_7g"] == pytest.approx(0.001078055, abs=1e-9)          # tek 11 $ emir: K‑35 öncesi/sonrası aynı (tavanlar devreye girmez)


def test_ayna_sifir_ya_da_negatifse_kopya_koruma_none_ve_elenir(tmp_path):
    """Trader zararda (110'dan açıp 100'e kapatır): ayna ≤ 0 → `kopya_koruma` None → `kopya_zarar` (kopya < 0) ELENİR; ayna 0 (fiyat aynı) → kopya (maliyet) < 0 → `kopya_zarar`."""
    dolumlar = {A1: [dolum(ms("10:00:00"), "BTC", "B", 10, 0, 110), dolum(ms("11:00:00"), "BTC", "A", 10, 10, 100, kapanan=-100.0)]}
    fiyat = lambda coin, t: 100.0 if t >= ms("11:00:00") else 110.0              # noqa: E731
    s = satir_al(kos(Sahte([lider(A1, 20_000, 100, 5_000)], dolumlar, fiyat), tmp_path, rules=RULES1), A1)
    assert s["ayna_getiri_7g"] < 0 and s["kopya_koruma"] is None and s["gecti"] is False and s["neden"] == "kopya_zarar"
    assert r.degerlendir({**s, "kopya_getiri_7g": 0.001, "ayna_getiri_7g": 0.0, "kopya_koruma": None, "kopya_alt20": 0.1, "hesap_usd": 1.0}, RULES1) == (False, "kopya_koruma_dusuk")


def test_eksik_mum_koşuyu_dusurmez_fiyat_uydurulmaz(tmp_path):
    """10:01 yürütme mumu yok: satır `veri_hatasi` OLMAZ, kopya sayıları sonlu; açılıştaki eksik fiyat için sahte fiyat yazılmaz (açılış kopyalanmaz → kazanç 100→110'dan gelmez)."""
    dolumlar = {A1: [dolum(ms("10:00:00"), "BTC", "B", 10, 0, 100), dolum(ms("11:00:00"), "BTC", "A", 10, 10, 110, kapanan=100.0)]}
    fiyat = lambda coin, t: None if ms("10:00:30") < t < ms("10:02:00") else (110.0 if t >= ms("11:00:00") else 100.0)       # noqa: E731
    c = Sahte([lider(A1, 20_000, 100, 5_000)], dolumlar, fiyat)
    s = satir_al(kos(c, tmp_path, rules=RULES1), A1)
    assert s["hata"] is None and isinstance(s["kopya_getiri_7g"], float)
    assert s["kopya_getiri_7g"] < 0.002                                                    # tam kâr 0,00203 olurdu; açılış fiyatsız → kopyalanmadı


def test_kopya_olculeri_hesaplanamadi_ve_bos_sonuc():
    bos = {"kopya_getiri_7g": None, "ayna_getiri_7g": None, "kopya_koruma": None, "kopya_alt20": None, "fiyatsiz_eylem": None, "yaklasik_fiyat_eylem": None, "v4_kopya_getiri_7g": None, "v5_onceki_kopya_getiri_7g": None,
           "kopya_islem_sayisi": None, "yuvarlanan_pay": None, "oransal_ayna": None, "koruma_boyut": None,          # B3/B12 bilgi alanları (08.11)
           "g_t_istat": None, "kopya_slot_kat": None}                                                             # B14 bilgi alanı (08.11); F-03 slot katı (14.11)
    assert r.kopya_olculeri(None, A1, RULES) == bos
    yok = r.kopya_olculeri({"durum": "hesaplanamadi", "neden": "yürütülebilir dolum yok"}, A1, RULES)
    assert yok["kopya_getiri_7g"] is None and yok["kopya_alt20"] is None
    sonuc = {"getiri": 0.05, "ayna": {"getiri": 0.10}, "baslangic_usd": 1000.0, "fiyatsiz_eylem": 2,
             "kapanan_islemler": [{"sonuc_usd": 20.0, "gecerli": True}, {"sonuc_usd": 30.0, "gecerli": True}, {"sonuc_usd": 99.0, "gecerli": False}]}
    o = r.kopya_olculeri(sonuc, A1, RULES)
    assert o["kopya_getiri_7g"] == 0.05 and o["ayna_getiri_7g"] == 0.10 and o["kopya_koruma"] == pytest.approx(0.5) and o["fiyatsiz_eylem"] == 2
    assert o["kopya_alt20"] == r.bootstrap_alt([0.02, 0.03], 1000, 0.20, r.adres_tohumu(A1))          # geçersiz işlem (gecerli: false) bootstrap'a girmez
    assert r.kopya_olculeri({**sonuc, "ayna": {"getiri": 0.0}}, A1, RULES)["kopya_koruma"] is None     # ayna 0 → oran yok
    assert r.kopya_olculeri({**sonuc, "ayna": {"getiri": -0.01}}, A1, RULES)["kopya_koruma"] is None
    k500 = r.kopya_olculeri({**sonuc, "baslangic_usd": 500.0}, A1, RULES)                              # işlem getirileri kopya kasasına göre (500 $): 0,04 / 0,06
    assert k500["kopya_alt20"] == r.bootstrap_alt([0.04, 0.06], 1000, 0.20, r.adres_tohumu(A1))


def test_koşu_sozlesme_alanlari_vault_payda_hesap_ve_429(tmp_path):
    liderler = [lider(A1, 20_000, 100, 5_000), lider(A2, 30_000, 90, 5_000), lider(A3, 40_000, 80, 5_000), lider("0x" + "4" * 40, 50_000, 70, 5_000),
                lider("0x" + "5" * 40, 12_000, 60, 5_000)]
    dolumlar = {A1: tur(ms("10:00:00"), 60), A2: tur(ms("10:00:00"), 60)}
    c = Sahte(liderler, dolumlar, vaultlar=[A2], hata={A3: RateLimitError("429")})
    sonuc = kos(c, tmp_path, rules=RULES1)                                                   # A2 dolum kurallarını geçer → vault sorulur (14.11 hız: önce dolum kapıları)
    assert sonuc["sema"] == "radar-havuz-v1" and sonuc["kosu_ms"] == KOSU and sonuc["pencere_bas_ms"] == BAS
    assert (sonuc["evren_toplam"], sonuc["evren_kesilen"], len(sonuc["satirlar"])) == (5, 0, 5)
    assert satir_al(sonuc, A2)["neden"] == "vault" and satir_al(sonuc, A2)["gecti"] is False
    veri_hatasi = satir_al(sonuc, A3)
    assert veri_hatasi["neden"] == "veri_hatasi" and "429" in veri_hatasi["hata"]            # istek hatası: koşu sürer, uydurma yok
    assert satir_al(sonuc, "0x" + "4" * 40)["neden"] == "islem_az" and satir_al(sonuc, "0x" + "5" * 40)["islem_sayisi"] == 0       # boş dolum listesi
    yazilan = json.loads((tmp_path / "radar/2026-10-27/havuz.json").read_text(encoding="utf-8"))
    assert yazilan == sonuc
    anahtarlar = {"adres", "hesap_usd", "hafta_pnl_usd", "trader_getiri_7g", "islem_sayisi", "medyan_tutma_saat", "kisa_islem_payi", "max_kaldirac", "likit_pay",
                  "kopya_getiri_7g", "ayna_getiri_7g", "kopya_koruma", "devir_hafta", "kopya_alt20", "fiyatsiz_eylem", "yaklasik_fiyat_eylem", "v4_kopya_getiri_7g", "v5_onceki_kopya_getiri_7g", "kopya_gunluk", "kopya_kazanc_gun_orani", "kopya_dusus", "yayilma", "kopya_getiri_72s", "hype_payi", "hip3_nosyonel_pay", "net_yatirma_usd", "yatirma_payi", "gecti", "neden", "hata",
                  "payda_kaynak", "payda_nokta", "payda_bas_usd", "payda_son_oran", "kopya_islem_sayisi", "yuvarlanan_pay", "oransal_ayna", "koruma_boyut", "g_t_istat",
                  "ay_pnl_usd", "tutma", "kopya_slot_kat", "kopya_getiri_72s_durum"}      # 14.11 F-03: slot katı + 72 sa durum kaydı; v1.1 (K-53): 30 g pnl + tutma işareti; T6 §2: iki yeni bilgi alanı; K‑43 adayı: hip3_nosyonel_pay; 08.11: B8 payda + B3/B12 + B14 bilgi alanları
    assert all(set(s) == anahtarlar for s in sonuc["satirlar"])
    assert all(c_[3] == KOSU for c_ in c.cagrilar) and all(c_[2] == BAS for c_ in c.cagrilar)         # pencere [kosu − 168 sa, kosu)


def test_payda_yok_ve_hesap_sifir_ayni_koruma(tmp_path):
    aday = {"adres": A1, "hesap_usd": 10_000.0, "hafta_pnl_usd": 10_000.0, "hafta_vlm_usd": 1.0}
    b = r.Baglam(Sahte([], {}), KOSU, BAS, RULES)
    assert r.kopyalanabilirlik(aday, [], None, b)["neden"] == "payda_yok"
    assert r.kopyalanabilirlik({**aday, "hesap_usd": 0.0, "hafta_pnl_usd": 5.0}, [], None, b)["neden"] == "payda_yok"


def test_aday_sayisi_tavani_evren_kesilen_yazilir(tmp_path):
    liderler = [lider("0x" + str(i) * 40, 20_000, 100 - i, 1_000) for i in range(1, 6)]
    sonuc = kos(Sahte(liderler, {}), tmp_path, adet=2)
    assert (sonuc["evren_toplam"], sonuc["evren_kesilen"], len(sonuc["satirlar"])) == (5, 3, 2)
    assert [s["adres"] for s in sonuc["satirlar"]] == ["0x" + "1" * 40, "0x" + "2" * 40]


def test_devir_hesabi_ve_ozet_tablosu(tmp_path):
    sonuc = kos(Sahte([lider(A1, 20_000, 100, 2_000_000), lider(A2, 20_000, 90, 40_000)], {}), tmp_path)
    assert satir_al(sonuc, A1)["devir_hafta"] == pytest.approx(100.0) and satir_al(sonuc, A2)["devir_hafta"] == pytest.approx(2.0)
    md = r.ozet_md(sonuc)
    assert "satır 2, gecti **0**" in md and "| islem_az | 2 |" in md and "| devir_hafta | 2 | 2 | 51 | 100 |" in md


def test_mum_onbellegi_her_coin_serisini_bir_kez_ceker_ve_dilimden_yanitlar():
    c = Sahte([], {})
    cagri = []
    asil = c.candles
    c.candles = lambda coin, bas, son, interval="1m": (cagri.append((coin, interval)), asil(coin, bas, son, interval))[1]
    m = r.MumOnbellegi(c, KOSU, BAS)
    a = m.candles("BTC", KOSU - 10 * MIN, KOSU, "1m")
    b = m.candles("BTC", KOSU - 3 * MIN, KOSU - 1 * MIN, "1m")
    assert [x["t"] for x in a][-1] == KOSU and [x["t"] for x in b] == [KOSU - 3 * MIN, KOSU - 2 * MIN, KOSU - MIN]
    assert m.candles("BTC", KOSU - 2 * HOUR, KOSU, "1h")[0]["t"] == (KOSU - 2 * HOUR) // HOUR * HOUR
    assert cagri == [("BTC", "1m"), ("BTC", "1h")]                                      # ikinci 1 dk çağrısı API'ye gitmedi
    assert m.candles("BTC", 0, 1, "1m") == []                                           # kapsam dışı dilim boş (uydurma yok)


# -------------------------------------------------------------------------------------------------------------------------------- lider kararları (2026-11-04): ucuzdan pahalıya, tavan, bütçe
def test_devir_ve_payda_dolum_cekilmeden_elenir_vault_dolum_kurallarindan_sonra(tmp_path):
    """14.11 hız düzeltmesi: `vault_details` yalnız dolum kurallarını (ucuz R1 kapıları) geçen adayda sorulur; dolum kuralında elenen vault da olsa vault sorusu gitmez."""
    A4 = "0x" + "4" * 40
    liderler = [lider(A1, 20_000, 100, 2_000_001), lider(A2, 20_000, 90, 2_000_000), lider(A3, 20_000, 80, 1_000), lider(A4, 20_000, 70, 1_000)]
    c = Sahte(liderler, {A1: tur(ms("10:00:00"), 60), A2: tur(ms("10:00:00"), 60)}, vaultlar=[A1, A2, A3])
    sonuc = kos(c, tmp_path, rules=RULES1)
    assert satir_al(sonuc, A1)["neden"] == "devir_yuksek" and satir_al(sonuc, A1)["devir_hafta"] == pytest.approx(100.00005)     # vault olsa da devir önce
    assert [x for x in c.cagrilar if x[1] == A1] == []                                                                           # dolum çekilmedi
    assert satir_al(sonuc, A2)["neden"] == "vault" and satir_al(sonuc, A2)["islem_sayisi"] == 1 and satir_al(sonuc, A2)["kopya_getiri_7g"] is None   # tam 100 kat devir geçer → dolum kuralları → vault
    assert satir_al(sonuc, A3)["neden"] == "islem_az" and satir_al(sonuc, A4)["neden"] == "islem_az"                            # dolum kuralında elenen vault'a sorulmaz
    assert c.vault_cagri == [A2]
    assert satir_al(sonuc, A1)["islem_sayisi"] is None                                                                           # ölçülmeyen alan null
    assert satir_al(sonuc, A2)["net_yatirma_usd"] is None and satir_al(sonuc, A3)["net_yatirma_usd"] is None                     # para hareketi yalnız kopya oynatmasına varana


def test_dolum_fazla_perp_suzgecinden_sonra_spot_dolum_sayilmaz(tmp_path):
    """14.11: tavan (6) PERP dolumla sayılır. A1: 4 perp + 4 spot (@ önekli) = 8 ham ≥ 6 ama perp 4 < 6 → dolum_fazla DEĞİL, ölçülür (spot dolumlar 2. çekimle gelir).
    A2: 6 perp → dolum_fazla. A3: 12 ham (= 2 × tavan, pencere kesik) → dolum_fazla."""
    kurallar = {**RULES, "radar_dolum_tavan": 6}
    perp, t = [], BAS + HOUR
    for _ in range(3):
        perp += tur(t, 60); t += 2 * HOUR
    spot = [{**f, "coin": "@107", "tid": f"s{i}"} for i, f in enumerate(perp[:4])]
    c = Sahte([lider(A1, 20_000, 100, 5_000), lider(A2, 20_000, 90, 5_000), lider(A3, 20_000, 80, 5_000)],
              {A1: perp[:4] + spot, A2: perp, A3: [{**f, "coin": "@107", "tid": f"x{i}"} for i, f in enumerate(perp + perp)]})
    sonuc = kos(c, tmp_path, rules=kurallar)
    assert satir_al(sonuc, A1)["neden"] == "islem_az" and satir_al(sonuc, A1)["islem_sayisi"] == 2         # perp 2 işlem ölçüldü (eskiden dolum_fazla)
    assert satir_al(sonuc, A2)["neden"] == "dolum_fazla" and satir_al(sonuc, A3)["neden"] == "dolum_fazla"
    assert [x[1] for x in c.cagrilar].count(A1) == 2 and [x[1] for x in c.cagrilar].count(A2) == 1        # spot ağırlıklı hesap yeniden (2 × tavan) çekilir


def test_dolum_tavani_ve_max_rows_dolum_fazla_kopya_oynatilmaz(tmp_path):
    kurallar = {**RULES, "radar_dolum_tavan": 6}
    fills, t = [], BAS + HOUR
    for i in range(3):
        fills += tur(t, 60); t += 2 * HOUR                                        # 6 dolum = tavan
    c = Sahte([lider(A1, 20_000, 100, 5_000), lider(A2, 20_000, 90, 5_000)], {A1: fills, A2: fills[:4]})
    sonuc = kos(c, tmp_path, rules=kurallar)
    assert satir_al(sonuc, A1)["neden"] == "dolum_fazla" and satir_al(sonuc, A1)["islem_sayisi"] is None and satir_al(sonuc, A1)["kopya_getiri_7g"] is None
    assert satir_al(sonuc, A2)["neden"] == "islem_az" and satir_al(sonuc, A2)["islem_sayisi"] == 2                 # tavanın altı: normal
    assert all(c_[0] == "fills" for c_ in c.cagrilar)


def test_dolum_tabanli_kural_basarisizsa_kopya_oynatilmaz(tmp_path):
    c = Sahte([lider(A1, 20_000, 100, 5_000)], {A1: tur(ms("10:00:00"), 60)})
    cagri = []
    asil = c.candles
    c.candles = lambda *a, **k: (cagri.append(a), asil(*a, **k))[1]
    s = satir_al(kos(c, tmp_path), A1)                                           # 1 işlem < 10: islem_az
    assert s["neden"] == "islem_az" and s["islem_sayisi"] == 1 and s["kopya_getiri_7g"] is None and s["fiyatsiz_eylem"] is None and cagri == []   # mum bile çekilmedi


def test_zaman_butcesi_asilinca_kalan_adaylar_zaman_yok(tmp_path):
    durum = {"t": 0.0}
    liderler = [lider("0x" + str(i) * 40, 20_000, 100 - i, 1_000) for i in range(1, 5)]
    c = Sahte(liderler, {})
    asil = c.fills
    def fills(*a, **k):
        durum["t"] = float(RULES["radar_zaman_butcesi_dk"]) * 60.0                      # ilk adaydan sonra bütçe (150 dk) doldu
        return asil(*a, **k)
    c.fills = fills
    sonuc = kos(c, tmp_path, saat=lambda: durum["t"])
    nedenler = [x["neden"] for x in sonuc["satirlar"]]
    assert nedenler[0] == "islem_az" and nedenler[1:] == ["zaman_yok"] * 3
    assert satir_al(sonuc, "0x" + "2" * 40)["islem_sayisi"] is None and "| zaman_yok | 3 |" in r.ozet_md(sonuc)


def test_yeni_kodlar_sirasi_ve_kurallar_anahtarlari():
    assert r.NEDENLER == ("veri_hatasi", "payda_yok", "devir_yuksek", "dolum_fazla", "islem_az", "tutma_kisa", "kisa_islem_fazla", "kaldirac_yuksek",
                          "likidite_dusuk", "vault", "kopya_zarar", "kopya_koruma_dusuk", "kopya_islem_az", "sans_riski", "akil_sagligi", "zaman_yok")
    assert (RULES["radar_dolum_tavan"], RULES["radar_api_agirlik_dk"], RULES["radar_zaman_butcesi_dk"]) == (5000, 1100, 150)          # 14.11: bütçe 120 → 150 (900 aday)


# -------------------------------------------------------------------------------------------------------------------------------- 5 dk yürütme fiyatı (eski kısım)
def test_eski_hedef_5dk_mumun_kotu_fiyati_alis_buyuk_satis_kucuk_ve_varsayilan_degismedi():
    """Hedef 10:08 (gecikme 1 dk → dolum 10:06:10 → 10:07:10 → yukarı yuvarlanır 10:08), 5 dk mumu 10:05: o = 100, c = 104. Alışta max = 104, satışta min = 100; karışık yön = açılış 100.
    Varsayılan (1 sa) davranış aynen: saatin açılışı. Hedefler 1 dk geçmişin (4.999 dk) dışında olacak kadar eski."""
    from copytrade import izleme_motoru as im
    simdi = ms("10:08:00") + 5_000 * MIN

    class Istemci:
        def candles(self, coin, bas, son, interval="1m"):
            assert interval in ("5m", "1h", "1m")
            if interval == "1m":
                return []
            return [{"t": ms("10:05:00"), "o": "100", "c": "104"}] if interval == "5m" else [{"t": ms("10:00:00"), "o": "90", "c": "95"}]

    alis = [{"coin": "BTC", "time": ms("10:06:10"), "side": "B"}]
    satis = [{"coin": "BTC", "time": ms("10:06:10"), "side": "A"}]
    for dolum, beklenen in ((alis, 104.0), (satis, 100.0), (alis + satis, 100.0)):
        cache = {}
        im.execution_candles(Istemci(), dolum, cache, simdi, 1, [], {}, eski_aralik="5m")
        assert cache["BTC"][str(ms("10:08:00"))] == {"fiyat": beklenen, "yaklasik": True}
    cache = {}
    im.execution_candles(Istemci(), alis, cache, simdi, 1, [], {})                     # varsayılan: 1 sa açılışı (bugünkü davranış)
    assert cache["BTC"][str(ms("10:08:00"))] == {"fiyat": 90.0, "yaklasik": True}
    eksik = []
    im.execution_candles(type("I", (), {"candles": lambda *a, **k: []})(), alis, {}, simdi, 1, eksik, {}, eski_aralik="5m")
    assert eksik == [{"coin": "BTC", "hedef": ms("10:08:00")}]                          # 5 dk mum yoksa fiyat uydurulmaz


def test_eski_dolumlar_5dk_mum_yolu_gercek_sekilli_mumlarla_veri_hatasi_vermez(tmp_path):
    """Gerçek koşu hatası (300 aday, 9/9 `veri_hatasi`, hata = "'c'"): 1 dk mum yalnız son 5.000 dk olduğundan 3,5 günden eski dolumlar 5 dk mum yolundan geçer ve o yol
    kapanışı (`c`) okur; `MumOnbellegi` yalnız `t`/`o` döndürünce KeyError('c') çıkıyordu. Burada 5 gün önce 100'den açılıp 110'dan kapanan işlem, 5 dk mum açılış 100 → 110 (kapanış aynı):
    `veri_hatasi` OLMAZ, kopya alanları dolar, `yaklasik_fiyat_eylem` 2 (iki eylem de 5 dk mumdan)."""
    t_ac, t_kapa = KOSU - 5 * 24 * HOUR, KOSU - 5 * 24 * HOUR + HOUR
    dolumlar = {A1: [dolum(t_ac, "BTC", "B", 10, 0, 100), dolum(t_kapa, "BTC", "A", 10, 10, 110, kapanan=100.0)]}
    fiyat = lambda coin, t: 110.0 if t >= t_kapa else 100.0                       # noqa: E731
    c = Sahte([lider(A1, 20_000, 100, 5_000)], dolumlar, fiyat)
    c.dk_siniri = 4999
    s = satir_al(kos(c, tmp_path, rules=RULES1), A1)
    assert s["hata"] is None and s["neden"] != "veri_hatasi"
    assert isinstance(s["kopya_getiri_7g"], float) and s["kopya_getiri_7g"] > 0 and s["yaklasik_fiyat_eylem"] == 2


def test_mum_onbellegi_kapanisi_korur():
    c = Sahte([], {}, lambda coin, t: 100.0)
    m = r.MumOnbellegi(c, KOSU, KOSU - HOUR)
    satir = m.candles("BTC", KOSU - HOUR, KOSU, interval="5m")
    assert satir and all(x["o"] == 100.0 and x["c"] == 100.0 for x in satir)


# -------------------------------------------------------------------------------------------------------------------------------- 5xx yeniden deneme, kural_ust
class _Yanit:
    def __init__(self, kod, veri=None):
        self.status_code, self._veri, self.headers = kod, veri, {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} Server Error: Internal Server Error for url: https://api.hyperliquid.xyz/info")

    def json(self):
        return self._veri


class _Oturum:
    def __init__(self, kodlar):
        self.kodlar, self.cagri = list(kodlar), 0

    def request(self, method, url, json=None, timeout=30):
        self.cagri += 1
        kod = self.kodlar.pop(0)
        return _Yanit(kod, {"ok": True} if kod == 200 else None)


def test_radar_istemcisi_5xx_uc_kez_yeniden_dener_sonra_veri_hatasi():
    """HL 5xx (300 koşusunda 1 kez `500 Internal Server Error`): 3 yeniden deneme (5/15/45 sn artan bekleme); 500, 500, 200 → başarı; 4 kez 500 → HTTPError (`veri_hatasi`)."""
    uyku: list[float] = []
    oturum = _Oturum([500, 500, 200])
    assert r.radar_istemcisi(oturum, sleep=uyku.append).info({"type": "meta"}) == {"ok": True}
    assert oturum.cagri == 3 and uyku == [5, 15]
    uyku2: list[float] = []
    oturum2 = _Oturum([500, 500, 500, 500])
    with pytest.raises(Exception) as hata:
        r.radar_istemcisi(oturum2, sleep=uyku2.append).info({"type": "meta"})
    assert oturum2.cagri == 4 and uyku2 == [5, 15, 45] and "500" in str(hata.value)


def test_5xx_koşuda_veri_hatasi_satiri_ve_hata_mesaji(tmp_path):
    import requests
    c = Sahte([lider(A1, 20_000, 100, 5_000)], {}, hata={A1: requests.HTTPError("500 Server Error: Internal Server Error")})
    s = satir_al(kos(c, tmp_path), A1)
    assert s["neden"] == "veri_hatasi" and "500" in s["hata"]


def test_kural_ust_yalniz_radar_anahtarlari_ve_tur():
    yeni, uygulanan = r.kural_ust_uygula(RULES, ["radar_min_islem=5"])
    assert yeni["radar_min_islem"] == 5 and isinstance(yeni["radar_min_islem"], int) and uygulanan == {"radar_min_islem": 5} and RULES["radar_min_islem"] == 10
    assert r.kural_ust_uygula(RULES, ["radar_kopya_koruma_min=0.4"])[0]["radar_kopya_koruma_min"] == 0.4
    for kotu in ("maliyet_taker=0", "radar_yok=1", "radar_min_islem"):
        with pytest.raises(ValueError):
            r.kural_ust_uygula(RULES, [kotu])


def test_kural_ust_havuz_json_a_yazilir(tmp_path):
    kurallar, ust = r.kural_ust_uygula(RULES, ["radar_min_islem=5"])
    sonuc = r.kos(Sahte([lider(A1, 20_000, 100, 5_000)], {}), KOSU, tmp_path / "radar", None, kurallar, log=lambda *_: None, kural_ust=ust)
    assert sonuc["kural_ust"] == {"radar_min_islem": 5}
    assert "kural_ust" not in kos(Sahte([lider(A1, 20_000, 100, 5_000)], {}), tmp_path / "b")


def test_h_yalniz_ana_dex_coinleri_builder_dex_mumu_istenmez():
    """Gerçek koşu bulgusu: 557 coinin 322'si builder dex (`xyz:AAPL`, `cash:BTC` …) ve saatlik mum vermiyor; her biri hız sınırından 20 ağırlık yer (≈ 13 dk boşa). H yalnız ana dex coinlerini okur."""
    istenen: list[str] = []

    class Istemci(Sahte):
        def candles(self, coin, bas, son, interval="1m"):
            istenen.append(coin)
            return super().candles(coin, bas, son, interval)

    c = Istemci([], {}, hacim={"BTC": 5e8, "ETH": 3e8, "xyz:AAPL": 1e7, "cash:BTC": 1e7})
    b = r.Baglam(c, KOSU, BAS, RULES)
    b.piyasa_oku()
    b.hareket(log=lambda *_: None)
    assert sorted(set(istenen)) == ["BTC", "ETH"]


# -------------------------------------------------------------------------------------------------------------------------------- T6 §2: trader para hareketi (bilgi)
def test_net_yatirma_altin_ornek_ve_uc_durumlar():
    """Pencere [1000, 2000]: yatırma 5.000 + 1.000, çekme 2.000 → net 4.000. Pencere dışı (999), diğer türler (iç transfer, spot/perp), sayı olmayan tutar yok sayılır."""
    ledger = [{"time": 1500, "delta": {"type": "deposit", "usdc": "5000.0"}}, {"time": 1600, "delta": {"type": "deposit", "usdc": "1000"}},
              {"time": 1700, "delta": {"type": "withdraw", "usdc": "2000.0", "fee": "1"}},
              {"time": 999, "delta": {"type": "deposit", "usdc": "9999"}}, {"time": 2001, "delta": {"type": "withdraw", "usdc": "9999"}},
              {"time": 1800, "delta": {"type": "accountClassTransfer", "usdc": "777", "toPerp": True}}, {"time": 1900, "delta": {"type": "deposit", "usdc": "yok"}}, {"time": 1900, "delta": {}}]
    assert r.net_yatirma(ledger, 1000, 2000) == pytest.approx(4000.0) and r.net_yatirma([], 0, 1) == 0.0
    assert r.net_yatirma([{"time": 5, "delta": {"type": "withdraw", "usdc": "300"}}], 0, 10) == -300.0          # net çekme negatif


def test_yatirma_payi_hafta_basi_sermayeye_oranlanir_ve_isaret_esigi():
    """hesap 14.000, hafta pnl 4.000 → hafta başı sermaye 10.000; net 3.000 → pay 0,3 (> 0,2 işaretlenir); 2.000 → tam 0,2 işaretlenmez (> kuralı). Sermaye ≤ 0 → None."""
    assert r.yatirma_payi(3000.0, 14_000.0, 4000.0) == pytest.approx(0.3) and r.yatirma_payi(2000.0, 14_000.0, 4000.0) == pytest.approx(0.2)
    assert r.yatirma_payi(1.0, 4000.0, 4000.0) is None
    satirlar = [{"adres": "a", "yatirma_payi": 0.3, "gecti": True}, {"adres": "b", "yatirma_payi": 0.2}, {"adres": "c", "yatirma_payi": None}, {"adres": "d", "yatirma_payi": -0.5}]
    assert [x["adres"] for x in r.yatirma_isaretli(satirlar, 0.2)] == ["a"]


def test_para_hareketi_ekle_okuma_hatasi_alani_bos_birakir_zaman_yok_atlanir_tarama_bozulmaz():
    class C:
        def non_funding_ledger(self, adres, bas):
            if adres == "bozuk":
                raise ValueError("boom")
            return [{"time": 5, "delta": {"type": "deposit", "usdc": "3000"}}]
    satirlar = [{"adres": "iyi", "hesap_usd": 14_000.0, "hafta_pnl_usd": 4000.0, "neden": None}, {"adres": "bozuk", "hesap_usd": 1.0, "hafta_pnl_usd": 0.0, "neden": None},
                {"adres": "zy", "hesap_usd": 1.0, "hafta_pnl_usd": 0.0, "neden": "zaman_yok"}]
    assert r.para_hareketi_ekle(C(), satirlar, 0, 10, RULES, log=lambda *_: None) == 1
    assert satirlar[0]["net_yatirma_usd"] == 3000.0 and satirlar[0]["yatirma_payi"] == pytest.approx(0.3)
    assert "net_yatirma_usd" not in satirlar[1] and "net_yatirma_usd" not in satirlar[2]
    sayac = {"t": 0.0}
    def saat():
        sayac["t"] += float(RULES["radar_zaman_butcesi_dk"]) * 60.0 * 0.6       # bütçenin %60'ı: ikinci çağrıda aşılır
        return sayac["t"]
    satirlar2 = [{"adres": "iyi", "hesap_usd": 14_000.0, "hafta_pnl_usd": 4000.0, "neden": None} for _ in range(3)]
    assert r.para_hareketi_ekle(C(), satirlar2, 0, 10, RULES, log=lambda *_: None, saat=saat, baslangic=0.0) == 1          # bütçe aşınca durur


def test_para_hareketi_havuz_json_a_ve_ozete_yazilir(tmp_path):
    liderler = [{"ethAddress": "0x" + "ab" * 20, "accountValue": "14000", "windowPerformances": [["week", {"pnl": "4000", "roi": "0.4", "vlm": "40000"}]]}]
    istemci = Sahte(liderler, {"0x" + "ab" * 20: tur(ms("10:00:00"), 60)})                 # 14.11: para hareketi yalnız dolum kurallarını geçip kopya oynatmasına varana
    istemci.defterler = {"0x" + "ab" * 20: [{"time": BAS + 1000, "delta": {"type": "deposit", "usdc": "3000"}}]}
    sonuc = r.kos(istemci, KOSU, tmp_path, 5, RULES1, log=lambda *_: None)
    s = sonuc["satirlar"][0]
    assert s["net_yatirma_usd"] == 3000.0 and s["yatirma_payi"] == pytest.approx(0.3)
    md = r.ozet_md(sonuc)
    assert "yatirma_payi` > 0.2 olan **1** kişi" in md and "| net_yatirma_usd | 1 |" in md


# -------------------------------------------------------------------------------------------------------------------------------- K‑43 adayı: radar_hip3_kopya
def _hip3_senaryo(tmp_path, rules):
    """Trader hesabı 20.000 $. BTC: 10 adet 10:00'da 100'den açılır, 11:00'de 110'dan kapanır (kopya 0,001078055, ayna 0,0011; bkz. yukarıdaki altın örnek). `xyz:GOLD`: 5 adet 10:00'da 2.000'den açılır,
    11:00'de 2.100'den kapanır. Slot 90,909 $ → GOLD hedefi 90,909 × 10.000 / 20.000 = 45,4545 $ (≥ 11, tavan 272,7 altında) = 0,0227273 adet.
    Ayna GOLD kârı 0,0227273 × 100 = 2,272727 $ → toplam ayna (1,10 + 2,272727) / 1.000 = 0,003372727. Kopya maliyeti GOLD: (45,4545 + 47,7273) × 0,00095 = 0,0885227 $ → net 2,184205 $;
    toplam kopya (1,078055 + 2,184205) / 1.000 = 0,00326226. `false`: GOLD'un iki dolumu (açılış + kapanış) oynatmadan çıkar → yalnız BTC sayıları; trader ölçüleri (işlem sayısı 2) ve `hip3_nosyonel_pay` = (10.000 + 10.500) / (1.000 + 1.100 + 10.000 + 10.500) = 20.500 / 22.600 = 0,90708 (açılış + kapanış dolumları) değişmez."""
    dolumlar = {A1: [dolum(ms("10:00:00"), "BTC", "B", 10, 0, 100), dolum(ms("10:00:00"), "xyz:GOLD", "B", 5, 0, 2000),
                     dolum(ms("11:00:00"), "BTC", "A", 10, 10, 110, kapanan=100.0), dolum(ms("11:00:00"), "xyz:GOLD", "A", 5, 5, 2100, kapanan=500.0)]}
    fiyat = lambda coin, t: (2100.0 if coin == "xyz:GOLD" else 110.0) if t >= ms("11:00:00") else (2000.0 if coin == "xyz:GOLD" else 100.0)   # noqa: E731
    c = Sahte([lider(A1, 20_000, 100, 5_000)], dolumlar, fiyat, hacim={"BTC": 5e8, "xyz:GOLD": 5e8})
    return satir_al(kos(c, tmp_path, rules=rules), A1)


def test_radar_hip3_kopya_true_ikisi_de_kopyalanir_eski_v1_davranisi(tmp_path):
    assert RULES["radar_hip3_kopya"] is False                                     # K‑43: varsayılan = HIP‑3 hariç
    s = _hip3_senaryo(tmp_path, {**RULES1, "radar_hip3_kopya": True})
    assert s["ayna_getiri_7g"] == pytest.approx(0.003372727, abs=1e-8) and s["kopya_getiri_7g"] == pytest.approx(0.00326226, abs=1e-7)
    assert s["hip3_nosyonel_pay"] == pytest.approx(20_500 / 22_600) and s["islem_sayisi"] == 2 and s["gecti"] is True


def test_radar_hip3_kopya_false_yalniz_perp_kopyalanir_trader_olculeri_degismez(tmp_path):
    s = _hip3_senaryo(tmp_path, {**RULES1, "radar_hip3_kopya": False})
    assert s["ayna_getiri_7g"] == pytest.approx(0.0011, abs=1e-9) and s["kopya_getiri_7g"] == pytest.approx(0.001078055, abs=1e-9)
    assert s["hip3_nosyonel_pay"] == pytest.approx(20_500 / 22_600) and s["islem_sayisi"] == 2
    assert s["likit_pay"] == 1.0 and s["gecti"] is True


def test_radar_hip3_kopya_ve_canli_hip3_kopya_varsayilanlari_ayni():
    assert RULES["radar_hip3_kopya"] is RULES["canli_hip3_kopya"] is False         # iki anahtar ayrışmasın (K‑43)


def test_ozet_md_gecti_11den_azsa_uyari_satiri(tmp_path):
    sonuc = kos(Sahte([lider(A1, 20_000, 100, 2_000_000)], {}), tmp_path)
    assert "⚠ UYARI: gecti 0 < 11" in r.ozet_md(sonuc)


def test_hip3_ayikla_spot_ve_perp_kalir_hip3_tamami_gider():
    from copytrade import kopya_v5
    f = [{"coin": "BTC"}, {"coin": "xyz:GOLD"}, {"coin": "@107"}, {"coin": "PURR/USDC"}, {"coin": "flx:TSLA"}]
    assert [x["coin"] for x in kopya_v5.hip3_ayikla(f, False)] == ["BTC", "@107", "PURR/USDC"]
    assert kopya_v5.hip3_ayikla(f, True) == f


def test_hip3_nosyonel_pay_uc_durumlar():
    assert r.hip3_nosyonel_pay([]) is None                                          # nosyonel 0
    assert r.hip3_nosyonel_pay([dolum(1, "@5", "B", 1, 0, 10)]) is None             # yalnız spot: perp nosyoneli yok
    assert r.hip3_nosyonel_pay([dolum(1, "BTC", "B", 1, 0, 100)]) == 0.0
    assert r.hip3_nosyonel_pay([dolum(1, "BTC", "B", 1, 0, 100), dolum(2, "xyz:GOLD", "B", 3, 0, 100)]) == pytest.approx(0.75)   # 300 / 400


def test_kural_ust_bool_false_gercekten_false_olur():
    yeni, uygulanan = r.kural_ust_uygula(RULES, ["radar_hip3_kopya=false"])
    assert yeni["radar_hip3_kopya"] is False and uygulanan == {"radar_hip3_kopya": False} and RULES["radar_hip3_kopya"] is False
    assert r.kural_ust_uygula(RULES, ["radar_hip3_kopya=true"])[0]["radar_hip3_kopya"] is True
    with pytest.raises(ValueError):
        r.kural_ust_uygula(RULES, ["radar_hip3_kopya=hayir"])


def test_m02_g_ve_y_acik_kopya_islemini_sanal_kapanisla_katar():
    """M-02 (14.11): G (bootstrap alt yüzdelik) ve Y (yayılma) dizisi = kapanan + pencere sonu açık (sanal kapanış) işlemler. Kasa 1.000 $: kapanan +20 $, açık −60 $ (geçerli),
    işareti olmayan açık (gecerli false) dışarıda → dizi [0,02; −0,06]; önceden yalnız [0,02] (alt yüzdelik > 0, `sans_riski` geçerdi)."""
    sonuc = {"getiri": -0.04, "ayna": {"getiri": 0.01}, "baslangic_usd": 1000.0, "slot_usd": 1000.0 / 11,
             "kapanan_islemler": [{"sonuc_usd": 20.0, "gecerli": True}],
             "acik_islemler": [{"sonuc_usd": -60.0, "gecerli": True, "neden": "pencere_sonu"}, {"sonuc_usd": 5.0, "gecerli": False, "neden": "pencere_sonu"}]}
    o = r.kopya_olculeri(sonuc, A1, RULES)
    assert o["kopya_islem_sayisi"] == 2
    assert o["kopya_alt20"] == r.bootstrap_alt([0.02, -0.06], int(RULES["radar_bootstrap_tekrar"]), float(RULES["radar_bootstrap_alt_yuzdelik"]), r.adres_tohumu(A1))
    eski = r.kopya_olculeri({**sonuc, "acik_islemler": []}, A1, RULES)
    assert eski["kopya_islem_sayisi"] == 1 and eski["kopya_alt20"] > 0 > o["kopya_alt20"]
    assert [t["sonuc_usd"] for t in r.g_y_islemleri(sonuc)] == [20.0, -60.0, 5.0]


def test_m03_radar_kopyasi_funding_ve_sig_coin_tavani_motorla_ayni():
    """M-03 (Fable mantık denetimi, 14.11). Kasa 1.000 → slot 90,909 $.
    Funding: altın örnekteki 0,11 BTC kopya 10:01–11:01 açık, 11:00'de oran 0,001, fiyat 110 → −0,11 × 110 × 0,001 = −0,0121 $ → kopya 0,001078055 − 0,0000121 = 0,001065955; ayna (10:00–11:00 açık, saat açılışı 100) −0,11 × 100 × 0,001 = −0,011 $ → 0,0011 − 0,000011.
    Sığ coin: ALT (24 sa hacim 1.000 $ < `canli_sig_hacim_usd`): trader 30.000 $ açar / hesap 20.000 → hedef 1,5 × slot = 136,36 $ → sığ tavan 0,75 × slot = 68,18 $ → ayna 0,6818 × 10 / 1.000 = 0,0068182."""
    dol = [dolum(ms("10:00:00"), "BTC", "B", 10, 0, 100), dolum(ms("11:00:00"), "BTC", "A", 10, 10, 110, kapanan=100.0)]
    fiyat = lambda coin, t: 110.0 if t >= ms("11:00:00") else 100.0               # noqa: E731
    c = Sahte([], {}, fiyat)
    c.fonlama = {"BTC": [{"coin": "BTC", "fundingRate": "0.001", "premium": "0", "time": ms("11:00:00")}]}
    b = r.Baglam(c, KOSU, BAS, RULES)
    b.piyasa_oku()
    o = b.kopya_oynat(dol, 20_000.0)
    assert o["getiri"] == pytest.approx(0.001078055 - 0.0000121, abs=1e-9) and o["ayna"]["getiri"] == pytest.approx(0.0011 - 0.000011, abs=1e-9)
    b.kopya_oynat(dol, 20_000.0)
    assert c.funding_cagri == ["BTC"]                                            # coin başına koşuda bir kez (önbellek)
    alt = [dolum(ms("10:00:00"), "ALT", "B", 300, 0, 100), dolum(ms("11:00:00"), "ALT", "A", 300, 300, 110, kapanan=3000.0)]
    b2 = r.Baglam(Sahte([], {}, fiyat), KOSU, BAS, RULES)
    b2.piyasa_oku()
    sig = b2.kopya_oynat(alt, 20_000.0)
    assert sig["ayna"]["getiri"] == pytest.approx(0.75 * 1000 / 11 * 0.1 / 1000)
    b2.hacim["ALT"] = 5e8                                                        # derin coin: yalnız slot tavanı (1,5 × slot)
    assert b2.kopya_oynat(alt, 20_000.0)["ayna"]["getiri"] == pytest.approx(1.5 * 1000 / 11 * 0.1 / 1000)
