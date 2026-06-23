from __future__ import annotations

from typing import Any

from agent.visual.operator_setup import operator_setup_actions_from_action


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

    budget_locked_by_user = explicit_candidate_budget is not None
    if wants_image and budget_locked_by_user:
        candidate_budget = _clamp(explicit_candidate_budget or 1, minimum=1, maximum=MAX_CANDIDATE_BUDGET)
        candidate_budget_source = "user"
    elif wants_image:
        candidate_budget = _clamp(default_candidate_budget, minimum=1, maximum=MAX_CANDIDATE_BUDGET)
        candidate_budget_source = "default"
    else:
        candidate_budget = 0
        candidate_budget_source = "not_requested"
    prefer_image_first_video = False
    rerank_before_delivery = False
    quality_repair_mode = "default"
    quality_repair_modes = {"image": "default", "video": "default"}
    provider_recovery_mode = "default"
    provider_retry_budget = 1
    provider_failure_context = {
        "provider_failure_classes": {},
        "provider_error_codes": {},
    }
    enforce_single_video_source_image = False
    enforce_video_source_aspect_ratio = False
    video_fallback_diagnostics: list[dict[str, Any]] = []
    operator_setup_actions: list[dict[str, Any]] = []
    strategy_preference: dict[str, Any] | None = None
    applied_action_types: list[str] = []
    applied_action_sources: list[str] = []
    repair_dimensions: list[dict[str, str]] = []
    quality_focus_operators: list[dict[str, str]] = []
    require_preference_dimension_evidence = False
    required_preference_dimensions: list[str] = []

    for action in _next_actions(feedback_report):
        action_type = str(action.get("type") or "")
        action_source = _action_source(action)
        if action_type == "increase_candidate_budget":
            value = _int(action.get("max_candidate_budget"))
            if wants_image and not budget_locked_by_user and value is not None and value > candidate_budget:
                candidate_budget = _clamp(value, minimum=candidate_budget, maximum=MAX_CANDIDATE_BUDGET)
                candidate_budget_source = action_source
                _append_once(applied_action_types, action_type)
                _append_once(applied_action_sources, action_source)
        elif action_type == "prefer_image_first_video" and wants_video:
            prefer_image_first_video = True
            rerank_before_delivery = True
            if candidate_budget < 2:
                candidate_budget = 2 if not budget_locked_by_user else _clamp(
                    explicit_candidate_budget or 1,
                    minimum=1,
                    maximum=MAX_CANDIDATE_BUDGET,
                )
                candidate_budget_source = action_source if not budget_locked_by_user else "user"
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "rerank_before_slack":
            rerank_before_delivery = True
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "prefer_quality_repair_retry":
            quality_repair_mode = "preferred"
            _set_quality_repair_mode(quality_repair_modes, action, "preferred")
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "escalate_quality_repair_strategy":
            value = _int(action.get("max_candidate_budget"))
            if not budget_locked_by_user and value is not None and value > candidate_budget:
                candidate_budget = _clamp(value, minimum=candidate_budget, maximum=MAX_CANDIDATE_BUDGET)
                candidate_budget_source = action_source
            quality_repair_mode = "escalated"
            _set_quality_repair_mode(quality_repair_modes, action, "escalated")
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "repair_low_preference_dimension":
            if not budget_locked_by_user and candidate_budget < 2:
                candidate_budget = 2
                candidate_budget_source = action_source
            rerank_before_delivery = True
            quality_repair_mode = "preferred"
            _set_quality_repair_mode(quality_repair_modes, action, "preferred")
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
            _append_repair_dimension(repair_dimensions, action)
        elif action_type == "apply_quality_focus_operator":
            if wants_image and not budget_locked_by_user and candidate_budget < 2:
                candidate_budget = 2
                candidate_budget_source = action_source
            rerank_before_delivery = True
            quality_repair_mode = "preferred"
            _set_quality_repair_mode(quality_repair_modes, {"modality": "image"}, "preferred")
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
            _append_repair_dimension(repair_dimensions, action)
            _append_quality_focus_operator(quality_focus_operators, action)
        elif action_type == "require_preference_dimension_evidence":
            require_preference_dimension_evidence = True
            _append_required_preference_dimension(required_preference_dimensions, action)
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "enforce_single_video_source_image" and wants_video:
            enforce_single_video_source_image = True
            prefer_image_first_video = True
            rerank_before_delivery = True
            quality_repair_mode = "preferred"
            _set_quality_repair_mode(quality_repair_modes, {"modality": "video"}, "preferred")
            if wants_image and not budget_locked_by_user and candidate_budget < 2:
                candidate_budget = 2
                candidate_budget_source = action_source
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "enforce_video_source_aspect_ratio" and wants_video:
            enforce_video_source_aspect_ratio = True
            prefer_image_first_video = True
            rerank_before_delivery = True
            quality_repair_mode = "preferred"
            _set_quality_repair_mode(quality_repair_modes, {"modality": "video"}, "preferred")
            if wants_image and not budget_locked_by_user and candidate_budget < 2:
                candidate_budget = 2
                candidate_budget_source = action_source
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "safe_reframe_provider_retry":
            provider_recovery_mode = "safe_reframe"
            provider_retry_budget = 2
            provider_failure_context = _provider_failure_context(action)
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "check_provider_connectivity_or_retry":
            provider_recovery_mode = "provider_connectivity_retry"
            provider_retry_budget = 1
            provider_failure_context = _provider_failure_context(action)
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "resolve_provider_quota_or_switch_provider":
            provider_recovery_mode = "provider_account_blocked"
            provider_retry_budget = 0
            provider_failure_context = _provider_failure_context(action)
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "configure_video_fallback_provider":
            provider_recovery_mode = "video_fallback_unavailable"
            provider_retry_budget = 0
            provider_failure_context = _provider_failure_context(action)
            video_fallback_diagnostics = _dict_list(action.get("video_fallback_diagnostics"))
            operator_setup_actions = operator_setup_actions_from_action(action)
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "configure_visual_judge_provider":
            operator_setup_actions = operator_setup_actions_from_action(action)
            _append_once(applied_action_types, action_type)
            _append_once(applied_action_sources, action_source)
        elif action_type == "prefer_strategy":
            preference = _strategy_preference(action)
            if preference:
                strategy_preference = preference
                if wants_video and preference.get("strategy_signature") == "image_first_rank_then_video":
                    prefer_image_first_video = True
                    rerank_before_delivery = True
                    preferred_budget = _int(preference.get("candidate_budget"))
                    if not budget_locked_by_user and preferred_budget is not None:
                        candidate_budget = _clamp(preferred_budget, minimum=1, maximum=MAX_CANDIDATE_BUDGET)
                        candidate_budget_source = str(preference.get("source") or "feedback_loop").strip() or "feedback_loop"
                    elif not budget_locked_by_user and candidate_budget < 2:
                        candidate_budget = 2
                        candidate_budget_source = "feedback_loop"
                _append_once(applied_action_types, action_type)
                _append_once(applied_action_sources, action_source)

    return {
        "candidate_budget": candidate_budget,
        "candidate_budget_source": candidate_budget_source,
        "prefer_image_first_video": prefer_image_first_video,
        "rerank_before_delivery": rerank_before_delivery,
        "quality_repair_mode": quality_repair_mode,
        "quality_repair_modes": quality_repair_modes,
        "provider_recovery_mode": provider_recovery_mode,
        "provider_retry_budget": provider_retry_budget,
        "provider_failure_context": provider_failure_context,
        "enforce_single_video_source_image": enforce_single_video_source_image,
        "enforce_video_source_aspect_ratio": enforce_video_source_aspect_ratio,
        "video_fallback_diagnostics": video_fallback_diagnostics,
        "requires_operator_setup": bool(operator_setup_actions),
        "operator_setup_actions": operator_setup_actions,
        "strategy_preference": strategy_preference,
        "repair_dimensions": repair_dimensions,
        "quality_focus_operators": quality_focus_operators,
        "require_preference_dimension_evidence": require_preference_dimension_evidence,
        "required_preference_dimensions": required_preference_dimensions,
        "applied_action_types": applied_action_types,
        "applied_action_sources": applied_action_sources,
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
        "quality_issue": _action_quality_issue(action),
        "repair_hint": str(action.get("repair_hint") or "").strip(),
    }
    action_source = _action_source(action)
    if action_source == "live_quality_trends":
        entry["source"] = action_source
    if any(item.get("dimension") == dimension for item in values):
        return
    values.append(entry)


