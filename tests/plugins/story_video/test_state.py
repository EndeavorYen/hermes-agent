from __future__ import annotations

import json

import pytest

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


def test_unspecified_visual_style_uses_generic_cinematic_default() -> None:
    call = parse_operator_call("故事影片：雲為什麼會下雨")

    assert call is not None
    assert call.visual_style == "Cinematic topic-appropriate visual storytelling"
    assert "pico" not in call.visual_style.casefold()


def test_long_form_revision_brief_extracts_chinese_duration_and_documentary_style() -> None:
    call = parse_operator_call(
        "做一部《恐龍的起源》的五分鐘故事影片，全自動到可審片。"
        "沿用既有專案的題材、研究方向與真實自然史紀錄片風格。"
    )

    assert call is not None
    assert call.topic == "恐龍的起源"
    assert call.duration == "五分鐘"
    assert call.visual_style == "真實自然史紀錄片風格"
    assert call.auto_mode is True


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


def test_active_story_video_parses_full_remake_as_linked_revision() -> None:
    call = parse_operator_call(
        "沿用目前恐龍起源專案，套用最新版故事影片流程全自動重新製作。",
        has_active_project=True,
    )

    assert call is not None
    assert call.action == "revision"
    assert call.auto_mode is True


def test_state_store_creates_fresh_revision_and_rebinds_source(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call("故事影片：恐龍起源｜5分｜真實照片")
    assert start is not None
    original = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="故事影片：恐龍起源｜5分｜真實照片",
    )
    original = store.update(original, phase="complete", status="complete")
    revision = parse_operator_call(
        "沿用目前專案，全自動重新製作最新版。",
        has_active_project=True,
    )
    assert revision is not None

    revised = store.create_or_load(
        source_key="source-1",
        session_id="session-2",
        call=revision,
        original_request="沿用目前專案，全自動重新製作最新版。",
    )

    assert revised.run_id != original.run_id
    assert revised.project_dir != original.project_dir
    assert revised.topic == original.topic
    assert revised.duration == original.duration
    assert revised.visual_style == original.visual_style
    assert revised.parent_run_id == original.run_id
    assert revised.source_project_dir == original.project_dir
    assert revised.phase == "planning"
    assert revised.status == "active"
    assert revised.auto_mode is True
    assert store.for_source("source-1").run_id == revised.run_id
    assert store.for_run(
        run_id=original.run_id,
        project_dir=original.project_dir,
    ).run_id == original.run_id


@pytest.mark.parametrize(
    "text",
    (
        "停止，不要做了",
        "請停止故事影片",
        "不要再繼續製作",
        "cancel story video",
    ),
)
def test_active_story_video_can_stop_with_natural_command(text) -> None:
    call = parse_operator_call(text, has_active_project=True)

    assert call is not None
    assert call.action == "stop"
    assert call.auto_mode is False


def test_stop_command_does_not_match_request_to_keep_going() -> None:
    assert parse_operator_call("不要停止，繼續做", has_active_project=True) is None


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


def test_parse_minute_scale_explainer_uses_same_story_video_intent_contract() -> None:
    call = parse_operator_call(
        "幫我做一部恐龍起源的科普影片，大概 5 分鐘，圖片走電影感寫實風格。"
    )

    assert call is not None
    assert call.action == "start"
    assert call.topic == "恐龍起源"
    assert call.duration == "5分鐘"


def test_parse_english_minute_scale_documentary_uses_same_intent_contract() -> None:
    call = parse_operator_call(
        "Make a 3-minute documentary about dinosaurs"
    )

    assert call is not None
    assert call.action == "start"
    assert call.topic == "dinosaurs"
    assert call.duration == "3-minute"


def test_parse_narrated_multiscene_video_uses_story_video_contract() -> None:
    call = parse_operator_call(
        "Create a multi-scene video with narration about dinosaurs"
    )

    assert call is not None
    assert call.action == "start"
    assert call.topic == "dinosaurs"


