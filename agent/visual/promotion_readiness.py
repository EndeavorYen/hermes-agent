from __future__ import annotations

from typing import Any


MIN_PROMOTION_LIVE_SCORE = 0.80
MIN_PROMOTION_STRATEGY_CONFIDENCE = 0.80
MIN_PROMOTION_CASES = 2

_SAFE_CANDIDATE_FIELDS = {
    "type",
    "source",
    "track",
    "strategy_signature",
    "bucket",
    "intent_signature",
    "activation_status",
    "confidence",
    "evidence_count",
}


def build_visual_promotion_readiness(
    *,
    report_success: bool,
    failures: list[str],
    live_e2e_ran: bool,
    summary: dict[str, Any],
    actions: list[dict[str, Any]],
    trend_degradations: list[str],
) -> dict[str, Any]:
    candidate = _strategy_candidate(actions)
    blocking_reasons = _blocking_reasons(
        report_success=report_success,
        failures=failures,
        live_e2e_ran=live_e2e_ran,
        summary=summary,
        candidate=candidate,
        trend_degradations=trend_degradations,
    )
    return {
        "ready": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "candidate": _sanitize_candidate(candidate),
        "thresholds": _thresholds(),
        "self_review": _self_review(),
    }


def missing_visual_promotion_readiness() -> dict[str, Any]:
    return {
        "ready": False,
        "blocking_reasons": ["self_validation_report_missing"],
        "candidate": None,
        "thresholds": _thresholds(),
        "self_review": _self_review(),
    }


def _thresholds() -> dict[str, float | int | bool]:
    return {
        "min_live_quality_burn_score": MIN_PROMOTION_LIVE_SCORE,
        "min_live_quality_burn_cases": MIN_PROMOTION_CASES,
        "allows_live_conversation_quality_evidence": True,
        "min_live_conversation_quality_score": MIN_PROMOTION_LIVE_SCORE,
        "min_live_conversation_quality_cases": MIN_PROMOTION_CASES,
        "min_strategy_confidence": MIN_PROMOTION_STRATEGY_CONFIDENCE,
        "requires_current_live_run": True,
        "requires_native_slack_upload": True,
        "requires_no_live_trend_degradation": True,
    }


def _self_review() -> dict[str, bool]:
    return {
        "privacy_safe": True,
        "raw_action_exposed": False,
        "provider_stability_gated": True,
        "aesthetic_quality_gated": True,
        "conversation_evidence_gated": True,
        "activation_performed": False,
    }


def _blocking_reasons(
    *,
    report_success: bool,
    failures: list[str],
    live_e2e_ran: bool,
    summary: dict[str, Any],
    candidate: dict[str, Any] | None,
    trend_degradations: list[str],
) -> list[str]:
    reasons: list[str] = []
    has_conversation_evidence = _has_live_conversation_quality_evidence(summary)
    conversation_evidence_ready = live_conversation_quality_evidence_ready(summary)
    live_burn_evidence_ready = _live_quality_burn_evidence_ready(summary)
    if not report_success or failures:
        reasons.append("self_validation_failed")
    if not live_e2e_ran and not conversation_evidence_ready:
        reasons.append("current_live_run_required")
    if trend_degradations:
        reasons.append("live_quality_trend_degraded")
    if live_burn_evidence_ready or conversation_evidence_ready:
        pass
    elif has_conversation_evidence:
        reasons.extend(_live_conversation_quality_blocking_reasons(summary))
    else:
        reasons.extend(_live_quality_burn_blocking_reasons(summary))
    if _int(summary.get("live_quality_burn_quality_focus_failure_count")) > 0:
        reasons.append("quality_focus_failures")
    if _int(summary.get("slack_duplicate_delivery_count")) > 0:
        reasons.append("duplicate_delivery_detected")
    if candidate is None:
        reasons.append("no_shadow_strategy_candidate")
    else:
        if str(candidate.get("activation_status") or "") != "shadow":
            reasons.append("strategy_candidate_not_shadow")
        if not str(candidate.get("strategy_signature") or "").strip():
            reasons.append("missing_strategy_signature")
        if _float(candidate.get("confidence")) < MIN_PROMOTION_STRATEGY_CONFIDENCE:
            reasons.append("strategy_confidence_below_threshold")
    return _dedupe(reasons)


