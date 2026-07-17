from __future__ import annotations

import json
from types import SimpleNamespace

from plugins.story_video import hooks
from plugins.story_video import guide
from plugins.story_video.audit import ProviderAudit
from plugins.story_video.state import StoryVideoStateStore, parse_operator_call
from plugins.story_video.tools import story_video_control


def _event(text: str, *, reply_to_text: str | None = None):
    return SimpleNamespace(
        text=text,
        reply_to_message_id="thread-1",
        reply_to_text=reply_to_text,
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


def test_voice_management_fast_route_avoids_story_project_and_shell_work(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)

    assert hooks.pre_gateway_dispatch(event=_event("列出故事影片聲線")) is None

    result = hooks.pre_llm_call(
        session_id="voice-list-session",
        user_message="列出故事影片聲線",
    )

    assert store.for_session("voice-list-session") is None
    assert "story_video_voice_manager action=list exactly once" in result["context"]
    assert "Do not run shell commands" in result["context"]
    assert "Do not inspect story-video projects" in result["context"]


def test_voice_management_fast_route_maps_lifecycle_actions_without_catching_casting(
) -> None:
    cases = {
        "列出目前可用聲線": "list",
        "新增聲線媽媽": "add",
        "增加新的聲線": "add",
        "調整聲線媽媽的速度": "tune",
        "封存聲線媽媽": "archive",
        "刪除聲線媽媽": "delete",
    }

    for prompt, expected_action in cases.items():
        result = hooks.pre_llm_call(
            session_id=f"voice-{expected_action}",
            user_message=prompt,
        )
        assert (
            f"story_video_voice_manager action={expected_action} exactly once"
            in result["context"]
        )

    assert hooks._voice_management_action("旁白聲線用 simon") is None


def test_voice_management_fast_route_bypasses_active_project_phase_guards(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    monkeypatch.setattr(hooks, "_VISUAL_AGENT_BYPASS_SESSIONS", set())
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜電影感科普。只規劃。")
    )
    hooks.pre_llm_call(session_id="active-story", user_message=start["text"])
    active = store.for_session("active-story")
    assert active is not None

    result = hooks.pre_llm_call(
        session_id="active-story",
        user_message="列出故事影片聲線",
    )

    assert "story_video_voice_manager action=list exactly once" in result["context"]
    assert store.for_session("active-story").run_id == active.run_id
    assert (
        hooks.pre_tool_call(
            session_id="active-story",
            tool_name="story_video_voice_manager",
            args={"action": "list"},
        )
        is None
    )
    assert (
        hooks.transform_llm_output(
            session_id="active-story",
            response_text="聲線清單",
        )
        is None
    )


def test_natural_help_fast_route_does_not_create_story_project(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    monkeypatch.setattr(hooks, "_VISUAL_AGENT_BYPASS_SESSIONS", set())

    assert hooks.pre_gateway_dispatch(event=_event("故事影片怎麼用")) is None
    result = hooks.pre_llm_call(
        session_id="story-help-session",
        user_message="故事影片怎麼用",
    )

    assert store.for_session("story-help-session") is None
    assert "story_video_control action=guide exactly once" in result["context"]
    assert "section=help" in result["context"]
    assert "Do not run shell commands" in result["context"]
    assert "Do not create, bind, validate, or advance" in result["context"]


def test_natural_help_maps_status_examples_and_voices_without_catching_start() -> None:
    cases = {
        "故事影片目前狀態": "status",
        "故事影片 prompt 範例": "examples",
        "Raphael，故事影片有哪些聲線？": "voices",
        "Raphael 故事影片幫助": "help",
    }

    for prompt, section in cases.items():
        assert hooks._story_video_help_section(prompt) == section

    assert hooks._story_video_help_section(
        "故事影片：恐龍起源｜5 分鐘｜寫實電影感。全自動"
    ) is None


def test_natural_status_help_bypasses_active_project_phase_guards(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    monkeypatch.setattr(hooks, "_VISUAL_AGENT_BYPASS_SESSIONS", set())
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜電影感科普。只規劃。")
    )
    hooks.pre_llm_call(session_id="active-help-story", user_message=start["text"])
    active = store.for_session("active-help-story")
    assert active is not None

    result = hooks.pre_llm_call(
        session_id="active-help-story",
        user_message="故事影片目前狀態",
    )

    assert "section=status" in result["context"]
    assert store.for_session("active-help-story").run_id == active.run_id
    assert store.for_session("active-help-story").phase == active.phase
    assert (
        hooks.pre_tool_call(
            session_id="active-help-story",
            tool_name="story_video_control",
            args={"action": "guide", "section": "status"},
        )
        is None
    )
    assert (
        hooks.transform_llm_output(
            session_id="active-help-story",
            response_text="目前在 planning。",
        )
        is None
    )


def test_raphael_output_uses_canonical_next_action_formatter(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    monkeypatch.setattr(hooks, "_SESSION_PHASE_AT_LLM_START", {})
    monkeypatch.setattr(hooks, "_SESSION_STATUS_AT_LLM_START", {})
    monkeypatch.setattr(hooks, "_VISUAL_AGENT_BYPASS_SESSIONS", set())
    call = parse_operator_call("故事影片：恐龍起源｜5分｜電影感")
    assert call is not None
    store.create_or_load(
        source_key="source-raphael",
        session_id="raphael-session",
        call=call,
        original_request="故事影片：恐龍起源｜5分｜電影感",
    )
    monkeypatch.setattr(
        guide,
        "format_raphael_next_action",
        lambda _context: "CANONICAL_RAPHAEL_NEXT",
    )

    result = hooks.transform_llm_output(
        session_id="raphael-session",
        response_text="目前狀態",
    )

    assert result == "目前狀態\n\nCANONICAL_RAPHAEL_NEXT"


def test_project_contract_defaults_to_semantic_holds_and_cinematic_focus_push(
    tmp_path,
) -> None:
    context = SimpleNamespace(
        project_dir=tmp_path,
        run_id="run-1",
        topic="測試主題",
        duration="5mins",
        visual_style="cinematic factual reconstruction",
        original_request="請製作故事影片",
    )

    hooks._write_project_contract(context)

    contract = (tmp_path / "PROJECT_CONTRACT.md").read_text(encoding="utf-8")
    assert "cinematic focus push 1.0 -> 1.10" in contract
    assert "normally at least two complete sentences" in contract
    assert "one precise OpenAI candidate by default" in contract
    assert "stable center zoom" not in contract
    assert "40-60" not in contract


def test_runtime_context_requires_v6_review_board_and_reserved_content_profiles(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜電影感科普。只規劃。")
    )

    runtime = hooks.pre_llm_call(session_id="session-v6", user_message=start["text"])
    context = runtime["context"]

    assert "quality_contract_version=6" in context
    assert "content_profile.json" in context
    assert "script_review_report.json" in context
    assert "story-video-script-review-board" in context
    assert "review_profile_id=family-review-board-v2" in context
    assert "story_video_editorial_metrics_v1" in context
    assert "concrete_scene_ratio>=0.80" in context
    assert "long_sentence_ratio<=0.25" in context
    assert "curiosity_loop_count>=max(2, ceil(runtime_minutes))" in context
    assert "delight_beat_count>=max(1, floor(runtime_minutes/2))" in context
    assert "no rhetorical template may appear in more than two segments" in context
    assert "at most two revision rounds" in context
    assert "final_script_sha256" in context
    assert "adult_explicit" in context
    assert "SETUP_REQUIRED" in context
    assert "family/child profile" in context
    assert "engagement_role=hook|build|reveal|reaction|payoff|breathe" in context
    assert "composition_energy=calm|curious|tense|kinetic|awe" in context
    assert "engagement_criteria MUST be a non-empty JSON array of strings" in context
    assert "a top-level shots array on that scene item" in context
    assert "never nest shots under a scene object" in context
    assert "revision_round_count=1 or 2" in context
    assert (
        "finding_id, severity, location, category, evidence, recommendation, and "
        "resolution_status"
    ) in context
    assert "severity=minor|moderate|major|critical" in context
    assert "resolution_status=resolved|unresolved|accepted_risk" in context
    assert "adjudication object" in context
    assert "minimum_age_years=5" in context
    assert "story_engine" in context
    assert "MUST NOT create empty scenes just to satisfy arc roles" in context
    assert "scene narrative_role=hook and its shot narrative_role=turn" in context
    assert "split immediately after sentence-ending punctuation plus any closing quotes" in context
    assert "style_bible" in context
    assert "style reference" in context.lower()
    assert "educational ending" in context.lower()
    assert "generate exactly two distinct text-free sources" in context
    assert "RELEASE_OPENING_C01" in context
    assert "RELEASE_ENDING_C01" in context
    assert "music_direction" in context
    assert "story_video_music_direction_v1" in context
    assert "min_cue_variants=3" in context
    assert "narration_priority=true" in context
    assert "story_video_music_library_v2" in context


def test_autopilot_runtime_context_exposes_verified_purpose_limited_authorization(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event(
            "故事影片：恐龍起源｜5分鐘｜電影感寫實。全自動製作，完成後供 review。"
        )
    )

    runtime = hooks.pre_llm_call(
        session_id="session-auto",
        user_message=start["text"],
    )
    context = store.for_session("session-auto")
    assert context is not None
    authorization = store.autopilot_authorization(context)
    assert authorization is not None

    prompt = runtime["context"]
    assert "VERIFIED_STORY_VIDEO_AUTHORIZATION" in prompt
    assert authorization["authorization_id"] in prompt
    assert "purpose-created story prompts and generated source art" in prompt
    assert "openai_image_generation" in prompt
    assert "unrelated workspace data is not authorized" in prompt


def test_keyframe_autopilot_uses_authorized_native_chunk_instead_of_manual_tools(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event(
            "故事影片：恐龍起源｜5分鐘｜電影感寫實。全自動製作，完成後供 review。"
        )
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=start["text"])
    context = store.for_session("session-auto")
    assert context is not None
    context = store.update(context, phase="keyframes", auto_mode=True)
    authorization = store.autopilot_authorization(context)
    assert authorization is not None

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROGRESS: keyframes IN_PROGRESS",
    )

    assert continuation is not None
    message = continuation["message"]
    assert "story_video_quality_control action=run_batch_chunk" in message
    assert f"authorization_id={authorization['authorization_id']}" in message
    assert f"run_id={context.run_id}" in message
    assert f"project_dir={context.project_dir}" in message
    assert "Do not call image_generate" in message
    assert "next_batch_work" not in message


def test_voice_autopilot_uses_one_native_phase_call_instead_of_shell_or_tts(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event(
            "故事影片：恐龍起源｜5分鐘｜電影感寫實。全自動製作，完成後供 review。"
        )
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=start["text"])
    context = store.for_session("session-auto")
    assert context is not None
    context = store.update(context, phase="voice", auto_mode=True)
    authorization = store.autopilot_authorization(context)
    assert authorization is not None

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROOF: voice BLOCKED",
    )

    assert continuation is not None
    message = continuation["message"]
    assert "story_video_quality_control action=run_voice_phase" in message
    assert f"authorization_id={authorization['authorization_id']}" in message
    assert "exactly one native voice phase call" in message
    assert "exec_command" not in message
    assert "text_to_speech" in message
    assert "forbidden" in message


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


def test_gateway_leaves_short_visual_agent_video_request_unmodified(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(hooks, "_STORE", StoryVideoStateStore(tmp_path))

    result = hooks.pre_gateway_dispatch(
        event=_event("幫我做一支 6 秒產品介紹影片，從產品照開始。")
    )

    assert result is None


def test_explicit_visual_agent_turn_bypasses_active_story_hooks_once(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    monkeypatch.setattr(hooks, "_VISUAL_AGENT_BYPASS_SESSIONS", set())
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=start["text"])

    visual_turn = (
        '[Replying to: "故事影片：恐龍起源｜5分｜真實照片"]\n'
        "\n"
        "Visual Agent：幫我做一張產品照和 6 秒短片"
    )
    assert hooks.pre_llm_call(
        session_id="session-auto", user_message=visual_turn
    ) is None
    assert hooks.pre_tool_call(
        session_id="session-auto",
        tool_name="video_generate",
        args={"prompt": "short product clip", "provider": "xai"},
    ) is None
    assert hooks.transform_llm_output(
        session_id="session-auto", response_text="visual result"
    ) is None
    assert hooks.auto_continue_llm_output(
        session_id="session-auto", response_text="visual result"
    ) is None
    assert "session-auto" not in hooks._VISUAL_AGENT_BYPASS_SESSIONS

    resumed = hooks.pre_llm_call(
        session_id="session-auto", user_message="繼續"
    )
    assert resumed is not None
    assert "STORY_VIDEO_RUN_CONTEXT" in resumed["context"]


def test_youtube_package_and_upload_approval_are_distinct_active_project_actions(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(session_id="session-1", user_message=start["text"])

    package = hooks.pre_gateway_dispatch(event=_event("準備上架"))
    package_context = hooks.pre_llm_call(
        session_id="session-1", user_message=package["text"]
    )
    approval = hooks.pre_gateway_dispatch(event=_event("核准上傳 YouTube"))
    approval_context = hooks.pre_llm_call(
        session_id="session-1", user_message=approval["text"]
    )

    assert '"action": "package"' in package["text"]
    assert "Do not upload" in package_context["context"]
    assert "audience-facing" in package_context["context"]
    assert "production brief" in package_context["context"]
    assert "internal visual style" in package_context["context"]
    assert '"action": "approve_upload"' in approval["text"]
    assert "privacy=private" in approval_context["context"]
    assert "YouTube Data API" in approval_context["context"]
    assert "youtube_publish_from_manifest.py" in approval_context["context"]
    assert "Do not open YouTube Studio" in approval_context["context"]
    assert "SETUP_REQUIRED" in approval_context["context"]
    assert "public release requires a separate" in approval_context["context"]


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


def test_gateway_natural_stop_revokes_autopilot_and_uses_hard_stop(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=start["text"])
    assert store.for_session("session-auto").auto_mode is True

    stopped = hooks.pre_gateway_dispatch(event=_event("停止，不要做了"))

    assert stopped == {"action": "rewrite", "text": "/stop"}
    context = store.for_session("session-auto")
    assert context is not None
    assert context.status == "stopped"
    assert context.auto_mode is False
    assert hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROGRESS: batch IN_PROGRESS",
    ) is None
    blocked = hooks.pre_tool_call(
        session_id="session-auto",
        turn_id="stale-turn",
        tool_name="image_generate",
        args={"prompt": "stale generation", "provider": "openai-codex"},
    )
    assert blocked["action"] == "block"
    assert "stopped by the operator" in blocked["message"]


def test_gateway_natural_stop_cannot_be_triggered_by_unauthorized_sender(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=start["text"])
    gateway = SimpleNamespace(_is_user_authorized=lambda source: False)

    stopped = hooks.pre_gateway_dispatch(
        event=_event("停止，不要做了"),
        gateway=gateway,
    )

    assert stopped is None
    context = store.for_session("session-auto")
    assert context is not None
    assert context.status == "active"
    assert context.auto_mode is True


def test_unrelated_message_does_not_implicitly_resume_stopped_story_video(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=start["text"])
    hooks.pre_gateway_dispatch(event=_event("停止，不要做了"))

    result = hooks.pre_llm_call(
        session_id="session-auto",
        user_message="現在幾點？",
    )

    assert result is None
    context = store.for_session("session-auto")
    assert context is not None
    assert context.status == "stopped"
    assert context.auto_mode is False


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


def test_same_slack_thread_recovers_story_run_after_session_index_reset(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    parent = "故事影片：恐龍的起源｜5分鐘｜真實自然史紀錄片風格。只規劃。"
    original_event = _event(parent)
    context = store.create_or_load(
        source_key="gateway:pre-migration-source",
        session_id="session-before-reset",
        call=hooks.OperatorCall(
            action="start",
            topic="恐龍的起源",
            duration="5分鐘",
            visual_style="真實自然史紀錄片風格",
        ),
        original_request=parent,
    )
    context = store.update(context, phase="batch", auto_mode=True)
    reset_event = _event(
        "[Thread context — prior messages in this thread (not yet in conversation history):]\n"
        f"[thread parent] simon: {parent}\n"
        "simon: 全自動\n"
        "[End of thread context]\n"
        "請繼續",
        reply_to_text=parent,
    )

    rewritten = hooks.pre_gateway_dispatch(event=reset_event)
    result = hooks.pre_llm_call(
        session_id="session-after-reset",
        user_message=rewritten["text"],
    )

    resumed = store.for_session("session-after-reset")
    assert resumed is not None
    assert resumed.run_id == context.run_id
    assert resumed.phase == "batch"
    assert resumed.auto_mode is True
    assert '"action": "continue"' in rewritten["text"]
    assert "phase=batch" in result["context"]
    assert store.for_source(hooks._source_key(original_event)).run_id == context.run_id


def test_pre_llm_recovers_from_reply_wrapper_when_gateway_marker_is_missing(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    parent = "故事影片：恐龍起源｜5分鐘｜真實照片。只規劃。"
    context = store.create_or_load(
        source_key="source-before-reset",
        session_id="session-before-reset",
        call=hooks.OperatorCall(
            action="start",
            topic="恐龍起源",
            duration="5分鐘",
            visual_style="真實照片",
        ),
        original_request=parent,
    )
    context = store.update(context, phase="batch", auto_mode=True)

    result = hooks.pre_llm_call(
        session_id="session-after-reset",
        user_message=(
            f'[Replying to: "{parent}"]\n'
            "[Thread context — prior messages in this thread (not yet in conversation history):]\n"
            f"[thread parent] simon: {parent}\n"
            "simon: 全自動\n"
            "[End of thread context]\n"
            "請繼續"
        ),
    )

    resumed = store.for_session("session-after-reset")
    assert resumed is not None
    assert resumed.run_id == context.run_id
    assert resumed.phase == "batch"
    assert resumed.auto_mode is True
    assert "phase=batch" in result["context"]


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
    assert "story_video_control action=select_voice voice_id=<voice_id>" in result[
        "context"
    ]
    assert "story_video_voice_manager" in result["context"]
    assert "story_video_audio_director" in result["context"]
    assert "creative, remake, or read_aloud" in result["context"]
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
    assert "3-4 semantic shots per minute" in result["context"]
    assert "story_video_script_quality_v1" in result["context"]
    assert "quality_contract_version=6" in result["context"]
    assert "content_profile.json" in result["context"]
    assert "script_review_report.json" in result["context"]
    assert "story-video-script-review-board" in result["context"]
    assert "review_profile_id=family-review-board-v2" in result["context"]
    assert "story_video_editorial_metrics_v1" in result["context"]
    assert "concrete_scene_evidence" in result["context"]
    assert "reported_read_aloud_metrics" in result["context"]
    assert "audience_profile" in result["context"]
    assert "engagement_profile" in result["context"]
    assert "mode=young_explorer, energy=high, humor=light" in result["context"]
    assert (
        "young_explorer|discovery_documentary|human_drama|transformation|"
        "decision_tension|calm_wonder"
    ) in result["context"]
    assert "gentle|balanced|high" in result["context"]
    assert "none|light|playful" in result["context"]
    assert "story_moment" in result["context"]
    assert "visual_truth_mode" in result["context"]
    assert "audience_engagement" in result["context"]
    assert "visual_truth" in result["context"]
    assert "checks MUST be an object" in result["context"]
    assert "a top-level shots array on that scene item" in result["context"]
    assert "never nest shots under a scene object" in result["context"]
    assert "### S00" in result["context"]
    assert "never write spoken aliases into script.md" in result["context"]
    assert "acceptance_criteria MUST be a non-empty JSON array of strings" in result["context"]
    assert "15-20" in result["context"]
    assert "15-20 seconds" in result["context"]
    assert "at least two complete sentences" in result["context"]
    assert "complete narration beat" in result["context"]


def test_remake_rebinds_thread_to_revision_and_injects_source_boundary(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    started = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(session_id="session-old", user_message=started["text"])
    original = store.for_session("session-old")
    assert original is not None
    store.update(original, phase="complete", status="complete")

    remake = hooks.pre_gateway_dispatch(
        event=_event("沿用目前專案，全自動重新製作最新版。")
    )
    result = hooks.pre_llm_call(
        session_id="session-revision",
        user_message=remake["text"],
    )

    revised = store.for_session("session-revision")
    assert revised is not None
    assert revised.run_id != original.run_id
    assert revised.parent_run_id == original.run_id
    assert revised.source_project_dir == original.project_dir
    assert f"revision_source_run_id={original.run_id}" in result["context"]
    assert f"revision_source_project_dir={original.project_dir}" in result["context"]
    assert "never deliver any render from the revision source" in result["context"]


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
    assert "original_request is historical" in result["context"]
    assert "never edit story_video_run_context.json" in result["context"]
    assert "never edit production_checklist.json phase" in result["context"]
    assert "scene_ledger.json MUST use exact machine keys" in result["context"]
    assert "During batch, first call" not in result["context"]
    assert "During render, create dedicated release art" not in result["context"]

    context = store.update(context, phase="batch")
    batch = hooks.pre_llm_call(
        session_id="session-auto",
        user_message="繼續",
    )
    assert "story_video_quality_control" in batch["context"]
    assert "action=run_batch_chunk" in batch["context"]
    assert "shot_candidate_manifest.json" in batch["context"]
    assert "manually" in batch["context"]
    assert "Do not call image_generate" in batch["context"]
    assert "candidate_id_hint" not in batch["context"]
    assert "one canonical bounded work group per LLM turn" not in batch["context"]
    assert "scene_ledger.json MUST use exact machine keys" not in batch["context"]

    store.update(context, phase="render")
    render = hooks.pre_llm_call(
        session_id="session-auto",
        user_message="繼續",
    )
    assert "compile_release_art" in render["context"]
    assert "register_release_art" in render["context"]
    assert "before prepare_render" in render["context"]
    assert "--refresh-qc" in render["context"]
    assert "without re-encoding" in render["context"]
    assert "approved story-video music library" in render["context"]
    assert "must never download random or unlicensed music" in render["context"]
    assert "During batch, first call" not in render["context"]


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


def test_planning_only_request_auto_completes_bundle_then_holds_before_media(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event(
            "故事影片：海底火山｜5分鐘｜電影感寫實重建。只規劃，建立完整規劃檔並驗證。"
        )
    )
    hooks.pre_llm_call(session_id="session-plan", user_message=start["text"])
    context = store.for_session("session-plan")
    assert context is not None
    assert context.auto_mode is False
    assert context.planning_only is True

    incomplete = hooks.auto_continue_llm_output(
        session_id="session-plan",
        response_text="接下來我會建立規劃檔。",
    )

    assert incomplete is not None
    assert incomplete["action"] == "continue"
    assert "STORY_VIDEO_PLANNING_COMPLETION" in incomplete["message"]
    assert "Do not generate images, narration, or video" in incomplete["message"]

    _write_planning_fixture(context)
    ready = hooks.auto_continue_llm_output(
        session_id="session-plan",
        response_text="規劃檔已建立。",
    )

    assert ready is not None
    assert "story_video_control action=validate" in ready["message"]

    validated = json.loads(
        story_video_control(
            {"action": "validate"},
            session_id="session-plan",
            store=store,
        )
    )
    held = store.for_session("session-plan")

    assert validated["success"] is True
    assert validated["proof"] == "STORY_VIDEO_PHASE_PROOF: planning PASS"
    assert held is not None
    assert held.phase == "planning"
    assert held.status == "complete"
    assert held.last_validated_phase == "planning"
    assert hooks.auto_continue_llm_output(
        session_id="session-plan",
        response_text=validated["proof"],
    ) is None


def test_autopilot_rotates_before_continuation_history_bloats(
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
        response_text="STORY_VIDEO_PHASE_PROGRESS: planning IN_PROGRESS",
        message_count=hooks._AUTOPILOT_ROTATE_AFTER_MESSAGES,
        auto_continuation_count=1,
    )

    assert continuation is not None
    assert continuation["action"] == "rotate"
    assert continuation["reason"] == "story_video_context_budget"


def test_autopilot_context_budget_is_small_enough_for_batch_workers() -> None:
    assert hooks._AUTOPILOT_ROTATE_AFTER_CONTINUATIONS <= 3
    assert hooks._AUTOPILOT_BATCH_ROTATE_AFTER_CONTINUATIONS >= 8
    assert hooks._AUTOPILOT_ROTATE_AFTER_MESSAGES <= 80


def test_batch_autopilot_does_not_rotate_during_normal_native_chunks(
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
    store.update(context, phase="batch", auto_mode=True)
    monkeypatch.setattr(
        hooks,
        "_next_batch_work",
        lambda _context: {"success": True, "work_status": "ready"},
    )

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROGRESS: batch IN_PROGRESS",
        auto_continuation_count=3,
    )

    assert continuation is not None
    assert continuation["action"] == "continue"


def test_story_video_batch_parallelism_is_capped_at_three(monkeypatch) -> None:
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"story_video": {"batch_parallelism": 99}},
    )

    assert hooks._batch_parallelism() == 3


def test_story_video_batch_parallelism_respects_global_image_cap(monkeypatch) -> None:
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {
            "story_video": {"batch_parallelism": 3},
            "image_gen": {"max_parallel_requests": 2},
        },
    )

    assert hooks._batch_parallelism() == 2


def test_pre_llm_binds_rotated_child_to_parent_story_context(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-parent", user_message=start["text"])

    result = hooks.pre_llm_call(
        session_id="session-child",
        parent_session_id="session-parent",
        user_message="STORY_VIDEO_AUTOPILOT continue canonical next work",
    )

    child = store.for_session("session-child")
    assert child is not None
    assert child.run_id == store.for_session("session-parent").run_id
    assert child.auto_mode is True
    assert "STORY_VIDEO_RUN_CONTEXT" in result["context"]
    audit = json.loads(
        (child.project_dir / "manifests" / "provider_audit.json").read_text(
            encoding="utf-8"
        )
    )
    rotation = audit["events"][-1]
    assert rotation["kind"] == "session_rotation"
    assert rotation["session_id"] == "session-child"
    assert rotation["detail"]["parent_session_id"] == "session-parent"


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


def test_autopilot_recovers_when_visual_strategy_budget_is_exhausted(
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
    store.update(context, phase="keyframes", auto_mode=True)

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text=(
            "錨點第二版的 vision QC 得分 78.11，低於 80，且該視覺策略額度已耗盡。"
            "我現在走 canonical bounded repair／replan 路徑。"
        ),
        recoverable_transport_error=True,
        turn_error="codex went silent for 90s after a tool result",
    )

    assert continuation is not None
    assert continuation["action"] == "rotate"
    assert continuation["reason"] == "story_video_transport_recovery"
    assert "phase=keyframes" in continuation["message"]


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


def test_planning_autopilot_does_not_stall_when_artifacts_advance(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    start = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=start["text"])

    assert hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="",
        recoverable_transport_error=True,
        turn_error="codex went silent for 90s after a tool result",
    ) is not None

    context = store.for_session("session-auto")
    assert context is not None
    (context.project_dir / "script.md").write_text(
        "### S00\n新的旁白進度", encoding="utf-8"
    )

    assert hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="",
        recoverable_transport_error=True,
        turn_error="codex went silent for 90s after a tool result",
    ) is not None
    advanced = store.for_session("session-auto")
    assert advanced is not None
    assert advanced.autopilot_stall_count == 1


def test_batch_autopilot_continuation_names_exact_next_quality_tool_call(
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
    shot = {
        "shot_id": "S03_SH01", "narration_text": "旁白", "subject": "恐龍",
        "action": "行走", "evidence_detail": "腿部", "shot_scale": "wide",
        "camera_angle": "side", "focal_point": "body",
        "subtitle_safe_area": "right top", "acceptance_criteria": ["clear"],
    }
    (context.project_dir / "scene_ledger.json").write_text(json.dumps({
        "scenes": [{"scene_id": "S03", "shots": [shot]}]
    }), encoding="utf-8")
    manifest = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"outputs": [{
        "shot_id": "S03_SH01", "status": "repair_required", "selected": False,
        "repair_round": 1, "hard_blockers": ["subtitle collision"],
    }]}), encoding="utf-8")
    context = store.update(context, phase="batch")

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROOF: batch BLOCKED",
    )

    assert continuation is not None
    assert "story_video_quality_control action=run_batch_chunk" in continuation[
        "message"
    ]
    assert "shot_id=S03_SH01" not in continuation["message"]
    assert "compile_prompt" in continuation["message"]