def test_parse_narrated_video_uses_story_video_contract() -> None:
    call = parse_operator_call("Create a narrated video about dinosaurs")

    assert call is not None
    assert call.action == "start"
    assert call.topic == "dinosaurs"


def test_short_product_intro_does_not_activate_story_video() -> None:
    assert parse_operator_call(
        "幫我做一支 6 秒產品介紹影片，從產品照開始。"
    ) is None


def test_continue_is_only_story_video_call_when_source_has_active_project() -> None:
    assert parse_operator_call("繼續", has_active_project=False) is None

    call = parse_operator_call("繼續", has_active_project=True)

    assert call is not None
    assert call.action == "continue"


def test_backward_compatible_next_call_maps_to_continue() -> None:
    call = parse_operator_call("故事影片下一步", has_active_project=False)

    assert call is not None
    assert call.action == "continue"


def test_active_project_treats_detailed_next_instruction_as_continue() -> None:
    call = parse_operator_call(
        "故事影片下一步。只執行一個 QC cycle：處理 S03_SH03。",
        has_active_project=True,
    )

    assert call is not None
    assert call.action == "continue"


def test_active_project_requires_explicit_new_project_intent_to_replace() -> None:
    protected = parse_operator_call(
        "故事影片：另一個主題｜30秒｜真實照片",
        has_active_project=True,
    )
    explicit = parse_operator_call(
        "新故事影片：另一個主題｜30秒｜真實照片",
        has_active_project=True,
    )

    assert protected is not None
    assert protected.action == "continue"
    assert explicit is not None
    assert explicit.action == "start"
    assert explicit.new_project is True
    assert explicit.topic == "另一個主題"


def test_state_store_refuses_implicit_active_project_replacement(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    original = parse_operator_call("故事影片：恐龍起源｜5分｜真實照片")
    assert original is not None
    context = store.create_or_load(
        source_key="source-1", session_id="session-1", call=original,
        original_request="start",
    )
    accidental = parse_operator_call("故事影片：QC cycle｜30秒｜真實照片")
    assert accidental is not None

    preserved = store.create_or_load(
        source_key="source-1", session_id="session-1", call=accidental,
        original_request="accidental start-shaped follow-up",
    )

    assert preserved.run_id == context.run_id
    assert preserved.topic == "恐龍起源"


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
    context = store.update(
        context,
        autopilot_last_signature="planning:blocked:continue",
        autopilot_stall_count=3,
    )

    auto = parse_operator_call("全自動", has_active_project=True)
    assert auto is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=auto,
        original_request="全自動",
    )

    assert context.auto_mode is True
    assert context.autopilot_last_signature == ""
    assert context.autopilot_stall_count == 0
    assert store.for_session("session-1").auto_mode is True


