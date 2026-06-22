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
from agent.visual.action_dedupe import dedupe_actions as _dedupe_actions
from agent.visual.live_quality_trends import build_live_quality_trend_report_from_dir
from scripts.visual_e2e_automation_report import build_visual_e2e_automation_report


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
    work_dir = Path(work_dir) if work_dir is not None else output_dir / "work"
    state = _read_json(output_dir / "state.json")
    live_policy = _live_policy(
        live_mode=live_mode,
        live_enabled=_live_enabled() if live_enabled is None else live_enabled,
        min_live_interval_hours=min_live_interval_hours,
        state=state,
        now=now,
    )
    include_live = live_policy["decision"] == "run"
    slack_live_upload_policy = _slack_live_upload_policy(live_policy)
    include_live_slack_upload = slack_live_upload_policy["decision"] == "run"
    automation_kwargs: dict[str, Any] = {
        "work_dir": work_dir,
        "include_live": include_live,
        "include_live_slack_upload": include_live_slack_upload,
    }
    if case_timeout_seconds is not None:
        automation_kwargs["case_timeout_seconds"] = case_timeout_seconds
    automation = build_visual_e2e_automation_report(**automation_kwargs)
    automation = _with_carried_live_quality_burn(
        automation=automation,
        live_policy=live_policy,
        state=state,
    )
    live_quality_trends = build_live_quality_trend_report_from_dir(_live_quality_burn_dir(output_dir))
    automation = _with_live_quality_trend_actions(
        automation=automation,
        live_quality_trends=live_quality_trends,
    )
    report = {
        "success": automation.get("success") is True,
        "run_id": _run_id(now),
        "generated_at": now.isoformat(),
        "mode": "fixture+live" if include_live else "fixture",
        "failures": list(automation.get("failures") or []),
        "live_policy": live_policy,
        "slack_live_upload_policy": slack_live_upload_policy,
        "live_quality_trends": live_quality_trends,
        "summary": _summary(automation, live_quality_trends=live_quality_trends),
        "automation": automation,
        "self_review": {
            "cron_safe": True,
            "privacy_safe": True,
            "reduces_human_intervention": True,
            "live_e2e_requires_opt_in": live_mode != "on",
        },
    }
    _write_report(output_dir, report)
    if include_live:
        _write_json(output_dir / "state.json", _next_state_after_live_run(state, automation=automation, now=now))
    return report


