"""Tek boyutlandırma (K‑28; `docs/RADAR_V1.md` §5/§5b): kopya pozisyonunun boyutu TEK yerde hesaplanır. Saf fonksiyonlar (ağ yok).

Hem R1/6 kopya testi (`kopya_v5`) hem canlı motor (T4) bu modülü çağırır; kural 7: aynı hesap ikinci bir yerde yazılmaz.
Birimler: `*_usd` = kasa ölçeğinde $ (kopya_$ = sanal/gerçek kopya kasası), `trader_hesap_usd` / trader pozisyon nosyoneli = trader_$ ölçeğinde $.
"""
from __future__ import annotations

import math

from copytrade.kurallar import load_rules

EPS = 1e-9


def saha_sayisi(kasa_usd: float, rules: dict | None = None) -> int:
    """N = min(`radar_saha_max`, taban(kasa / `radar_canli_slot_min_usd`)). Kasa üst sınırı aşarsa / slot kurulamıyorsa ValueError.
    Üst sınır = max(`canli_kasa_ust_usd`, `canli_sanal_kasa_ust_usd`) (K-66: sanal 10.000 $ boyutlanabilsin); GERÇEK kipin 1.000 $ sınırı motorda (`motor.kasa_ust`, `kasa_belirle`) ayrıca uygulanır."""
    rules = rules or load_rules()
    kasa = float(kasa_usd)
    ust = max(float(rules["canli_kasa_ust_usd"]), float(rules.get("canli_sanal_kasa_ust_usd", 0.0) or 0.0))
    if not math.isfinite(kasa) or kasa <= 0 or kasa > ust + EPS:
        raise ValueError(f"kasa 0 < kasa <= {ust:g} olmalı: {kasa_usd}")
    n = min(int(rules["radar_saha_max"]), int(math.floor(kasa / float(rules["radar_canli_slot_min_usd"]) + EPS)))
    if n < 1:
        raise ValueError(f"kasa {kasa} $ < slot alt sınırı {rules['radar_canli_slot_min_usd']} $")
    return n


def radar_kasa(rules: dict | None = None, kasa_usd: float | None = None) -> float:
    """D-01 (14.11 denetim, K-66): radar oynatma kasası ($; tarama, kadro, isabet). Öncelik: verilen `kasa_usd` (CLI) → `radar_kasa_usd` (motorun sanal kasasıyla aynı, 10.000 $)
    → eski `canli_kasa_usd`. Gerçek para anlamı yoktur; `canli_kasa_usd` (gerçek kip, ≤ 1.000 $) değişmez."""
    rules = rules or load_rules()
    if kasa_usd is not None:
        return float(kasa_usd)
    return float(rules.get("radar_kasa_usd") or rules["canli_kasa_usd"])


def slot_usd(kasa_usd: float | None = None, rules: dict | None = None) -> float:
    """Slot kasası = kasa / N (kasa verilmezse `canli_kasa_usd`)."""
    rules = rules or load_rules()
    kasa = float(rules["canli_kasa_usd"] if kasa_usd is None else kasa_usd)
    return kasa / saha_sayisi(kasa, rules)


def hedef_ham(slot: float, trader_poz: float, fiyat: float, trader_hesap_usd: float) -> float:
    """Kopya hedef nosyoneli ($, tavansız) = slot × trader nosyonel / trader hesap. TEK YER: `hedef_emir` (ac/artir/azalt), motor `hedef_usd` kaydı ve `_hedef_usd` buna dayanır (işlem sırası korunur)."""
    return float(slot) * abs(float(trader_poz)) * float(fiyat) / float(trader_hesap_usd)


