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


def test_slack_feedback_ingestion_binds_quality_praise_to_selected_artifact_and_prompt_arsenal(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.slack_feedback_ingestion import ingest_slack_visual_feedback

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id, artifact_ids = _seed_request_with_artifacts(ledger, tmp_path)
    selected_artifact_id = artifact_ids[1]
    selected_artifact = ledger.get_artifact(selected_artifact_id)
    ledger.record_ranking(
        request_id=request_id,
        selected_attempt_id=selected_artifact["attempt_id"],
        selected_artifact_id=selected_artifact_id,
        decision="post",
        scores={"reward": {"final_score": 0.91}},
        metadata={
            "strategy_signature": "vstrat_success",
            "strategy_plan": {
                "intent_signature": "visig_success",
                "strategy_signature": "vstrat_success",
            },
        },
    )

    result = ingest_slack_visual_feedback(
        ledger,
        {
            "text": "這次的產圖品質很棒!",
            "channel": "C123",
            "thread_ts": "1700000000.000100",
            "ts": "1700000000.000250",
        },
    )

    assert result["success"] is True
    assert result["recorded_feedback_count"] == 1
    row = ledger.get_feedback(result["feedback_ids"][0])
    assert row["artifact_id"] == selected_artifact_id
    assert row["polarity"] > 0
    assert "general_positive" in row["parsed"]["signals"]
    updates = ledger._list("visual_shadow_updates")
    assert len(updates) == 1
    update = updates[0]
    assert update["request_id"] == request_id
    assert update["intent_signature"] == "visig_success"
    assert update["strategy_signature"] == "vstrat_success"
    assert update["proposed_change"]["type"] == "approved_prompt_arsenal_entry"
    assert update["evidence"]["artifact_id"] == selected_artifact_id
    assert update["evidence"]["prompt_mediated"] == "prompt"


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


def test_slack_reaction_ingestion_binds_delivery_message_to_artifact(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.slack_feedback_ingestion import ingest_slack_visual_reaction

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id, artifact_ids = _seed_request_with_artifacts(ledger, tmp_path, count=1)
    ledger.record_delivery(
        request_id=request_id,
        artifact_id=artifact_ids[0],
        platform="slack",
        destination_id="C123",
        thread_id="1700000000.000100",
        message_id="1700000000.000500",
        delivery_status="sent",
    )

    result = ingest_slack_visual_reaction(
        ledger,
        {
            "reaction": "thumbsup",
            "item": {"channel": "C123", "ts": "1700000000.000500"},
            "event_ts": "1700000000.000600",
            "user": "U999",
        },
    )

    assert result["success"] is True
    row = ledger.get_feedback(result["feedback_ids"][0])
    assert row["request_id"] == request_id
    assert row["artifact_id"] == artifact_ids[0]
    assert row["polarity"] > 0
    assert row["metadata"]["source"] == "slack_reaction_ingestion"
    assert "U999" not in str(row)


def test_slack_reaction_ingestion_ignores_unknown_emoji(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.slack_feedback_ingestion import ingest_slack_visual_reaction

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()

    result = ingest_slack_visual_reaction(
        ledger,
        {"reaction": "eyes", "item": {"channel": "C123", "ts": "1700000000.000500"}},
    )

    assert result["success"] is False
    assert result["reason"] == "unsupported_reaction"
