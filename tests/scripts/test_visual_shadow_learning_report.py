import json


def test_shadow_learning_report_is_private_safe(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.shadow_learning import record_shadow_update
    from scripts.visual_shadow_learning_report import build_shadow_learning_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", user_prompt="private raw prompt")
    record_shadow_update(
        ledger,
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="composition.full_subject_visible@v1",
        proposed_change={"increase_weight": 0.05},
        evidence={"sample_count": 3, "reason": "composition_positive"},
        confidence=0.4,
    )

    report = build_shadow_learning_report(tmp_path / "visual.sqlite3", request_id=request_id)

    assert report["success"] is True
    assert report["shadow_updates"]["count"] == 1
    assert report["shadow_updates"]["active_count"] == 0
    assert report["shadow_updates"]["top"][0]["activation_status"] == "shadow"
    assert "private raw prompt" not in json.dumps(report, ensure_ascii=False)