def hedef_usd(slot: float, trader_poz: float, fiyat: float, trader_hesap_usd: float, rules: dict) -> float:
    """`hedef_ham` + coin tavanı (`radar_slot_tavan_carpan` × slot)."""
    return min(hedef_ham(slot, trader_poz, fiyat, trader_hesap_usd), float(rules["radar_slot_tavan_carpan"]) * float(slot))


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
    - `azalt` (K‑38, hedef tabanlı): hedef = slot × trader nosyonel(sonra) / trader hesap (coin tavanı 3 × slot); fark = biz − hedef. hedef < minimum ve biz ≥ minimum → tamamı kapat (`kucuk_kalan_kapat`);
      fark ≥ minimum → fark kadar azalt; aksi halde 0 (`min_emir_atlandi`; atlanan azaltma KAYBOLMAZ, hedef tabanlı olduğundan bir sonraki dolumda yakalanır). Trader hesabı bilinmiyorsa eski oransal kural (yedek).
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
        hedef = hedef_ham(slot, sonra, fiyat, trader_hesap_usd)
        neden = "tamam"
        if hedef > tavan + EPS:
            hedef, neden = tavan, "tavan_kirpildi"
        if hedef > kalan + EPS:                                          # slot toplam tavanı (K‑35)
            hedef, neden = kalan, "slot_tavani"
            return (hedef, neden) if hedef >= minimum - EPS else (0.0, "slot_tavani")
        if hedef < minimum - EPS:
            if tavan < minimum - EPS or hedef < float(rules.get("radar_min_emir_yuvarla_alt", 0.0) or 0.0) - EPS:   # K-56 D+: çok küçük hedef açılmaz (şişme ≤ 2×)
                return 0.0, "min_emir_atlandi"
            return (minimum, "min_emir_yuvarlandi") if kalan >= minimum - EPS else (0.0, "slot_tavani")
        return hedef, neden
    if eylem == "artir":
        # K‑36: hedef tabanlı. hedef = slot × trader nosyonel(sonra) / trader hesap; coin tavanı; emir = max(0, hedef − mevcut); sonra K‑35 toplam tavanı.
        if trader_hesap_usd <= 0 or fiyat <= 0:
            return 0.0, "hesap_yok"
        hedef = hedef_ham(slot, sonra, fiyat, trader_hesap_usd)
        if hedef > tavan + EPS:
            hedef = tavan
        emir, neden = max(0.0, hedef - biz), "tamam"
        if emir > kalan + EPS:
            emir, neden = kalan, "slot_tavani"
        if emir >= minimum - EPS:
            return emir, neden
        return (0.0, "slot_tavani") if neden == "slot_tavani" else (0.0, "min_emir_atlandi")
    if eylem == "azalt":
        # K‑38 (K‑36'nın simetriği): hedef tabanlı. hedef = slot × trader nosyonel(sonra) / trader hesap (coin tavanı 3 × slot); fark = biz − hedef.
        # hedef < minimum ve biz ≥ minimum → tamamı kapat (kucuk_kalan_kapat); fark ≥ minimum → fark kadar azalt; aksi halde atla (birikir, bir sonraki dolumda yakalanır).
        if trader_hesap_usd <= 0 or fiyat <= 0:                          # hesap bilinmiyor: eski oransal kural (azaltma ATLANMAZ; pozisyonu büyük bırakmak riskli)
            if once <= 0:
                return 0.0, "min_emir_atlandi"
            emir = biz * (once - sonra) / once
            if emir >= minimum - EPS:
                return emir, "azalt_oransal_yedek"                       # lider onayı (05.11): yedek yol SAYILIR (neden_say / kayıt `boyut_neden`)
            return (biz, "azalt_oransal_yedek") if biz - emir < minimum - EPS else (0.0, "min_emir_atlandi")
        hedef = min(hedef_ham(slot, sonra, fiyat, trader_hesap_usd), tavan)
        if hedef < minimum - EPS and biz >= minimum - EPS:
            return biz, "kucuk_kalan_kapat"
        fark = biz - hedef
        if fark >= minimum - EPS:
            return fark, "tamam"
        return 0.0, "min_emir_atlandi"
    raise ValueError(f"bilinmeyen eylem: {eylem}")


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# K-86 (CT yeni plan — motor): CANLI motor boyutlandırması. Radar oynatması (`hedef_emir`) ayrı kalır; motor bu fonksiyonları kullanır. Tüm sayılar `kurallar.yaml` anahtarıdır.
# ---------------------------------------------------------------------------------------------------------------------------------------------------------
def motor_slot(kasa_usd: float, rules: dict | None = None) -> float:
    """Eşit slot = kasa / `canli_slot_sayisi` (5): 1.000 $ → 200 $."""
    rules = rules or load_rules()
    return float(kasa_usd) / int(rules.get("canli_slot_sayisi", 5))


def min_emir_usd(rules: dict, coin: str | None = None) -> float:
    """Sembol başına asgari emir ($; `canli_min_emir_usd` haritası: BTC 100, ETH 20, diğer 5; Binance asgarileri DOĞRULANMADI → `canli_min_emir_dogrulanmadi: true`).
    Harita yoksa eski `radar_min_emir_usd` (yedek)."""
    harita = rules.get("canli_min_emir_usd")
    if not isinstance(harita, dict):
        return float(rules.get("radar_min_emir_usd", 11.0))
    if coin is not None and coin in harita:
        return float(harita[coin])
    return float(harita.get("diger", 5.0))


