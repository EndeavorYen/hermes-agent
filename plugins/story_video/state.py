from __future__ import annotations

import hashlib
import hmac
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
DEFAULT_STYLE = "Cinematic topic-appropriate visual storytelling"
PHASES = ("planning", "keyframes", "batch", "voice", "render", "complete")
AUTOPILOT_AUTHORIZATION_SCHEMA = "story_video_autopilot_authorization_v2"
LEGACY_AUTOPILOT_AUTHORIZATION_SCHEMA = "story_video_autopilot_authorization_v1"
AUTOPILOT_AUTHORIZATION_SCOPES = (
    "openai_image_generation",
    "openai_vision_qc",
    "local_project_artifact_write",
)
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


def _revision_command(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or "").casefold())
    if any(
        marker in compact
        for marker in (
            "不要重製",
            "不要重制",
            "不要重新製作",
            "不要重新制作",
        )
    ):
        return False
    return any(
        marker in compact
        for marker in (
            "重製",
            "重制",
            "重新製作",
            "重新制作",
            "重新產生影片",
            "重新生成影片",
        )
    )


def _stop_command(text: str) -> bool:
    compact = re.sub(r"[\s，,。.!！?？;；:：_-]+", "", str(text or "").casefold())
    if any(
        marker in compact
        for marker in (
            "不要停止",
            "别停止",
            "別停止",
            "不要停",
            "繼續不要停",
            "继续不要停",
            "donotstop",
            "don'tstop",
            "keepgoing",
        )
    ):
        return False
    if compact in {"停", "停止", "stop", "cancel", "abort"}:
        return True
    return any(
        marker in compact
        for marker in (
            "停止不要做了",
            "停止故事影片",
            "停止製作",
            "停止制作",
            "不要再繼續製作",
            "不要再继续制作",
            "不要做了",
            "不要再做",
            "取消故事影片",
            "取消製作",
            "取消制作",
            "先停",
            "停下來",
            "停下来",
            "stopstoryvideo",
            "cancelstoryvideo",
            "abortstoryvideo",
        )
    )


