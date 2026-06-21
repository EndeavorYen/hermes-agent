from __future__ import annotations


def _seed_request_with_artifacts(ledger, tmp_path, *, count=2, thread_id="1700000000.000100"):
    request_id = ledger.record_request(
        user_prompt="batch",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        platform="slack",
        channel_id="C123",
        thread_id=thread_id,
        message_id="1700000000.000000",
        status="completed",
    )
    artifact_ids = []
    for index in range(count):
        attempt_id = ledger.record_attempt(
            request_id=request_id,
            candidate_index=index,
            provider="xai",
            model="image",
            prompt_original="prompt",
            prompt_mediated="prompt",
            parameters_requested={},
            parameters_effective={},
            status="completed",
        )
        artifact_ids.append(
            ledger.record_artifact(
                request_id=request_id,
                attempt_id=attempt_id,
                kind="image",
                local_path=str(tmp_path / f"image-{index}.jpg"),
                uri=str(tmp_path / f"image-{index}.jpg"),
                content_hash=f"sha256:{index}",
                mime_type="image/jpeg",
                is_stable=True,
                freshness_status="fresh",
            )
        )
    return request_id, artifact_ids


def test_slack_feedback_ingestion_resolves_thread_and_binds_selection(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.slack_feedback_ingestion import ingest_slack_visual_feedback

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id, artifact_ids = _seed_request_with_artifacts(ledger, tmp_path)

    result = ingest_slack_visual_feedback(
        ledger,
        {
            "text": "G2 臉有點怪，但腿不錯，給過",
            "channel": "C123",
            "thread_ts": "1700000000.000100",
            "ts": "1700000000.000200",
            "user": "U999",
        },
    )

    assert result["request_id"] == request_id
    assert result["recorded_feedback_count"] == 1
    row = ledger.get_feedback(result["feedback_ids"][0])
    assert row["artifact_id"] == artifact_ids[1]
    assert row["metadata"]["platform"] == "slack"
    assert row["metadata"]["channel_id"] == "C123"
    assert row["metadata"]["thread_id"] == "1700000000.000100"
    assert row["metadata"]["message_id"] == "1700000000.000200"
    assert "U999" not in str(row)


def test_slack_feedback_ingestion_applies_all_rejected_to_current_artifacts(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.slack_feedback_ingestion import ingest_slack_visual_feedback

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id, artifact_ids = _seed_request_with_artifacts(ledger, tmp_path, count=3)

    result = ingest_slack_visual_feedback(
        ledger,
        {
            "text": "全部退貨，臉不像 reference，也不夠性感",
            "channel": "C123",
            "thread_ts": "1700000000.000100",
            "ts": "1700000000.000300",
        },
    )

    assert result["request_id"] == request_id
    assert result["attribution_scope"] == "all_artifacts"
    assert result["recorded_feedback_count"] == 3
    rows = [ledger.get_feedback(feedback_id) for feedback_id in result["feedback_ids"]]
    assert [row["artifact_id"] for row in rows] == artifact_ids
    assert all(row["polarity"] < 0 for row in rows)


def test_slack_feedback_ingestion_ignores_generic_thread_chat(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.slack_feedback_ingestion import ingest_slack_visual_feedback

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    _seed_request_with_artifacts(ledger, tmp_path)

    result = ingest_slack_visual_feedback(
        ledger,
        {
            "text": "我等一下再看",
            "channel": "C123",
            "thread_ts": "1700000000.000100",
            "ts": "1700000000.000400",
        },
    )

    assert result["success"] is False
    assert result["reason"] == "not_visual_feedback"
    assert ledger._list("visual_feedback") == []