def test_batch_autopilot_uses_image_edit_source_for_targeted_repair(
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
    store.update(context, phase="batch", auto_mode=True)
    monkeypatch.setattr(
        hooks,
        "_next_batch_work",
        lambda _context: {
            "success": True,
            "work_status": "ready",
            "operation": "repair",
            "shot_id": "S03_SH01",
            "candidate_id_hint": "S03_SH01_C02",
            "repair_strategy": "targeted_repair",
            "shot_contract_hash": "contract-hash",
            "source_image_url": "/tmp/S03_SH01_C01.png",
            "source_candidate_id": "S03_SH01_C01",
            "remaining_shot_count": 2,
        },
    )

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROGRESS: batch IN_PROGRESS",
    )

    assert continuation is not None
    message = continuation["message"]
    assert "story_video_quality_control action=run_batch_chunk" in message
    assert "image_url=/tmp/S03_SH01_C01.png" not in message
    assert "Do not call image_generate" in message


def test_batch_autopilot_continuation_batches_fresh_generation(
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
    store.update(context, phase="batch", auto_mode=True)
    monkeypatch.setattr(
        hooks,
        "_next_batch_work",
        lambda _context: {
            "success": True,
            "work_status": "ready",
            "operation": "generate_batch",
            "parallelism": 3,
            "remaining_shot_count": 4,
            "work_items": [
                {
                    "operation": "generate",
                    "shot_id": f"S00_SH0{index}",
                    "candidate_id_hint": f"S00_SH0{index}_C01",
                    "repair_strategy": "initial",
                }
                for index in range(3)
            ],
        },
    )

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROGRESS: batch IN_PROGRESS",
    )

    assert continuation is not None
    message = continuation["message"]
    assert "story_video_quality_control action=run_batch_chunk" in message
    assert "S00_SH00_C01" not in message
    assert "up to three parallel OpenAI image requests" in message


