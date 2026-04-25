"""Operator review tool for Layer-2 candidate memory."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from memory.layer2_store import Layer2Store, apply_layer2_payload, format_layer2_audit_section


LAYER2_REVIEW_SCHEMA = {
    "name": "layer2_review",
    "description": (
        "Review and adjudicate Hermes Layer-2 candidate memory. Use list_candidates to inspect "
        "candidate facts with support/contradiction counts, prune_candidate to reject stale or false "
        "candidates, and promote_candidate for explicit operator-approved durable promotion."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_candidates", "inspect_candidate", "prune_candidate", "promote_candidate"],
            },
            "canonical_text": {"type": "string"},
            "status": {"type": "string", "enum": ["active", "stale", "quarantined", "quarantine", "pruned", "promoted", "all"]},
            "target": {"type": "string", "enum": ["memory", "user"]},
            "content": {"type": "string"},
            "query_text": {"type": "string"},
            "subject_scope": {"type": "string"},
            "subject_id": {"type": "string"},
            "max_items": {"type": "integer"},
            "min_support_count": {"type": "integer"},
            "notes": {"type": "string"},
            "source_ref": {"type": "string"},
        },
        "required": ["action"],
    },
}


def _candidate_markdown(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "No Layer-2 candidates matched."
    lines = ["## Layer-2 Candidate Review", ""]
    for item in candidates:
        destination = item.get("routing_destination") or item.get("proposed_target") or "-"
        kind = item.get("kind") or "fact"
        support = int(item.get("support_count") or 0)
        contradict = int(item.get("contradict_count") or 0)
        status = item.get("status") or "active"
        scope = item.get("subject_scope") or "-"
        subject = item.get("subject_id") or "-"
        lines.append(
            f"- [{status}/{destination}/{kind}] {item.get('canonical_text')} "
            f"(support={support}, contradict={contradict}, scope={scope}:{subject})"
        )
    return "\n".join(lines)


def layer2_review_tool(
    *,
    action: str,
    canonical_text: Optional[str] = None,
    target: Optional[str] = None,
    content: Optional[str] = None,
    query_text: Optional[str] = None,
    subject_scope: Optional[str] = None,
    subject_id: Optional[str] = None,
    max_items: int = 20,
    min_support_count: int = 0,
    status: Optional[str] = "active",
    notes: Optional[str] = None,
    source_ref: Optional[str] = None,
    store: Optional[Layer2Store] = None,
) -> str:
    ledger = store or Layer2Store()
    resolved_source_ref = (source_ref or "operator:layer2_review").strip() or "operator:layer2_review"

    if action == "list_candidates":
        normalized_status = "quarantine" if (status or "").strip().lower() == "quarantined" else (status or "active")
        candidates = ledger.list_candidates_by_status(
            status=normalized_status,
            max_items=max_items,
            min_support_count=min_support_count,
            query_text=query_text,
            subject_scope=subject_scope,
            subject_id=subject_id,
        )
        return json.dumps(
            {
                "success": True,
                "count": len(candidates),
                "candidates": candidates,
                "markdown": _candidate_markdown(candidates),
            },
            ensure_ascii=False,
        )

    canonical = (canonical_text or "").strip()
    if not canonical:
        return json.dumps({"success": False, "error": "canonical_text is required."}, ensure_ascii=False)

    if action == "inspect_candidate":
        candidate = ledger.get_candidate(canonical)
        if not candidate:
            return json.dumps({"success": False, "error": "candidate not found."}, ensure_ascii=False)
        events = ledger.list_events(canonical)
        return json.dumps(
            {
                "success": True,
                "candidate": candidate,
                "events": events,
                "event_count": len(events),
            },
            ensure_ascii=False,
        )

    if action == "prune_candidate":
        applied = ledger.record_event(
            event_type="prune",
            canonical_text=canonical,
            status="pruned",
            source_ref=resolved_source_ref,
            source_event_id=f"{resolved_source_ref}:prune:{canonical}",
            counts_for_recurrence=False,
            notes=notes or "operator_prune",
        )
        return json.dumps({"success": True, "audit_event": applied}, ensure_ascii=False)

    if action == "promote_candidate":
        resolved_target = (target or "").strip().lower()
        if resolved_target not in {"memory", "user"}:
            return json.dumps({"success": False, "error": "target must be 'memory' or 'user'."}, ensure_ascii=False)
        durable_content = (content or canonical).strip()
        payload = {
            "promotions": [
                {
                    "canonical_text": canonical,
                    "target": resolved_target,
                    "content": durable_content,
                    "source_ref": resolved_source_ref,
                    "source_event_id": f"{resolved_source_ref}:promote:{canonical}",
                    "notes": notes or "operator_promote",
                }
            ]
        }
        audit_events = apply_layer2_payload(
            {
                "id": "operator-layer2-review",
                "memory_pipeline": {
                    "enabled": True,
                    "allow_durable_promotion_targets": [resolved_target],
                },
            },
            payload,
            source_ref=resolved_source_ref,
            store=ledger,
        )
        return json.dumps(
            {
                "success": bool(audit_events),
                "audit_events": audit_events,
                "audit_markdown": format_layer2_audit_section(audit_events),
            },
            ensure_ascii=False,
        )

    return json.dumps({"success": False, "error": f"Unknown action '{action}'."}, ensure_ascii=False)


from tools.registry import registry

registry.register(
    name="layer2_review",
    toolset="memory",
    schema=LAYER2_REVIEW_SCHEMA,
    handler=lambda args, **kw: layer2_review_tool(
        action=args.get("action", ""),
        canonical_text=args.get("canonical_text"),
        target=args.get("target"),
        content=args.get("content"),
        query_text=args.get("query_text"),
        subject_scope=args.get("subject_scope"),
        subject_id=args.get("subject_id"),
        max_items=args.get("max_items", 20),
        min_support_count=args.get("min_support_count", 0),
        status=args.get("status", "active"),
        notes=args.get("notes"),
        source_ref=args.get("source_ref"),
        store=kw.get("store"),
    ),
    emoji="🧾",
)
