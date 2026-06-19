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


def test_records_feedback_against_delivered_artifact(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.feedback import parse_visual_feedback

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="fashion editorial portrait",
        normalized_intent={"modality": "image"},
        modality="image",
        operation="text_to_image",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="fake",
        model="fake-image",
        prompt_original="fashion editorial portrait",
        prompt_mediated="fashion editorial portrait",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/out.png",
        content_hash="sha256:test",
        mime_type="image/png",
        bytes=10,
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

    parsed = parse_visual_feedback("第二張不錯，保留這個方向")
    feedback_id = ledger.record_feedback_for_delivery(
        delivery_id,
        raw_text=parsed.raw_text,
        parsed_feedback=parsed,
    )

    feedback = ledger.get_feedback(feedback_id)
    assert feedback["request_id"] == request_id
    assert feedback["attempt_id"] == attempt_id
    assert feedback["artifact_id"] == artifact_id
    assert feedback["platform"] == "slack"
    assert feedback["raw_text"] == "第二張不錯，保留這個方向"
    assert feedback["parsed"]["selection_hint"] == 2


def test_builds_delivery_metadata_for_latest_request_artifacts(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    old_request = _record_artifact_fixture(
        ledger,
        request_id="vrq_old",
        attempt_id="vat_old",
        artifact_id="var_old",
        local_path="/tmp/old.png",
        content_hash="sha256:old",
        created_at="2026-06-19T01:00:00Z",
    )
    new_request = _record_artifact_fixture(
        ledger,
        request_id="vrq_new",
        attempt_id="vat_new",
        artifact_id="var_new",
        local_path="/tmp/new.png",
        content_hash="sha256:new",
        created_at="2026-06-19T02:00:00Z",
    )

    metadata = ledger.build_delivery_metadata_for_urls(
        ["file:///tmp/old.png", "file:///tmp/new.png"]
    )

    assert old_request == "vrq_old"
    assert new_request == "vrq_new"
    assert metadata["visual_request_id"] == "vrq_new"
    assert metadata["selected_visual_artifact_ids"] == ["var_new"]
    assert metadata["visual_artifacts"]["file:///tmp/old.png"]["artifact_id"] == "var_old"
    assert metadata["visual_artifacts"]["file:///tmp/new.png"]["artifact_id"] == "var_new"


def _record_artifact_fixture(
    ledger,
    *,
    request_id: str,
    attempt_id: str,
    artifact_id: str,
    local_path: str,
    content_hash: str,
    created_at: str,
) -> str:
    ledger.record_request(
        request_id=request_id,
        user_prompt="fashion editorial portrait",
        normalized_intent={"modality": "image"},
        modality="image",
        operation="text_to_image",
        created_at=created_at,
    )
    ledger.record_attempt(
        request_id=request_id,
        attempt_id=attempt_id,
        candidate_index=0,
        provider="fake",
        model="fake-image",
        prompt_original="fashion editorial portrait",
        prompt_mediated="fashion editorial portrait",
        created_at=created_at,
    )
    ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        kind="image",
        local_path=local_path,
        content_hash=content_hash,
        mime_type="image/png",
        bytes=10,
        is_stable=True,
        freshness_status="fresh",
        created_at=created_at,
    )
    return request_id