def test_batch_autopilot_uses_native_chunk_instead_of_llm_shot_scheduler(
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
    store.update(context, phase="batch", auto_mode=True)
    monkeypatch.setattr(
        hooks,
        "_next_batch_work",
        lambda _context: (_ for _ in ()).throw(
            AssertionError("legacy shot scheduler must not run")
        ),
    )

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROGRESS: batch IN_PROGRESS",
    )

    assert continuation is not None
    assert "story_video_quality_control action=run_batch_chunk" in continuation[
        "message"
    ]
    assert "work_items=" not in continuation["message"]


def test_batch_autopilot_validates_when_canonical_work_is_complete(
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
    store.update(
        context,
        phase="batch",
        auto_mode=True,
        repair_request="補齊 batch：repeated_shot_scale_without_reason:medium:3",
    )
    monkeypatch.setattr(
        hooks,
        "_batch_assets_complete",
        lambda _context: True,
    )

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROOF: batch BLOCKED",
    )

    assert continuation is not None
    assert "story_video_control action=validate" in continuation["message"]
    assert "Execute the next action now: None" not in continuation["message"]


def test_batch_autopilot_does_not_repeat_human_review_required_work(
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
    store.update(
        context,
        phase="batch",
        auto_mode=True,
        repair_request="補齊 batch：S00_SH01.selected_asset",
    )
    monkeypatch.setattr(
        hooks,
        "_next_batch_work",
        lambda _context: {
            "work_status": "human_review_required",
            "shot_id": "S00_SH01",
            "error": "all evidence-backed repairs exhausted",
        },
    )

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text=(
            "STORY_VIDEO_PHASE_ATTENTION: batch REVIEW_REQUIRED shot_id=S00_SH01"
        ),
    )

    assert continuation is None


