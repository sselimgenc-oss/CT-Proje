"""Kopya hesap v5 (K‑28) = v4 risk katmanı + TEK boyutlandırma (`boyut.hedef_emir`, RADAR_V1.md §5b) — sabit tutar eğrisi YERİNE.

v3/v4 silinmez / değişmez (kural 6). Aynı `defter.copy_ledger`: tek fark dolumun kopyaya etkisini `boyutlayici` (aşağıda) belirler; o da yalnız `boyut.hedef_emir`'i çağırır
(R1/6 kopya testi ve canlı motor aynı sayıyı görür). Birim: kopya kasası (`kasa_usd`, varsayılan `canli_kasa_usd`) — getiri = net / kasa; slot = kasa / N (`boyut.slot_usd`).
`trader_hesap_usd`: oranın paydası (trader hesap değeri, trader_$): sabit sayı (eski: radar koşu anındaki lider tablosu `accountValue`) YA DA zamana bağlı payda
(B8, 08.11 seçim denetimi: `PaydaSerisi` — her emir, yürütme anındaki (≤ o an son bilinen) trader hesap değerine oranlanır; canlı motor da o anki hesap değerini kullanır)."""
from __future__ import annotations

import bisect
import math
from typing import Any, Callable

import pandas as pd

from copytrade import boyut, kopya_v3, kopya_v4
from copytrade.kurallar import load_rules
from copytrade.olcut import is_hip3

EPS = 1e-12


class PaydaSerisi:
    """Zamana bağlı trader hesap değeri (trader_$; B8). `noktalar` = [(UTC ms, $)]; değeri ≤ 0 / sayı olmayan nokta atılır. `deger(t)` = t anında ya da öncesindeki SON nokta
    (nedensel: canlı motor da önbellekteki son okumayı kullanır); t ilk noktadan önceyse ilk nokta. Boş seri kurulamaz (ValueError) — çağıran sabit paydaya düşer."""

    def __init__(self, noktalar: list[tuple[int, float]]):
        temiz = sorted((int(t), float(v)) for t, v in noktalar if v is not None and math.isfinite(float(v)) and float(v) > 0)
        if not temiz:
            raise ValueError("payda serisi boş")
        self.zaman = [t for t, _ in temiz]
        self.deger_ = [v for _, v in temiz]

    def __call__(self, t: int) -> float:
        i = bisect.bisect_right(self.zaman, int(t)) - 1
        return self.deger_[max(i, 0)]

    def __len__(self) -> int:
        return len(self.zaman)


def payda_fonk(trader_hesap_usd: float | Callable[[int], float]) -> Callable[[int], float]:
    """Sabit sayı → her zaman aynı değer (eski davranış, birebir); çağrılabilir (`PaydaSerisi`) → aynen."""
    if callable(trader_hesap_usd):
        return trader_hesap_usd
    sabit = float(trader_hesap_usd)
    return lambda _t: sabit


def _slot_toplam_usd(held: dict, entry: dict, market: Any, when: int, coin: str, price: float, base_usd: float) -> float:
    """Kopyanın TÜM coinlerdeki brüt nosyoneli ($): bu coin yürütme fiyatında, diğerleri mark (yoksa giriş) fiyatında."""
    toplam = 0.0
    for c, q in held.items():
        if abs(q) > EPS:
            mk = price if c == coin else (market.mark(c, when) or entry.get(c) or price)
            toplam += abs(q) * mk * base_usd
    return toplam


def boyutlayici(trader_hesap_usd: float | Callable[[int], float], slot: float, rules: dict, kayit: list | None = None, toplam_tavan: bool = True):
    """`copy_ledger(boyutlayici=…)` için geri çağrı. Defter birimi = coin / kasa; dönüş: dolumun kopyaya işaretli etkisi (aynı birim). Ters dönüş = kapanış + yeni açılış.
    `trader_hesap_usd`: sabit payda ya da `PaydaSerisi` (B8: yürütme anı `when`'deki değer). `kayit` verilirse her karar `(eylem, neden, emir_usd)` olarak eklenir (rapor; hesabı değiştirmez). `toplam_tavan=False`: K‑35 öncesi coin başına tavan (YALNIZ önce/sonra karşılaştırması için; üretimde True)."""

    payda = payda_fonk(trader_hesap_usd)

    def isle(sign, signed, before_leader, own, price, when, held, entry, market, realized, base_usd, coin=""):
        trader_hesap = payda(when)                          # B8: emir anındaki trader hesap değeri (sabit paydada hep aynı sayı)
        sonra = before_leader + signed                      # trader'ın dolum sonrası işaretli pozisyonu (coin)
        biz_usd = abs(own) * price * base_usd
        toplam_usd = _slot_toplam_usd(held, entry, market, when, coin, price, base_usd) if toplam_tavan else None
        birim = lambda usd: usd / price / base_usd           # noqa: E731 — $ -> defter birimi (işaretsiz)
        sonuc = 0.0
        acilacak = None                                       # taze açılışa kalan trader pozisyonu
        if before_leader * signed < 0:                       # azaltma / kapanış / ters dönüş
            kapanis = abs(sonra) < EPS or sonra * before_leader < 0
            if own * before_leader > 0:                      # kopyada aynı yönde pozisyon var
                eylem = "kapat" if kapanis else "azalt"
                emir, neden = boyut.hedef_emir(eylem, before_leader, 0.0 if kapanis else sonra, trader_hesap, biz_usd, slot, price, rules, toplam_usd)
                sonuc += sign * birim(emir)
                if kayit is not None:
                    kayit.append((eylem, neden, emir))
            if sonra * before_leader < 0:                    # ters dönüş: kalan yeni açılış
                acilacak = sonra
                if toplam_usd is not None and own * before_leader > 0:
                    toplam_usd -= biz_usd                    # eski yön tamamen kapanıyor: yeni açılışın tavan hesabında sayılmaz
        elif abs(own) < EPS or abs(before_leader) < EPS:     # taze açılış (miras pozisyona ekleme dahil: defterin v3 davranışı)
            acilacak = sonra
        else:                                                # ekleme (artış)
            emir, neden = boyut.hedef_emir("artir", before_leader, sonra, trader_hesap, biz_usd, slot, price, rules, toplam_usd)
            if kayit is not None:
                kayit.append(("artir", neden, emir))
            return sign * birim(emir)
        if acilacak is not None:
            emir, neden = boyut.hedef_emir("ac", 0.0, acilacak, trader_hesap, 0.0, slot, price, rules, toplam_usd)
            if kayit is not None:
                kayit.append(("ac", neden, emir))
            sonuc += sign * birim(emir)
        return sonuc

    return isle