def _live_policy(
    *,
    live_mode: str,
    live_enabled: bool,
    min_live_interval_hours: int,
    state: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    mode = str(live_mode or "off").strip().lower()
    if mode not in {"off", "auto", "on"}:
        mode = "off"
    if mode == "off":
        return {"mode": mode, "decision": "not_requested", "live_enabled": live_enabled}
    if mode == "on":
        return {"mode": mode, "decision": "run", "live_enabled": True}
    if not live_enabled:
        return {"mode": mode, "decision": "skip_not_enabled", "live_enabled": False}

    last_live_run_at = _parse_datetime(state.get("last_live_run_at"))
    if last_live_run_at is None:
        return {
            "mode": mode,
            "decision": "run",
            "live_enabled": True,
            "min_live_interval_hours": min_live_interval_hours,
            "last_live_run_at": None,
        }
    elapsed_hours = (now - last_live_run_at).total_seconds() / 3600
    if elapsed_hours < max(0, min_live_interval_hours):
        return {
            "mode": mode,
            "decision": "skip_interval",
            "live_enabled": True,
            "min_live_interval_hours": min_live_interval_hours,
            "last_live_run_at": last_live_run_at.isoformat(),
            "elapsed_hours": round(elapsed_hours, 4),
        }
    return {
        "mode": mode,
        "decision": "run",
        "live_enabled": True,
        "min_live_interval_hours": min_live_interval_hours,
        "last_live_run_at": last_live_run_at.isoformat(),
        "elapsed_hours": round(elapsed_hours, 4),
    }


def _summary(automation: dict[str, Any], live_quality_trends: dict[str, Any] | None = None) -> dict[str, Any]:
    live_quality_trends = live_quality_trends if isinstance(live_quality_trends, dict) else {}
    feedback_loop = automation.get("feedback_loop") if isinstance(automation.get("feedback_loop"), dict) else {}
    closed_loop_regression = (
        automation.get("closed_loop_regression")
        if isinstance(automation.get("closed_loop_regression"), dict)
        else {}
    )
    self_improvement = (
        automation.get("self_improvement")
        if isinstance(automation.get("self_improvement"), dict)
        else {}
    )
    live_e2e = automation.get("live_e2e") if isinstance(automation.get("live_e2e"), dict) else {}
    live_evidence = live_e2e.get("evidence") if isinstance(live_e2e.get("evidence"), dict) else {}
    quality_gate = live_evidence.get("quality_gate") if isinstance(live_evidence.get("quality_gate"), dict) else {}
    slack_delivery = automation.get("slack_delivery") if isinstance(automation.get("slack_delivery"), dict) else {}
    delivery = slack_delivery.get("delivery") if isinstance(slack_delivery.get("delivery"), dict) else {}
    live_slack_delivery = (
        automation.get("live_slack_delivery")
        if isinstance(automation.get("live_slack_delivery"), dict)
        else {}
    )
    live_slack_delivery_record = (
        live_slack_delivery.get("delivery")
        if isinstance(live_slack_delivery.get("delivery"), dict)
        else {}
    )
    live_slack_missing_native_uploads = _list(
        live_slack_delivery_record.get("missing_uploaded_artifact_ids")
    )
    live_slack_unexpected_native_uploads = _list(
        live_slack_delivery_record.get("unexpected_uploaded_artifact_ids")
    )
    fixture_quality_suite = (
        automation.get("fixture_quality_suite")
        if isinstance(automation.get("fixture_quality_suite"), dict)
        else {}
    )
    live_quality_suite = (
        automation.get("live_quality_suite")
        if isinstance(automation.get("live_quality_suite"), dict)
        else {}
    )
    live_quality_burn = (
        automation.get("live_quality_burn")
        if isinstance(automation.get("live_quality_burn"), dict)
        else {}
    )
    live_quality_burn_summary = (
        live_quality_burn.get("summary")
        if isinstance(live_quality_burn.get("summary"), dict)
        else {}
    )
    live_quality_burn_preference_failures = _list(
        live_quality_burn_summary.get("preference_dimension_failures")
    )
    fixture_quality_recovery = (
        fixture_quality_suite.get("recovery_summary")
        if isinstance(fixture_quality_suite.get("recovery_summary"), dict)
        else {}
    )
    fixture_quality_repair = (
        fixture_quality_suite.get("quality_repair_summary")
        if isinstance(fixture_quality_suite.get("quality_repair_summary"), dict)
        else {}
    )
    live_quality_recovery = (
        live_quality_suite.get("recovery_summary")
        if isinstance(live_quality_suite.get("recovery_summary"), dict)
        else {}
    )
    live_quality_repair = (
        live_quality_suite.get("quality_repair_summary")
        if isinstance(live_quality_suite.get("quality_repair_summary"), dict)
        else {}
    )
    fixture_video_repair = _modality_summary(fixture_quality_repair, "video")
    live_video_repair = _modality_summary(live_quality_repair, "video")
    health = automation.get("health") if isinstance(automation.get("health"), dict) else {}
    self_review = health.get("self_review") if isinstance(health.get("self_review"), dict) else {}
    feedback_action_types = _action_types(
        feedback_loop.get("next_actions"),
        self_improvement.get("next_actions"),
        live_quality_burn.get("next_actions"),
        live_quality_trends.get("next_actions"),
    )
    slack_sent_count = _int(delivery.get("sent_count"))
    slack_deliverable_count = _int(delivery.get("deliverable_count"))
    slack_duplicate_delivery_count = _int(delivery.get("duplicate_delivery_count"))
    slack_unexpected_delivery_count = len(delivery.get("unexpected_delivery_artifact_ids") or [])
    scheduled_validation_reduces_human_intervention = (
        automation.get("success") is True
        and feedback_action_types != []
        and slack_sent_count == slack_deliverable_count
        and slack_duplicate_delivery_count == 0
        and slack_unexpected_delivery_count == 0
    )
    return {
        "feedback_action_types": feedback_action_types,
        "live_quality_gate_success": quality_gate.get("success"),
        "live_quality_gate_min_score": quality_gate.get("min_score"),
        "slack_sent_count": slack_sent_count,
        "slack_deliverable_count": slack_deliverable_count,
        "slack_duplicate_delivery_count": slack_duplicate_delivery_count,
        "slack_unexpected_delivery_count": slack_unexpected_delivery_count,
        "scheduled_self_validation_reduces_human_intervention": scheduled_validation_reduces_human_intervention,
        "autonomous_rollout_reduces_human_intervention": self_review.get("reduces_human_intervention") is True,
        "closed_loop_regression_success": closed_loop_regression.get("success")
        if "success" in closed_loop_regression
        else None,
        "closed_loop_regression_case_count": _int(closed_loop_regression.get("case_count")),
        "closed_loop_regression_failure_count": _int(closed_loop_regression.get("failure_count")),
        "fixture_quality_suite_success": fixture_quality_suite.get("success")
        if "success" in fixture_quality_suite
        else None,
        "fixture_quality_suite_case_count": _int(fixture_quality_suite.get("case_count")),
        "fixture_quality_suite_failure_count": len(fixture_quality_suite.get("failures") or []),
        "fixture_quality_suite_negotiation_success_case_count": _int(
            fixture_quality_recovery.get("negotiation_success_case_count")
        ),
        "fixture_quality_suite_content_moderation_recovered_case_count": _int(
            fixture_quality_recovery.get("content_moderation_recovered_case_count")
        ),
        "fixture_quality_repair_attempt_count": _int(fixture_quality_repair.get("attempt_count")),
        "fixture_quality_repair_success_count": _int(fixture_quality_repair.get("success_count")),
        "fixture_quality_repair_selected_count": _int(fixture_quality_repair.get("selected_repair_count")),
        "fixture_video_quality_repair_success_count": _int(fixture_video_repair.get("success_count")),
        "scheduled_self_validation_video_repair_covered": _int(fixture_video_repair.get("success_count")) > 0,
        "live_quality_suite_success": live_quality_suite.get("success")
        if "success" in live_quality_suite
        else None,
        "live_quality_suite_case_count": _int(live_quality_suite.get("case_count")),
        "live_quality_suite_failure_count": len(live_quality_suite.get("failures") or []),
        "live_quality_suite_negotiation_success_case_count": _int(
            live_quality_recovery.get("negotiation_success_case_count")
        ),
        "live_quality_suite_content_moderation_recovered_case_count": _int(
            live_quality_recovery.get("content_moderation_recovered_case_count")
        ),
        "live_quality_burn_success": live_quality_burn.get("success")
        if "success" in live_quality_burn
        else None,
        "live_quality_burn_case_count": _int(live_quality_burn_summary.get("case_count")),
        "live_quality_burn_min_score": live_quality_burn_summary.get("min_quality_score"),
        "live_quality_burn_action_types": _action_types(live_quality_burn.get("next_actions")),
        "live_quality_burn_image_first_video_source_case_count": _int(
            live_quality_burn_summary.get("image_first_video_source_case_count")
        ),
        "live_quality_burn_image_first_video_source_covered_count": _int(
            live_quality_burn_summary.get("image_first_video_source_covered_count")
        ),
        "live_quality_burn_image_first_video_source_failure_count": _int(
            live_quality_burn_summary.get("image_first_video_source_failure_count")
        ),
        "live_quality_burn_image_first_video_source_failure_case_ids": _list(
            live_quality_burn_summary.get("image_first_video_source_failure_case_ids")
        ),
        "live_quality_burn_image_first_video_source_covered": _image_first_video_source_covered(
            live_quality_burn_summary
        ),
        "live_quality_burn_preference_dimension_failure_count": _int(
            live_quality_burn_summary.get("preference_dimension_failure_count")
        ),
        "live_quality_burn_preference_dimensions": _preference_dimensions(
            live_quality_burn_preference_failures
        ),
        "live_quality_burn_core_quality_contract_case_count": _int(
            live_quality_burn_summary.get("core_quality_contract_case_count")
        ),
        "live_quality_burn_core_quality_coverage_ready": live_quality_burn_summary.get(
            "core_quality_coverage_ready"
        )
        if "core_quality_coverage_ready" in live_quality_burn_summary
        else None,
        "live_quality_burn_core_quality_dimensions": _list(
            live_quality_burn_summary.get("core_quality_dimensions")
        ),
        "live_quality_burn_core_quality_dimensions_missing": _list(
            live_quality_burn_summary.get("core_quality_dimensions_missing")
        ),
        "live_quality_burn_quality_focus_outcome_count": _int(
            live_quality_burn_summary.get("quality_focus_outcome_count")
        ),
        "live_quality_burn_quality_focus_success_count": _int(
            live_quality_burn_summary.get("quality_focus_success_count")
        ),
        "live_quality_burn_quality_focus_failure_count": _int(
            live_quality_burn_summary.get("quality_focus_failure_count")
        ),
        "live_quality_burn_quality_focus_successes": _list(
            live_quality_burn_summary.get("quality_focus_successes")
        ),
        "live_quality_burn_quality_focus_failures": _list(
            live_quality_burn_summary.get("quality_focus_failures")
        ),
        "live_quality_burn_quality_focus_failed_case_ids": _list(
            live_quality_burn_summary.get("quality_focus_failed_case_ids")
        ),
        "live_quality_trend_run_count": _int(live_quality_trends.get("run_count")),
        "live_quality_trend_degradations": _list(live_quality_trends.get("degradations")),
        "live_quality_trend_action_types": _action_types(live_quality_trends.get("next_actions")),
        "live_quality_repair_attempt_count": _int(live_quality_repair.get("attempt_count")),
        "live_quality_repair_success_count": _int(live_quality_repair.get("success_count")),
        "live_video_quality_repair_success_count": _int(live_video_repair.get("success_count")),
        "live_slack_upload_success": live_slack_delivery.get("success")
        if "success" in live_slack_delivery
        else None,
        "live_slack_upload_sent_count": _int(live_slack_delivery_record.get("sent_count"))
        if live_slack_delivery_record
        else None,
        "live_slack_upload_uploaded_image_file_count": _int(
            live_slack_delivery_record.get("uploaded_image_file_count")
        )
        if live_slack_delivery_record
        else None,
        "live_slack_upload_uploaded_video_file_count": _int(
            live_slack_delivery_record.get("uploaded_video_file_count")
        )
        if live_slack_delivery_record
        else None,
        "live_slack_upload_uploaded_remote_video_url_count": _int(
            live_slack_delivery_record.get("uploaded_remote_video_url_count")
        )
        if live_slack_delivery_record
        else None,
        "live_slack_upload_missing_native_upload_count": len(live_slack_missing_native_uploads)
        if live_slack_delivery_record
        else None,
        "live_slack_upload_unexpected_native_upload_count": len(live_slack_unexpected_native_uploads)
        if live_slack_delivery_record
        else None,
        "live_slack_upload_native_delivery_covered": (
            live_slack_delivery.get("success") is True
            and _int(live_slack_delivery_record.get("uploaded_video_file_count")) > 0
            and _int(live_slack_delivery_record.get("uploaded_remote_video_url_count")) == 0
            and len(live_slack_missing_native_uploads) == 0
            and len(live_slack_unexpected_native_uploads) == 0
        )
        if live_slack_delivery_record
        else None,
    }


def _live_quality_burn_dir(output_dir: Path) -> Path:
    if output_dir.name == "self_validation":
        return output_dir.parent / "live_quality_burn"
    return output_dir / "live_quality_burn"


def _modality_summary(summary: dict[str, Any], modality: str) -> dict[str, Any]:
    by_modality = summary.get("by_modality")
    if not isinstance(by_modality, dict):
        return {}
    value = by_modality.get(modality)
    return value if isinstance(value, dict) else {}


def _action_types(*action_lists: Any) -> list[str]:
    values: list[str] = []
    for actions in action_lists:
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict) or action.get("requires_human_feedback") is True:
                continue
            action_type = str(action.get("type") or "")
            if action_type and action_type not in values:
                values.append(action_type)
    return values


