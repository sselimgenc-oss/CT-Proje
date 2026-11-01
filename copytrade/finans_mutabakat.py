"""Salt bellek içi HL gözlem ↔ dahili ledger mutabakatı.

Bu modül ağ, dosya, imzalama ve emir arayüzü içermez. Girdi, dışarıdan
salt-okunur alınmış Hyperliquid state'i ve ledger anlık görüntüsüdür.
Uyumsuzluk ya da eksik veri yeni girişleri engeller; çıkış yetkisi daima açık
kalır. Modül pozisyon düzeltmez ve ledger'ı değiştirmez.
"""
from __future__ import annotations

import math
from typing import Any


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _hl_positions(state: dict[str, Any] | None) -> tuple[dict[str, float], int]:
    rows = state.get("assetPositions") if isinstance(state, dict) else None
    if not isinstance(rows, list):
        return {}, 1
    positions: dict[str, float] = {}
    invalid = 0
    for row in rows:
        p = row.get("position", row) if isinstance(row, dict) else None
        coin = p.get("coin") if isinstance(p, dict) else None
        size = _number(p.get("szi")) if isinstance(p, dict) else None
        if not isinstance(coin, str) or not coin.strip() or size is None:
            invalid += 1
            continue
        coin = coin.strip()
        positions[coin] = positions.get(coin, 0.0) + size
    return {coin: size for coin, size in positions.items() if size}, invalid


def reconcile(ledger: dict[str, Any], observed: dict[str, Any], *,
              balance_abs_tolerance_usd: float, position_abs_tolerance: float,
              max_age_seconds: float | None = None) -> dict[str, Any]:
    """Compare ledger ``balance_usd``/``positions`` to HL clearinghouseState.

    ``observed`` accepts the read-only HL ``clearinghouseState`` shape, with
    optional ``observed_at`` Unix seconds. Position size is signed coin units;
    account value is USD. Any malformed/missing component is fail-closed for
    entries. Tolerances are explicit caller inputs, never hidden defaults.
    """
    if balance_abs_tolerance_usd < 0 or position_abs_tolerance < 0:
        raise ValueError("Mutabakat toleransları negatif olamaz.")
    expected_balance = _number(ledger.get("balance_usd"))
    margin = observed.get("marginSummary", {}) if isinstance(observed, dict) else {}
    actual_balance = _number(margin.get("accountValue")) if isinstance(margin, dict) else None
    balance_diff = (expected_balance - actual_balance
                    if expected_balance is not None and actual_balance is not None else None)

    expected_raw = ledger.get("positions")
    expected: dict[str, float] = {}
    invalid = 0
    if not isinstance(expected_raw, dict):
        invalid += 1
    else:
        for coin, raw_size in expected_raw.items():
            size = _number(raw_size)
            if not isinstance(coin, str) or not coin.strip() or size is None:
                invalid += 1
            else:
                expected[coin.strip()] = size
    actual, bad_hl = _hl_positions(observed)
    invalid += bad_hl
    comparisons = []
    for coin in sorted(set(expected) | set(actual)):
        book, hl = expected.get(coin, 0.0), actual.get(coin, 0.0)
        diff = book - hl
        comparisons.append({"coin": coin, "ledger_size": book, "hl_size": hl,
                            "difference": diff,
                            "matched": abs(diff) <= position_abs_tolerance})

    age_ok = True
    observed_at = _number(observed.get("observed_at")) if isinstance(observed, dict) else None
    now = _number(observed.get("now")) if isinstance(observed, dict) else None
    if max_age_seconds is not None:
        age_ok = (observed_at is not None and now is not None and
                  0 <= now - observed_at <= max_age_seconds)
    balance_ok = (balance_diff is not None and abs(balance_diff) <= balance_abs_tolerance_usd)
    positions_ok = invalid == 0 and all(row["matched"] for row in comparisons)
    matched = balance_ok and positions_ok and age_ok
    return {
        "status": "matched" if matched else "mismatch",
        "expected_balance_usd": expected_balance,
        "observed_balance_usd": actual_balance,
        "balance_difference_usd": balance_diff,
        "balance_matched": balance_ok,
        "positions": comparisons,
        "invalid_rows": invalid,
        "freshness_matched": age_ok,
        "new_entries_allowed": matched,
        "exits_allowed": True,
        "observed_at": observed_at,
        "read_only": True,
    }


EVIDENCE_FIELDS = (
    "record_id", "mode", "source", "source_event_id", "timestamp_utc",
    "coin", "side", "quantity", "price_usd", "fee_usd", "funding_usd",
    "reference_price_usd", "slippage_bps", "ledger_entry_id", "policy_version",
)


def validate_evidence(record: dict[str, Any]) -> list[str]:
    """Return missing/invalid evidence fields; records are append-only by contract."""
    errors = [f"missing:{key}" for key in EVIDENCE_FIELDS if key not in record]
    if record.get("mode") not in {"paper", "real"}:
        errors.append("invalid:mode")
    for key in ("quantity", "price_usd", "fee_usd", "funding_usd", "reference_price_usd", "slippage_bps"):
        if key in record and _number(record[key]) is None:
            errors.append(f"invalid:{key}")
    return errors
