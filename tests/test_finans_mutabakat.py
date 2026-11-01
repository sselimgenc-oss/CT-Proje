from copytrade.finans_mutabakat import reconcile, validate_evidence


def test_hl_ledger_uyumlu_kapilar_acik():
    result = reconcile(
        {"balance_usd": 100.0, "positions": {"BTC": 0.2}},
        {"marginSummary": {"accountValue": "100.01"},
         "assetPositions": [{"position": {"coin": "BTC", "szi": "0.2"}}]},
        balance_abs_tolerance_usd=0.02, position_abs_tolerance=0.001,
    )
    assert result["status"] == "matched"
    assert result["new_entries_allowed"] is True
    assert result["exits_allowed"] is True


def test_mismatch_stale_ve_bozuk_veri_girisleri_kapatir_cikislari_acik_tutar():
    result = reconcile(
        {"balance_usd": 100.0, "positions": {"BTC": 0.2}},
        {"marginSummary": {"accountValue": "90"},
         "assetPositions": [{"position": {"coin": "BTC", "szi": "-0.2"}}, {}],
         "observed_at": 10, "now": 20},
        balance_abs_tolerance_usd=0.01, position_abs_tolerance=0.001,
        max_age_seconds=5,
    )
    assert result["status"] == "mismatch"
    assert result["invalid_rows"] == 1
    assert result["freshness_matched"] is False
    assert result["new_entries_allowed"] is False
    assert result["exits_allowed"] is True


def test_evidence_kaydi_mod_ve_maliyet_alanlarini_zorunlu_tutar():
    record = dict.fromkeys(("record_id", "mode", "source", "source_event_id", "timestamp_utc",
                            "coin", "side", "quantity", "price_usd", "fee_usd", "funding_usd",
                            "reference_price_usd", "slippage_bps", "ledger_entry_id", "policy_version"))
    record.update(mode="real", quantity=1, price_usd=10, fee_usd=0.1, funding_usd=0,
                  reference_price_usd=9.9, slippage_bps=100)
    assert validate_evidence(record) == []
    record["mode"] = "live"
    assert "invalid:mode" in validate_evidence(record)
