"""Mutabakat (görev T4 §1): gerçek kipte HL `clearinghouseState` ↔ bizim defter; sanal kipte defter ↔ mark tutarlılığı. SAF karşılaştırma fonksiyonları (ağ çağrısı motorda).

Fark eşiği: |bizim − HL| nosyoneli > kasa × `canli_mutabakat_oran` (1 %; kasa 1.000 $ iken 10 $ ≈ en küçük emir) → alarm + yeni açılış durur (yetim pozisyon / kaçak).
"""
from __future__ import annotations

from typing import Any


def poz_farki(bizim: dict[str, float], hl: dict[str, float], marks: dict[str, float], kasa_usd: float, oran: float) -> list[dict]:
    """Coin başına işaretli miktar farkı. `bizim`/`hl`: {coin: işaretli sz}. Fark nosyoneli (`|Δsz| × mark`) kasa × oran'ı aşanlar döner; mark yoksa farkın kendisi 'mark_yok' ile işaretlenir (uydurma fiyat yok)."""
    sonuc = []
    for coin in sorted({*bizim, *hl}):
        fark = float(hl.get(coin, 0.0)) - float(bizim.get(coin, 0.0))
        if abs(fark) < 1e-12:
            continue
        mark = marks.get(coin)
        if not mark:
            sonuc.append({"coin": coin, "fark_sz": fark, "fark_usd": None, "neden": "mark_yok", "bizim": bizim.get(coin, 0.0), "hl": hl.get(coin, 0.0)})
            continue
        usd = abs(fark) * mark
        if usd > float(kasa_usd) * float(oran):
            sonuc.append({"coin": coin, "fark_sz": fark, "fark_usd": usd, "neden": "yetim" if coin not in bizim else ("eksik" if coin not in hl else "fark"),
                          "bizim": bizim.get(coin, 0.0), "hl": hl.get(coin, 0.0)})
    return sonuc


def sanal_tutarlilik(hesap: Any, marks: dict[str, float], mark_zamani: dict[str, int], simdi_ms: int, stale_sn: float) -> list[dict]:
    """Sanal kip: (1) açık pozisyonu olan her coinin mark fiyatı taze mi, (2) başlangıç marjı toplamı özsermayeyi aşmıyor mu (marj yetersizliği = defter hatası), (3) NaN/negatif yok."""
    sorunlar = []
    for adres, coinler in hesap.poz.items():
        for coin, p in coinler.items():
            yas = simdi_ms - mark_zamani.get(coin, 0)
            if coin not in marks or yas > stale_sn * 1000:
                sorunlar.append({"neden": "mark_eski", "coin": coin, "yas_sn": None if coin not in marks else yas / 1000})
    oz = hesap.ozsermaye(marks)
    if not (oz == oz) or hesap.marj_toplam() > max(oz, 0.0) + 1e-6:
        sorunlar.append({"neden": "marj_yetersiz", "marj": hesap.marj_toplam(), "ozsermaye": oz})
    return sorunlar
