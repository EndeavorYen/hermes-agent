def test_visual_regression_report_missing_ledger_is_success(tmp_path):
    from agent.visual.eval_report import build_visual_regression_report

    report = build_visual_regression_report(tmp_path / "missing.sqlite3")

    assert report["success"] is True
    assert report["counts"]["requests"] == 0
    assert report["failures"] == []


def test_visual_regression_report_fails_on_delivery_and_strategy_regressions(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.eval_report import build_visual_regression_report
    from agent.visual.strategy_activation import record_strategy_activation

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    attempt_id = ledger.record_attempt(request_id=request_id, status="completed", provider="fixture", model="image")
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        content_hash="same-hash",
        mime_type="image/png",
        freshness_status="fresh",
        is_stable=True,
    )
    for _ in range(2):
        ledger.record_delivery(
            request_id=request_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            platform="slack",
            destination="C123",
            delivery_status="sent",
        )
    activation_id = record_strategy_activation(
        ledger,
        shadow_update_id="vsh_demo",
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        activation_status="controlled",
        promotion_decision={"decision": "promote_controlled", "allowed": True},
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_id,
        decision="post",
        scores={},
        metadata={
            "strategy_plan": {
                "activation_id": activation_id,
                "prompt_mutation_allowed": True,
            }
        },
    )

    report = build_visual_regression_report(tmp_path / "visual.sqlite3")

    assert report["success"] is False
    assert "duplicate_delivery" in report["failures"]
    assert "missing_source_metadata" in report["failures"]
    assert "prompt_mutation_read" in report["failures"]
    assert report["counts"]["duplicate_deliveries"] == 1
    assert report["counts"]["prompt_mutation_reads"] == 1
