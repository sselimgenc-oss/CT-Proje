"""İlk11 Faz 1 saf kadro/puan fonksiyonları.

commit f3f5cff92d6db2fff62b6f7753c45343e00583ba; yüzdelik sırası,
eksik alan varsayılanı, kaldıraç ağırlıkları, gölge sonucu kırpma ve
``kadro.py`` içindeki hesap büyüklüğü dönüşümü de aynı kaynak committen alınmıştır.
Bu repo GPL-3.0 ile lisanslıdır; bu dosya
kuralları değil, puan hesaplama parçaları taşınmıştır.

Veri ağdan okunmaz/yazılmaz. Aday girdilerinde `alanlar` K1-K10 ham
ölçümleridir; PAPER dışı ölçüm dönüşümleri veri sağlayıcıya aittir ve
belirsiz eşleme uydurulmaz. Gölge ortalama K1 için `golge_ozeti` yardımcıdır.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

KALDIRAC_ALANLARI = (
    "golge", "ay_roi", "hafta_roi", "hesap", "dusus", "kazanma",
    "siklik", "tutma", "kaldirac", "tutarli",
)
KALDIRAC_AGIRLIKLARI = {
    "golge": 1.0, "ay_roi": 0.8, "hafta_roi": 0.6, "hesap": 0.6,
    "dusus": 2.0, "kazanma": 1.0, "siklik": 0.7, "tutma": 0.8,
    "kaldirac": 0.9, "tutarli": 1.8,
}
DUSUK_IYI = frozenset({"dusus"})
EKSİK_ALAN_PUANI = 35.0
KAPASITE = 50
ILK11 = 11
YEDEK11 = 11
PAF = 28


def yuzdelik(degerler: Mapping[str, float | None], dusuk_iyi: bool = False) -> dict[str, float]:
    """Kaynakla aynı sıra: sıralı (değer, kimlik), sıra ortası; eksik 35."""
    sirali = sorted((float(v), str(k)) for k, v in degerler.items() if v is not None)
    sonuc = {str(k): EKSİK_ALAN_PUANI for k in degerler}
    n = len(sirali)
    for i, (value, key) in enumerate(sirali):
        p = 100.0 * (i + 0.5) / n
        sonuc[key] = 100.0 - p if dusuk_iyi else p
    return sonuc


def siklik_puani(gunluk: float | None, bot: float = 150.0) -> float | None:
    if gunluk is None:
        return None
    if gunluk <= 0 or gunluk >= min(20.0, bot):
        return 0.0
    alt = min(1.0, gunluk / 1.0)
    ust = 1.0 if gunluk <= 3 else max(0.0, 1 - (gunluk - 3) / (min(20.0, bot) - 3))
    return alt * ust


def tutma_puani(dk: float | None) -> float | None:
    import math
    if dk is None:
        return None
    if dk < 2:
        return 0.0
    if dk <= 5:
        return (dk - 2) / 3
    if dk <= 30:
        return 1.0
    return max(0.4, 1.0 - 0.6 * (math.log10(dk / 30) / math.log10(8)))


def kaldirac_puani(ortalama: float | None) -> float | None:
    return None if ortalama is None else max(0.0, 1.0 - abs(float(ortalama) - 4.0) / 20.0)


def hesap_puani(usd: float | None) -> float | None:
    if not usd:
        return None
    return min(1.0, max(0.0, (float(usd) - 5000.0) / 500000.0)) ** 0.5


def hazirla_kaldirac_alanlari(ham: Mapping[str, float | None], bot: float = 150.0) -> dict[str, float | None]:
    result = dict(ham)
    result["hesap"] = hesap_puani(ham.get("hesap"))
    result["siklik"] = siklik_puani(ham.get("siklik"), bot)
    result["tutma"] = tutma_puani(ham.get("tutma"))
    result["kaldirac"] = kaldirac_puani(ham.get("kaldirac"))
    return result


def agirlikli_puan(alanlar: Mapping[str, Mapping[str, float | None]],
                    agirliklar: Mapping[str, float] | None = None) -> dict[str, float]:
    """Önceden dönüştürülmüş alanların yüzdeliklerini/ağırlıklı ortalamasını verir.

    Ham değerler için `hazirla_kaldirac_alanlari` çağrılmalıdır; eski adapter
    davranışı (doğrudan puanlanmış alan sözlüğü) aynen korunur.
    """
    weights = agirliklar or KALDIRAC_AGIRLIKLARI
    ranks = {
        field: yuzdelik({key: values.get(field) for key, values in alanlar.items()}, field in DUSUK_IYI)
        for field in KALDIRAC_ALANLARI
    }
    positive = {field: max(0.0, float(weights.get(field, 0.0))) for field in KALDIRAC_ALANLARI}
    divisor = sum(positive.values()) or 1.0
    return {
        key: sum(ranks[field][key] * positive[field] for field in KALDIRAC_ALANLARI) / divisor
        for key in alanlar
    }


def golge_ozeti(sonuclar: Sequence[float | None], k: int = 8) -> dict[str, Any]:
    xs = [max(-1.0, min(3.0, float(x))) for x in sonuclar if x is not None]
    n = len(xs)
    if not n:
        return {"n": 0, "ortalama": None, "buzulmus_ortalama": None}
    ort = sum(xs) / n
    return {"n": n, "ortalama": ort, "buzulmus_ortalama": ort * n / (n + k)}


def _tie_key(row: Mapping[str, Any]) -> tuple[float, float, float, str]:
    # Pazar terfi eşitliği: form -> geçmiş kapı puanı -> geçerli gözlem süresi.
    return (-float(row.get("form_puani") or 0), -float(row.get("kapi_puani") or 0),
            -float(row.get("gecerli_gozlem_suresi") or 0), str(row["id"]))


def ilk_kadro(adaylar: Sequence[Mapping[str, Any]], kapasite: int = KAPASITE,
              bot: float = 150.0) -> dict[str, Any]:
    """Uygun adayların tüm evreninde puanla; en iyi kapasiteyi 11/11/28 dağıt."""
    if kapasite != KAPASITE:
        raise ValueError("Faz 1 kapasitesi sabit 50; farklı kapasite desteklenmiyor")
    ids = [str(a["id"]) for a in adaylar]
    if len(ids) != len(set(ids)):
        raise ValueError("aday id değerleri benzersiz olmalı")
    uygun = [a for a in adaylar if a.get("uygun") is True]
    ham = {str(a["id"]): hazirla_kaldirac_alanlari(a.get("alanlar", {}), bot) for a in uygun}
    scores = agirlikli_puan(ham)
    sirali = sorted(uygun, key=lambda a: (-scores[str(a["id"])], *_tie_key(a)))
    secilen = sirali[:KAPASITE]
    return {
        "surum": "ilk11-faz1", "uygun_evren": len(uygun), "secim_adedi": len(secilen),
        "kapasite_bos": KAPASITE - len(secilen),
        "uyari": None if len(uygun) >= KAPASITE else "uygun evren 50 adaya ulaşmadı; kapasite boş kaldı",
        "kadro": [
            {"id": str(a["id"]), "grup": "ilk11" if i < ILK11 else "yedek11" if i < ILK11 + YEDEK11 else "paf",
             "puan": scores[str(a["id"])], "alanlar": dict(a.get("alanlar", {}))}
            for i, a in enumerate(secilen)
        ],
    }


def yedekten_terfi_kapisi(son_paper_sonuclari: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Son 6 geçerli PAPER sonucu: toplam >0, kazanma >=.40, en iyi hariç >0."""
    valid = [float(r["sonuc"]) for r in son_paper_sonuclari
             if r.get("gecerli") is True and r.get("sonuc") is not None]
    last = valid[-6:]
    n = len(last)
    total = sum(last)
    wins = sum(x > 0 for x in last) / n if n else 0.0
    ex_best = total - max(last) if n > 1 else 0.0
    passed = n == 6 and total > 0 and wins >= 0.40 and ex_best > 0
    return {"gecti": passed, "n_gecerli": n, "toplam": total, "kazanma_orani": wins,
            "en_iyi_haric_toplam": ex_best,
            "neden": None if passed else "6 geçerli PAPER işlemi/pozitif toplam/%40 kazanma/en iyi hariç pozitif koşulları sağlanmadı"}


