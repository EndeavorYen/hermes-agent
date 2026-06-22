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
            "provider_recovery_mode": "default",
            "provider_retry_budget": 1,
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
    quality_repair_modes = {"image": "default", "video": "default"}
    provider_recovery_mode = "default"
    provider_retry_budget = 1
    applied_action_types: list[str] = []
    repair_dimensions: list[dict[str, str]] = []

    for action in _next_actions(feedback_report):
        action_type = str(action.get("type") or "")
        if action_type == "increase_candidate_budget":
            value = _int(action.get("max_candidate_budget"))
            if not budget_locked_by_user and value is not None and value > candidate_budget:
                candidate_budget = _clamp(value, minimum=candidate_budget, maximum=MAX_CANDIDATE_BUDGET)
                candidate_budget_source = "feedback_loop"
                _append_once(applied_action_types, action_type)
        elif action_type == "prefer_image_first_video" and wants_video:
            prefer_image_first_video = True
            _append_once(applied_action_types, action_type)
        elif action_type == "rerank_before_slack":
            rerank_before_delivery = True
            _append_once(applied_action_types, action_type)
        elif action_type == "prefer_quality_repair_retry":
            quality_repair_mode = "preferred"
            _set_quality_repair_mode(quality_repair_modes, action, "preferred")
            _append_once(applied_action_types, action_type)
        elif action_type == "escalate_quality_repair_strategy":
            value = _int(action.get("max_candidate_budget"))
            if not budget_locked_by_user and value is not None and value > candidate_budget:
                candidate_budget = _clamp(value, minimum=candidate_budget, maximum=MAX_CANDIDATE_BUDGET)
                candidate_budget_source = "feedback_loop"
            quality_repair_mode = "escalated"
            _set_quality_repair_mode(quality_repair_modes, action, "escalated")
            _append_once(applied_action_types, action_type)
        elif action_type == "repair_low_preference_dimension":
            if not budget_locked_by_user and candidate_budget < 2:
                candidate_budget = 2
                candidate_budget_source = "feedback_loop"
            rerank_before_delivery = True
            quality_repair_mode = "preferred"
            _set_quality_repair_mode(quality_repair_modes, action, "preferred")
            _append_once(applied_action_types, action_type)
            _append_repair_dimension(repair_dimensions, action)
        elif action_type == "safe_reframe_provider_retry":
            provider_recovery_mode = "safe_reframe"
            provider_retry_budget = 2
            _append_once(applied_action_types, action_type)

    return {
        "candidate_budget": candidate_budget,
        "candidate_budget_source": candidate_budget_source,
        "prefer_image_first_video": prefer_image_first_video,
        "rerank_before_delivery": rerank_before_delivery,
        "quality_repair_mode": quality_repair_mode,
        "quality_repair_modes": quality_repair_modes,
        "provider_recovery_mode": provider_recovery_mode,
        "provider_retry_budget": provider_retry_budget,
        "repair_dimensions": repair_dimensions,
        "applied_action_types": applied_action_types,
        "policy_sources": _string_list(feedback_report.get("policy_sources")) or ["feedback_loop"],
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


def _append_once(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _set_quality_repair_mode(modes: dict[str, str], action: dict[str, Any], mode: str) -> None:
    modalities = _action_modalities(action)
    if not modalities:
        modalities = ["image", "video"]
    for modality in modalities:
        modes[modality] = mode


def _append_repair_dimension(values: list[dict[str, str]], action: dict[str, Any]) -> None:
    dimension = str(action.get("dimension") or "").strip()
    if not dimension:
        return
    entry = {
        "dimension": dimension,
        "quality_issue": str(action.get("quality_issue") or "").strip(),
        "repair_hint": str(action.get("repair_hint") or "").strip(),
    }
    if any(item.get("dimension") == dimension for item in values):
        return
    values.append(entry)


def _action_modalities(action: dict[str, Any]) -> list[str]:
    value = action.get("modalities")
    if not isinstance(value, list):
        value = [action.get("modality")]
    modalities: list[str] = []
    for item in value:
        text = str(item or "").strip().lower()
        if text in {"image", "video"} and text not in modalities:
            modalities.append(text)
    return modalities


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]
