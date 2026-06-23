from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from datetime import timedelta
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
DEFAULT_RUNTIME_POLICY_TTL_HOURS = 24
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
    "check_provider_connectivity_or_retry",
    "resolve_provider_quota_or_switch_provider",
    "configure_video_fallback_provider",
    "configure_visual_judge_provider",
    "configure_visual_runtime_dependencies",
    "prefer_strategy",
}
_RUNTIME_POLICY_ACTION_KEYS = {
    "type",
    "track",
    "reason",
    "confidence",
    "evidence_count",
    "requires_human_feedback",
    "requires_operator_setup",
    "activation_status",
    "source",
    "missing_modules",
    "operator_setup_actions",
    "evaluation_operator",
    "max_candidate_budget",
    "candidate_budget",
    "modality",
    "success_rate",
    "selected_repair_rate",
    "dimension",
    "quality_issue",
    "quality_issues",
    "repair_hint",
    "focus",
    "case_ids",
    "strategy_operator",
    "provider_failure_classes",
    "provider_error_codes",
    "strategy_signature",
    "bucket",
    "prompt_mutation_allowed",
    "video_fallback_diagnostics",
}


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
    pre_live_quality_trends = build_live_quality_trend_report_from_dir(_live_quality_burn_dir(output_dir))
    live_policy = _live_policy(
        live_mode=live_mode,
        live_enabled=_live_enabled() if live_enabled is None else live_enabled,
        min_live_interval_hours=min_live_interval_hours,
        state=state,
        now=now,
        live_quality_trends=pre_live_quality_trends,
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
    summary = _summary(automation, live_quality_trends=live_quality_trends)
    runtime_policy = _runtime_policy(automation, now=now, summary=summary)
    report = {
        "success": automation.get("success") is True,
        "run_id": _run_id(now),
        "generated_at": now.isoformat(),
        "mode": "fixture+live" if include_live else "fixture",
        "failures": list(automation.get("failures") or []),
        "live_policy": live_policy,
        "slack_live_upload_policy": slack_live_upload_policy,
        "live_quality_trends": live_quality_trends,
        "runtime_policy": runtime_policy,
        "summary": summary,
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
    live_quality_trends: dict[str, Any] | None = None,
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
        trend_degradations = _live_quality_trend_degradations(live_quality_trends)
        if trend_degradations:
            return {
                "mode": mode,
                "decision": "run",
                "live_enabled": True,
                "reason": "live_quality_trend_degraded",
                "degradations": trend_degradations,
                "min_live_interval_hours": min_live_interval_hours,
                "last_live_run_at": last_live_run_at.isoformat(),
                "elapsed_hours": round(elapsed_hours, 4),
            }
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


def _live_quality_trend_degradations(live_quality_trends: dict[str, Any] | None) -> list[str]:
    if not isinstance(live_quality_trends, dict):
        return []
    degradations = live_quality_trends.get("degradations")
    if not isinstance(degradations, list):
        return []
    return [str(item) for item in degradations if isinstance(item, str) and item]


def _summary(automation: dict[str, Any], live_quality_trends: dict[str, Any] | None = None) -> dict[str, Any]:
    live_quality_trends = live_quality_trends if isinstance(live_quality_trends, dict) else {}
    live_quality_trend_summary = (
        live_quality_trends.get("summary")
        if isinstance(live_quality_trends.get("summary"), dict)
        else {}
    )
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
    fixture_e2e = automation.get("fixture_e2e") if isinstance(automation.get("fixture_e2e"), dict) else {}
    live_e2e = automation.get("live_e2e") if isinstance(automation.get("live_e2e"), dict) else {}
    fixture_runtime_policy_effect = _runtime_policy_effect(fixture_e2e)
    live_runtime_policy_effect = _runtime_policy_effect(live_e2e)
    live_runtime_policy_quality_delta = _runtime_policy_quality_delta(
        live_runtime_policy_effect,
        baseline_score=live_quality_trend_summary.get("recent_avg_min_quality_score"),
    )
    live_evidence = live_e2e.get("evidence") if isinstance(live_e2e.get("evidence"), dict) else {}
    quality_gate = live_evidence.get("quality_gate") if isinstance(live_evidence.get("quality_gate"), dict) else {}
    slack_delivery = automation.get("slack_delivery") if isinstance(automation.get("slack_delivery"), dict) else {}
    delivery = slack_delivery.get("delivery") if isinstance(slack_delivery.get("delivery"), dict) else {}
    slack_conversation = (
        automation.get("slack_conversation")
        if isinstance(automation.get("slack_conversation"), dict)
        else {}
    )
    slack_conversation_self_review = (
        slack_conversation.get("self_review")
        if isinstance(slack_conversation.get("self_review"), dict)
        else {}
    )
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
    slack_internal_source_image_artifact_ids = _list(delivery.get("internal_source_image_artifact_ids"))
    slack_internal_source_image_delivery_count = len(slack_internal_source_image_artifact_ids)
    scheduled_validation_reduces_human_intervention = (
        automation.get("success") is True
        and feedback_action_types != []
        and slack_sent_count == slack_deliverable_count
        and slack_duplicate_delivery_count == 0
        and slack_unexpected_delivery_count == 0
        and slack_internal_source_image_delivery_count == 0
    )
    return {
        "feedback_action_types": feedback_action_types,
        "slack_conversation_self_review_decision": slack_conversation_self_review.get("decision"),
        "slack_conversation_self_review_success": slack_conversation_self_review.get("success")
        if "success" in slack_conversation_self_review
        else None,
        "slack_conversation_requires_human_feedback": slack_conversation_self_review.get(
            "requires_human_feedback"
        )
        if "requires_human_feedback" in slack_conversation_self_review
        else None,
        "slack_conversation_requires_operator_setup": slack_conversation_self_review.get(
            "requires_operator_setup"
        )
        if "requires_operator_setup" in slack_conversation_self_review
        else None,
        "slack_conversation_operator_setup_actions": _dict_list(
            slack_conversation_self_review.get("operator_setup_actions")
        ),
        "slack_conversation_operator_setup_action_count": _int(
            slack_conversation_self_review.get("operator_setup_action_count")
        ),
        "slack_conversation_reduces_human_intervention": slack_conversation_self_review.get(
            "reduces_human_intervention"
        )
        if "reduces_human_intervention" in slack_conversation_self_review
        else None,
        "slack_conversation_auto_next_action_count": _int(
            slack_conversation_self_review.get("auto_next_action_count")
        ),
        "slack_conversation_action_types": _list(slack_conversation_self_review.get("action_types")),
        "slack_conversation_quality_gate_success": slack_conversation_self_review.get(
            "quality_gate_success"
        )
        if "quality_gate_success" in slack_conversation_self_review
        else None,
        "slack_conversation_provider_failure_count": _int(
            slack_conversation_self_review.get("provider_failure_count")
        ),
        "slack_conversation_image_first_video_source_covered": slack_conversation_self_review.get(
            "image_first_video_source_covered"
        )
        if "image_first_video_source_covered" in slack_conversation_self_review
        else None,
        "slack_conversation_native_video_upload_covered": slack_conversation_self_review.get(
            "native_video_upload_covered"
        )
        if "native_video_upload_covered" in slack_conversation_self_review
        else None,
        "slack_conversation_blocking_reasons": _list(
            slack_conversation_self_review.get("blocking_reasons")
        ),
        "fixture_runtime_policy_active": fixture_runtime_policy_effect.get("policy_active"),
        "fixture_runtime_policy_applied": fixture_runtime_policy_effect.get("applied"),
        "fixture_runtime_policy_expected_action_types": _list(
            fixture_runtime_policy_effect.get("expected_action_types")
        ),
        "fixture_runtime_policy_missing_action_types": _list(
            fixture_runtime_policy_effect.get("missing_action_types")
        ),
        "fixture_runtime_policy_quality_gate_success": fixture_runtime_policy_effect.get(
            "quality_gate_success"
        ),
        "fixture_runtime_policy_quality_gate_min_score": fixture_runtime_policy_effect.get(
            "quality_gate_min_score"
        ),
        "fixture_runtime_policy_quality_issue_count": _int(
            fixture_runtime_policy_effect.get("quality_issue_count")
        ),
        "fixture_runtime_policy_video_source_uses_ranked_selected_image": fixture_runtime_policy_effect.get(
            "video_source_uses_ranked_selected_image"
        ),
        "live_runtime_policy_active": live_runtime_policy_effect.get("policy_active"),
        "live_runtime_policy_applied": live_runtime_policy_effect.get("applied"),
        "live_runtime_policy_expected_action_types": _list(
            live_runtime_policy_effect.get("expected_action_types")
        ),
        "live_runtime_policy_missing_action_types": _list(
            live_runtime_policy_effect.get("missing_action_types")
        ),
        "live_runtime_policy_quality_gate_success": live_runtime_policy_effect.get(
            "quality_gate_success"
        ),
        "live_runtime_policy_quality_gate_min_score": live_runtime_policy_effect.get(
            "quality_gate_min_score"
        ),
        "live_runtime_policy_quality_issue_count": _int(
            live_runtime_policy_effect.get("quality_issue_count")
        ),
        "live_runtime_policy_video_source_uses_ranked_selected_image": live_runtime_policy_effect.get(
            "video_source_uses_ranked_selected_image"
        ),
        "live_runtime_policy_quality_delta_vs_recent_trend": live_runtime_policy_quality_delta,
        "live_runtime_policy_quality_regressed": (
            live_runtime_policy_quality_delta < 0
            if live_runtime_policy_quality_delta is not None
            else None
        ),
        "live_quality_gate_success": quality_gate.get("success"),
        "live_quality_gate_min_score": quality_gate.get("min_score"),
        "slack_sent_count": slack_sent_count,
        "slack_deliverable_count": slack_deliverable_count,
        "slack_duplicate_delivery_count": slack_duplicate_delivery_count,
        "slack_unexpected_delivery_count": slack_unexpected_delivery_count,
        "slack_internal_source_image_delivery_count": slack_internal_source_image_delivery_count,
        "slack_internal_source_image_artifact_ids": slack_internal_source_image_artifact_ids,
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
        "live_quality_burn_promotion_min_score": live_quality_burn_summary.get(
            "promotion_min_quality_score"
        ),
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
        "live_quality_burn_image_first_video_source_not_single_count": _int(
            live_quality_burn_summary.get("image_first_video_source_not_single_count")
        ),
        "live_quality_burn_image_first_video_source_not_single_case_ids": _list(
            live_quality_burn_summary.get("image_first_video_source_not_single_case_ids")
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
        "live_quality_trend_recent_run_ids": _list(live_quality_trend_summary.get("recent_run_ids")),
        "live_quality_trend_recent_avg_min_quality_score": live_quality_trend_summary.get(
            "recent_avg_min_quality_score"
        ),
        "live_quality_trend_recent_provider_failure_count": _int(
            live_quality_trend_summary.get("recent_provider_failure_count")
        ),
        "live_quality_trend_recent_video_generation_failure_count": _int(
            live_quality_trend_summary.get("recent_video_generation_failure_count")
        ),
        "live_quality_trend_recent_preference_dimension_failure_count": _int(
            live_quality_trend_summary.get("recent_preference_dimension_failure_count")
        ),
        "live_conversation_quality_run_count": _int(
            live_quality_trend_summary.get("recent_slack_conversation_run_count")
        ),
        "live_conversation_quality_recent_run_ids": _list(
            live_quality_trend_summary.get("recent_slack_conversation_run_ids")
        ),
        "live_conversation_quality_recent_avg_min_quality_score": live_quality_trend_summary.get(
            "recent_slack_conversation_avg_min_quality_score"
        ),
        "live_conversation_quality_native_video_upload_covered_count": _int(
            live_quality_trend_summary.get("recent_slack_conversation_native_video_upload_covered_count")
        ),
        "live_conversation_quality_image_first_video_source_failure_count": _int(
            live_quality_trend_summary.get("recent_slack_conversation_image_first_video_source_failure_count")
        ),
        "live_conversation_quality_provider_failure_count": _int(
            live_quality_trend_summary.get("recent_slack_conversation_provider_failure_count")
        ),
        "live_conversation_quality_latest_generated_at": live_quality_trend_summary.get(
            "recent_slack_conversation_latest_generated_at"
        ),
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


def _runtime_policy_effect(report: dict[str, Any]) -> dict[str, Any]:
    evidence = report.get("evidence") if isinstance(report.get("evidence"), dict) else {}
    effect = (
        evidence.get("runtime_policy_effect")
        if isinstance(evidence.get("runtime_policy_effect"), dict)
        else {}
    )
    return effect


def _runtime_policy_quality_delta(
    effect: dict[str, Any],
    *,
    baseline_score: Any,
) -> float | None:
    current_score = _float_or_none(effect.get("quality_gate_min_score"))
    baseline = _float_or_none(baseline_score)
    if current_score is None or baseline is None:
        return None
    return round(current_score - baseline, 4)


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


def _runtime_policy(
    automation: dict[str, Any],
    *,
    now: datetime,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    self_improvement = (
        automation.get("self_improvement")
        if isinstance(automation.get("self_improvement"), dict)
        else {}
    )
    actions = _runtime_policy_actions(_action_list(self_improvement.get("next_actions")))
    if _runtime_policy_quality_regressed(summary):
        suspended_action_types = _runtime_policy_suspended_action_types(actions, summary)
        return {
            "success": False,
            "decision": "suspend_quality_regressed",
            "reason": "runtime_policy_quality_regressed",
            "generated_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=DEFAULT_RUNTIME_POLICY_TTL_HOURS)).isoformat(),
            "next_actions": [],
            "suspended_action_types": suspended_action_types,
            "privacy_safe": True,
            "source": "scheduled_self_validation",
        }
    if not actions:
        return {
            "success": False,
            "decision": "no_actions",
            "generated_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=DEFAULT_RUNTIME_POLICY_TTL_HOURS)).isoformat(),
            "next_actions": [],
            "privacy_safe": True,
        }
    return {
        "success": True,
        "decision": "apply_next_run",
        "generated_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=DEFAULT_RUNTIME_POLICY_TTL_HOURS)).isoformat(),
        "next_actions": actions,
        "privacy_safe": True,
        "source": "scheduled_self_validation",
    }


def _runtime_policy_quality_regressed(summary: dict[str, Any] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    return any(
        summary.get(f"{prefix}_runtime_policy_quality_regressed") is True
        for prefix in ("fixture", "live")
    )


def _runtime_policy_suspended_action_types(
    actions: list[dict[str, Any]],
    summary: dict[str, Any] | None,
) -> list[str]:
    values = _action_types(actions)
    if isinstance(summary, dict):
        for prefix in ("fixture", "live"):
            for key in (
                f"{prefix}_runtime_policy_expected_action_types",
                f"{prefix}_runtime_policy_missing_action_types",
            ):
                raw_action_types = summary.get(key)
                if not isinstance(raw_action_types, list):
                    continue
                for action_type in raw_action_types:
                    if not isinstance(action_type, str):
                        continue
                    action_type = action_type.strip()
                    if action_type and action_type not in values:
                        values.append(action_type)
    return values


def _runtime_policy_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for action in actions:
        sanitized_action = _runtime_policy_action(action)
        if sanitized_action:
            sanitized.append(sanitized_action)
    return _dedupe_actions(sanitized)


def _runtime_policy_action(action: dict[str, Any]) -> dict[str, Any]:
    action_type = str(action.get("type") or "").strip()
    if action_type not in _RUNTIME_POLICY_ACTION_TYPES:
        return {}
    if action.get("requires_human_feedback") is True:
        return {}
    if action.get("prompt_mutation_allowed") is True:
        return {}
    sanitized: dict[str, Any] = {}
    for key in _RUNTIME_POLICY_ACTION_KEYS:
        if key not in action:
            continue
        value = _runtime_policy_value(action[key])
        if value is not None:
            sanitized[key] = value
    sanitized["type"] = action_type
    sanitized["requires_human_feedback"] = False
    return sanitized


def _runtime_policy_value(value: Any) -> Any:
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        values = [_runtime_policy_value(item) for item in value]
        return [item for item in values if item is not None]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                continue
            safe_item = _runtime_policy_value(item)
            if safe_item is not None:
                sanitized[key.strip()] = safe_item
        return sanitized
    return None


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


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


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
