"""Aşırı uydurma (overfitting) ölçüleri — yalnız RAPOR (karar kodu, eşik ve ağırlık değişmez).

1) `pbo`: Backtest aşırı uydurma olasılığı (Bailey, Borwein, López de Prado, Zhu 2015; CSCV = birleşimsel simetrik çapraz doğrulama).
   Girdi: T dönem × N aday yapılandırma getiri matrisi (satır = dönem, sütun = aday). Dönemler S eşit bloğa bölünür (S çift, varsayılan 8);
   her C(S, S/2) bölünmede yarı bloklar "eğitim" (IS), kalanı "sınama" (OOS) olur. IS'te en iyi adayın OOS'taki göreli sırası ω = sıra/(N+1)
   (1 = en kötü), λ = ln(ω/(1-ω)). PBO = λ ≤ 0 olan bölünme payı: "eğitimde seçtiğim aday sınamada medyanın altında kalır mı?".
   Saf gürültüde ≈ 0,5; gerçek üstün bir aday varsa 0'a yakın. Başarı ölçüsü varsayılan Sharpe (ortalama/std; dönem başına, yıllıklandırmasız).
   T < 2·S ise sonuç `yetersiz veri` (hesaplanmaz).
2) `deflated_sharpe`: Deflated Sharpe Oranı (Bailey & López de Prado 2014): çok sayıda aday denendiğinde en iyi Sharpe'ın şansla bu kadar yüksek
   çıkma payı düşülerek gerçek-beceri olasılığı (0-1). Yıllıklandırmasız Sharpe ve aynı dönem birimi kullanılır.

Yalnız numpy + standart kütüphane. Ağ yok.
"""
from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist

import numpy as np

EULER = 0.5772156649015329
YETERSIZ = "yetersiz veri"
_N = NormalDist()


def sharpe_sutun(m: np.ndarray) -> np.ndarray:
    """Sütun başına Sharpe (ortalama / örneklem std, ddof=1). std = 0: ortalama 0 ise 0, değilse ±1e12 (kararlı sıralama için)."""
    m = np.asarray(m, dtype=float)
    ort = m.mean(axis=0)
    sd = m.std(axis=0, ddof=1) if m.shape[0] > 1 else np.zeros(m.shape[1])
    iyi = sd > 1e-15
    return np.where(iyi, ort / np.where(iyi, sd, 1.0), np.sign(ort) * 1e12)


