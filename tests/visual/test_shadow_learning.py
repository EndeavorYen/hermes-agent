def test_shadow_learning_records_proposed_update_without_activation(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.shadow_learning import record_shadow_update

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")

    update_id = record_shadow_update(
        ledger,
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="composition.full_subject_visible@v1",
        proposed_change={"increase_weight": 0.05},
        evidence={"sample_count": 3, "expected_delta": 0.04},
    )

    row = ledger.get_shadow_update(update_id)
    assert row["activation_status"] == "shadow"
    assert row["proposed_change"]["increase_weight"] == 0.05


def test_shadow_learning_never_activates_by_default(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.shadow_learning import record_shadow_update

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")

    update_id = record_shadow_update(
        ledger,
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="composition.full_subject_visible@v1",
        proposed_change={"increase_weight": 0.05},
        evidence={"sample_count": 3},
        activation_status="active",
    )

    assert ledger.get_shadow_update(update_id)["activation_status"] == "shadow"