def _split_fields(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[｜|，,]+", text) if part.strip()]


def _strip_start_prefix(text: str) -> str:
    return re.sub(
        r"^\s*(?:新(?:的)?\s*)?(?:故事影片|產影片|story\s*video|story-video)"
        r"\s*[:：\-]?\s*",
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
    from tools.story_video_provider_guard import story_video_request_detected

    if not story_video_request_detected(text):
        return None
    duration_token = (
        r"(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百兩两]+)\s*"
        r"(?:[-–]\s*)?(?:minutes?|mins?|seconds?|secs?|分鐘|分钟|秒|分)"
        r"(?![A-Za-z])"
    )
    topic_match = re.search(
        r"^\s*(?:幫我|請)?(?:做|製作|產生|生成)(?:一部|一支)?\s*"
        r"(.+?)(?:的)?(?:科普|故事|介紹|紀錄片)?影片",
        text,
        re.I,
    )
    if topic_match is None:
        topic_match = re.search(
            rf"^\s*(?:please\s+)?(?:make|create|produce|generate)\s+"
            rf"(?:me\s+)?(?:an?\s+)?(?:{duration_token}\s+)?"
            r"(?:(?:multi[ -](?:scene|shot)|narrated)\s+)*"
            r"(?:documentary|explainer(?:\s+video)?|story[ -]?video|video)"
            r"(?:\s+with\s+(?:narration|subtitles?))?\s+"
            r"(?:about|on)\s+(.+?)(?:[.!?]|$)",
            text,
            re.I,
        )
        if topic_match is None:
            return None
    topic = re.sub(
        rf"(?:的)?{duration_token}$",
        "",
        topic_match.group(1).strip(" ，,。:：-–"),
        flags=re.I,
    ).strip(" ，,。:：-–《》")
    duration_match = re.search(
        rf"({duration_token})",
        text,
        re.I,
    )
    style_match = re.search(
        r"(?:圖片|畫面)(?:走|用|採用|風格(?:是|為)?)\s*"
        r"([^，。；;\n]+?)(?=，|。|；|;|大概|約|$)",
        text,
        re.I,
    )
    if style_match is None:
        style_match = re.search(
            r"((?:真實|真实|寫實|写实|照片|photoreal(?:istic)?|cinematic|電影感|电影感)"
            r"[^，。；;\n]{0,32}?(?:紀錄片風格|纪录片风格|紀錄片|纪录片|風格|风格))",
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
    new_project: bool = False


def parse_operator_call(
    text: str,
    *,
    has_active_project: bool = False,
) -> OperatorCall | None:
    raw = _compact(text)
    lowered = raw.lower()
    if not raw:
        return None

    explicit_new_project = bool(re.match(
        r"^\s*(?:新(?:的)?\s*(?:故事影片|story[ -]?video)|"
        r"重新開始(?:一個|一部|一支)?\s*故事影片|start\s+new\s+story[ -]?video)",
        raw,
        re.I,
    ))

    if has_active_project and _stop_command(raw):
        return OperatorCall(action="stop")

    if has_active_project and _revision_command(raw) and not explicit_new_project:
        return OperatorCall(
            action="revision",
            auto_mode=_autopilot_command(raw),
        )

    if has_active_project and _autopilot_command(raw) and not explicit_new_project:
        return OperatorCall(action="auto", auto_mode=True)

    if (
        lowered in {"故事影片下一步", "story video next", "story-video next"}
        or has_active_project
        and re.match(r"^\s*(?:故事影片下一步|story[ -]?video\s+next)", raw, re.I)
    ):
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
    if lowered in {
        "準備上架",
        "准备上架",
        "youtube 審核包",
        "youtube 审核包",
        "準備 youtube 審核包",
        "准备 youtube 审核包",
    }:
        return OperatorCall(action="package") if has_active_project else None
    if lowered in {
        "核准上傳 youtube",
        "核准上传 youtube",
        "批准上傳 youtube",
        "批准上传 youtube",
    }:
        return OperatorCall(action="approve_upload") if has_active_project else None

    repair = re.match(
        r"^\s*(?:(?:故事影片|產影片|story\s*video|story-video)\s*)?"
        r"(?:修正|修改|repair|fix)\s*[:：\-]\s*(.+)$",
        raw,
        flags=re.I,
    )
    if repair and has_active_project:
        return OperatorCall(action="repair", repair_request=repair.group(1).strip())

    if (
        has_active_project
        and not explicit_new_project
        and (
            re.match(r"^\s*(?:故事影片|產影片|story\s*video|story-video)", raw, re.I)
            or _parse_explicit_long_form_start(raw) is not None
        )
    ):
        return OperatorCall(action="continue")

    if re.match(
        r"^\s*(?:新(?:的)?\s*)?(?:故事影片|產影片|story\s*video|story-video)",
        raw,
        re.I,
    ):
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
            new_project=explicit_new_project,
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
    parent_run_id: str = ""
    source_project_dir: Path | None = None
    auto_mode: bool = False
    autopilot_last_signature: str = ""
    autopilot_stall_count: int = 0
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
    def planning_only(self) -> bool:
        return _planning_only_requested(self.original_request)

    @property
    def next_call(self) -> str | None:
        if self.repair_request and not self.repair_is_stale:
            return f"修正：{self.repair_request}"
        if self.status in {"complete", "stopped"} or self.phase == "complete":
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
        payload["source_project_dir"] = (
            str(self.source_project_dir) if self.source_project_dir is not None else None
        )
        payload["session_ids"] = list(self.session_ids)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StoryVideoRunContext":
        data = dict(payload)
        data["project_dir"] = Path(data["project_dir"])
        if data.get("source_project_dir"):
            data["source_project_dir"] = Path(data["source_project_dir"])
        data["session_ids"] = tuple(data.get("session_ids") or ())
        return cls(**data)


class StoryVideoStateStore:
    def __init__(self, root: str | Path | None = None) -> None:
        hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
        self.root = Path(root) if root is not None else hermes_home / "story_videos"
        self.state_root = self.root / "_workflow_state"
        self.run_state_root = self.state_root / "runs"
        self.authorization_state_root = self.state_root / "authorizations"
        self.source_index_path = self.state_root / "source_index.json"
        self.session_index_path = self.state_root / "session_index.json"

    def has_source(self, source_key: str) -> bool:
        return self.for_source(source_key) is not None

    def for_source(self, source_key: str) -> StoryVideoRunContext | None:
        return self._from_index(self.source_index_path, source_key)

    def for_session(self, session_id: str) -> StoryVideoRunContext | None:
        return self._from_index(self.session_index_path, session_id)

    def for_original_request(
        self,
        original_request: str,
    ) -> StoryVideoRunContext | None:
        """Recover a run from the immutable Slack thread parent request.

        Gateway session records can be pruned while the platform thread stays
        alive. The quoted parent survives that reset, so use an exact compacted
        request match instead of guessing from the newest project or topic.
        """
        target = _compact(original_request)
        if not target or not self.run_state_root.is_dir():
            return None
        matches: list[StoryVideoRunContext] = []
        for path in self.run_state_root.glob("*.json"):
            payload = self._read_json(path, None)
            if not isinstance(payload, dict):
                continue
            try:
                context = StoryVideoRunContext.from_dict(payload)
            except (KeyError, TypeError, ValueError):
                continue
            if _compact(context.original_request) == target:
                matches.append(self._reconcile_production_context(context))
        if not matches:
            return None
        return max(matches, key=lambda item: (item.updated_at, item.created_at))

    def for_run(
        self,
        *,
        run_id: str,
        project_dir: str | Path,
    ) -> StoryVideoRunContext | None:
        if not run_id or not project_dir:
            return None
        try:
            root = self.root.expanduser().resolve()
            candidate = Path(project_dir).expanduser().resolve()
            candidate.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return None
        canonical_path = self.run_state_root / f"{run_id}.json"
        payload = self._read_json(canonical_path, None)
        if not isinstance(payload, dict):
            payload = self._read_json(
                candidate / "story_video_run_context.json",
                None,
            )
        if not isinstance(payload, dict):
            return None
        try:
            context = StoryVideoRunContext.from_dict(payload)
        except (KeyError, TypeError, ValueError):
            return None
        try:
            context_dir = context.project_dir.expanduser().resolve()
        except (OSError, RuntimeError):
            return None
        if context.run_id != run_id or context_dir != candidate:
            return None
        recovered = self._reconcile_production_context(context)
        if recovered != context:
            self.save(recovered)
        return recovered

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
            if existing is not None and call.action == "revision":
                run_id = uuid.uuid4().hex
                project_id = f"{_slug(existing.topic)}-{run_id[:8]}"
                context = StoryVideoRunContext(
                    run_id=run_id,
                    project_id=project_id,
                    project_dir=self.root / project_id,
                    source_key=source_key,
                    session_ids=(),
                    original_request=original_request,
                    topic=existing.topic,
                    duration=existing.duration,
                    visual_style=existing.visual_style,
                    parent_run_id=existing.run_id,
                    source_project_dir=existing.project_dir,
                    auto_mode=call.auto_mode,
                )
            elif existing is not None and (
                call.action != "start"
                or call.topic == existing.topic
                or not call.new_project
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
            if call.action == "stop":
                self._write_autopilot_authorization(
                    context,
                    enabled=False,
                    source="operator_stop_command",
                )
                auto_mode = False
                status = "stopped"
                repair_request = ""
                repair_phase = ""
            elif call.action == "auto":
                auto_mode = True
                status = "active"
            elif context.status == "stopped":
                auto_mode = False
                status = "active"
            else:
                auto_mode = context.auto_mode
                status = context.status
            context = StoryVideoRunContext.from_dict(
                {
                    **context.to_dict(),
                    "session_ids": list(sessions),
                    "auto_mode": auto_mode,
                    "status": status,
                    "autopilot_last_signature": (
                        ""
                        if call.action in {"auto", "stop"}
                        else context.autopilot_last_signature
                    ),
                    "autopilot_stall_count": (
                        0
                        if call.action in {"auto", "stop"}
                        else context.autopilot_stall_count
                    ),
                    "repair_request": repair_request,
                    "repair_phase": repair_phase,
                    "updated_at": _utc_now(),
                }
            )
            if call.auto_mode:
                self._write_autopilot_authorization(
                    context,
                    enabled=True,
                    source="operator_auto_command",
                )
            context = self._reconcile_production_context(context)
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
            canonical_path = self.run_state_root / f"{context.run_id}.json"
            self._write_json(canonical_path, context.to_dict())
            source_index = self._read_json(self.source_index_path, {})
            source_index[context.source_key] = str(canonical_path)
            self._write_json(self.source_index_path, source_index)
            session_index = self._read_json(self.session_index_path, {})
            for session_id in context.session_ids:
                session_index[session_id] = str(canonical_path)
            self._write_json(self.session_index_path, session_index)

    def update(
        self,
        context: StoryVideoRunContext,
        **changes: Any,
    ) -> StoryVideoRunContext:
        with _LOCK:
            canonical = self._read_json(
                self.run_state_root / f"{context.run_id}.json",
                None,
            )
            if isinstance(canonical, dict):
                try:
                    latest = StoryVideoRunContext.from_dict(canonical)
                except (KeyError, TypeError, ValueError):
                    latest = None
                if (
                    latest is not None
                    and latest.run_id == context.run_id
                    and latest.project_dir == context.project_dir
                ):
                    context = latest

            next_phase = changes.get("phase", context.phase)
            if next_phase not in PHASES:
                raise ValueError(f"Unknown story-video phase: {next_phase}")
            if PHASES.index(next_phase) < PHASES.index(context.phase):
                raise ValueError(
                    f"Story-video phase regression is forbidden: "
                    f"{context.phase} -> {next_phase}"
                )
            if next_phase != context.phase:
                changes.setdefault("repair_request", "")
                changes.setdefault("repair_phase", "")
                changes.setdefault("autopilot_last_signature", "")
                changes.setdefault("autopilot_stall_count", 0)
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
                self.run_state_root / f"{context.run_id}.json"
            )
            self._write_json(self.source_index_path, source_index)
        return context

    def autopilot_authorization(
        self,
        context: StoryVideoRunContext,
        *,
        authorization_id: str = "",
    ) -> dict[str, Any] | None:
        path = self.authorization_state_root / f"{context.run_id}.json"
        payload = self._read_json(path, None)
        if (
            isinstance(payload, dict)
            and payload.get("schema") == LEGACY_AUTOPILOT_AUTHORIZATION_SCHEMA
            and payload.get("run_id") == context.run_id
            and payload.get("enabled") is True
        ):
            self._write_autopilot_authorization(
                context,
                enabled=True,
                source=str(payload.get("source") or "legacy_operator_auto_command"),
            )
            payload = self._read_json(path, None)
        if not isinstance(payload, dict):
            return None
        try:
            project_dir = str(context.project_dir.expanduser().resolve())
        except (OSError, RuntimeError):
            return None
        expected_scopes = set(AUTOPILOT_AUTHORIZATION_SCOPES)
        actual_scopes = {
            str(scope) for scope in payload.get("scopes") or [] if str(scope).strip()
        }
        if not (
            payload.get("schema") == AUTOPILOT_AUTHORIZATION_SCHEMA
            and payload.get("run_id") == context.run_id
            and payload.get("project_dir") == project_dir
            and payload.get("provider") == "openai-codex"
            and payload.get("enabled") is True
            and actual_scopes == expected_scopes
            and str(payload.get("authorization_id") or "").strip()
        ):
            return None
        if authorization_id and not hmac.compare_digest(
            str(payload["authorization_id"]),
            str(authorization_id),
        ):
            return None
        return payload

    def for_autopilot_authorization(
        self,
        authorization_id: str,
    ) -> StoryVideoRunContext | None:
        normalized_id = str(authorization_id or "").strip()
        if not normalized_id or not self.authorization_state_root.exists():
            return None
        for path in self.authorization_state_root.glob("*.json"):
            payload = self._read_json(path, None)
            if not isinstance(payload, dict) or not (
                payload.get("schema") == AUTOPILOT_AUTHORIZATION_SCHEMA
                and payload.get("enabled") is True
            ):
                continue
            candidate_id = str(payload.get("authorization_id") or "").strip()
            if not candidate_id or not hmac.compare_digest(candidate_id, normalized_id):
                continue
            context = self.for_run(
                run_id=str(payload.get("run_id") or ""),
                project_dir=str(payload.get("project_dir") or ""),
            )
            if context is None:
                return None
            if self.autopilot_authorization(
                context,
                authorization_id=normalized_id,
            ) is None:
                return None
            return context
        return None

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
            recovered = self._reconcile_production_context(context)
            changed = recovered != context
            context = recovered
            if context.repair_is_stale:
                context = replace(
                    context,
                    repair_request="",
                    repair_phase="",
                    updated_at=_utc_now(),
                )
                changed = True
            if changed:
                self.save(context)
            return context

    def _write_autopilot_authorization(
        self,
        context: StoryVideoRunContext,
        *,
        enabled: bool,
        source: str,
    ) -> None:
        path = self.authorization_state_root / f"{context.run_id}.json"
        existing = self._read_json(path, {})
        authorization_id = str(existing.get("authorization_id") or uuid.uuid4().hex)
        timestamp_key = "authorized_at" if enabled else "revoked_at"
        self._write_json(
            path,
            {
                "schema": AUTOPILOT_AUTHORIZATION_SCHEMA,
                "run_id": context.run_id,
                "project_dir": str(context.project_dir.expanduser().resolve()),
                "provider": "openai-codex",
                "scopes": list(AUTOPILOT_AUTHORIZATION_SCOPES),
                "authorization_id": authorization_id,
                "original_request_sha256": hashlib.sha256(
                    context.original_request.encode("utf-8")
                ).hexdigest(),
                "enabled": enabled,
                timestamp_key: _utc_now(),
                "source": source,
            },
        )

    def _reconcile_production_context(
        self,
        context: StoryVideoRunContext,
    ) -> StoryVideoRunContext:
        authorization = self.autopilot_authorization(context)
        if authorization is None:
            return context

        manifest = self._read_json(
            context.project_dir / "manifests" / "shot_candidate_manifest.json",
            None,
        )
        manifest_phase = manifest.get("phase") if isinstance(manifest, dict) else None
        recovered_phase = context.phase
        if (
            manifest_phase in PHASES
            and manifest.get("run_id") == context.run_id
            and PHASES.index(manifest_phase) > PHASES.index(context.phase)
        ):
            recovered_phase = manifest_phase

        if context.auto_mode and recovered_phase == context.phase:
            return context
        recovered = replace(
            context,
            auto_mode=True,
            phase=recovered_phase,
            repair_request="" if recovered_phase != context.phase else context.repair_request,
            repair_phase="" if recovered_phase != context.phase else context.repair_phase,
            autopilot_last_signature=(
                "" if recovered_phase != context.phase else context.autopilot_last_signature
            ),
            autopilot_stall_count=(
                0 if recovered_phase != context.phase else context.autopilot_stall_count
            ),
            updated_at=_utc_now(),
        )
        return recovered

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
