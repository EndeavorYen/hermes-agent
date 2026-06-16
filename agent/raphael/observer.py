from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
    return "\n".join(
        [
            "Raphael State Observer (ephemeral, internal):",
            f"task_state: {observation.task_state}",
            f"risk_signal: {observation.risk_signal}",
            f"suggested_next_move: {observation.suggested_next_move}",
            f"visual_status_needed: {visual_status}",
        ]
    )


def build_raphael_observation_context(
    user_message: str,
    config: Mapping[str, Any] | None = None,
) -> str:
    if not should_inject_raphael_observation(config):
        return ""
    return render_raphael_observation(observe_raphael_turn(user_message))


__all__ = [
    "RaphaelTurnObservation",
    "build_raphael_observation_context",
    "observe_raphael_turn",
    "render_raphael_observation",
    "should_inject_raphael_observation",
]
