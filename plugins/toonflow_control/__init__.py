"""Optional Hermes supervision of Toonflow through Control Contract 1.0."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from . import schemas, tools
from .client import ToonflowControlClient

_TOOL_DEFINITIONS = (
    (
        "toonflow_capabilities",
        schemas.TOONFLOW_CAPABILITIES_SCHEMA,
        tools.toonflow_capabilities,
    ),
    (
        "toonflow_create_project",
        schemas.TOONFLOW_CREATE_PROJECT_SCHEMA,
        tools.toonflow_create_project,
    ),
    ("toonflow_run", schemas.TOONFLOW_RUN_SCHEMA, tools.toonflow_run),
    (
        "toonflow_run_status",
        schemas.TOONFLOW_RUN_STATUS_SCHEMA,
        tools.toonflow_run_status,
    ),
    (
        "toonflow_cancel_run",
        schemas.TOONFLOW_CANCEL_RUN_SCHEMA,
        tools.toonflow_cancel_run,
    ),
    (
        "toonflow_select_artifact",
        schemas.TOONFLOW_SELECT_ARTIFACT_SCHEMA,
        tools.toonflow_select_artifact,
    ),
)


def check_toonflow_configured() -> tuple[bool, str]:
    """Validate local configuration without contacting Toonflow."""

    if not (os.environ.get("TOONFLOW_CONTROL_TOKEN") or "").strip():
        return False, "TOONFLOW_CONTROL_TOKEN is not configured"
    try:
        ToonflowControlClient()
    except ValueError as exc:
        return False, str(exc)
    return True, "configured"


def is_toonflow_configured() -> bool:
    """Boolean availability gate used by the Hermes tool registry."""

    return check_toonflow_configured()[0]


def _serialized(
    handler: Callable[..., dict[str, Any]],
) -> Callable[..., str]:
    def wrapped(args: dict[str, Any], **kwargs: Any) -> str:
        return json.dumps(
            handler(args, **kwargs),
            ensure_ascii=False,
        )

    wrapped.__name__ = handler.__name__
    return wrapped


def register(ctx: Any) -> None:
    """Register six low-coupling supervisory tools."""

    for name, schema, handler in _TOOL_DEFINITIONS:
        ctx.register_tool(
            name=name,
            toolset="toonflow",
            schema=schema,
            handler=_serialized(handler),
            check_fn=is_toonflow_configured,
        )
