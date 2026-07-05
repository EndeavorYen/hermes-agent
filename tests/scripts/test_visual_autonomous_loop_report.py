from __future__ import annotations

import json


def test_visual_autonomous_loop_report_promotes_low_risk_fixture_candidates(tmp_path):
    from scripts.visual_autonomous_loop_report import build_visual_autonomous_loop_report
    from scripts.visual_learning_replay import build_visual_learning_replay

    db_path = tmp_path / "visual.sqlite3"
    replay = build_visual_learning_replay(db_path)
    assert replay["success"] is True

    report = build_visual_autonomous_loop_report(db_path, autonomy_level=2)

    assert report["success"] is True
    assert report["regression"]["success"] is True
    assert report["learning"]["proposal_count"] >= 1
    assert report["rollout"]["controlled_candidate_count"] >= 1
    assert report["self_review"]["reduces_human_intervention"] is True
    assert report["self_review"]["prompt_mutation_allowed"] is False


def test_visual_autonomous_loop_report_cli_json(capsys, tmp_path):
    from scripts.visual_autonomous_loop_report import main
    from scripts.visual_learning_replay import build_visual_learning_replay

    db_path = tmp_path / "visual.sqlite3"
    build_visual_learning_replay(db_path)

    code = main(["--db-path", str(db_path), "--autonomy-level", "2", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["success"] is True
    assert payload["rollout"]["controlled_candidate_count"] >= 1


def test_visual_autonomous_loop_report_fails_closed_on_regression_failure(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_autonomous_loop_report import build_visual_autonomous_loop_report

    db_path = tmp_path / "visual.sqlite3"
    ledger = VisualAttemptLedger(db_path)
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="test",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="completed",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="xai",
        model="image",
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path=str(tmp_path / "image.jpg"),
        uri=str(tmp_path / "image.jpg"),
        content_hash="sha256:dup",
        mime_type="image/jpeg",
        is_stable=True,
        freshness_status="fresh",
    )
    for _ in range(2):
        ledger.record_delivery(
            request_id=request_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            platform="slack",
            destination_id="C_TEST",
            thread_id="T_TEST",
            delivery_status="sent",
        )

    report = build_visual_autonomous_loop_report(db_path, autonomy_level=2)

    assert report["success"] is False
    assert "regression_failed" in report["failures"]
    assert report["regression"]["counts"]["duplicate_deliveries"] == 1
