def test_self_validation_fails_when_reward_trace_missing(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.self_validation import run_visual_self_validation

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        status="completed",
        provider="fixture",
        model="image",
    )
    ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/current.png",
        content_hash="abc",
        mime_type="image/png",
        freshness_status="fresh",
        is_stable=True,
    )

    result = run_visual_self_validation(tmp_path / "visual.sqlite3", request_id=request_id)

    assert result["success"] is False
    assert "missing_reward_trace" in result["failures"]


def test_self_validation_fails_for_unsafe_controlled_strategy_activation(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.self_validation import run_visual_self_validation
    from agent.visual.strategy_activation import record_strategy_activation

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    record_strategy_activation(
        ledger,
        shadow_update_id="vsh_demo",
        intent_signature="visig_demo",
        strategy_signature="composition.full_subject_visible@v1",
        activation_status="controlled",
        promotion_decision={"decision": "shadow_only", "allowed": False},
    )

    result = run_visual_self_validation(tmp_path / "visual.sqlite3")

    assert result["success"] is False
    assert "unsafe_strategy_activation" in result["failures"]