def min_yuvarla(emir_usd: float, minimum: float) -> tuple[float, str]:
    """K-86 kural 6: hesaplanan emir ≥ minimum → aynen; ≥ minimum/2 ve < minimum → minimuma YUKARI yuvarla (`min_emir_yuvarlandi`); < minimum/2 → emir yok (`min_alti`)."""
    if emir_usd >= minimum - EPS:
        return emir_usd, ""
    if emir_usd >= minimum / 2 - EPS:
        return minimum, "min_emir_yuvarlandi"
    return 0.0, "min_alti"


def motor_hedef_usd(slot: float, trader_poz: float, fiyat: float, trader_hesap_usd: float, rules: dict) -> float:
    """Kopya hedef nosyoneli ($): trader nosyoneli ile orantılı (slot × nosyonel / trader hesap), pozisyon başına tavan `canli_pozisyon_tavan_slot` (1,0) × slot."""
    return min(hedef_ham(slot, trader_poz, fiyat, trader_hesap_usd), float(rules.get("canli_pozisyon_tavan_slot", 1.0)) * float(slot))


def motor_emir(eylem: str, trader_poz_sonra: float, trader_hesap_usd: float, biz_poz_usd: float, slot: float, fiyat: float, rules: dict, biz_slot_toplam_usd: float | None = None,
               coin: str | None = None, azalt_hedef_usd: float | None = None) -> tuple[float, str]:
    """K-86: tek trader olayının bizdeki emir büyüklüğü ($, işaretsiz) ve nedeni.
    - `ac` / `artir`: hedef = `motor_hedef_usd` (trader ile orantılı, pozisyon başına ≤ 1 × slot); `artir` emri = max(0, hedef − mevcut); trader başına TÜM coinler toplamı ≤ `canli_slot_toplam_tavan_carpan` (3) × slot (`slot_tavani`);
      sonra sembol asgarisi (`min_yuvarla`: ≥ yarısı → asgariye yuvarla, altı `min_alti`). Fark/hedef 0 ise `hedefte`.
    - `azalt`: hedef = `azalt_hedef_usd` (trader oranı × yeni trader pozisyonu; çağıran hesaplar); fark = mevcut − hedef; hedef asgarinin altında ve mevcut ≥ asgari → tamamı kapat (`kucuk_kalan_kapat`); aksi halde fark `min_yuvarla`'dan geçer.
    - `kapat`: pozisyonun tamamı."""
    biz = abs(float(biz_poz_usd))
    if eylem == "kapat":
        return biz, "tam_kapanis"
    minimum = min_emir_usd(rules, coin)
    if eylem == "azalt":
        hedef = max(0.0, float(azalt_hedef_usd or 0.0))
        if hedef < minimum - EPS and biz >= minimum - EPS:
            return biz, "kucuk_kalan_kapat"
        fark = biz - hedef
        if fark <= EPS:
            return 0.0, "hedefte"
        emir, neden = min_yuvarla(fark, minimum)
        return (min(emir, biz), neden or "tamam") if emir > 0 else (0.0, neden)
    if trader_hesap_usd <= 0 or fiyat <= 0:
        return 0.0, "hesap_yok"
    toplam = biz if biz_slot_toplam_usd is None else abs(float(biz_slot_toplam_usd))
    kalan = max(0.0, float(rules.get("canli_slot_toplam_tavan_carpan", 3.0)) * float(slot) - toplam)
    hedef = motor_hedef_usd(slot, trader_poz_sonra, fiyat, trader_hesap_usd, rules)
    emir = hedef if eylem == "ac" else max(0.0, hedef - biz)
    if emir <= EPS:
        return 0.0, "hedefte"
    neden = "tamam"
    if emir > kalan + EPS:
        emir, neden = kalan, "slot_tavani"
        if emir < minimum / 2 - EPS:
            return 0.0, "slot_tavani"
    emir2, mn = min_yuvarla(emir, minimum)
    if emir2 <= 0:
        return 0.0, mn
    if mn == "min_emir_yuvarlandi" and emir2 > kalan + EPS:
        return 0.0, "slot_tavani"
    return emir2, mn or neden
