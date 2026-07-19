from __future__ import annotations

import importlib.util
import importlib
import json

import pytest

from plugins.story_video.state import StoryVideoStateStore, parse_operator_call


def _context(tmp_path):
    store = StoryVideoStateStore(tmp_path)
    call = parse_operator_call(
        "故事影片：夜班故事｜1分｜全黑背景加字幕。完整製作並出片。"
    )
    assert call is not None
    return store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=call,
        original_request="故事影片：夜班故事｜1分｜全黑背景加字幕。完整製作並出片。",
    )


def test_production_module_exists() -> None:
    assert importlib.util.find_spec("plugins.story_video.production") is not None


def _production():
    return importlib.import_module("plugins.story_video.production")


def test_start_production_launches_one_tracked_background_process(tmp_path) -> None:
    context = _context(tmp_path)
    start_production = _production().start_production
    calls: list[dict] = []

    def fake_terminal(**kwargs):
        calls.append(kwargs)
        return json.dumps({"status": "running", "session_id": "proc-1"})

    payload = start_production(context, terminal_runner=fake_terminal)

    assert payload["success"] is True
    assert payload["work_status"] == "running"
    assert payload["process_session_id"] == "proc-1"
    assert len(calls) == 1
    assert calls[0]["background"] is True
    assert calls[0]["notify_on_complete"] is True
    assert calls[0]["workdir"] == str(context.project_dir.resolve())
    assert calls[0]["session_id"] == "session-1"
    assert "plugins.story_video.production_runner" in calls[0]["command"]
    assert context.run_id in calls[0]["command"]


def test_start_production_does_not_launch_twice_while_running(tmp_path) -> None:
    context = _context(tmp_path)
    start_production = _production().start_production
    calls = 0

    def fake_terminal(**_kwargs):
        nonlocal calls
        calls += 1
        return json.dumps({"status": "running", "session_id": "proc-1"})

    first = start_production(context, terminal_runner=fake_terminal)
    second = start_production(context, terminal_runner=fake_terminal)

    assert first["process_session_id"] == "proc-1"
    assert second["process_session_id"] == "proc-1"
    assert second["already_running"] is True
    assert calls == 1


def test_fast_worker_terminal_state_is_not_overwritten_by_launcher(tmp_path) -> None:
    context = _context(tmp_path)
    module = _production()
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"video")

    def fast_terminal(**_kwargs):
        module.ProductionJobStore(context.project_dir).transition(
            run_id=context.run_id,
            visual_mode=context.visual_mode,
            status="artifact_ready",
            selected_mp4=str(final),
        )
        return json.dumps({"status": "running", "session_id": "proc-fast"})

    payload = module.start_production(context, terminal_runner=fast_terminal)

    assert payload["work_status"] == "artifact_ready"
    assert payload["media"] == [f"MEDIA:{final}"]
    assert module.ProductionJobStore(context.project_dir).load()["status"] == "artifact_ready"


def test_ready_job_returns_only_existing_project_mp4_without_relaunch(tmp_path) -> None:
    context = _context(tmp_path)
    module = _production()
    ProductionJobStore = module.ProductionJobStore
    start_production = module.start_production
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"video")
    ProductionJobStore(context.project_dir).transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="artifact_ready",
        selected_mp4=str(final),
    )

    payload = start_production(
        context,
        terminal_runner=lambda **_: pytest.fail("production relaunched"),
    )

    assert payload["already_complete"] is True
    assert payload["media"] == [f"MEDIA:{final.resolve()}"]


def test_status_rejects_selected_mp4_outside_current_project(tmp_path) -> None:
    context = _context(tmp_path)
    module = _production()
    ProductionJobStore = module.ProductionJobStore
    production_status = module.production_status
    outside = tmp_path / "other" / "final.mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"video")
    ProductionJobStore(context.project_dir).transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="artifact_ready",
        selected_mp4=str(outside),
    )

    payload = production_status(context)

    assert payload["success"] is False
    assert payload["error_type"] == "production_artifact_invalid"
    assert "media" not in payload


def test_failed_job_can_be_relaunched_without_losing_attempt_count(tmp_path) -> None:
    context = _context(tmp_path)
    module = _production()
    ProductionJobStore = module.ProductionJobStore
    start_production = module.start_production
    jobs = ProductionJobStore(context.project_dir)
    jobs.transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="failed",
        error_type="render_failed",
    )

    payload = start_production(
        context,
        terminal_runner=lambda **_: json.dumps(
            {"status": "running", "session_id": "proc-2"}
        ),
    )

    assert payload["work_status"] == "running"
    assert payload["attempts"] == 2
