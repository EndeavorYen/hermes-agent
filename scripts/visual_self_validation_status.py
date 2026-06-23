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
from agent.visual.promotion_readiness import build_visual_promotion_readiness
from agent.visual.promotion_readiness import live_conversation_quality_evidence_ready
from agent.visual.promotion_readiness import missing_visual_promotion_readiness


DEFAULT_STALE_AFTER_HOURS = 24
_RUNTIME_POLICY_ACTION_TYPES = {
    "increase_candidate_budget",
    "prefer_image_first_video",
    "rerank_before_slack",
    "prefer_quality_repair_retry",
    "escalate_quality_repair_strategy",
    "repair_low_preference_dimension",
    "apply_quality_focus_operator",
    "require_preference_dimension_evidence",
    "enforce_single_video_source_image",
    "enforce_video_source_aspect_ratio",
    "safe_reframe_provider_retry",
    "resolve_provider_quota_or_switch_provider",
    "configure_video_fallback_provider",
    "configure_visual_runtime_dependencies",
    "prefer_strategy",
}


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
            "promotion_readiness": missing_visual_promotion_readiness(),
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
    live_conversation_evidence_current = (
        not is_stale and live_conversation_quality_evidence_ready(summary)
    )
    failures = _strings(payload.get("failures"))
    runtime_policy = _runtime_policy_status(payload.get("runtime_policy"), now=now, summary=summary)
    actions = _collect_actions(payload)
    action_types = _action_types(summary, actions)
    trend_degradations = _strings(summary.get("live_quality_trend_degradations"))
    provider_failure_classes = _aggregate_counts(actions, "provider_failure_classes")
    provider_error_codes = _aggregate_counts(actions, "provider_error_codes")
    promotion_readiness = build_visual_promotion_readiness(
        report_success=payload.get("success") is True,
        failures=failures,
        live_e2e_ran=live_e2e_ran,
        summary=summary,
        actions=actions,
        trend_degradations=trend_degradations,
    )

    next_steps = _next_steps(
        report_success=payload.get("success") is True,
        failures=failures,
        live_e2e_ran=live_e2e_ran,
        carried_live_evidence_current=carried_live_evidence_current,
        live_conversation_evidence_current=live_conversation_evidence_current,
        live_decision=live_decision,
        is_stale=is_stale,
        summary=summary,
        trend_degradations=trend_degradations,
        slack_upload_policy=slack_upload_policy,
        runtime_policy=runtime_policy,
    )
    health_status = _health_status(
        report_success=payload.get("success") is True,
        next_steps=next_steps,
        live_e2e_ran=live_e2e_ran,
        carried_live_evidence_current=carried_live_evidence_current,
        live_conversation_evidence_current=live_conversation_evidence_current,
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
        "runtime_policy": runtime_policy,
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
            "burn_promotion_min_score": summary.get("live_quality_burn_promotion_min_score"),
            "image_first_video_source_covered": summary.get(
                "live_quality_burn_image_first_video_source_covered"
            ),
            "image_first_video_source_failure_count": _optional_int(
                summary.get("live_quality_burn_image_first_video_source_failure_count")
            ),
            "image_first_video_source_not_single_count": _optional_int(
                summary.get("live_quality_burn_image_first_video_source_not_single_count")
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
            "trend_run_count": _optional_int(summary.get("live_quality_trend_run_count")),
            "trend_recent_run_ids": _strings(summary.get("live_quality_trend_recent_run_ids")),
            "trend_recent_avg_min_quality_score": summary.get(
                "live_quality_trend_recent_avg_min_quality_score"
            ),
            "trend_recent_provider_failure_count": _optional_int(
                summary.get("live_quality_trend_recent_provider_failure_count")
            ),
            "trend_recent_video_generation_failure_count": _optional_int(
                summary.get("live_quality_trend_recent_video_generation_failure_count")
            ),
            "trend_recent_preference_dimension_failure_count": _optional_int(
                summary.get("live_quality_trend_recent_preference_dimension_failure_count")
            ),
            "conversation_quality_run_count": _optional_int(
                summary.get("live_conversation_quality_run_count")
            ),
            "conversation_quality_recent_run_ids": _strings(
                summary.get("live_conversation_quality_recent_run_ids")
            ),
            "conversation_quality_recent_avg_min_quality_score": summary.get(
                "live_conversation_quality_recent_avg_min_quality_score"
            ),
            "conversation_quality_native_video_upload_covered_count": _optional_int(
                summary.get("live_conversation_quality_native_video_upload_covered_count")
            ),
            "conversation_quality_image_first_video_source_failure_count": _optional_int(
                summary.get("live_conversation_quality_image_first_video_source_failure_count")
            ),
            "conversation_quality_provider_failure_count": _optional_int(
                summary.get("live_conversation_quality_provider_failure_count")
            ),
            "conversation_quality_latest_generated_at": summary.get(
                "live_conversation_quality_latest_generated_at"
            ),
        },
        "delivery": {
            "native_video_upload_covered": summary.get("live_slack_upload_native_delivery_covered"),
            "uploaded_video_file_count": _optional_int(
                summary.get("live_slack_upload_uploaded_video_file_count")
            ),
            "duplicate_delivery_count": _optional_int(summary.get("slack_duplicate_delivery_count")),
            "internal_source_image_delivery_count": _optional_int(
                summary.get("slack_internal_source_image_delivery_count")
            ),
        },
        "conversation": {
            "self_review_decision": summary.get("slack_conversation_self_review_decision"),
            "self_review_success": summary.get("slack_conversation_self_review_success"),
            "requires_human_feedback": summary.get("slack_conversation_requires_human_feedback"),
            "requires_operator_setup": summary.get("slack_conversation_requires_operator_setup"),
            "operator_setup_actions": _dicts(
                summary.get("slack_conversation_operator_setup_actions")
            ),
            "operator_setup_action_count": _optional_int(
                summary.get("slack_conversation_operator_setup_action_count")
            ),
            "reduces_human_intervention": summary.get(
                "slack_conversation_reduces_human_intervention"
            ),
            "auto_next_action_count": _optional_int(
                summary.get("slack_conversation_auto_next_action_count")
            ),
            "quality_gate_success": summary.get("slack_conversation_quality_gate_success"),
            "provider_failure_count": _optional_int(
                summary.get("slack_conversation_provider_failure_count")
            ),
            "image_first_video_source_covered": summary.get(
                "slack_conversation_image_first_video_source_covered"
            ),
            "native_video_upload_covered": summary.get(
                "slack_conversation_native_video_upload_covered"
            ),
            "blocking_reasons": _strings(summary.get("slack_conversation_blocking_reasons")),
        },
        "self_improvement": {
            "action_types": action_types,
            "action_count": len(action_types),
            "requires_human_feedback": False,
        },
        "promotion_readiness": promotion_readiness,
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
        "reason",
        "degradations",
    }
    sanitized = {key: source[key] for key in allowed if key in source}
    if source.get("reason") == "live_quality_trend_degraded":
        sanitized["reason"] = "live_quality_trend_degraded"
    else:
        sanitized.pop("reason", None)
    degradations = source.get("degradations")
    if isinstance(degradations, list):
        allowed_degradations = {
            "quality_score_degraded",
            "video_generation_degraded",
            "provider_failures_spiked",
            "preference_dimension_failures_spiked",
        }
        sanitized_degradations = [
            item for item in degradations if isinstance(item, str) and item in allowed_degradations
        ]
        if sanitized_degradations:
            sanitized["degradations"] = sanitized_degradations
        else:
            sanitized.pop("degradations", None)
    else:
        sanitized.pop("degradations", None)
    return sanitized


