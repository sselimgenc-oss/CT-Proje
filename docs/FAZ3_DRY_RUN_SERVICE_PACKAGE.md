# Faz 3 dry-run service package

The explicit process entrypoint is `python -m copytrade.faz3_dry_run_service`. Importing it does not start a listener. `--check-config` validates settings without importing an adapter or opening network connections. There is no service manager, scheduled task, container entrypoint, or deployment hook in this package.

## Configuration

Required for a config-only check:

```dotenv
RUN_MODE=dry_run
NETWORK_ENABLED=false
SUBSCRIPTIONS=<comma-separated list of exactly 11 unique 0x addresses>
RUN_DURATION_SECONDS=86400
HEALTH_HOST=127.0.0.1
HEALTH_PORT=8080
EVIDENCE_DIR=./evidence
```

Run `python -m copytrade.faz3_dry_run_service --check-config` to validate this without network use. A service run additionally requires the explicit opt-in `NETWORK_ENABLED=true`, a `WS_URL` using `ws://` or `wss://`, and `ADAPTER_FACTORY=python.module:factory`. The operator-supplied factory is called with `ws_url=...` and must return an object implementing `connect(addresses)`, `receive(timeout_seconds)`, `backfill(plan, addresses)`, and `close()`. No provider client or exchange URL is included in this repository. The adapter's `connect` implementation must be restricted to public/read-only data.

After setting those values in the operator's environment, a run is started only by the explicit command:

```sh
python -m copytrade.faz3_dry_run_service
```

`SIGINT` and `SIGTERM` stop the runtime cleanly; it closes the adapter and flushes a final manifest. `RUN_DURATION_SECONDS` is limited to 1–86400 seconds. Health binds only to loopback; `/healthz` reports process health and `/readyz` returns 503 until connected with a fresh heartbeat. The JSONL evidence file is `EVIDENCE_DIR/dry-run.jsonl`, append-only, and records per-run IDs; the runtime does not store raw provider messages or full source addresses.

The package deliberately does not include a Docker image or Compose file. The configured provider adapter and a pinned, reviewed dependency/image set are prerequisites before a container build can be considered complete. No deployment or 24-hour run was performed as part of packaging.

## Remaining operator/deployment prerequisites

- Select and review a provider-specific public/read-only WebSocket adapter and document its actual subscription/backfill semantics.
- Supply the intended 11 addresses and read-only WebSocket URL in the operator environment; neither is bundled or defaulted.
- Review filesystem ownership/retention for the evidence directory, and choose a process supervisor/container image if needed. Configure any supervisor for explicit/manual invocation with no automatic restart.
- Run an operator-approved network smoke test and the full 24-hour observation separately. This package work did not make external connections.
