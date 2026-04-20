"""Thin runtime reflection artifacts for post-task analysis.

This module intentionally stays deterministic and compact. It does not invoke an
LLM or mutate memory/skills; it only derives a small structured record from the
completed run so later phase-2/phase-3 workflows have durable substrate.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home


_REFLECTION_SCHEMA_VERSION = 2
_WRITE_TOOLS = {
    "write_file",
    "patch",
    "terminal",
    "execute_code",
    "skill_manage",
    "cronjob",
}
_REPO_INSPECTION_TOOLS = {
    "read_file",
    "search_files",
    "session_search",
    "browser_snapshot",
    "browser_console",
}


def _trim_text(value: Optional[str], max_chars: int) -> str:
    text = (value or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _iter_tool_call_names(messages: List[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for tool_call in msg.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            name = tool_call.get("function", {}).get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def _count_failed_tool_results(messages: List[Dict[str, Any]]) -> int:
    failed = 0
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("success") is False:
            failed += 1
    return failed


def infer_affordance_signals(
    tool_names: List[str],
    *,
    completed: bool,
    interrupted: bool,
    partial: bool,
    failed_tool_results: int,
    messages: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    needs: List[str] = []
    evidence: List[str] = []
    suggested_next: List[str] = []

    unique_names = list(dict.fromkeys(tool_names))
    if unique_names:
        needs.append("tool_use")
        evidence.append(f"used {len(unique_names)} distinct tool(s): {', '.join(unique_names[:6])}")

    if any(name in _REPO_INSPECTION_TOOLS for name in unique_names) and len(unique_names) >= 2:
        needs.append("repo_inspection")
        evidence.append("combined multiple inspection/search surfaces in one turn")

    if any(name in _WRITE_TOOLS for name in unique_names):
        needs.append("workspace_mutation")
        evidence.append("used file/system mutation tools")

    if "delegate_task" in unique_names:
        needs.append("delegation")
        evidence.append("used subagent delegation")

    if any(isinstance(msg, dict) and msg.get("role") == "assistant" and len(msg.get("tool_calls") or []) > 1 for msg in messages):
        needs.append("parallel_tools")
        evidence.append("issued multiple tool calls in one assistant turn")

    if interrupted or partial or not completed or failed_tool_results:
        needs.append("reflection")
        if interrupted:
            evidence.append("run ended interrupted")
        if partial:
            evidence.append("run ended partial")
        if not completed and not interrupted:
            evidence.append("run did not complete successfully")
        if failed_tool_results:
            evidence.append(f"{failed_tool_results} tool result(s) reported success=false")
        suggested_next.append("review recent failures/interruption patterns before broadening scope")

    if not suggested_next and unique_names:
        suggested_next.append("mine repeated tool patterns before adding new automation")

    return {
        "needs": list(dict.fromkeys(needs)),
        "evidence": list(dict.fromkeys(evidence)),
        "suggested_next": list(dict.fromkeys(suggested_next)),
    }


def build_reflection_record(
    *,
    messages: List[Dict[str, Any]],
    user_message: str,
    final_response: Optional[str],
    session_id: Optional[str],
    parent_session_id: Optional[str],
    model: str,
    provider: Optional[str],
    platform: Optional[str],
    completed: bool,
    interrupted: bool,
    partial: bool,
    max_user_message_chars: int = 500,
    max_final_response_chars: int = 300,
    post_response_review: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    tool_names = _iter_tool_call_names(messages)
    failed_tool_results = _count_failed_tool_results(messages)
    affordance = infer_affordance_signals(
        tool_names,
        completed=completed,
        interrupted=interrupted,
        partial=partial,
        failed_tool_results=failed_tool_results,
        messages=messages,
    )
    normalized_post_response_review = {
        "memory": bool((post_response_review or {}).get("memory", False)),
        "skills": bool((post_response_review or {}).get("skills", False)),
        "queued": bool((post_response_review or {}).get("queued", False)),
    }
    return {
        "version": _REFLECTION_SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "parent_session_id": parent_session_id,
        "platform": platform or "",
        "model": model,
        "provider": provider or "",
        "prompt": {
            "user_message": _trim_text(user_message, max_user_message_chars),
            "task_hash": hashlib.sha256((user_message or "").encode("utf-8")).hexdigest(),
        },
        "outcome": {
            "completed": completed,
            "failed": (not completed) and (not interrupted),
            "interrupted": interrupted,
            "partial": partial,
            "error": None,
            "final_response_preview": _trim_text(final_response, max_final_response_chars),
        },
        "tools": {
            "called": len(tool_names),
            "unique": list(dict.fromkeys(tool_names)),
            "failed": failed_tool_results,
        },
        "affordance": affordance,
        "post_response_review": normalized_post_response_review,
    }


def reflection_log_path(hermes_home: Optional[Path] = None) -> Path:
    base = Path(hermes_home) if hermes_home else get_hermes_home()
    return base / "artifacts" / "reflections.jsonl"


def affordance_gap_log_path(hermes_home: Optional[Path] = None) -> Path:
    base = Path(hermes_home) if hermes_home else get_hermes_home()
    return base / "artifacts" / "affordance_gaps.jsonl"


def background_review_log_path(hermes_home: Optional[Path] = None) -> Path:
    base = Path(hermes_home) if hermes_home else get_hermes_home()
    return base / "artifacts" / "background_reviews.jsonl"


def extract_affordance_gap_entry(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    outcome = record.get("outcome") or {}
    tools = record.get("tools") or {}
    affordance = record.get("affordance") or {}
    if not (
        outcome.get("interrupted")
        or outcome.get("partial")
        or outcome.get("failed")
        or int(tools.get("failed") or 0) > 0
    ):
        return None

    needs = [
        need
        for need in affordance.get("needs") or []
        if need not in {"tool_use", "repo_inspection", "workspace_mutation"}
    ]
    return {
        "version": record.get("version", _REFLECTION_SCHEMA_VERSION),
        "timestamp": record.get("timestamp"),
        "session_id": record.get("session_id"),
        "platform": record.get("platform", ""),
        "model": record.get("model", ""),
        "provider": record.get("provider", ""),
        "prompt": record.get("prompt", {}),
        "outcome": outcome,
        "tools": {
            "unique": tools.get("unique", []),
            "failed": tools.get("failed", 0),
        },
        "gap_signals": needs or ["reflection"],
        "evidence": affordance.get("evidence", []),
        "suggested_next": affordance.get("suggested_next", []),
    }


def append_reflection_record(record: Dict[str, Any], hermes_home: Optional[Path] = None) -> Path:
    path = reflection_log_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    gap_entry = extract_affordance_gap_entry(record)
    if gap_entry is not None:
        gap_path = affordance_gap_log_path(hermes_home)
        gap_path.parent.mkdir(parents=True, exist_ok=True)
        with gap_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(gap_entry, ensure_ascii=False) + "\n")
    return path


def append_background_review_event(event: Dict[str, Any], hermes_home: Optional[Path] = None) -> Path:
    path = background_review_log_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def should_emit_reflection(
    *,
    enabled: bool,
    messages: List[Dict[str, Any]],
    completed: bool,
    interrupted: bool,
    partial: bool,
    min_tool_turns: int,
) -> bool:
    if not enabled:
        return False
    if interrupted or partial or not completed:
        return True
    tool_turns = sum(
        1
        for msg in messages
        if isinstance(msg, dict) and msg.get("role") == "assistant" and msg.get("tool_calls")
    )
    return tool_turns >= max(1, int(min_tool_turns))
