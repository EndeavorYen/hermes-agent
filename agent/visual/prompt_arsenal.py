from __future__ import annotations

from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger


APPROVED_PROMPT_ENTRY_TYPE = "approved_prompt_arsenal_entry"


def record_approved_prompt_arsenal_entry_for_feedback(
    ledger: VisualAttemptLedger,
    *,
    feedback_id: str,
) -> str | None:
    existing_id = _existing_entry_for_feedback(ledger, feedback_id)
    if existing_id:
        return existing_id
    feedback = ledger.get_feedback(feedback_id)
    if _coerce_float(feedback.get("polarity")) < 0.6:
        return None
    parsed = _dict_value(feedback, "parsed", "parsed_json")
    if _list_value(parsed.get("issues")):
        return None

    request_id = str(feedback.get("request_id") or "").strip()
    artifact_id = str(feedback.get("artifact_id") or "").strip()
    if not request_id or not artifact_id:
        return None

    artifact = ledger.get_artifact(artifact_id)
    attempt_id = str(artifact.get("attempt_id") or "").strip()
    if not attempt_id:
        return None
    attempt = ledger.get_attempt(attempt_id)
    prompt_mediated = str(attempt.get("prompt_mediated") or "").strip()
    if not prompt_mediated:
        return None

    request = ledger.get_request(request_id)
    ranking = _latest_ranking_for_request(ledger, request_id)
    intent_signature = _intent_signature(request, ranking)
    strategy_signature = _strategy_signature(ranking, attempt)
    request_category = _request_category(request)
    score = _selected_score(ranking)

    return ledger.record_shadow_update(
        request_id=request_id,
        intent_signature=intent_signature,
        strategy_signature=strategy_signature,
        proposed_change={
            "type": APPROVED_PROMPT_ENTRY_TYPE,
            "request_category": request_category,
            "prompt_role": "provider_ready_success_pattern",
            "activation_rule": "reuse_as_bounded_variant_for_similar_visual_requests",
        },
        evidence={
            "feedback_id": feedback_id,
            "artifact_id": artifact_id,
            "attempt_id": attempt_id,
            "prompt_mediated": prompt_mediated,
            "prompt_original": str(attempt.get("prompt_original") or "").strip(),
            "provider": str(attempt.get("provider") or "").strip(),
            "model": str(attempt.get("model") or "").strip(),
            "request_category": request_category,
            "score": score,
            "human_feedback": {
                "polarity": _coerce_float(feedback.get("polarity")),
                "signals": _list_value(parsed.get("signals")),
            },
        },
        confidence=min(0.95, max(0.65, _coerce_float(feedback.get("polarity")))),
        activation_status="shadow",
    )


def _existing_entry_for_feedback(ledger: VisualAttemptLedger, feedback_id: str) -> str | None:
    for row in reversed(ledger._list("visual_shadow_updates")):
        proposed = _dict_value(row, "proposed_change", "proposed_change_json")
        if proposed.get("type") != APPROVED_PROMPT_ENTRY_TYPE:
            continue
        evidence = _dict_value(row, "evidence", "evidence_json")
        if str(evidence.get("feedback_id") or "") == feedback_id:
            return str(row.get("id") or row.get("shadow_update_id") or "")
    return None


def approved_prompt_arsenal_entries(
    ledger: VisualAttemptLedger,
    *,
    request_category: str,
    limit: int = 2,
) -> list[dict[str, Any]]:
    category = str(request_category or "").strip()
    rows = ledger._list("visual_shadow_updates")
    entries: list[dict[str, Any]] = []
    for row in reversed(rows):
        proposed = _dict_value(row, "proposed_change", "proposed_change_json")
        if proposed.get("type") != APPROVED_PROMPT_ENTRY_TYPE:
            continue
        if category and str(proposed.get("request_category") or "").strip() != category:
            continue
        evidence = _dict_value(row, "evidence", "evidence_json")
        prompt = str(evidence.get("prompt_mediated") or "").strip()
        if not prompt:
            continue
        entries.append(
            {
                "prompt_mediated": prompt,
                "request_category": str(evidence.get("request_category") or proposed.get("request_category") or ""),
                "strategy_signature": str(row.get("strategy_signature") or ""),
                "confidence": _coerce_float(row.get("confidence")),
                "feedback_id": str(evidence.get("feedback_id") or ""),
                "artifact_id": str(evidence.get("artifact_id") or ""),
            }
        )
        if len(entries) >= max(1, int(limit)):
            break
    return entries


def _latest_ranking_for_request(ledger: VisualAttemptLedger, request_id: str) -> dict[str, Any]:
    rows = ledger._list("visual_rankings", where="request_id = ?", params=(request_id,))
    return rows[-1] if rows else {}


def _intent_signature(request: dict[str, Any], ranking: dict[str, Any]) -> str:
    ranking_meta = _dict_value(ranking, "metadata", "rationale_json")
    plan = ranking_meta.get("strategy_plan") if isinstance(ranking_meta.get("strategy_plan"), dict) else {}
    if plan.get("intent_signature"):
        return str(plan["intent_signature"])
    request_meta = _dict_value(request, "metadata", "policy_context_json")
    if request_meta.get("intent_signature"):
        return str(request_meta["intent_signature"])
    return "unknown"


def _strategy_signature(ranking: dict[str, Any], attempt: dict[str, Any]) -> str:
    ranking_meta = _dict_value(ranking, "metadata", "rationale_json")
    direct = ranking_meta.get("strategy_signature")
    if direct:
        return str(direct)
    plan = ranking_meta.get("strategy_plan") if isinstance(ranking_meta.get("strategy_plan"), dict) else {}
    if plan.get("strategy_signature"):
        return str(plan["strategy_signature"])
    for value in (
        attempt.get("parameters_requested"),
        attempt.get("parameters_requested_json"),
        attempt.get("parameters_effective"),
        attempt.get("parameters_effective_json"),
        attempt.get("metadata"),
    ):
        found = _find_nested_string(value, "strategy_signature")
        if found:
            return found
    return "unknown"


def _request_category(request: dict[str, Any]) -> str:
    normalized = _dict_value(request, "normalized_intent", "normalized_intent_json")
    return str(normalized.get("category") or "general")


def _selected_score(ranking: dict[str, Any]) -> float:
    scores = _dict_value(ranking, "scores", "score_json")
    for path in (("reward", "final_score"), ("selected", "final_score"), ("final_score",)):
        value: Any = scores
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        score = _coerce_float(value)
        if score > 0:
            return score
    return 0.0


def _dict_value(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _find_nested_string(value: Any, key: str) -> str | None:
    if isinstance(value, dict):
        found = value.get(key)
        if isinstance(found, str) and found:
            return found
        for nested in value.values():
            nested_found = _find_nested_string(nested, key)
            if nested_found:
                return nested_found
    if isinstance(value, list):
        for item in value:
            nested_found = _find_nested_string(item, key)
            if nested_found:
                return nested_found
    return None


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
