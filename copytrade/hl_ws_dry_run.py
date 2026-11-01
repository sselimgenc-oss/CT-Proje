"""Provider independent, memory-only HL WebSocket ingestion for dry-run review.

No socket/client, persistence, signing, wallet, or exchange order interface lives
here. A host supplies decoded messages and (optionally) its own idempotency store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Protocol


class EventIdStore(Protocol):
    def seen(self, event_id: str) -> bool: ...
    def remember(self, event_id: str) -> None: ...


@dataclass
class MemoryEventIdStore:
    """Process-local example store; restart durability belongs to the host."""
    ids: set[str] = field(default_factory=set)

    def seen(self, event_id: str) -> bool:
        return event_id in self.ids

    def remember(self, event_id: str) -> None:
        self.ids.add(event_id)


@dataclass(frozen=True)
class NormalizedEvent:
    event_id: str
    trader: str
    coin: str
    side: str
    price: float
    size: float
    event_time_ms: int
    order_id: str | None
    trade_id: str | None
    raw: dict[str, Any]


def normalize_message(message: Any, *, trader: str | None = None) -> list[NormalizedEvent]:
    """Normalize decoded HL ``userFills`` messages; malformed rows fail closed."""
    if not isinstance(message, dict) or message.get("channel") != "userFills":
        raise ValueError("userFills websocket message bekleniyordu")
    data = message.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("fills"), list):
        raise ValueError("userFills data.fills listesi eksik")
    address = str(trader or data.get("user") or "").strip().lower()
    if not address:
        raise ValueError("trader/user kimliği eksik")
    events = []
    for fill in data["fills"]:
        if not isinstance(fill, dict):
            raise ValueError("fill nesne olmalı")
        try:
            coin = str(fill["coin"]).strip()
            side = str(fill["side"]).upper()
            price, size, timestamp = float(fill["px"]), float(fill["sz"]), int(fill["time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("fill coin/side/px/sz/time alanları geçersiz") from exc
        if not coin or side not in {"B", "A"}:
            raise ValueError("fill coin veya side geçersiz")
        if not (math.isfinite(price) and price > 0 and math.isfinite(size) and size > 0 and timestamp >= 0):
            raise ValueError("fill fiyatı, boyutu ve zamanı geçersiz")
        tid = str(fill["tid"]) if fill.get("tid") is not None else None
        oid = str(fill["oid"]) if fill.get("oid") is not None else None
        if not tid and not (oid and timestamp and coin):
            raise ValueError("idempotency için tid veya oid+time+coin gerekli")
        event_id = f"{address}:{tid}" if tid else f"{address}:{oid}:{timestamp}:{coin}:{side}:{price}:{size}"
        events.append(NormalizedEvent(event_id, address, coin, side, price, size, timestamp,
                                      oid, tid, dict(fill)))
    return events


@dataclass(frozen=True)
class IngestResult:
    accepted: tuple[NormalizedEvent, ...]
    duplicates: tuple[str, ...]
    out_of_order: tuple[str, ...]
    newest_event_time_ms: int | None


class IngestionState:
    """Dedup/order tracker and reconnect/backfill planning; no I/O is performed."""
    def __init__(self, ids: EventIdStore | None = None) -> None:
        self.ids = ids or MemoryEventIdStore()
        self.latest_event_time_ms: int | None = None

    def ingest(self, events: list[NormalizedEvent]) -> IngestResult:
        accepted, duplicates, out_of_order = [], [], []
        latest = self.latest_event_time_ms
        for event in events:
            if self.ids.seen(event.event_id):
                duplicates.append(event.event_id)
                continue
            self.ids.remember(event.event_id)
            if latest is not None and event.event_time_ms < latest:
                out_of_order.append(event.event_id)
            latest = event.event_time_ms if latest is None else max(latest, event.event_time_ms)
            accepted.append(event)
        self.latest_event_time_ms = latest
        return IngestResult(tuple(accepted), tuple(duplicates), tuple(out_of_order), latest)

    def reconnect_backfill_plan(self, *, now_ms: int, overlap_ms: int = 5_000) -> dict[str, int | str | None]:
        if now_ms < 0 or overlap_ms < 0:
            raise ValueError("zaman ve overlap negatif olamaz")
        return {"kind": "read_only_backfill_request", "start_ms": max(0, (self.latest_event_time_ms or now_ms) - overlap_ms),
                "end_ms": now_ms, "after_event_time_ms": self.latest_event_time_ms}


def evaluate_dry_run(event: NormalizedEvent, *, now_ms: int, max_age_ms: int,
                     late_cutoff_ms: int, proposal_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return evidence and a proposal/rejection only; never creates an order."""
    if min(now_ms, max_age_ms, late_cutoff_ms) < 0:
        raise ValueError("zaman eşikleri negatif olamaz")
    age = now_ms - event.event_time_ms
    reasons = []
    if age < 0:
        reasons.append("event_from_future")
    elif age > max_age_ms:
        reasons.append("stale_event")
    if age > late_cutoff_ms:
        reasons.append("late_cutoff")
    return {
        "kind": "dry_run_rejection" if reasons else "dry_run_proposal",
        "event_id": event.event_id,
        "event_time_ms": event.event_time_ms,
        "observed_time_ms": now_ms,
        "age_ms": age,
        "direction": "buy" if event.side == "B" else "sell",
        "coin": event.coin,
        "price_reference": event.price,
        "size_reference": event.size,
        "context": dict(proposal_context or {}),
        "reasons": reasons,
        "order_sent": False,
        "exchange_post_performed": False,
    }
