from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.visual_self_validation_status import build_visual_self_validation_status
from scripts.visual_self_validation_status import default_latest_path
from tools.registry import registry


VISUAL_SELF_VALIDATION_STATUS_SCHEMA: dict[str, Any] = {
    "name": "visual_self_validation_status",
    "description": (
        "Summarize Hermes visual agent mode health from the latest scheduled "
        "self-validation report. Use this when diagnosing image/video quality "
        "regressions, provider failures, duplicate Slack delivery, missing "
        "native uploads, or whether live E2E has recently run."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "stale_after_hours": {
                "type": "number",
                "description": "Optional threshold for marking the latest self-validation report stale.",
            }
        },
    },
}


def _default_latest_path() -> Path:
    return default_latest_path()


def check_visual_self_validation_status_requirements() -> bool:
    return True


def _handle_visual_self_validation_status(args: dict[str, Any], **_kw: Any) -> str:
    stale_after_hours = args.get("stale_after_hours") if isinstance(args, dict) else None
    kwargs: dict[str, Any] = {"latest_path": _default_latest_path()}
    if stale_after_hours is not None:
        kwargs["stale_after_hours"] = stale_after_hours
    payload = build_visual_self_validation_status(**kwargs)
    return json.dumps(payload, ensure_ascii=False)


registry.register(
    name="visual_self_validation_status",
    toolset="image_gen",
    schema=VISUAL_SELF_VALIDATION_STATUS_SCHEMA,
    handler=_handle_visual_self_validation_status,
    check_fn=check_visual_self_validation_status_requirements,
    requires_env=[],
    is_async=False,
    emoji="📊",
)
