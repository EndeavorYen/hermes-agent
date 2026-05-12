"""Operator review tool for Layer-2 candidate memory."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, Optional

from memory.layer2_promotion import L1Pressure, evaluate_promotion
from memory.layer2_store import Layer2Store, apply_layer2_payload, format_layer2_audit_section
from tools.memory_tool import ENTRY_DELIMITER, MemoryStore


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
            "respect_l1_pressure": {"type": "boolean"},
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


def _l1_pressure_for_target(memory_store: MemoryStore, target: str) -> L1Pressure:
    if hasattr(memory_store, "_char_count"):
        current_chars = int(memory_store._char_count(target))
    else:
        entries = getattr(memory_store, f"{target}_entries", [])
        current_chars = len(ENTRY_DELIMITER.join(entries)) if entries else 0

    if hasattr(memory_store, "_char_limit"):
        char_limit = int(memory_store._char_limit(target))
    else:
        attr = "user_char_limit" if target == "user" else "memory_char_limit"
        char_limit = int(getattr(memory_store, attr, 0) or 0)

    return L1Pressure(current_chars=current_chars, char_limit=char_limit)


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
    respect_l1_pressure: bool = True,
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
        if respect_l1_pressure:
            candidate = ledger.get_candidate(canonical)
            if not candidate:
                return json.dumps({"success": False, "error": "candidate not found."}, ensure_ascii=False)
            memory_store = MemoryStore()
            memory_store.load_from_disk()
            pressure = _l1_pressure_for_target(memory_store, resolved_target)
            decision = evaluate_promotion(candidate, pressure=pressure)
            if not decision.allowed:
                return json.dumps(
                    {
                        "success": False,
                        "error": "promotion blocked by L1 pressure policy.",
                        "candidate": candidate,
                        "l1_pressure": {
                            "target": resolved_target,
                            "current_chars": pressure.current_chars,
                            "char_limit": pressure.char_limit,
                            "usage_ratio": pressure.usage_ratio,
                        },
                        "promotion_decision": asdict(decision),
                    },
                    ensure_ascii=False,
                )
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
        respect_l1_pressure=args.get("respect_l1_pressure", True),
        store=kw.get("store"),
    ),
    emoji="🧾",
)
