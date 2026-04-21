from __future__ import annotations

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
    def _cli_session_key(session_id: str) -> str:
        return f"cli:{session_id}"
