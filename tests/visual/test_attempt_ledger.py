def test_attempt_ledger_records_request_attempt_artifact_and_delivery(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger = VisualAttemptLedger(tmp_path / "attempts.sqlite3")
    ledger.initialize()

    request_id = ledger.record_request(
        user_prompt="redacted user prompt",
        normalized_intent={"modality": "image", "operation": "text_to_image"},
        modality="image",
        operation="text_to_image",
        platform="slack",
        channel_id="C123",
        thread_id="T123",
        user_id="U123",
        message_id="M123",
        conversation_id="slack:C123",
        status="completed",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="xai",
        model="grok-imagine-image",
        prompt_original="redacted user prompt",
        prompt_mediated="compiled prompt",
        parameters_requested={"aspect_ratio": "16:9"},
        parameters_effective={"aspect_ratio": "16:9"},
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/generated.png",
        content_hash="sha256:test",
        mime_type="image/png",
        bytes=12,
        width=1280,
        height=720,
        is_stable=True,
        freshness_status="fresh",
    )
    delivery_id = ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        platform="slack",
        destination_id="C123",
        thread_id="T123",
        message_id="M456",
        delivery_status="sent",
    )

    assert ledger.get_request(request_id)["platform"] == "slack"
    assert ledger.get_request(request_id)["normalized_intent"] == {
        "modality": "image",
        "operation": "text_to_image",
    }
    assert ledger.get_attempt(attempt_id)["provider"] == "xai"
    assert ledger.get_attempt(attempt_id)["parameters_effective"] == {
        "aspect_ratio": "16:9",
    }
    assert ledger.get_artifact(artifact_id)["freshness_status"] == "fresh"
    assert ledger.get_artifact(artifact_id)["is_stable"] is True
    assert ledger.get_delivery(delivery_id)["delivery_status"] == "sent"


def test_attempt_ledger_records_judgment_ranking_and_feedback(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger = VisualAttemptLedger(tmp_path / "attempts.sqlite3")
    ledger.initialize()

    request_id = ledger.record_request(
        normalized_intent={"modality": "image"},
        modality="image",
        operation="text_to_image",
        status="completed",
    )
    attempt_id = ledger.record_attempt(request_id=request_id, provider="xai")
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        content_hash="sha256:test",
    )
    judgment_id = ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="deterministic_judge.v0.1",
        score=0.8,
        verdict="pass",
        details={"fresh": True},
    )
    ranking_id = ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_id,
        decision="post",
        scores={"deterministic": 0.8},
    )
    feedback_id = ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="good composition",
        polarity=1.0,
        parsed={"signals": ["composition_positive"]},
    )

    assert ledger.get_judgment(judgment_id)["details"] == {"fresh": True}
    assert ledger.get_ranking(ranking_id)["scores"] == {"deterministic": 0.8}
    assert ledger.get_feedback(feedback_id)["parsed"] == {
        "signals": ["composition_positive"],
    }
