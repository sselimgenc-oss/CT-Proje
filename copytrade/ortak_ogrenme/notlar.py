# Kaynak: sselimgenc-oss/SG-Github-AB-proje trader/paket/ortak_ogrenme/notlar.py @ af68a02 (kopya; değiştirme, güncelleme kaynaktan)
"""Kodla yazilan islem notu (spec bolum 2). ML trader_core/trade_notes.py mantiginin Aday uzerindeki hali.

Ag yok, rastgelelik yok. Etiketler islem SONRASI bilgidir (hedef/olcum), ozellik degildir.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from .kayit import Aday

TAG_VOCAB: dict[str, tuple[str, ...]] = {
    "giris": ("iyi", "kotu_dolum"),
    "stop": ("dar", "normal", "genis"),
    "seans": ("open", "closed", "weekend", "yok"),
    "rejim": ("trend_up", "trend_down", "range", "volatile", "unclear"),
    "olay": ("bilinmiyor",),
    "uyum": ("uyumlu", "uyumsuz"),
    "kacinilabilir": ("evet", "hayir"),
    "sonuc": ("kazanc", "kayip", "basabas"),
}
LESSON_CODES = ("seans_kapali", "yuksek_vol", "dusuk_rr")
LESSON_PREFIX = "ders:"
TAG_CATEGORIES = tuple(TAG_VOCAB) + ("ders",)

HIGH_VOL_ATR_RATIO = 1.3
LOW_RR = 2.0
KAYMA_ESIGI = 0.10          # giris kaymasi / risk orani
STOP_DAR_ATR = 1.0
STOP_GENIS_ATR = 3.0
UYUM_TABLOSU: dict[str, tuple[str, ...]] = {"R1": ("range",), "T1": ("trend_up", "trend_down")}
EPS = 1e-9


def _sayi(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def ders_kimligi(kod: str, kurulum: str) -> str:
    return f"{kod}:{kurulum}"


def valid_tag(tag: Any) -> bool:
    if not isinstance(tag, str) or ":" not in tag:
        return False
    cat, val = tag.split(":", 1)
    if cat == "ders":
        code, _, setup = val.partition(":")
        return code in LESSON_CODES and bool(setup) and setup.replace("_", "").replace("@", "").isalnum()   # kurulum "T1@1h" bicimi (ML ders kimlikleri @ icermez; parite korunur)
    return cat in TAG_VOCAB and val in TAG_VOCAB[cat]


def validate_tags(tags: Sequence[str]) -> list[str]:
    """Sozluk disi etiket => ValueError (not yazilmaz)."""
    if isinstance(tags, (str, bytes)):
        raise ValueError("tags liste olmali")
    bad = [t for t in tags if not valid_tag(t)]
    if bad:
        raise ValueError(f"sozluk disi etiket: {bad}")
    return list(tags)


def ders_uyar_mi(kod: str, kurulum: str, aday: Aday) -> bool:
    """Aday, ders kosuluna uyar mi? Yalniz karar aninda bilinen alanlar; eksik/sayi degilse False."""
    if aday.kurulum != kurulum:
        return False
    if kod == "seans_kapali":
        return aday.seans in ("closed", "weekend")
    if kod == "yuksek_vol":
        ar = aday.ozellikler.get("atr_ratio")
        return _sayi(ar) and ar >= HIGH_VOL_ATR_RATIO
    if kod == "dusuk_rr":
        rr = aday.ozellikler.get("rr")
        return _sayi(rr) and rr < LOW_RR
    return False


def not_yaz(aday: Aday) -> tuple[list[str], str]:
    """(etiketler, metin). Yalniz alindi=True ve r bilinen adaylar icin; aksi ValueError."""
    if not aday.alindi or aday.r is None:
        raise ValueError("not yalniz alinmis ve R'si bilinen aday icin yazilir")
    r = float(aday.r)
    cik = aday.cikis or {}
    ozl = aday.ozellikler or {}
    giris, plan, stop = cik.get("entry_price"), cik.get("planned_entry"), cik.get("planned_stop")

    slip = 0.0
    if _sayi(giris) and _sayi(plan) and _sayi(stop):
        risk = abs(plan - stop)
        if risk > 0:
            slip = abs(giris - plan) / risk
    tags: list[str] = ["giris:kotu_dolum" if slip > KAYMA_ESIGI else "giris:iyi"]

    sd = ozl.get("stop_dist_atr")
    sd = float(sd) if _sayi(sd) else None
    tags.append("stop:dar" if sd is not None and sd < STOP_DAR_ATR
                else "stop:genis" if sd is not None and sd > STOP_GENIS_ATR else "stop:normal")

    st = aday.seans
    tags.append(f"seans:{st if st in ('open', 'closed', 'weekend') else 'yok'}")
    reg = aday.rejim if aday.rejim in TAG_VOCAB["rejim"] else "unclear"
    tags.append(f"rejim:{reg}")
    tags.append("olay:bilinmiyor")

    fit = UYUM_TABLOSU.get(aday.kurulum.split("@", 1)[0])
    tags.append("uyum:uyumsuz" if fit is not None and aday.rejim not in fit else "uyum:uyumlu")

    loss = r < -EPS
    sonuc = "sonuc:kayip" if loss else "sonuc:kazanc" if r > EPS else "sonuc:basabas"
    lessons: list[str] = []
    if loss:
        lessons = [ders_kimligi(c, aday.kurulum) for c in LESSON_CODES if ders_uyar_mi(c, aday.kurulum, aday)]
    avoidable = loss and (bool(lessons) or "giris:kotu_dolum" in tags or "uyum:uyumsuz" in tags)
    kac = f"kacinilabilir:{'evet' if avoidable else 'hayir'}"
    tags.extend([kac, sonuc] if loss else [sonuc, kac])
    tags.extend(LESSON_PREFIX + lid for lid in lessons)
    validate_tags(tags)

    def fmt(x: Any, nd: int = 2) -> str:
        return "yok" if x is None else f"{x:.{nd}f}"

    atr = ozl.get("atr_ratio")
    rr = ozl.get("rr")
    bars = cik.get("bars_held")
    text = (f"{aday.enstruman} {aday.yon} {aday.kurulum} ({aday.rejim}): R={fmt(r)}, "
            f"cikis={cik.get('exit_reason') or 'yok'}, tutulan_bar={bars if bars is not None else 'yok'}, "
            f"MFE={fmt(cik.get('mfe_r'))} R, MAE={fmt(cik.get('mae_r'))} R, giris_kaymasi={slip:.2f} risk, "
            f"stop_mesafesi={fmt(sd)} ATR, seans={st or 'yok'}, atr_orani={fmt(atr if _sayi(atr) else None)}, "
            f"rr={fmt(rr if _sayi(rr) else None)}. Ders onerisi: {', '.join(lessons) if lessons else 'yok'}.")
    return tags, " ".join(text.split())
