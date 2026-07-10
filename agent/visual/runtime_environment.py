from __future__ import annotations

import importlib.util
from collections.abc import Callable
from typing import Any


_LIVE_MODULES = ("openai",)
_LIVE_SLACK_UPLOAD_MODULES = ("aiohttp", "slack_sdk")
_POST_SETUP = (
    "Run live visual validation through the project environment: "
    "rtk uv run --extra dev --extra slack python3 <script>, or sync the Hermes venv."
)


def build_visual_runtime_environment_diagnostic(
    *,
    include_live: bool,
    include_live_slack_upload: bool,
    find_spec: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Report whether the current Python runner can execute live visual validation."""

    find_spec = find_spec or importlib.util.find_spec
    required_modules = _required_modules(
        include_live=include_live,
        include_live_slack_upload=include_live_slack_upload,
    )
    missing_modules = [
        module
        for module in required_modules
        if find_spec(module) is None
    ]
    next_actions = []
    if missing_modules:
        next_actions.append(
            {
                "type": "configure_visual_runtime_dependencies",
                "track": "operator_setup",
                "reason": "visual_runtime_missing_python_modules",
                "requires_human_feedback": False,
                "requires_operator_setup": True,
                "activation_status": "operator_setup",
                "source": "visual_runtime_environment",
                "missing_modules": missing_modules,
                "operator_setup_actions": [
                    {
                        "provider": "python_runtime",
                        "missing_env_vars": [],
                        "post_setup": _POST_SETUP,
                    }
                ],
            }
        )
    return {
        "success": not missing_modules,
        "required_modules": required_modules,
        "missing_modules": missing_modules,
        "next_actions": next_actions,
    }


def _required_modules(
    *,
    include_live: bool,
    include_live_slack_upload: bool,
) -> list[str]:
    modules: list[str] = []
    if include_live:
        modules.extend(_LIVE_MODULES)
    if include_live_slack_upload:
        modules.extend(_LIVE_SLACK_UPLOAD_MODULES)
    return sorted(set(modules))
