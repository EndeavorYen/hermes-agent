"""Thin autonomous continuation loop for Hermes CLI.

The first slice is intentionally bounded:
- inspect one target session and any recent continuation artifacts if present
- ask Hermes itself for a strict continue/stop decision
- optionally execute one bounded continuation step

This is a loop controller, not a new autonomous framework.
"""

from __future__ import annotations

import json
import re
from argparse import Namespace
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home
from hermes_loop import LoopStore
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


def _load_recent_jsonl(path: Path, *, session_id: str, limit: int = 5) -> List[Dict[str, Any]]:
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


def _preview_text(text: str, limit: int = 200) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def format_loop_stop_notice(stop_reason: str, reason: str = "") -> str:
    reason_text = (reason or "").strip()
    mapping = {
        "model_stop": reason_text or "No clear bounded next step.",
        "repeated_next_prompt": "repeated next prompt (stall suppression).",
        "empty_continuation_result": "continuation produced no visible result.",
        "duplicate_result_preview": "continuation produced no meaningful new result.",
        "missing_next_prompt": "controller chose continue without a bounded next prompt.",
        "max_auto_turns_reached": "bounded auto-turn budget reached.",
        "missing_goal": "loop goal is missing.",
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


def _checkpoint_summary_fields(checkpoint: Dict[str, Any]) -> List[tuple[str, Any]]:
    fields = [
        ("session_id", checkpoint.get("session_id")),
        ("session_key", checkpoint.get("session_key")),
        ("active", checkpoint.get("active")),
        ("updated_at", checkpoint.get("updated_at")),
        ("goal", checkpoint.get("goal")),
        ("remaining_auto_turns", checkpoint.get("remaining_auto_turns")),
        ("stop_reason", checkpoint.get("stop_reason")),
        ("last_prompt", checkpoint.get("last_prompt")),
        ("last_prompt_norm", checkpoint.get("last_prompt_norm")),
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
        active = bool(checkpoint.get("active", False))
        updated_at = str(checkpoint.get("updated_at") or "")
        goal = _preview_text(str(checkpoint.get("goal") or ""), limit=100)
        status = "active" if active else "inactive"
        suffix = f" goal={goal}" if goal else ""
        print(f"- {session_id} [{status}] updated_at={updated_at}{suffix}")

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
    checkpoint = LoopStore().read_checkpoint(session_id)
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
            for key in ("stop_reason", "goal", "remaining_auto_turns", "last_result_preview"):
                value = event.get(key)
                if value in (None, ""):
                    continue
                if key == "last_result_preview":
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
        '{"action":"continue|stop","reason":"short string","next_prompt":"required iff action=continue"}.\n'
        "Rules:\n"
        "- continue only if there is one clear bounded next step\n"
        "- stop on ambiguity, convergence, repeated/stalled motion, or real user-level tradeoff\n"
        "- keep next_prompt concrete and directly executable\n"
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
) -> str:
    context = {
        "goal": goal,
        "session_id": session_row.get("id"),
        "title": session_row.get("title") or "",
        "recent_history": recent_history,
        "last_background_reviews": background_reviews,
        "latest_final_response": _preview_text(final_response, limit=400),
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
    artifacts_dir = _continuation_artifact_dir()
    recent_history = _recent_history_context(session_id)
    reflections = _load_recent_jsonl(artifacts_dir / "reflections.jsonl", session_id=session_id)
    gaps = _load_recent_jsonl(artifacts_dir / "affordance_gaps.jsonl", session_id=session_id)
    background_reviews = _load_recent_jsonl(artifacts_dir / "background_reviews.jsonl", session_id=session_id)
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
    if not payload or payload.get("action") not in {"continue", "stop"}:
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
    if payload["action"] == "stop":
        payload.setdefault("stop_reason", "model_stop")
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
    decision = _decide_once(goal.strip(), session_row, args)
    decision.setdefault("session_id", session_id)
    return decision


def verify_progress_for_session(
    session_id: str,
    goal: str,
    final_response: str,
    *,
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

    artifacts_dir = _continuation_artifact_dir()
    recent_history = _recent_history_context(session_id)
    background_reviews = _load_recent_jsonl(artifacts_dir / "background_reviews.jsonl", session_id=session_id)
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
            goal=goal.strip(),
            session_row=session_row,
            recent_history=recent_history,
            background_reviews=background_reviews,
            final_response=final_response,
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

    max_cycles = max(1, int(getattr(args, "max_cycles", 1) or 1))
    session_row: Dict[str, Any] | None = None
    previous_prompt_norm: str | None = None
    cycles_completed = 0
    last_next_prompt: str | None = None
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

        if action != "continue":
            stop_reason = decision.get("stop_reason") or "model_stop"
            outcome = "error" if stop_reason in {"invalid_decision_payload", "missing_next_prompt"} else "stopped"
            exit_code = 1 if outcome == "error" else 0
            record_background_review(
                session_id=session_id,
                goal=goal,
                progress_state="stop",
                stop_reason=stop_reason,
                next_prompt=last_next_prompt,
                result_preview=last_result_preview,
                cycle=cycle,
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
                executed=cycles_completed > 0,
                result_preview=last_result_preview,
                exit_code=exit_code,
            )

        next_prompt = (decision.get("next_prompt") or "").strip()
        last_next_prompt = next_prompt
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
        last_result_preview = result_preview
        record_background_review(
            session_id=session_id,
            goal=goal,
            progress_state="meaningful_result",
            next_prompt=next_prompt,
            result_preview=result_preview,
            cycle=cycle,
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