def test_batch_autopilot_executes_bounded_shot_contract_replan(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    hooks.pre_llm_call(
        session_id="session-auto",
        user_message="故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。",
    )
    context = store.for_session("session-auto")
    assert context is not None
    store.update(context, phase="batch", auto_mode=True)
    monkeypatch.setattr(
        hooks,
        "_next_batch_work",
        lambda _context: {
            "success": True,
            "work_status": "ready",
            "operation": "replan_shot_contract",
            "shot_id": "S00_SH02",
            "replan_revision": 1,
            "max_replan_revisions": 2,
            "immutable_contract": {
                "narration_text": "海洋與陸地上的生命大量消失，",
                "viewer_takeaway": "生態崩潰留下空缺",
                "visual_truth_mode": "reconstruction",
            },
            "mutable_fields": [
                "subject",
                "action",
                "evidence_detail",
                "shot_scale",
                "camera_angle",
                "focal_point",
                "subtitle_safe_area",
                "acceptance_criteria",
            ],
            "hard_blockers": ["the prior image did not show the declared evidence"],
        },
    )

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROGRESS: batch IN_PROGRESS",
    )

    assert continuation is not None
    message = continuation["message"]
    assert "story_video_quality_control action=run_batch_chunk" in message
    assert "operation=replan_shot_contract" not in message
    assert "Do not call image_generate" in message


