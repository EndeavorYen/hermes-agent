from __future__ import annotations

import importlib.util
import importlib
import hashlib
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


def _write_final_speech_qc(context, final) -> None:
    manifest = context.project_dir / "manifests" / "narration_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "voice_chunk_count": 1,
                "outputs": [
                    {
                        "spoken_text": "故事開始",
                        "segments": [
                            {
                                "voice_chunks": [
                                    {
                                        "voice_chunk_id": "U01__C01",
                                        "spoken_text": "故事開始",
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = context.project_dir / "qc" / "final_speech_qc_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "schema": "story_video_final_speech_qc_v1",
                "run_id": context.run_id,
                "status": "PASS",
                "method": "final_mp4_demux_qwen_asr_v1",
                "video_sha256": hashlib.sha256(final.read_bytes()).hexdigest(),
                "narration_manifest_sha256": hashlib.sha256(
                    manifest.read_bytes()
                ).hexdigest(),
                "voice_chunk_count": 1,
                "voice_chunk_ids": ["U01__C01"],
                "expected_transcript": "故事開始",
                "asr_transcript": "故事開始",
                "transcript_similarity": 1.0,
            }
        ),
        encoding="utf-8",
    )


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
        _write_final_speech_qc(context, final)
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


def test_artifact_ready_job_cannot_regress_to_running(tmp_path) -> None:
    context = _context(tmp_path)
    store = _production().ProductionJobStore(context.project_dir)
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"video")
    _write_final_speech_qc(context, final)
    store.transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="artifact_ready",
        selected_mp4=str(final),
    )

    payload = store.transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="running",
        process_session_id="proc-late-launcher",
    )

    assert payload["status"] == "artifact_ready"
    assert payload["selected_mp4"] == str(final)
    assert store.load()["status"] == "artifact_ready"


def test_ready_job_returns_only_existing_project_mp4_without_relaunch(tmp_path) -> None:
    context = _context(tmp_path)
    module = _production()
    ProductionJobStore = module.ProductionJobStore
    start_production = module.start_production
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"video")
    _write_final_speech_qc(context, final)
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


def test_legacy_ready_job_without_final_speech_qc_is_relaunched(tmp_path) -> None:
    context = _context(tmp_path)
    module = _production()
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"legacy-video")
    module.ProductionJobStore(context.project_dir).transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="artifact_ready",
        selected_mp4=str(final),
    )
    calls = []

    payload = module.start_production(
        context,
        terminal_runner=lambda **kwargs: calls.append(kwargs)
        or json.dumps({"status": "running", "session_id": "proc-revalidate"}),
    )

    assert payload["work_status"] == "running"
    assert payload["attempts"] == 2
    assert len(calls) == 1


@pytest.mark.parametrize("legacy_status", ["artifact_ready", "delivered"])
def test_legacy_complete_job_runs_revalidation_only_through_launcher(
    tmp_path, legacy_status
) -> None:
    from plugins.story_video.production_runner import run_production

    context = _context(tmp_path)
    state_store = StoryVideoStateStore(tmp_path)
    context = state_store.update(context, phase="voice")
    context = state_store.update(context, phase="render")
    context = state_store.update(context, phase="complete", status="complete")
    module = _production()
    final = context.project_dir / "video" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"legacy-speech-video")
    jobs = module.ProductionJobStore(context.project_dir)
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
    rendered = []

    def synchronous_terminal(**_kwargs):
        run_production(
            context.run_id,
            context.project_dir,
            store=state_store,
            renderer=lambda _context: rendered.append(True),
            delivery_speech_validator=lambda _context, video: {
                "success": True,
                "qc_report": "qc/final_speech_qc_report.json",
                "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            },
        )
        return json.dumps({"status": "running", "session_id": "proc-revalidate"})

    payload = module.start_production(context, terminal_runner=synchronous_terminal)

    assert payload["work_status"] == "artifact_ready"
    assert payload["selected_mp4"] == str(final.resolve())
    assert rendered == []


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
