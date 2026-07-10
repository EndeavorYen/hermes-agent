from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state import StoryVideoRunContext


_AUDIT_LOCK = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_provider(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if not raw:
        return ""
    if "openai" in raw or "codex" in raw or "gpt-image" in raw:
        return "openai-codex" if "codex" in raw else "openai"
    if "grok" in raw or "x.ai" in raw or raw in {"xai", "xai-oauth"}:
        return "xai-oauth" if "oauth" in raw else "xai"
    return raw


@dataclass(frozen=True)
class ProviderAuditEvent:
    kind: str
    phase: str
    provider: str
    model: str
    status: str
    tool: str = ""
    session_id: str = ""
    turn_id: str = ""
    request_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_utc_now)


@dataclass(frozen=True)
class ProviderAuditResult:
    ok: bool
    violations: tuple[str, ...]
    event_count: int


class ProviderAudit:
    def __init__(self, context: StoryVideoRunContext) -> None:
        self.context = context
        self.path = context.project_dir / "manifests" / "provider_audit.json"

    def append_event(self, event: ProviderAuditEvent) -> None:
        with _AUDIT_LOCK:
            payload = self._load()
            payload["events"].append(asdict(event))
            self._write(payload)

    def validate(self) -> ProviderAuditResult:
        payload = self._load()
        violations: list[str] = []
        forbidden = {
            normalize_provider(value)
            for value in self.context.provider_policy.get("forbidden", [])
        }
        for index, event in enumerate(payload.get("events") or []):
            if not isinstance(event, dict):
                violations.append(f"event[{index}] is malformed")
                continue
            provider = normalize_provider(event.get("provider"))
            status = str(event.get("status") or "").lower()
            kind = str(event.get("kind") or "").lower()
            if status == "blocked":
                continue
            if provider in forbidden or provider.startswith("xai"):
                violations.append(
                    f"event[{index}] used forbidden provider {provider or '<missing>'}"
                )
            if kind in {"api", "image", "tool"} and status in {"ok", "sent", "success"}:
                if not provider:
                    violations.append(f"event[{index}] has unclassified provider")
        return ProviderAuditResult(
            ok=not violations,
            violations=tuple(violations),
            event_count=len(payload.get("events") or []),
        )

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {
                "schema": "story_video_provider_audit_v1",
                "run_id": self.context.run_id,
                "project_id": self.context.project_id,
                "policy": self.context.provider_policy,
                "events": [],
            }
        if not isinstance(payload.get("events"), list):
            payload["events"] = []
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

