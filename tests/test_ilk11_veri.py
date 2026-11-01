from copytrade.ilk11_veri import form_esle, snapshot_json, snapshot_olustur


def test_form_esle_only_transfers_explicit_semantic_matches():
    form, source = form_esle({
        "hesap_degeri": "12000", "gunluk_islem_sikligi": 2,
        "medyan_tutma_saat": 3.5, "medyan_kaldirac": 4,
        "yonlu_dolum_iyi_orani": 0.75,  # exact completed-trade win rate is not established
        "form_ham": {"ay_roi": 0.12},
    })
    assert form == {
        "golge": None, "ay_roi": 0.12, "hafta_roi": None, "hesap": 12000,
        "dusus": None, "kazanma": None, "siklik": 2, "tutma": 210,
        "kaldirac": 4, "tutarli": None,
    }
    assert source["hesap"] == "hesap_degeri"
    assert source["ay_roi"] == "form_ham.ay_roi"
    assert source["tutma"] == "medyan_tutma_saat*60"
    assert source["kazanma"] is None


def test_explicit_tutma_is_already_in_minutes():
    form, source = form_esle({"medyan_tutma_saat": 3.5, "form_ham": {"tutma": 42}})
    assert form["tutma"] == 42
    assert source["tutma"] == "form_ham.tutma"


def test_snapshot_is_deterministic_frozen_and_has_team_assignments():
    candidates = [
        {"id": f"t-{i:02}", "uygun": True, "hesap_degeri": 1000 + i}
        for i in range(52)
    ]
    source_version = {"secim_surumu": "v1", "kurallar_sha256": "abc"}
    snap = snapshot_olustur(candidates, "2026-11-01T10:00:00Z", source_version)
    serialized = snapshot_json(snap)
    candidates[0]["hesap_degeri"] = 999999
    source_version["secim_surumu"] = "mutated"

    assert snap["as_of"] == "2026-11-01T13:00:00+03:00"
    assert snap["secim_adedi"] == 50
    assert len(snap["kadro"]) == 50
    assert [sum(row["grup"] == group for row in snap["kadro"])
            for group in ("ilk11", "yedek11", "paf")] == [11, 11, 28]
    assert snapshot_json(snap) == serialized


def test_snapshot_rejects_non_sunday_or_wrong_time():
    candidates = [{"id": "x", "uygun": True}]
    versions = {"secim": "v1"}
    for instant in ("2026-11-01T12:00:00+03:00", "2026-11-02T13:00:00+03:00"):
        try:
            snapshot_olustur(candidates, instant, versions)
        except ValueError as error:
            assert "Pazar 13:00" in str(error)
        else:
            raise AssertionError("geçersiz snapshot zamanı kabul edildi")


def test_snapshot_tamper_detection():
    snap = snapshot_olustur([{"id": "x", "uygun": True}],
                            "2026-11-01T13:00:00+03:00", {"secim": "v1"})
    snap["uygun_evren"] = 99
    try:
        snapshot_json(snap)
    except ValueError as error:
        assert "snapshot_id" in str(error)
    else:
        raise AssertionError("değiştirilmiş snapshot kabul edildi")
