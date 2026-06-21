import json


def test_strategy_activation_report_lists_controlled_rows_without_private_prompt(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.strategy_activation import record_strategy_activation
    from scripts.visual_strategy_activation_report import build_strategy_activation_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", user_prompt="private prompt")
    shadow_update_id = ledger.record_shadow_update(
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="composition.full_subject_visible@v1",
        proposed_change={"increase_weight": 0.05},
        evidence={"sample_count": 25},
        confidence=0.9,
    )
    record_strategy_activation(
        ledger,
        shadow_update_id=shadow_update_id,
        intent_signature="visig_demo",
        strategy_signature="composition.full_subject_visible@v1",
        activation_status="controlled",
        promotion_decision={"decision": "promote_controlled", "allowed": True, "reasons": []},
    )

    report = build_strategy_activation_report(tmp_path / "visual.sqlite3")

    assert report["success"] is True
    assert report["strategy_activations"]["count"] == 1
    assert report["strategy_activations"]["controlled_count"] == 1
    assert report["strategy_activations"]["unsafe_count"] == 0
    assert report["strategy_activations"]["top"][0]["activation_status"] == "controlled"
    assert "private prompt" not in json.dumps(report, ensure_ascii=False)


def test_strategy_activation_report_flags_unsafe_controlled_decision(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.strategy_activation import record_strategy_activation
    from scripts.visual_strategy_activation_report import build_strategy_activation_report

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

    report = build_strategy_activation_report(tmp_path / "visual.sqlite3")

    assert report["success"] is False
    assert report["strategy_activations"]["unsafe_count"] == 1


def test_strategy_activation_report_cli_json(capsys, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_strategy_activation_report import main

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()

    code = main(["--db-path", str(tmp_path / "visual.sqlite3"), "--json"])
    out = capsys.readouterr().out

    assert code == 0
    assert '"success": true' in out
