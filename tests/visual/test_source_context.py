from __future__ import annotations


def test_source_context_round_trips_gateway_fields():
    from agent.visual.source_context import (
        VisualSourceContext,
        clear_visual_source_context,
        get_visual_source_context,
        set_visual_source_context,
    )

    clear_visual_source_context()
    context = VisualSourceContext(
        platform="slack",
        channel_id="D123",
        thread_id="1710000000.000100",
        user_id="U123",
        message_id="1710000000.000200",
        conversation_id="slack:D123",
    )

    token = set_visual_source_context(context)
    try:
        assert get_visual_source_context() == context
    finally:
        clear_visual_source_context(token)

    assert get_visual_source_context() is None


def test_source_context_normalizes_platform_and_empty_fields():
    from agent.visual.source_context import VisualSourceContext

    context = VisualSourceContext(
        platform=" Slack ",
        channel_id="",
        thread_id=" ",
        user_id=None,
        message_id="1710000000.000200",
        conversation_id=" ",
    )

    assert context.platform == "slack"
    assert context.channel_id is None
    assert context.thread_id is None
    assert context.user_id is None
    assert context.message_id == "1710000000.000200"
    assert context.conversation_id is None


def test_tracking_records_source_context_on_new_request(tmp_path, monkeypatch):
    from agent.visual import tracking
    from agent.visual.artifact_store import ArtifactStore
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.source_context import (
        VisualSourceContext,
        clear_visual_source_context,
        set_visual_source_context,
    )

    ledger_path = tmp_path / "visual.sqlite3"
    artifact_root = tmp_path / "artifacts"
    generated = tmp_path / "generated.gif"
    generated.write_bytes(b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")

    monkeypatch.setattr(tracking, "default_visual_ledger_path", lambda: ledger_path)
    monkeypatch.setattr(
        tracking,
        "ArtifactStore",
        lambda: ArtifactStore(artifact_root),
    )
    token = set_visual_source_context(
        VisualSourceContext(
            platform="Slack",
            channel_id="D123",
            thread_id="1710000000.000100",
            user_id="U123",
            message_id="1710000000.000200",
            conversation_id="slack:D123",
        )
    )
    try:
        payload = tracking.record_visual_generation_attempt(
            {
                "success": True,
                "image_path": str(generated),
                "provider": "fake",
                "model": "fake-image",
            },
            user_prompt="clean product photo",
            prompt_original="clean product photo",
            prompt_mediated="clean product photo",
            modality="image",
            operation="text_to_image",
            artifact_key="image_path",
            kind="image",
        )
    finally:
        clear_visual_source_context(token)

    ledger = VisualAttemptLedger(ledger_path)
    request = ledger.get_request(payload["visual_request_id"])
    assert request["platform"] == "slack"
    assert request["channel_id"] == "D123"
    assert request["thread_id"] == "1710000000.000100"
    assert request["user_id"] == "U123"
    assert request["message_id"] == "1710000000.000200"
    assert request["conversation_id"] == "slack:D123"
