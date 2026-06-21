import json


def test_visual_learning_report_is_privacy_safe_and_counts_learning_state(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.strategy_activation import record_strategy_activation
    from scripts.visual_learning_report import build_visual_learning_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="private visual prompt",
        status="completed",
        metadata={"intent_signature": "visig_demo"},
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine",
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/current.png",
        content_hash="sha256:current",
        freshness_status="fresh",
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        platform="slack",
        destination_id="C123",
        delivery_status="sent",
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="good",
        polarity=1.0,
        parsed={},
    )
    shadow_update_id = ledger.record_shadow_update(
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        proposed_change={"type": "prefer_strategy"},
        evidence={"request_count": 20},
        confidence=0.8,
        activation_status="shadow",
    )
    activation_id = record_strategy_activation(
        ledger,
        shadow_update_id=shadow_update_id,
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        activation_status="controlled",
        promotion_decision={"decision": "promote_controlled", "allowed": True, "confidence": 0.8},
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_id,
        decision="post",
        scores={},
        metadata={
            "strategy_signature": "vstrat_demo",
            "active_learning": {"action": "auto_post"},
            "strategy_plan": {
                "activation_id": activation_id,
                "activation_status": "controlled",
                "prompt_mutation_allowed": False,
            },
        },
    )

    report = build_visual_learning_report(tmp_path / "visual.sqlite3")
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["success"] is True
    assert report["learning"]["bucket_count"] == 1
    assert report["learning"]["strategy_count"] == 1
    assert report["learning"]["controlled_strategy_reads"] == 1
    assert report["learning"]["rollback_count"] == 0
    assert report["learning"]["prompt_mutation_reads"] == 0
    assert "private visual prompt" not in encoded


def test_visual_learning_report_fails_on_prompt_mutation_read(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_learning_report import build_visual_learning_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=None,
        decision="post",
        scores={},
        metadata={
            "strategy_signature": "vstrat_demo",
            "strategy_plan": {
                "activation_id": "vsa_unsafe",
                "activation_status": "controlled",
                "prompt_mutation_allowed": True,
            },
        },
    )

    report = build_visual_learning_report(tmp_path / "visual.sqlite3")

    assert report["success"] is False
    assert "prompt_mutation_read" in report["failures"]


def test_visual_learning_report_cli_json(capsys, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_learning_report import main

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()

    code = main(["--db-path", str(tmp_path / "visual.sqlite3"), "--json"])
    out = capsys.readouterr().out

    assert code == 0
    assert '"success": true' in out
