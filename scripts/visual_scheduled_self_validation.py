from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hermes_constants import get_hermes_home


DEFAULT_MIN_LIVE_INTERVAL_HOURS = 6


def build_visual_scheduled_self_validation_report(
    *,
    output_dir: str | Path | None = None,
    work_dir: str | Path | None = None,
    live_mode: str = "off",
    live_enabled: bool | None = None,
    min_live_interval_hours: int = DEFAULT_MIN_LIVE_INTERVAL_HOURS,
    case_timeout_seconds: float | int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = _normalise_now(now)
    output_dir = Path(output_dir) if output_dir is not None else get_hermes_home() / "visual" / "self_validation"
    _ = Path(work_dir) if work_dir is not None else output_dir / "work"
    live_policy = _live_policy(
        live_mode=live_mode,
        live_enabled=_live_enabled() if live_enabled is None else live_enabled,
        min_live_interval_hours=min_live_interval_hours,
    )
    summary = _fixture_summary()
    live_requested_without_runner = live_policy["decision"] == "run"
    failures = list(summary.pop("_failures"))
    if live_requested_without_runner:
        failures.append("live_visual_self_validation_runner_not_ported")
    success = not failures
    report = {
        "success": success,
        "run_id": _run_id(now),
        "generated_at": now.isoformat(),
        "mode": "fixture+live_requested" if live_requested_without_runner else "fixture",
        "failures": failures,
        "live_policy": live_policy,
        "summary": summary,
        "self_review": {
            "cron_safe": not live_requested_without_runner,
            "privacy_safe": True,
            "reduces_human_intervention": success,
            "live_e2e_requires_opt_in": live_mode != "on",
            "case_timeout_seconds": case_timeout_seconds,
        },
    }
    _write_report(output_dir, report)
    return report


def _fixture_summary() -> dict[str, Any]:
    failures: list[str] = []
    visual_agent_tool_registered = False
    visual_package_tool_registered = False
    visual_agent_in_image_toolset = False
    visual_package_in_image_toolset = False
    visual_agent_in_cli_toolset = False
    visual_package_in_cli_toolset = False
    visual_package_requirements_available = False
    planner_image_plus_video = False
    planner_image_first_video = False
    visual_agent_production_kernel = False
    prompt_disclosure_guard_active = False

    try:
        from agent.visual.agent_mode.planner import plan_visual_agent_request
        from agent.visual.prompt_disclosure import is_visual_prompt_disclosure_request
        from tools.registry import discover_builtin_tools
        from tools.registry import registry
        from tools.visual_package_tool import check_visual_package_requirements
        from toolsets import resolve_toolset

        discover_builtin_tools()
        visual_agent_tool_registered = registry.get_entry("visual_agent_generate") is not None
        visual_package_tool_registered = registry.get_entry("visual_package_generate") is not None
        image_gen_tools = set(resolve_toolset("image_gen"))
        cli_tools = set(resolve_toolset("hermes-cli"))
        visual_agent_in_image_toolset = "visual_agent_generate" in image_gen_tools
        visual_package_in_image_toolset = "visual_package_generate" in image_gen_tools
        visual_agent_in_cli_toolset = "visual_agent_generate" in cli_tools
        visual_package_in_cli_toolset = "visual_package_generate" in cli_tools

        image_plus_video = plan_visual_agent_request(
            "Generate an image and a 6 second video of a matte black fountain pen."
        )
        planner_image_plus_video = (
            image_plus_video.get("should_use_visual_package") is True
            and image_plus_video.get("arguments", {}).get("include_image") is True
            and image_plus_video.get("arguments", {}).get("include_video") is True
        )
        image_first_video = plan_visual_agent_request(
            "Generate a 6 second product video of a matte black fountain pen."
        )
        planner_image_first_video = (
            image_first_video.get("should_use_visual_package") is True
            and image_first_video.get("arguments", {}).get("include_image") is False
            and image_first_video.get("arguments", {}).get("include_video") is True
            and image_first_video.get("arguments", {}).get("candidate_budget") == 1
        )
        kernel_arguments = image_first_video.get("arguments", {})
        kernel_contract = kernel_arguments.get("visual_intent_contract", {})
        visual_agent_production_kernel = (
            kernel_arguments.get("visual_production_kernel") is True
            and kernel_arguments.get("max_generated_repairs") == 1
            and bool(kernel_arguments.get("visual_contract_hash"))
            and isinstance(kernel_contract, dict)
            and kernel_contract.get("schema") == "visual_intent_contract_v1"
        )
        prompt_disclosure_guard_active = (
            is_visual_prompt_disclosure_request("show me the prompt you used for the image") is True
            and is_visual_prompt_disclosure_request("generate an image of a fountain pen") is False
        )
        try:
            visual_package_requirements_available = bool(check_visual_package_requirements())
        except Exception:
            visual_package_requirements_available = False
    except Exception:
        failures.append("visual_self_validation_fixture_import_failed")

    checks = {
        "visual_agent_tool_registered": visual_agent_tool_registered,
        "visual_package_tool_registered": visual_package_tool_registered,
        "visual_agent_in_image_toolset": visual_agent_in_image_toolset,
        "visual_package_in_image_toolset": visual_package_in_image_toolset,
        "visual_agent_in_cli_toolset": visual_agent_in_cli_toolset,
        "visual_package_in_cli_toolset": visual_package_in_cli_toolset,
        "visual_agent_planner_image_plus_video": planner_image_plus_video,
        "visual_agent_planner_image_first_video": planner_image_first_video,
        "visual_agent_production_kernel": visual_agent_production_kernel,
        "prompt_disclosure_guard_active": prompt_disclosure_guard_active,
    }
    failures.extend(key for key, value in checks.items() if value is not True)
    return {
        **checks,
        "visual_package_requirements_available": visual_package_requirements_available,
        "scheduled_self_validation_entrypoint_ready": not failures,
        "privacy_safe": True,
        "_failures": failures,
    }


def _live_policy(
    *,
    live_mode: str,
    live_enabled: bool,
    min_live_interval_hours: int,
) -> dict[str, Any]:
    mode = str(live_mode or "off").strip().lower()
    if mode not in {"off", "auto", "on"}:
        mode = "off"
    if mode == "off":
        return {
            "mode": mode,
            "decision": "not_requested",
            "live_enabled": bool(live_enabled),
        }
    if mode == "auto" and not live_enabled:
        return {
            "mode": mode,
            "decision": "skip_not_enabled",
            "live_enabled": False,
        }
    return {
        "mode": mode,
        "decision": "run",
        "live_enabled": True,
        "min_live_interval_hours": min_live_interval_hours,
    }


def _live_enabled() -> bool:
    return str(os.environ.get("HERMES_VISUAL_LIVE_E2E") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _write_report(output_dir: Path, report: dict[str, Any]) -> None:
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    _write_json(runs_dir / f"{report['run_id']}.json", report)
    _write_json(output_dir / "latest.json", report)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _normalise_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _run_id(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run cron-safe visual self-validation.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--live-mode", choices=["off", "auto", "on"], default="off")
    parser.add_argument("--min-live-interval-hours", type=int, default=DEFAULT_MIN_LIVE_INTERVAL_HOURS)
    parser.add_argument("--case-timeout-seconds", type=float, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_scheduled_self_validation_report(
        output_dir=args.output_dir,
        work_dir=args.work_dir,
        live_mode=args.live_mode,
        min_live_interval_hours=args.min_live_interval_hours,
        case_timeout_seconds=args.case_timeout_seconds,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual scheduled self-validation {status} run_id={payload['run_id']}")
    if args.allow_failures:
        return 0
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
