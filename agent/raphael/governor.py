from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

_JUDGMENT_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(狀態|風險|下一步)\s*[:：]"
)
_JUDGMENT_ORDER = ("狀態", "風險", "下一步")


def _cfg_get(config: Mapping[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = config
    for key in path:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key, default)
    return current


def should_apply_raphael_response_governor(
    config: Mapping[str, Any] | None = None,
) -> bool:
    if config is None:
        try:
            from hermes_cli.config import load_config

            config = load_config()
        except Exception:
            return False

    if _cfg_get(config, "raphael", "enabled", default=False) is not True:
        return False
    if (
        _cfg_get(
            config,
            "raphael",
            "default_conversation_mode_enabled",
            default=False,
        )
        is not True
    ):
        return False
    mode = str(_cfg_get(config, "raphael", "mode", default="advisor") or "").strip()
    return not mode or mode == "advisor"


def _has_code_block(text: str) -> bool:
    return "```" in text


def _has_file_mutation_footer(text: str) -> bool:
    return "file(s) were NOT modified" in text


def _extract_judgment_lines(lines: list[str], max_lines: int) -> list[str]:
    found: dict[str, str] = {}
    for line in lines:
        match = _JUDGMENT_LINE_RE.match(line)
        if match and match.group(1) not in found:
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

    lines = text.splitlines()
    judgment_lines = _extract_judgment_lines(lines, max_lines)
    if judgment_lines:
        return "\n".join(judgment_lines).rstrip()

    non_empty_seen = 0
    kept: list[str] = []
    for line in lines:
        if line.strip():
            non_empty_seen += 1
        if non_empty_seen > max_lines:
            break
        kept.append(line)

    if non_empty_seen <= max_lines:
        return text
    return "\n".join(kept).rstrip()


__all__ = [
    "apply_raphael_response_governor",
    "should_apply_raphael_response_governor",
]