def test_batch_autopilot_rejudges_existing_candidate_without_image_generation(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    hooks.pre_llm_call(
        session_id="session-auto",
        user_message="故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。",
    )
    context = store.for_session("session-auto")
    assert context is not None
    shot = {
        "shot_id": "S03_SH04",
        "narration_text": "旁白",
        "narrative_role": "evidence",
        "viewer_takeaway": "看懂足跡如何形成",
        "subject": "恐龍腳掌",
        "action": "離開泥面",
        "evidence_detail": "清楚足跡",
        "shot_scale": "close_up",
        "camera_angle": "eye_level",
        "focal_point": "腳掌與足跡",
        "subtitle_safe_area": "lower_third",
        "acceptance_criteria": ["foot and track are readable"],
        "risk_class": "standard",
        "engagement_role": "reveal",
        "attention_hook": "泥地留下什麼",
        "story_moment": "腳掌剛離開泥面",
        "action_consequence": "足跡留在泥面",
        "composition_energy": "curious",
        "viewer_emotion": "discovery",
        "engagement_criteria": ["cause and effect are readable"],
        "visual_truth_mode": "reconstruction",
    }
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps(
            {
                "quality_contract_version": 3,
                "audience_profile": {
                    "age_band": "general",
                    "knowledge_level": "newcomer",
                    "attention_style": "curious_explorer",
                    "safety_intensity": "standard",
                },
                "engagement_profile": {
                    "mode": "discovery_documentary",
                    "energy": "balanced",
                    "humor": "none",
                    "sensationalism_forbidden": True,
                },
                "scenes": [{"scene_id": "S03", "shots": [shot]}],
            }
        ),
        encoding="utf-8",
    )
    candidate_path = context.project_dir / "images" / "S03_SH04.png"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_bytes(b"candidate")
    manifest = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "shot_id": "S03_SH04",
                        "candidate_id": "S03_SH04_C01",
                        "selected": True,
                        "status": "selected_current",
                        "provider": "openai-codex",
                        "model": "gpt-image-2-high",
                        "candidate_path": str(candidate_path),
                        "local_path": str(candidate_path),
                        "repair_round": 1,
                        "quality_dimensions": {
                            "text_alignment": 88,
                            "focal_clarity": 88,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    store.update(context, phase="batch")

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROOF: batch BLOCKED",
    )

    assert continuation is not None
    message = continuation["message"]
    assert "story_video_quality_control action=run_batch_chunk" in message
    assert "S03_SH04_C01_V3_REVIEW" not in message
    assert str(candidate_path) not in message
    assert "Do not call image_generate" in message


