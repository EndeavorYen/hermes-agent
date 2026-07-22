from __future__ import annotations

from typing import Any


LOW_RISK_PROPOSAL_TYPES = {
    "prefer_strategy",
    "prefer_provider_for_bucket",
    "increase_candidate_budget",
    "reduce_video_duration",
    "ask_user_sooner",
}


def evaluate_autonomous_rollout_candidate(
    proposal: dict[str, Any],
    *,
    runtime_checks: dict[str, Any],
    autonomy_level: int,
) -> dict[str, Any]:
    reasons = _reasons(proposal, runtime_checks=runtime_checks, autonomy_level=autonomy_level)
    return {
        "decision": "controlled_candidate" if not reasons else "shadow_only",
        "allowed": not reasons,
        "reasons": reasons,
        "confidence": _float(proposal.get("confidence")),
        "proposal_type": str(proposal.get("type") or ""),
        "activation_status": "controlled_candidate" if not reasons else "shadow",
    }


def _reasons(
    proposal: dict[str, Any],
    *,
    runtime_checks: dict[str, Any],
    autonomy_level: int,
) -> list[str]:
    reasons: list[str] = []
    proposal_type = str(proposal.get("type") or "")
    evidence = proposal.get("evidence_counts") if isinstance(proposal.get("evidence_counts"), dict) else {}
    if autonomy_level < 2:
        reasons.append("autonomy_level_below_controlled_threshold")
    if proposal_type not in LOW_RISK_PROPOSAL_TYPES:
        reasons.append("proposal_type_not_low_risk")
    if str(proposal.get("activation_status") or "") != "shadow":
        reasons.append("proposal_not_shadow")
    if _float(proposal.get("confidence")) < 0.85:
        reasons.append("proposal_confidence_below_threshold")
    if _int(evidence.get("request_count")) < 20:
        reasons.append("insufficient_request_count")
    if _int(evidence.get("attempt_count")) < 20:
        reasons.append("insufficient_attempt_count")
    if _int(evidence.get("delivery_count")) < 10:
        reasons.append("insufficient_delivery_count")
    if _int(evidence.get("judgment_count")) < 10:
        reasons.append("insufficient_judgment_count")
    if _int(evidence.get("human_veto_count")) > 0:
        reasons.append("human_veto_detected")
    if _int(runtime_checks.get("duplicate_delivery_count")) > 0:
        reasons.append("duplicate_delivery_detected")
    if _int(runtime_checks.get("missing_source_metadata_count")) > 0:
        reasons.append("missing_source_metadata")
    if _int(runtime_checks.get("prompt_mutation_read_count")) > 0:
        reasons.append("prompt_mutation_detected")
    if _int(runtime_checks.get("unsafe_activation_count")) > 0:
        reasons.append("unsafe_activation_detected")
    return list(dict.fromkeys(reasons))


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
