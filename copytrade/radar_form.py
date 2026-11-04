"""R2 form puanı (docs/RADAR_V1.md §4): T2 `havuz.json` içindeki `gecti` adaylarının havuz-içi göreli puanı. Saf fonksiyonlar (ağ yalnız `coin_hareketleri`'nde).

`form = Σ ağırlık × yüzdelik` (G 0,35 · K 0,15 · İ1 0,10 · İ2 0,10 · Y 0,10 · H 0,20; ağırlıklar `kurallar.yaml` `radar_agirlik_*`). Her bileşen havuz içinde 0–100 yüzdelik sıraya çevrilir
(eşitlikte ortalama sıra; 1 kişi → 50). İ2 düşüşte AZ = iyi (yüzdelik ters). Birimler (VERI_SOZLESMESI.md "Radar havuzu" ve "Radar kadro"): oranlar kesir, `kopya_*` = kopya kasası ölçeği (`kopya_$`).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from copytrade.kurallar import load_rules

HOUR = 3_600_000
DAY = 24 * HOUR
BILESENLER = ("G", "K", "I1", "I2", "Y", "H")
AGIRLIK_ANAHTARI = {"G": "radar_agirlik_g", "K": "radar_agirlik_k", "I1": "radar_agirlik_i1", "I2": "radar_agirlik_i2", "Y": "radar_agirlik_y", "H": "radar_agirlik_h"}
HAM_ALAN = {"G": "kopya_alt20", "K": "kopya_getiri_7g", "I1": "kopya_kazanc_gun_orani", "I2": "kopya_dusus", "Y": "yayilma", "H": "hype_payi"}


def yuzdelik_sira(degerler: list[float | None], az_iyi: bool = False) -> list[float]:
    """Değerlerin havuz-içi yüzdelik sırası (0 = en kötü … 100 = en iyi). Eşit değerlere ortalama sıra; `az_iyi=True`: küçük değer yüksek puan. None = en kötü (sıra 0 grubuna girer).
    1 kişi → 50. Altın: [1, 2, 3] → [0, 50, 100]; [1, 1, 3] → [25, 25, 100]."""
    n = len(degerler)
    if n == 0:
        return []
    if n == 1:
        return [50.0]
    anahtar = [(-math.inf if v is None else (-float(v) if az_iyi else float(v))) for v in degerler]
    sirali = sorted(range(n), key=lambda i: anahtar[i])
    sira = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and anahtar[sirali[j + 1]] == anahtar[sirali[i]]:
            j += 1
        ortalama = (i + j) / 2.0                                  # 0 tabanlı ortalama sıra
        for k in range(i, j + 1):
            sira[sirali[k]] = ortalama / (n - 1) * 100.0
        i = j + 1
    return sira


def gunluk_getiriler(egri: list[list], kasa_usd: float) -> list[float]:
    """Günlük kopya getirisi (kasa ölçeği) = (özsermaye_gün − özsermaye_önceki_gün) / kasa; ilk gün önceki = kasa (kopya pencere başında BOŞ, kasa tam). `egri` = kopya_v5 `egri` ([[gün, özsermaye $]])."""
    onceki, sonuc = float(kasa_usd), []
    for _, deger in egri:
        sonuc.append((float(deger) - onceki) / float(kasa_usd))
        onceki = float(deger)
    return sonuc


def kazanc_gun_orani(gunluk: list[float], eps: float = 1e-12) -> float:
    """İ1: aktif günlerde (günlük getiri ≠ 0) kopya günlük getirisi > 0 olan gün oranı; aktif gün yoksa 0."""
    aktif = [g for g in gunluk if abs(g) > eps]
    return sum(1 for g in aktif if g > 0) / len(aktif) if aktif else 0.0


def yayilma(kapanan_islemler: list[dict]) -> float:
    """Y = 1 − (en iyi tek kopya işleminin toplam brüt kârdaki payı); brüt kâr = kârlı işlemlerin toplamı. Kâr yoksa 0."""
    karlar = [float(t["sonuc_usd"]) for t in kapanan_islemler if t.get("gecerli") is not False and t.get("sonuc_usd") is not None and float(t["sonuc_usd"]) > 0]
    return 1.0 - max(karlar) / sum(karlar) if karlar else 0.0


def coin_hareketleri(client: Any, coinler: list[str], kosu_ms: int, pencere_bas_ms: int, rules: dict | None = None, log=None) -> dict[str, dict]:
    """H için coin başına piyasa hareketi: saatlik mumlarla (`radar_hype_yeni_gun` gün geriye) {p0 (pencere başı açılış), p1 (son açılış), getiri, yeni (listelenme ≤ N gün), saatlik {saat_ms: açılış}}
    ve `trend` (|getiri| üst `radar_hype_trend_oran` (niceliği ≥) **ya da** yeni). Mumu olmayan / hata veren coin atlanır (trend sayılmaz)."""
    rules = rules or load_rules()
    gun = int(rules["radar_hype_yeni_gun"])
    baslangic = (kosu_ms - gun * DAY) // HOUR * HOUR
    pbas = pencere_bas_ms // HOUR * HOUR
    sonuc: dict[str, dict] = {}
    for coin in coinler:
        try:
            mumlar = client.candles(coin, baslangic, kosu_ms, interval="1h")
        except Exception as hata:                              # noqa: BLE001 — tek coin hatası H'yi düşürmez (o coin trend sayılmaz); günlüğe yazılır
            if log:
                log(f"H: {coin} mumu okunamadı: {hata}")
            continue
        saatlik = {int(c["t"]): float(c["o"]) for c in mumlar if c.get("o") is not None and float(c["o"]) > 0}
        pencere = sorted(t for t in saatlik if t >= pbas)
        if not saatlik or not pencere:
            continue
        p0, p1 = saatlik[pencere[0]], saatlik[pencere[-1]]
        ilk = min(saatlik)
        sonuc[coin] = {"p0": p0, "p1": p1, "getiri": p1 / p0 - 1.0, "yeni": ilk > baslangic + HOUR, "saatlik": saatlik}
    return trend_isaretle(sonuc, rules)


def trend_isaretle(hareket: dict[str, dict], rules: dict | None = None) -> dict[str, dict]:
    """`trend` = |getiri| ≥ üst `radar_hype_trend_oran` eşiği (1 − oran niceliği) **ya da** `yeni`. Altın: 4 coin |getiri| [0,40, 0,10, 0,05, 0,01], hiçbiri yeni değil, oran 0,25 → nicelik(0,75) = 0,10 + 0,25 × (0,40 − 0,10) = 0,175 → yalnız 0,40 trend."""
    rules = rules or load_rules()
    if hareket:
        esik = float(np.quantile([abs(h["getiri"]) for h in hareket.values()], 1.0 - float(rules["radar_hype_trend_oran"])))
    for h in hareket.values():
        h["trend"] = bool(abs(h["getiri"]) >= esik or h["yeni"])
    return hareket


def hype_payi(islemler: list[dict], hareket: dict[str, dict], rules: dict | None = None) -> float:
    """H: trader'ın son 7 gün brüt kârının (kârlı round trip `net_pnl` toplamı) erken-trend girişlerden gelen payı (0–1); kâr yoksa 0.
    Erken-trend giriş = açılışı bilinen (`open_time` var) işlem, coin trend, coinin 7 g hareketi işlemin yönünde (`d × (p1 − p0) > 0`) ve açılış anında bu hareketin %`radar_hype_erken_pay`'ından
    AZI gerçekleşmiş (saatlik açılış mumu, açılış saatine yuvarlanmış). Yön = işlemin ilk dolumu (B = long). Girdi `islemler`: `olcut.closed_round_trips` satırları."""
    rules = rules or load_rules()
    pay = float(rules["radar_hype_erken_pay"])
    toplam = erken = 0.0
    for t in islemler:
        kar = float(t["net_pnl"])
        if kar <= 0:
            continue
        toplam += kar
        h = hareket.get(str(t["coin"]))
        if t.get("open_time") is None or h is None or not h.get("trend") or not t.get("fills"):
            continue
        yon = 1.0 if t["fills"][0]["side"] == "B" else -1.0
        hareket_yonu = yon * (h["p1"] - h["p0"])
        if hareket_yonu <= 0:
            continue
        acilis = int(t["open_time"].value // 1_000_000) // HOUR * HOUR
        fiyat = h["saatlik"].get(acilis)
        if fiyat is None:
            continue
        if yon * (fiyat - h["p0"]) / hareket_yonu < pay:
            erken += kar
    return erken / toplam if toplam > 0 else 0.0


def soguyor(satir: dict, rules: dict | None = None) -> bool:
    """Form sürüyor mu (sert kural): son `radar_soguyor_saat` saatte kopya getirisi ≥ `radar_soguyor_min_getiri` (tam −%2 GEÇER). Ölçü yoksa (None) soğuyor sayılır (kanıt yok = puanlanmaz)."""
    rules = rules or load_rules()
    g = satir.get("kopya_getiri_72s")
    return g is None or float(g) < float(rules["radar_soguyor_min_getiri"])


def form_puanla(havuz_satirlari: list[dict], rules: dict | None = None) -> tuple[list[dict], list[dict]]:
    """`gecti` satırlarından form puanı. Döner: (puanlananlar form azalan [eşitlikte adres], `soguyor` nedeniyle puanlanmayanlar [{adres, neden: 'soguyor', kopya_getiri_72s}]).
    Yüzdelikler `soguyor` elenenler DIŞINDA kalan havuzda hesaplanır. Puanlananlar: {adres, form, bilesenler {G,K,I1,I2,Y,H: yüzdelik}, ham alanlar}."""
    rules = rules or load_rules()
    gecenler = [s for s in havuz_satirlari if s.get("gecti")]
    soguyanlar = [{"adres": s["adres"], "neden": "soguyor", "kopya_getiri_72s": s.get("kopya_getiri_72s")} for s in gecenler if soguyor(s, rules)]
    adaylar = [s for s in gecenler if not soguyor(s, rules)]
    yuzdelikler = {b: yuzdelik_sira([s.get(HAM_ALAN[b]) for s in adaylar], az_iyi=(b == "I2")) for b in BILESENLER}
    puanli = []
    for i, s in enumerate(adaylar):
        bilesen = {b: yuzdelikler[b][i] for b in BILESENLER}
        puanli.append({"adres": s["adres"], "form": sum(float(rules[AGIRLIK_ANAHTARI[b]]) * bilesen[b] for b in BILESENLER), "bilesenler": bilesen,
                       "kopya_getiri_7g": s.get("kopya_getiri_7g"), "max_kaldirac": s.get("max_kaldirac"), "kopya_gunluk": s.get("kopya_gunluk")})
    puanli.sort(key=lambda p: (-p["form"], p["adres"]))
    return puanli, soguyanlar


def korelasyon(satirlar: list[dict]) -> dict:
    """Günlük kopya getirisi korelasyon matrisi (Pearson) — `satirlar` = [{adres, kopya_gunluk}] (aynı gün sayısı). Sabit seri / <2 gün → None. Canlı motor §6 'benzer trader ≥ 0,7' kuralını uygular."""
    adresler = [s["adres"] for s in satirlar]
    seriler = [np.asarray(s.get("kopya_gunluk") or [], dtype=float) for s in satirlar]

    def r(a: np.ndarray, b: np.ndarray) -> float | None:
        if len(a) != len(b) or len(a) < 2 or np.std(a) < 1e-15 or np.std(b) < 1e-15:
            return None
        return float(np.corrcoef(a, b)[0, 1])

    return {"adresler": adresler, "gun_sayisi": len(seriler[0]) if seriler else 0,
            "matris": [[1.0 if i == j and r(seriler[i], seriler[j]) is not None else r(seriler[i], seriler[j]) for j in range(len(seriler))] for i in range(len(seriler))]}
