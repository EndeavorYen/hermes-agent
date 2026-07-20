from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform
from tools.send_message_tool import _send_to_platform


@pytest.mark.asyncio
async def test_send_to_platform_forwards_slack_media_to_plugin(tmp_path):
    from gateway.platform_registry import platform_registry
    from hermes_cli.plugins import discover_plugins

    discover_plugins()
    image = tmp_path / "candidate.jpg"
    image.write_bytes(b"jpeg")
    sender = AsyncMock(
        return_value={"success": True, "platform": "slack", "uploaded_files": 1}
    )
    entry = platform_registry.get("slack")
    original = entry.standalone_sender_fn
    entry.standalone_sender_fn = sender
    try:
        result = await _send_to_platform(
            Platform.SLACK,
            SimpleNamespace(enabled=True, token="token", extra={}),
            "D123456789",
            "qualified candidate",
            thread_id="123.456",
            media_files=[(str(image), False)],
        )
    finally:
        entry.standalone_sender_fn = original

    assert result["success"] is True
    sender.assert_awaited_once_with(
        SimpleNamespace(enabled=True, token="token", extra={}),
        "D123456789",
        "qualified candidate",
        thread_id="123.456",
        media_files=[(str(image), False)],
        force_document=False,
    )


@pytest.mark.asyncio
async def test_slack_standalone_sender_uploads_media_with_comment(monkeypatch, tmp_path):
    import plugins.platforms.slack.adapter as slack_mod

    first = tmp_path / "xai-one.jpg"
    second = tmp_path / "xai-two.jpg"
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    client = MagicMock()
    client.files_upload_v2 = AsyncMock(
        return_value={"ok": True, "files": [{"id": "F1"}, {"id": "F2"}]}
    )
    client_factory = MagicMock(return_value=client)
    apply_proxy = MagicMock()
    monkeypatch.setattr(slack_mod, "AsyncWebClient", client_factory)
    monkeypatch.setattr(slack_mod, "_resolve_slack_proxy_url", lambda: "http://proxy")
    monkeypatch.setattr(slack_mod, "_apply_slack_proxy", apply_proxy)
    monkeypatch.setattr(
        slack_mod.aiohttp,
        "ClientSession",
        MagicMock(side_effect=AssertionError("media must not use chat.postMessage")),
    )

    result = await slack_mod._standalone_send(
        SimpleNamespace(token="token"),
        "D123456789",
        "**three** qualified candidates",
        thread_id="123.456",
        media_files=[(str(first), False), (str(second), False)],
    )

    assert result == {
        "success": True,
        "platform": "slack",
        "chat_id": "D123456789",
        "uploaded_files": 2,
    }
    client_factory.assert_called_once_with(token="token")
    apply_proxy.assert_called_once_with(client, "http://proxy")
    client.files_upload_v2.assert_awaited_once_with(
        channel="D123456789",
        file_uploads=[
            {"file": str(first), "filename": "xai-one.jpg"},
            {"file": str(second), "filename": "xai-two.jpg"},
        ],
        initial_comment="*three* qualified candidates",
        thread_ts="123.456",
    )


@pytest.mark.asyncio
async def test_slack_standalone_sender_batches_more_than_ten_files(monkeypatch, tmp_path):
    import plugins.platforms.slack.adapter as slack_mod

    media_files = []
    for index in range(11):
        path = tmp_path / f"candidate-{index}.jpg"
        path.write_bytes(str(index).encode())
        media_files.append((str(path), False))

    client = MagicMock()
    client.files_upload_v2 = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(slack_mod, "AsyncWebClient", MagicMock(return_value=client))

    result = await slack_mod._standalone_send(
        SimpleNamespace(token="token"),
        "D123456789",
        "qualified candidates",
        thread_id="123.456",
        media_files=media_files,
    )

    assert result["success"] is True
    assert result["uploaded_files"] == 11
    assert client.files_upload_v2.await_count == 2
    first, second = client.files_upload_v2.await_args_list
    assert len(first.kwargs["file_uploads"]) == 10
    assert first.kwargs["initial_comment"] == "qualified candidates"
    assert len(second.kwargs["file_uploads"]) == 1
    assert second.kwargs["initial_comment"] == ""


@pytest.mark.asyncio
async def test_slack_standalone_sender_reports_partial_batch_without_retry_signal(
    monkeypatch,
    tmp_path,
):
    import plugins.platforms.slack.adapter as slack_mod

    media_files = []
    for index in range(11):
        path = tmp_path / f"candidate-{index}.jpg"
        path.write_bytes(str(index).encode())
        media_files.append((str(path), False))

    client = MagicMock()
    client.files_upload_v2 = AsyncMock(
        side_effect=[{"ok": True}, RuntimeError("second batch failed")]
    )
    monkeypatch.setattr(slack_mod, "AsyncWebClient", MagicMock(return_value=client))

    result = await slack_mod._standalone_send(
        SimpleNamespace(token="token"),
        "D123456789",
        "qualified candidates",
        thread_id="123.456",
        media_files=media_files,
    )

    assert result["success"] is True
    assert result["partial"] is True
    assert result["uploaded_files"] == 10
    assert result["warnings"] == ["Slack file upload stopped after a partial batch"]


@pytest.mark.asyncio
async def test_slack_media_is_sent_before_remaining_text_chunks(tmp_path):
    from gateway.platform_registry import platform_registry
    from hermes_cli.plugins import discover_plugins

    discover_plugins()
    image = tmp_path / "candidate.jpg"
    image.write_bytes(b"jpeg")
    sender = AsyncMock(
        side_effect=[
            {
                "success": True,
                "partial": True,
                "platform": "slack",
                "uploaded_files": 1,
                "warnings": ["media batch was partial"],
            },
            {"error": "tail text failed access_token=top-secret"},
        ]
    )
    entry = platform_registry.get("slack")
    original = entry.standalone_sender_fn
    original_max = entry.max_message_length
    entry.standalone_sender_fn = sender
    entry.max_message_length = 20
    try:
        result = await _send_to_platform(
            Platform.SLACK,
            SimpleNamespace(enabled=True, token="token", extra={}),
            "D123456789",
            "first chunk then second chunk",
            thread_id="123.456",
            media_files=[(str(image), False)],
        )
    finally:
        entry.standalone_sender_fn = original
        entry.max_message_length = original_max

    first_call = sender.await_args_list[0]
    assert first_call.kwargs["media_files"] == [(str(image), False)]
    assert result["success"] is True
    assert result["partial"] is True
    assert result["uploaded_files"] == 1
    assert result["warnings"][0] == "media batch was partial"
    assert "top-secret" not in result["warnings"][1]
    assert "access_token=***" in result["warnings"][1]
