from __future__ import annotations

from typing import Any


MAX_CANDIDATE_BUDGET = 4


def resolve_visual_feedback_policy(
    feedback_report: dict[str, Any],
    *,
    wants_image: bool,
    wants_video: bool,
    explicit_candidate_budget: int | None,
    default_candidate_budget: int,
) -> dict[str, Any]:
    """Convert feedback-loop next_actions into runtime-safe generation policy."""

    if not wants_image:
        return {
            "candidate_budget": 0,
            "candidate_budget_source": "not_requested",
            "prefer_image_first_video": False,
            "rerank_before_delivery": False,
            "quality_repair_mode": "default",
            "applied_action_types": [],
        }

    budget_locked_by_user = explicit_candidate_budget is not None
    if budget_locked_by_user:
        candidate_budget = _clamp(explicit_candidate_budget or 1, minimum=1, maximum=MAX_CANDIDATE_BUDGET)
        candidate_budget_source = "user"
    else:
        candidate_budget = _clamp(default_candidate_budget, minimum=1, maximum=MAX_CANDIDATE_BUDGET)
        candidate_budget_source = "default"
    prefer_image_first_video = False
    rerank_before_delivery = False
    quality_repair_mode = "default"
    applied_action_types: list[str] = []

    for action in _next_actions(feedback_report):
        action_type = str(action.get("type") or "")
        if action_type == "increase_candidate_budget":
            value = _int(action.get("max_candidate_budget"))
            if not budget_locked_by_user and value is not None and value > candidate_budget:
                candidate_budget = _clamp(value, minimum=candidate_budget, maximum=MAX_CANDIDATE_BUDGET)
                candidate_budget_source = "feedback_loop"
                applied_action_types.append(action_type)
        elif action_type == "prefer_image_first_video" and wants_video:
            prefer_image_first_video = True
            applied_action_types.append(action_type)
        elif action_type == "rerank_before_slack":
            rerank_before_delivery = True
            applied_action_types.append(action_type)
        elif action_type == "prefer_quality_repair_retry":
            quality_repair_mode = "preferred"
            applied_action_types.append(action_type)
        elif action_type == "escalate_quality_repair_strategy":
            value = _int(action.get("max_candidate_budget"))
            if not budget_locked_by_user and value is not None and value > candidate_budget:
                candidate_budget = _clamp(value, minimum=candidate_budget, maximum=MAX_CANDIDATE_BUDGET)
                candidate_budget_source = "feedback_loop"
            quality_repair_mode = "escalated"
            applied_action_types.append(action_type)

    return {
        "candidate_budget": candidate_budget,
        "candidate_budget_source": candidate_budget_source,
        "prefer_image_first_video": prefer_image_first_video,
        "rerank_before_delivery": rerank_before_delivery,
        "quality_repair_mode": quality_repair_mode,
        "applied_action_types": applied_action_types,
    }


def _next_actions(feedback_report: dict[str, Any]) -> list[dict[str, Any]]:
    actions = feedback_report.get("next_actions")
    if not isinstance(actions, list):
        return []
    return [action for action in actions if isinstance(action, dict) and action.get("requires_human_feedback") is not True]


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))
