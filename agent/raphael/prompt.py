from __future__ import annotations

from collections.abc import Mapping
from typing import Any


RAPHAEL_MODE_PROMPT = """Raphael Mode

Operate as a read-only advisor layer for this conversation by default.
Continuously help the user notice risks, missing context, stale assumptions,
better next actions, and useful checks before they spend effort or mutate state.

Keep the boundary explicit:
- Do not create, patch, delete, install, or enable skills by default.
- Do not mutate memory, cron, tools, or public delivery by default.
- Do not present observations as approved actions.
- Only perform mutating actions after an explicit user request and the normal
  Hermes safety gates allow that action.

Prefer concise advisor notes when they materially improve the answer. Stay
pragmatic: if no Raphael observation is useful, answer normally."""


def _cfg_get(config: Mapping[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = config
    for key in path:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key, default)
    return current


def build_raphael_mode_prompt(config: Mapping[str, Any] | None = None) -> str:
    if config is None:
        try:
            from hermes_cli.config import load_config

            config = load_config()
        except Exception:
            return ""

    if _cfg_get(config, "raphael", "enabled", default=False) is not True:
        return ""
    if (
        _cfg_get(
            config,
            "raphael",
            "default_conversation_mode_enabled",
            default=False,
        )
        is not True
    ):
        return ""
    mode = str(_cfg_get(config, "raphael", "mode", default="advisor") or "").strip()
    if mode and mode != "advisor":
        return ""
    return RAPHAEL_MODE_PROMPT


__all__ = [
    "RAPHAEL_MODE_PROMPT",
    "build_raphael_mode_prompt",
]
