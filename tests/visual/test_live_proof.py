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
    assert proof.counts["missing_request_source_metadata_count"] == 2


def test_live_proof_handles_historical_schema_without_message_id_column(tmp_path):
    from agent.visual.live_proof import verify_visual_agent_live_proof

    ledger_path = tmp_path / "visual.sqlite3"
    _create_historical_live_proof_schema(ledger_path)

    proof = verify_visual_agent_live_proof(
        ledger_path,
        since="2026-06-20T00:00:00Z",
        platform="slack",
        destination_id="D123",
    )

    assert proof.success is False
    assert proof.counts.get("sqlite_error") is None
    assert proof.counts["artifact_kind_counts"] == {"image": 1, "video": 1}
    assert proof.counts["missing_request_source_metadata_count"] == 2
    assert proof.missing == ["missing_request_source_metadata"]
    assert [artifact.request_message_id for artifact in proof.artifacts] == [None, None]


def test_live_proof_can_skip_source_metadata_with_historical_schema(tmp_path):
    from agent.visual.live_proof import verify_visual_agent_live_proof

    ledger_path = tmp_path / "visual.sqlite3"
    _create_historical_live_proof_schema(ledger_path)

    proof = verify_visual_agent_live_proof(
        ledger_path,
        since="2026-06-20T00:00:00Z",
        platform="slack",
        destination_id="D123",
        require_source_metadata=False,
    )

    assert proof.success is True
    assert proof.missing == []
    assert proof.counts["missing_request_source_metadata_count"] == 2


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


def _create_historical_live_proof_schema(path):
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE visual_requests (
                request_id TEXT PRIMARY KEY,
                conversation_id TEXT,
                user_id TEXT,
                platform TEXT,
                channel_id TEXT,
                thread_id TEXT,
                user_prompt TEXT,
                normalized_intent_json TEXT,
                modality TEXT,
                operation TEXT,
                created_at TEXT,
                policy_context_json TEXT,
                status TEXT
            );
            CREATE TABLE visual_artifacts (
                artifact_id TEXT PRIMARY KEY,
                attempt_id TEXT,
                request_id TEXT,
                kind TEXT,
                local_path TEXT,
                source_url TEXT,
                content_hash TEXT,
                perceptual_hash TEXT,
                mime_type TEXT,
                bytes INTEGER,
                width INTEGER,
                height INTEGER,
                duration_ms INTEGER,
                frame_count INTEGER,
                created_at TEXT,
                expires_at TEXT,
                is_stable INTEGER,
                freshness_status TEXT
            );
            CREATE TABLE visual_deliveries (
                delivery_id TEXT PRIMARY KEY,
                request_id TEXT,
                attempt_id TEXT,
                artifact_id TEXT,
                platform TEXT,
                destination_id TEXT,
                thread_id TEXT,
                message_id TEXT,
                delivery_status TEXT,
                error_type TEXT,
                error_message TEXT,
                delivered_at TEXT
            );
            INSERT INTO visual_requests (
                request_id, conversation_id, user_id, platform, channel_id,
                thread_id, user_prompt, normalized_intent_json, modality,
                operation, created_at, policy_context_json, status
            ) VALUES
                (
                    'vrq_image', 'slack:D123', 'U123', 'slack', 'D123',
                    NULL, 'private prompt', '{}', 'image', 'generated',
                    '2026-06-20T00:01:00Z', '{}', 'completed'
                ),
                (
                    'vrq_video', 'slack:D123', 'U123', 'slack', 'D123',
                    NULL, 'private prompt', '{}', 'video', 'generated',
                    '2026-06-20T00:02:00Z', '{}', 'completed'
                );
            INSERT INTO visual_artifacts (
                artifact_id, attempt_id, request_id, kind, local_path,
                source_url, mime_type, is_stable, freshness_status, created_at
            ) VALUES
                (
                    'var_image', 'vat_image', 'vrq_image', 'image',
                    '/tmp/var_image.png', NULL, 'image/png', 1, 'fresh',
                    '2026-06-20T00:01:00Z'
                ),
                (
                    'var_video', 'vat_video', 'vrq_video', 'video',
                    '/tmp/var_video.mp4', NULL, 'video/mp4', 1, 'fresh',
                    '2026-06-20T00:02:00Z'
                );
            INSERT INTO visual_deliveries (
                delivery_id, request_id, attempt_id, artifact_id, platform,
                destination_id, thread_id, message_id, delivery_status,
                delivered_at
            ) VALUES
                (
                    'vdl_image', 'vrq_image', 'vat_image', 'var_image',
                    'slack', 'D123', NULL, 'msg-image', 'sent',
                    '2026-06-20T00:03:00Z'
                ),
                (
                    'vdl_video', 'vrq_video', 'vat_video', 'var_video',
                    'slack', 'D123', NULL, 'msg-video', 'sent',
                    '2026-06-20T00:04:00Z'
                );
            """
        )
