from __future__ import annotations

import json
from types import SimpleNamespace

from plugins.story_video import hooks
from plugins.story_video.audit import ProviderAudit
from plugins.story_video.state import StoryVideoStateStore


def _event(text: str):
    return SimpleNamespace(
        text=text,
        reply_to_message_id="thread-1",
        source=SimpleNamespace(
            platform="slack",
            scope_id="workspace-1",
            chat_id="channel-1",
            thread_id="thread-1",
            user_id="user-1",
        ),
    )


def _event_with_identity(
    text: str,
    *,
    scope_id: str,
    user_id: str,
):
    event = _event(text)
    event.source.scope_id = scope_id
    event.source.user_id = user_id
    return event


def _write_planning_fixture(context) -> None:
    (context.project_dir / "script.md").write_text(
        "### S00\nfinal narration script", encoding="utf-8"
    )
    scales = ("close_up", "medium", "wide", "macro", "medium", "insert", "medium", "establishing")
    shots = [
        {
            "shot_id": f"S00_SH{index:02d}",
            "narration_text": f"第 {index} 個旁白片段",
            "narrative_role": "evidence",
            "viewer_takeaway": "觀眾看懂一個具體證據",
            "subject": "可辨識的主要證據",
            "action": "主體執行與旁白相符的動作",
            "evidence_detail": "關鍵細節清楚可見",
            "shot_scale": scales[index % len(scales)],
            "camera_angle": "eye level",
            "focal_point": "primary evidence",
            "subtitle_safe_area": "bottom 20 percent clear",
            "acceptance_criteria": ["evidence is immediately readable"],
            "risk_class": "normal",
        }
        for index in range(40)
    ]
    ledger = {
        "schema": "story_video_scene_ledger_v2",
        "production_type": "science_explainer",
        "target_duration_sec": 300,
        "visual_style": "photoreal professional science documentary",
        "scenes": [
            {
                "scene_id": "S00",
                "narrative_role": "evidence",
                "viewer_takeaway": "觀眾看懂一個具體證據",
                "shots": shots,
            }
        ],
    }
    (context.project_dir / "PROJECT_CONTRACT.md").write_text("contract", encoding="utf-8")
    (context.project_dir / "storyboard.md").write_text("storyboard", encoding="utf-8")
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )
    (context.project_dir / "production_checklist.json").write_text(
        json.dumps({"quality_mode": "quality_first"}), encoding="utf-8"
    )
    (context.project_dir / "script_quality_report.json").write_text(
        json.dumps(
            {
                "schema": "story_video_script_quality_v1",
                "quality_contract_version": 2,
                "status": "PASS",
                "checks": {
                    "visual_evidence": "PASS",
                    "narrative_roles": "PASS",
                    "claim_confidence": "PASS",
                },
            }
        ),
        encoding="utf-8",
    )
    (context.project_dir / "pronunciation_lexicon.json").write_text(
        json.dumps(
            {
                "schema": "story_video_pronunciation_lexicon_v1",
                "language": "zh-TW",
                "review_status": "PASS",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )


def test_gateway_rewrites_short_start_with_structured_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(hooks, "_STORE", StoryVideoStateStore(tmp_path))

    result = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )

    assert result["action"] == "rewrite"
    assert "STORY_VIDEO_OPERATOR_CONTEXT" in result["text"]
    assert '"action": "start"' in result["text"]


def test_gateway_only_rewrites_continue_when_source_is_active(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    event = _event("繼續")

    assert hooks.pre_gateway_dispatch(event=event) is None

    start_result = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(
        session_id="session-1",
        user_message=start_result["text"],
        model="gpt-5.5",
    )

    result = hooks.pre_gateway_dispatch(event=event)

    assert result["action"] == "rewrite"
    assert '"action": "continue"' in result["text"]


def test_gateway_rewrites_polite_continue_for_active_thread(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(session_id="session-1", user_message=start["text"])

    result = hooks.pre_gateway_dispatch(event=_event("請繼續"))

    assert result["action"] == "rewrite"
    assert '"action": "continue"' in result["text"]


def test_gateway_source_key_uses_real_slack_reply_thread_id() -> None:
    first = _event("繼續")
    second = _event("繼續")
    first.source.thread_id = ""
    second.source.thread_id = ""
    second.reply_to_message_id = "thread-2"

    assert hooks._source_key(first) != hooks._source_key(second)


def test_gateway_source_key_is_stable_across_session_identity_changes() -> None:
    original = _event_with_identity(
        "繼續",
        scope_id="workspace-before-restart",
        user_id="user-before-restart",
    )
    resumed = _event_with_identity(
        "繼續",
        scope_id="workspace-after-restart",
        user_id="user-after-restart",
    )

    assert hooks._source_key(original) == hooks._source_key(resumed)


def test_gateway_migrates_legacy_source_binding_for_active_thread(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start_event = _event("故事影片：恐龍起源｜5分｜真實照片")
    legacy_key = hooks._legacy_source_key(start_event)
    store.create_or_load(
        source_key=legacy_key,
        session_id="session-before-restart",
        call=hooks.OperatorCall(
            action="start",
            topic="恐龍起源",
            duration="5分",
            visual_style="真實照片",
        ),
        original_request=start_event.text,
    )

    result = hooks.pre_gateway_dispatch(event=_event("繼續"))

    assert result["action"] == "rewrite"
    assert '"action": "continue"' in result["text"]
    assert store.for_source(hooks._source_key(start_event)) is not None


def test_pre_llm_creates_context_and_injects_provider_policy(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )

    result = hooks.pre_llm_call(
        session_id="session-1",
        turn_id="turn-1",
        user_message=rewritten["text"],
        model="gpt-5.5",
    )

    context = store.for_session("session-1")
    assert context is not None
    assert context.topic == "恐龍起源"
    assert "provider=openai-codex" in result["context"]
    assert "story_video_control" in result["context"]
    assert "Complete the current phase in this turn" in result["context"]
    assert "Do not inspect other story-video projects" in result["context"]
    assert "story-video-script-director" in result["context"]
    assert "script.md" in result["context"]
    assert "script_quality_report.json" in result["context"]
    assert '"language": "zh-TW"' in result["context"]
    assert '"review_status": "PASS"' in result["context"]
    assert "high-risk spoken aliases MUST differ from display text" in result["context"]
    assert "三疊紀 -> 三碟紀" in result["context"]
    assert "target_duration_sec" in result["context"]
    assert "narration_text" in result["context"]
    assert "camera_angle" in result["context"]
    assert "subtitle_safe_area" in result["context"]
    assert "establishing|wide|medium|close_up|macro|insert" in result["context"]
    assert "8-12 shots per minute" in result["context"]
    assert "story_video_script_quality_v1" in result["context"]
    assert "quality_contract_version=2" in result["context"]
    assert "checks MUST be an object" in result["context"]
    assert "scene.shots array" in result["context"]
    assert "### S00" in result["context"]
    assert "never write spoken aliases into script.md" in result["context"]
    assert "acceptance_criteria MUST be a non-empty JSON array of strings" in result["context"]
    assert "40-60" in result["context"]


def test_autopilot_context_requires_canonical_quality_tool_and_phase_loop(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。")
    )

    result = hooks.pre_llm_call(
        session_id="session-auto",
        user_message=rewritten["text"],
    )

    context = store.for_session("session-auto")
    assert context is not None
    assert context.auto_mode is True
    assert "AUTOPILOT is enabled" in result["context"]
    assert "story_video_quality_control" in result["context"]
    assert "never edit shot_candidate_manifest.json manually" in result["context"]


def test_autopilot_requests_internal_continuation_until_complete(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=start["text"])

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROOF: planning PASS",
    )

    assert continuation["action"] == "continue"
    assert "STORY_VIDEO_AUTOPILOT" in continuation["message"]


def test_autopilot_stops_for_operator_setup_blocker(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=start["text"])

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="OpenAI quota exhausted; setup required.",
    )

    assert continuation is None


def test_autopilot_stops_after_three_identical_blocked_phase_reports(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=start["text"])
    blocked = "STORY_VIDEO_PHASE_PROOF: keyframes BLOCKED"

    first = hooks.auto_continue_llm_output(
        session_id="session-auto", response_text=blocked
    )
    second = hooks.auto_continue_llm_output(
        session_id="session-auto", response_text=blocked
    )
    third = hooks.auto_continue_llm_output(
        session_id="session-auto", response_text=blocked
    )

    assert first is not None
    assert second is not None
    assert third is None
    context = store.for_session("session-auto")
    assert context is not None
    assert context.autopilot_stall_count == 3


def test_autopilot_does_not_stall_when_candidate_manifest_advances(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=start["text"])
    context = store.for_session("session-auto")
    assert context is not None
    store.update(context, phase="batch")
    blocked = "STORY_VIDEO_PHASE_PROOF: batch BLOCKED"

    assert hooks.auto_continue_llm_output(
        session_id="session-auto", response_text=blocked
    ) is not None
    context = store.for_session("session-auto")
    assert context is not None
    manifest = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "shot_id": "S00_SH01",
                        "candidate_id": "S00_SH01_C01",
                        "selected": True,
                        "status": "selected_current",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert hooks.auto_continue_llm_output(
        session_id="session-auto", response_text=blocked
    ) is not None
    advanced = store.for_session("session-auto")
    assert advanced is not None
    assert advanced.autopilot_stall_count == 1


def test_direct_full_auto_resets_existing_stall_guard(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    hooks.pre_llm_call(
        session_id="session-auto",
        user_message="故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。",
    )
    context = store.for_session("session-auto")
    assert context is not None
    store.update(
        context,
        autopilot_last_signature="keyframes:blocked:repair",
        autopilot_stall_count=3,
    )

    hooks.pre_llm_call(session_id="session-auto", user_message="全自動")

    reset = store.for_session("session-auto")
    assert reset is not None
    assert reset.autopilot_last_signature == ""
    assert reset.autopilot_stall_count == 0


def test_pre_llm_creates_context_for_direct_cli_story_video_request(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)

    result = hooks.pre_llm_call(
        session_id="cli-session-1",
        user_message="故事影片：恐龍起源｜5分｜真實照片",
        model="gpt-5.5",
    )

    context = store.for_session("cli-session-1")
    assert context is not None
    assert context.topic == "恐龍起源"
    assert context.source_key == "session:cli-session-1"
    assert "provider=openai-codex" in result["context"]


def test_pre_tool_guard_uses_session_context_not_prompt_words(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(session_id="session-1", user_message=rewritten["text"])

    blocked = hooks.pre_tool_call(
        session_id="session-1",
        turn_id="turn-1",
        tool_name="image_generate",
        args={"prompt": "A dinosaur beside a river"},
    )
    allowed = hooks.pre_tool_call(
        session_id="session-1",
        turn_id="turn-1",
        tool_name="image_generate",
        args={
            "prompt": "A dinosaur beside a river",
            "provider": "openai-codex",
        },
    )

    assert blocked["action"] == "block"
    assert allowed is None


def test_api_hooks_record_provider_and_subagent_inherits_context(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(session_id="parent", user_message=rewritten["text"])

    hooks.subagent_start(parent_session_id="parent", child_session_id="child")
    hooks.pre_api_request(
        session_id="child",
        turn_id="turn-2",
        api_request_id="req-1",
        provider="openai-codex",
        model="gpt-5.5",
    )

    child_context = store.for_session("child")
    assert child_context is not None
    audit = ProviderAudit(child_context)
    payload = json.loads(audit.path.read_text(encoding="utf-8"))
    assert payload["events"][-1]["provider"] == "openai-codex"
    assert payload["events"][-1]["request_id"] == "req-1"


def test_transform_output_uses_phase_next_call(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(session_id="session-1", user_message=rewritten["text"])
    context = store.for_session("session-1")
    assert context is not None
    _write_planning_fixture(context)

    result = hooks.transform_llm_output(
        response_text="規劃檔案已建立。",
        session_id="session-1",
    )

    assert result.endswith('Raphael 下一步：回覆「繼續」。')


def test_transform_output_uses_render_and_repair_calls_from_state(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(session_id="session-1", user_message=rewritten["text"])
    context = store.for_session("session-1")
    assert context is not None

    store.update(context, phase="render")
    render = hooks.transform_llm_output(
        response_text="素材與旁白已鎖定。",
        session_id="session-1",
    )
    context = store.for_session("session-1")
    assert context is not None
    store.update(context, repair_request="補齊 provider audit")
    repair = hooks.transform_llm_output(
        response_text="目前仍有阻塞。",
        session_id="session-1",
    )

    assert render.endswith('Raphael 下一步：回覆「出片」。')
    assert repair.endswith('Raphael 下一步：回覆「修正：補齊 provider audit」。')


def test_transform_output_blocks_unproven_planning_completion(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(session_id="session-1", user_message=rewritten["text"])

    result = hooks.transform_llm_output(
        response_text="規劃文件已全部完成。",
        session_id="session-1",
    )

    assert "STORY_VIDEO_PHASE_PROOF: planning BLOCKED" in result
    assert "storyboard.md" in result
    assert 'Raphael 下一步：回覆「修正：' in result


def test_transform_output_auto_validates_current_phase_once(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(session_id="session-1", user_message=rewritten["text"])
    context = store.for_session("session-1")
    assert context is not None
    _write_planning_fixture(context)

    result = hooks.transform_llm_output(
        response_text="規劃文件已全部完成。",
        session_id="session-1",
    )

    assert "STORY_VIDEO_PHASE_PROOF: planning PASS" in result
    assert store.for_session("session-1").phase == "keyframes"
    assert result.endswith('Raphael 下一步：回覆「繼續」。')


def test_transform_output_does_not_validate_new_phase_after_explicit_advance(
    tmp_path, monkeypatch
) -> None:
    from plugins.story_video.tools import story_video_control

    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(session_id="session-1", user_message=rewritten["text"])
    context = store.for_session("session-1")
    assert context is not None
    _write_planning_fixture(context)
    proof = json.loads(
        story_video_control(
            {"action": "validate"}, session_id="session-1", store=store
        )
    )
    assert proof["success"] is True

    result = hooks.transform_llm_output(
        response_text="規劃文件已全部完成。",
        session_id="session-1",
    )

    assert "keyframes BLOCKED" not in result
    assert store.for_session("session-1").phase == "keyframes"
    assert result.endswith('Raphael 下一步：回覆「繼續」。')


def test_transform_output_blocks_video_not_selected_by_current_render_manifest(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    context = store.create_or_load(
        source_key="gateway:thread-1",
        session_id="session-1",
        call=hooks.OperatorCall(
            action="start",
            topic="恐龍起源",
            duration="5分",
            visual_style="真實照片",
        ),
        original_request="故事影片：恐龍起源｜5分｜真實照片",
    )
    selected = context.project_dir / "renders" / "selected.mp4"
    stale = context.project_dir / "renders" / "stale.mp4"
    selected.parent.mkdir(parents=True)
    selected.write_bytes(b"selected")
    stale.write_bytes(b"stale")
    (context.project_dir / "render_manifest.json").write_text(
        json.dumps({"output": {"path": "renders/selected.mp4"}}),
        encoding="utf-8",
    )
    store.update(context, phase="complete", status="complete")

    blocked = hooks.transform_llm_output(
        response_text=f"新版已完成：MEDIA:{stale}",
        session_id="session-1",
    )
    allowed = hooks.transform_llm_output(
        response_text=f"新版已完成：MEDIA:{selected}",
        session_id="session-1",
    )

    assert str(stale) not in blocked
    assert "STORY_VIDEO_DELIVERY_BLOCKED" in blocked
    assert str(selected) in allowed
