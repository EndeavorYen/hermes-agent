from __future__ import annotations


def test_ledger_initializes_expected_tables(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    db = tmp_path / "visual.sqlite3"
    ledger = VisualAttemptLedger(db)
    ledger.initialize()

    tables = ledger.table_names()
    assert {
        "visual_schema_meta",
        "visual_requests",
        "visual_attempts",
        "visual_artifacts",
        "visual_judgments",
        "visual_rankings",
        "visual_deliveries",
        "visual_feedback",
    }.issubset(tables)


def test_records_request_attempt_artifact_and_delivery(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="fashion editorial portrait",
        normalized_intent={"modality": "image"},
        modality="image",
        operation="text_to_image",
        platform="slack",
        channel_id="C123",
        thread_id="171000.0001",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="fake",
        model="fake-image",
        prompt_original="fashion editorial portrait",
        prompt_mediated="fashion editorial portrait",
        parameters_requested={"aspect_ratio": "portrait"},
        parameters_effective={"aspect_ratio": "portrait"},
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/out.png",
        content_hash="sha256:test",
        mime_type="image/png",
        bytes=10,
        width=1024,
        height=1536,
        is_stable=True,
        freshness_status="fresh",
    )
    delivery_id = ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        platform="slack",
        destination_id="C123",
        thread_id="171000.0001",
        message_id="171000.0002",
        delivery_status="sent",
    )

    assert ledger.get_request(request_id)["status"] == "pending"
    assert ledger.get_request(request_id)["normalized_intent"] == {"modality": "image"}
    assert ledger.get_attempt(attempt_id)["provider"] == "fake"
    assert ledger.get_attempt(attempt_id)["parameters_requested"] == {"aspect_ratio": "portrait"}
    assert ledger.get_artifact(artifact_id)["freshness_status"] == "fresh"
    assert ledger.get_artifact(artifact_id)["is_stable"] is True
    assert ledger.get_delivery(delivery_id)["delivery_status"] == "sent"