def _ortalama_sira(x: np.ndarray) -> np.ndarray:
    """1..N ortalama sıra (eşitlikte ortalama; 1 = en küçük)."""
    idx = np.argsort(x, kind="stable")
    sira = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[idx[j + 1]] == x[idx[i]]:
            j += 1
        sira[idx[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return sira


def pbo(getiri: np.ndarray, s: int = 8, olcut: str = "sharpe") -> dict:
    """CSCV ile PBO. `getiri`: (T, N). `olcut`: "sharpe" | "ortalama". Döner sözlük:
    `durum` ("tamam" | "yetersiz veri"), `pbo`, `bolunme` (C(S,S/2)), `s`, `n_aday`, `t` (kullanılan dönem), `lambda_medyan`, `oos_sira_ort` (ω ortalaması),
    `is_en_iyi_sayim` (aday başına IS'te en iyi seçilme sayısı). Yetersiz: T < 2·S ya da N < 2 ya da S tek/küçük → pbo None.
    T, S'in katına kırpılır (EN ESKİ dönemler atılır, yeni veri korunur)."""
    m = np.asarray(getiri, dtype=float)
    if m.ndim != 2:
        raise ValueError("getiri 2 boyutlu olmalı (dönem × aday)")
    if not np.all(np.isfinite(m)):
        raise ValueError("getiri matrisi sonlu sayılardan oluşmalı (NaN/Inf yok)")
    if olcut not in ("sharpe", "ortalama"):
        raise ValueError("olcut sharpe | ortalama")
    t_ham, n = m.shape
    if s < 2 or s % 2 or t_ham < 2 * s or n < 2:
        return {"durum": YETERSIZ, "pbo": None, "s": s, "n_aday": n, "t": t_ham, "bolunme": 0,
                "neden": f"T={t_ham} (gerekli ≥ {2 * s}), N={n} (gerekli ≥ 2), S={s} (çift ve ≥ 2 olmalı)"}
    b = t_ham // s
    t = b * s
    m = m[t_ham - t:]                                          # en eski dönemleri at
    bloklar = m.reshape(s, b, n)
    toplam = bloklar.sum(axis=1)                               # (S, N)
    kare = (bloklar ** 2).sum(axis=1)
    kombler = list(combinations(range(s), s // 2))
    isaret = np.zeros((len(kombler), s))
    for i, c in enumerate(kombler):
        isaret[i, list(c)] = 1.0
    yarim = s // 2 * b                                         # IS ve OOS örnek sayısı (eşit)

    def olc(bay: np.ndarray) -> np.ndarray:
        top, kar = bay @ toplam, bay @ kare                    # (C, N)
        ort = top / yarim
        if olcut == "ortalama":
            return ort
        sd = np.sqrt(np.maximum((kar - yarim * ort ** 2) / (yarim - 1), 0.0))
        iyi = sd > 1e-15
        return np.where(iyi, ort / np.where(iyi, sd, 1.0), np.sign(ort) * 1e12)

    is_p, oos_p = olc(isaret), olc(1.0 - isaret)
    lam, omega = [], []
    secim = np.zeros(n, dtype=int)
    for i in range(len(kombler)):
        en_iyi = int(np.argmax(is_p[i]))                       # eşitlikte ilk sütun (belirlenimci)
        secim[en_iyi] += 1
        w = _ortalama_sira(oos_p[i])[en_iyi] / (n + 1)
        omega.append(w)
        lam.append(math.log(w / (1.0 - w)))
    lam_a = np.array(lam)
    return {"durum": "tamam", "pbo": float((lam_a <= 0).mean()), "s": s, "n_aday": n, "t": t, "bolunme": len(kombler), "lambda_medyan": float(np.median(lam_a)),
            "oos_sira_ort": float(np.mean(omega)), "is_en_iyi_sayim": [int(x) for x in secim], "olcut": olcut}


def deflated_sharpe(sr: float, n_deneme: int, sr_varyans: float, t: int, carpiklik: float = 0.0, basiklik: float = 3.0) -> float | None:
    """Deflated Sharpe Oranı (0-1): P(gerçek Sharpe > 0 | `n_deneme` aday denendi, en iyisi `sr`).
    `sr`: en iyi adayın dönem başına (yıllıklandırmasız) Sharpe'ı; `sr_varyans`: adaylar arası Sharpe'ların varyansı; `t`: dönem sayısı; `carpiklik`/`basiklik`: en iyi adayın
    getiri çarpıklığı ve (normal = 3) basıklığı. SR0 = √V · ((1-γ)Φ⁻¹(1-1/N) + γ Φ⁻¹(1-1/(N·e))) (beklenen en büyük Sharpe, şans). Girdi geçersizse (t < 2, N < 1, V < 0,
    kök içi ≤ 0) None. N = 1: şans eşiği 0 (düzeltme yok)."""
    if t < 2 or n_deneme < 1 or sr_varyans < 0:
        return None
    if n_deneme == 1:
        sr0 = 0.0
    else:
        sr0 = math.sqrt(sr_varyans) * ((1 - EULER) * _N.inv_cdf(1 - 1 / n_deneme) + EULER * _N.inv_cdf(1 - 1 / (n_deneme * math.e)))
    payda = 1 - carpiklik * sr + (basiklik - 1) / 4 * sr ** 2
    if payda <= 0:
        return None
    return float(_N.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(payda)))


def deflated_sharpe_matris(getiri: np.ndarray) -> dict:
    """Matrisin (T, N) en yüksek Sharpe'lı sütunu için DSR: tüm sütunlar "denenen aday" sayılır. Döner {`sutun`, `sr`, `n_deneme`, `sr_varyans`, `dsr`};
    T < 4 ya da N < 2 → dsr None."""
    m = np.asarray(getiri, dtype=float)
    t, n = m.shape
    if t < 4 or n < 2:
        return {"sutun": None, "sr": None, "n_deneme": n, "sr_varyans": None, "dsr": None}
    sr = sharpe_sutun(m)
    k = int(np.argmax(sr))
    x = m[:, k]
    sd = float(x.std())
    z = (x - x.mean()) / sd if sd > 1e-15 else np.zeros_like(x)
    var = float(np.var(sr, ddof=1))
    dsr = deflated_sharpe(float(sr[k]), n, var, t, float((z ** 3).mean()), float((z ** 4).mean()) if sd > 1e-15 else 3.0)
    return {"sutun": k, "sr": float(sr[k]), "n_deneme": n, "sr_varyans": var, "dsr": dsr}
