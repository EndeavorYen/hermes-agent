from __future__ import annotations

from typing import Any


VERSION = "visual_active_learning_gate.v0.1"

AUTO_POST_SCORE_THRESHOLD = 0.80
AUTO_POST_CONFIDENCE_THRESHOLD = 0.75
ASK_CONFIDENCE_FLOOR = 0.45
_ACTIONABLE_RETRY_FAILURES = {
    "artifact_missing",
    "artifact_stale",
    "delivery_failed",
    "provider_timeout",
    "transient_provider_error",
    "no_candidate_passed_hard_gate",
}
_POLICY_FAILURES = {
    "content_moderation",
    "policy_failure",
    "safety",
    "guardrail",
}
_HIGH_RISK_UNCERTAINTY = {
    "conflicting_preferences",
    "identity_drift",
    "policy_failure",
    "repeated_aesthetic_miss",
}


def decide_visual_action(
    ranking: dict[str, Any],
    *,
    request_context: dict[str, Any],
) -> dict[str, Any]:
    score = _coerce_float(ranking.get("top_score"))
    confidence = _coerce_float(ranking.get("top_confidence"))
    uncertainty_reasons = _string_list(ranking.get("uncertainty_reasons"))
    ranking_decision = str(ranking.get("decision") or "")
    retry_budget = int(_coerce_float(request_context.get("retry_budget_remaining", 0)))
    failure_type = str(request_context.get("failure_type") or "")

    if ranking.get("proposed_learning_mutation") is True:
        return _decision(
            "shadow_only",
            False,
            "learning_mutation_requires_shadow_mode",
            score,
            confidence,
            uncertainty_reasons,
        )

    if _is_policy_failure(failure_type, uncertainty_reasons):
        return _decision(
            "fail_closed",
            False,
            "policy_failure_without_safe_retry_path",
            score,
            confidence,
            uncertainty_reasons,
        )

    if ranking_decision in {"retry", "fail"}:
        if retry_budget > 0 and _is_actionable_retry(failure_type, uncertainty_reasons):
            return _decision(
                "auto_retry",
                False,
                "actionable_failure_with_retry_budget",
                score,
                confidence,
                uncertainty_reasons,
            )
        return _decision(
            "fail_closed",
            False,
            "no_safe_retry_path",
            score,
            confidence,
            uncertainty_reasons,
        )

    if _requires_user_for_uncertainty(uncertainty_reasons, request_context):
        return _decision(
            "ask_user",
            True,
            "high_risk_uncertainty",
            score,
            confidence,
            uncertainty_reasons,
        )

    if score >= AUTO_POST_SCORE_THRESHOLD and confidence >= AUTO_POST_CONFIDENCE_THRESHOLD:
        return _decision(
            "auto_post",
            False,
            "high_score_high_confidence",
            score,
            confidence,
            uncertainty_reasons,
        )

    if confidence >= ASK_CONFIDENCE_FLOOR:
        return _decision(
            "ask_user",
            True,
            "moderate_confidence_requires_review",
            score,
            confidence,
            uncertainty_reasons,
        )

    if retry_budget > 0:
        return _decision(
            "auto_retry",
            False,
            "low_confidence_with_retry_budget",
            score,
            confidence,
            uncertainty_reasons,
        )

    return _decision(
        "fail_closed",
        False,
        "low_confidence_without_retry_budget",
        score,
        confidence,
        uncertainty_reasons,
    )


def _requires_user_for_uncertainty(
    uncertainty_reasons: list[str],
    request_context: dict[str, Any],
) -> bool:
    if request_context.get("has_reference_image") and "reference_adherence_missing" in uncertainty_reasons:
        return True
    return any(reason in _HIGH_RISK_UNCERTAINTY for reason in uncertainty_reasons)


def _is_actionable_retry(failure_type: str, uncertainty_reasons: list[str]) -> bool:
    return failure_type in _ACTIONABLE_RETRY_FAILURES or any(
        reason in _ACTIONABLE_RETRY_FAILURES
        for reason in uncertainty_reasons
    )


def _is_policy_failure(failure_type: str, uncertainty_reasons: list[str]) -> bool:
    return failure_type in _POLICY_FAILURES or any(
        reason in _POLICY_FAILURES
        for reason in uncertainty_reasons
    )


def _decision(
    action: str,
    requires_user: bool,
    reason: str,
    score: float,
    confidence: float,
    uncertainty_reasons: list[str],
) -> dict[str, Any]:
    return {
        "version": VERSION,
        "action": action,
        "requires_user": requires_user,
        "reason": reason,
        "top_score": score,
        "top_confidence": confidence,
        "uncertainty_reasons": uncertainty_reasons,
        "thresholds": {
            "auto_post_score": AUTO_POST_SCORE_THRESHOLD,
            "auto_post_confidence": AUTO_POST_CONFIDENCE_THRESHOLD,
            "ask_confidence_floor": ASK_CONFIDENCE_FLOOR,
        },
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
