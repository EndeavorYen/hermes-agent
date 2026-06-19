"""Rule-based parsing for sparse visual generation feedback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class VisualFeedback:
    feedback_type: str
    polarity: float
    strength: float
    raw_text: str
    parsed: Dict[str, Any]


_CHINESE_NUMBER = {
    "一": 1,
    "二": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def parse_visual_feedback(text: str) -> VisualFeedback:
    raw_text = str(text or "")
    normalized = raw_text.strip()
    lower = normalized.lower()

    issues = _detect_issues(normalized, lower)
    requested_direction = _detect_requested_direction(normalized, lower)
    selection_hint = _detect_selection_hint(normalized)
    candidate_hints = _detect_candidate_hints(normalized)
    polarity = _detect_polarity(normalized, lower, issues)

    parsed = {
        "issues": issues,
        "selection_hint": selection_hint,
        "candidate_hints": candidate_hints,
        "requested_direction": requested_direction,
    }
    return VisualFeedback(
        feedback_type="explicit_text",
        polarity=polarity,
        strength=round(abs(polarity), 3),
        raw_text=raw_text,
        parsed=parsed,
    )


def _detect_issues(text: str, lower: str) -> List[str]:
    issues: List[str] = []
    _append_if(
        issues,
        "reference_identity_drift",
        _contains_any(
            text,
            (
                "臉不像",
                "臉不太像",
                "面容不符合",
                "面容不像",
                "人設差異太大",
                "不像同一人",
            ),
        ),
    )
    _append_if(
        issues,
        "not_attractive",
        _contains_any(text, ("醜", "不漂亮", "不美", "臉太圓", "臉不自然")),
    )
    _append_if(
        issues,
        "not_sexy_enough",
        _contains_any(
            text,
            (
                "不夠性感",
                "不性感",
                "性感升級不夠",
                "性感程度普普",
                "性感程度普通",
                "太保守",
            ),
        ),
    )
    _append_if(
        issues,
        "too_explicit",
        _contains_any(text, ("太露骨", "太露", "過度裸露", "太色情"))
        or "too explicit" in lower,
    )
    _append_if(
        issues,
        "stale_or_repeated_artifact",
        _contains_any(text, ("舊圖", "上輪", "重複", "同張圖", "貼到舊")),
    )
    _append_if(
        issues,
        "aspect_or_stretch_issue",
        _contains_any(text, ("比例錯", "比例不對", "拉伸", "變形", "被拉長")),
    )
    return issues


def _detect_requested_direction(text: str, lower: str) -> Optional[str]:
    if (
        "slow motion" in lower
        or _contains_any(text, ("更有動作", "多一點動作", "動起來", "不要慢動作"))
    ):
        return "more_motion"
    if _contains_any(text, ("少一點動作", "不要動太多", "太晃", "太動")):
        return "less_motion"
    return None


def _detect_selection_hint(text: str) -> Optional[int]:
    match = re.search(r"第\s*([一二兩三四五六七八九十]|\d+)\s*(?:張|個|个|號|号)", text)
    if match:
        value = match.group(1)
        if value.isdigit():
            return int(value)
        return _CHINESE_NUMBER.get(value)
    match = re.search(r"\b(\d+)\s*(?:st|nd|rd|th)\b", text, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _detect_candidate_hints(text: str) -> List[str]:
    candidates = re.findall(r"(?<![A-Za-z0-9])([A-Z]{1,3}[0-9][A-Z0-9]*)(?![A-Za-z0-9])", text)
    result: List[str] = []
    seen = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


def _detect_polarity(text: str, lower: str, issues: List[str]) -> float:
    score = 0.0
    for term in ("不錯", "很好", "好評", "過關", "給過", "保留", "喜歡", "突破", "加分"):
        if term in text:
            score += 0.35
    for term in ("退貨", "差評", "不好", "不行", "失敗", "醜", "扣分", "爛"):
        if term in text:
            score -= 0.45
    if "good" in lower or "nice" in lower:
        score += 0.25
    if "bad" in lower or "fail" in lower:
        score -= 0.35
    if issues:
        score -= min(0.6, 0.2 * len(issues))
    if score > 1.0:
        return 1.0
    if score < -1.0:
        return -1.0
    return round(score, 3)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _append_if(items: List[str], item: str, condition: bool) -> None:
    if condition and item not in items:
        items.append(item)
