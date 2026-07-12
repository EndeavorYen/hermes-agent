from __future__ import annotations

import json

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
    assert call.auto_mode is False


def test_planning_only_start_does_not_enable_autopilot() -> None:
    call = parse_operator_call(
        "故事影片：恐龍起源｜5分鐘｜真實照片。只規劃。"
    )

    assert call is not None
    assert call.auto_mode is False


def test_active_story_video_can_enable_autopilot_with_natural_command() -> None:
    call = parse_operator_call("你幫我一直推進", has_active_project=True)

    assert call is not None
    assert call.action == "auto"
    assert call.auto_mode is True


def test_parse_short_start_ignores_planning_only_media_prohibition() -> None:
    call = parse_operator_call(
        "故事影片：三疊紀發音與恐龍起源測試｜30秒｜真實照片風格。"
        "只規劃：建立 project contract、storyboard 與 scene ledger；"
        "不要產生任何圖片、語音或影片。"
    )

    assert call is not None
    assert call.action == "start"
    assert call.topic == "三疊紀發音與恐龍起源測試"
    assert call.duration == "30秒"
    assert call.visual_style == "真實照片風格"


def test_parse_long_form_request_that_explicitly_routes_to_story_video() -> None:
    call = parse_operator_call(
        "幫我做一部恐龍起源的科普影片（可用之前故事影片的 skill 或流程），"
        "圖片走真實照片風格，大概 5mins。先不要產圖或產影片。"
    )

    assert call is not None
    assert call.action == "start"
    assert call.topic == "恐龍起源"
    assert call.duration == "5mins"
    assert call.visual_style == "真實照片風格"


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
    assert context.auto_mode is False
    assert "xai" in context.provider_policy["forbidden"]
    assert (context.project_dir / "story_video_run_context.json").exists()


def test_existing_project_persists_autopilot_activation(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call(
        "故事影片：恐龍起源｜5分鐘｜真實照片。只規劃。"
    )
    assert start is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="start",
    )
    assert context.auto_mode is False

    auto = parse_operator_call("全自動", has_active_project=True)
    assert auto is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=auto,
        original_request="全自動",
    )

    assert context.auto_mode is True
    assert store.for_session("session-1").auto_mode is True


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


def test_loading_advanced_phase_clears_stale_legacy_repair(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call("故事影片：恐龍起源｜5分｜真實照片")
    assert start is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="start",
    )
    context_path = context.project_dir / "story_video_run_context.json"
    payload = context.to_dict()
    payload.update(
        {
            "phase": "render",
            "last_validated_phase": "voice",
            "repair_request": "補齊 voice：audio narration segments",
        }
    )
    context_path.write_text(json.dumps(payload), encoding="utf-8")

    reloaded = store.for_session("session-1")

    assert reloaded is not None
    assert reloaded.repair_request == ""
    assert reloaded.next_call == "出片"
    assert json.loads(context_path.read_text(encoding="utf-8"))["repair_request"] == ""


def test_new_cross_phase_repair_is_not_treated_as_stale(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call("故事影片：恐龍起源｜5分｜真實照片")
    assert start is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="start",
    )
    context = store.update(
        context,
        phase="render",
        last_validated_phase="voice",
        repair_request="",
    )
    repair = parse_operator_call(
        "修正：補齊 voice：重新錄製 S03", has_active_project=True
    )
    assert repair is not None

    repaired = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=repair,
        original_request="repair",
    )

    assert repaired.repair_phase == "render"
    assert repaired.next_call == "修正：補齊 voice：重新錄製 S03"
