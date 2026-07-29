"""Optional Hermes supervision of Toonflow through Control Contract 1.0."""

from __future__ import annotations

import json
import os
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
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

_EXPLICIT_TOONFLOW_MARKERS = (
    "請用toonflow",
    "请用toonflow",
    "用toonflow",
    "使用toonflow",
    "透過toonflow",
    "通过toonflow",
    "走toonflow",
    "交給toonflow",
    "交给toonflow",
    "由toonflow",
    "讓toonflow",
    "让toonflow",
    "toonflow幫我",
    "toonflow帮我",
)
_TOONFLOW_OPTOUT_MARKERS = (
    "不要用toonflow",
    "不要使用toonflow",
    "不使用toonflow",
    "別用toonflow",
    "别用toonflow",
    "請勿使用toonflow",
    "请勿使用toonflow",
    "勿用toonflow",
    "勿使用toonflow",
)
_TOONFLOW_TURN_CLAIM_LIMIT = 1024
_TOONFLOW_TURN_CLAIMS: OrderedDict[tuple[str, str], bool] = OrderedDict()
_TOONFLOW_TURN_CLAIMS_LOCK = threading.Lock()


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


def _message_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        parts = [
            _message_text(value.get(key))
            for key in ("text", "content")
            if value.get(key) is not None
        ]
        return "\n".join(part for part in parts if part)
    if isinstance(value, (list, tuple)):
        return "\n".join(part for item in value if (part := _message_text(item)))
    return ""


def _explicit_toonflow_request(user_message: Any) -> bool:
    text = _message_text(user_message).lower()
    compact = re.sub(r"[\s_-]+", "", text)
    if any(marker in compact for marker in _TOONFLOW_OPTOUT_MARKERS):
        return False
    toonflow_name = r"toon[\s_-]*flow\b"
    english_optout_patterns = (
        rf"\b(?:do\s+not|don't|never)\s+(?:use|using)\s+{toonflow_name}",
        rf"\b(?:do\s+not|don't|never)\s+"
        rf"(?:make|create|generate|produce|build|run)\b[^.!?;；\n]*"
        rf"\b(?:with|via|through|using)\s+{toonflow_name}",
        rf"\bwithout\s+(?:using\s+)?{toonflow_name}",
    )
    if any(re.search(pattern, text) for pattern in english_optout_patterns):
        return False
    if any(marker in compact for marker in _EXPLICIT_TOONFLOW_MARKERS):
        return True
    if re.search(
        r"\b(?:use|using|via|through|run)\s+toon[\s_-]*flow\b",
        text,
    ):
        return True
    if re.search(
        r"(?:^|\n)\s*toon[\s_-]*flow\b[\s,，:：-]*(?:please\s+)?"
        r"(?:make|create|generate|produce|build|run)\b",
        text,
    ):
        return True
    return bool(
        re.search(r"\bwith\s+toon[\s_-]*flow\b", text)
        and re.search(
            r"\b(?:make|create|generate|produce|build|run)\b",
            text,
        )
    )


def _turn_key(session_id: Any, turn_id: Any) -> tuple[str, str] | None:
    key = (str(session_id or "").strip(), str(turn_id or "").strip())
    return key if all(key) else None


def _remember_turn_claim(
    *,
    session_id: Any,
    turn_id: Any,
    configured: bool,
) -> None:
    key = _turn_key(session_id, turn_id)
    if key is None:
        return
    with _TOONFLOW_TURN_CLAIMS_LOCK:
        _TOONFLOW_TURN_CLAIMS[key] = configured
        _TOONFLOW_TURN_CLAIMS.move_to_end(key)
        while len(_TOONFLOW_TURN_CLAIMS) > _TOONFLOW_TURN_CLAIM_LIMIT:
            _TOONFLOW_TURN_CLAIMS.popitem(last=False)


def _claimed_turn_configuration(
    *,
    session_id: Any,
    turn_id: Any,
) -> bool | None:
    key = _turn_key(session_id, turn_id)
    if key is None:
        return None
    with _TOONFLOW_TURN_CLAIMS_LOCK:
        return _TOONFLOW_TURN_CLAIMS.get(key)


def _claim_explicit_toonflow_turn(
    *,
    user_message: Any = "",
    session_id: Any = "",
    turn_id: Any = "",
    **_: Any,
) -> dict[str, Any] | None:
    if not _explicit_toonflow_request(user_message):
        return None

    configured, setup_message = check_toonflow_configured()
    if configured:
        context = (
            "TOONFLOW_WORKFLOW_ROUTE. The user explicitly selected ToonFlow, "
            "which owns project creation, story/script/storyboard execution, "
            "shot generation, assembly, and artifact selection for this turn. "
            "Call toonflow_capabilities first, then use only toonflow_* control "
            "tools to create and run the requested project and report its status. "
            "Do not call visual_agent_generate, visual_engine_generate, a media "
            "provider, or a browser provider directly."
        )
    else:
        context = (
            "TOONFLOW_WORKFLOW_ROUTE_SETUP_REQUIRED. The user explicitly selected "
            f"ToonFlow, but its control route is unavailable: {setup_message}. "
            "Report this setup requirement. Do not fall back to visual_agent_generate, "
            "visual_engine_generate, another media provider, or a browser provider."
        )
    _remember_turn_claim(
        session_id=session_id,
        turn_id=turn_id,
        configured=configured,
    )
    return {
        "context": context,
        "turn_control": {
            "mode": "external_workflow",
            "completion_policy": "toonflow_control",
            "route": {
                "owner": "toonflow",
                "bypass_base_llm": False,
                "configured": configured,
            },
        },
    }


def _enforce_toonflow_turn_ownership(
    *,
    tool_name: str = "",
    session_id: Any = "",
    turn_id: Any = "",
    **_: Any,
) -> dict[str, str] | None:
    configured = _claimed_turn_configuration(
        session_id=session_id,
        turn_id=turn_id,
    )
    if configured is None:
        return None
    if configured and str(tool_name or "").startswith("toonflow_"):
        return None
    reason = (
        "ToonFlow control is not configured for this explicitly selected workflow."
        if not configured
        else "This turn is owned by the explicitly selected ToonFlow workflow."
    )
    return {
        "action": "block",
        "message": (
            f"{reason} Tool '{tool_name}' was blocked; no provider or workflow "
            "fallback is allowed."
        ),
    }


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
    ctx.register_hook("pre_llm_call", _claim_explicit_toonflow_turn)
    ctx.register_hook("pre_tool_call", _enforce_toonflow_turn_ownership)