def _append_quality_focus_operator(values: list[dict[str, str]], action: dict[str, Any]) -> None:
    focus = str(action.get("focus") or "").strip()
    operator = str(action.get("strategy_operator") or "").strip()
    if not focus or not operator:
        return
    entry = {
        "focus": focus,
        "dimension": str(action.get("dimension") or "").strip(),
        "strategy_operator": operator,
        "source": _action_source(action),
    }
    if any(
        item.get("focus") == entry["focus"]
        and item.get("strategy_operator") == entry["strategy_operator"]
        for item in values
    ):
        return
    values.append(entry)


def _append_required_preference_dimension(values: list[str], action: dict[str, Any]) -> None:
    dimension = str(action.get("dimension") or "").strip()
    if dimension and dimension not in values:
        values.append(dimension)


def _action_quality_issue(action: dict[str, Any]) -> str:
    issue = str(action.get("quality_issue") or "").strip()
    if issue:
        return issue
    issues = action.get("quality_issues")
    if not isinstance(issues, list):
        return ""
    for item in issues:
        text = str(item or "").strip()
        if text:
            return text
    return ""


def _strategy_preference(action: dict[str, Any]) -> dict[str, Any] | None:
    strategy_signature = str(action.get("strategy_signature") or "").strip()
    if not strategy_signature:
        return None
    return {
        "strategy_signature": strategy_signature,
        "source": str(action.get("source") or "").strip(),
        "bucket": str(action.get("bucket") or action.get("intent_signature") or "").strip(),
        "activation_status": str(action.get("activation_status") or "shadow").strip() or "shadow",
        "confidence": _float(action.get("confidence")),
        "candidate_budget": _int(action.get("candidate_budget")),
        "prompt_mutation_allowed": False,
    }


