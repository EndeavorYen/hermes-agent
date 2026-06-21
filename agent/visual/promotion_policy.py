from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromotionThresholds:
    min_bucket_requests: int = 20
    min_successful_artifacts: int = 10
    min_successful_deliveries: int = 5
    min_provider_confidence: float = 0.80
    min_shadow_confidence: float = 0.75
    max_duplicate_deliveries: int = 0
    max_missing_source_metadata: int = 0
    max_recent_negative_feedback: int = 0
    max_human_veto_count: int = 0
    max_judge_human_disagreement_rate: float = 0.25

    def to_record(self) -> dict[str, float | int | bool]:
        return {
            "min_bucket_requests": self.min_bucket_requests,
            "min_successful_artifacts": self.min_successful_artifacts,
            "min_successful_deliveries": self.min_successful_deliveries,
            "min_provider_confidence": self.min_provider_confidence,
            "min_shadow_confidence": self.min_shadow_confidence,
            "max_duplicate_deliveries": self.max_duplicate_deliveries,
            "max_missing_source_metadata": self.max_missing_source_metadata,
            "max_recent_negative_feedback": self.max_recent_negative_feedback,
            "max_human_veto_count": self.max_human_veto_count,
            "max_judge_human_disagreement_rate": self.max_judge_human_disagreement_rate,
            "operator_approved": True,
            "self_validation_success": True,
            "prompt_mutation_allowed": False,
        }


@dataclass(frozen=True)
class PromotionDecision:
    decision: str
    allowed: bool
    reasons: list[str]
    confidence: float
    required: dict[str, float | int | bool]
    observed: dict[str, float | int | bool]

    def to_record(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "allowed": self.allowed,
            "reasons": self.reasons,
            "confidence": self.confidence,
            "required": self.required,
            "observed": self.observed,
        }


def evaluate_shadow_promotion(
    evidence: dict[str, Any],
    *,
    operator_approved: bool = False,
    thresholds: PromotionThresholds | None = None,
) -> PromotionDecision:
    thresholds = thresholds or PromotionThresholds()
    observed = _observed(evidence, operator_approved=operator_approved)
    reasons = _gate_failures(observed, thresholds)
    confidence = min(
        _float(observed["provider_confidence"]),
        _float(observed["shadow_confidence"]),
    )
    if not reasons:
        decision = "promote_controlled"
        allowed = True
    elif "operator_approval_required" in reasons:
        decision = "blocked"
        allowed = False
    else:
        decision = "shadow_only"
        allowed = False
    return PromotionDecision(
        decision=decision,
        allowed=allowed,
        reasons=reasons,
        confidence=round(confidence, 4),
        required=thresholds.to_record(),
        observed=observed,
    )


def _observed(
    evidence: dict[str, Any],
    *,
    operator_approved: bool,
) -> dict[str, float | int | bool]:
    return {
        "bucket_request_count": _int(evidence.get("bucket_request_count")),
        "successful_artifact_count": _int(evidence.get("successful_artifact_count")),
        "successful_delivery_count": _int(evidence.get("successful_delivery_count")),
        "provider_confidence": _float(evidence.get("provider_confidence")),
        "shadow_confidence": _float(evidence.get("shadow_confidence")),
        "duplicate_delivery_count": _int(evidence.get("duplicate_delivery_count")),
        "missing_source_metadata_count": _int(evidence.get("missing_source_metadata_count")),
        "recent_negative_feedback_count": _int(evidence.get("recent_negative_feedback_count")),
        "human_veto_count": _int(evidence.get("human_veto_count")),
        "judge_human_disagreement_rate": _float(evidence.get("judge_human_disagreement_rate")),
        "self_validation_success": evidence.get("self_validation_success") is True,
        "operator_approved": operator_approved is True,
        "prompt_mutation_allowed": evidence.get("prompt_mutation_allowed") is True,
    }


def _gate_failures(
    observed: dict[str, float | int | bool],
    thresholds: PromotionThresholds,
) -> list[str]:
    reasons: list[str] = []
    if _int(observed["bucket_request_count"]) < thresholds.min_bucket_requests:
        reasons.append("insufficient_bucket_requests")
    if _int(observed["successful_artifact_count"]) < thresholds.min_successful_artifacts:
        reasons.append("insufficient_successful_artifacts")
    if _int(observed["successful_delivery_count"]) < thresholds.min_successful_deliveries:
        reasons.append("insufficient_successful_deliveries")
    if _float(observed["provider_confidence"]) < thresholds.min_provider_confidence:
        reasons.append("provider_confidence_below_threshold")
    if _float(observed["shadow_confidence"]) < thresholds.min_shadow_confidence:
        reasons.append("shadow_confidence_below_threshold")
    if _int(observed["duplicate_delivery_count"]) > thresholds.max_duplicate_deliveries:
        reasons.append("duplicate_delivery_detected")
    if _int(observed["missing_source_metadata_count"]) > thresholds.max_missing_source_metadata:
        reasons.append("missing_source_metadata")
    if _int(observed["recent_negative_feedback_count"]) > thresholds.max_recent_negative_feedback:
        reasons.append("recent_negative_feedback")
    if _int(observed["human_veto_count"]) > thresholds.max_human_veto_count:
        reasons.append("human_veto_detected")
    if _float(observed["judge_human_disagreement_rate"]) > thresholds.max_judge_human_disagreement_rate:
        reasons.append("judge_human_disagreement_above_threshold")
    if observed["self_validation_success"] is not True:
        reasons.append("self_validation_failed")
    if observed["operator_approved"] is not True:
        reasons.append("operator_approval_required")
    if observed["prompt_mutation_allowed"] is True:
        reasons.append("prompt_mutation_requested")
    return reasons


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
