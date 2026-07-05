from __future__ import annotations


def test_autonomous_validation_accepts_complete_package(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.autonomous_validation import validate_visual_generation_payload

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
        provider="xai",
        model="grok-imagine-image-quality",
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
        local_path=str(tmp_path / "image.jpg"),
        uri=str(tmp_path / "image.jpg"),
        content_hash="sha256:ok",
        mime_type="image/jpeg",
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
    ledger.record_shadow_update(
        request_id=request_id,
        intent_signature="visig_ok",
        strategy_signature="vstrat_ok",
        proposed_change={"type": "strategy_observation"},
        evidence={"selected_artifact_id": artifact_id},
        confidence=0.9,
        activation_status="shadow",
    )

    report = validate_visual_generation_payload(
        {
            "success": True,
            "visual_request_id": request_id,
            "images": [str(tmp_path / "image.jpg")],
            "videos": [],
        },
        db_path=db_path,
        require_video=False,
    )

    assert report["success"] is True
    assert report["decision"] == "accept"
    assert report["failures"] == []
    assert report["evidence"]["judgment_count"] == 1
    assert report["evidence"]["learning_trace_count"] == 1


def test_autonomous_validation_retries_missing_judgment(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.autonomous_validation import validate_visual_generation_payload

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
        provider="xai",
        model="grok-imagine-image-quality",
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
        local_path=str(tmp_path / "image.jpg"),
        uri=str(tmp_path / "image.jpg"),
        content_hash="sha256:missing-judge",
        mime_type="image/jpeg",
        is_stable=True,
        freshness_status="fresh",
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_id,
        decision="post",
        scores={"reward": {"final_score": 0.9, "confidence": 0.9}},
        metadata={"active_learning": {"action": "auto_post"}},
    )

    report = validate_visual_generation_payload(
        {
            "success": True,
            "visual_request_id": request_id,
            "images": [str(tmp_path / "image.jpg")],
            "videos": [],
        },
        db_path=db_path,
        require_video=False,
    )

    assert report["success"] is False
    assert report["decision"] == "retry_or_rejudge"
    assert "missing_quality_judgments" in report["failures"]


def test_autonomous_validation_requests_generation_retry_when_selected_media_missing(tmp_path):
    from agent.visual.autonomous_validation import validate_visual_generation_payload

    report = validate_visual_generation_payload(
        {"success": False, "visual_request_id": "vrq_missing", "images": [], "videos": []},
        db_path=tmp_path / "missing.sqlite3",
        require_video=False,
    )

    assert report["success"] is False
    assert report["decision"] == "retry_generation"
    assert "provider_generation_failed" in report["failures"]
    assert "missing_image_output" in report["failures"]
