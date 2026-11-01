"""Saf Pazar kadro çalışması planlayıcısı.

Planlayıcı veri çekmez, dosya yazmaz ve emir üretmez. İlk çalışma Pazar günü
13:00 Europe/Istanbul saatinde başlar. Her başarısızlıktan sonra aynı snapshot
kimliğiyle iki saatlik aralıkta yeniden denenir; başarıdan sonra akış kapanır.

Çağıran taraf snapshot'ı değişmez olarak saklamalı ve tekrar denemede hem
snapshot_id hem retry_snapshot_id değerlerini göndermelidir. Kimlik değişirse
planlayıcı yeniden denemeyi reddeder. Saatler timezone bilgili datetime olmalı.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

ISTANBUL = ZoneInfo("Europe/Istanbul")
ILK_SAAT = (13, 0)
TEKRAR_ARALIGI = timedelta(hours=2)


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} timezone bilgili datetime olmalı")
    return value


def _ilk_calistirma_zamani(now_istanbul: datetime) -> datetime:
    """Şimdiki hafta Pazar 13:00 geçtiyse onu, değilse yaklaşan Pazar'ı seç."""
    weekday = now_istanbul.weekday()  # Monday=0, Sunday=6
    if weekday == 6 and (now_istanbul.hour, now_istanbul.minute) >= ILK_SAAT:
        days_until_sunday = 0
    else:
        days_until_sunday = (6 - weekday) % 7
    sunday = (now_istanbul + timedelta(days=days_until_sunday)).date()
    candidate = datetime.combine(sunday, datetime.min.time(), tzinfo=ISTANBUL).replace(
        hour=ILK_SAAT[0], minute=ILK_SAAT[1]
    )
    return candidate


def pazar_akis_plani(
    *,
    now: datetime,
    deneme_sayisi: int,
    snapshot_id: str | None = None,
    retry_snapshot_id: str | None = None,
    son_basarisiz_at: datetime | None = None,
    basarili: bool = False,
) -> dict[str, Any]:
    """Bir sonraki eylemi döndürür; durum değiştirmez.

    ``deneme_sayisi`` tamamlanmış çalışma denemelerinin sayısıdır. İlk
    denemeden sonra ``son_basarisiz_at`` son başarısız denemenin zamanıdır.
    Tekrar çağrılarında ``retry_snapshot_id`` yeniden kullanılan girdinin
    kimliğini temsil eder ve ``snapshot_id`` ile aynı olmalıdır.

    Eylemler: ``bekle``, ``snapshot_hazirla``, ``calistir``, ``yeniden_dene``,
    ``tamamla`` veya ``reddet``.
    """
    now = _aware(now, "now")
    if isinstance(deneme_sayisi, bool) or not isinstance(deneme_sayisi, int) or deneme_sayisi < 0:
        raise ValueError("deneme_sayisi sıfır veya pozitif tam sayı olmalı")
    if not isinstance(basarili, bool):
        raise ValueError("basarili boolean olmalı")
    if snapshot_id is not None and (not isinstance(snapshot_id, str) or not snapshot_id.strip()):
        raise ValueError("snapshot_id boş olmayan metin olmalı")
    if retry_snapshot_id is not None and (not isinstance(retry_snapshot_id, str) or not retry_snapshot_id.strip()):
        raise ValueError("retry_snapshot_id boş olmayan metin olmalı")

    local_now = now.astimezone(ISTANBUL)
    if deneme_sayisi == 0:
        if son_basarisiz_at is not None or retry_snapshot_id is not None:
            raise ValueError("ilk denemede başarısızlık zamanı/tekrar snapshot kimliği olamaz")
        if basarili:
            raise ValueError("deneme olmadan başarı bildirilemez")
        due = _ilk_calistirma_zamani(local_now)
        if local_now < due:
            return {"eylem": "bekle", "deneme_no": 1, "zaman": due.isoformat(),
                    "snapshot_id": snapshot_id, "snapshot_as_of": due.isoformat(),
                    "neden": "Pazar 13:00 Türkiye saati başlangıcı bekleniyor"}
        if snapshot_id is None:
            return {"eylem": "snapshot_hazirla", "deneme_no": 1, "zaman": due.isoformat(),
                    "snapshot_id": None, "snapshot_as_of": due.isoformat(),
                    "neden": "Başlangıç zamanı geldi; değişmez seçim snapshotı hazırlanmalı"}
        return {"eylem": "calistir", "deneme_no": 1, "zaman": local_now.isoformat(),
                "snapshot_id": snapshot_id, "snapshot_as_of": due.isoformat(),
                "neden": "Pazar 13:00 başlangıcı geldi; dondurulmuş snapshot ile çalıştır"}

    if son_basarisiz_at is None:
        raise ValueError("önceki denemeler için son_basarisiz_at gerekli")
    last_failure = _aware(son_basarisiz_at, "son_basarisiz_at")
    if snapshot_id is None:
        return {"eylem": "reddet", "deneme_no": deneme_sayisi + 1, "zaman": None,
                "snapshot_id": None, "neden": "Tekrar denemede sabit snapshot_id gerekli"}
    if retry_snapshot_id != snapshot_id:
        return {"eylem": "reddet", "deneme_no": deneme_sayisi + 1, "zaman": None,
                "snapshot_id": snapshot_id,
                "neden": "Tekrar snapshot kimliği ilk snapshot ile eşleşmiyor"}
    if basarili:
        return {"eylem": "tamamla", "deneme_no": deneme_sayisi, "zaman": local_now.isoformat(),
                "snapshot_id": snapshot_id, "neden": "Kadro çalışması başarılı; tekrar durduruldu"}

    due = last_failure.astimezone(ISTANBUL) + TEKRAR_ARALIGI
    if local_now < due:
        return {"eylem": "bekle", "deneme_no": deneme_sayisi + 1, "zaman": due.isoformat(),
                "snapshot_id": snapshot_id,
                "neden": "Aynı snapshot için iki saatlik yeniden deneme aralığı bekleniyor"}
    return {"eylem": "yeniden_dene", "deneme_no": deneme_sayisi + 1,
            "zaman": local_now.isoformat(), "snapshot_id": snapshot_id,
            "neden": "İki saat doldu; aynı dondurulmuş snapshot ile yeniden dene"}
