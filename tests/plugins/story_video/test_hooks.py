from __future__ import annotations

import json
from types import SimpleNamespace

from plugins.story_video import hooks
from plugins.story_video.audit import ProviderAudit
from plugins.story_video.state import StoryVideoStateStore


def _event(text: str):
    return SimpleNamespace(
        text=text,
        source=SimpleNamespace(
            platform="slack",
            scope_id="workspace-1",
            chat_id="channel-1",
            thread_id="thread-1",
            user_id="user-1",
        ),
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
    (context.project_dir / "PROJECT_CONTRACT.md").write_text("contract", encoding="utf-8")
    (context.project_dir / "storyboard.md").write_text("storyboard", encoding="utf-8")
    (context.project_dir / "scene_ledger.json").write_text("{}", encoding="utf-8")
    (context.project_dir / "production_checklist.json").write_text("{}", encoding="utf-8")

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
    (context.project_dir / "PROJECT_CONTRACT.md").write_text("contract", encoding="utf-8")
    (context.project_dir / "storyboard.md").write_text("storyboard", encoding="utf-8")
    (context.project_dir / "scene_ledger.json").write_text("{}", encoding="utf-8")
    (context.project_dir / "production_checklist.json").write_text("{}", encoding="utf-8")

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
    (context.project_dir / "PROJECT_CONTRACT.md").write_text("contract", encoding="utf-8")
    (context.project_dir / "storyboard.md").write_text("storyboard", encoding="utf-8")
    (context.project_dir / "scene_ledger.json").write_text("{}", encoding="utf-8")
    (context.project_dir / "production_checklist.json").write_text("{}", encoding="utf-8")
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
