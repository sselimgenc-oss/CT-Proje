"""Salt kayıt/uyarı hesapları (işlem etkisi yok): alınmayan sinyal (counterfactual) K/Z'si ve kopya drift'i. Saf fonksiyonlar; emir/karar yoluna girmez."""
from __future__ import annotations


def hayali_pnl(yon: str, usd: float, giris: float, mark: float) -> float:
    """Hayali pozisyon K/Z ($): `usd` giriş nosyoneli, `yon` B (uzun) / A (kısa). Geçersiz fiyat → 0."""
    if giris <= 0 or mark <= 0:
        return 0.0
    return usd * (mark / giris - 1.0) * (1.0 if yon == "B" else -1.0)


def drift_orani(biz_usd: float, ideal_usd: float, taban_usd: float) -> float:
    """|biz − ideal| / max(|ideal|, taban); işaretli nosyoneller ($, uzun +/kısa −)."""
    return abs(biz_usd - ideal_usd) / max(abs(ideal_usd), taban_usd, 1e-9)
