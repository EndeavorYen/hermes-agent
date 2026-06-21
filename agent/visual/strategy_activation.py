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
    return ledger.record_strategy_activation(
        shadow_update_id=shadow_update_id,
        intent_signature=intent_signature,
        strategy_signature=strategy_signature,
        activation_status=activation_status,
        promotion_decision=promotion_decision,
        rollback_of=rollback_of,
        metadata=metadata or {},
    )
