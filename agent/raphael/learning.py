"""Raphael learning dispatch helpers."""

from __future__ import annotations

from typing import Any, Mapping

from agent.learn_prompt import build_learn_prompt


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
