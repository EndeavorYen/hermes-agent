from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DURATION = "60-120s"
DEFAULT_STYLE = "Bright PICO-8 storybook pixel art v1"
PHASES = ("planning", "keyframes", "batch", "voice", "render", "complete")
DEFAULT_PROVIDER_POLICY: dict[str, Any] = {
    "llm": ["openai", "openai-codex"],
    "image": ["openai", "openai-codex"],
    "tts": ["local-qwen"],
    "render": ["local"],
    "forbidden": ["xai", "xai-oauth", "grok", "grok_web_imagine"],
    "generic_video_body": "forbidden",
    "fallback": "fail_closed",
}

_LOCK = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _planning_only_requested(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or "").casefold())
    return any(
        marker in compact
        for marker in (
            "只規劃",
            "只规划",
            "先不要產圖",
            "先不要产图",
            "先不要產生圖片",
            "先不要生成图片",
            "不要產生任何圖片",
            "不要生成任何图片",
            "不要產圖或產影片",
            "不要产图或产影片",
        )
    )


def _autopilot_command(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or "").casefold())
    return any(
        marker in compact
        for marker in (
            "全自動",
            "全自动",
            "自動完成",
            "自动完成",
            "一直推進",
            "一直推进",
            "直接做到結束",
            "直接做到结束",
            "完整製作並出片",
            "完整制作并出片",
        )
    )


