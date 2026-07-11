"""Raphael learning dispatch helpers."""

from __future__ import annotations

from typing import Any, Mapping

from agent.learn_prompt import build_learn_prompt


_OUTCOME_CONTRACT_REQUIRED_FIELDS = (
    "failure_cluster_id",
    "component",
    "owner",
    "occurrence_id",
    "replay_command",
    "baseline_metric",
    "target_metric",
)


def normalize_learning_outcome_contract(
    metadata: Mapping[str, object] | None,
) -> dict[str, str] | None:
    if not isinstance(metadata, Mapping):
        return None
    contract = {
        key: " ".join(str(metadata.get(key) or "").split())
        for key in (
            "origin",
            *_OUTCOME_CONTRACT_REQUIRED_FIELDS,
            "signal_kind",
            "approval_class",
            "failure_class",
        )
    }
    if contract["origin"] != "foreground":
        return None
    if any(not contract[field] for field in _OUTCOME_CONTRACT_REQUIRED_FIELDS):
        return None
    contract["approval_class"] = contract["approval_class"] or "R2"
    return {key: value for key, value in contract.items() if value}


def build_raphael_learning_dispatch(
    decision: Any,
    user_request: str,
) -> Mapping[str, object]:
    if getattr(decision, "mode", "") != "learn_skill":
        raise ValueError("Raphael learning dispatch requires mode='learn_skill'")
    required = list(
        getattr(getattr(decision, "evidence", None), "required_proofs", ()) or ()
    )
    return {
        "type": "send",
        "message": build_learn_prompt(user_request),
        "required_proofs": required,
    }


def recommend_post_learning_actions(record: Mapping[str, object]) -> list[dict[str, str]]:
    if str(record.get("skill_name") or "").strip():
        return [
            {
                "command": "skills.reload",
                "reason": "new skill should be visible in the gateway process",
            }
        ]
    return []


__all__ = [
    "build_raphael_learning_dispatch",
    "normalize_learning_outcome_contract",
    "recommend_post_learning_actions",
]
