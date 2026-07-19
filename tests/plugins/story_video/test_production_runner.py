from __future__ import annotations

import hashlib
import importlib.util
from types import SimpleNamespace

import pytest

from plugins.story_video.production import ProductionJobStore
from plugins.story_video.state import StoryVideoStateStore, parse_operator_call


def test_production_runner_module_exists() -> None:
    assert importlib.util.find_spec("plugins.story_video.production_runner") is not None


def _render_context(tmp_path):
    store = StoryVideoStateStore(tmp_path)
    text = "故事影片：夜班故事｜1分｜全黑背景加字幕。"
    call = parse_operator_call(text)
    assert call is not None
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=call,
        original_request=text,
    )
    return store, store.update(context, phase="render")


def test_runner_resumes_at_render_and_marks_artifact_ready(tmp_path) -> None:
    from plugins.story_video.production_runner import run_production

    store, context = _render_context(tmp_path)
    final = context.project_dir / "video" / "final.mp4"
    calls = []

    def renderer(_context):
        calls.append("render")
        final.parent.mkdir(parents=True)
        final.write_bytes(b"video")
        return {"success": True, "video": str(final), "qc_report": "render_qc.json"}

    result = run_production(
        context.run_id,
        context.project_dir,
        store=store,
        voice_runner=lambda _context: calls.append("voice"),
        voice_validator=lambda _context: SimpleNamespace(
            ok=True, missing=(), violations=()
        ),
        render_preparer=lambda _context: calls.append("prepare"),
        renderer=renderer,
        render_validator=lambda _context: SimpleNamespace(ok=True, missing=(), violations=()),
        delivery_speech_validator=lambda _context, _video: {
            "success": True,
            "qc_report": "qc/final_speech_qc_report.json",
            "video_sha256": "a" * 64,
        },
    )

    assert calls == ["prepare", "render"]
    assert result["success"] is True
    assert result["work_status"] == "artifact_ready"
    assert result["media"] == [f"MEDIA:{final.resolve()}"]
    assert ProductionJobStore(context.project_dir).load()["status"] == "artifact_ready"
    assert store.for_run(run_id=context.run_id, project_dir=context.project_dir).phase == "complete"


def test_runner_blocks_story_visual_artifact_without_final_mp4_speech_qc(
    tmp_path,
) -> None:
    from plugins.story_video.production_runner import run_production

    store = StoryVideoStateStore(tmp_path)
    text = "故事影片：夜班故事｜1分｜故事圖片加字幕。"
    call = parse_operator_call(text)
    assert call is not None
    context = store.create_or_load(
        source_key="source-visual",
        session_id="session-visual",
        call=call,
        original_request=text,
    )
    context = store.update(context, phase="render")
    final = context.project_dir / "video" / "final.mp4"

    def renderer(_context):
        final.parent.mkdir(parents=True)
        final.write_bytes(b"video-with-tone-not-speech")
        return {"success": True, "video": str(final), "qc_report": "render_qc.json"}

    result = run_production(
        context.run_id,
        context.project_dir,
        store=store,
        voice_validator=lambda _context: SimpleNamespace(
            ok=True, missing=(), violations=()
        ),
        render_preparer=lambda _context: None,
        renderer=renderer,
        render_validator=lambda _context: SimpleNamespace(
            ok=True, missing=(), violations=()
        ),
        delivery_speech_validator=lambda _context, _video: {
            "success": False,
            "error": "final MP4 ASR transcript is empty",
        },
    )

    assert result["success"] is False
    assert result["error_type"] == "final_speech_qc_failed"
    assert "ASR transcript is empty" in result["error"]
    assert "media" not in result


def test_runner_records_render_failure_without_claiming_media(tmp_path) -> None:
    from plugins.story_video.production_runner import run_production

    store, context = _render_context(tmp_path)

    result = run_production(
        context.run_id,
        context.project_dir,
        store=store,
        voice_validator=lambda _context: SimpleNamespace(
            ok=True, missing=(), violations=()
        ),
        render_preparer=lambda _context: None,
        renderer=lambda _context: {"success": False, "error": "ffmpeg exited 1"},
        render_validator=lambda _context: SimpleNamespace(ok=False, missing=(), violations=()),
    )

    assert result["success"] is False
    assert result["work_status"] == "failed"
    assert result["error_type"] == "render_failed"
    assert "media" not in result
    assert ProductionJobStore(context.project_dir).load()["status"] == "failed"


def test_runner_blocks_render_resume_without_current_voice_qc(tmp_path) -> None:
    from plugins.story_video.production_runner import run_production

    store, context = _render_context(tmp_path)
    rendered = []

    result = run_production(
        context.run_id,
        context.project_dir,
        store=store,
        voice_validator=lambda _context: SimpleNamespace(
            ok=False,
            missing=("qc/pronunciation_qc_report.json",),
            violations=("local Qwen pronunciation QC is not PASS",),
        ),
        render_preparer=lambda _context: None,
        renderer=lambda _context: rendered.append(True),
    )

    assert result["success"] is False
    assert result["error_type"] == "voice_qc_failed"
    assert "pronunciation_qc_report.json" in result["error"]
    assert rendered == []


@pytest.mark.parametrize("legacy_status", ["artifact_ready", "delivered"])
def test_runner_revalidates_stale_complete_artifact_without_rerendering(
    tmp_path, legacy_status
) -> None:
    from plugins.story_video.production_runner import run_production

    store, context = _render_context(tmp_path)
    context = store.update(context, phase="complete", status="complete")
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"legacy-video")
    jobs = ProductionJobStore(context.project_dir)
    jobs.transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="artifact_ready",
        selected_mp4=str(final),
    )
    if legacy_status == "delivered":
        jobs.transition(
            run_id=context.run_id,
            visual_mode=context.visual_mode,
            status="delivered",
            selected_mp4=str(final),
        )
    jobs.transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="failed",
        error_type="final_speech_qc_stale",
        selected_mp4=str(final),
    )
    rendered = []

    result = run_production(
        context.run_id,
        context.project_dir,
        store=store,
        renderer=lambda _context: rendered.append(True),
        delivery_speech_validator=lambda _context, video: {
            "success": True,
            "qc_report": "qc/final_speech_qc_report.json",
            "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        },
    )

    assert result["work_status"] == "artifact_ready"
    assert result["selected_mp4"] == str(final.resolve())
    assert rendered == []
