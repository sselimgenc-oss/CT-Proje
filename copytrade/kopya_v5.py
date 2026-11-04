"""Kopya hesap v5 (K‑28) = v4 risk katmanı + TEK boyutlandırma (`boyut.hedef_emir`, RADAR_V1.md §5b) — sabit tutar eğrisi YERİNE.

v3/v4 silinmez / değişmez (kural 6). Aynı `defter.copy_ledger`: tek fark dolumun kopyaya etkisini `boyutlayici` (aşağıda) belirler; o da yalnız `boyut.hedef_emir`'i çağırır
(R1/6 kopya testi ve canlı motor aynı sayıyı görür). Birim: kopya kasası (`kasa_usd`, varsayılan `canli_kasa_usd`) — getiri = net / kasa; slot = kasa / N (`boyut.slot_usd`).
`trader_hesap_usd`: oranın paydası (trader hesap değeri, trader_$; radar taramasında lider tablosundaki `accountValue`)."""
from __future__ import annotations

import pandas as pd

from copytrade import boyut, kopya_v3, kopya_v4
from copytrade.kurallar import load_rules

EPS = 1e-12


def boyutlayici(trader_hesap_usd: float, slot: float, rules: dict, kayit: list | None = None):
    """`copy_ledger(boyutlayici=…)` için geri çağrı. Defter birimi = coin / kasa; dönüş: dolumun kopyaya işaretli etkisi (aynı birim). Ters dönüş = kapanış + yeni açılış.
    `kayit` verilirse her karar `(coin_yok, eylem, neden, emir_usd)` olarak eklenir (rapor; hesabı değiştirmez)."""

    def isle(sign, signed, before_leader, own, price, when, held, entry, market, realized, base_usd):
        sonra = before_leader + signed                      # trader'ın dolum sonrası işaretli pozisyonu (coin)
        biz_usd = abs(own) * price * base_usd
        birim = lambda usd: usd / price / base_usd           # noqa: E731 — $ -> defter birimi (işaretsiz)
        sonuc = 0.0
        acilacak = None                                       # taze açılışa kalan trader pozisyonu
        if before_leader * signed < 0:                       # azaltma / kapanış / ters dönüş
            kapanis = abs(sonra) < EPS or sonra * before_leader < 0
            if own * before_leader > 0:                      # kopyada aynı yönde pozisyon var
                eylem = "kapat" if kapanis else "azalt"
                emir, neden = boyut.hedef_emir(eylem, before_leader, 0.0 if kapanis else sonra, trader_hesap_usd, biz_usd, slot, price, rules)
                sonuc += sign * birim(emir)
                if kayit is not None:
                    kayit.append((eylem, neden, emir))
            if sonra * before_leader < 0:                    # ters dönüş: kalan yeni açılış
                acilacak = sonra
        elif abs(own) < EPS or abs(before_leader) < EPS:     # taze açılış (miras pozisyona ekleme dahil: defterin v3 davranışı)
            acilacak = sonra
        else:                                                # ekleme (artış)
            emir, neden = boyut.hedef_emir("artir", before_leader, sonra, trader_hesap_usd, biz_usd, slot, price, rules)
            if kayit is not None:
                kayit.append(("artir", neden, emir))
            return sign * birim(emir)
        if acilacak is not None:
            emir, neden = boyut.hedef_emir("ac", 0.0, acilacak, trader_hesap_usd, 0.0, slot, price, rules)
            if kayit is not None:
                kayit.append(("ac", neden, emir))
            sonuc += sign * birim(emir)
        return sonuc

    return isle


def hesapla(fills: list[dict], saatlik: dict[str, list[dict]], isaret: dict[str, list[dict]], yurutme: dict[str, dict[int, float]], funding: list[dict],
            t0: pd.Timestamp, now: pd.Timestamp, delay: int, style: str, rules: dict | None = None, azami_kaldirac: dict[str, float] | None = None,
            trader_hesap_usd: float = 0.0, kasa_usd: float | None = None, kayit: list | None = None) -> dict:
    """v5 sanal kopya sonucu (kasa ölçeğinde): v3/v4 alanları + `surum: v5`, `kasa_usd`, `slot_usd`. `delay` 0 = ayna (trader'ın dolum fiyatı; `kopya_v3.hesapla` H1 yolu)."""
    rules = rules or load_rules()
    kasa = float(rules["canli_kasa_usd"] if kasa_usd is None else kasa_usd)
    slot = boyut.slot_usd(kasa, rules)
    lim = kopya_v4.limitler(rules, azami_kaldirac)
    sonuc = kopya_v3.hesapla(fills, saatlik, isaret, yurutme, funding, t0, now, delay, style, rules, risk_limitleri=lim, surum="v5",
                             base_usd=kasa, boyutlayici=boyutlayici(float(trader_hesap_usd), slot, rules, kayit))
    if sonuc.get("durum") != "hesaplanamadi":
        sonuc.update({"kasa_usd": kasa, "slot_usd": slot})
    return sonuc