def test_batch_transport_recovery_is_bounded_and_uses_current_next_work(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    hooks.pre_llm_call(
        session_id="session-auto",
        user_message="故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。",
    )
    context = store.for_session("session-auto")
    assert context is not None
    shot = {
        "shot_id": "S03_SH02", "narration_text": "旁白", "subject": "兔蜥",
        "action": "警戒", "evidence_detail": "長後肢", "shot_scale": "medium",
        "camera_angle": "eye_level", "focal_point": "body",
        "subtitle_safe_area": "upper_left", "acceptance_criteria": ["clear"],
    }
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps({"scenes": [{"scene_id": "S03", "shots": [shot]}]}),
        encoding="utf-8",
    )
    manifest = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"outputs": [{
        "shot_id": "S03_SH02", "status": "repair_required", "selected": False,
        "repair_round": 1, "hard_blockers": ["subtitle collision"],
    }]}), encoding="utf-8")
    store.update(
        context,
        phase="batch",
        repair_request="補齊 batch：S03_SH01.selected_asset",
    )

    kwargs = {
        "session_id": "session-auto",
        "response_text": "completed image output was preserved",
        "recoverable_transport_error": True,
        "turn_error": "codex went silent for 90s after a tool result",
    }
    first = hooks.auto_continue_llm_output(**kwargs)
    second = hooks.auto_continue_llm_output(**kwargs)
    third = hooks.auto_continue_llm_output(**kwargs)

    assert first is not None
    assert first["action"] == "rotate"
    assert "story_video_quality_control action=run_batch_chunk" in first["message"]
    assert "S03_SH01.selected_asset" not in first["message"]
    assert second is not None
    assert second["action"] == "rotate"
    assert third is None


