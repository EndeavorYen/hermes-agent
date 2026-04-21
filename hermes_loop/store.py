from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home


class LoopStore:
    """Minimal filesystem persistence for gateway loop checkpoints/events."""

    def __init__(self, root: Path | None = None):
        self.root = root or (get_hermes_home() / "state" / "loops")

    def session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    def checkpoint_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "checkpoint.json"

    def events_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "events.jsonl"

    def write_checkpoint(
        self,
        *,
        session_id: str,
        session_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        checkpoint = {
            "session_id": session_id,
            "session_key": session_key,
            "updated_at": self._timestamp(),
        }
        checkpoint.update(payload)
        path = self.checkpoint_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        return checkpoint

    def read_checkpoint(self, session_id: str) -> dict[str, Any] | None:
        return self._read_json_dict(self.checkpoint_path(session_id))

    def list_checkpoints(self, active_only: bool = False) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        checkpoints: list[dict[str, Any]] = []
        for session_dir in (path for path in self.root.iterdir() if path.is_dir()):
            checkpoint = self._read_json_dict(session_dir / "checkpoint.json")
            if checkpoint is None:
                continue
            if active_only and not bool(checkpoint.get("active")):
                continue
            checkpoints.append(checkpoint)
        checkpoints.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return checkpoints

    def append_event(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event = {
            "session_id": session_id,
            "event_type": event_type,
            "recorded_at": self._timestamp(),
        }
        event.update(payload)
        path = self.events_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def read_events(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        path = self.events_path(session_id)
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        events.append(event)
        except OSError:
            return []
        if limit is not None and limit > 0:
            return events[-limit:]
        return events

    def mark_stopped(
        self,
        *,
        session_id: str,
        session_key: str,
        stop_reason: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        checkpoint_payload = dict(payload)
        checkpoint_payload.update({"active": False, "stop_reason": stop_reason})
        checkpoint = self.write_checkpoint(
            session_id=session_id,
            session_key=session_key,
            payload=checkpoint_payload,
        )
        self.append_event(
            session_id=session_id,
            event_type="loop_stopped",
            payload={**payload, "stop_reason": stop_reason},
        )
        return checkpoint

    @staticmethod
    def _read_json_dict(path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()
