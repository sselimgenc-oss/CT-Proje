"""Provider-neutral, read-only websocket dry-run runtime scaffolding.

The host injects a public-data adapter. Importing this module performs no I/O,
and no exchange/order, signing, or credential interface is defined here.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import time
from typing import Any, Protocol
import uuid

from copytrade.hl_ws_dry_run import IngestionState, evaluate_dry_run, normalize_message


class ReadOnlyAdapter(Protocol):
    """Host implementation restricted to public websocket and read-only fills."""

    async def connect(self, addresses: tuple[str, ...]) -> None: ...
    async def receive(self, timeout_seconds: float) -> Any | None: ...
    async def backfill(self, plan: dict[str, Any], addresses: tuple[str, ...]) -> list[Any]: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class RuntimeConfig:
    addresses: tuple[str, ...]
    run_mode: str = "dry_run"
    network_enabled: bool = False
    run_duration_seconds: int = 86_400
    max_age_ms: int = 10_000
    late_cutoff_ms: int = 10_000
    overlap_ms: int = 5_000
    heartbeat_timeout_seconds: float = 30.0
    reconnect_initial_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0
    evidence_path: Path | None = None

    def validate(self) -> None:
        if self.run_mode != "dry_run":
            raise ValueError("yalnız dry_run modu desteklenir")
        if not self.network_enabled:
            raise ValueError("ağ kapalı; bağlantı isteniyorsa network_enabled açıkça verilmelidir")
        if len(self.addresses) != 11 or any(not str(a).strip() for a in self.addresses):
            raise ValueError("tam 11 açıkça sağlanmış adres gerekli")
        if len(set(a.lower() for a in self.addresses)) != 11:
            raise ValueError("abonelik adresleri benzersiz olmalı")
        if not (0 < self.run_duration_seconds <= 86_400):
            raise ValueError("run_duration_seconds 1..86400 aralığında olmalı")
        if min(self.max_age_ms, self.late_cutoff_ms, self.overlap_ms) < 0:
            raise ValueError("zaman eşikleri negatif olamaz")
        if self.heartbeat_timeout_seconds <= 0 or self.reconnect_initial_seconds <= 0:
            raise ValueError("heartbeat/backoff süreleri pozitif olmalı")
        if self.reconnect_max_seconds < self.reconnect_initial_seconds:
            raise ValueError("reconnect_max_seconds başlangıç backoff değerinden küçük olamaz")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_event_id(event_id: str) -> str:
    return hashlib.sha256(event_id.encode("utf-8")).hexdigest()


@dataclass
class HealthState:
    run_id: str
    started_monotonic: float = field(default_factory=time.monotonic)
    connected: bool = False
    last_heartbeat_monotonic: float | None = None
    counters: dict[str, int] = field(default_factory=lambda: {
        "connections": 0, "reconnects": 0, "connection_errors": 0,
        "messages": 0, "accepted": 0, "duplicates": 0,
        "proposals": 0, "rejections": 0, "backfill_messages": 0,
    })

    def snapshot(self, heartbeat_timeout_seconds: float) -> dict[str, Any]:
        now = time.monotonic()
        age = None if self.last_heartbeat_monotonic is None else max(0.0, now - self.last_heartbeat_monotonic)
        return {
            "status": "ok", "mode": "dry_run", "run_id": self.run_id,
            "uptime_seconds": round(now - self.started_monotonic, 3),
            "listener_connected": self.connected,
            "last_heartbeat_age_seconds": None if age is None else round(age, 3),
            "ready": self.connected and age is not None and age <= heartbeat_timeout_seconds,
            "counters": dict(self.counters),
        }


class JsonlEvidence:
    """Append-only local evidence with no raw messages or addresses."""
    def __init__(self, path: Path | None, run_id: str) -> None:
        self.path, self.run_id = path, run_id
        self._file = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("a", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        if self._file is not None:
            self._file.write(json.dumps({"run_id": self.run_id, "recorded_at_utc": _utc_now(), **record},
                                        sort_keys=True, separators=(",", ":")) + "\n")
            self._file.flush()

    def close(self, manifest: dict[str, Any]) -> None:
        self.write({"event_type": "run_manifest", **manifest})
        if self._file is not None:
            self._file.close()
            self._file = None


class DryRunRuntime:
    def __init__(self, config: RuntimeConfig, adapter: ReadOnlyAdapter, *,
                 clock_ms=None, state: IngestionState | None = None) -> None:
        config.validate()
        self.config, self.adapter = config, adapter
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.state = state or IngestionState()
        self.health = HealthState(str(uuid.uuid4()))
        self.evidence = JsonlEvidence(config.evidence_path, self.health.run_id)
        self._stop = asyncio.Event()
        self._started = time.monotonic()
        self._accepted = 0
        self._duplicates = 0
        self._proposals = 0
        self._rejections = 0
        self._stop_reason = "requested"

    def request_stop(self, reason: str = "signal") -> None:
        self._stop_reason = reason
        self._stop.set()

    def health_snapshot(self) -> dict[str, Any]:
        return self.health.snapshot(self.config.heartbeat_timeout_seconds)

    async def _process(self, message: Any, *, backfill: bool = False) -> None:
        self.health.counters["messages"] += 1
        self.health.last_heartbeat_monotonic = time.monotonic()
        events = normalize_message(message)
        result = self.state.ingest(events)
        self._accepted += len(result.accepted)
        self._duplicates += len(result.duplicates)
        self.health.counters["accepted"] = self._accepted
        self.health.counters["duplicates"] = self._duplicates
        for event in result.accepted:
            decision = evaluate_dry_run(event, now_ms=self.clock_ms(), max_age_ms=self.config.max_age_ms,
                                        late_cutoff_ms=self.config.late_cutoff_ms)
            self._proposals += decision["kind"] == "dry_run_proposal"
            self._rejections += decision["kind"] == "dry_run_rejection"
            self.health.counters["proposals"] = self._proposals
            self.health.counters["rejections"] = self._rejections
            decision["event_id"] = _safe_event_id(event.event_id)
            self.evidence.write({
                "event_type": "dry_run_decision", "mode": "dry_run",
                "event_id": decision["event_id"], "event_time_utc": datetime.fromtimestamp(
                    event.event_time_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z"),
                "received_at_utc": _utc_now(), "processed_at_utc": _utc_now(),
                "decision": decision, "backfill": backfill,
            })

    async def run(self) -> dict[str, Any]:
        """Run until stopped or duration expires; adapter errors trigger bounded reconnects."""
        self.evidence.write({"event_type": "run_started", "mode": "dry_run"})
        backoff = self.config.reconnect_initial_seconds
        try:
            while not self._stop.is_set() and time.monotonic() - self._started < self.config.run_duration_seconds:
                try:
                    await self.adapter.connect(self.config.addresses)
                    self.health.connected = True
                    self.health.counters["connections"] += 1
                    self.health.last_heartbeat_monotonic = time.monotonic()
                    self.evidence.write({"event_type": "connected"})
                    plan = self.state.reconnect_backfill_plan(now_ms=self.clock_ms(), overlap_ms=self.config.overlap_ms)
                    for message in await self.adapter.backfill(plan, self.config.addresses):
                        self.health.counters["backfill_messages"] += 1
                        await self._process(message, backfill=True)
                    backoff = self.config.reconnect_initial_seconds
                    while not self._stop.is_set() and time.monotonic() - self._started < self.config.run_duration_seconds:
                        try:
                            message = await asyncio.wait_for(self.adapter.receive(self.config.heartbeat_timeout_seconds),
                                                             timeout=self.config.heartbeat_timeout_seconds + 0.25)
                        except asyncio.TimeoutError:
                            self.health.last_heartbeat_monotonic = time.monotonic()
                            self.evidence.write({"event_type": "heartbeat_timeout"})
                            raise ConnectionError("adapter receive heartbeat timeout")
                        if message is not None:
                            await self._process(message)
                        else:
                            self.health.last_heartbeat_monotonic = time.monotonic()
                except asyncio.CancelledError:
                    self.request_stop("cancelled")
                    raise
                except Exception as exc:
                    self.health.connected = False
                    self.health.counters["connection_errors"] += 1
                    if self.health.counters["connections"] > 1:
                        self.health.counters["reconnects"] += 1
                    # Error text may contain provider data; keep evidence generic.
                    self.evidence.write({"event_type": "connection_error", "error_type": type(exc).__name__})
                    try:
                        await self.adapter.close()
                    except Exception:
                        pass
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    except asyncio.TimeoutError:
                        pass
                    backoff = min(self.config.reconnect_max_seconds, backoff * 2)
        finally:
            self.health.connected = False
            try:
                await self.adapter.close()
            finally:
                completed = time.monotonic() - self._started >= self.config.run_duration_seconds
                manifest = {
                    "ended_at_utc": _utc_now(), "stop_reason": "duration_elapsed" if completed else self._stop_reason,
                    "completed": completed, "counters": dict(self.health.counters),
                    "evidence_path": None if self.config.evidence_path is None else str(self.config.evidence_path),
                }
                self.evidence.close(manifest)
        return manifest


async def run_with_signal_handlers(runtime: DryRunRuntime) -> dict[str, Any]:
    """Install SIGINT/SIGTERM stop hooks for an explicitly invoked runtime."""
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runtime.request_stop, sig.name.lower())
            installed.append(sig)
        except (NotImplementedError, RuntimeError):
            # On platforms without asyncio signal handlers, callers can still
            # invoke request_stop directly from their process supervisor.
            continue
    try:
        return await runtime.run()
    finally:
        for sig in installed:
            loop.remove_signal_handler(sig)


def config_from_env() -> RuntimeConfig:
    """Read non-secret runtime settings. Addresses must be explicitly supplied."""
    raw = os.environ.get("SUBSCRIPTIONS", "")
    addresses = tuple(a.strip() for a in raw.split(",") if a.strip())
    evidence = os.environ.get("EVIDENCE_PATH", "").strip()
    return RuntimeConfig(
        addresses=addresses,
        run_mode=os.environ.get("RUN_MODE", "dry_run"),
        network_enabled=os.environ.get("NETWORK_ENABLED", "false").lower() == "true",
        run_duration_seconds=int(os.environ.get("RUN_DURATION_SECONDS", "86400")),
        evidence_path=Path(evidence) if evidence else None,
    )