def _split_fields(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[｜|，,]+", text) if part.strip()]


def _strip_start_prefix(text: str) -> str:
    return re.sub(
        r"^\s*(?:故事影片|產影片|story\s*video|story-video)\s*[:：\-]?\s*",
        "",
        text,
        flags=re.I,
    ).strip()


def _slug(text: str) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if ascii_slug:
        return ascii_slug[:64]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    return f"story-video-{digest}"


def _parse_explicit_long_form_start(text: str) -> OperatorCall | None:
    if not re.search(r"故事影片|story[ -]?video", text, re.I):
        return None
    topic_match = re.search(
        r"^\s*(?:幫我|請)?(?:做|製作|產生|生成)(?:一部|一支)?\s*"
        r"(.+?)(?:的)?(?:科普|故事|介紹|紀錄片)?影片",
        text,
        re.I,
    )
    if topic_match is None:
        return None
    topic = topic_match.group(1).strip(" ，,。:：-–")
    duration_match = re.search(
        r"(\d+(?:\.\d+)?\s*(?:mins?|minutes?|secs?|seconds?|分鐘|秒|分))",
        text,
        re.I,
    )
    style_match = re.search(
        r"(?:圖片|畫面)(?:走|用|採用|風格(?:是|為)?)\s*"
        r"([^，。；;\n]+?)(?=，|。|；|;|大概|約|$)",
        text,
        re.I,
    )
    return OperatorCall(
        action="start",
        topic=topic or "未命名故事影片",
        duration=(duration_match.group(1).replace(" ", "") if duration_match else DEFAULT_DURATION),
        visual_style=(style_match.group(1).strip() if style_match else DEFAULT_STYLE),
        auto_mode=(
            _autopilot_command(text) and not _planning_only_requested(text)
        ),
    )


@dataclass(frozen=True)
class OperatorCall:
    action: str
    topic: str = ""
    duration: str = ""
    visual_style: str = ""
    repair_request: str = ""
    auto_mode: bool = False


def parse_operator_call(
    text: str,
    *,
    has_active_project: bool = False,
) -> OperatorCall | None:
    raw = _compact(text)
    lowered = raw.lower()
    if not raw:
        return None

    if has_active_project and _autopilot_command(raw):
        return OperatorCall(action="auto", auto_mode=True)

    if lowered in {"故事影片下一步", "story video next", "story-video next"}:
        return OperatorCall(action="continue")
    if lowered in {
        "繼續",
        "继续",
        "請繼續",
        "请继续",
        "continue",
        "please continue",
        "下一步",
        "next",
    }:
        return OperatorCall(action="continue") if has_active_project else None
    if lowered in {"出片", "渲染", "render", "final cut", "故事影片出片"}:
        return OperatorCall(action="render") if has_active_project else None

    repair = re.match(
        r"^\s*(?:(?:故事影片|產影片|story\s*video|story-video)\s*)?"
        r"(?:修正|修改|repair|fix)\s*[:：\-]\s*(.+)$",
        raw,
        flags=re.I,
    )
    if repair and has_active_project:
        return OperatorCall(action="repair", repair_request=repair.group(1).strip())

    if re.match(r"^\s*(?:故事影片|產影片|story\s*video|story-video)", raw, re.I):
        body = _strip_start_prefix(raw)
        if re.search(r"[｜|]", body):
            fields = [part.strip() for part in re.split(r"[｜|]", body, maxsplit=2)]
            if len(fields) > 2:
                fields[2] = re.split(r"[。；;\n]", fields[2], maxsplit=1)[0].strip()
        else:
            fields = _split_fields(body)
        return OperatorCall(
            action="start",
            topic=fields[0] if fields else "未命名故事影片",
            duration=fields[1] if len(fields) > 1 else DEFAULT_DURATION,
            visual_style=fields[2] if len(fields) > 2 else DEFAULT_STYLE,
            auto_mode=(
                _autopilot_command(raw) and not _planning_only_requested(raw)
            ),
        )

    long_form = _parse_explicit_long_form_start(raw)
    if long_form is not None:
        return long_form
    return None


@dataclass(frozen=True)
class StoryVideoRunContext:
    run_id: str
    project_id: str
    project_dir: Path
    source_key: str
    session_ids: tuple[str, ...]
    original_request: str
    topic: str
    duration: str
    visual_style: str
    auto_mode: bool = False
    phase: str = "planning"
    last_validated_phase: str = ""
    status: str = "active"
    repair_request: str = ""
    repair_phase: str = ""
    provider_policy: dict[str, Any] = field(
        default_factory=lambda: json.loads(json.dumps(DEFAULT_PROVIDER_POLICY))
    )
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    @property
    def next_call(self) -> str | None:
        if self.repair_request and not self.repair_is_stale:
            return f"修正：{self.repair_request}"
        if self.status == "complete" or self.phase == "complete":
            return None
        if self.phase == "render":
            return "出片"
        return "繼續"

    @property
    def repair_is_stale(self) -> bool:
        if not self.repair_request:
            return False
        if self.repair_phase:
            return self.repair_phase != self.phase
        match = re.match(r"^\s*補齊\s+([^：:]+)\s*[：:]", self.repair_request)
        if match is None or not self.last_validated_phase:
            return False
        target_phase = match.group(1).strip().lower()
        validated_phase = self.last_validated_phase.strip().lower()
        return target_phase == validated_phase and self.phase != self.last_validated_phase

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["project_dir"] = str(self.project_dir)
        payload["session_ids"] = list(self.session_ids)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StoryVideoRunContext":
        data = dict(payload)
        data["project_dir"] = Path(data["project_dir"])
        data["session_ids"] = tuple(data.get("session_ids") or ())
        return cls(**data)


class StoryVideoStateStore:
    def __init__(self, root: str | Path | None = None) -> None:
        hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
        self.root = Path(root) if root is not None else hermes_home / "story_videos"
        self.state_root = self.root / "_workflow_state"
        self.source_index_path = self.state_root / "source_index.json"
        self.session_index_path = self.state_root / "session_index.json"

    def has_source(self, source_key: str) -> bool:
        return self.for_source(source_key) is not None

    def for_source(self, source_key: str) -> StoryVideoRunContext | None:
        return self._from_index(self.source_index_path, source_key)

    def for_session(self, session_id: str) -> StoryVideoRunContext | None:
        return self._from_index(self.session_index_path, session_id)

    def create_or_load(
        self,
        *,
        source_key: str,
        session_id: str,
        call: OperatorCall,
        original_request: str,
    ) -> StoryVideoRunContext:
        with _LOCK:
            existing = self.for_source(source_key)
            if existing is not None and (
                call.action != "start" or call.topic == existing.topic
            ):
                context = existing
            else:
                if call.action != "start":
                    raise ValueError("No active story-video project for this source")
                run_id = uuid.uuid4().hex
                project_id = f"{_slug(call.topic)}-{run_id[:8]}"
                context = StoryVideoRunContext(
                    run_id=run_id,
                    project_id=project_id,
                    project_dir=self.root / project_id,
                    source_key=source_key,
                    session_ids=(),
                    original_request=original_request,
                    topic=call.topic,
                    duration=call.duration,
                    visual_style=call.visual_style,
                    auto_mode=call.auto_mode,
                )

            sessions = tuple(dict.fromkeys((*context.session_ids, session_id)))
            repair_request = (
                call.repair_request if call.action == "repair" else context.repair_request
            )
            repair_phase = context.phase if call.action == "repair" else context.repair_phase
            context = StoryVideoRunContext.from_dict(
                {
                    **context.to_dict(),
                    "session_ids": list(sessions),
                    "auto_mode": (
                        True if call.action == "auto" else context.auto_mode
                    ),
                    "repair_request": repair_request,
                    "repair_phase": repair_phase,
                    "updated_at": _utc_now(),
                }
            )
            self.save(context)
            return context

    def save(self, context: StoryVideoRunContext) -> None:
        with _LOCK:
            context.project_dir.mkdir(parents=True, exist_ok=True)
            self.state_root.mkdir(parents=True, exist_ok=True)
            self._write_json(
                context.project_dir / "story_video_run_context.json",
                context.to_dict(),
            )
            source_index = self._read_json(self.source_index_path, {})
            source_index[context.source_key] = str(
                context.project_dir / "story_video_run_context.json"
            )
            self._write_json(self.source_index_path, source_index)
            session_index = self._read_json(self.session_index_path, {})
            for session_id in context.session_ids:
                session_index[session_id] = str(
                    context.project_dir / "story_video_run_context.json"
                )
            self._write_json(self.session_index_path, session_index)

    def update(
        self,
        context: StoryVideoRunContext,
        **changes: Any,
    ) -> StoryVideoRunContext:
        if changes.get("phase", context.phase) != context.phase:
            changes.setdefault("repair_request", "")
            changes.setdefault("repair_phase", "")
        elif changes.get("repair_request") == "":
            changes.setdefault("repair_phase", "")
        updated = replace(context, updated_at=_utc_now(), **changes)
        self.save(updated)
        return updated

    def bind_session(
        self,
        context: StoryVideoRunContext,
        session_id: str,
    ) -> StoryVideoRunContext:
        sessions = tuple(dict.fromkeys((*context.session_ids, session_id)))
        return self.update(context, session_ids=sessions)

    def bind_source(
        self,
        context: StoryVideoRunContext,
        source_key: str,
    ) -> StoryVideoRunContext:
        if not source_key:
            return context
        with _LOCK:
            self.state_root.mkdir(parents=True, exist_ok=True)
            source_index = self._read_json(self.source_index_path, {})
            source_index[source_key] = str(
                context.project_dir / "story_video_run_context.json"
            )
            self._write_json(self.source_index_path, source_index)
        return context

    def _from_index(
        self,
        index_path: Path,
        key: str,
    ) -> StoryVideoRunContext | None:
        if not key:
            return None
        with _LOCK:
            index = self._read_json(index_path, {})
            context_path = index.get(key)
            if not context_path:
                return None
            payload = self._read_json(Path(context_path), None)
            if not isinstance(payload, dict):
                return None
            context = StoryVideoRunContext.from_dict(payload)
            if context.repair_is_stale:
                context = replace(
                    context,
                    repair_request="",
                    repair_phase="",
                    updated_at=_utc_now(),
                )
                self._write_json(Path(context_path), context.to_dict())
            return context

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
