from __future__ import annotations

from typing import Any


ALLOWED_PROPOSAL_TYPES = {
    "prefer_strategy",
    "avoid_strategy",
    "prefer_provider_for_bucket",
    "avoid_provider_for_bucket",
    "increase_candidate_budget",
    "reduce_video_duration",
    "ask_user_sooner",
}


def propose_visual_policy_updates(outcomes: dict[str, Any]) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for outcome in outcomes.get("outcomes", []):
        if not isinstance(outcome, dict):
            continue
        proposals.extend(_strategy_proposals(outcome))
        proposals.extend(_provider_proposals(outcome))
        proposals.extend(_budget_proposals(outcome))
    return [
        proposal
        for proposal in proposals
        if proposal.get("type") in ALLOWED_PROPOSAL_TYPES and proposal.get("activation_status") == "shadow"
    ]


def _strategy_proposals(outcome: dict[str, Any]) -> list[dict[str, Any]]:
    request_count = _int(outcome.get("request_count"))
    confidence = _float(outcome.get("confidence"))
    quality = _nested_float(outcome, "quality", "average_confidence")
    feedback = _nested_float(outcome, "human_feedback", "average_polarity")
    human_veto = _nested_int(outcome, "human_feedback", "human_veto_count")
    delivery_success = _nested_float(outcome, "delivery", "delivery_success_rate")
    duplicate_delivery = _nested_int(outcome, "delivery", "duplicate_delivery_count")
    disagreement = _nested_float(outcome, "disagreement", "judge_human_disagreement_rate")
    ask_user_rate = _nested_float(outcome, "active_learning", "ask_user_rate")

    proposals: list[dict[str, Any]] = []
    if (
        request_count >= 10
        and confidence >= 0.60
        and quality >= 0.75
        and feedback >= 0
        and delivery_success >= 0.85
        and duplicate_delivery == 0
        and human_veto == 0
        and disagreement <= 0.25
    ):
        proposals.append(
            _proposal(
                "prefer_strategy",
                outcome,
                confidence=confidence,
                reason="high_quality_delivery_and_positive_feedback",
            )
        )

    if (
        request_count >= 5
        and (
            quality < 0.50
            or feedback <= -0.35
            or delivery_success < 0.50
            or duplicate_delivery > 0
            or human_veto > 0
            or disagreement > 0.50
        )
    ):
        proposals.append(
            _proposal(
                "avoid_strategy",
                outcome,
                confidence=max(confidence, min(1.0, 0.55 + disagreement * 0.4)),
                reason="negative_feedback_or_quality_disagreement",
            )
        )

    if request_count >= 5 and (ask_user_rate >= 0.50 or disagreement > 0.35 or human_veto > 0):
        proposals.append(
            _proposal(
                "ask_user_sooner",
                outcome,
                confidence=max(confidence, min(1.0, 0.50 + ask_user_rate * 0.4 + disagreement * 0.2)),
                reason="high_uncertainty_or_human_veto",
            )
        )
    return proposals


def _provider_proposals(outcome: dict[str, Any]) -> list[dict[str, Any]]:
    providers = outcome.get("provider_health", {}).get("providers", {})
    if not isinstance(providers, dict):
        return []
    proposals: list[dict[str, Any]] = []
    for provider_model, stats in sorted(providers.items()):
        if not isinstance(stats, dict):
            continue
        attempt_count = _int(stats.get("attempt_count"))
        success_rate = _float(stats.get("generation_success_rate"))
        policy_failure_rate = _float(stats.get("policy_failure_rate"))
        if attempt_count >= 5 and success_rate >= 0.85 and policy_failure_rate <= 0.05:
            proposals.append(
                _proposal(
                    "prefer_provider_for_bucket",
                    outcome,
                    confidence=min(_float(outcome.get("confidence")), success_rate),
                    reason="provider_reliable_for_bucket",
                    provider_model=provider_model,
                )
            )
        if attempt_count >= 5 and (success_rate <= 0.50 or policy_failure_rate >= 0.20):
            proposals.append(
                _proposal(
                    "avoid_provider_for_bucket",
                    outcome,
                    confidence=max(_float(outcome.get("confidence")), 0.60),
                    reason="provider_low_success_or_policy_failures",
                    provider_model=provider_model,
                )
            )
    return proposals


def _budget_proposals(outcome: dict[str, Any]) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    quality = _nested_float(outcome, "quality", "average_confidence")
    provider_success = _nested_float(outcome, "provider_health", "generation_success_rate")
    retry_attempts = _nested_int(outcome, "retry", "retry_attempt_count")
    retry_success = _nested_float(outcome, "retry", "retry_success_rate")
    if quality < 0.55 and provider_success >= 0.60:
        proposals.append(
            _proposal(
                "increase_candidate_budget",
                outcome,
                confidence=max(_float(outcome.get("confidence")), 0.55),
                reason="provider_renders_but_quality_selection_needs_more_candidates",
                max_candidate_budget=4,
            )
        )
    if retry_attempts >= 3 and retry_success < 0.50:
        proposals.append(
            _proposal(
                "reduce_video_duration",
                outcome,
                confidence=max(_float(outcome.get("confidence")), 0.55),
                reason="retry_effectiveness_low_for_current_video_duration",
                max_duration_seconds=6,
            )
        )
    return proposals


def _proposal(
    proposal_type: str,
    outcome: dict[str, Any],
    *,
    confidence: float,
    reason: str,
    **extra: Any,
) -> dict[str, Any]:
    proposal = {
        "type": proposal_type,
        "bucket": str(outcome.get("bucket") or "unknown"),
        "strategy_signature": str(outcome.get("strategy_signature") or "unknown"),
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "evidence_counts": _evidence_counts(outcome),
        "reason": reason,
        "activation_status": "shadow",
    }
    proposal.update(extra)
    return proposal


def _evidence_counts(outcome: dict[str, Any]) -> dict[str, int]:
    return {
        "request_count": _int(outcome.get("request_count")),
        "attempt_count": _nested_int(outcome, "provider_health", "attempt_count"),
        "delivery_count": _nested_int(outcome, "delivery", "delivery_count"),
        "judgment_count": _nested_int(outcome, "quality", "judgment_count"),
        "feedback_count": _nested_int(outcome, "human_feedback", "feedback_count"),
        "human_veto_count": _nested_int(outcome, "human_feedback", "human_veto_count"),
    }


def _nested_float(row: dict[str, Any], outer: str, inner: str) -> float:
    value = row.get(outer)
    if not isinstance(value, dict):
        return 0.0
    return _float(value.get(inner))


def _nested_int(row: dict[str, Any], outer: str, inner: str) -> int:
    value = row.get(outer)
    if not isinstance(value, dict):
        return 0
    return _int(value.get(inner))


def _float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
