from __future__ import annotations

from plugins.story_video.audit import ProviderAudit, ProviderAuditEvent
from plugins.story_video.policy import guard_tool_call
from plugins.story_video.state import StoryVideoStateStore, parse_operator_call


def _context(tmp_path):
    store = StoryVideoStateStore(tmp_path)
    call = parse_operator_call("故事影片：恐龍起源｜5分｜真實照片")
    assert call is not None
    return store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=call,
        original_request="start",
    )


def test_scene_prompt_without_story_markers_requires_explicit_openai(tmp_path) -> None:
    context = _context(tmp_path)
    args = {"prompt": "A photorealistic Triassic forest at dawn"}

    message = guard_tool_call(context, "image_generate", args)

    assert message is not None
    assert "openai-codex" in message
    assert "missing" in message.lower()


def test_scene_prompt_without_story_markers_allows_openai(tmp_path) -> None:
    context = _context(tmp_path)
    args = {
        "prompt": "A photorealistic Triassic forest at dawn",
        "provider": "openai-codex",
    }

    assert guard_tool_call(context, "image_generate", args) is None


def test_explicit_xai_image_is_blocked(tmp_path) -> None:
    context = _context(tmp_path)

    message = guard_tool_call(
        context,
        "image_generate",
        {"prompt": "scene", "provider": "xai"},
    )

    assert message is not None
    assert "xai" in message.lower()


def test_generic_video_body_is_blocked(tmp_path) -> None:
    context = _context(tmp_path)

    message = guard_tool_call(
        context,
        "video_generate",
        {"prompt": "animate this scene", "provider": "xai"},
    )

    assert message is not None
    assert "renderer" in message.lower()


def test_xai_terminal_and_delegate_attempts_are_blocked(tmp_path) -> None:
    context = _context(tmp_path)

    terminal = guard_tool_call(
        context,
        "terminal",
        {"command": "python generate.py --provider xai"},
    )
    delegate = guard_tool_call(
        context,
        "delegate_task",
        {"goal": "use Grok Imagine for all scene art"},
    )

    assert terminal is not None
    assert delegate is not None


def test_generic_tts_tool_is_blocked_to_prevent_configured_edge_fallback(tmp_path) -> None:
    context = _context(tmp_path)

    message = guard_tool_call(
        context,
        "text_to_speech",
        {"text": "旁白"},
    )

    assert message is not None
    assert "local" in message.lower() or "openai" in message.lower()


def test_provider_audit_passes_openai_and_local_events(tmp_path) -> None:
    context = _context(tmp_path)
    audit = ProviderAudit(context)
    audit.append_event(
        ProviderAuditEvent(
            kind="api",
            phase="planning",
            provider="openai-codex",
            model="gpt-5.5",
            status="ok",
        )
    )
    audit.append_event(
        ProviderAuditEvent(
            kind="local",
            phase="render",
            provider="local",
            model="ffmpeg",
            status="ok",
        )
    )

    result = audit.validate()

    assert result.ok is True
    assert result.violations == ()


def test_provider_audit_fails_when_xai_event_is_recorded(tmp_path) -> None:
    context = _context(tmp_path)
    audit = ProviderAudit(context)
    audit.append_event(
        ProviderAuditEvent(
            kind="tool",
            phase="keyframes",
            provider="xai",
            model="grok-imagine-image-quality",
            status="ok",
        )
    )

    result = audit.validate()

    assert result.ok is False
    assert any("xai" in violation.lower() for violation in result.violations)


def test_provider_audit_keeps_blocked_xai_attempt_as_non_usage_evidence(tmp_path) -> None:
    context = _context(tmp_path)
    audit = ProviderAudit(context)
    audit.append_event(
        ProviderAuditEvent(
            kind="tool",
            phase="keyframes",
            provider="xai",
            model="grok-imagine-image-quality",
            status="blocked",
        )
    )

    result = audit.validate()

    assert result.ok is True
