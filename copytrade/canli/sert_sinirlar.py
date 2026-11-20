"""Gerçek para SERT sınırları (K-72, kullanıcı kararı 19.11): koda gömülüdür; yanlış `kurallar.yaml` bunları AŞAMAZ.

Yalnız GERÇEK kipte geçerlidir; sanal kip (kendi `canli_sanal_kasa_ust_usd` sınırı) etkilenmez.
- Kasa üst sınırı 1.500 $ (etkin sınır = min(yaml `canli_kasa_ust_usd`, bu sabit)).
- Günlük kayıp oranı ≤ 0,05: yaml'daki `canli_gunluk_kayip_oran` bunu aşarsa gerçek kip BAŞLAMAZ (açık hata).
- Marj kaldıracı `canli_marj_kaldirac` ∈ [1, 5]: dışındaysa gerçek kip BAŞLAMAZ. (K-67 `canli_min_azami_kaldirac` ayrı şeydir: coin filtresi.)
- `canli_hl_deger_ust_usd` (HL hesap değeri açılış tavanı) kasa sınırı DEĞİLDİR: kârlı günden sonra yeniden başlatma takılmasın diye
  kasa sınırından büyük olabilir; etkin kasa yine min(CANLI_KASA_USD, HL) ≤ kasa sınırı. Ayrı sert sınır konmadı.
"""
from __future__ import annotations

import math

GERCEK_KASA_UST_USD = 1500.0     # $ (K-72; önceki 1.000 $, kullanıcı 19.11'de yükseltti)
GUNLUK_KAYIP_UST_ORAN = 0.05     # oran (gün başı özsermayeden kayıp)
KALDIRAC_ALT = 1                 # x
KALDIRAC_UST = 5                 # x (CT 3x kalır; K-74 dinamik stop: stop oranı = min(üst, tasfiye mesafesi − pay), yani stoplar tasfiyeden ÖNCE kalır; 5x izole tasfiye mesafesi ≈ %17-19)


def etkin_kasa_ust(rules: dict) -> float:
    """Gerçek kip kasa üst sınırı ($) = min(yaml, sert sabit)."""
    return min(float(rules["canli_kasa_ust_usd"]), GERCEK_KASA_UST_USD)


def gercek_kip_dogrula(rules: dict) -> None:
    """Gerçek kip başlangıç denetimi: yaml sert sınırı aşıyorsa ValueError (çağıran KipHatasi'na çevirir). Eksik anahtar atlanır (kendi yükleyicisi yakalar)."""
    ust = rules.get("canli_kasa_ust_usd")
    if ust is not None and (not math.isfinite(float(ust)) or float(ust) > GERCEK_KASA_UST_USD + 1e-9):
        raise ValueError(f"canli_kasa_ust_usd {ust} $ > sert sınır {GERCEK_KASA_UST_USD:g} $ (K-72)")
    gk = rules.get("canli_gunluk_kayip_oran")
    if gk is not None and (not math.isfinite(float(gk)) or float(gk) > GUNLUK_KAYIP_UST_ORAN + 1e-12):
        raise ValueError(f"canli_gunluk_kayip_oran {gk} > sert sınır {GUNLUK_KAYIP_UST_ORAN:g} (K-72)")
    k = rules.get("canli_marj_kaldirac")
    if k is not None and (not math.isfinite(float(k)) or not KALDIRAC_ALT <= float(k) <= KALDIRAC_UST):
        raise ValueError(f"canli_marj_kaldirac {k} x, [{KALDIRAC_ALT}, {KALDIRAC_UST}] x dışında (K-72)")
