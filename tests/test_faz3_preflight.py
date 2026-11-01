from copytrade.faz3_preflight import build_preflight_report


def evidence(**overrides):
    values = {
        "team_snapshot": {
            "snapshot_id": "team-1",
            "members": [
                {"id": f"trader-{i}", "grup": "ilk11", "uygun": True}
                for i in range(11)
            ],
        },
        "activation_approval_record": {
            "record_id": "approval-1", "status": "approved", "scope": "dry_run",
            "team_snapshot_id": "team-1",
        },
        "data_freshness": {"fresh": True},
        "reconciliation_result": {"status": "matched", "new_entries_allowed": True},
        "dry_run_duration_hours": 24,
    }
    values.update(overrides)
    return build_preflight_report(**values)


def test_complete_24h_evidence_passes_without_enabling_live():
    report = evidence()
    assert report["status"] == "passed"
    assert report["passed"] is True
    assert report["live_enabled"] is False
    assert report["emir_gonderildi"] is False


def test_missing_or_invalid_required_evidence_fails_closed():
    report = evidence(
        team_snapshot=None,
        activation_approval_record={"record_id": "draft", "status": "draft"},
        data_freshness={"fresh": False},
        reconciliation_result={"status": "mismatch", "new_entries_allowed": False},
        dry_run_duration_hours=23.99,
    )
    assert report["status"] == "failed"
    assert report["passed"] is False
    assert report["live_enabled"] is False
    assert report["emir_gonderildi"] is False
    assert len(report["failures"]) == 5


def test_approval_must_match_team_snapshot_and_duration_must_be_exactly_24h():
    mismatch = evidence(activation_approval_record={
        "record_id": "approval-2", "status": "approved", "scope": "dry_run",
        "team_snapshot_id": "other-team",
    })
    extra = evidence(dry_run_duration_hours=25)
    assert "activation_approval_missing_or_invalid" in mismatch["failures"]
    assert "dry_run_duration_must_be_24_hours" in extra["failures"]


def test_truthy_non_boolean_freshness_does_not_pass():
    report = evidence(data_freshness={"fresh": 1})
    assert report["status"] == "failed"
    assert "data_not_confirmed_fresh" in report["failures"]


def test_team_must_be_exactly_11_eligible_ilk11_members():
    snapshot = {
        "snapshot_id": "team-1",
        "members": [
            {"id": f"trader-{i}", "grup": "ilk11", "uygun": True}
            for i in range(11)
        ],
    }
    wrong_count = evidence(team_snapshot={**snapshot, "members": snapshot["members"][:-1]})
    non_ilk11_members = [*snapshot["members"][:-1],
                        {"id": "trader-10", "grup": "yedek11", "uygun": True}]
    wrong_group = evidence(team_snapshot={**snapshot, "members": non_ilk11_members})

    assert "team_snapshot_missing_or_invalid" in wrong_count["failures"]
    assert "team_snapshot_missing_or_invalid" in wrong_group["failures"]
