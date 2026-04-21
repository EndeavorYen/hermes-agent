"""Thin autonomous continuation loop for Hermes CLI.

The first slice is intentionally bounded:
- inspect one target session and any recent continuation artifacts if present
- ask Hermes itself for a strict continue/stop decision
- optionally execute one bounded continuation step

This is a loop controller, not a new autonomous framework.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home
from hermes_loop import LoopRuntime, LoopStore
from hermes_state import SessionDB
from run_agent import AIAgent


def _resolve_target_session(args: Namespace) -> Optional[str]:
    db = SessionDB()
    try:
        resume = getattr(args, "resume", None)
        if resume:
            session = db.get_session(resume)
            return session["id"] if session else None
        continue_last = getattr(args, "continue_last", None)
        if continue_last:
            sessions = db.search_sessions(source="cli", limit=1)
            return sessions[0]["id"] if sessions else None
        sessions = db.search_sessions(source="cli", limit=1)
        return sessions[0]["id"] if sessions else None
    finally:
        db.close()


def _load_recent_jsonl(path: Path, *, session_id: str, goal_id: str | None = None, limit: int = 5) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        rows = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            text = raw.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("session_id") == session_id:
                if goal_id is not None and payload.get("goal_id") != goal_id:
                    continue
                rows.append(payload)
        return rows[-limit:]
    except Exception:
        return []


def _continuation_artifact_dir() -> Path:
    return get_hermes_home() / "logs"


def _append_jsonl_artifact(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def record_background_review(
    *,
    session_id: str,
    goal: str,
    progress_state: str,
    stop_reason: str = "",
    next_prompt: str | None = None,
    result_preview: str = "",
    source: str = "bounded_loop",
    cycle: int | None = None,
    goal_id: str | None = None,
    run_id: str | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "source": source,
        "goal": goal,
        "progress_state": progress_state,
        "stop_reason": stop_reason,
        "next_prompt": next_prompt,
        "result_preview": result_preview,
    }
    if cycle is not None:
        payload["cycle"] = cycle
    if goal_id is not None:
        payload["goal_id"] = goal_id
    if run_id is not None:
        payload["run_id"] = run_id
    _append_jsonl_artifact(_continuation_artifact_dir() / "background_reviews.jsonl", payload)
    return payload


def _extract_json_object(text: str) -> Dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _normalize_loop_prompt(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _stable_goal_id(session_id: str, goal: str) -> str:
    key = f"{session_id}\x00{_normalize_loop_prompt(goal)}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


_OBSERVABLE_EVIDENCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"```"),
    re.compile(r"(?m)^(?:diff --git |\+\+\+ |--- )"),
    re.compile(
        r"(?i)(?:(?<=[\s`'\"(\[{,])|^)[\w./-]+\.(?:py|js|mjs|cjs|ts|tsx|jsx|"
        r"md|rst|yaml|yml|json|toml|ini|cfg|xml|html|css|sh|bash|zsh|sql|"
        r"rs|go|java|kt|swift|c|h|cpp|cc|hpp|rb|php|lua|pl|proto|dart|"
        r"vue|svelte)\b"
    ),
    re.compile(
        r"(?i)\b(?:pytest|unittest|npm|pnpm|yarn|bun|cargo|ruff|mypy|jest|"
        r"vitest|tox|gradle|mvn|make|go\s+test|go\s+build|bash|sh\s+-c|"
        r"git\s+(?:diff|status|log|commit|push|add|checkout|stash|branch|"
        r"merge|rebase))\b"
    ),
    re.compile(r"(?i)\b\d+\s+(?:passed|failed|errors?|skipped|warnings?)\b"),
    re.compile(r"(?m)^\s*\$\s+\S"),
)


def _has_observable_evidence(text: str) -> bool:
    """Deterministic positive-signal check for concrete progress markers.

    Returns True if the response contains any of: fenced code blocks, unified
    diff headers, file paths with source/config extensions, known test/build/
    VCS invocations, test-runner result lines, or shell-prompt style lines.
    Used as a thin gate before any semantic verifier is trusted.
    """
    compact = (text or "").strip()
    if not compact:
        return False
    return any(pat.search(compact) for pat in _OBSERVABLE_EVIDENCE_PATTERNS)



def _normalize_expected_evidence(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()



def _final_response_has_expected_evidence(final_response: str, expected_evidence: str) -> bool:
    marker = _normalize_expected_evidence(expected_evidence)
    if not marker:
        return False
    haystack = _normalize_expected_evidence(final_response)
    return marker in haystack


def _preview_text(text: str, limit: int = 200) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def parse_wake_after_duration_seconds(raw_value: str) -> int | None:
    duration = str(raw_value or "").strip().lower()
    match = re.fullmatch(r"(\d+)([smh])", duration)
    if not match:
        return None
    amount = int(match.group(1))
    if amount <= 0:
        return None
    return amount * {"s": 1, "m": 60, "h": 3600}[match.group(2)]


def format_loop_stop_notice(stop_reason: str, reason: str = "") -> str:
    reason_text = (reason or "").strip()
    mapping = {
        "model_stop": reason_text or "No clear bounded next step.",
        "repeated_next_prompt": "repeated next prompt (stall suppression).",
        "empty_continuation_result": "continuation produced no visible result.",
        "duplicate_result_preview": "continuation produced no meaningful new result.",
        "missing_reason": "controller chose wait without a reason.",
        "missing_next_prompt": "controller chose continue without a bounded next prompt.",
        "missing_wake_after": "controller chose wait without a bounded wake_after.",
        "missing_expected_evidence": "controller chose continue without expected evidence.",
        "max_auto_turns_reached": "bounded auto-turn budget reached.",
        "missing_goal": "loop goal is missing.",
        "operator_pause": "loop paused by operator.",
        "operator_stop": "loop stopped by operator.",
        "idle_timeout": "loop idle timeout reached.",
        "max_retry_budget_reached": "loop retry budget exhausted.",
        "recovery_incomplete": "recovered loop had an ambiguous interrupted turn; operator resume is required.",
        "loop_checkpoint_persist_failed": "failed to persist loop checkpoint; stopped conservatively.",
        "loop_event_persist_failed": "failed to persist loop event; stopped conservatively.",
        "progress_verifier_done": reason_text or "latest continuation appears effectively complete.",
        "progress_verifier_stalled": reason_text or "latest continuation did not materially advance the goal.",
        "missing_observable_evidence": reason_text or "continuation lacked observable evidence (no code, diff, file path, test, or command).",
        "expected_evidence_missing": reason_text or "continuation did not include the expected evidence marker.",
        "loop_goal_artifact_persist_failed": reason_text or "failed to persist loop goal artifact; stopped conservatively.",
        "loop_goal_artifact_missing": reason_text or "loop goal artifact is missing; cannot trust continuation target.",
        "loop_goal_artifact_malformed": reason_text or "loop goal artifact is malformed; cannot trust continuation target.",
        "loop_goal_artifact_mismatch": reason_text or "loop goal artifact goal_id does not match active run; stopping conservatively.",
    }
    detail = mapping.get(stop_reason, reason_text or stop_reason or "unknown reason")
    return f"Loop stopped: {detail} ({stop_reason or 'unknown'})"


def _emit_result(**payload: Any) -> Dict[str, Any]:
    result = {
        "session_id": payload.get("session_id"),
        "goal": payload.get("goal", ""),
        "max_cycles": payload.get("max_cycles", 1),
        "cycles_attempted": payload.get("cycles_attempted", 0),
        "cycles_completed": payload.get("cycles_completed", 0),
        "outcome": payload.get("outcome", "error"),
        "stop_reason": payload.get("stop_reason", "unknown"),
        "decision_reason": payload.get("decision_reason", ""),
        "next_prompt": payload.get("next_prompt"),
        "expected_evidence": payload.get("expected_evidence"),
        "wake_after": payload.get("wake_after"),
        "executed": payload.get("executed", False),
        "result_preview": payload.get("result_preview", ""),
        "exit_code": payload.get("exit_code", 1),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def _emit_launcher_result(**payload: Any) -> Dict[str, Any]:
    result = {
        "session_id": payload.get("session_id"),
        "goal": payload.get("goal", ""),
        "max_runs": payload.get("max_runs", 1),
        "runs_attempted": payload.get("runs_attempted", 0),
        "runs_completed": payload.get("runs_completed", 0),
        "outcome": payload.get("outcome", "error"),
        "stop_reason": payload.get("stop_reason", "unknown"),
        "exit_code": payload.get("exit_code", 1),
        "last_result": payload.get("last_result"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def _emit_inspection_result(**payload: Any) -> Dict[str, Any]:
    result = {
        "command": payload.get("command", "loop_inspection"),
        "session_id": payload.get("session_id"),
        "count": payload.get("count", 0),
        "active_only": payload.get("active_only"),
        "checkpoint": payload.get("checkpoint"),
        "events": payload.get("events"),
        "exit_code": payload.get("exit_code", 0),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def _loop_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _checkpoint_runtime_state(checkpoint: Dict[str, Any]) -> str:
    state = str(checkpoint.get("state") or "").strip()
    if state:
        return state
    if bool(checkpoint.get("active")):
        return "waiting"
    if checkpoint.get("stop_reason"):
        return "stopped"
    return "inactive"


def _checkpoint_resumable(checkpoint: Dict[str, Any]) -> bool:
    if "resumable" in checkpoint:
        return bool(checkpoint.get("resumable"))
    return _checkpoint_runtime_state(checkpoint) == "paused"


def _checkpoint_payload_for_write(checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in checkpoint.items() if key not in {"session_id", "session_key"}}


def _cli_loop_session_key(session_id: str) -> str:
    return f"cli:{session_id}"


def _write_cli_loop_checkpoint(session_id: str, checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    checkpoint = dict(checkpoint)
    checkpoint.setdefault("session_id", session_id)
    checkpoint.setdefault("session_key", _cli_loop_session_key(session_id))
    checkpoint["updated_at"] = _loop_now_iso()
    return LoopStore().write_checkpoint(
        session_id=session_id,
        session_key=str(checkpoint.get("session_key") or _cli_loop_session_key(session_id)),
        payload=_checkpoint_payload_for_write(checkpoint),
    )


def _update_loop_checkpoint(session_id: str, updates: Dict[str, Any]) -> Dict[str, Any] | None:
    checkpoint = LoopStore().read_checkpoint(session_id)
    if checkpoint is None:
        return None
    checkpoint.update(updates)
    checkpoint.setdefault("session_id", session_id)
    checkpoint["updated_at"] = _loop_now_iso()
    return LoopStore().write_checkpoint(
        session_id=session_id,
        session_key=str(checkpoint.get("session_key") or ""),
        payload=_checkpoint_payload_for_write(checkpoint),
    )


def _checkpoint_summary_fields(checkpoint: Dict[str, Any]) -> List[tuple[str, Any]]:
    fields = [
        ("session_id", checkpoint.get("session_id")),
        ("session_key", checkpoint.get("session_key")),
        ("state", checkpoint.get("state") or _checkpoint_runtime_state(checkpoint)),
        ("active", checkpoint.get("active")),
        ("updated_at", checkpoint.get("updated_at")),
        ("goal", checkpoint.get("goal")),
        ("remaining_auto_turns", checkpoint.get("remaining_auto_turns")),
        ("resumable", checkpoint.get("resumable") if "resumable" in checkpoint else _checkpoint_resumable(checkpoint)),
        ("stop_reason", checkpoint.get("stop_reason")),
        ("stop_class", checkpoint.get("stop_class")),
        ("stop_message", checkpoint.get("stop_message")),
        ("last_progress_summary", checkpoint.get("last_progress_summary")),
        ("retry_count", checkpoint.get("retry_count")),
        ("max_retry_budget", checkpoint.get("max_retry_budget")),
        ("idle_timeout_seconds", checkpoint.get("idle_timeout_seconds")),
        ("last_activity_at", checkpoint.get("last_activity_at")),
        ("expected_evidence", checkpoint.get("expected_evidence")),
        ("pending_wakeup_at", checkpoint.get("pending_wakeup_at")),
        ("last_prompt", checkpoint.get("last_prompt")),
        ("last_prompt_norm", checkpoint.get("last_prompt_norm")),
        ("inflight_prompt", checkpoint.get("inflight_prompt")),
        ("inflight_started_at", checkpoint.get("inflight_started_at")),
        ("last_result_preview", checkpoint.get("last_result_preview")),
        ("channel_prompt", checkpoint.get("channel_prompt")),
    ]
    return [(key, value) for key, value in fields if value not in (None, "")]


def loop_list_command(args: Namespace) -> Dict[str, Any]:
    active_only = not bool(getattr(args, "all", False))
    checkpoints = LoopStore().list_checkpoints(active_only=active_only)
    if not checkpoints:
        if active_only:
            print("No active persisted loops found.")
        else:
            print("No persisted loops found.")
        return _emit_inspection_result(
            command="list",
            count=0,
            active_only=active_only,
            checkpoint=None,
            events=[],
            exit_code=0,
        )

    heading = "Active persisted loops:" if active_only else "Persisted loops:"
    print(heading)
    for checkpoint in checkpoints:
        session_id = str(checkpoint.get("session_id") or "")
        state = _checkpoint_runtime_state(checkpoint)
        updated_at = str(checkpoint.get("updated_at") or "")
        goal = _preview_text(str(checkpoint.get("goal") or ""), limit=100)
        remaining = checkpoint.get("remaining_auto_turns")
        reason = str(checkpoint.get("stop_reason") or "")
        expected_evidence = str(checkpoint.get("expected_evidence") or "")
        pending_wakeup_at = str(checkpoint.get("pending_wakeup_at") or "")
        suffix_parts = []
        if goal:
            suffix_parts.append(f"goal={goal}")
        if remaining not in (None, ""):
            suffix_parts.append(f"remaining={remaining}")
        if expected_evidence:
            suffix_parts.append(f"expected_evidence={expected_evidence}")
        if pending_wakeup_at:
            suffix_parts.append(f"wakeup_at={pending_wakeup_at}")
        if reason:
            suffix_parts.append(f"stop_reason={reason}")
        suffix = f" {' '.join(suffix_parts)}" if suffix_parts else ""
        print(f"- {session_id} [{state}] updated_at={updated_at}{suffix}")

    return _emit_inspection_result(
        command="list",
        count=len(checkpoints),
        active_only=active_only,
        checkpoint=None,
        events=checkpoints,
        exit_code=0,
    )


def loop_status_command(args: Namespace) -> Dict[str, Any]:
    session_id = (getattr(args, "session_id", "") or "").strip()
    runtime = LoopRuntime()
    checkpoint = runtime.status(session_id)
    if checkpoint is None:
        print(f"Loop session '{session_id}' was not found in persisted artifacts.")
        return _emit_inspection_result(
            command="status",
            session_id=session_id,
            count=0,
            checkpoint=None,
            events=[],
            exit_code=1,
        )

    event_limit = int(getattr(args, "events", 5) or 0)
    events = LoopStore().read_events(session_id, limit=event_limit) if event_limit > 0 else []
    print("Checkpoint summary:")
    for key, value in _checkpoint_summary_fields(checkpoint):
        print(f"- {key}: {value}")

    print("Recent events:")
    if not events:
        print("- none")
    else:
        for event in events:
            recorded_at = str(event.get("recorded_at") or "")
            event_type = str(event.get("event_type") or "unknown")
            details = []
            for key in (
                "stop_reason",
                "stop_class",
                "goal",
                "remaining_auto_turns",
                "last_result_preview",
                "next_prompt",
                "expected_evidence",
                "pending_wakeup_at",
                "deferred",
            ):
                value = event.get(key)
                if value in (None, ""):
                    continue
                if key in {"last_result_preview", "next_prompt"}:
                    value = _preview_text(str(value), limit=100)
                details.append(f"{key}={value}")
            detail_suffix = f" ({', '.join(details)})" if details else ""
            print(f"- {recorded_at} {event_type}{detail_suffix}")

    return _emit_inspection_result(
        command="status",
        session_id=session_id,
        count=1,
        checkpoint=checkpoint,
        events=events,
        exit_code=0,
    )


def loop_pause_command(args: Namespace) -> Dict[str, Any]:
    session_id = (getattr(args, "session_id", "") or "").strip()
    result = LoopRuntime().pause(session_id)
    if not result.get("ok"):
        print(f"Loop session '{session_id}' was not found in persisted artifacts.")
        return _emit_inspection_result(command="pause", session_id=session_id, count=0, checkpoint=None, events=[], exit_code=1)

    updated = result.get("checkpoint")
    print(f"Paused loop '{session_id}'.")
    return _emit_inspection_result(command="pause", session_id=session_id, count=1, checkpoint=updated, events=[], exit_code=0)


def loop_resume_command(args: Namespace) -> Dict[str, Any]:
    session_id = (getattr(args, "session_id", "") or "").strip()
    result = LoopRuntime().resume(session_id)
    if not result.get("ok"):
        checkpoint = result.get("checkpoint")
        error = str(result.get("error") or "")
        if error == "not_found":
            print(f"Loop session '{session_id}' was not found in persisted artifacts.")
            return _emit_inspection_result(command="resume", session_id=session_id, count=0, checkpoint=None, events=[], exit_code=1)
        if error == "not_resumable":
            print(f"Loop session '{session_id}' is not resumable.")
        elif error == "missing_prompt":
            print(f"Loop session '{session_id}' has no persisted prompt to resume.")
        else:
            print(f"Loop session '{session_id}' could not be resumed.")
        return _emit_inspection_result(command="resume", session_id=session_id, count=1 if checkpoint else 0, checkpoint=checkpoint, events=[], exit_code=1)

    updated = result.get("checkpoint") or {}
    print(f"Resumed loop '{session_id}'.")
    if result.get("should_tick_now") and str(updated.get("session_key") or "").startswith("cli:"):
        return loop_command(
            Namespace(
                loop_command="once",
                goal=str(updated.get("goal") or ""),
                resume=session_id,
                continue_last=None,
                dry_run=False,
                model=None,
                provider=None,
                max_turns=None,
                max_cycles=1,
                max_runs=1,
            )
        )
    return _emit_inspection_result(command="resume", session_id=session_id, count=1, checkpoint=updated, events=[], exit_code=0)


def loop_stop_command(args: Namespace) -> Dict[str, Any]:
    session_id = (getattr(args, "session_id", "") or "").strip()
    result = LoopRuntime().stop(session_id)
    if not result.get("ok"):
        print(f"Loop session '{session_id}' was not found in persisted artifacts.")
        return _emit_inspection_result(command="stop", session_id=session_id, count=0, checkpoint=None, events=[], exit_code=1)

    updated = result.get("checkpoint")
    print(format_loop_stop_notice("operator_stop", "Loop stopped by operator."))
    return _emit_inspection_result(command="stop", session_id=session_id, count=1, checkpoint=updated, events=[], exit_code=0)


def _session_runtime_config(session_row: Dict[str, Any], args: Namespace) -> Dict[str, Any]:
    model = getattr(args, "model", None) or session_row.get("model") or None
    provider = getattr(args, "provider", None) or None
    base_url = None
    raw_cfg = session_row.get("model_config")
    if raw_cfg:
        try:
            parsed = json.loads(raw_cfg) if isinstance(raw_cfg, str) else raw_cfg
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            provider = provider or parsed.get("provider")
            base_url = parsed.get("base_url")
    return {"model": model, "provider": provider, "base_url": base_url}


def _recent_history_context(session_id: str, limit: int = 6) -> List[Dict[str, str]]:
    db = SessionDB()
    try:
        history = db.get_messages_as_conversation(session_id) or []
    finally:
        db.close()

    rows: List[Dict[str, str]] = []
    for msg in history[-limit:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        content = _preview_text(str(msg.get("content") or ""), limit=280)
        if role and content:
            rows.append({"role": role, "content": content})
    return rows


def _build_decision_prompt(
    *,
    goal: str,
    session_row: Dict[str, Any],
    recent_history: List[Dict[str, str]],
    reflections: List[Dict[str, Any]],
    gaps: List[Dict[str, Any]],
    background_reviews: List[Dict[str, Any]],
) -> str:
    context = {
        "goal": goal,
        "session_id": session_row.get("id"),
        "title": session_row.get("title") or "",
        "recent_history": recent_history,
        "last_reflections": reflections,
        "last_affordance_gaps": gaps,
        "last_background_reviews": background_reviews,
    }
    return (
        "You are Hermes deciding whether an autonomous continuation loop should run one more step.\n"
        "Given the objective, the recent session transcript, and any runtime artifacts, return ONLY JSON with this schema:\n"
        '{"action":"continue|wait|stop","reason":"short string","next_prompt":"required iff action=continue|wait","wake_after":"required iff action=wait; use <int>s, <int>m, or <int>h","expected_evidence":"required iff action=continue|wait"}.\n'
        "Rules:\n"
        "- continue only if there is one clear bounded next step\n"
        "- use wait only for a bounded deferred continuation that should resume later\n"
        "- stop on ambiguity, convergence, repeated/stalled motion, or real user-level tradeoff\n"
        "- keep next_prompt concrete and directly executable\n"
        "- for continue, expected_evidence must be a short literal marker we expect to observe in the next final response\n"
        "- for wait, wake_after must use only s, m, or h units\n"
        "- use the recent_history as the primary grounding signal\n\n"
        f"Context:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def _build_progress_verifier_prompt(
    *,
    goal: str,
    session_row: Dict[str, Any],
    recent_history: List[Dict[str, str]],
    background_reviews: List[Dict[str, Any]],
    final_response: str,
    expected_evidence: str = "",
) -> str:
    context = {
        "goal": goal,
        "session_id": session_row.get("id"),
        "title": session_row.get("title") or "",
        "recent_history": recent_history,
        "last_background_reviews": background_reviews,
        "latest_final_response": _preview_text(final_response, limit=400),
        "expected_evidence": (expected_evidence or "").strip(),
    }
    return (
        "You are Hermes verifying whether the latest bounded continuation step made real progress.\n"
        "Return ONLY JSON with this schema:\n"
        '{"verdict":"progress|stalled|done","reason":"short string","should_continue":true|false}.\n'
        "Rules:\n"
        "- verdict=progress only if the latest response materially advances the goal\n"
        "- verdict=stalled if the response mostly restates status, repeats prior content, or does not create meaningful progress\n"
        "- verdict=done if the latest response indicates the bounded objective is effectively complete or no further bounded step is warranted\n"
        "- use recent_history as the primary grounding signal\n"
        "- keep the reason concise and factual\n\n"
        f"Context:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def _decide_once(goal: str, session_row: Dict[str, Any], args: Namespace) -> Dict[str, Any]:
    session_id = session_row["id"]
    goal_id = _stable_goal_id(session_id, goal)
    artifacts_dir = _continuation_artifact_dir()
    recent_history = _recent_history_context(session_id)
    reflections = _load_recent_jsonl(artifacts_dir / "reflections.jsonl", session_id=session_id)
    gaps = _load_recent_jsonl(artifacts_dir / "affordance_gaps.jsonl", session_id=session_id)
    background_reviews = _load_recent_jsonl(artifacts_dir / "background_reviews.jsonl", session_id=session_id, goal_id=goal_id)
    runtime = _session_runtime_config(session_row, args)
    agent = AIAgent(
        model=runtime.get("model") or "",
        provider=runtime.get("provider"),
        base_url=runtime.get("base_url"),
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        enabled_toolsets=[],
        max_iterations=4,
    )
    result = agent.run_conversation(
        _build_decision_prompt(
            goal=goal,
            session_row=session_row,
            recent_history=recent_history,
            reflections=reflections,
            gaps=gaps,
            background_reviews=background_reviews,
        )
    )
    payload = _extract_json_object(result.get("final_response", ""))
    if not payload or payload.get("action") not in {"continue", "wait", "stop"}:
        return {
            "action": "stop",
            "reason": "Invalid decision payload from Hermes.",
            "stop_reason": "invalid_decision_payload",
        }
    if payload["action"] == "continue" and not (payload.get("next_prompt") or "").strip():
        return {
            "action": "stop",
            "reason": "Hermes chose continue without a bounded next prompt.",
            "stop_reason": "missing_next_prompt",
        }
    if payload["action"] == "continue" and not (payload.get("expected_evidence") or "").strip():
        return {
            "action": "stop",
            "reason": "Hermes chose continue without expected evidence.",
            "stop_reason": "missing_expected_evidence",
        }
    if payload["action"] == "wait" and not (payload.get("reason") or "").strip():
        return {
            "action": "stop",
            "reason": "Hermes chose wait without a reason.",
            "stop_reason": "missing_reason",
        }
    if payload["action"] == "wait" and not (payload.get("next_prompt") or "").strip():
        return {
            "action": "stop",
            "reason": "Hermes chose wait without a bounded next prompt.",
            "stop_reason": "missing_next_prompt",
        }
    if payload["action"] == "wait" and not (payload.get("expected_evidence") or "").strip():
        return {
            "action": "stop",
            "reason": "Hermes chose wait without expected evidence.",
            "stop_reason": "missing_expected_evidence",
        }
    if payload["action"] == "wait" and parse_wake_after_duration_seconds(str(payload.get("wake_after") or "")) is None:
        return {
            "action": "stop",
            "reason": "Hermes chose wait without a bounded wake_after.",
            "stop_reason": "missing_wake_after",
        }
    if payload["action"] == "stop":
        payload.setdefault("stop_reason", "model_stop")
    elif payload["action"] in {"continue", "wait"}:
        payload["reason"] = str(payload.get("reason") or "").strip()
        payload["next_prompt"] = str(payload.get("next_prompt") or "").strip()
        payload["expected_evidence"] = str(payload.get("expected_evidence") or "").strip()
        if payload["action"] == "wait":
            payload["wake_after"] = str(payload.get("wake_after") or "").strip().lower()
    return payload


def decide_continuation_for_session(
    session_id: str,
    goal: str,
    *,
    model: str | None = None,
    provider: str | None = None,
) -> Dict[str, Any]:
    """Return a bounded continue/stop decision for an explicit session id.

    This exposes the controller logic to non-CLI surfaces like gateway /loop
    without requiring them to shell out through the CLI runner.
    """
    if not (session_id or "").strip():
        return {
            "action": "stop",
            "reason": "Missing target session id.",
            "stop_reason": "missing_session_id",
        }

    db = SessionDB()
    try:
        session_row = db.get_session(session_id)
    finally:
        db.close()

    if not session_row:
        return {
            "action": "stop",
            "reason": f"Session '{session_id}' was not found.",
            "stop_reason": "session_not_found",
        }

    args = Namespace(model=model, provider=provider)
    goal = goal.strip()
    try:
        from hermes_loop import LoopStore
        _goal_artifact = LoopStore().read_goal_artifact(session_id)
    except Exception:
        _goal_artifact = None
    if _goal_artifact is not None:
        _artifact_goal_id = str(_goal_artifact.get("goal_id") or "").strip()
        _artifact_goal_text = str(_goal_artifact.get("goal_text") or "").strip()
        _expected_goal_id = _stable_goal_id(session_id, goal)
        if _artifact_goal_id and _artifact_goal_id != _expected_goal_id:
            return {
                "action": "stop",
                "reason": "Goal artifact goal_id does not match expected goal; stopping conservatively.",
                "stop_reason": "goal_artifact_mismatch",
                "session_id": session_id,
            }
        if _artifact_goal_text:
            goal = _artifact_goal_text
    decision = _decide_once(goal, session_row, args)
    decision.setdefault("session_id", session_id)
    return decision


def verify_progress_for_session(
    session_id: str,
    goal: str,
    final_response: str,
    *,
    expected_evidence: str = "",
    model: str | None = None,
    provider: str | None = None,
) -> Dict[str, Any]:
    """Return a bounded semantic progress verdict for an explicit session id."""
    if not (session_id or "").strip():
        return {
            "verdict": "stalled",
            "reason": "Missing target session id.",
            "should_continue": False,
            "stop_reason": "missing_session_id",
        }

    db = SessionDB()
    try:
        session_row = db.get_session(session_id)
    finally:
        db.close()

    if not session_row:
        return {
            "verdict": "stalled",
            "reason": f"Session '{session_id}' was not found.",
            "should_continue": False,
            "stop_reason": "session_not_found",
        }

    goal = goal.strip()
    goal_id = _stable_goal_id(session_id, goal)
    try:
        from hermes_loop import LoopStore
        _goal_artifact = LoopStore().read_goal_artifact(session_id)
    except Exception:
        _goal_artifact = None
    if _goal_artifact is not None:
        _artifact_goal_id = str(_goal_artifact.get("goal_id") or "").strip()
        _artifact_goal_text = str(_goal_artifact.get("goal_text") or "").strip()
        if _artifact_goal_id and _artifact_goal_id != goal_id:
            return {
                "verdict": "stalled",
                "reason": "Goal artifact goal_id does not match expected goal; stopping conservatively.",
                "should_continue": False,
                "stop_reason": "goal_artifact_mismatch",
            }
        if _artifact_goal_text:
            goal = _artifact_goal_text
    artifacts_dir = _continuation_artifact_dir()
    recent_history = _recent_history_context(session_id)
    background_reviews = _load_recent_jsonl(artifacts_dir / "background_reviews.jsonl", session_id=session_id, goal_id=goal_id)
    runtime = _session_runtime_config(session_row, Namespace(model=model, provider=provider))
    agent = AIAgent(
        model=runtime.get("model") or "",
        provider=runtime.get("provider"),
        base_url=runtime.get("base_url"),
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        enabled_toolsets=[],
        max_iterations=4,
    )
    result = agent.run_conversation(
        _build_progress_verifier_prompt(
            goal=goal,
            session_row=session_row,
            recent_history=recent_history,
            background_reviews=background_reviews,
            final_response=final_response,
            expected_evidence=expected_evidence,
        )
    )
    payload = _extract_json_object(result.get("final_response", ""))
    if not payload or payload.get("verdict") not in {"progress", "stalled", "done"}:
        return {
            "verdict": "stalled",
            "reason": "Invalid verifier payload; defaulting to stalled.",
            "should_continue": False,
            "stop_reason": "invalid_progress_verifier_payload",
        }
    if not isinstance(payload.get("should_continue"), bool):
        payload["should_continue"] = payload.get("verdict") == "progress"
    payload.setdefault("reason", "")
    return payload


def _run_single_continuation(session_row: Dict[str, Any], next_prompt: str, args: Namespace) -> Dict[str, Any]:
    db = SessionDB()
    try:
        history = db.get_messages_as_conversation(session_row["id"])
    finally:
        db.close()
    runtime = _session_runtime_config(session_row, args)
    agent = AIAgent(
        model=runtime.get("model") or "",
        provider=runtime.get("provider"),
        base_url=runtime.get("base_url"),
        quiet_mode=True,
        session_id=session_row["id"],
    )
    return agent.run_conversation(next_prompt, conversation_history=history)


def loop_command(args: Namespace) -> Dict[str, Any]:
    goal = (getattr(args, "goal", "") or "").strip()
    if not goal:
        print("Error: --goal is required.")
        return _emit_result(
            session_id=None,
            goal="",
            max_cycles=0,
            cycles_attempted=0,
            cycles_completed=0,
            outcome="error",
            stop_reason="missing_goal",
            executed=False,
            exit_code=1,
        )

    session_id = _resolve_target_session(args)
    if not session_id:
        print("Error: No target session found.")
        return _emit_result(
            session_id=None,
            goal=goal,
            max_cycles=max(1, int(getattr(args, "max_cycles", 1) or 1)),
            cycles_attempted=0,
            cycles_completed=0,
            outcome="error",
            stop_reason="no_target_session",
            executed=False,
            exit_code=1,
        )

    goal_id = _stable_goal_id(session_id, goal)
    run_id = _new_run_id()
    max_cycles = max(1, int(getattr(args, "max_cycles", 1) or 1))
    session_row: Dict[str, Any] | None = None
    previous_prompt_norm: str | None = None
    cycles_completed = 0
    last_next_prompt: str | None = None
    last_expected_evidence: str | None = None
    last_result_preview = ""
    for cycle in range(1, max_cycles + 1):
        print(f"Cycle {cycle}/{max_cycles}")
        db = SessionDB()
        try:
            session_row = db.get_session(session_id)
        finally:
            db.close()
        if not session_row:
            print(f"Error: Session '{session_id}' not found.")
            return _emit_result(
                session_id=session_id,
                goal=goal,
                max_cycles=max_cycles,
                cycles_attempted=cycle,
                cycles_completed=cycles_completed,
                outcome="error",
                stop_reason="session_not_found",
                executed=cycles_completed > 0,
                result_preview=last_result_preview,
                exit_code=1,
            )

        decision = _decide_once(goal, session_row, args)
        action = decision.get("action", "stop")
        reason = decision.get("reason", "")
        print(f"Decision: {action}")
        if reason:
            print(f"Reason:   {reason}")

        if action == "wait":
            next_prompt = (decision.get("next_prompt") or "").strip()
            expected_evidence = (decision.get("expected_evidence") or "").strip()
            wake_after = str(decision.get("wake_after") or "").strip().lower()
            last_next_prompt = next_prompt
            last_expected_evidence = expected_evidence
            print(f"Wake after: {wake_after}")
            print(f"Prompt:   {next_prompt}")
            record_background_review(
                session_id=session_id,
                goal=goal,
                progress_state="wait",
                stop_reason="wait_requested",
                next_prompt=next_prompt,
                result_preview=last_result_preview,
                cycle=cycle,
                goal_id=goal_id,
                run_id=run_id,
            )
            return _emit_result(
                session_id=session_id,
                goal=goal,
                max_cycles=max_cycles,
                cycles_attempted=cycle,
                cycles_completed=cycles_completed,
                outcome="waiting",
                stop_reason="wait_requested",
                decision_reason=reason,
                next_prompt=next_prompt,
                expected_evidence=expected_evidence,
                wake_after=wake_after,
                executed=cycles_completed > 0,
                result_preview=last_result_preview,
                exit_code=0,
            )

        if action != "continue":
            stop_reason = decision.get("stop_reason") or "model_stop"
            outcome = "error" if stop_reason in {"invalid_decision_payload", "missing_next_prompt", "missing_expected_evidence"} else "stopped"
            exit_code = 1 if outcome == "error" else 0
            record_background_review(
                session_id=session_id,
                goal=goal,
                progress_state="stop",
                stop_reason=stop_reason,
                next_prompt=last_next_prompt,
                result_preview=last_result_preview,
                cycle=cycle,
                goal_id=goal_id,
                run_id=run_id,
            )
            return _emit_result(
                session_id=session_id,
                goal=goal,
                max_cycles=max_cycles,
                cycles_attempted=cycle,
                cycles_completed=cycles_completed,
                outcome=outcome,
                stop_reason=stop_reason,
                decision_reason=reason,
                next_prompt=last_next_prompt,
                expected_evidence=last_expected_evidence,
                executed=cycles_completed > 0,
                result_preview=last_result_preview,
                exit_code=exit_code,
            )

        next_prompt = (decision.get("next_prompt") or "").strip()
        expected_evidence = (decision.get("expected_evidence") or "").strip()
        last_next_prompt = next_prompt
        last_expected_evidence = expected_evidence
        next_prompt_norm = _normalize_loop_prompt(next_prompt)
        if previous_prompt_norm is not None and next_prompt_norm == previous_prompt_norm:
            print("Reason:   Stopped: repeated next prompt from previous cycle (stall suppression).")
            record_background_review(
                session_id=session_id,
                goal=goal,
                progress_state="repeated_prompt",
                stop_reason="repeated_next_prompt",
                next_prompt=next_prompt,
                result_preview=last_result_preview,
                cycle=cycle,
                goal_id=goal_id,
                run_id=run_id,
            )
            return _emit_result(
                session_id=session_id,
                goal=goal,
                max_cycles=max_cycles,
                cycles_attempted=cycle,
                cycles_completed=cycles_completed,
                outcome="stopped",
                stop_reason="repeated_next_prompt",
                decision_reason=reason,
                next_prompt=next_prompt,
                executed=cycles_completed > 0,
                result_preview=last_result_preview,
                exit_code=0,
            )
        previous_prompt_norm = next_prompt_norm
        print(f"Prompt:   {next_prompt}")
        if getattr(args, "dry_run", False):
            print("Dry run: continuation step not executed.")
            record_background_review(
                session_id=session_id,
                goal=goal,
                progress_state="dry_run",
                stop_reason="dry_run",
                next_prompt=next_prompt,
                result_preview=last_result_preview,
                cycle=cycle,
                goal_id=goal_id,
                run_id=run_id,
            )
            return _emit_result(
                session_id=session_id,
                goal=goal,
                max_cycles=max_cycles,
                cycles_attempted=cycle,
                cycles_completed=cycles_completed,
                outcome="dry_run",
                stop_reason="dry_run",
                decision_reason=reason,
                next_prompt=next_prompt,
                executed=cycles_completed > 0,
                result_preview=last_result_preview,
                exit_code=0,
            )

        result = _run_single_continuation(session_row, next_prompt, args)
        final_response = result.get("final_response", "")
        result_preview = _preview_text(final_response)
        if not result_preview:
            print("Reason:   Stopped: continuation produced no visible result.")
            record_background_review(
                session_id=session_id,
                goal=goal,
                progress_state="empty_result",
                stop_reason="empty_continuation_result",
                next_prompt=next_prompt,
                result_preview=last_result_preview,
                cycle=cycle,
                goal_id=goal_id,
                run_id=run_id,
            )
            return _emit_result(
                session_id=session_id,
                goal=goal,
                max_cycles=max_cycles,
                cycles_attempted=cycle,
                cycles_completed=cycles_completed,
                outcome="stopped",
                stop_reason="empty_continuation_result",
                decision_reason=reason,
                next_prompt=next_prompt,
                executed=cycles_completed > 0,
                result_preview=last_result_preview,
                exit_code=0,
            )
        if last_result_preview and result_preview == last_result_preview:
            print("Reason:   Stopped: continuation produced no meaningful new result preview.")
            record_background_review(
                session_id=session_id,
                goal=goal,
                progress_state="duplicate_result",
                stop_reason="duplicate_result_preview",
                next_prompt=next_prompt,
                result_preview=last_result_preview,
                cycle=cycle,
                goal_id=goal_id,
                run_id=run_id,
            )
            return _emit_result(
                session_id=session_id,
                goal=goal,
                max_cycles=max_cycles,
                cycles_attempted=cycle,
                cycles_completed=cycles_completed,
                outcome="stopped",
                stop_reason="duplicate_result_preview",
                decision_reason=reason,
                next_prompt=next_prompt,
                executed=cycles_completed > 0,
                result_preview=last_result_preview,
                exit_code=0,
            )
        if not _has_observable_evidence(final_response):
            print("Reason:   Stopped: no observable evidence (file/test/command/code/diff) in continuation result.")
            record_background_review(
                session_id=session_id,
                goal=goal,
                progress_state="missing_observable_evidence",
                stop_reason="missing_observable_evidence",
                next_prompt=next_prompt,
                result_preview=result_preview,
                cycle=cycle,
                goal_id=goal_id,
                run_id=run_id,
            )
            return _emit_result(
                session_id=session_id,
                goal=goal,
                max_cycles=max_cycles,
                cycles_attempted=cycle,
                cycles_completed=cycles_completed,
                outcome="stopped",
                stop_reason="missing_observable_evidence",
                decision_reason=reason,
                next_prompt=next_prompt,
                executed=cycles_completed > 0,
                result_preview=last_result_preview,
                exit_code=0,
            )
        last_result_preview = result_preview
        record_background_review(
            session_id=session_id,
            goal=goal,
            progress_state="meaningful_result",
            next_prompt=next_prompt,
            result_preview=result_preview,
            cycle=cycle,
            goal_id=goal_id,
            run_id=run_id,
        )
        cycles_completed += 1
        if final_response:
            print()
            print(final_response)

    print(f"Stopped after reaching max cycles ({max_cycles}).")
    record_background_review(
        session_id=session_id,
        goal=goal,
        progress_state="max_cycles",
        stop_reason="max_cycles_reached",
        next_prompt=last_next_prompt,
        result_preview=last_result_preview,
        cycle=max_cycles,
        goal_id=goal_id,
        run_id=run_id,
    )
    return _emit_result(
        session_id=session_id,
        goal=goal,
        max_cycles=max_cycles,
        cycles_attempted=max_cycles,
        cycles_completed=cycles_completed,
        outcome="continued",
        stop_reason="max_cycles_reached",
        decision_reason="",
        next_prompt=last_next_prompt,
        executed=cycles_completed > 0,
        result_preview=last_result_preview,
        exit_code=0,
    )


def loop_run_command(args: Namespace) -> Dict[str, Any]:
    goal = (getattr(args, "goal", "") or "").strip()
    max_runs = max(1, int(getattr(args, "max_runs", 1) or 1))
    last_result: Dict[str, Any] | None = None
    runs_completed = 0

    base_args = vars(args).copy()
    base_args["max_cycles"] = 1
    base_args["loop_command"] = "once"
    child_args = Namespace(**base_args)

    for run in range(1, max_runs + 1):
        print(f"Run {run}/{max_runs}")
        last_result = loop_command(child_args)
        outcome = last_result.get("outcome")
        if outcome == "continued":
            runs_completed += 1
            continue
        if outcome in {"waiting", "stopped", "dry_run", "error"}:
            return _emit_launcher_result(
                session_id=last_result.get("session_id"),
                goal=goal,
                max_runs=max_runs,
                runs_attempted=run,
                runs_completed=runs_completed,
                outcome=outcome,
                stop_reason=last_result.get("stop_reason", "unknown"),
                exit_code=last_result.get("exit_code", 1),
                last_result=last_result,
            )
        return _emit_launcher_result(
            session_id=last_result.get("session_id"),
            goal=goal,
            max_runs=max_runs,
            runs_attempted=run,
            runs_completed=runs_completed,
            outcome="error",
            stop_reason="unexpected_child_outcome",
            exit_code=1,
            last_result=last_result,
        )

    print(f"Stopped after reaching max runs ({max_runs}).")
    return _emit_launcher_result(
        session_id=(last_result or {}).get("session_id"),
        goal=goal,
        max_runs=max_runs,
        runs_attempted=max_runs,
        runs_completed=runs_completed,
        outcome="continued",
        stop_reason="max_runs_reached",
        exit_code=0,
        last_result=last_result,
    )
