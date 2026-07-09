from __future__ import annotations

from collections.abc import Mapping
import re

from agent.raphael.config import raphael_effective_enabled

_JUDGMENT_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(狀態|風險|下一步)\s*[:：]"
)
_JUDGMENT_ORDER = ("狀態", "風險", "下一步")
_JUDGMENT_VALUE_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:狀態|風險|下一步)\s*[:：]\s*(?P<value>.*)$"
)


def should_apply_raphael_response_governor(
    config: Mapping[str, Any] | None = None,
) -> bool:
    if config is None:
        try:
            from hermes_cli.config import load_config

            config = load_config()
        except Exception:
            return False

    return raphael_effective_enabled(config)


def _has_code_block(text: str) -> bool:
    return "```" in text


def _has_file_mutation_footer(text: str) -> bool:
    return "file(s) were NOT modified" in text


def _looks_like_review_or_evidence_report(text: str) -> bool:
    lowered = text.lower()
    if not any(marker in lowered for marker in ("findings", "evidence", "[p0]", "[p1]", "[p2]")):
        return False
    lines = [line.strip().lower().strip("*#") for line in text.splitlines()]
    has_review_heading = any(
        line in {"findings", "evidence", "verification", "tests", "open questions"}
        for line in lines
    )
    has_finding_marker = any(marker in lowered for marker in ("[p0]", "[p1]", "[p2]"))
    has_evidence_marker = any(
        marker in lowered
        for marker in ("pytest ", "runtime smoke", "non-live repro", "release state")
    )
    return has_review_heading and (has_finding_marker or has_evidence_marker)


def _extract_judgment_lines(lines: list[str], max_lines: int) -> list[str]:
    found: dict[str, str] = {}
    for line in lines:
        match = _JUDGMENT_LINE_RE.match(line)
        if not match or match.group(1) in found:
            continue
        value_match = _JUDGMENT_VALUE_RE.match(line)
        if not value_match or not value_match.group("value").strip():
            continue
        if match:
            found[match.group(1)] = line.strip()
    return [
        found[label]
        for label in _JUDGMENT_ORDER
        if label in found
    ][:max_lines]


def apply_raphael_response_governor(
    text: str,
    *,
    enabled: bool,
    max_lines: int = 6,
) -> str:
    if not enabled or max_lines <= 0 or not isinstance(text, str):
        return text
    if _has_code_block(text) or _has_file_mutation_footer(text):
        return text
    if _looks_like_review_or_evidence_report(text):
        return text

    lines = text.splitlines()
    judgment_lines = _extract_judgment_lines(lines, max_lines)
    if len(judgment_lines) >= 2:
        return "\n".join(judgment_lines).rstrip()

    return text


__all__ = [
    "apply_raphael_response_governor",
    "should_apply_raphael_response_governor",
]