def _with_carried_live_quality_burn(
    *,
    automation: dict[str, Any],
    live_policy: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    if live_policy.get("decision") != "skip_interval":
        return automation
    carried = _carried_live_quality_burn(state)
    if not carried:
        return automation

    merged = dict(automation)
    merged["live_quality_burn"] = carried

    self_improvement = (
        dict(merged.get("self_improvement"))
        if isinstance(merged.get("self_improvement"), dict)
        else {}
    )
    self_improvement["next_actions"] = _dedupe_actions(
        _action_list(self_improvement.get("next_actions")) + _action_list(carried.get("next_actions"))
    )
    self_improvement["action_count"] = len(self_improvement["next_actions"])
    self_improvement["reduces_human_intervention"] = bool(self_improvement["next_actions"])
    self_improvement.setdefault("privacy_safe", True)
    merged["self_improvement"] = self_improvement
    return merged


def _with_live_quality_trend_actions(
    *,
    automation: dict[str, Any],
    live_quality_trends: dict[str, Any],
) -> dict[str, Any]:
    actions = _action_list(live_quality_trends.get("next_actions"))
    if not actions:
        return automation
    merged = dict(automation)
    self_improvement = (
        dict(merged.get("self_improvement"))
        if isinstance(merged.get("self_improvement"), dict)
        else {}
    )
    self_improvement["next_actions"] = _dedupe_actions(
        _action_list(self_improvement.get("next_actions")) + actions
    )
    self_improvement["action_count"] = len(self_improvement["next_actions"])
    self_improvement["reduces_human_intervention"] = bool(self_improvement["next_actions"])
    self_improvement.setdefault("privacy_safe", True)
    merged["self_improvement"] = self_improvement
    return merged


def _next_state_after_live_run(
    state: dict[str, Any],
    *,
    automation: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    next_state = dict(state)
    next_state["last_live_run_at"] = now.isoformat()
    live_quality_burn = _state_live_quality_burn(automation, now=now)
    if live_quality_burn:
        next_state["last_live_quality_burn"] = live_quality_burn
    return next_state


def _state_live_quality_burn(automation: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    live_quality_burn = automation.get("live_quality_burn")
    if not isinstance(live_quality_burn, dict):
        return {}
    actions = _action_list(live_quality_burn.get("next_actions"))
    if not actions:
        return {}
    return {
        "success": live_quality_burn.get("success"),
        "status": live_quality_burn.get("status"),
        "summary": live_quality_burn.get("summary") if isinstance(live_quality_burn.get("summary"), dict) else {},
        "next_actions": actions,
        "generated_at": now.isoformat(),
    }


def _carried_live_quality_burn(state: dict[str, Any]) -> dict[str, Any]:
    live_quality_burn = state.get("last_live_quality_burn")
    if not isinstance(live_quality_burn, dict):
        return {}
    actions = _action_list(live_quality_burn.get("next_actions"))
    if not actions:
        return {}
    carried = dict(live_quality_burn)
    carried["status"] = "carried_forward"
    carried["next_actions"] = actions
    return carried


def _action_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _write_report(output_dir: Path, report: dict[str, Any]) -> None:
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    _write_json(runs_dir / f"{report['run_id']}.json", report)
    _write_json(output_dir / "latest.json", report)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _live_enabled() -> bool:
    return str(os.environ.get("HERMES_VISUAL_LIVE_E2E") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _slack_live_upload_policy(live_policy: dict[str, Any]) -> dict[str, Any]:
    enabled = _live_slack_upload_enabled()
    target = _resolve_live_slack_target()
    if live_policy.get("decision") != "run":
        return {
            "decision": "not_requested",
            "enabled": enabled,
            "target": target,
        }
    if not enabled:
        return {
            "decision": "skip_not_enabled",
            "enabled": False,
            "target": target,
        }
    if not target:
        return {
            "decision": "skip_missing_target",
            "enabled": True,
            "target": None,
        }
    return {
        "decision": "run",
        "enabled": True,
        "target": target,
    }


def _live_slack_upload_enabled() -> bool:
    return str(os.environ.get("HERMES_VISUAL_SLACK_LIVE_UPLOAD") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _resolve_live_slack_target() -> str | None:
    try:
        from scripts.visual_slack_delivery_e2e import _resolve_target

        return _resolve_target(mode="live", target=None)
    except Exception:
        return None


def _normalise_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _normalise_now(parsed)


def _run_id(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _image_first_video_source_covered(summary: dict[str, Any]) -> bool | None:
    case_count = _int(summary.get("image_first_video_source_case_count"))
    if case_count <= 0:
        return None
    return (
        _int(summary.get("image_first_video_source_failure_count")) == 0
        and _int(summary.get("image_first_video_source_covered_count")) >= case_count
    )


def _preference_dimensions(failures: list[Any]) -> list[str]:
    dimensions: list[str] = []
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        dimension = str(failure.get("dimension") or "").strip()
        if dimension and dimension not in dimensions:
            dimensions.append(dimension)
    return dimensions


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