def hip3_ayikla(fills: list[dict], hip3_kopya: bool) -> list[dict]:
    """K‑43 adayı (deneme seçeneği): `hip3_kopya=False` ise HIP‑3 (`olcut.is_hip3`: `dex:COIN`) dolumları atılır. HIP‑3 pozisyonu kopyada hiç açılmadığı için
    kapanış/azaltma dolumları da (motor K‑42'deki gibi) oynatmada karşılıksızdır: HIP‑3 dolumlarının TAMAMI atlanır. `True` = bugünkü davranış (liste aynen)."""
    return list(fills) if hip3_kopya else [f for f in fills if not is_hip3(str(f.get("coin", "")))]


def hesapla(fills: list[dict], saatlik: dict[str, list[dict]], isaret: dict[str, list[dict]], yurutme: dict[str, dict[int, float]], funding: list[dict],
            t0: pd.Timestamp, now: pd.Timestamp, delay: int, style: str, rules: dict | None = None, azami_kaldirac: dict[str, float] | None = None,
            trader_hesap_usd: float | Callable[[int], float] = 0.0, kasa_usd: float | None = None, kayit: list | None = None, k35: bool = True, hip3_kopya: bool | None = None) -> dict:
    """v5 sanal kopya sonucu (kasa ölçeğinde): v3/v4 alanları + `surum: v5`, `kasa_usd`, `slot_usd`. `delay` 0 = ayna (trader'ın dolum fiyatı; `kopya_v3.hesapla` H1 yolu).
    `k35=False`: K‑35 ÖNCESİ davranış (v4 emir/trader tavanı açık, slot tavanı coin başına) — yalnız önce/sonra karşılaştırması için; üretimde True.
    `hip3_kopya` (K‑43 adayı, yalnız deneme): None = `rules["radar_hip3_kopya"]` (varsayılan true = HIP‑3 dolumları da kopyalanır, bugünkü davranış); False = HIP‑3 dolumları oynatmadan çıkar (`hip3_ayikla`)."""
    rules = rules or load_rules()
    fills = hip3_ayikla(fills, bool(rules.get("radar_hip3_kopya", True)) if hip3_kopya is None else hip3_kopya)
    kasa = float(rules["canli_kasa_usd"] if kasa_usd is None else kasa_usd)
    slot = boyut.slot_usd(kasa, rules)
    lim = kopya_v4.limitler(rules, azami_kaldirac)
    if k35:
        # K‑35: v4'ün eski sabit tutar sınırları (emir başına 100 $, trader başına toplam 200 $; referans kasa 1.000 $) v5'te KALKAR: yerini `boyut` slot tavanı (3 × slot, tüm coinler) alır.
        # Aksi halde toplam 200 $'da takılır, canlı motor 272,7 $'a kadar açar ve R1/6 canlıdan farklı sayı görürdü. HL azami kaldıraç / teminat sınırı (`azami_kaldirac`) KALIR.
        lim = {**lim, "emir_tavan_usd": 1e12, "trader_tavan_usd": 1e12}
    sonuc = kopya_v3.hesapla(fills, saatlik, isaret, yurutme, funding, t0, now, delay, style, rules, risk_limitleri=lim, surum="v5",
                             base_usd=kasa, boyutlayici=boyutlayici(trader_hesap_usd if callable(trader_hesap_usd) else float(trader_hesap_usd), slot, rules, kayit, k35))
    if sonuc.get("durum") != "hesaplanamadi":
        sonuc.update({"kasa_usd": kasa, "slot_usd": slot})
    return sonuc
