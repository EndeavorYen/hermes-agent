from __future__ import annotations

from typing import Any


def operator_setup_actions_from_action(action: dict[str, Any]) -> list[dict[str, Any]]:
    setup_actions = operator_setup_actions_from_setup_actions(
        action.get("operator_setup_actions")
    )
    for diagnostic in _dict_list(action.get("video_fallback_diagnostics")):
        setup_actions.extend(
            operator_setup_actions_from_setup_actions(diagnostic.get("setup_actions"))
        )
    return _dedupe_operator_setup_actions(setup_actions)


def operator_setup_actions_from_actions(actions: Any) -> list[dict[str, Any]]:
    if not isinstance(actions, list):
        return []
    setup_actions: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        setup_actions.extend(operator_setup_actions_from_action(action))
    return _dedupe_operator_setup_actions(setup_actions)


def operator_setup_actions_from_video_fallback_diagnostics(
    value: Any,
) -> list[dict[str, Any]]:
    setup_actions: list[dict[str, Any]] = []
    for diagnostic in _dict_list(value):
        setup_actions.extend(
            operator_setup_actions_from_setup_actions(diagnostic.get("setup_actions"))
        )
    return _dedupe_operator_setup_actions(setup_actions)


def operator_setup_actions_from_setup_actions(value: Any) -> list[dict[str, Any]]:
    setup_actions: list[dict[str, Any]] = []
    for setup in _dict_list(value):
        missing_env_vars = _string_list(setup.get("missing_env_vars"))
        post_setup = str(setup.get("post_setup") or "").strip()
        if not missing_env_vars and not post_setup:
            continue
        setup_actions.append(
            {
                "provider": str(setup.get("provider") or "").strip(),
                "missing_env_vars": missing_env_vars,
                "post_setup": post_setup,
            }
        )
    return _dedupe_operator_setup_actions(setup_actions)


def _dedupe_operator_setup_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    for action in actions:
        provider = str(action.get("provider") or "").strip()
        missing_env_vars = tuple(_string_list(action.get("missing_env_vars")))
        post_setup = str(action.get("post_setup") or "").strip()
        key = (provider, missing_env_vars, post_setup)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "provider": provider,
                "missing_env_vars": list(missing_env_vars),
                "post_setup": post_setup,
            }
        )
    return deduped


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]
