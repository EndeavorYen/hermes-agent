"""Chat-accessible Layer-2 ledger write tool."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from memory.layer2_store import Layer2Store, apply_layer2_payload, format_layer2_audit_section

_ALLOWED_PAYLOAD_KEYS = {"candidate_events", "episodes", "observations", "context_packs"}


LAYER2_MEMORY_SCHEMA = {
    "name": "layer2_memory",
    "description": (
        "Write candidate-memory items into Hermes's Layer-2 ledger. Use this for candidate lessons, "
        "observations, episodes, and context packs that should NOT be promoted to durable memory yet. "
        "This tool is for L2 only and does not allow durable promotions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["write"],
                "description": "The action to perform. Only 'write' is supported.",
            },
            "payload": {
                "type": "object",
                "description": (
                    "Layer-2 write payload containing any of: candidate_events, episodes, observations, context_packs. "
                    "Do not include promotions."
                ),
            },
        },
        "required": ["action", "payload"],
    },
}


def layer2_memory_tool(
    *,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
    store: Optional[Layer2Store] = None,
    source_ref: Optional[str] = None,
    session_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> str:
    if action != "write":
        return json.dumps({"success": False, "error": f"Unknown action '{action}'. Supported action: write."}, ensure_ascii=False)

    if not isinstance(payload, dict):
        return json.dumps({"success": False, "error": "payload must be an object."}, ensure_ascii=False)

    unknown_keys = sorted(set(payload) - _ALLOWED_PAYLOAD_KEYS)
    if unknown_keys:
        return json.dumps(
            {
                "success": False,
                "error": f"Unsupported payload keys: {', '.join(unknown_keys)}. Allowed keys: {', '.join(sorted(_ALLOWED_PAYLOAD_KEYS))}.",
            },
            ensure_ascii=False,
        )

    if "promotions" in payload:
        return json.dumps({"success": False, "error": "promotions are not allowed on the chat Layer-2 write path."}, ensure_ascii=False)

    if not any(isinstance(payload.get(key), list) and payload.get(key) for key in _ALLOWED_PAYLOAD_KEYS):
        return json.dumps({"success": False, "error": "payload must contain at least one non-empty Layer-2 item list."}, ensure_ascii=False)

    ledger = store or Layer2Store()
    resolved_session_id = (session_id or "").strip() or None
    resolved_tool_call_id = (tool_call_id or "").strip() or None
    resolved_source_ref = (source_ref or "").strip() or None
    if not resolved_source_ref:
        if resolved_session_id and resolved_tool_call_id:
            resolved_source_ref = f"chat:unknown:{resolved_session_id}:{resolved_tool_call_id}"
        elif resolved_session_id:
            resolved_source_ref = f"chat:unknown:{resolved_session_id}"
        else:
            resolved_source_ref = "chat:unknown"

    synthetic_job = {
        "id": "chat-layer2-write",
        "memory_pipeline": {
            "enabled": True,
            "allow_durable_promotion_targets": [],
        },
    }

    audit_events = apply_layer2_payload(
        synthetic_job,
        payload,
        source_ref=resolved_source_ref,
        store=ledger,
        session_id=resolved_session_id,
        prompt_snapshot_id=None,
    )

    if not audit_events:
        return json.dumps(
            {"success": False, "error": "No valid Layer-2 items were applied from the payload."},
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "success": True,
            "applied_count": len(audit_events),
            "audit_events": audit_events,
            "audit_markdown": format_layer2_audit_section(audit_events),
            "source_ref": resolved_source_ref,
            "session_id": resolved_session_id,
        },
        ensure_ascii=False,
    )


from tools.registry import registry

registry.register(
    name="layer2_memory",
    toolset="memory",
    schema=LAYER2_MEMORY_SCHEMA,
    handler=lambda args, **kw: layer2_memory_tool(
        action=args.get("action", ""),
        payload=args.get("payload"),
        store=kw.get("store"),
        source_ref=kw.get("source_ref"),
        session_id=kw.get("session_id"),
        tool_call_id=kw.get("tool_call_id"),
    ),
    emoji="🧩",
)
