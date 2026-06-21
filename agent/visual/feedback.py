from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger


@dataclass(frozen=True)
class ParsedVisualFeedback:
    text: str
    selection_hint: int | None
    selection_label: str | None
    polarity: float
    parsed: dict[str, Any]


def parse_visual_feedback(text: str) -> ParsedVisualFeedback:
    normalized = text.strip()
    selection_hint, selection_label = _extract_selection(normalized)
    signals = _extract_signals(normalized)
    issues = _extract_issues(normalized)
    polarity = _score_polarity(normalized, signals, issues)
    parsed = {
        "selection_hint": selection_hint,
        "selection_label": selection_label,
        "signals": signals,
        "issues": issues,
    }
    return ParsedVisualFeedback(
        text=normalized,
        selection_hint=selection_hint,
        selection_label=selection_label,
        polarity=polarity,
        parsed=parsed,
    )


def record_parsed_visual_feedback(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    feedback_text: str,
    artifact_ids_by_index: list[str] | dict[int, str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    feedback = parse_visual_feedback(feedback_text)
    artifact_id = _artifact_for_selection(feedback.selection_hint, artifact_ids_by_index)
    return ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text=feedback.text,
        polarity=feedback.polarity,
        parsed=feedback.parsed,
        metadata=metadata,
    )


def _extract_selection(text: str) -> tuple[int | None, str | None]:
    numbered = re.search(r"第\s*(\d+)\s*張", text)
    if numbered:
        value = int(numbered.group(1))
        return value, numbered.group(0)

    label = re.search(r"\b([A-Za-z]{0,3})(\d+)([A-Za-z]?)\b", text)
    if label:
        return int(label.group(2)), label.group(0)
    return None, None


def _extract_signals(text: str) -> list[str]:
    signals = []
    if _has_any(text, ("構圖更好", "構圖不錯", "構圖算不錯", "composition good")):
        signals.append("composition_positive")
    elif "構圖" in text and _has_any(text, ("好", "不錯", "突破")) and not _has_any(text, ("不好", "差", "普普")):
        signals.append("composition_positive")
    if _has_any(text, ("動作不錯", "動態不錯", "motion good", "跳脫")):
        signals.append("motion_good")
    if _has_any(text, ("腿", "美腿", "裸足")) and _has_any(text, ("好", "加分", "不錯")):
        signals.append("legs_positive")
    return _dedupe(signals)


def _extract_issues(text: str) -> list[str]:
    issues = []
    if _has_any(text, ("不像", "差異太大", "不符合", "identity drift")):
        issues.append("reference_identity_drift")
    if "臉" in text and _has_any(text, ("不自然", "怪", "醜", "太圓")):
        issues.append("face_unnatural")
    if _has_any(text, ("不漂亮", "不好看", "不是美女", "醜")):
        issues.append("not_beautiful")
    if _has_any(text, ("不夠性感", "性感不足", "不性感", "sexy enough")):
        issues.append("not_sexy_enough")
    if "構圖" in text and _has_any(text, ("差", "不好", "普普", "無新意")):
        issues.append("composition_bad")
    if _has_any(text, ("slow motion", "太慢", "不動", "靜態")):
        issues.append("static_video")
    if _has_any(text, ("舊圖", "重複貼", "上輪")):
        issues.append("stale_repost")
    return _dedupe(issues)


def _score_polarity(text: str, signals: list[str], issues: list[str]) -> float:
    score = 0.0
    score += len(signals) * 0.6
    score -= len(issues) * 0.45
    if _has_any(text, ("不錯", "好評", "給過", "加分", "很好", "成功")):
        score += 0.6
    if _has_any(text, ("退貨", "差評", "扣分", "爛", "失敗")):
        score -= 0.8
    return max(-1.0, min(1.0, round(score, 4)))


def _artifact_for_selection(
    selection_hint: int | None,
    artifact_ids_by_index: list[str] | dict[int, str] | None,
) -> str | None:
    if selection_hint is None or artifact_ids_by_index is None:
        return None
    if isinstance(artifact_ids_by_index, dict):
        return artifact_ids_by_index.get(selection_hint)
    index = selection_hint - 1
    if index < 0 or index >= len(artifact_ids_by_index):
        return None
    return artifact_ids_by_index[index]


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    text_lc = text.lower()
    return any(needle.lower() in text_lc for needle in needles)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
