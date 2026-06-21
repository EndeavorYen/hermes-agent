from __future__ import annotations

from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger


_SUPPORTED_STATUSES = {"controlled", "disabled", "rolled_back"}


def record_strategy_activation(
    ledger: VisualAttemptLedger,
    *,
    shadow_update_id: str,
    intent_signature: str,
    strategy_signature: str,
    activation_status: str,
    promotion_decision: dict[str, Any],
    rollback_of: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    if activation_status not in _SUPPORTED_STATUSES:
        raise ValueError(f"unsupported activation_status: {activation_status}")
    if activation_status == "controlled" and _prompt_mutation_requested(
        promotion_decision=promotion_decision,
        metadata=metadata,
    ):
        raise ValueError("controlled strategy activation must be read-only")
    return ledger.record_strategy_activation(
        shadow_update_id=shadow_update_id,
        intent_signature=intent_signature,
        strategy_signature=strategy_signature,
        activation_status=activation_status,
        promotion_decision=promotion_decision,
        rollback_of=rollback_of,
        metadata=metadata or {},
    )


def _prompt_mutation_requested(
    *,
    promotion_decision: dict[str, Any],
    metadata: dict[str, Any] | None,
) -> bool:
    if isinstance(metadata, dict) and metadata.get("prompt_mutation_allowed") is True:
        return True
    observed = promotion_decision.get("observed") if isinstance(promotion_decision, dict) else None
    if isinstance(observed, dict) and observed.get("prompt_mutation_allowed") is True:
        return True
    return promotion_decision.get("prompt_mutation_allowed") is True
