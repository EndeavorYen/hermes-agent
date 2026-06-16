from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class RaphaelTurnObservation:
    task_state: str
    risk_signal: str
    suggested_next_move: str
    visual_status_needed: bool = False


_MUTATION_OR_PUBLIC_KEYWORDS = (
    "skill",
    "memory",
    "cron",
    "slack",
    "tool",
    "plugin",
    "hook",
    "install",
    "delete",
    "remove",
    "patch",
    "commit",
    "push",
    "deploy",
    "release",
    "publish",
    "public",
    "上線",
    "發布",
    "公開",
    "部署",
    "刪除",
    "安裝",
    "啟用",
    "推送",
    "發 slack",
    "發送",
)

_VISUAL_STATUS_KEYWORDS = (
    "image",
    "visual",
    "portrait",
    "status card",
    "rpg",
    "圖",
    "產圖",
    "狀態圖",
    "肖像",
    "樣貌",
    "表情",
)

_IMPLEMENTATION_OR_PLAN_KEYWORDS = (
    "phase",
    "mvp",
    "plan",
    "implement",
    "execute",
    "執行",
    "進行",
    "實作",
    "規劃",
    "下一步",
)

_JUDGMENT_LINE_RE = re.compile(r"^\s*(?:[-*•]\s*)?(狀態|風險|下一步)\s*[:：]")


def _cfg_get(config: Mapping[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = config
    for key in path:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key, default)
    return current


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def should_inject_raphael_observation(
    config: Mapping[str, Any] | None = None,
) -> bool:
    if config is None:
        try:
            from hermes_cli.config import load_config

            config = load_config()
        except Exception:
            return False

    if _cfg_get(config, "raphael", "enabled", default=False) is not True:
        return False
    if (
        _cfg_get(
            config,
            "raphael",
            "default_conversation_mode_enabled",
            default=False,
        )
        is not True
    ):
        return False
    mode = str(_cfg_get(config, "raphael", "mode", default="advisor") or "").strip()
    return not mode or mode == "advisor"


def observe_raphael_turn(user_message: str) -> RaphaelTurnObservation:
    text = user_message if isinstance(user_message, str) else ""
    visual_status_needed = _contains_any(text, _VISUAL_STATUS_KEYWORDS)

    if _contains_any(text, _MUTATION_OR_PUBLIC_KEYWORDS):
        next_move = "separate observation from mutation; confirm scope and approval"
        if visual_status_needed:
            next_move += "; keep any status card secondary"
        return RaphaelTurnObservation(
            task_state="mutation_or_delivery_request",
            risk_signal="persistent_or_public_side_effect",
            suggested_next_move=next_move,
            visual_status_needed=visual_status_needed,
        )

    if visual_status_needed:
        return RaphaelTurnObservation(
            task_state="visual_status_request",
            risk_signal="visual_generation_requested",
            suggested_next_move="consider a status card only if it clarifies the turn",
            visual_status_needed=True,
        )

    if _contains_any(text, _IMPLEMENTATION_OR_PLAN_KEYWORDS):
        return RaphaelTurnObservation(
            task_state="planning_or_execution_request",
            risk_signal="scope_drift",
            suggested_next_move="state the immediate next action before expanding",
            visual_status_needed=False,
        )

    return RaphaelTurnObservation(
        task_state="casual_or_direct",
        risk_signal="low",
        suggested_next_move="answer directly",
        visual_status_needed=False,
    )


def render_raphael_observation(observation: RaphaelTurnObservation) -> str:
    visual_status = "true" if observation.visual_status_needed else "false"
    lines = [
        "Raphael State Observer (ephemeral, internal):",
        f"task_state: {observation.task_state}",
        f"risk_signal: {observation.risk_signal}",
        f"suggested_next_move: {observation.suggested_next_move}",
        f"visual_status_needed: {visual_status}",
    ]
    return "\n".join(lines)


def extract_raphael_turn_sketches(
    conversation_history: Sequence[Mapping[str, Any]] | None,
    *,
    max_items: int = 3,
) -> tuple[str, ...]:
    if not conversation_history or max_items <= 0:
        return ()

    sketches: list[str] = []
    for message in reversed(conversation_history):
        if not isinstance(message, Mapping) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        for line in reversed(content.splitlines()):
            stripped = line.strip()
            if _JUDGMENT_LINE_RE.match(stripped):
                sketches.append(stripped)
                if len(sketches) >= max_items:
                    return tuple(reversed(sketches))
    return tuple(reversed(sketches))


def _render_raphael_turn_sketch(sketches: tuple[str, ...]) -> str:
    if not sketches:
        return ""
    return "\n".join(
        ["Raphael Turn Sketch (recent, derived):"]
        + [f"- {sketch}" for sketch in sketches]
    )


def build_raphael_observation_context(
    user_message: str,
    config: Mapping[str, Any] | None = None,
    *,
    conversation_history: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    if not should_inject_raphael_observation(config):
        return ""
    observation = render_raphael_observation(observe_raphael_turn(user_message))
    sketch = _render_raphael_turn_sketch(
        extract_raphael_turn_sketches(conversation_history)
    )
    if not sketch:
        return observation
    return observation + "\n\n" + sketch


__all__ = [
    "RaphaelTurnObservation",
    "build_raphael_observation_context",
    "extract_raphael_turn_sketches",
    "observe_raphael_turn",
    "render_raphael_observation",
    "should_inject_raphael_observation",
]
