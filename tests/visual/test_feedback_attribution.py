from __future__ import annotations


def test_feedback_attribution_binds_one_based_index_to_artifact(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.feedback_attribution import record_visual_feedback_for_request

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="batch",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
    )
    artifact_ids = []
    for index in range(2):
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

    feedback_id = record_visual_feedback_for_request(
        ledger,
        request_id=request_id,
        feedback_text="第 2 張臉不自然，但腿不錯",
    )

    row = ledger.get_feedback(feedback_id)
    assert row["artifact_id"] == artifact_ids[1]
    assert row["polarity"] > 0
    assert row["parsed"]["issues"] == ["face_unnatural"]
    assert row["parsed"]["signals"] == ["legs_positive"]
    assert row["parsed"]["attribution"]["method"] == "selection_hint"


def test_feedback_attribution_records_unbound_feedback_privacy_safe(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.feedback_attribution import record_visual_feedback_for_request

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="batch",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
    )

    feedback_id = record_visual_feedback_for_request(
        ledger,
        request_id=request_id,
        feedback_text="整體差評，像舊圖",
    )

    row = ledger.get_feedback(feedback_id)
    assert row["artifact_id"] is None
    assert row["polarity"] < 0
    assert "stale_repost" in row["parsed"]["issues"]
    assert "batch" not in str(row["parsed"])
