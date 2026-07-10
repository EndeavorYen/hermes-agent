from __future__ import annotations

import hashlib
import re
from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger


APPROVED_PROMPT_ENTRY_TYPE = "approved_prompt_arsenal_entry"
PROMPT_DRAFT_ENTRY_SOURCE = "prompt_only_visual_agent"


def record_prompt_draft_arsenal_entry(
    ledger: VisualAttemptLedger,
    *,
    user_prompt: str,
    prompt_response: str,
    platform: str = "",
    channel_id: str = "",
    thread_id: str = "",
    message_id: str = "",
) -> str | None:
    """Record a prompt-only visual-agent response as reusable prompt arsenal evidence."""

    original = str(user_prompt or "").strip()
    mediated = str(prompt_response or "").strip()
    if len(original) < 8 or len(mediated) < 32:
        return None
    if _looks_like_prompt_disclosure_response(mediated):
        return None

    ledger.initialize()
    fingerprint = _prompt_draft_fingerprint(original, mediated)
    existing_id = _existing_prompt_draft_entry(ledger, fingerprint)
    if existing_id:
        return existing_id

    request_category = _prompt_request_category(original)
    request_id = ledger.record_request(
        user_prompt=original,
        normalized_intent={
            "kind": "visual_prompt_draft",
            "category": request_category,
            "learning_source": PROMPT_DRAFT_ENTRY_SOURCE,
        },
        modality="prompt",
        operation="visual_prompt_draft",
        platform=str(platform or "").strip(),
        channel_id=str(channel_id or "").strip(),
        thread_id=str(thread_id or "").strip(),
        message_id=str(message_id or "").strip(),
        status="completed",
        metadata={
            "source": PROMPT_DRAFT_ENTRY_SOURCE,
            "prompt_draft_fingerprint": fingerprint,
        },
    )
    return ledger.record_shadow_update(
        request_id=request_id,
        intent_signature=f"prompt_draft:{request_category}",
        strategy_signature=f"prompt_draft_response@v1:{fingerprint[:12]}",
        proposed_change={
            "type": APPROVED_PROMPT_ENTRY_TYPE,
            "request_category": request_category,
            "prompt_role": "prompt_only_success_pattern",
            "activation_rule": "reuse_as_bounded_variant_for_similar_visual_requests",
        },
        evidence={
            "prompt_original": original,
            "prompt_mediated": mediated,
            "request_category": request_category,
            "source": PROMPT_DRAFT_ENTRY_SOURCE,
            "prompt_draft_fingerprint": fingerprint,
            "platform": str(platform or "").strip(),
            "channel_id": str(channel_id or "").strip(),
            "thread_id": str(thread_id or "").strip(),
            "message_id": str(message_id or "").strip(),
        },
        confidence=0.72,
        activation_status="shadow",
    )


