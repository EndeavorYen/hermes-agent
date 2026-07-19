"""Deterministic background worker for one persisted story-video run."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .production import ProductionJobStore
from .state import StoryVideoStateStore


DEFAULT_RENDERER = (
    Path.home()
    / ".hermes"
    / "skills"
    / "creative"
    / "story-video-production-pipeline"
    / "scripts"
    / "render_story_video.py"
)


def _error_payload(
    jobs: ProductionJobStore,
    context: Any,
    *,
    error_type: str,
    error: str,
) -> dict[str, Any]:
    failed = jobs.transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="failed",
        phase=context.phase,
        error_type=error_type,
        error=str(error)[-2000:],
    )
    return {**failed, "success": False, "work_status": "failed"}


def _default_voice_runner(context: Any, store: StoryVideoStateStore) -> dict[str, Any]:
    from dataclasses import asdict

    from .tools import validate_phase
    from .voice_executor import StoryVideoVoiceExecutor

    def cancelled() -> bool:
        latest = store.for_run(
            run_id=context.run_id,
            project_dir=context.project_dir,
        )
        return latest is None or latest.status == "stopped"

    return asdict(
        StoryVideoVoiceExecutor(phase_validator=validate_phase).run(
            context,
            cancel_check=cancelled,
        )
    )


def _default_render_preparer(context: Any) -> dict[str, Any]:
    if context.visual_mode == "black_subtitle":
        from .render_modes import prepare_black_subtitle_render

        return prepare_black_subtitle_render(context)
    from .visual_judge import _prepare_render

    return _prepare_render(context)


def _default_renderer(context: Any) -> dict[str, Any]:
    if not DEFAULT_RENDERER.is_file():
        return {
            "success": False,
            "error_type": "render_runtime_missing",
            "error": f"Missing local story-video renderer: {DEFAULT_RENDERER}",
        }
    process = subprocess.run(
        [sys.executable, str(DEFAULT_RENDERER), str(context.project_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        return {
            "success": False,
            "error_type": "render_failed",
            "error": (process.stderr or process.stdout or "renderer failed")[-2000:],
        }
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        return {
            "success": False,
            "error_type": "render_failed",
            "error": "renderer returned invalid JSON",
        }
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return {
            "success": False,
            "error_type": "render_failed",
            "error": str(payload),
        }
    if context.visual_mode == "black_subtitle":
        from .render_modes import finalize_black_subtitle_render

        return finalize_black_subtitle_render(context, payload)
    return payload


def _resolve_selected_mp4(context: Any, result: dict[str, Any]) -> Path | None:
    raw = str(result.get("selected_mp4") or result.get("video") or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = context.project_dir / candidate
    try:
        project = context.project_dir.expanduser().resolve()
        candidate = candidate.resolve()
        candidate.relative_to(project)
    except (OSError, RuntimeError, ValueError):
        return None
    if candidate.suffix.casefold() != ".mp4" or not candidate.is_file():
        return None
    return candidate


def run_production(
    run_id: str,
    project_dir: str | Path,
    *,
    store: StoryVideoStateStore | None = None,
    voice_runner: Any = None,
    voice_validator: Any = None,
    render_preparer: Any = None,
    renderer: Any = None,
    render_validator: Any = None,
    delivery_speech_validator: Any = None,
) -> dict[str, Any]:
    project = Path(project_dir).expanduser().resolve()
    state_store = store or StoryVideoStateStore(project.parent)
    context = state_store.for_run(run_id=run_id, project_dir=project)
    if context is None:
        return {
            "success": False,
            "work_status": "failed",
            "error_type": "story_video_context_missing",
            "error": "No canonical story-video run context for production job.",
        }
    jobs = ProductionJobStore(context.project_dir)
    current_job = jobs.load() or {}
    jobs.transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="running",
        attempts=int(current_job.get("attempts") or 1),
        phase=context.phase,
        error_type="",
        error="",
    )

    if context.status == "stopped":
        stopped = jobs.transition(
            run_id=context.run_id,
            visual_mode=context.visual_mode,
            status="stopped",
            phase=context.phase,
            error_type="stopped",
            error="Production was stopped by the operator.",
        )
        return {**stopped, "success": False, "work_status": "stopped"}

    if (
        context.phase == "complete"
        and str(current_job.get("error_type") or "") == "final_speech_qc_stale"
    ):
        selected = _resolve_selected_mp4(context, current_job)
        if selected is None:
            return _error_payload(
                jobs,
                context,
                error_type="production_artifact_invalid",
                error="stale production job has no current-project MP4 to revalidate",
            )
        if delivery_speech_validator is None:
            from .delivery_speech import verify_final_video_speech

            delivery_speech_validator = verify_final_video_speech
        speech_result = delivery_speech_validator(context, selected)
        if (
            not isinstance(speech_result, dict)
            or speech_result.get("success") is not True
        ):
            return _error_payload(
                jobs,
                context,
                error_type="final_speech_qc_failed",
                error=str(
                    (speech_result or {}).get("error")
                    or "final MP4 did not pass speech-content QC"
                ),
            )
        ready = jobs.transition(
            run_id=context.run_id,
            visual_mode=context.visual_mode,
            status="artifact_ready",
            phase="complete",
            selected_mp4=str(selected),
            qc_report=str(current_job.get("qc_report") or ""),
            final_speech_qc_report=str(speech_result.get("qc_report") or ""),
            final_speech_video_sha256=str(
                speech_result.get("video_sha256") or ""
            ),
            error_type="",
            error="",
        )
        return {
            **ready,
            "success": True,
            "work_status": "artifact_ready",
            "media": [f"MEDIA:{selected}"],
        }

    if context.phase == "voice":
        voice_result = (
            voice_runner(context)
            if voice_runner is not None
            else _default_voice_runner(context, state_store)
        )
        work_status = (
            str(voice_result.get("work_status") or "")
            if isinstance(voice_result, dict)
            else str(getattr(voice_result, "work_status", ""))
        )
        if work_status != "complete":
            return _error_payload(
                jobs,
                context,
                error_type=str(
                    (voice_result.get("error_type") if isinstance(voice_result, dict) else "")
                    or "voice_generation_failed"
                ),
                error=str(
                    (voice_result.get("error") if isinstance(voice_result, dict) else "")
                    or "voice production did not complete"
                ),
            )
        if voice_validator is None:
            from .tools import _validate_voice

            voice_validator = _validate_voice
        proof = voice_validator(context)
        if not proof.ok:
            return _error_payload(
                jobs,
                context,
                error_type="voice_qc_failed",
                error="; ".join((*proof.missing, *proof.violations)),
            )
        context = state_store.update(context, phase="render", last_validated_phase="voice")

    if context.phase != "render":
        return _error_payload(
            jobs,
            context,
            error_type="production_phase_invalid",
            error=f"production can run only during voice or render, not {context.phase}",
        )

    if voice_validator is None:
        from .tools import _validate_voice

        voice_validator = _validate_voice
    voice_proof = voice_validator(context)
    if not voice_proof.ok:
        return _error_payload(
            jobs,
            context,
            error_type="voice_qc_failed",
            error="; ".join((*voice_proof.missing, *voice_proof.violations)),
        )

    try:
        (
            render_preparer(context)
            if render_preparer is not None
            else _default_render_preparer(context)
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error_payload(
            jobs,
            context,
            error_type="render_preparation_failed",
            error=str(exc),
        )
    render_result = renderer(context) if renderer is not None else _default_renderer(context)
    if not isinstance(render_result, dict) or render_result.get("success") is not True:
        return _error_payload(
            jobs,
            context,
            error_type=str(
                (render_result or {}).get("error_type") or "render_failed"
            ),
            error=str((render_result or {}).get("error") or "renderer failed"),
        )
    if render_validator is None:
        from .tools import validate_phase

        proof = validate_phase(context)
    else:
        proof = render_validator(context)
    if not proof.ok:
        return _error_payload(
            jobs,
            context,
            error_type="render_qc_failed",
            error="; ".join((*proof.missing, *proof.violations)),
        )
    selected = _resolve_selected_mp4(context, render_result)
    if selected is None:
        return _error_payload(
            jobs,
            context,
            error_type="production_artifact_invalid",
            error="renderer did not return a current-project MP4",
        )
    if delivery_speech_validator is None:
        from .delivery_speech import verify_final_video_speech

        delivery_speech_validator = verify_final_video_speech
    speech_result = delivery_speech_validator(context, selected)
    if not isinstance(speech_result, dict) or speech_result.get("success") is not True:
        return _error_payload(
            jobs,
            context,
            error_type="final_speech_qc_failed",
            error=str(
                (speech_result or {}).get("error")
                or "final MP4 did not pass speech-content QC"
            ),
        )
    context = state_store.update(
        context,
        phase="complete",
        last_validated_phase="render",
        status="complete",
    )
    ready = jobs.transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="artifact_ready",
        phase="complete",
        selected_mp4=str(selected),
        qc_report=str(render_result.get("qc_report") or ""),
        final_speech_qc_report=str(speech_result.get("qc_report") or ""),
        final_speech_video_sha256=str(speech_result.get("video_sha256") or ""),
        error_type="",
        error="",
    )
    return {
        **ready,
        "success": True,
        "work_status": "artifact_ready",
        "media": [f"MEDIA:{selected}"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic story-video production")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--project-dir", required=True)
    args = parser.parse_args()
    result = run_production(args.run_id, args.project_dir)
    marker = (
        "STORY_VIDEO_PRODUCTION_COMPLETE"
        if result.get("success") is True
        else "STORY_VIDEO_PRODUCTION_FAILED"
    )
    print(f"{marker} run_id={args.run_id}")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("success") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
