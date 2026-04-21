from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .store import LoopStore


class LoopRuntime:
    """Minimal shared runtime/control-plane helper for persisted loop checkpoints."""

    def __init__(self, store: LoopStore | None = None):
        self.store = store or LoopStore()

    def status(self, session_id: str) -> dict[str, Any] | None:
        checkpoint = self.store.read_checkpoint(session_id)
        if checkpoint is None:
            return None
        return self._normalize_checkpoint(checkpoint, session_id=session_id)

    def pause(self, session_id: str) -> dict[str, Any]:
        checkpoint = self.status(session_id)
        if checkpoint is None:
            return self._error("not_found")
        updated = self._write_checkpoint(
            session_id,
            checkpoint,
            {
                "active": False,
                "state": "paused",
                "resumable": True,
                "stop_reason": "operator_pause",
                "stop_class": "user",
                "stop_message": "Loop paused by operator.",
                "pending_wakeup_at": "",
                "last_activity_at": self._now_iso(),
            },
        )
        event = self.store.append_event(
            session_id=session_id,
            event_type="paused",
            payload={
                "stop_reason": "operator_pause",
                "stop_class": "user",
                "message": "Loop paused by operator.",
            },
        )
        return {"ok": True, "checkpoint": updated, "event": event}

    def resume(
        self,
        session_id: str,
        *,
        message: str = "Loop resumed by operator.",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        checkpoint = self.status(session_id)
        if checkpoint is None:
            return self._error("not_found")
        if not self._resumable(checkpoint):
            return self._error("not_resumable", checkpoint=checkpoint)
        if not str(checkpoint.get("last_prompt") or "").strip():
            return self._error("missing_prompt", checkpoint=checkpoint)

        should_tick_now, pending_wakeup_at = self._resume_semantics(checkpoint)
        updated = self._write_checkpoint(
            session_id,
            checkpoint,
            {
                "active": True,
                "state": "waiting",
                "resumable": True,
                "stop_reason": "",
                "stop_class": "",
                "stop_message": "",
                "pending_wakeup_at": pending_wakeup_at,
                "last_activity_at": self._now_iso(),
                "retry_count": 0,
            },
        )
        payload = {
            "message": message,
            "pending_wakeup_at": pending_wakeup_at,
            "should_tick_now": should_tick_now,
        }
        if metadata:
            payload.update(metadata)
        event = self.store.append_event(
            session_id=session_id,
            event_type="resumed",
            payload=payload,
        )
        return {
            "ok": True,
            "checkpoint": updated,
            "event": event,
            "should_tick_now": should_tick_now,
        }

    def stop(self, session_id: str) -> dict[str, Any]:
        checkpoint = self.status(session_id)
        if checkpoint is None:
            return self._error("not_found")
        updated = self._write_checkpoint(
            session_id,
            checkpoint,
            {
                "active": False,
                "state": "stopped",
                "resumable": False,
                "stop_reason": "operator_stop",
                "stop_class": "user",
                "stop_message": "Loop stopped by operator.",
                "pending_wakeup_at": "",
                "last_activity_at": self._now_iso(),
            },
        )
        event = self.store.append_event(
            session_id=session_id,
            event_type="stop_requested",
            payload={
                "stop_reason": "operator_stop",
                "stop_class": "user",
                "message": "Loop stopped by operator.",
            },
        )
        return {"ok": True, "checkpoint": updated, "event": event}

    def finalize_stop(
        self,
        session_id: str,
        *,
        stop_reason: str,
        stop_message: str,
        state: str = "stopped",
        **event_payload: Any,
    ) -> dict[str, Any]:
        checkpoint = self.status(session_id)
        if checkpoint is None:
            return self._error("not_found")
        stop_reason_text = str(stop_reason or "").strip()
        stop_message_text = str(stop_message or "").strip()
        stop_state = str(state or "stopped").strip() or "stopped"
        stop_class = self._stop_class(stop_reason_text)
        checkpoint_updates = dict(event_payload)
        if "result_preview" in event_payload:
            checkpoint_updates.setdefault("last_result_preview", str(event_payload.get("result_preview") or ""))
            checkpoint_updates.setdefault("last_progress_summary", str(event_payload.get("result_preview") or ""))
        if "next_prompt" in event_payload:
            checkpoint_updates.setdefault("last_prompt", str(event_payload.get("next_prompt") or ""))
        try:
            updated = self._write_checkpoint(
                session_id,
                checkpoint,
                {
                    "active": False,
                    "state": stop_state,
                    "resumable": False,
                    "stop_reason": stop_reason_text,
                    "stop_class": stop_class,
                    "stop_message": stop_message_text,
                    "pending_wakeup_at": "",
                    "inflight_prompt": "",
                    "inflight_started_at": "",
                    "last_activity_at": self._now_iso(),
                    **checkpoint_updates,
                },
            )
            event = self.store.append_event(
                session_id=session_id,
                event_type="loop_stopped",
                payload={
                    "goal": str(updated.get("goal") or ""),
                    "goal_id": str(updated.get("goal_id") or ""),
                    "run_id": str(updated.get("run_id") or ""),
                    "stop_reason": stop_reason_text,
                    "stop_class": stop_class,
                    "message": stop_message_text,
                    **event_payload,
                },
            )
        except Exception:
            return self._error("finalize_stop_failed", checkpoint=checkpoint)
        return {"ok": True, "checkpoint": updated, "event": event}

    def apply_validated_stop(
        self,
        session_id: str,
        *,
        stop_reason: str,
        stop_message: str,
        result_preview: str = "",
        **event_payload: Any,
    ) -> dict[str, Any]:
        return self.finalize_stop(
            session_id,
            stop_reason=stop_reason,
            stop_message=stop_message,
            result_preview=result_preview,
            **event_payload,
        )

    def schedule_initial(
        self,
        *,
        session_id: str,
        session_key: str,
        goal: str,
        goal_id: str,
        run_id: str,
        next_prompt: str,
        next_prompt_norm: str,
        expected_evidence: str,
        remaining_auto_turns: int,
        max_retry_budget: int,
        idle_timeout_seconds: int,
        channel_prompt: str | None,
        pending_wakeup_at: str,
        deferred: bool,
    ) -> dict[str, Any]:
        checkpoint = {"session_key": str(session_key or self._cli_session_key(session_id))}
        try:
            updated = self._write_checkpoint(
                session_id,
                checkpoint,
                {
                    "goal": str(goal or ""),
                    "goal_id": str(goal_id or ""),
                    "run_id": str(run_id or ""),
                    "remaining_auto_turns": int(remaining_auto_turns or 0),
                    "last_prompt": str(next_prompt or ""),
                    "last_prompt_norm": str(next_prompt_norm or ""),
                    "last_result_preview": "",
                    "expected_evidence": str(expected_evidence or ""),
                    "channel_prompt": channel_prompt,
                    "active": True,
                    "state": "waiting",
                    "resumable": True,
                    "stop_reason": "",
                    "stop_class": "",
                    "stop_message": "",
                    "last_progress_summary": "",
                    "retry_count": 0,
                    "max_retry_budget": int(max_retry_budget or 0),
                    "idle_timeout_seconds": int(idle_timeout_seconds or 0),
                    "last_activity_at": self._now_iso(),
                    "pending_wakeup_at": str(pending_wakeup_at or ""),
                    "inflight_prompt": "",
                    "inflight_started_at": "",
                },
            )
            event = self.store.append_event(
                session_id=session_id,
                event_type="loop_started",
                payload={
                    "goal": str(goal or ""),
                    "goal_id": str(goal_id or ""),
                    "run_id": str(run_id or ""),
                    "next_prompt": str(next_prompt or ""),
                    "expected_evidence": str(expected_evidence or ""),
                    "remaining_auto_turns": int(remaining_auto_turns or 0),
                    "idle_timeout_seconds": int(idle_timeout_seconds or 0),
                    "max_retry_budget": int(max_retry_budget or 0),
                    "pending_wakeup_at": str(pending_wakeup_at or ""),
                    "deferred": bool(deferred),
                },
            )
        except Exception:
            return self._error("schedule_initial_failed", checkpoint=checkpoint)
        return {"ok": True, "checkpoint": updated, "event": event}

    def schedule_continue(
        self,
        session_id: str,
        *,
        next_prompt: str,
        next_prompt_norm: str,
        expected_evidence: str,
        remaining_auto_turns: int,
        result_preview: str,
    ) -> dict[str, Any]:
        checkpoint = self.status(session_id)
        if checkpoint is None:
            return self._error("not_found")
        try:
            updated = self._write_checkpoint(
                session_id,
                checkpoint,
                {
                    "last_prompt": str(next_prompt or ""),
                    "last_prompt_norm": str(next_prompt_norm or ""),
                    "expected_evidence": str(expected_evidence or ""),
                    "remaining_auto_turns": int(remaining_auto_turns or 0),
                    "last_result_preview": str(result_preview or ""),
                    "last_progress_summary": str(result_preview or ""),
                    "active": True,
                    "state": "waiting",
                    "resumable": True,
                    "stop_reason": "",
                    "stop_class": "",
                    "stop_message": "",
                    "retry_count": 0,
                    "pending_wakeup_at": "",
                    "inflight_prompt": "",
                    "inflight_started_at": "",
                    "last_activity_at": self._now_iso(),
                },
            )
            event = self.store.append_event(
                session_id=session_id,
                event_type="loop_followup_scheduled",
                payload={
                    "goal": str(updated.get("goal") or ""),
                    "goal_id": str(updated.get("goal_id") or ""),
                    "run_id": str(updated.get("run_id") or ""),
                    "next_prompt": str(next_prompt or ""),
                    "expected_evidence": str(expected_evidence or ""),
                    "remaining_auto_turns": int(remaining_auto_turns or 0),
                    "result_preview": str(result_preview or ""),
                },
            )
        except Exception:
            return self._error("schedule_continue_failed", checkpoint=checkpoint)
        return {"ok": True, "checkpoint": updated, "event": event}

    def schedule_wait(
        self,
        session_id: str,
        *,
        next_prompt: str,
        next_prompt_norm: str,
        expected_evidence: str,
        remaining_auto_turns: int,
        result_preview: str,
        pending_wakeup_at: str,
    ) -> dict[str, Any]:
        checkpoint = self.status(session_id)
        if checkpoint is None:
            return self._error("not_found")
        try:
            updated = self._write_checkpoint(
                session_id,
                checkpoint,
                {
                    "last_prompt": str(next_prompt or ""),
                    "last_prompt_norm": str(next_prompt_norm or ""),
                    "expected_evidence": str(expected_evidence or ""),
                    "remaining_auto_turns": int(remaining_auto_turns or 0),
                    "last_result_preview": str(result_preview or ""),
                    "last_progress_summary": str(result_preview or ""),
                    "active": True,
                    "state": "waiting",
                    "resumable": True,
                    "stop_reason": "",
                    "stop_class": "",
                    "stop_message": "",
                    "retry_count": 0,
                    "pending_wakeup_at": str(pending_wakeup_at or ""),
                    "inflight_prompt": "",
                    "inflight_started_at": "",
                    "last_activity_at": self._now_iso(),
                },
            )
            event = self.store.append_event(
                session_id=session_id,
                event_type="loop_followup_scheduled",
                payload={
                    "goal": str(updated.get("goal") or ""),
                    "goal_id": str(updated.get("goal_id") or ""),
                    "run_id": str(updated.get("run_id") or ""),
                    "next_prompt": str(next_prompt or ""),
                    "expected_evidence": str(expected_evidence or ""),
                    "remaining_auto_turns": int(remaining_auto_turns or 0),
                    "result_preview": str(result_preview or ""),
                    "pending_wakeup_at": str(pending_wakeup_at or ""),
                    "deferred": True,
                },
            )
        except Exception:
            return self._error("schedule_wait_failed", checkpoint=checkpoint)
        return {"ok": True, "checkpoint": updated, "event": event}

    def apply_followup_decision(
        self,
        *,
        session_id: str,
        decision: dict[str, Any],
        result_preview: str,
        remaining_auto_turns: int,
        pending_wakeup_at: str = "",
    ) -> dict[str, Any]:
        checkpoint = self.status(session_id)
        if checkpoint is None:
            return {
                **self._error("not_found"),
                "kind": "error",
                "event": None,
                "stop_reason": "",
                "stop_message": "",
                "next_prompt": "",
                "pending_wakeup_at": "",
            }

        action = str((decision or {}).get("action") or "").strip()
        next_prompt = str((decision or {}).get("next_prompt") or "").strip()
        next_prompt_norm = self._normalize_followup_prompt(next_prompt)
        expected_evidence = str((decision or {}).get("expected_evidence") or "").strip()
        result_preview_text = str(result_preview or "")
        pending_wakeup_text = str(pending_wakeup_at or "")

        stop_result: dict[str, Any] | None = None
        if action in {"continue", "wait"} and not next_prompt:
            stop_result = self.finalize_stop(
                session_id,
                stop_reason="missing_next_prompt",
                stop_message="controller chose continue without a bounded next prompt.",
                result_preview=result_preview_text,
            )
        elif action == "wait" and not pending_wakeup_text:
            stop_result = self.finalize_stop(
                session_id,
                stop_reason="missing_wake_after",
                stop_message="controller chose wait without a bounded wake_after.",
                result_preview=result_preview_text,
            )
        elif action in {"continue", "wait"}:
            previous_prompt_norm = str(checkpoint.get("last_prompt_norm") or "")
            if previous_prompt_norm and next_prompt_norm == previous_prompt_norm:
                stop_result = self.finalize_stop(
                    session_id,
                    stop_reason="repeated_next_prompt",
                    stop_message="repeated next prompt (stall suppression).",
                    result_preview=result_preview_text,
                    next_prompt=next_prompt,
                )

        if stop_result is not None:
            if not stop_result.get("ok"):
                return {
                    **stop_result,
                    "kind": "error",
                    "event": stop_result.get("event"),
                    "stop_reason": str(stop_result.get("stop_reason") or ""),
                    "stop_message": str(stop_result.get("stop_message") or ""),
                    "next_prompt": next_prompt,
                    "pending_wakeup_at": pending_wakeup_text,
                }
            updated = dict(stop_result.get("checkpoint") or checkpoint)
            return {
                **stop_result,
                "kind": "stop",
                "checkpoint": updated,
                "event": stop_result.get("event"),
                "stop_reason": str(updated.get("stop_reason") or ""),
                "stop_message": str(updated.get("stop_message") or ""),
                "next_prompt": str(updated.get("last_prompt") or next_prompt),
                "pending_wakeup_at": str(updated.get("pending_wakeup_at") or ""),
            }

        if action == "continue":
            result = self.schedule_continue(
                session_id,
                next_prompt=next_prompt,
                next_prompt_norm=next_prompt_norm,
                expected_evidence=expected_evidence,
                remaining_auto_turns=remaining_auto_turns,
                result_preview=result_preview_text,
            )
            if not result.get("ok"):
                return {
                    **result,
                    "kind": "error",
                    "event": result.get("event"),
                    "stop_reason": "",
                    "stop_message": "",
                    "next_prompt": next_prompt,
                    "pending_wakeup_at": "",
                }
            updated = dict(result.get("checkpoint") or checkpoint)
            return {
                **result,
                "kind": "continue",
                "checkpoint": updated,
                "event": result.get("event"),
                "stop_reason": "",
                "stop_message": "",
                "next_prompt": str(updated.get("last_prompt") or next_prompt),
                "pending_wakeup_at": str(updated.get("pending_wakeup_at") or ""),
            }

        if action == "wait":
            result = self.schedule_wait(
                session_id,
                next_prompt=next_prompt,
                next_prompt_norm=next_prompt_norm,
                expected_evidence=expected_evidence,
                remaining_auto_turns=remaining_auto_turns,
                result_preview=result_preview_text,
                pending_wakeup_at=pending_wakeup_text,
            )
            if not result.get("ok"):
                return {
                    **result,
                    "kind": "error",
                    "event": result.get("event"),
                    "stop_reason": "",
                    "stop_message": "",
                    "next_prompt": next_prompt,
                    "pending_wakeup_at": pending_wakeup_text,
                }
            updated = dict(result.get("checkpoint") or checkpoint)
            return {
                **result,
                "kind": "wait",
                "checkpoint": updated,
                "event": result.get("event"),
                "stop_reason": "",
                "stop_message": "",
                "next_prompt": str(updated.get("last_prompt") or next_prompt),
                "pending_wakeup_at": str(updated.get("pending_wakeup_at") or pending_wakeup_text),
            }

        stop_reason = str((decision or {}).get("stop_reason") or "model_stop").strip() or "model_stop"
        stop_message = str((decision or {}).get("reason") or "").strip() or stop_reason
        result = self.finalize_stop(
            session_id,
            stop_reason=stop_reason,
            stop_message=stop_message,
            result_preview=result_preview_text,
        )
        if not result.get("ok"):
            return {
                **result,
                "kind": "error",
                "event": result.get("event"),
                "stop_reason": stop_reason,
                "stop_message": stop_message,
                "next_prompt": next_prompt,
                "pending_wakeup_at": pending_wakeup_text,
            }
        updated = dict(result.get("checkpoint") or checkpoint)
        return {
            **result,
            "kind": "stop",
            "checkpoint": updated,
            "event": result.get("event"),
            "stop_reason": str(updated.get("stop_reason") or stop_reason),
            "stop_message": str(updated.get("stop_message") or stop_message),
            "next_prompt": str(updated.get("last_prompt") or next_prompt),
            "pending_wakeup_at": str(updated.get("pending_wakeup_at") or ""),
        }

    def _write_checkpoint(self, session_id: str, checkpoint: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        payload = dict(checkpoint)
        payload.update(updates)
        payload["session_id"] = session_id
        payload["session_key"] = str(payload.get("session_key") or self._cli_session_key(session_id))
        payload["updated_at"] = self._now_iso()
        written = self.store.write_checkpoint(
            session_id=session_id,
            session_key=str(payload.get("session_key") or self._cli_session_key(session_id)),
            payload={key: value for key, value in payload.items() if key not in {"session_id", "session_key"}},
        )
        return self._normalize_checkpoint(written, session_id=session_id)

    def _normalize_checkpoint(self, checkpoint: dict[str, Any], *, session_id: str) -> dict[str, Any]:
        normalized = dict(checkpoint)
        normalized["session_id"] = str(normalized.get("session_id") or session_id)
        normalized["session_key"] = str(normalized.get("session_key") or self._cli_session_key(session_id))
        normalized["active"] = bool(normalized.get("active", False))
        normalized["state"] = self._state(normalized)
        normalized["resumable"] = self._resumable(normalized)
        normalized["stop_reason"] = str(normalized.get("stop_reason") or "")
        normalized["stop_class"] = str(normalized.get("stop_class") or "")
        normalized["stop_message"] = str(normalized.get("stop_message") or "")
        normalized["pending_wakeup_at"] = str(normalized.get("pending_wakeup_at") or "")
        normalized["last_prompt"] = str(normalized.get("last_prompt") or "")
        return normalized

    def _resume_semantics(self, checkpoint: dict[str, Any]) -> tuple[bool, str]:
        state = self._state(checkpoint)
        pending_wakeup_at = str(checkpoint.get("pending_wakeup_at") or "")
        if state == "waiting":
            due = self._pending_wakeup_due(pending_wakeup_at)
            return due, "" if due else pending_wakeup_at
        if state == "paused":
            return True, ""
        return False, pending_wakeup_at

    @staticmethod
    def _error(code: str, *, checkpoint: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"ok": False, "error": code, "checkpoint": checkpoint}

    @staticmethod
    def _state(checkpoint: dict[str, Any]) -> str:
        state = str(checkpoint.get("state") or "").strip()
        if state:
            return state
        if bool(checkpoint.get("active")):
            return "waiting"
        if checkpoint.get("stop_reason"):
            return "stopped"
        return "inactive"

    @staticmethod
    def _resumable(checkpoint: dict[str, Any]) -> bool:
        if "resumable" in checkpoint:
            return bool(checkpoint.get("resumable"))
        return LoopRuntime._state(checkpoint) in {"paused", "waiting"}

    @staticmethod
    def _stop_class(stop_reason: str) -> str:
        reason = str(stop_reason or "").strip()
        if reason in {"operator_pause", "operator_stop"}:
            return "user"
        if reason in {"idle_timeout", "max_auto_turns_reached", "max_retry_budget_reached"}:
            return "resource"
        if reason.startswith("progress_verifier") or reason in {
            "duplicate_result_preview",
            "expected_evidence_missing",
            "missing_observable_evidence",
            "repeated_next_prompt",
        }:
            return "verification"
        if reason.startswith("loop_") or reason in {"invalid_loop_checkpoint", "missing_loop_checkpoint", "inactive_loop_checkpoint"}:
            return "runtime_error"
        return "normal"

    @staticmethod
    def _pending_wakeup_due(pending_wakeup_at: str) -> bool:
        text = str(pending_wakeup_at or "").strip()
        if not text:
            return True
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return True
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= datetime.now(timezone.utc)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_followup_prompt(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip()).lower()

    @staticmethod
    def _cli_session_key(session_id: str) -> str:
        return f"cli:{session_id}"