def prompt_requests_arsenal_lookup(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    return any(
        marker in compact
        for marker in (
            "翻prompt庫",
            "翻prompt库",
            "翻提示詞庫",
            "翻提示词库",
            "查prompt庫",
            "查prompt库",
            "看prompt庫",
            "看prompt库",
            "使用prompt庫",
            "使用prompt库",
            "使用提示詞庫",
            "使用提示词库",
            "套用prompt庫",
            "套用prompt库",
            "套用prompt武器庫",
            "套用prompt武器库",
            "prompt武器庫",
            "prompt武器库",
            "產圖prompt庫",
            "产图prompt库",
            "生圖prompt庫",
            "生图prompt库",
        )
    ) or any(
        marker in text
        for marker in (
            "prompt arsenal",
            "visual prompt arsenal",
            "use prompt arsenal",
            "use the prompt arsenal",
        )
    )


def build_prompt_arsenal_context(
    ledger: VisualAttemptLedger,
    prompt: str,
    *,
    limit: int = 3,
) -> str:
    """Build a short user-message context block from learned prompt patterns."""

    if not prompt_requests_arsenal_lookup(prompt):
        return ""
    ledger.initialize()
    category = _prompt_request_category(prompt)
    entries = approved_prompt_arsenal_entries(
        ledger,
        request_category=category,
        limit=limit,
    )
    if not entries and category != "general":
        entries = approved_prompt_arsenal_entries(
            ledger,
            request_category="general",
            limit=limit,
        )
    if not entries:
        return ""

    lines = [
        "[Visual Prompt Arsenal]",
        (
            "Use these prior approved prompt patterns as inspiration only. "
            "Preserve the current user request, current reference mapping, and provider choice. "
            "Do not copy stale subject details, old role assignments, or obsolete composition constraints."
        ),
    ]
    for index, entry in enumerate(entries[: max(1, int(limit))], start=1):
        confidence = _coerce_float(entry.get("confidence"))
        prompt_excerpt = _safe_prompt_excerpt(str(entry.get("prompt_mediated") or ""), max_chars=480)
        if not prompt_excerpt:
            continue
        role = str(entry.get("prompt_role") or "approved_prompt_pattern")
        entry_category = str(entry.get("request_category") or category or "general")
        lines.append(f"{index}. category={entry_category}; role={role}; confidence={confidence:.2f}; pattern={prompt_excerpt}")
    return "\n".join(lines) if len(lines) > 2 else ""


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
                "prompt_role": str(proposed.get("prompt_role") or ""),
            }
        )
        if len(entries) >= max(1, int(limit)):
            break
    return entries


def _existing_prompt_draft_entry(ledger: VisualAttemptLedger, fingerprint: str) -> str | None:
    for row in reversed(ledger._list("visual_shadow_updates")):
        proposed = _dict_value(row, "proposed_change", "proposed_change_json")
        if proposed.get("type") != APPROVED_PROMPT_ENTRY_TYPE:
            continue
        evidence = _dict_value(row, "evidence", "evidence_json")
        if str(evidence.get("source") or "") != PROMPT_DRAFT_ENTRY_SOURCE:
            continue
        if str(evidence.get("prompt_draft_fingerprint") or "") == fingerprint:
            return str(row.get("id") or row.get("shadow_update_id") or "")
    return None


def _prompt_draft_fingerprint(original: str, mediated: str) -> str:
    normalized = "\n".join((_clean_for_fingerprint(original), _clean_for_fingerprint(mediated)))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _clean_for_fingerprint(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _looks_like_prompt_disclosure_response(response: str) -> bool:
    text = str(response or "").strip().lower()
    compact = re.sub(r"\s+", "", text)
    return any(
        marker in compact
        for marker in (
            "上一輪可追溯的visualprompt",
            "上一轮可追溯的visualprompt",
            "實際送進image/videoprovider的prompt",
            "实际送进image/videoprovider的prompt",
            "我目前找不到上一輪可追溯的visualprompt",
            "我目前找不到上一轮可追溯的visualprompt",
        )
    ) or "provider / model:" in text


def _prompt_request_category(prompt: str) -> str:
    text = str(prompt or "").strip().lower()
    compact = re.sub(r"\s+", "", text)
    if any(
        marker in text
        for marker in (
            "anime",
            "gacha",
            "genshin",
            "fox",
            "elf",
            "character",
            "2d",
            "manga",
        )
    ) or any(
        marker in compact
        for marker in (
            "動漫",
            "动漫",
            "角色",
            "狐耳",
            "狐",
            "精靈",
            "精灵",
            "二次元",
            "立繪",
            "立绘",
            "人物",
        )
    ):
        return "anime_character"
    if any(marker in text for marker in ("product", "packshot", "commerce")) or any(
        marker in compact for marker in ("產品", "产品", "商品", "商業", "商业")
    ):
        return "product"
    if any(marker in text for marker in ("video", "motion")) or any(
        marker in compact for marker in ("影片", "視頻", "视频", "動畫", "动画", "動態", "动态")
    ):
        return "video"
    return "general"


def _safe_prompt_excerpt(prompt: str, *, max_chars: int = 700) -> str:
    cleaned = re.sub(r"\s+", " ", str(prompt or "")).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 3)].rstrip() + "..."


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
