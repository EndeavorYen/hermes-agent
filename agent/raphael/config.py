from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def cfg_get(config: Mapping[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = config
    for key in path:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key, default)
    return current


def raphael_plugin_active(config: Mapping[str, Any]) -> bool:
    plugins = config.get("plugins")
    if not isinstance(plugins, Mapping):
        return False
    enabled = plugins.get("enabled")
    disabled = plugins.get("disabled")
    enabled_set = {str(item) for item in enabled} if isinstance(enabled, list) else set()
    disabled_set = {str(item) for item in disabled} if isinstance(disabled, list) else set()
    if "raphael" in disabled_set:
        return False
    return "raphael" in enabled_set


def raphael_effective_enabled(
    config: Mapping[str, Any] | None,
    *,
    require_default_conversation: bool = True,
) -> bool:
    if not isinstance(config, Mapping):
        return False
    if not raphael_plugin_active(config):
        return False
    if cfg_get(config, "raphael", "enabled", default=False) is not True:
        return False
    if require_default_conversation and (
        cfg_get(
            config,
            "raphael",
            "default_conversation_mode_enabled",
            default=False,
        )
        is not True
    ):
        return False
    mode = str(cfg_get(config, "raphael", "mode", default="sage_king") or "").strip()
    return not mode or mode in {"advisor", "sage_king"}


__all__ = ["cfg_get", "raphael_effective_enabled", "raphael_plugin_active"]
