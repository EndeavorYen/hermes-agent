from __future__ import annotations

import json
from typing import Any


ACTION_DEDUPE_FIELDS = (
    "type",
    "source",
    "track",
    "modality",
    "dimension",
    "focus",
    "strategy_operator",
    "strategy_signature",
    "evaluation_operator",
    "quality_issue",
    "issue",
    "quality_issues",
    "provider_failure_classes",
    "provider_error_codes",
    "reason",
    "bucket",
    "repair_hint",
)


def dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for action in actions:
        key = action_dedupe_key(action)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def action_dedupe_key(action: dict[str, Any]) -> tuple[str, ...]:
    return tuple(_key_value(action.get(field)) for field in ACTION_DEDUPE_FIELDS)


def _key_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    return str(value)
