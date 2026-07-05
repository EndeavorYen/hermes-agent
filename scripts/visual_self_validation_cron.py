from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cron.jobs import create_job
from cron.jobs import list_jobs
from cron.jobs import parse_schedule
from cron.jobs import update_job
from hermes_constants import get_hermes_home


JOB_NAME = "Visual Agent Mode Self-Validation"
SCRIPT_NAME = "visual_self_validation_cron.sh"


def ensure_visual_self_validation_cron(
    *,
    repo_root: str | Path | None = None,
    schedule: str = "every 6h",
    live_mode: str = "auto",
    enable_live_provider: bool = True,
    enable_live_slack_upload: bool = True,
    case_timeout_seconds: int | float = 240,
    min_live_interval_hours: int = 6,
    deliver: str = "local",
) -> dict[str, Any]:
    repo = Path(repo_root) if repo_root is not None else _REPO_ROOT
    repo = repo.expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        return {
            "success": False,
            "error_type": "invalid_repo_root",
            "error": f"repo_root does not exist or is not a directory: {repo}",
        }

    hermes_home = get_hermes_home()
    scripts_dir = hermes_home / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_path = scripts_dir / SCRIPT_NAME
    script_body = _script_body(
        repo_root=repo,
        live_mode=live_mode,
        enable_live_provider=enable_live_provider,
        enable_live_slack_upload=enable_live_slack_upload,
        case_timeout_seconds=case_timeout_seconds,
        min_live_interval_hours=min_live_interval_hours,
    )
    script_action = _write_executable_if_changed(script_path, script_body)

    existing = _find_job_by_name(JOB_NAME)
    updates = {
        "schedule": schedule,
        "script": SCRIPT_NAME,
        "no_agent": True,
        "deliver": deliver,
        "workdir": str(repo),
        "name": JOB_NAME,
        "prompt": "",
    }
    if existing is None:
        job = create_job(
            prompt="",
            schedule=schedule,
            name=JOB_NAME,
            deliver=deliver,
            script=SCRIPT_NAME,
            no_agent=True,
            workdir=str(repo),
        )
        action = "created"
    else:
        job = update_job(str(existing["id"]), updates)
        action = "updated" if _job_needs_update(existing, updates) or script_action == "updated" else "unchanged"

    return {
        "success": True,
        "action": action,
        "job_id": job.get("id") if isinstance(job, dict) else None,
        "job_name": JOB_NAME,
        "schedule": schedule,
        "script": {
            "path": str(script_path),
            "relative_path": SCRIPT_NAME,
            "action": script_action,
        },
        "live_mode": live_mode,
        "enable_live_provider": enable_live_provider,
        "enable_live_slack_upload": enable_live_slack_upload,
        "case_timeout_seconds": case_timeout_seconds,
        "min_live_interval_hours": min_live_interval_hours,
        "self_review": {
            "cron_safe": True,
            "privacy_safe": True,
            "reduces_human_intervention": True,
            "live_provider_enabled": enable_live_provider,
            "live_slack_upload_enabled": enable_live_slack_upload,
            "prompt_mutation": "disabled",
            "provider_health_separate_from_preference": True,
        },
    }


def _script_body(
    *,
    repo_root: Path,
    live_mode: str,
    enable_live_provider: bool,
    enable_live_slack_upload: bool,
    case_timeout_seconds: int | float,
    min_live_interval_hours: int,
) -> str:
    live_value = "1" if enable_live_provider else "0"
    live_slack_upload_value = "1" if enable_live_slack_upload else "0"
    python_bin = repo_root / "venv" / "bin" / "python"
    python_ref = str(python_bin if python_bin.exists() else Path(sys.executable))
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"export HERMES_VISUAL_LIVE_E2E={live_value}",
            f"export HERMES_VISUAL_SLACK_LIVE_UPLOAD={live_slack_upload_value}",
            f"cd {json.dumps(str(repo_root))}",
            (
                f"exec {json.dumps(python_ref)} "
                "scripts/visual_scheduled_self_validation.py "
                f"--live-mode {live_mode} "
                f"--min-live-interval-hours {int(min_live_interval_hours)} "
                f"--case-timeout-seconds {case_timeout_seconds:g} "
                "--json --allow-failures"
            ),
            "",
        ]
    )


def _write_executable_if_changed(path: Path, content: str) -> str:
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old != content:
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return "created" if old is None else "updated"
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return "unchanged"


def _find_job_by_name(name: str) -> dict[str, Any] | None:
    matches = [job for job in list_jobs(include_disabled=True) if str(job.get("name") or "") == name]
    return matches[0] if matches else None


def _job_needs_update(job: dict[str, Any], updates: dict[str, Any]) -> bool:
    schedule_display = _schedule_display(str(updates["schedule"]))
    return (
        job.get("schedule_display") != schedule_display
        or job.get("script") != updates["script"]
        or job.get("no_agent") is not True
        or job.get("deliver") != updates["deliver"]
        or job.get("workdir") != updates["workdir"]
        or job.get("prompt") != updates["prompt"]
    )


def _schedule_display(schedule: str) -> str:
    try:
        parsed = parse_schedule(schedule)
    except Exception:
        return schedule
    return str(parsed.get("display") or schedule)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or update the visual self-validation cron job.")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--schedule", default="every 6h")
    parser.add_argument("--live-mode", choices=["off", "auto", "on"], default="auto")
    parser.add_argument("--disable-live-provider", action="store_true")
    parser.add_argument("--disable-live-slack-upload", action="store_true")
    parser.add_argument("--case-timeout-seconds", type=float, default=240)
    parser.add_argument("--min-live-interval-hours", type=int, default=6)
    parser.add_argument("--deliver", default="local")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = ensure_visual_self_validation_cron(
        repo_root=args.repo_root,
        schedule=args.schedule,
        live_mode=args.live_mode,
        enable_live_provider=not args.disable_live_provider,
        enable_live_slack_upload=not args.disable_live_slack_upload,
        case_timeout_seconds=args.case_timeout_seconds,
        min_live_interval_hours=args.min_live_interval_hours,
        deliver=args.deliver,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        status = "installed" if report.get("success") else "failed"
        print(f"visual self-validation cron {status}: {report.get('action') or report.get('error')}")
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
