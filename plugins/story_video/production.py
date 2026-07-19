from __future__ import annotations

import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .state import StoryVideoRunContext


PRODUCTION_JOB_SCHEMA = "story_video_production_job_v1"
PRODUCTION_JOB_STATUSES = {
    "queued",
    "running",
    "artifact_ready",
    "delivered",
    "failed",
    "stopped",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductionJobStore:
    def __init__(self, project_dir: str | Path) -> None:
        self.project_dir = Path(project_dir).expanduser().resolve()
        self.path = self.project_dir / "manifests" / "production_job.json"

    def load(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("schema") != PRODUCTION_JOB_SCHEMA:
            return None
        return payload

    def transition(
        self,
        *,
        run_id: str,
        visual_mode: str,
        status: str,
        **evidence: Any,
    ) -> dict[str, Any]:
        if status not in PRODUCTION_JOB_STATUSES:
            raise ValueError(f"Unknown production job status: {status}")
        current = self.load() or {}
        current_run_id = str(current.get("run_id") or "")
        if current_run_id and current_run_id != run_id:
            raise ValueError("Production job belongs to another story-video run")
        now = _utc_now()
        attempts = int(evidence.pop("attempts", current.get("attempts") or 1))
        payload = {
            **current,
            "schema": PRODUCTION_JOB_SCHEMA,
            "run_id": run_id,
            "project_dir": str(self.project_dir),
            "visual_mode": visual_mode,
            "status": status,
            "attempts": attempts,
            "created_at": str(current.get("created_at") or now),
            "updated_at": now,
            **evidence,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return payload


def _selected_mp4(
    context: StoryVideoRunContext,
    payload: dict[str, Any],
) -> Path | None:
    raw = str(payload.get("selected_mp4") or "").strip()
    if not raw:
        return None
    selected = Path(raw).expanduser()
    if not selected.is_absolute():
        selected = context.project_dir / selected
    try:
        project = context.project_dir.expanduser().resolve()
        selected = selected.resolve()
        selected.relative_to(project)
    except (OSError, RuntimeError, ValueError):
        return None
    if selected.suffix.casefold() != ".mp4" or not selected.is_file():
        return None
    return selected


def production_status(context: StoryVideoRunContext) -> dict[str, Any]:
    payload = ProductionJobStore(context.project_dir).load()
    if payload is None:
        return {
            "success": True,
            "work_status": "not_started",
            "run_id": context.run_id,
            "project_dir": str(context.project_dir),
            "visual_mode": context.visual_mode,
        }
    result = {
        **payload,
        "success": payload.get("status") not in {"failed", "stopped"},
        "work_status": str(payload.get("status") or "not_started"),
    }
    if payload.get("status") in {"artifact_ready", "delivered"}:
        selected = _selected_mp4(context, payload)
        if selected is None:
            result.update(
                {
                    "success": False,
                    "error_type": "production_artifact_invalid",
                    "error": "Selected production MP4 is missing or outside the active project.",
                }
            )
            result.pop("media", None)
        else:
            result["selected_mp4"] = str(selected)
            result["media"] = [f"MEDIA:{selected}"]
    return result


def start_production(
    context: StoryVideoRunContext,
    *,
    terminal_runner: Callable[..., str] | None = None,
) -> dict[str, Any]:
    jobs = ProductionJobStore(context.project_dir)
    current = jobs.load()
    if current is not None and current.get("status") in {"artifact_ready", "delivered"}:
        result = production_status(context)
        result["already_complete"] = result.get("success") is True
        return result
    if current is not None and current.get("status") == "running":
        return {
            **current,
            "success": True,
            "work_status": "running",
            "already_running": True,
        }

    attempts = int((current or {}).get("attempts") or 0) + 1
    jobs.transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="queued",
        attempts=attempts,
        phase=context.phase,
        error_type="",
        error="",
    )
    argv = [
        sys.executable,
        "-m",
        "plugins.story_video.production_runner",
        "--run-id",
        context.run_id,
        "--project-dir",
        str(context.project_dir.expanduser().resolve()),
    ]
    command = shlex.join(argv)
    if terminal_runner is None:
        from tools.terminal_tool import terminal_tool

        terminal_runner = terminal_tool
    raw_result = terminal_runner(
        command=command,
        background=True,
        notify_on_complete=True,
        workdir=str(context.project_dir.expanduser().resolve()),
        session_id=context.session_ids[-1] if context.session_ids else None,
    )
    try:
        launched = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
    except json.JSONDecodeError:
        launched = None
    if not isinstance(launched, dict) or launched.get("status") == "error":
        failed = jobs.transition(
            run_id=context.run_id,
            visual_mode=context.visual_mode,
            status="failed",
            attempts=attempts,
            phase=context.phase,
            error_type="production_launch_failed",
            error=str((launched or {}).get("error") or raw_result),
            command=command,
        )
        return {**failed, "success": False, "work_status": "failed"}
    latest = jobs.load() or {}
    if latest.get("status") in {"artifact_ready", "delivered", "failed", "stopped"}:
        return production_status(context)
    process_session_id = str(
        launched.get("session_id") or launched.get("process_session_id") or ""
    ).strip()
    running = jobs.transition(
        run_id=context.run_id,
        visual_mode=context.visual_mode,
        status="running",
        attempts=attempts,
        phase=context.phase,
        process_session_id=process_session_id,
        command=command,
    )
    return {
        **running,
        "success": True,
        "work_status": "running",
    }
