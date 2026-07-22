from __future__ import annotations

from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.shadow_learning import record_shadow_update
from agent.visual.strategy_activation import record_strategy_activation
from agent.visual.strategy_policy import GLOBAL_VISUAL_AGENT_INTENT_SIGNATURE


def activate_ready_visual_promotion(
    ledger: VisualAttemptLedger,
    status: dict[str, Any],
) -> dict[str, Any]:
    readiness = status.get("promotion_readiness") if isinstance(status.get("promotion_readiness"), dict) else {}
    candidate = readiness.get("candidate") if isinstance(readiness.get("candidate"), dict) else {}
    if readiness.get("ready") is not True:
        reasons = _strings(readiness.get("blocking_reasons")) or ["promotion_readiness_not_ready"]
        return _result(
            activated_count=0,
            blocked_count=1,
            skipped_count=0,
            activation_ids=[],
            decisions=[{"decision": "blocked", "allowed": False, "reasons": reasons}],
        )

    intent_signature = _intent_signature(candidate)
    strategy_signature = str(candidate.get("strategy_signature") or "").strip()
    missing = [
        name
        for name, value in (
            ("intent_signature", intent_signature),
            ("strategy_signature", strategy_signature),
        )
        if not value
    ]
    if missing:
        return _result(
            activated_count=0,
            blocked_count=1,
            skipped_count=0,
            activation_ids=[],
            decisions=[
                {
                    "decision": "blocked",
                    "allowed": False,
                    "reasons": [f"missing_activation_fields:{','.join(missing)}"],
                }
            ],
        )

    existing = _existing_controlled_activation(
        ledger,
        intent_signature=intent_signature,
        strategy_signature=strategy_signature,
    )
    if existing:
        return _result(
            activated_count=0,
            blocked_count=0,
            skipped_count=1,
            activation_ids=[],
            decisions=[
                {
                    "decision": "skipped",
                    "allowed": True,
                    "reason": "strategy_already_controlled",
                    "activation_id": str(existing.get("id") or ""),
                }
            ],
        )

    request_id = ledger.record_request(
        user_prompt="[visual promotion readiness activation]",
        normalized_intent={
            "operation": "visual_strategy_promotion",
            "source": "visual_self_validation_status",
            "run_id": status.get("run_id"),
        },
        modality="policy",
        operation="visual_strategy_promotion",
        status="completed",
        metadata={
            "privacy_safe": True,
            "prompt_mutation_allowed": False,
            "promotion_readiness_run_id": status.get("run_id"),
        },
    )
    shadow_update_id = record_shadow_update(
        ledger,
        request_id=request_id,
        intent_signature=intent_signature,
        strategy_signature=strategy_signature,
        proposed_change=_proposed_change(candidate),
        evidence=_evidence(status, readiness=readiness),
        confidence=_float(candidate.get("confidence")),
    )
    decision = _promotion_decision(status, readiness=readiness, candidate=candidate)
    activation_id = record_strategy_activation(
        ledger,
        shadow_update_id=shadow_update_id,
        intent_signature=intent_signature,
        strategy_signature=strategy_signature,
        activation_status="controlled",
        promotion_decision=decision,
        metadata={
            "source": "promotion_readiness_activation",
            "scope": "global_visual_agent_mode"
            if intent_signature == GLOBAL_VISUAL_AGENT_INTENT_SIGNATURE
            else "intent_signature",
            "promotion_readiness_run_id": status.get("run_id"),
            "prompt_mutation_allowed": False,
        },
    )
    return _result(
        activated_count=1,
        blocked_count=0,
        skipped_count=0,
        activation_ids=[activation_id],
        decisions=[
            {
                "decision": "promote_controlled",
                "allowed": True,
                "activation_id": activation_id,
                "reasons": [],
            }
        ],
    )


def _existing_controlled_activation(
    ledger: VisualAttemptLedger,
    *,
    intent_signature: str,
    strategy_signature: str,
) -> dict[str, Any] | None:
    for row in reversed(
        ledger.list_strategy_activations(
            intent_signature=intent_signature,
            strategy_signature=strategy_signature,
        )
    ):
        if row.get("activation_status") != "controlled":
            continue
        decision = row.get("promotion_decision")
        if isinstance(decision, dict) and decision.get("allowed") is True:
            return row
    return None


def _intent_signature(candidate: dict[str, Any]) -> str:
    value = str(candidate.get("intent_signature") or candidate.get("bucket") or "").strip()
    return value


