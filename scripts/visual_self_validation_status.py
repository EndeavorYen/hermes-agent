from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hermes_constants import get_hermes_home


DEFAULT_STALE_AFTER_HOURS = 24


def default_latest_path() -> Path:
    return get_hermes_home() / "visual" / "self_validation" / "latest.json"


def build_visual_self_validation_status(
    *,
    latest_path: str | Path | None = None,
    now: datetime | None = None,
    stale_after_hours: float | int = DEFAULT_STALE_AFTER_HOURS,
) -> dict[str, Any]:
    path = Path(latest_path) if latest_path is not None else default_latest_path()
    payload = _read_json(path)
    now = _normalise_now(now)
    if not payload:
        return {
            "success": False,
            "health_status": "missing",
            "live_e2e_ran": False,
            "next_steps": ["run_visual_scheduled_self_validation"],
            "self_review": {
                "privacy_safe": True,
                "raw_report_exposed": False,
            },
        }

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    live_policy = _sanitise_live_policy(payload.get("live_policy"))
    slack_upload_policy = _sanitise_slack_upload_policy(payload.get("slack_live_upload_policy"))
    live_decision = str(live_policy.get("decision") or "")
    live_e2e_ran = live_decision == "run" and summary.get("live_quality_suite_success") is not None
    generated_at = _parse_datetime(payload.get("generated_at"))
    age_hours = _age_hours(now, generated_at)
    is_stale = age_hours is not None and age_hours > max(0, float(stale_after_hours))
    carried_live_evidence_current = _carried_live_evidence_current(
        live_decision=live_decision,
        summary=summary,
        is_stale=is_stale,
    )
    failures = _strings(payload.get("failures"))
    action_types = _action_types(summary, payload)
    trend_degradations = _strings(summary.get("live_quality_trend_degradations"))
    provider_failure_classes = _aggregate_counts(_collect_actions(payload), "provider_failure_classes")
    provider_error_codes = _aggregate_counts(_collect_actions(payload), "provider_error_codes")

    next_steps = _next_steps(
        report_success=payload.get("success") is True,
        failures=failures,
        live_e2e_ran=live_e2e_ran,
        carried_live_evidence_current=carried_live_evidence_current,
        live_decision=live_decision,
        is_stale=is_stale,
        summary=summary,
        trend_degradations=trend_degradations,
        slack_upload_policy=slack_upload_policy,
    )
    health_status = _health_status(
        report_success=payload.get("success") is True,
        next_steps=next_steps,
        live_e2e_ran=live_e2e_ran,
        carried_live_evidence_current=carried_live_evidence_current,
        failures=failures,
    )
    return {
        "success": health_status == "pass",
        "health_status": health_status,
        "run_id": payload.get("run_id"),
        "generated_at": payload.get("generated_at"),
        "age_hours": age_hours,
        "mode": payload.get("mode"),
        "failures": failures,
        "live_policy": live_policy,
        "slack_upload_policy": slack_upload_policy,
        "live_e2e_ran": live_e2e_ran,
        "live": {
            "quality_gate_success": summary.get("live_quality_gate_success"),
            "quality_gate_min_score": summary.get("live_quality_gate_min_score"),
            "suite_success": summary.get("live_quality_suite_success"),
            "suite_case_count": _optional_int(summary.get("live_quality_suite_case_count")),
            "suite_failure_count": _optional_int(summary.get("live_quality_suite_failure_count")),
            "burn_success": summary.get("live_quality_burn_success"),
            "burn_case_count": _optional_int(summary.get("live_quality_burn_case_count")),
            "burn_min_score": summary.get("live_quality_burn_min_score"),
            "image_first_video_source_covered": summary.get(
                "live_quality_burn_image_first_video_source_covered"
            ),
            "image_first_video_source_failure_count": _optional_int(
                summary.get("live_quality_burn_image_first_video_source_failure_count")
            ),
            "content_moderation_recovered_count": _optional_int(
                summary.get("live_quality_suite_content_moderation_recovered_case_count")
            ),
            "video_quality_repair_success_count": _optional_int(
                summary.get("live_video_quality_repair_success_count")
            ),
            "preference_dimensions": _strings(summary.get("live_quality_burn_preference_dimensions")),
            "provider_failure_classes": provider_failure_classes,
            "provider_error_codes": provider_error_codes,
            "carried_evidence_current": carried_live_evidence_current,
            "trend_degradations": trend_degradations,
        },
        "delivery": {
            "native_video_upload_covered": summary.get("live_slack_upload_native_delivery_covered"),
            "uploaded_video_file_count": _optional_int(
                summary.get("live_slack_upload_uploaded_video_file_count")
            ),
            "duplicate_delivery_count": _optional_int(summary.get("slack_duplicate_delivery_count")),
        },
        "self_improvement": {
            "action_types": action_types,
            "action_count": len(action_types),
            "requires_human_feedback": False,
        },
        "next_steps": next_steps,
        "self_review": {
            "privacy_safe": True,
            "raw_report_exposed": False,
            "reduces_human_intervention": bool(action_types) and health_status in {"pass", "warn"},
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sanitise_live_policy(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    allowed = {
        "mode",
        "decision",
        "live_enabled",
        "min_live_interval_hours",
        "last_live_run_at",
        "elapsed_hours",
    }
    return {key: source[key] for key in allowed if key in source}


def _sanitise_slack_upload_policy(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    allowed = {"decision", "enabled"}
    return {key: source[key] for key in allowed if key in source}


def _action_types(summary: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("live_quality_burn_action_types", "live_quality_trend_action_types", "feedback_action_types"):
        values.extend(_strings(summary.get(key)))
    for action in _collect_actions(payload):
        if action.get("requires_human_feedback") is True:
            continue
        action_type = str(action.get("type") or "").strip()
        if action_type:
            values.append(action_type)
    return _dedupe(values)


def _collect_actions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for container in (
        payload.get("self_improvement"),
        _dict_get(payload, "automation", "self_improvement"),
        _dict_get(payload, "automation", "live_quality_burn"),
        payload.get("live_quality_burn"),
    ):
        if isinstance(container, dict):
            actions.extend(_dicts(container.get("next_actions")))
    return actions


def _dict_get(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _aggregate_counts(actions: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for action in actions:
        value = action.get(field)
        if not isinstance(value, dict):
            continue
        for key, count in value.items():
            name = str(key or "").strip()
            if not name:
                continue
            counts[name] = counts.get(name, 0) + _int(count)
    return counts


def _next_steps(
    *,
    report_success: bool,
    failures: list[str],
    live_e2e_ran: bool,
    carried_live_evidence_current: bool,
    live_decision: str,
    is_stale: bool,
    summary: dict[str, Any],
    trend_degradations: list[str],
    slack_upload_policy: dict[str, Any],
) -> list[str]:
    steps: list[str] = []
    if not report_success or failures:
        steps.append("inspect_self_validation_failures")
    if summary.get("closed_loop_regression_success") is False or "closed_loop_regression_failed" in failures:
        steps.append("inspect_closed_loop_policy_application")
    if (live_decision != "run" or not live_e2e_ran) and not carried_live_evidence_current:
        steps.append("enable_or_force_live_self_validation")
    if is_stale:
        steps.append("refresh_stale_self_validation")
    if trend_degradations:
        steps.append("stabilize_live_quality_trends")
    if summary.get("slack_duplicate_delivery_count") not in (None, 0):
        steps.append("fix_duplicate_delivery")
    if summary.get("live_slack_upload_native_delivery_covered") is False:
        steps.append("verify_slack_native_uploads")
    if (
        live_e2e_ran
        and summary.get("live_slack_upload_native_delivery_covered") is None
        and slack_upload_policy.get("decision") != "run"
    ):
        if slack_upload_policy.get("decision") == "skip_missing_target":
            steps.append("configure_live_slack_upload_target")
        else:
            steps.append("enable_live_slack_upload_self_validation")
    if not steps:
        steps.append("continue_visual_agent_mode_rollout")
    return steps


def _health_status(
    *,
    report_success: bool,
    next_steps: list[str],
    live_e2e_ran: bool,
    carried_live_evidence_current: bool,
    failures: list[str],
) -> str:
    if not report_success or failures:
        return "fail"
    if not live_e2e_ran and not carried_live_evidence_current:
        return "warn"
    if any(step != "continue_visual_agent_mode_rollout" for step in next_steps):
        return "warn"
    return "pass"


def _carried_live_evidence_current(
    *,
    live_decision: str,
    summary: dict[str, Any],
    is_stale: bool,
) -> bool:
    if live_decision != "skip_interval" or is_stale:
        return False
    if summary.get("live_quality_burn_success") is not True:
        return False
    if _int(summary.get("live_quality_burn_case_count")) <= 0:
        return False
    if summary.get("live_quality_burn_image_first_video_source_covered") is False:
        return False
    if _int(summary.get("live_quality_burn_image_first_video_source_failure_count")) > 0:
        return False
    if _int(summary.get("live_quality_burn_quality_focus_failure_count")) > 0:
        return False
    return True


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _normalise_now(parsed)


def _normalise_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _age_hours(now: datetime, generated_at: datetime | None) -> float | None:
    if generated_at is None:
        return None
    return round(max(0.0, (now - generated_at).total_seconds() / 3600), 4)


def _dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return _int(value)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize the latest visual self-validation health.")
    parser.add_argument("--latest-path", type=Path, default=None)
    parser.add_argument("--stale-after-hours", type=float, default=DEFAULT_STALE_AFTER_HOURS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_self_validation_status(
        latest_path=args.latest_path,
        stale_after_hours=args.stale_after_hours,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"visual self-validation status {payload['health_status']}")
    if args.allow_failures:
        return 0
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