def _provider_failure_context(action: dict[str, Any]) -> dict[str, dict[str, int]]:
    return {
        "provider_failure_classes": _int_mapping(action.get("provider_failure_classes")),
        "provider_error_codes": _int_mapping(action.get("provider_error_codes")),
    }


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _action_source(action: dict[str, Any]) -> str:
    source = str(action.get("source") or "").strip()
    return source or "feedback_loop"


def _action_modalities(action: dict[str, Any]) -> list[str]:
    value = action.get("modalities")
    if not isinstance(value, list):
        value = [action.get("modality")]
    modalities: list[str] = []
    for item in value:
        text = str(item or "").strip().lower()
        if text in {"image", "video"} and text not in modalities:
            modalities.append(text)
    if modalities:
        return modalities
    return _dimension_modalities(action)


def _dimension_modalities(action: dict[str, Any]) -> list[str]:
    dimension = str(action.get("dimension") or "").strip().lower()
    quality_issue = str(action.get("quality_issue") or "").strip().lower()
    issues = [str(item or "").strip().lower() for item in action.get("quality_issues") or []]
    video_signals = {
        "aspect_integrity",
        "motion_quality",
        "aspect_integrity_bad",
        "motion_bad",
        "video_metadata_missing",
        "duration_mismatch",
    }
    if dimension in video_signals or quality_issue in video_signals or any(issue in video_signals for issue in issues):
        return ["video"]
    image_signals = {
        "subject_beauty",
        "face_naturalness",
        "glamour_impact",
        "fashion_material_quality",
        "pose_composition",
        "subject_not_attractive",
        "not_beautiful",
        "face_unnatural",
        "stockings_bad",
        "composition_bad",
        "reference_identity_drift",
    }
    if dimension in image_signals or quality_issue in image_signals or any(issue in image_signals for issue in issues):
        return ["image"]
    return []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _float(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return 0.0


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    mapping: dict[str, int] = {}
    for key, count in value.items():
        text = str(key or "").strip()
        parsed = _int(count)
        if text and parsed is not None and parsed > 0:
            mapping[text] = parsed
    return mapping
