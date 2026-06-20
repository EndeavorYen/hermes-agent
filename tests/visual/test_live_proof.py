from __future__ import annotations


def test_live_proof_passes_when_recent_slack_image_and_video_are_delivered(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.live_proof import verify_visual_agent_live_proof

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    image = _record_delivered_artifact(
        ledger,
        request_id="vrq_image",
        attempt_id="vat_image",
        artifact_id="var_image",
        kind="image",
        destination_id="D123",
        delivered_at="2026-06-20T00:01:00Z",
    )
    video = _record_delivered_artifact(
        ledger,
        request_id="vrq_video",
        attempt_id="vat_video",
        artifact_id="var_video",
        kind="video",
        destination_id="D123",
        delivered_at="2026-06-20T00:02:00Z",
    )

    proof = verify_visual_agent_live_proof(
        ledger.path,
        since="2026-06-20T00:00:00Z",
        platform="slack",
        destination_id="D123",
    )

    assert proof.success is True
    assert proof.missing == []
    assert proof.counts["sent_delivery_count"] == 2
    assert proof.counts["artifact_kind_counts"] == {"image": 1, "video": 1}
    assert [artifact.artifact_id for artifact in proof.artifacts] == [video, image]
    assert proof.artifacts[0].request_platform == "slack"
    assert proof.artifacts[0].request_channel_id == "D123"
    assert proof.artifacts[0].request_user_id == "U123"
    assert proof.artifacts[0].request_message_id == "msg-var_video"
    assert proof.artifacts[0].request_conversation_id == "slack:D123"


def test_live_proof_fails_when_recent_package_has_no_video(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.live_proof import verify_visual_agent_live_proof

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    _record_delivered_artifact(
        ledger,
        request_id="vrq_image",
        attempt_id="vat_image",
        artifact_id="var_image",
        kind="image",
        destination_id="D123",
        delivered_at="2026-06-20T00:01:00Z",
    )

    proof = verify_visual_agent_live_proof(
        ledger.path,
        since="2026-06-20T00:00:00Z",
        platform="slack",
        destination_id="D123",
    )

    assert proof.success is False
    assert proof.missing == ["missing_video_delivery"]
    assert proof.counts["artifact_kind_counts"] == {"image": 1}


def test_live_proof_fails_when_delivery_does_not_join_to_artifact(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.live_proof import verify_visual_agent_live_proof

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    ledger.record_delivery(
        request_id="vrq_missing",
        attempt_id="vat_missing",
        artifact_id="var_missing",
        platform="slack",
        destination_id="D123",
        delivery_status="sent",
        delivered_at="2026-06-20T00:01:00Z",
    )

    proof = verify_visual_agent_live_proof(
        ledger.path,
        since="2026-06-20T00:00:00Z",
        platform="slack",
        destination_id="D123",
    )

    assert proof.success is False
    assert proof.missing == [
        "missing_artifact_join",
        "missing_request_source_metadata",
        "missing_image_delivery",
        "missing_video_delivery",
    ]
    assert proof.counts["missing_artifact_join_count"] == 1
    assert proof.counts["missing_request_source_metadata_count"] == 1


def test_live_proof_fails_when_same_artifact_is_delivered_twice(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.live_proof import verify_visual_agent_live_proof

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    duplicate_image = _record_delivered_artifact(
        ledger,
        request_id="vrq_image",
        attempt_id="vat_image",
        artifact_id="var_image",
        kind="image",
        destination_id="D123",
        delivered_at="2026-06-20T00:01:00Z",
    )
    ledger.record_delivery(
        request_id="vrq_image",
        attempt_id="vat_image",
        artifact_id=duplicate_image,
        platform="slack",
        destination_id="D123",
        delivery_status="sent",
        delivered_at="2026-06-20T00:01:30Z",
    )
    _record_delivered_artifact(
        ledger,
        request_id="vrq_video",
        attempt_id="vat_video",
        artifact_id="var_video",
        kind="video",
        destination_id="D123",
        delivered_at="2026-06-20T00:02:00Z",
    )

    proof = verify_visual_agent_live_proof(
        ledger.path,
        since="2026-06-20T00:00:00Z",
        platform="slack",
        destination_id="D123",
    )

    assert proof.success is False
    assert proof.missing == ["duplicate_artifact_delivery"]
    assert proof.counts["duplicate_artifact_delivery_count"] == 1
    assert proof.duplicate_artifact_ids == [duplicate_image]
    assert proof.to_dict()["duplicate_artifact_ids"] == [duplicate_image]


def test_live_proof_respects_since_window(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.live_proof import verify_visual_agent_live_proof

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    _record_delivered_artifact(
        ledger,
        request_id="vrq_image",
        attempt_id="vat_image",
        artifact_id="var_image",
        kind="image",
        destination_id="D123",
        delivered_at="2026-06-19T23:59:59Z",
    )
    _record_delivered_artifact(
        ledger,
        request_id="vrq_video",
        attempt_id="vat_video",
        artifact_id="var_video",
        kind="video",
        destination_id="D123",
        delivered_at="2026-06-19T23:59:58Z",
    )

    proof = verify_visual_agent_live_proof(
        ledger.path,
        since="2026-06-20T00:00:00Z",
        platform="slack",
        destination_id="D123",
    )

    assert proof.success is False
    assert proof.missing == ["no_sent_deliveries"]
    assert proof.counts["sent_delivery_count"] == 0


def test_live_proof_fails_when_request_source_metadata_is_missing(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.live_proof import verify_visual_agent_live_proof

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    _record_delivered_artifact(
        ledger,
        request_id="vrq_image",
        attempt_id="vat_image",
        artifact_id="var_image",
        kind="image",
        destination_id="D123",
        delivered_at="2026-06-20T00:01:00Z",
        source_metadata=False,
    )
    _record_delivered_artifact(
        ledger,
        request_id="vrq_video",
        attempt_id="vat_video",
        artifact_id="var_video",
        kind="video",
        destination_id="D123",
        delivered_at="2026-06-20T00:02:00Z",
        source_metadata=False,
    )

    proof = verify_visual_agent_live_proof(
        ledger.path,
        since="2026-06-20T00:00:00Z",
        platform="slack",
        destination_id="D123",
    )

    assert proof.success is False
    assert "missing_request_source_metadata" in proof.missing
    assert proof.counts["missing_request_source_metadata_count"] == 2


def test_live_proof_can_skip_source_metadata_for_historical_rows(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.live_proof import verify_visual_agent_live_proof

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    _record_delivered_artifact(
        ledger,
        request_id="vrq_image",
        attempt_id="vat_image",
        artifact_id="var_image",
        kind="image",
        destination_id="D123",
        delivered_at="2026-06-20T00:01:00Z",
        source_metadata=False,
    )
    _record_delivered_artifact(
        ledger,
        request_id="vrq_video",
        attempt_id="vat_video",
        artifact_id="var_video",
        kind="video",
        destination_id="D123",
        delivered_at="2026-06-20T00:02:00Z",
        source_metadata=False,
    )

    proof = verify_visual_agent_live_proof(
        ledger.path,
        since="2026-06-20T00:00:00Z",
        platform="slack",
        destination_id="D123",
        require_source_metadata=False,
    )

    assert proof.success is True
    assert "missing_request_source_metadata" not in proof.missing


def _record_delivered_artifact(
    ledger,
    *,
    request_id: str,
    attempt_id: str,
    artifact_id: str,
    kind: str,
    destination_id: str,
    delivered_at: str,
    source_metadata: bool = True,
) -> str:
    source_kwargs = {}
    if source_metadata:
        source_kwargs = {
            "platform": "slack",
            "channel_id": destination_id,
            "user_id": "U123",
            "message_id": f"msg-{artifact_id}",
            "conversation_id": f"slack:{destination_id}",
        }
    ledger.record_request(
        request_id=request_id,
        user_prompt="product showcase",
        normalized_intent={"modality": kind},
        modality=kind,
        operation="generated",
        created_at=delivered_at,
        **source_kwargs,
    )
    ledger.record_attempt(
        request_id=request_id,
        attempt_id=attempt_id,
        candidate_index=0,
        provider="fake",
        model=f"fake-{kind}",
        prompt_original="product showcase",
        prompt_mediated="product showcase",
        created_at=delivered_at,
    )
    ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        kind=kind,
        local_path=f"/tmp/{artifact_id}.{'mp4' if kind == 'video' else 'png'}",
        mime_type="video/mp4" if kind == "video" else "image/png",
        is_stable=True,
        freshness_status="fresh",
        created_at=delivered_at,
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        platform="slack",
        destination_id=destination_id,
        delivery_status="sent",
        delivered_at=delivered_at,
    )
    return artifact_id
