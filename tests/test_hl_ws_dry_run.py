import pytest

from copytrade.hl_ws_dry_run import IngestionState, MemoryEventIdStore, evaluate_dry_run, normalize_message


def msg(*fills):
    return {"channel": "userFills", "data": {"user": "0xAbC", "fills": list(fills)}}


def fill(tid, time, **extra):
    return {"coin": "BTC", "side": "B", "px": "100", "sz": "0.25", "time": time,
            "oid": 7, "tid": tid, **extra}


def test_normalizes_hl_user_fills_and_stable_event_identity():
    got = normalize_message(msg(fill(99, 1000)))
    assert len(got) == 1
    assert (got[0].event_id, got[0].trader, got[0].price, got[0].size) == ("0xabc:99", "0xabc", 100, .25)


@pytest.mark.parametrize("bad", [None, {}, {"channel": "orders", "data": {"fills": []}},
                                  {"channel": "userFills", "data": {"fills": [fill(1, 0, sz="nan")]}}])
def test_invalid_message_or_fill_rejected(bad):
    with pytest.raises(ValueError):
        normalize_message(bad)


def test_dedup_and_out_of_order_are_reported_and_overlap_is_planned():
    state = IngestionState(MemoryEventIdStore())
    first = normalize_message(msg(fill(1, 2000), fill(2, 1000)))
    out = state.ingest(first)
    assert [e.event_id for e in out.accepted] == ["0xabc:1", "0xabc:2"]
    assert out.out_of_order == ("0xabc:2",)
    assert state.ingest(first).duplicates == ("0xabc:1", "0xabc:2")
    assert state.reconnect_backfill_plan(now_ms=5000, overlap_ms=300) == {
        "kind": "read_only_backfill_request", "start_ms": 1700, "end_ms": 5000,
        "after_event_time_ms": 2000}


def test_proposal_is_dry_run_only_and_cutoffs_reject_late_or_stale_events():
    event = normalize_message(msg(fill(5, 1000)))[0]
    ok = evaluate_dry_run(event, now_ms=1500, max_age_ms=1000, late_cutoff_ms=2000)
    assert ok["kind"] == "dry_run_proposal" and ok["order_sent"] is False
    assert ok["exchange_post_performed"] is False
    late = evaluate_dry_run(event, now_ms=2501, max_age_ms=1000, late_cutoff_ms=1000)
    assert late["kind"] == "dry_run_rejection"
    assert late["reasons"] == ["stale_event", "late_cutoff"]


def test_event_without_unique_identity_is_rejected():
    row = fill(None, 1000)
    row.pop("tid")
    row.pop("oid")
    with pytest.raises(ValueError, match="idempotency"):
        normalize_message(msg(row))
