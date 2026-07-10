from __future__ import annotations

from plugins.story_video.state import (
    StoryVideoStateStore,
    parse_operator_call,
)


def test_parse_short_start_call_uses_operator_fields() -> None:
    call = parse_operator_call("故事影片：恐龍起源｜5分｜真實照片")

    assert call is not None
    assert call.action == "start"
    assert call.topic == "恐龍起源"
    assert call.duration == "5分"
    assert call.visual_style == "真實照片"


def test_continue_is_only_story_video_call_when_source_has_active_project() -> None:
    assert parse_operator_call("繼續", has_active_project=False) is None

    call = parse_operator_call("繼續", has_active_project=True)

    assert call is not None
    assert call.action == "continue"


def test_backward_compatible_next_call_maps_to_continue() -> None:
    call = parse_operator_call("故事影片下一步", has_active_project=False)

    assert call is not None
    assert call.action == "continue"


def test_state_store_persists_source_and_session_bindings(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    call = parse_operator_call("故事影片：恐龍起源｜5分｜真實照片")
    assert call is not None

    context = store.create_or_load(
        source_key="slack:workspace:channel:thread",
        session_id="session-1",
        call=call,
        original_request="故事影片：恐龍起源｜5分｜真實照片",
    )

    reloaded = StoryVideoStateStore(tmp_path)
    assert reloaded.for_source("slack:workspace:channel:thread") == context
    assert reloaded.for_session("session-1") == context
    assert context.phase == "planning"
    assert context.next_call == "繼續"
    assert context.provider_policy["image"] == ["openai", "openai-codex"]
    assert "xai" in context.provider_policy["forbidden"]
    assert (context.project_dir / "story_video_run_context.json").exists()


def test_existing_source_reloads_project_and_binds_new_session(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call("故事影片：恐龍起源｜5分｜真實照片")
    assert start is not None
    original = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="start",
    )
    continuation = parse_operator_call("繼續", has_active_project=True)
    assert continuation is not None

    resumed = store.create_or_load(
        source_key="source-1",
        session_id="session-2",
        call=continuation,
        original_request="繼續",
    )

    assert resumed.run_id == original.run_id
    assert store.for_session("session-2") == resumed


def test_repair_call_records_issue_and_returns_repair_next_call(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call("故事影片：恐龍起源｜5分｜真實照片")
    assert start is not None
    store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="start",
    )
    repair = parse_operator_call(
        "修正：旁白講完不要乾等", has_active_project=True
    )
    assert repair is not None

    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=repair,
        original_request="repair",
    )

    assert context.repair_request == "旁白講完不要乾等"
    assert context.next_call == "修正：旁白講完不要乾等"
