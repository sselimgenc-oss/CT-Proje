"""Tek boyutlandırma (K‑28; `docs/RADAR_V1.md` §5/§5b): kopya pozisyonunun boyutu TEK yerde hesaplanır. Saf fonksiyonlar (ağ yok).

Hem R1/6 kopya testi (`kopya_v5`) hem canlı motor (T4) bu modülü çağırır; kural 7: aynı hesap ikinci bir yerde yazılmaz.
Birimler: `*_usd` = kasa ölçeğinde $ (kopya_$ = sanal/gerçek kopya kasası), `trader_hesap_usd` / trader pozisyon nosyoneli = trader_$ ölçeğinde $.
"""
from __future__ import annotations

import math

from copytrade.kurallar import load_rules

EPS = 1e-9


def saha_sayisi(kasa_usd: float, rules: dict | None = None) -> int:
    """N = min(`radar_saha_max`, taban(kasa / `radar_canli_slot_min_usd`)). Kasa `canli_kasa_ust_usd`'yi aşarsa / slot kurulamıyorsa ValueError."""
    rules = rules or load_rules()
    kasa = float(kasa_usd)
    if not math.isfinite(kasa) or kasa <= 0 or kasa > float(rules["canli_kasa_ust_usd"]) + EPS:
        raise ValueError(f"kasa 0 < kasa <= {rules['canli_kasa_ust_usd']} olmalı: {kasa_usd}")
    n = min(int(rules["radar_saha_max"]), int(math.floor(kasa / float(rules["radar_canli_slot_min_usd"]) + EPS)))
    if n < 1:
        raise ValueError(f"kasa {kasa} $ < slot alt sınırı {rules['radar_canli_slot_min_usd']} $")
    return n


def slot_usd(kasa_usd: float | None = None, rules: dict | None = None) -> float:
    """Slot kasası = kasa / N (kasa verilmezse `canli_kasa_usd`)."""
    rules = rules or load_rules()
    kasa = float(rules["canli_kasa_usd"] if kasa_usd is None else kasa_usd)
    return kasa / saha_sayisi(kasa, rules)


def hedef_emir(eylem: str, trader_poz_once: float, trader_poz_sonra: float, trader_hesap_usd: float, biz_poz_usd: float, slot: float, fiyat: float,
               rules: dict | None = None, biz_slot_toplam_usd: float | None = None) -> tuple[float, str]:
    """§5b: tek bir trader dolumunun bizdeki emir BÜYÜKLÜĞÜ ($, işaretsiz; yönü çağıran bilir) ve nedeni.

    `eylem`: `ac` (taze açılış; trader sonrası pozisyonu `trader_poz_sonra`, coin birimi, işaretli) · `artir` · `azalt` · `kapat` (trader tam kapanış).
    `trader_poz_*`: trader'ın o coindeki işaretli pozisyonu (coin birimi) dolumdan önce / sonra; `biz_poz_usd`: bizim pozisyonumuzun $ büyüklüğü (işaretsiz);
    `slot`: slot kasası ($); `fiyat`: yürütme fiyatı; `biz_slot_toplam_usd`: bu trader'ın TÜM coinlerdeki kopya nosyoneli toplamı ($, K‑35; verilmezse yalnız bu coinin `biz_poz_usd`'ü — eski coin başına davranış).
    - `ac`: slot × (trader nosyonel / trader hesap), tek emir tavanı `radar_slot_tavan_carpan` × slot; **slot toplam tavanı (K‑35, RADAR §6 "slot başına 3,0x"):** trader'ın tüm coinlerdeki toplamı ≤ çarpan × slot, aşan kısım kırpılır (`slot_tavani`;
      kalan < `radar_min_emir_usd` ise 0). Hedef < minimum ise: tavandan kalan ≥ minimum → minimum'a yuvarlanır (`min_emir_yuvarlandi`), değilse 0 (`min_emir_atlandi` / kalan yetmiyorsa `slot_tavani`).
    - `artir` (K‑36, hedef tabanlı): hedef = slot × trader nosyonel(sonra) / trader hesap, coin tavanı 3 × slot; emir = max(0, hedef − mevcut); sonra K‑35 toplam tavanı
      (`slot_tavani`); emir < minimum → 0 (`min_emir_atlandi`); hesap/fiyat ≤ 0 → 0 (`hesap_yok`).
    - `azalt`: bizim pozisyon × trader'ın azaltma oranı; < minimum ise kalan < minimum → tamamı kapat (`kucuk_kalan_kapat`), değilse 0 (`min_emir_atlandi`).
    - `kapat`: bizim pozisyonun tamamı (trader tam kapattı)."""
    rules = rules or load_rules()
    minimum, tavan = float(rules["radar_min_emir_usd"]), float(rules["radar_slot_tavan_carpan"]) * float(slot)
    biz = abs(float(biz_poz_usd))
    once, sonra = abs(float(trader_poz_once)), abs(float(trader_poz_sonra))
    if eylem == "kapat":
        return biz, "tam_kapanis"
    toplam = biz if biz_slot_toplam_usd is None else abs(float(biz_slot_toplam_usd))
    kalan = max(0.0, tavan - toplam)
    if eylem == "ac":
        if trader_hesap_usd <= 0 or fiyat <= 0:
            return 0.0, "hesap_yok"
        hedef = float(slot) * sonra * float(fiyat) / float(trader_hesap_usd)
        neden = "tamam"
        if hedef > tavan + EPS:
            hedef, neden = tavan, "tavan_kirpildi"
        if hedef > kalan + EPS:                                          # slot toplam tavanı (K‑35)
            hedef, neden = kalan, "slot_tavani"
            return (hedef, neden) if hedef >= minimum - EPS else (0.0, "slot_tavani")
        if hedef < minimum - EPS:
            if tavan < minimum - EPS:
                return 0.0, "min_emir_atlandi"
            return (minimum, "min_emir_yuvarlandi") if kalan >= minimum - EPS else (0.0, "slot_tavani")
        return hedef, neden
    if eylem == "artir":
        # K‑36: hedef tabanlı. hedef = slot × trader nosyonel(sonra) / trader hesap; coin tavanı; emir = max(0, hedef − mevcut); sonra K‑35 toplam tavanı.
        if trader_hesap_usd <= 0 or fiyat <= 0:
            return 0.0, "hesap_yok"
        hedef = float(slot) * sonra * float(fiyat) / float(trader_hesap_usd)
        if hedef > tavan + EPS:
            hedef = tavan
        emir, neden = max(0.0, hedef - biz), "tamam"
        if emir > kalan + EPS:
            emir, neden = kalan, "slot_tavani"
        if emir >= minimum - EPS:
            return emir, neden
        return (0.0, "slot_tavani") if neden == "slot_tavani" else (0.0, "min_emir_atlandi")
    if eylem == "azalt":
        if once <= 0:
            return 0.0, "min_emir_atlandi"
        emir = biz * (once - sonra) / once
        if emir >= minimum - EPS:
            return emir, "tamam"
        return (biz, "kucuk_kalan_kapat") if biz - emir < minimum - EPS else (0.0, "min_emir_atlandi")
    raise ValueError(f"bilinmeyen eylem: {eylem}")