def pazar_gecis(kadro: Sequence[Mapping[str, Any]], hafta: str) -> dict[str, Any]:
    """Mevcut 50 kişi için değişiklik planı üretir; hiçbir dosyaya yazmaz.

    Her satırda `form_puani`, `bu_pazar_gecerli`, `bu_pazar_aktif`,
    `onceki_pazar_aktif` beklenir; eşitlikte ayrıca `kapi_puani` ve
    `gecerli_gozlem_suresi`, yedeklerde `paper_sonuclari` kullanılır.
    Bilinmeyen/eksik veri hareket üretmez ve açıklanır.
    """
    if len(kadro) > KAPASITE or len({str(r["id"]) for r in kadro}) != len(kadro):
        raise ValueError("mevcut kadro en çok 50 benzersiz üyeden oluşmalı")
    caps = {"ilk11": ILK11, "yedek11": YEDEK11, "paf": PAF}
    counts = {group: sum(r.get("grup") == group for r in kadro) for group in caps}
    if any(counts[group] > caps[group] for group in caps):
        raise ValueError("mevcut kadro grup kapasitelerini aşıyor")
    notes: list[dict[str, str]] = []
    exits: list[dict[str, Any]] = []
    down: list[dict[str, Any]] = []
    for row in kadro:
        group = row.get("grup")
        if group not in caps:
            continue
        active_now, active_prev = row.get("bu_pazar_aktif"), row.get("onceki_pazar_aktif")
        inactive = active_now is False and active_prev is False
        if active_now is None or active_prev is None:
            notes.append({"id": str(row["id"]), "neden": "aktivite verisi eksik; iki Pazar hareketsizlik kararı yok"})
        form = row.get("form_puani")
        valid_form = row.get("bu_pazar_gecerli") is True and form is not None
        if form is not None and row.get("bu_pazar_gecerli") is False:
            notes.append({"id": str(row["id"]), "neden": "Pazar form snapshotı geçersiz; form hareketi yok"})
        low_form = valid_form and float(form) < 40
        if group == "paf" and low_form:
            exits.append({"id": str(row["id"]), "once": "paf", "sonra": "kadrodisi", "neden": "geçerli Pazar formu <40"})
        elif group == "yedek11" and low_form:
            down.append({"id": str(row["id"]), "once": "yedek11", "sonra": "paf", "neden": "geçerli Pazar formu <40"})
        elif group == "ilk11" and low_form:
            down.append({"id": str(row["id"]), "once": "ilk11", "sonra": "yedek11", "neden": "geçerli Pazar formu <40"})
        elif inactive and group == "paf":
            exits.append({"id": str(row["id"]), "once": "paf", "sonra": "kadrodisi", "neden": "iki ardışık Pazar hareketsiz"})
        elif inactive and group == "yedek11":
            down.append({"id": str(row["id"]), "once": "yedek11", "sonra": "paf", "neden": "iki ardışık Pazar hareketsiz"})
        elif inactive and group == "ilk11":
            down.append({"id": str(row["id"]), "once": "ilk11", "sonra": "yedek11", "neden": "iki ardışık Pazar hareketsiz"})
        elif form is None or row.get("bu_pazar_gecerli") is not True:
            notes.append({"id": str(row["id"]), "neden": "geçerli Pazar formu yok; 60/40 kararı yok"})

    planned: list[dict[str, Any]] = []
    moved_ids: set[str] = set()
    # Empty the bottom first, then cascade reserve and First 11 downward.
    # This keeps every intermediate plan inside the fixed 11/11/28 caps.
    down.sort(key=lambda m: (0 if m["once"] == "yedek11" else 1, m["id"]))
    for move in exits + down:
        if move["id"] in moved_ids:
            continue
        if move["sonra"] in caps and counts[move["sonra"]] >= caps[move["sonra"]]:
            notes.append({"id": move["id"], "neden": f"{move['sonra']} kapasitesi dolu; alt kademe boşluğu oluşana kadar ertelendi"})
            continue
        counts[move["once"]] -= 1
        if move["sonra"] in caps:
            counts[move["sonra"]] += 1
        planned.append(move)
        moved_ids.add(move["id"])

    def ranked(group: str) -> list[Mapping[str, Any]]:
        rows = [r for r in kadro if r.get("grup") == group and str(r["id"]) not in moved_ids
                and r.get("bu_pazar_gecerli") is True and r.get("form_puani") is not None
                and float(r["form_puani"]) >= 60]
        return sorted(rows, key=_tie_key)

    # Reserve → First 11; the six-result PAPER gate is required.
    for row in ranked("yedek11"):
        if counts["ilk11"] >= ILK11:
            break
        gate = yedekten_terfi_kapisi(row.get("paper_sonuclari", []))
        if gate["gecti"]:
            counts["yedek11"] -= 1
            counts["ilk11"] += 1
            planned.append({"id": str(row["id"]), "once": "yedek11", "sonra": "ilk11", "neden": "form >=60 ve PAPER terfi kapısı geçti"})
            moved_ids.add(str(row["id"]))
        else:
            notes.append({"id": str(row["id"]), "neden": gate["neden"]})
    # PAF → Reserve only. Never jump directly to First 11.
    for row in ranked("paf"):
        if counts["yedek11"] >= YEDEK11:
            break
        counts["paf"] -= 1
        counts["yedek11"] += 1
        planned.append({"id": str(row["id"]), "once": "paf", "sonra": "yedek11", "neden": "form >=60; yedek boşluğu"})
        moved_ids.add(str(row["id"]))
    return {"hafta": hafta, "mod": "PAPER", "emir_uretildi": False, "kadro_yazildi": False,
            "degisiklik_plani": planned, "grup_sayilari_plan": counts, "aciklamalar": notes}