def test_stop_revokes_durable_autopilot_and_explicit_continue_resumes_manual_mode(
    tmp_path,
) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call(
        "故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。"
    )
    assert start is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="start",
    )
    assert context.auto_mode is True

    stop = parse_operator_call("停止，不要做了", has_active_project=True)
    assert stop is not None
    stopped = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=stop,
        original_request="停止，不要做了",
    )

    assert stopped.status == "stopped"
    assert stopped.auto_mode is False
    assert stopped.next_call is None
    authorization = json.loads(
        (store.authorization_state_root / f"{stopped.run_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert authorization["enabled"] is False
    assert authorization["source"] == "operator_stop_command"
    reloaded = StoryVideoStateStore(tmp_path).for_session("session-1")
    assert reloaded is not None
    assert reloaded.status == "stopped"
    assert reloaded.auto_mode is False

    resume = parse_operator_call("繼續", has_active_project=True)
    assert resume is not None
    resumed = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=resume,
        original_request="繼續",
    )
    assert resumed.status == "active"
    assert resumed.auto_mode is False


def test_autopilot_authorization_recovers_polluted_production_context(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call(
        "故事影片：恐龍起源｜5分鐘｜真實照片。只規劃。"
    )
    assert start is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="只規劃",
    )
    auto = parse_operator_call("全自動", has_active_project=True)
    assert auto is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=auto,
        original_request="全自動",
    )
    (context.project_dir / "manifests").mkdir(parents=True, exist_ok=True)
    (context.project_dir / "manifests" / "shot_candidate_manifest.json").write_text(
        json.dumps({"run_id": context.run_id, "phase": "batch"}),
        encoding="utf-8",
    )
    polluted = {
        **context.to_dict(),
        "phase": "planning",
        "auto_mode": False,
        "last_validated_phase": "planning",
    }
    (context.project_dir / "story_video_run_context.json").write_text(
        json.dumps(polluted),
        encoding="utf-8",
    )

    recovered = store.for_session("session-1")

    assert recovered is not None
    assert recovered.phase == "batch"
    assert recovered.auto_mode is True
    assert recovered.last_validated_phase == ""
    authorization = json.loads(
        (store.authorization_state_root / f"{context.run_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert authorization["run_id"] == context.run_id
    assert authorization["enabled"] is True


def test_private_canonical_state_wins_over_project_context_pollution(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call(
        "故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。"
    )
    assert start is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="完整製作並出片",
    )
    context = store.update(context, phase="batch")
    project_context = context.project_dir / "story_video_run_context.json"
    project_context.write_text(
        json.dumps({**context.to_dict(), "phase": "planning", "auto_mode": False}),
        encoding="utf-8",
    )

    by_session = store.for_session("session-1")
    by_run = store.for_run(run_id=context.run_id, project_dir=context.project_dir)

    assert by_session is not None
    assert by_session.phase == "batch"
    assert by_session.auto_mode is True
    assert by_run == by_session
    assert (store.state_root / "runs" / f"{context.run_id}.json").is_file()


def test_batch_media_does_not_override_planning_without_authorization(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call(
        "故事影片：恐龍起源｜5分鐘｜真實照片。只規劃。"
    )
    assert start is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="只規劃",
    )
    (context.project_dir / "manifests").mkdir(parents=True)
    (context.project_dir / "manifests" / "shot_candidate_manifest.json").write_text(
        json.dumps({"run_id": context.run_id, "phase": "batch"}),
        encoding="utf-8",
    )

    preserved = store.for_session("session-1")

    assert preserved is not None
    assert preserved.phase == "planning"
    assert preserved.auto_mode is False


def test_state_store_rejects_phase_regression(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call("故事影片：恐龍起源｜5分鐘｜真實照片")
    assert start is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="開始",
    )
    context = store.update(context, phase="batch")

    with pytest.raises(ValueError, match="phase regression"):
        store.update(context, phase="planning")


def test_stale_worker_update_cannot_overwrite_newer_canonical_phase(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    start = parse_operator_call("故事影片：恐龍起源｜5分鐘｜真實照片")
    assert start is not None
    stale = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=start,
        original_request="開始",
    )
    store.update(stale, phase="batch")

    updated = store.update(stale, autopilot_stall_count=1)

    assert updated.phase == "batch"
    assert updated.autopilot_stall_count == 1
    assert store.for_session("session-1").phase == "batch"


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


def test_for_run_rejects_project_outside_story_video_root(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path / "story-videos")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "story_video_run_context.json").write_text(
        '{"run_id":"run-1","project_dir":"%s"}' % outside,
        encoding="utf-8",
    )

    assert store.for_run(run_id="run-1", project_dir=outside) is None


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
    store.update(
        context,
        phase="render",
        last_validated_phase="voice",
        repair_request="補齊 voice：audio narration segments",
    )

    reloaded = store.for_session("session-1")

    assert reloaded is not None
    assert reloaded.repair_request == ""
    assert reloaded.next_call == "出片"
    persisted = json.loads(
        (context.project_dir / "story_video_run_context.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["repair_request"] == ""


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


def test_parse_operator_call_supports_youtube_review_package() -> None:
    call = parse_operator_call("準備上架", has_active_project=True)

    assert call is not None
    assert call.action == "package"


def test_parse_operator_call_requires_explicit_youtube_upload_approval() -> None:
    call = parse_operator_call("核准上傳 YouTube", has_active_project=True)

    assert call is not None
    assert call.action == "approve_upload"
