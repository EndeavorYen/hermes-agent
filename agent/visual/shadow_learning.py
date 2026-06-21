from __future__ import annotations

from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger


def record_shadow_update(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    intent_signature: str,
    strategy_signature: str,
    proposed_change: dict[str, Any],
    evidence: dict[str, Any],
    confidence: float | None = None,
    activation_status: str = "shadow",
) -> str:
    return ledger.record_shadow_update(
        request_id=request_id,
        intent_signature=intent_signature,
        strategy_signature=strategy_signature,
        proposed_change=proposed_change,
        evidence=evidence,
        confidence=confidence,
        activation_status="shadow" if activation_status != "disabled" else "shadow",
    )
