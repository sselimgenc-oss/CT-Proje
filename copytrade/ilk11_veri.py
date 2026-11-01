"""Faz 1: İlk 11 puanı için açık kaynak alan eşlemesi ve Pazar snapshotı.

Bu modül yalnızca verilen veriyi dönüştürür; ağ, dosya veya emir işlemi yapmaz.
Anlamı doğrulanmamış ölçümler forma aktarılmaz. Snapshotın kanonik JSON metni
değişmez artefakttır; snapshot_id içerik SHA-256'sıdır.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from copytrade.ilk11 import KALDIRAC_ALANLARI, ilk_kadro

ISTANBUL = ZoneInfo("Europe/Istanbul")

# Mapping rationale is retained with each value in the candidate's provenance.
_DOGRUDAN = {
    "hesap": ("hesap_degeri", "account_value"),
    "siklik": ("gunluk_islem_sikligi",),
    "tutma": ("medyan_tutma_saat",),
    "kaldirac": ("medyan_kaldirac",),
    "dusus": ("max_drawdown",),
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def form_esle(kayit: Mapping[str, Any]) -> tuple[dict[str, float | None], dict[str, str | None]]:
    """Bir seçilim/izleme kaydından güvenilir ham form alanlarını al.

    Yalnız bire bir aynı tanım kabul edilen alanlar taşınır. `kazanma`, `golge`,
    ROI ve `tutarli` mevcut kayıtların farklı sonuç tanımları gerektirebildiği
    için veri sağlayıcı bunları açıkça `form_ham` içinde vermedikçe null kalır.
    """
    explicit = kayit.get("form_ham") if isinstance(kayit.get("form_ham"), Mapping) else {}
    result: dict[str, float | None] = {}
    provenance: dict[str, str | None] = {}
    for field in KALDIRAC_ALANLARI:
        if field in explicit:
            result[field] = _number(explicit[field])
            provenance[field] = f"form_ham.{field}" if result[field] is not None else None
            continue
        result[field] = None
        provenance[field] = None
        for source in _DOGRUDAN.get(field, ()):
            if source in kayit:
                value = _number(kayit[source])
                if value is not None:
                    if field == "tutma" and source == "medyan_tutma_saat":
                        value *= 60.0  # Etre ham tutma birimi dakikadır.
                        source = "medyan_tutma_saat*60"
                    result[field], provenance[field] = value, source
                    break
    return result, provenance


def _as_of(value: str | datetime) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("as_of zaman dilimini içermeli")
    local = parsed.astimezone(ISTANBUL)
    if local.weekday() != 6 or (local.hour, local.minute, local.second, local.microsecond) != (13, 0, 0, 0):
        raise ValueError("snapshot zamanı Türkiye saatiyle Pazar 13:00 olmalı")
    return local.isoformat()


def snapshot_olustur(adaylar: Sequence[Mapping[str, Any]], as_of: str | datetime,
                     kaynak_surumu: Mapping[str, str]) -> dict[str, Any]:
    """Pazar seçim sonucunu deterministik ve hash'li JSON snapshot olarak üret.

    Girdi adayları kapıyı geçmiş HL evrenidir. `uygun` alanı false olanlar
    sıralamaya girmez. Snapshot tüm girdileri ve en iyi 50 takım dağılımını
    içerir; sonradan kaynak nesnelerde yapılacak değişiklikler sonucu etkilemez.
    """
    captured_at = _as_of(as_of)
    if not kaynak_surumu or any(not isinstance(k, str) or not isinstance(v, str) or not v
                                for k, v in kaynak_surumu.items()):
        raise ValueError("kaynak_surumu boş olmayan metin anahtar/değerleri içermeli")
    normalized = []
    seen: set[str] = set()
    for item in adaylar:
        ident = str(item.get("id", ""))
        if not ident or ident in seen:
            raise ValueError("aday id değerleri boş olmamalı ve benzersiz olmalı")
        seen.add(ident)
        form, provenance = form_esle(item)
        normalized.append({
            "id": ident,
            "uygun": item.get("uygun") is True,
            "alanlar": form,
            "alan_kaynagi": provenance,
            "kapi_puani": _number(item.get("kapi_puani")),
            "gecerli_gozlem_suresi": _number(item.get("gecerli_gozlem_suresi")),
        })
    ranked = ilk_kadro(normalized)
    body = {
        "sema": "ilk11-pazar-v1",
        "as_of": captured_at,
        "kaynak_surumu": dict(sorted(kaynak_surumu.items())),
        "adaylar": normalized,
        "uygun_evren": ranked["uygun_evren"],
        "secim_adedi": ranked["secim_adedi"],
        "uyari": ranked["uyari"],
        "kadro": [{**row, "takim": row["grup"]} for row in ranked["kadro"]],
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"snapshot_id": hashlib.sha256(canonical.encode("utf-8")).hexdigest(), **body}


def snapshot_json(snapshot: Mapping[str, Any]) -> str:
    """Hash'i doğrulayarak değişmez snapshot artefaktının kanonik JSON'unu döndür."""
    body = {k: v for k, v in snapshot.items() if k != "snapshot_id"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if snapshot.get("snapshot_id") != digest:
        raise ValueError("snapshot içeriği snapshot_id ile uyuşmuyor")
    return json.dumps({"snapshot_id": digest, **body}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
