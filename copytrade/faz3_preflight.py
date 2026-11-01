"""Pure validation for the Faz 3 24-hour dry-run preflight.

This module consumes already-produced in-memory evidence only. It performs no
I/O and cannot activate live trading; a successful report means only that the
provided preflight evidence passed these checks.
"""
from __future__ import annotations

import math
from typing import Any


REQUIRED_DRY_RUN_HOURS = 24
REQUIRED_TEAM_SIZE = 11
ILK11_GROUP = "ilk11"


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def build_preflight_report(*, team_snapshot: Any,
                           activation_approval_record: Any,
                           data_freshness: Any,
                           reconciliation_result: Any,
                           dry_run_duration_hours: Any) -> dict[str, Any]:
    """Validate required preflight evidence and return a fail-closed summary.

    Input contract:
    - team snapshot: ``snapshot_id`` and exactly 11 ``members``. Each member
      is a dict with a unique non-empty ``id``, ``grup='ilk11'``, and
      ``uygun is True`` (the İlk 11 eligibility marker from the roster);
    - approval: ``record_id``, ``status='approved'``, ``scope='dry_run'`` and
      matching ``team_snapshot_id``;
    - freshness: explicit ``fresh is True``;
    - reconciliation: ``status='matched'`` and ``new_entries_allowed is True``;
    - duration: exactly 24 hours.

    The approval is evidence for this dry-run preflight only; this function
    never infers or grants live authorization.
    """
    failures: list[str] = []

    snapshot_id = team_snapshot.get("snapshot_id") if isinstance(team_snapshot, dict) else None
    members = team_snapshot.get("members") if isinstance(team_snapshot, dict) else None
    team_valid = (
        isinstance(members, list)
        and len(members) == REQUIRED_TEAM_SIZE
        and all(
            isinstance(member, dict)
            and _nonempty_string(member.get("id"))
            and member.get("grup") == ILK11_GROUP
            and member.get("uygun") is True
            for member in members
        )
    )
    if team_valid:
        member_ids = [member["id"] for member in members]
        team_valid = len(set(member_ids)) == REQUIRED_TEAM_SIZE
    if not _nonempty_string(snapshot_id) or not team_valid:
        failures.append("team_snapshot_missing_or_invalid")

    approval = activation_approval_record
    if not isinstance(approval, dict):
        failures.append("activation_approval_missing_or_invalid")
    else:
        if (not _nonempty_string(approval.get("record_id"))
                or approval.get("status") != "approved"
                or approval.get("scope") != "dry_run"
                or not _nonempty_string(snapshot_id)
                or approval.get("team_snapshot_id") != snapshot_id):
            failures.append("activation_approval_missing_or_invalid")

    if not isinstance(data_freshness, dict) or data_freshness.get("fresh") is not True:
        failures.append("data_not_confirmed_fresh")

    if (not isinstance(reconciliation_result, dict)
            or reconciliation_result.get("status") != "matched"
            or reconciliation_result.get("new_entries_allowed") is not True):
        failures.append("reconciliation_not_matched")

    try:
        duration = float(dry_run_duration_hours)
    except (TypeError, ValueError):
        duration = math.nan
    if not math.isfinite(duration) or duration != REQUIRED_DRY_RUN_HOURS:
        failures.append("dry_run_duration_must_be_24_hours")

    passed = not failures
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "failures": failures,
        "dry_run_duration_hours": duration if math.isfinite(duration) else None,
        "required_dry_run_duration_hours": REQUIRED_DRY_RUN_HOURS,
        "live_enabled": False,
        "emir_gonderildi": False,
        "read_only_validation": True,
    }
