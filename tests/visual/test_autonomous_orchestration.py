from __future__ import annotations


def test_post_generation_orchestration_summarizes_validation_and_next_action(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.autonomous_orchestration import build_post_generation_orchestration

    db_path = tmp_path / "visual.sqlite3"
    ledger = VisualAttemptLedger(db_path)
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="product photo and video",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="fixture",
        model="image",
        prompt_original="prompt",
        prompt_mediated="prompt",
        parameters_requested={},
        parameters_effective={},
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path=str(tmp_path / "image.png"),
        uri=str(tmp_path / "image.png"),
        content_hash="sha256:image",
        mime_type="image/png",
        is_stable=True,
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.9,
        verdict="pass",
        details={"scores": {"aesthetic_fit": 0.9}},
        metadata={"intent_signature": "visig_ok", "strategy_signature": "vstrat_ok", "modality": "image"},
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_id,
        decision="post",
        scores={"reward": {"final_score": 0.9, "confidence": 0.9}},
        metadata={"active_learning": {"action": "auto_post"}},
    )

    report = build_post_generation_orchestration(
        {
            "success": True,
            "visual_request_id": request_id,
            "images": [str(tmp_path / "image.png")],
            "videos": [],
        },
        db_path=db_path,
        require_video=False,
        autonomy_level=2,
    )

    assert report["runtime_hook"] == "post_generation"
    assert report["validation"]["decision"] == "accept"
    assert report["next_action"] == "accept_and_monitor"
    assert report["health"]["artifact_count"] == 1
    assert report["self_review"]["requires_human_input"] is False
    assert "prompt" not in str(report)


def test_post_generation_orchestration_requests_rejudge_when_quality_missing(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.autonomous_orchestration import build_post_generation_orchestration

    db_path = tmp_path / "visual.sqlite3"
    ledger = VisualAttemptLedger(db_path)
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="product photo",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="fixture",
        model="image",
        prompt_original="prompt",
        prompt_mediated="prompt",
        parameters_requested={},
        parameters_effective={},
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path=str(tmp_path / "image.png"),
        uri=str(tmp_path / "image.png"),
        content_hash="sha256:image",
        mime_type="image/png",
        is_stable=True,
        freshness_status="fresh",
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_id,
        decision="post",
        scores={"reward": {"final_score": 0.8, "confidence": 0.8}},
        metadata={"active_learning": {"action": "auto_post"}},
    )

    report = build_post_generation_orchestration(
        {
            "success": True,
            "visual_request_id": request_id,
            "images": [str(tmp_path / "image.png")],
            "videos": [],
        },
        db_path=db_path,
        require_video=False,
        autonomy_level=2,
    )

    assert report["validation"]["decision"] == "retry_or_rejudge"
    assert report["next_action"] == "rejudge_before_delivery"
    assert report["self_review"]["requires_human_input"] is False