def test_batch_autopilot_names_adaptive_repair_strategy(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    hooks.pre_llm_call(
        session_id="session-auto",
        user_message="故事影片：恐龍起源｜5分鐘｜真實照片。完整製作並出片。",
    )
    context = store.for_session("session-auto")
    assert context is not None
    shot = {
        "shot_id": "S03_SH03", "narration_text": "旁白", "subject": "顎骨",
        "action": "展示", "evidence_detail": "牙齒", "shot_scale": "macro",
        "camera_angle": "eye_level", "focal_point": "牙列",
        "subtitle_safe_area": "right_third", "acceptance_criteria": ["partial"],
    }
    (context.project_dir / "scene_ledger.json").write_text(json.dumps({
        "scenes": [{"scene_id": "S03", "shots": [shot]}]
    }), encoding="utf-8")
    manifest = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"outputs": [{
        "shot_id": "S03_SH03", "status": "quality_budget_exhausted",
        "selected": False, "repair_round": 1, "strategy_reset": True,
        "hard_blockers": ["科學與解剖辨識不足", "牙齒幾何疑似失真"],
    }]}), encoding="utf-8")
    store.update(context, phase="batch")

    continuation = hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text="STORY_VIDEO_PHASE_PROOF: batch BLOCKED",
    )

    assert continuation is not None
    assert "story_video_quality_control action=run_batch_chunk" in continuation[
        "message"
    ]
    assert "candidate_id_hint=S03_SH03_EVIDENCE_C01" not in continuation[
        "message"
    ]


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


