from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from plugins import story_video
from plugins.story_video import hooks
from plugins.story_video.guide import (
    format_raphael_next_action,
    format_story_video_guide,
    operator_next_call,
)
from plugins.story_video.state import StoryVideoRunContext, StoryVideoStateStore, parse_operator_call


def _context(tmp_path, **changes) -> StoryVideoRunContext:
    context = StoryVideoRunContext(
        run_id="run-1",
        project_id="curious-dinosaurs-run-1",
        project_dir=tmp_path / "curious-dinosaurs-run-1",
        source_key="source-1",
        session_ids=("session-1",),
        original_request="故事影片：恐龍起源｜5分｜電影感。全自動",
        topic="恐龍起源",
        duration="5分",
        visual_style="電影感",
    )
    return replace(context, **changes)


def _event(text: str = "/story-video status"):
    return SimpleNamespace(
        text=text,
        reply_to_message_id="thread-1",
        reply_to_text=None,
        source=SimpleNamespace(
            platform="slack",
            scope_id="workspace-1",
            chat_id="channel-1",
            thread_id="thread-1",
            user_id="user-1",
        ),
    )


def test_help_is_compact_and_copy_ready() -> None:
    text = format_story_video_guide(None, "help")

    assert text.startswith("故事影片 Help")
    assert "/story-video status" in text
    assert "/story-video writing" in text
    assert "故事影片：<主題>｜<時長>｜<風格>。全自動" in text
    assert "淺顯但不幼稚" in text
    assert "story_video_control" not in text


def test_status_without_project_is_actionable() -> None:
    text = format_story_video_guide(None, "status")

    assert "沒有綁定故事影片" in text
    assert "全自動" in text


def test_manual_status_uses_canonical_repair_call(tmp_path) -> None:
    context = _context(
        tmp_path,
        phase="batch",
        repair_request="補齊 S03_SH03.selected_asset",
        repair_phase="batch",
    )

    text = format_story_video_guide(context, "status")

    assert "階段：batch" in text
    assert "模式：手動" in text
    assert "修正：補齊 S03_SH03.selected_asset" in text
    assert operator_next_call(context) == "修正：補齊 S03_SH03.selected_asset"


def test_auto_status_requires_no_operator_action(tmp_path) -> None:
    text = format_story_video_guide(
        _context(tmp_path, phase="batch", auto_mode=True),
        "status",
    )

    assert "模式：全自動" in text
    assert "不需要操作" in text
    assert "停止" in text


def test_stopped_and_complete_status_have_post_run_actions(tmp_path) -> None:
    stopped = _context(tmp_path, phase="voice", status="stopped")
    complete = _context(tmp_path, phase="complete", status="complete")

    assert operator_next_call(stopped) == "繼續"
    assert "要全自動則回覆「全自動」" in format_story_video_guide(
        stopped,
        "status",
    )
    assert operator_next_call(complete) == "準備上架"
    assert "YouTube 審核包" in format_story_video_guide(complete, "status")


def test_planning_hold_prompts_for_production_authorization_not_upload(tmp_path) -> None:
    planning_hold = _context(
        tmp_path,
        original_request="故事影片：恐龍起源｜5分｜電影感。只規劃。",
        phase="planning",
        status="complete",
        last_validated_phase="planning",
    )

    assert operator_next_call(planning_hold) == "全自動"
    assert format_raphael_next_action(planning_hold) == (
        "Raphael 下一步：回覆「全自動」。"
    )
    status = format_story_video_guide(planning_hold, "status")
    assert "開始製作影像、旁白與影片" in status
    assert "準備上架" not in status


def test_examples_cover_creation_and_dubbing_modes() -> None:
    text = format_story_video_guide(None, "examples")

    assert "只規劃" in text
    assert "全自動" in text
    assert "創作模式" in text
    assert "重製模式" in text
    assert "說書模式" in text
    assert "凱因斯經濟學" in text
    assert "進階版" in text
    assert "專業版，不要淺白化" in text


def test_writing_help_explains_default_and_opt_out() -> None:
    text = format_story_video_guide(None, "writing")

    assert "預設：淺顯但不幼稚" in text
    assert "具體直覺" in text
    assert "正式名詞" in text
    assert "進階版" in text
    assert "專業版" in text
    assert "不要淺白化" in text
    assert "敘事主軸" in text
    assert "冷開場" in text
    assert "跨場懸念" in text
    assert "因果接棒" in text
    assert "回扣結尾" in text


def test_voice_guide_exposes_ids_without_private_paths() -> None:
    text = format_story_video_guide(
        None,
        "voices",
        voices={
            "default_profile_id": "simon_clean_v2",
            "profiles": [
                {
                    "voice_id": "simon",
                    "profile_id": "simon_clean_v2",
                    "display_name": "Simon",
                    "version": 2,
                    "enabled": True,
                    "selectable": True,
                    "profile_path": "/private/voice/profile.json",
                    "reference_audio": "/private/voice/reference.wav",
                },
                {
                    "voice_id": "old",
                    "profile_id": "old_v1",
                    "enabled": False,
                    "selectable": False,
                },
            ],
        },
    )

    assert "simon" in text
    assert "simon_clean_v2" in text
    assert "old_v1" not in text
    assert "/private/voice" not in text


def test_raphael_next_action_uses_operator_next_call(tmp_path) -> None:
    context = _context(tmp_path, phase="render")

    assert operator_next_call(context) == "出片"
    assert format_raphael_next_action(context) == "Raphael 下一步：回覆「出片」。"
    assert format_raphael_next_action(replace(context, auto_mode=True)) is None


def test_slash_status_is_read_only_and_thread_aware(tmp_path, monkeypatch) -> None:
    store = StoryVideoStateStore(tmp_path)
    event = _event()
    source_key = hooks._source_key(event)
    call = parse_operator_call("故事影片：恐龍起源｜5分｜電影感")
    assert call is not None
    context = store.create_or_load(
        source_key=source_key,
        session_id="session-1",
        call=call,
        original_request="故事影片：恐龍起源｜5分｜電影感",
    )
    monkeypatch.setattr(hooks, "_STORE", store)
    state_path = store.run_state_root / f"{context.run_id}.json"
    before = state_path.read_bytes()

    result = hooks.handle_story_video_command("status", event=event)

    assert "恐龍起源" in result
    assert "階段：planning" in result
    assert state_path.read_bytes() == before


def test_story_video_plugin_registers_discoverable_command() -> None:
    commands = []

    class FakeContext:
        llm = None

        def register_tool(self, **_kwargs):
            return None

        def register_hook(self, *_args, **_kwargs):
            return None

        def register_command(self, name, handler, **metadata):
            commands.append((name, handler, metadata))

    story_video.register(FakeContext())

    assert len(commands) == 1
    name, handler, metadata = commands[0]
    assert name == "story-video"
    assert handler is hooks.handle_story_video_command
    assert "status" in metadata["args_hint"]
