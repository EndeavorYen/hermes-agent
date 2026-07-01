from __future__ import annotations

from dataclasses import dataclass
import copy
import shutil
from typing import Any

import yaml

from hermes_cli.config import DEFAULT_CONFIG, get_config_path
from hermes_constants import get_hermes_home


PLUGIN_NAME = "raphael"


@dataclass(frozen=True)
class RaphaelLifecycleResult:
    action: str
    changed: bool
    message: str


def install_raphael() -> RaphaelLifecycleResult:
    config = _read_user_config()
    before = copy.deepcopy(config)

    _ensure_plugin_enabled(config)
    _ensure_raphael_defaults(config)

    changed = config != before
    if changed:
        _write_user_config(config)
    return RaphaelLifecycleResult(
        action="install",
        changed=changed,
        message=(
            "Raphael installed. Run `hermes raphael enable` to turn on the "
            "control layer."
            if changed
            else "Raphael is already installed."
        ),
    )


def enable_raphael() -> RaphaelLifecycleResult:
    config = _read_user_config()
    before = copy.deepcopy(config)

    _ensure_plugin_enabled(config)
    raphael = _ensure_raphael_defaults(config)
    raphael["enabled"] = True
    raphael["default_conversation_mode_enabled"] = True

    changed = config != before
    if changed:
        _write_user_config(config)
    return RaphaelLifecycleResult(
        action="enable",
        changed=changed,
        message=(
            "Raphael enabled. Summon/control-layer injection is active."
            if changed
            else "Raphael is already enabled."
        ),
    )


def disable_raphael() -> RaphaelLifecycleResult:
    config = _read_user_config()
    before = copy.deepcopy(config)

    raphael = _ensure_raphael_defaults(config)
    raphael["enabled"] = False
    raphael["default_conversation_mode_enabled"] = False

    changed = config != before
    if changed:
        _write_user_config(config)
    return RaphaelLifecycleResult(
        action="disable",
        changed=changed,
        message=(
            "Raphael disabled. Summon/control-layer injection is off."
            if changed
            else "Raphael is already disabled."
        ),
    )


def uninstall_raphael() -> RaphaelLifecycleResult:
    config = _read_user_config()
    before = copy.deepcopy(config)
    state_dir = get_hermes_home() / "raphael"
    has_plugin_reference = _has_plugin_reference(config)
    has_raphael_config = "raphael" in config
    has_runtime_state = state_dir.exists()

    if not (has_plugin_reference or has_raphael_config or has_runtime_state):
        return RaphaelLifecycleResult(
            action="uninstall",
            changed=False,
            message="Raphael is already uninstalled.",
        )

    _remove_plugin_references(config)
    if has_raphael_config:
        raphael = _ensure_raphael_defaults(config)
        raphael["enabled"] = False
        raphael["default_conversation_mode_enabled"] = False

    state_removed = False
    if state_dir.exists():
        shutil.rmtree(state_dir)
        state_removed = True

    changed = state_removed or config != before
    if config != before:
        _write_user_config(config)
    return RaphaelLifecycleResult(
        action="uninstall",
        changed=changed,
        message=(
            "Raphael uninstalled. Raphael-owned runtime state was removed."
            if changed
            else "Raphael is already uninstalled."
        ),
    )


def render_lifecycle_status() -> str:
    config = _read_user_config()
    plugins = _dict_value(config, "plugins")
    enabled_plugins = _string_list(plugins.get("enabled"))
    disabled_plugins = _string_list(plugins.get("disabled"))
    raphael = _dict_value(config, "raphael")
    installed = PLUGIN_NAME in enabled_plugins and PLUGIN_NAME not in disabled_plugins
    enabled = raphael.get("enabled") is True
    conversation_mode = raphael.get("default_conversation_mode_enabled") is True
    state_dir = get_hermes_home() / "raphael"

    if not installed:
        next_action = "hermes raphael install"
    elif not enabled:
        next_action = "hermes raphael enable"
    else:
        next_action = "summon Raphael or run hermes raphael disable"

    return "\n".join(
        [
            "Raphael lifecycle status",
            f"Installed: {_yes_no(installed)}",
            f"Enabled: {_yes_no(enabled)}",
            f"Conversation mode: {'on' if conversation_mode else 'off'}",
            f"Runtime state: {'present' if state_dir.exists() else 'absent'}",
            f"Next action: {next_action}",
        ]
    )


def raphael_command(args: Any) -> int:
    action = getattr(args, "raphael_action", None) or "status"
    if action == "install":
        result = install_raphael()
        print(result.message)
        return 0
    if action == "enable":
        result = enable_raphael()
        print(result.message)
        return 0
    if action == "disable":
        result = disable_raphael()
        print(result.message)
        return 0
    if action == "uninstall":
        result = uninstall_raphael()
        print(result.message)
        return 0
    if action == "status":
        print(render_lifecycle_status())
        return 0
    print("Usage: hermes raphael [install|enable|disable|status|uninstall]")
    return 2


def _read_user_config() -> dict[str, Any]:
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_user_config(config: dict[str, Any]) -> None:
    from utils import atomic_yaml_write

    get_hermes_home().mkdir(parents=True, exist_ok=True)
    atomic_yaml_write(get_config_path(), config, sort_keys=False)


def _ensure_raphael_defaults(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("raphael")
    if not isinstance(raw, dict):
        raw = {}
        config["raphael"] = raw
    defaults = copy.deepcopy(DEFAULT_CONFIG["raphael"])
    _deep_merge_missing(raw, defaults)
    return raw


def _ensure_plugin_enabled(config: dict[str, Any]) -> None:
    plugins = config.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        plugins = {}
        config["plugins"] = plugins
    enabled = _ensure_list(plugins, "enabled")
    if PLUGIN_NAME not in enabled:
        enabled.append(PLUGIN_NAME)
    disabled = _ensure_list(plugins, "disabled")
    while PLUGIN_NAME in disabled:
        disabled.remove(PLUGIN_NAME)


def _remove_plugin_references(config: dict[str, Any]) -> None:
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return
    for key in ("enabled", "disabled"):
        values = plugins.get(key)
        if isinstance(values, list):
            plugins[key] = [value for value in values if value != PLUGIN_NAME]


def _has_plugin_reference(config: dict[str, Any]) -> bool:
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return False
    for key in ("enabled", "disabled"):
        values = plugins.get(key)
        if isinstance(values, list) and PLUGIN_NAME in values:
            return True
    return False


def _ensure_list(container: dict[str, Any], key: str) -> list[Any]:
    raw = container.get(key)
    if isinstance(raw, list):
        return raw
    values: list[Any] = []
    container[key] = values
    return values


def _dict_value(config: dict[str, Any], key: str) -> dict[str, Any]:
    raw = config.get(key)
    return raw if isinstance(raw, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _deep_merge_missing(target: dict[str, Any], defaults: dict[str, Any]) -> None:
    for key, value in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(value)
            continue
        if isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge_missing(target[key], value)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


__all__ = [
    "RaphaelLifecycleResult",
    "disable_raphael",
    "enable_raphael",
    "install_raphael",
    "raphael_command",
    "render_lifecycle_status",
    "uninstall_raphael",
]
