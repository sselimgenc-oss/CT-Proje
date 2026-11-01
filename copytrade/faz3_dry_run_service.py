"""Explicitly invoked process wrapper for the HL dry-run runtime.

This module ships no provider adapter. A deployment must supply an adapter
factory implementing ``ReadOnlyAdapter``; importing this module is inert.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse

from copytrade.hl_ws_runtime import DryRunRuntime, RuntimeConfig, run_with_signal_handlers


ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")


@dataclass(frozen=True)
class ServiceConfig:
    runtime: RuntimeConfig
    ws_url: str
    adapter_factory: str
    health_host: str
    health_port: int

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        # Parse values without importing an adapter or opening a socket.
        raw = os.environ.get("SUBSCRIPTIONS", "")
        addresses = tuple(item.strip() for item in raw.split(",") if item.strip())
        evidence_dir = Path(os.environ.get("EVIDENCE_DIR", "./evidence"))
        raw_network = os.environ.get("NETWORK_ENABLED", "false").strip().lower()
        if raw_network not in {"true", "false"}:
            raise ValueError("NETWORK_ENABLED yalnız true veya false olabilir")
        runtime = RuntimeConfig(
            addresses=addresses,
            run_mode=os.environ.get("RUN_MODE", ""),
            network_enabled=raw_network == "true",
            run_duration_seconds=_int_env("RUN_DURATION_SECONDS", "86400"),
            evidence_path=evidence_dir / "dry-run.jsonl",
        )
        return cls(
            runtime=runtime,
            ws_url=os.environ.get("WS_URL", "").strip(),
            adapter_factory=os.environ.get("ADAPTER_FACTORY", "").strip(),
            health_host=os.environ.get("HEALTH_HOST", "127.0.0.1").strip(),
            health_port=_int_env("HEALTH_PORT", "8080"),
        )

    def validate(self, *, starting: bool = False) -> None:
        config = self.runtime
        if config.run_mode != "dry_run":
            raise ValueError("RUN_MODE=dry_run açıkça verilmelidir")
        if len(config.addresses) != 11:
            raise ValueError("SUBSCRIPTIONS tam 11 geçerli 0x adresi içermelidir")
        if len({item.lower() for item in config.addresses}) != 11:
            raise ValueError("SUBSCRIPTIONS adresleri benzersiz olmalıdır")
        if any(not ADDRESS.fullmatch(item) for item in config.addresses):
            raise ValueError("SUBSCRIPTIONS tam 11 geçerli 0x adresi içermelidir")
        if not (0 < config.run_duration_seconds <= 86_400):
            raise ValueError("RUN_DURATION_SECONDS 1..86400 aralığında olmalıdır")
        if not self.health_host or self.health_host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("HEALTH_HOST yalnız loopback olabilir")
        if not (1 <= self.health_port <= 65_535):
            raise ValueError("HEALTH_PORT 1..65535 aralığında olmalıdır")
        if starting:
            config.validate()
            parsed = urlparse(self.ws_url)
            if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
                raise ValueError("başlangıç için açık ws:// veya wss:// WS_URL gereklidir")
            if not self.adapter_factory:
                raise ValueError("başlangıç için ADAPTER_FACTORY=paket.modul:factory gereklidir")


def _int_env(name: str, default: str) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} tam sayı olmalıdır") from exc


def _load_adapter(spec: str, ws_url: str) -> Any:
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("ADAPTER_FACTORY biçimi paket.modul:factory olmalıdır")
    factory = getattr(importlib.import_module(module_name), attribute)
    adapter = factory(ws_url=ws_url)
    required = ("connect", "receive", "backfill", "close")
    if any(not callable(getattr(adapter, name, None)) for name in required):
        raise TypeError("adapter, ReadOnlyAdapter arayüzünü uygulamalıdır")
    return adapter


async def _health_server(runtime: DryRunRuntime, host: str, port: int) -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(reader.readline(), timeout=2)
            parts = request.decode("ascii", "replace").strip().split()
            while await reader.readline() not in (b"\r\n", b"\n", b""):
                pass
            path = parts[1] if len(parts) >= 2 else ""
            if path not in {"/healthz", "/readyz"}:
                status, payload = 404, {"status": "not_found"}
            else:
                snapshot = runtime.health_snapshot()
                if path == "/healthz":
                    payload = {key: snapshot[key] for key in ("status", "mode", "run_id", "uptime_seconds")}
                    status = 200
                else:
                    payload = snapshot
                    status = 200 if snapshot["ready"] else 503
            body = json.dumps(payload, separators=(",", ":")).encode()
            reason = "OK" if status == 200 else "Service Unavailable" if status == 503 else "Not Found"
            writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
        except (asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    return await asyncio.start_server(handle, host, port)


async def serve(config: ServiceConfig) -> dict[str, Any]:
    config.validate(starting=True)
    # The evidence directory is the only intended writable service path.
    config.runtime.evidence_path.parent.mkdir(parents=True, exist_ok=True)
    adapter = _load_adapter(config.adapter_factory, config.ws_url)
    runtime = DryRunRuntime(config.runtime, adapter)
    server = await _health_server(runtime, config.health_host, config.health_port)
    try:
        return await run_with_signal_handlers(runtime)
    finally:
        server.close()
        await server.wait_closed()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicitly run the read-only Faz 3 dry-run service")
    parser.add_argument("--check-config", action="store_true", help="validate config without importing adapter or using network")
    args = parser.parse_args(argv)
    try:
        config = ServiceConfig.from_env()
        config.validate(starting=not args.check_config)
        if args.check_config:
            print(json.dumps({"status": "valid", "mode": "dry_run", "network_enabled": config.runtime.network_enabled,
                              "subscription_count": 11, "duration_seconds": config.runtime.run_duration_seconds,
                              "health_host": config.health_host, "health_port": config.health_port}))
            return 0
        manifest = asyncio.run(serve(config))
        print(json.dumps({"status": "stopped", "mode": "dry_run", "completed": manifest["completed"],
                          "stop_reason": manifest["stop_reason"]}))
        return 0
    except (ValueError, OSError, ImportError, AttributeError, TypeError) as exc:
        print(f"faz3-dry-run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