def live_conversation_quality_evidence_ready(summary: dict[str, Any]) -> bool:
    if not _has_live_conversation_quality_evidence(summary):
        return False
    return not _live_conversation_quality_blocking_reasons(summary)


def _live_quality_burn_evidence_ready(summary: dict[str, Any]) -> bool:
    return not _live_quality_burn_blocking_reasons(summary)


def _live_quality_burn_blocking_reasons(summary: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if summary.get("live_quality_burn_success") is not True:
        reasons.append("live_quality_burn_not_successful")
    if _int(summary.get("live_quality_burn_case_count")) < MIN_PROMOTION_CASES:
        reasons.append("insufficient_live_quality_cases")
    promotion_score = summary.get("live_quality_burn_promotion_min_score")
    if promotion_score is None:
        promotion_score = summary.get("live_quality_burn_min_score")
    if _float(promotion_score) < MIN_PROMOTION_LIVE_SCORE:
        reasons.append("live_quality_score_below_threshold")
    if summary.get("live_quality_burn_image_first_video_source_covered") is not True:
        reasons.append("image_first_video_source_not_covered")
    if _int(summary.get("live_quality_burn_image_first_video_source_failure_count")) > 0:
        reasons.append("image_first_video_source_failures")
    if summary.get("live_slack_upload_native_delivery_covered") is not True:
        reasons.append("slack_native_upload_not_covered")
    return reasons


def _has_live_conversation_quality_evidence(summary: dict[str, Any]) -> bool:
    return (
        _int(summary.get("live_conversation_quality_run_count")) > 0
        or summary.get("live_conversation_quality_recent_avg_min_quality_score") is not None
        or _int(summary.get("live_conversation_quality_native_video_upload_covered_count")) > 0
        or _int(summary.get("live_conversation_quality_image_first_video_source_failure_count")) > 0
        or _int(summary.get("live_conversation_quality_provider_failure_count")) > 0
    )


def _live_conversation_quality_blocking_reasons(summary: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if _int(summary.get("live_conversation_quality_run_count")) < MIN_PROMOTION_CASES:
        reasons.append("insufficient_live_conversation_quality_cases")
    if (
        _float(summary.get("live_conversation_quality_recent_avg_min_quality_score"))
        < MIN_PROMOTION_LIVE_SCORE
    ):
        reasons.append("live_conversation_quality_score_below_threshold")
    if (
        _int(summary.get("live_conversation_quality_native_video_upload_covered_count"))
        < MIN_PROMOTION_CASES
    ):
        reasons.append("live_conversation_native_upload_not_covered")
    if _int(summary.get("live_conversation_quality_image_first_video_source_failure_count")) > 0:
        reasons.append("live_conversation_image_first_video_source_failures")
    if _int(summary.get("live_conversation_quality_provider_failure_count")) > 0:
        reasons.append("live_conversation_provider_failures")
    return reasons


def _strategy_candidate(actions: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [action for action in actions if str(action.get("type") or "") == "prefer_strategy"]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda action: (_float(action.get("confidence")), _int(action.get("evidence_count"))),
        reverse=True,
    )[0]


def _sanitize_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    sanitized: dict[str, Any] = {}
    for key in _SAFE_CANDIDATE_FIELDS:
        value = candidate.get(key)
        if value is None:
            continue
        if key == "confidence":
            sanitized[key] = round(_float(value), 4)
        elif key == "evidence_count":
            sanitized[key] = _int(value)
        else:
            sanitized[key] = str(value)
    ordered_keys = [
        "type",
        "source",
        "track",
        "strategy_signature",
        "bucket",
        "intent_signature",
        "activation_status",
        "confidence",
        "evidence_count",
    ]
    return {key: sanitized[key] for key in ordered_keys if key in sanitized}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
