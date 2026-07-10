from __future__ import annotations

from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.autonomous_rollout import evaluate_autonomous_rollout_candidate
from agent.visual.strategy_activation import record_strategy_activation


def activate_controlled_visual_candidates(
    ledger: VisualAttemptLedger,
    proposals: list[dict[str, Any]],
    *,
    runtime_checks: dict[str, Any],
    autonomy_level: int,
    operator_approved: bool = False,
) -> dict[str, Any]:
    activation_ids: list[str] = []
    decisions: list[dict[str, Any]] = []
    blocked_count = 0
    for proposal in proposals:
        decision = evaluate_autonomous_rollout_candidate(
            proposal,
            runtime_checks=runtime_checks,
            autonomy_level=autonomy_level,
        )
        shadow_update_id = str(proposal.get("shadow_update_id") or "")
        intent_signature = str(proposal.get("bucket") or proposal.get("intent_signature") or "")
        strategy_signature = str(proposal.get("strategy_signature") or "")
        missing_fields = [
            field
            for field, value in (
                ("shadow_update_id", shadow_update_id),
                ("intent_signature", intent_signature),
                ("strategy_signature", strategy_signature),
            )
            if not value
        ]
        if missing_fields:
            decision = {
                **decision,
                "allowed": False,
                "decision": "shadow_only",
                "activation_status": "shadow",
                "reasons": [*decision.get("reasons", []), f"missing_activation_fields:{','.join(missing_fields)}"],
            }
        if not operator_approved and decision.get("allowed") is True:
            decision = {
                **decision,
                "allowed": False,
                "decision": "shadow_only",
                "activation_status": "shadow",
                "reasons": [*decision.get("reasons", []), "operator_approval_required"],
            }

        if decision.get("allowed") is not True:
            decisions.append(decision)
            blocked_count += 1
            continue

        try:
            activation_id = record_strategy_activation(
                ledger,
                shadow_update_id=shadow_update_id,
                intent_signature=intent_signature,
                strategy_signature=strategy_signature,
                activation_status="controlled",
                promotion_decision={**decision, "decision": "promote_controlled"},
                metadata={
                    "source": "controlled_activation_runner",
                    "proposal_type": decision.get("proposal_type"),
                    "prompt_mutation_allowed": proposal.get("prompt_mutation_allowed") is True,
                },
            )
        except ValueError as exc:
            blocked = {
                **decision,
                "allowed": False,
                "decision": "shadow_only",
                "activation_status": "shadow",
                "reasons": [*decision.get("reasons", []), str(exc)],
            }
            decisions.append(blocked)
            blocked_count += 1
            continue

        activation_ids.append(activation_id)
        decisions.append({**decision, "decision": "promote_controlled", "activation_id": activation_id})

    return {
        "success": True,
        "activated_count": len(activation_ids),
        "blocked_count": blocked_count,
        "activation_ids": activation_ids,
        "decisions": decisions,
    }