def _proposed_change(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "prefer_strategy",
        "source": str(candidate.get("source") or "promotion_readiness"),
        "track": str(candidate.get("track") or ""),
        "strategy_signature": str(candidate.get("strategy_signature") or ""),
        "activation_status": "shadow",
        "prompt_mutation_allowed": False,
    }


def _evidence(status: dict[str, Any], *, readiness: dict[str, Any]) -> dict[str, Any]:
    live = status.get("live") if isinstance(status.get("live"), dict) else {}
    delivery = status.get("delivery") if isinstance(status.get("delivery"), dict) else {}
    return {
        "run_id": status.get("run_id"),
        "generated_at": status.get("generated_at"),
        "health_status": status.get("health_status"),
        "live_e2e_ran": status.get("live_e2e_ran") is True,
        "live_quality_burn_success": live.get("burn_success") is True,
        "live_quality_burn_case_count": _int(live.get("burn_case_count")),
        "live_quality_burn_min_score": _float(live.get("burn_min_score")),
        "image_first_video_source_covered": live.get("image_first_video_source_covered") is True,
        "native_video_upload_covered": delivery.get("native_video_upload_covered") is True,
        "live_conversation_quality_run_count": _int(live.get("conversation_quality_run_count")),
        "live_conversation_quality_recent_avg_min_quality_score": _float(
            live.get("conversation_quality_recent_avg_min_quality_score")
        ),
        "live_conversation_native_video_upload_covered": _int(
            live.get("conversation_quality_native_video_upload_covered_count")
        )
        > 0,
        "live_conversation_native_video_upload_covered_count": _int(
            live.get("conversation_quality_native_video_upload_covered_count")
        ),
        "live_conversation_image_first_video_source_failure_count": _int(
            live.get("conversation_quality_image_first_video_source_failure_count")
        ),
        "live_conversation_provider_failure_count": _int(
            live.get("conversation_quality_provider_failure_count")
        ),
        "duplicate_delivery_count": _int(delivery.get("duplicate_delivery_count")),
        "thresholds": readiness.get("thresholds") if isinstance(readiness.get("thresholds"), dict) else {},
    }


def _promotion_decision(
    status: dict[str, Any],
    *,
    readiness: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    live = status.get("live") if isinstance(status.get("live"), dict) else {}
    delivery = status.get("delivery") if isinstance(status.get("delivery"), dict) else {}
    return {
        "decision": "promote_controlled",
        "allowed": True,
        "confidence": _float(candidate.get("confidence")),
        "reasons": [],
        "source": "promotion_readiness",
        "required": readiness.get("thresholds") if isinstance(readiness.get("thresholds"), dict) else {},
        "observed": {
            "health_status": status.get("health_status"),
            "live_e2e_ran": status.get("live_e2e_ran") is True,
            "live_quality_burn_success": live.get("burn_success") is True,
            "live_quality_burn_case_count": _int(live.get("burn_case_count")),
            "live_quality_burn_min_score": _float(live.get("burn_min_score")),
            "image_first_video_source_covered": live.get("image_first_video_source_covered") is True,
            "native_video_upload_covered": delivery.get("native_video_upload_covered") is True,
            "live_conversation_quality_run_count": _int(live.get("conversation_quality_run_count")),
            "live_conversation_quality_recent_avg_min_quality_score": _float(
                live.get("conversation_quality_recent_avg_min_quality_score")
            ),
            "live_conversation_native_video_upload_covered": _int(
                live.get("conversation_quality_native_video_upload_covered_count")
            )
            > 0,
            "live_conversation_native_video_upload_covered_count": _int(
                live.get("conversation_quality_native_video_upload_covered_count")
            ),
            "live_conversation_image_first_video_source_failure_count": _int(
                live.get("conversation_quality_image_first_video_source_failure_count")
            ),
            "live_conversation_provider_failure_count": _int(
                live.get("conversation_quality_provider_failure_count")
            ),
            "duplicate_delivery_count": _int(delivery.get("duplicate_delivery_count")),
            "prompt_mutation_allowed": False,
        },
        "prompt_mutation_allowed": False,
    }


def _result(
    *,
    activated_count: int,
    blocked_count: int,
    skipped_count: int,
    activation_ids: list[str],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "success": blocked_count == 0,
        "activated_count": activated_count,
        "blocked_count": blocked_count,
        "skipped_count": skipped_count,
        "activation_ids": activation_ids,
        "decisions": decisions,
        "self_review": {
            "privacy_safe": True,
            "prompt_mutation_allowed": False,
            "audit_chain_recorded": activated_count > 0,
            "reduces_human_intervention": activated_count > 0 or skipped_count > 0,
        },
    }


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return 0.0