def test_detailed_next_instruction_keeps_active_project_binding(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    hooks.pre_llm_call(
        session_id="session-1",
        user_message="故事影片：恐龍起源｜5分｜真實照片",
    )
    original = store.for_session("session-1")
    assert original is not None
    store.update(original, phase="batch")

    result = hooks.pre_llm_call(
        session_id="session-1",
        user_message="故事影片下一步。只執行一個 QC cycle：處理 S03_SH03。",
    )

    current = store.for_session("session-1")
    assert current is not None
    assert current.run_id == original.run_id
    assert current.phase == "batch"
    assert "Operator action=continue" in result["context"]


def test_pre_tool_guard_locks_story_session_to_openai_without_prompt_markers(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片")
    )
    hooks.pre_llm_call(session_id="session-1", user_message=rewritten["text"])

    implicit_args = {"prompt": "A dinosaur beside a river"}
    implicit = hooks.pre_tool_call(
        session_id="session-1",
        turn_id="turn-1",
        tool_name="image_generate",
        args=implicit_args,
    )
    explicit_xai = hooks.pre_tool_call(
        session_id="session-1",
        turn_id="turn-1",
        tool_name="image_generate",
        args={
            "prompt": "A dinosaur beside a river",
            "provider": "xai",
        },
    )

    assert implicit is None
    assert implicit_args["_provider"] == "openai-codex"
    assert explicit_xai["action"] == "block"
    assert "xai" in explicit_xai["message"]


def test_transform_output_reports_ready_batch_as_progress_not_phase_failure(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=rewritten["text"])
    context = store.for_session("session-auto")
    assert context is not None
    shot = {
        "shot_id": "S05_SH01",
        "narration_text": "新的生態空缺出現了。",
        "subject": "河谷",
        "action": "薄霧散開",
        "evidence_detail": "河道與植被",
        "shot_scale": "wide",
        "camera_angle": "eye_level",
        "focal_point": "river",
        "subtitle_safe_area": "lower_third",
        "acceptance_criteria": ["river is readable"],
    }
    (context.project_dir / "scene_ledger.json").write_text(
        json.dumps({"scenes": [{"scene_id": "S05", "shots": [shot]}]}),
        encoding="utf-8",
    )
    store.update(context, phase="batch", auto_mode=True)
    hooks.pre_llm_call(session_id="session-auto", user_message="繼續")

    result = hooks.transform_llm_output(
        response_text="已完成目前的工具呼叫。",
        session_id="session-auto",
    )

    assert "STORY_VIDEO_PHASE_PROGRESS: batch IN_PROGRESS" in result
    assert "shot_id=S05_SH01" not in result
    assert "STORY_VIDEO_PHASE_PROOF: batch BLOCKED" not in result
    assert ".selected_asset" not in result


def test_transform_output_preserves_native_human_review_required(
    tmp_path, monkeypatch
) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=rewritten["text"])
    context = store.for_session("session-auto")
    assert context is not None
    store.update(context, phase="batch", auto_mode=True)
    hooks.pre_llm_call(session_id="session-auto", user_message="繼續")
    response = (
        "STORY_VIDEO_PHASE_ATTENTION: batch REVIEW_REQUIRED shot_id=S00_SH00"
    )

    result = hooks.transform_llm_output(
        response_text=response,
        session_id="session-auto",
    )

    assert result == response
    assert hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text=result,
    ) is None


def test_transform_output_preserves_real_batch_setup_blocker(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    monkeypatch.setattr(hooks, "_STORE", store)
    rewritten = hooks.pre_gateway_dispatch(
        event=_event("故事影片：恐龍起源｜5分｜真實照片。完整製作並出片。")
    )
    hooks.pre_llm_call(session_id="session-auto", user_message=rewritten["text"])
    context = store.for_session("session-auto")
    assert context is not None
    store.update(context, phase="batch", auto_mode=True)
    monkeypatch.setattr(
        hooks,
        "_next_batch_work",
        lambda _context: {
            "work_status": "ready",
            "operation": "generate",
            "shot_id": "S00_SH01",
            "remaining_shot_count": 1,
        },
    )
    hooks.pre_llm_call(session_id="session-auto", user_message="繼續")

    result = hooks.transform_llm_output(
        response_text="OpenAI quota exhausted; setup required.",
        session_id="session-auto",
    )

    assert result == "OpenAI quota exhausted; setup required."
    assert hooks.auto_continue_llm_output(
        session_id="session-auto",
        response_text=result,
    ) is None


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


def test_transform_output_blocks_same_project_alias_with_selected_render_content(
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
    selected = context.project_dir / "video" / "final.mp4"
    review_alias = context.project_dir / "video" / "恐龍起源_review.mp4"
    selected.parent.mkdir(parents=True)
    selected.write_bytes(b"current-selected-render")
    review_alias.write_bytes(selected.read_bytes())
    (context.project_dir / "render_manifest.json").write_text(
        json.dumps({"output": {"path": "video/final.mp4"}}),
        encoding="utf-8",
    )
    store.update(context, phase="complete", status="complete")

    blocked = hooks.transform_llm_output(
        response_text=f"新版已完成：MEDIA:{review_alias}",
        session_id="session-1",
    )

    assert "STORY_VIDEO_DELIVERY_BLOCKED" in blocked
    assert str(review_alias) not in blocked


def test_transform_output_blocks_matching_render_content_outside_current_project(
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
    selected = context.project_dir / "video" / "final.mp4"
    cross_project = tmp_path / "other-project" / "final.mp4"
    selected.parent.mkdir(parents=True)
    cross_project.parent.mkdir(parents=True)
    selected.write_bytes(b"current-selected-render")
    cross_project.write_bytes(selected.read_bytes())
    (context.project_dir / "render_manifest.json").write_text(
        json.dumps({"output": {"path": "video/final.mp4"}}),
        encoding="utf-8",
    )
    store.update(context, phase="complete", status="complete")

    blocked = hooks.transform_llm_output(
        response_text=f"新版已完成：MEDIA:{cross_project}",
        session_id="session-1",
    )

    assert str(cross_project) not in blocked
    assert "STORY_VIDEO_DELIVERY_BLOCKED" in blocked