def _sanitise_slack_upload_policy(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    allowed = {"decision", "enabled"}
    return {key: source[key] for key in allowed if key in source}


def _action_types(summary: dict[str, Any], actions: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for key in (
        "live_quality_burn_action_types",
        "live_quality_trend_action_types",
        "feedback_action_types",
        "slack_conversation_action_types",
    ):
        values.extend(_strings(summary.get(key)))
    for action in actions:
        if action.get("requires_human_feedback") is True:
            continue
        action_type = str(action.get("type") or "").strip()
        if action_type:
            values.append(action_type)
    return _dedupe(values)


def _collect_actions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for container in (
        payload.get("runtime_policy"),
        payload.get("self_improvement"),
        _dict_get(payload, "automation", "self_improvement"),
        _dict_get(payload, "automation", "live_quality_burn"),
        payload.get("live_quality_burn"),
    ):
        if isinstance(container, dict):
            actions.extend(_dicts(container.get("next_actions")))
    return actions


def _runtime_policy_status(value: Any, *, now: datetime, summary: dict[str, Any]) -> dict[str, Any]:
    policy = value if isinstance(value, dict) else {}
    generated_at = policy.get("generated_at") if isinstance(policy.get("generated_at"), str) else None
    expires_at_value = policy.get("expires_at") if isinstance(policy.get("expires_at"), str) else None
    expires_at = _parse_datetime(expires_at_value)
    expired = expires_at is not None and expires_at <= now
    actions = _dicts(policy.get("next_actions"))
    status = {
        "success": policy.get("success") is True,
        "decision": policy.get("decision"),
        "generated_at": generated_at,
        "expires_at": expires_at_value,
        "expired": expired,
        "action_types": _action_types({}, actions),
        "fixture_effect": _runtime_policy_effect_status(summary, prefix="fixture"),
        "live_effect": _runtime_policy_effect_status(summary, prefix="live"),
    }
    suspended_action_types = _sanitise_runtime_policy_action_types(
        policy.get("suspended_action_types")
    )
    if suspended_action_types:
        status["suspended_action_types"] = suspended_action_types
    return status


def _runtime_policy_effect_status(summary: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    return {
        "active": summary.get(f"{prefix}_runtime_policy_active"),
        "applied": summary.get(f"{prefix}_runtime_policy_applied"),
        "expected_action_types": _strings(summary.get(f"{prefix}_runtime_policy_expected_action_types")),
        "missing_action_types": _strings(summary.get(f"{prefix}_runtime_policy_missing_action_types")),
        "quality_gate_min_score": summary.get(f"{prefix}_runtime_policy_quality_gate_min_score"),
        "quality_delta_vs_recent_trend": summary.get(
            f"{prefix}_runtime_policy_quality_delta_vs_recent_trend"
        ),
        "quality_regressed": summary.get(f"{prefix}_runtime_policy_quality_regressed"),
    }


def _sanitise_runtime_policy_action_types(value: Any) -> list[str]:
    return [
        action_type
        for action_type in _strings(value)
        if action_type in _RUNTIME_POLICY_ACTION_TYPES
    ]


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
    live_conversation_evidence_current: bool,
    live_decision: str,
    is_stale: bool,
    summary: dict[str, Any],
    trend_degradations: list[str],
    slack_upload_policy: dict[str, Any],
    runtime_policy: dict[str, Any],
) -> list[str]:
    steps: list[str] = []
    if not report_success or failures:
        steps.append("inspect_self_validation_failures")
    if _has_action_type(
        "configure_visual_runtime_dependencies",
        summary,
        runtime_policy,
    ):
        steps.append("configure_visual_runtime_dependencies")
    if summary.get("closed_loop_regression_success") is False or "closed_loop_regression_failed" in failures:
        steps.append("inspect_closed_loop_policy_application")
    if (
        (live_decision != "run" or not live_e2e_ran)
        and not carried_live_evidence_current
        and not live_conversation_evidence_current
    ):
        steps.append("enable_or_force_live_self_validation")
    if is_stale:
        steps.append("refresh_stale_self_validation")
    if trend_degradations:
        steps.append("stabilize_live_quality_trends")
    if _runtime_policy_not_applied(summary):
        steps.append("verify_runtime_policy_application")
    if runtime_policy.get("decision") == "suspend_quality_regressed":
        steps.append("review_suspended_runtime_policy")
    if _runtime_policy_quality_regressed(summary):
        steps.append("inspect_runtime_policy_quality_regression")
    if summary.get("slack_duplicate_delivery_count") not in (None, 0):
        steps.append("fix_duplicate_delivery")
    if _int(summary.get("slack_internal_source_image_delivery_count")) > 0:
        steps.append("fix_internal_source_image_delivery")
    if summary.get("live_slack_upload_native_delivery_covered") is False:
        steps.append("verify_slack_native_uploads")
    if summary.get("slack_conversation_self_review_success") is False:
        if summary.get("slack_conversation_requires_human_feedback") is True:
            steps.append("review_slack_conversation_self_review_blocker")
        elif summary.get("slack_conversation_requires_operator_setup") is True:
            steps.append("configure_operator_setup_prerequisites")
        else:
            steps.append("apply_slack_conversation_self_review_actions")
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


def _runtime_policy_not_applied(summary: dict[str, Any]) -> bool:
    for prefix in ("fixture", "live"):
        if (
            summary.get(f"{prefix}_runtime_policy_active") is True
            and summary.get(f"{prefix}_runtime_policy_applied") is False
        ):
            return True
    return False


def _runtime_policy_quality_regressed(summary: dict[str, Any]) -> bool:
    for prefix in ("fixture", "live"):
        if summary.get(f"{prefix}_runtime_policy_quality_regressed") is True:
            return True
    return False


def _has_action_type(
    action_type: str,
    summary: dict[str, Any],
    runtime_policy: dict[str, Any],
) -> bool:
    values: list[str] = []
    values.extend(_strings(summary.get("feedback_action_types")))
    values.extend(_strings(runtime_policy.get("action_types")))
    return action_type in values


def _health_status(
    *,
    report_success: bool,
    next_steps: list[str],
    live_e2e_ran: bool,
    carried_live_evidence_current: bool,
    live_conversation_evidence_current: bool,
    failures: list[str],
) -> str:
    if not report_success or failures:
        if _runtime_dependency_setup_pending(failures, next_steps):
            return "warn"
        return "fail"
    if (
        not live_e2e_ran
        and not carried_live_evidence_current
        and not live_conversation_evidence_current
    ):
        return "warn"
    if any(step != "continue_visual_agent_mode_rollout" for step in next_steps):
        return "warn"
    return "pass"


def _runtime_dependency_setup_pending(failures: list[str], next_steps: list[str]) -> bool:
    if "configure_visual_runtime_dependencies" not in next_steps:
        return False
    if not failures:
        return False
    return all(failure == "runtime_environment_missing_dependencies" for failure in failures)


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
    if _int(summary.get("live_quality_burn_image_first_video_source_not_single_count")) > 0:
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
