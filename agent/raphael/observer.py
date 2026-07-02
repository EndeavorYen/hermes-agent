from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from agent.raphael.config import raphael_effective_enabled


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
    "status card",
    "status portrait",
    "visual status",
    "rpg status",
    "raphael status",
    "Raphael Status Portrait",
    "狀態圖",
    "狀態卡",
    "狀態卡片",
    "狀態肖像",
    "RPG 狀態",
    "RPG 樣貌",
    "拉斐爾狀態",
    "大賢者狀態",
)

_RAPHAEL_PERSONA_KEYWORDS = (
    "raphael",
    "拉斐爾",
    "大賢者",
    "內在顧問",
)

_VISUAL_REQUEST_KEYWORDS = (
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

_VISUAL_TRANSITION_KEYWORDS = (
    "complete",
    "completed",
    "done",
    "blocked",
    "error",
    "failed",
    "failure",
    "上線",
    "完成",
    "失敗",
    "錯誤",
    "阻塞",
    "卡住",
)

_AUTO_STATUS_PORTRAIT_COOLDOWN_TURNS = 3
_STATUS_PORTRAIT_MARKER = "Raphael Status Portrait"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _looks_like_raphael_visual_status_request(text: str) -> bool:
    lowered = text.lower()
    if _contains_any(lowered, _VISUAL_STATUS_KEYWORDS):
        return True
    return _contains_any(lowered, _RAPHAEL_PERSONA_KEYWORDS) and _contains_any(
        lowered,
        _VISUAL_REQUEST_KEYWORDS,
    )


def should_inject_raphael_observation(
    config: Mapping[str, Any] | None = None,
) -> bool:
    if config is None:
        try:
            from hermes_cli.config import load_config

            config = load_config()
        except Exception:
            return False

    return raphael_effective_enabled(config)


def observe_raphael_turn(user_message: Any) -> RaphaelTurnObservation:
    text = _extract_user_text(user_message)
    visual_status_needed = _looks_like_raphael_visual_status_request(text)

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


def _render_raphael_invocation_gate(user_message: str) -> str:
    try:
        from agent.raphael.invocation import is_raphael_invocation
    except Exception:
        return ""
    if not is_raphael_invocation(user_message):
        return ""
    return "\n".join(
        [
            "Raphael Invocation Gate:",
            "summoned: true",
            "public_reply_style: natural_status_risk_next_step",
            "do_not_echo_internal_labels: true",
            "auto_call_tool: false",
        ]
    )


def decide_raphael_visual_trigger(
    observation: RaphaelTurnObservation,
    sketches: tuple[str, ...],
) -> dict[str, Any]:
    if observation.visual_status_needed:
        reason = "explicit_visual_request"
    elif _contains_any("\n".join(sketches), _VISUAL_TRANSITION_KEYWORDS):
        reason = "state_transition"
    else:
        reason = "not_needed"

    visual_trigger = (
        "suggest_status_portrait" if reason != "not_needed" else "none"
    )
    return {
        "visual_trigger": visual_trigger,
        "reason": reason,
        "auto_call_image_tool": False,
    }


def _has_recent_status_portrait(
    conversation_history: Sequence[Mapping[str, Any]] | None,
    *,
    max_user_turns: int = _AUTO_STATUS_PORTRAIT_COOLDOWN_TURNS,
) -> bool:
    if not conversation_history:
        return False

    user_turns_seen = 0
    for message in reversed(conversation_history):
        if not isinstance(message, Mapping):
            continue
        if message.get("role") == "user":
            user_turns_seen += 1
            if user_turns_seen >= max_user_turns:
                return False
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str) and _STATUS_PORTRAIT_MARKER in content:
            return True
    return False


def decide_raphael_auto_status_portrait(
    observation: RaphaelTurnObservation,
    visual_decision: Mapping[str, Any],
    conversation_history: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if visual_decision.get("visual_trigger") != "suggest_status_portrait":
        status = "none"
        reason = "not_needed"
    elif observation.task_state == "mutation_or_delivery_request":
        status = "suppressed"
        reason = "mutation_or_delivery_turn"
    elif _has_recent_status_portrait(conversation_history):
        status = "suppressed"
        reason = "cooldown"
    else:
        status = "suppressed"
        reason = "disabled_by_default"

    return {
        "auto_status_portrait": status,
        "reason": reason,
        "cooldown_turns": _AUTO_STATUS_PORTRAIT_COOLDOWN_TURNS,
        "marker": _STATUS_PORTRAIT_MARKER,
    }


def _render_raphael_visual_trigger_gate(decision: Mapping[str, Any]) -> str:
    if decision.get("visual_trigger") == "none":
        return ""
    auto_call = "true" if decision.get("auto_call_image_tool") is True else "false"
    return "\n".join(
        [
            "Raphael Visual Trigger Gate (suggestion only):",
            f"visual_trigger: {decision.get('visual_trigger', 'none')}",
            f"reason: {decision.get('reason', 'not_needed')}",
            f"auto_call_image_tool: {auto_call}",
        ]
    )


def _render_raphael_auto_status_portrait_gate(decision: Mapping[str, Any]) -> str:
    if decision.get("auto_status_portrait") == "none":
        return ""
    instruction = (
        "instruction: may call image_generate once for an original non-infringing RPG status portrait when allowed; include the marker if generated"
        if decision.get("auto_status_portrait") == "allowed"
        else "instruction: do not generate Raphael images automatically; answer with text only"
    )
    return "\n".join(
        [
            "Raphael Auto Status Portrait Gate (MVP):",
            f"auto_status_portrait: {decision.get('auto_status_portrait', 'none')}",
            f"reason: {decision.get('reason', 'not_needed')}",
            f"cooldown_turns: {decision.get('cooldown_turns', _AUTO_STATUS_PORTRAIT_COOLDOWN_TURNS)}",
            f"marker: {decision.get('marker', _STATUS_PORTRAIT_MARKER)}",
            instruction,
        ]
    )


def _render_raphael_status_portrait_tool_call(decision: Mapping[str, Any]) -> str:
    if decision.get("auto_status_portrait") != "allowed":
        return ""
    prompt = (
        "Create one original non-infringing RPG status portrait of an abstract "
        "Raphael-style inner advisor presence: calm analytical expression, "
        "cool luminous interface fragments, restrained high-contrast lighting, "
        "status-reading posture, no copyrighted character likeness, do not "
        "depict copyrighted characters, no anime-specific costume copying."
    )
    return "\n".join(
        [
            "Raphael Status Portrait Tool Call (MVP):",
            "tool: image_generate",
            "call_policy: call_once_when_available",
            "aspect_ratio: portrait",
            f"prompt: {prompt}",
            f"arguments.prompt: {prompt}",
            "arguments.aspect_ratio: portrait",
            "result_contract: report only real image_generate output",
            "do_not_fabricate_image_path_or_url: true",
            "final_response_shape: 狀態 / 風險 / 下一步",
            "final_marker_required: 狀態：Raphael Status Portrait: <image path or URL>",
        ]
    )


def _render_raphael_control_degraded(
    *,
    failure_layer: str,
    error: BaseException,
    next_action: str,
) -> str:
    return "\n".join(
        [
            "Raphael Control Layer Degraded (ephemeral, internal):",
            f"failure_layer: {failure_layer}",
            f"error_class: {type(error).__name__}",
            f"next_action: {next_action}",
        ]
    )


def build_raphael_observation_context(
    user_message: Any,
    config: Mapping[str, Any] | None = None,
    *,
    conversation_history: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    if not should_inject_raphael_observation(config):
        return ""
    message_text = _extract_user_text(user_message)
    attachments = _extract_attachment_refs(user_message)
    turn_observation = observe_raphael_turn(message_text)
    observation = render_raphael_observation(turn_observation)
    invocation_gate = _render_raphael_invocation_gate(message_text)
    sketches = extract_raphael_turn_sketches(conversation_history)
    sketch = _render_raphael_turn_sketch(sketches)
    visual_decision = decide_raphael_visual_trigger(turn_observation, sketches)
    visual_gate = _render_raphael_visual_trigger_gate(visual_decision)
    auto_portrait_decision = decide_raphael_auto_status_portrait(
        turn_observation,
        visual_decision,
        conversation_history,
    )
    auto_portrait_gate = _render_raphael_auto_status_portrait_gate(
        auto_portrait_decision
    )
    status_portrait_tool_call = _render_raphael_status_portrait_tool_call(
        auto_portrait_decision
    )
    blocks = [observation]
    try:
        from agent.raphael.appraisal import appraise_raphael_situation
        from agent.raphael.invocation import (
            is_casual_raphael_summon,
            is_raphael_invocation,
        )
        from agent.raphael.mission import update_raphael_mission
        from agent.raphael.state import read_mission_state, write_mission_state
        from agent.raphael.strategy import simulate_raphael_strategies

        appraisal = appraise_raphael_situation(
            user_message,
            conversation_history=conversation_history,
            attachments=attachments,
        )
        current_mission = read_mission_state()
        if not (
            appraisal.task_type == "general"
            and (
                is_casual_raphael_summon(message_text)
                or (
                    current_mission is not None
                    and not is_raphael_invocation(message_text)
                )
            )
            or (
                current_mission is not None
                and _is_vague_current_task_takeover(message_text)
            )
        ):
            strategies = simulate_raphael_strategies(appraisal)
            mission = update_raphael_mission(
                current_mission,
                appraisal,
                strategies,
            )
            write_mission_state(mission)
    except Exception as exc:
        blocks.append(
            _render_raphael_control_degraded(
                failure_layer="mission_state",
                error=exc,
                next_action="inspect Raphael state writer before trusting mission continuity",
            )
        )
    if invocation_gate:
        blocks.append(invocation_gate)
    if sketch:
        blocks.append(sketch)
    if visual_gate:
        blocks.append(visual_gate)
    if auto_portrait_gate:
        blocks.append(auto_portrait_gate)
    if status_portrait_tool_call:
        blocks.append(status_portrait_tool_call)
    try:
        from agent.raphael.control import (
            build_raphael_control_decision,
            render_raphael_control_context,
        )

        control_decision = build_raphael_control_decision(
            user_message,
            attachments=attachments,
            conversation_history=conversation_history,
        )
        control_context = render_raphael_control_context(control_decision)
        if control_context:
            blocks.append(control_context)
    except Exception as exc:
        blocks.append(
            _render_raphael_control_degraded(
                failure_layer="control_decision",
                error=exc,
                next_action="inspect Raphael control decision before trusting handoff routing",
            )
        )
    return "\n\n".join(blocks)


def _is_vague_current_task_takeover(text: str) -> bool:
    compact = re.sub(r"[\s，,。！？!?:：、]+", "", str(text or "").lower())
    return compact in {
        "拉斐爾接管這個任務",
        "拉斐尔接管这个任务",
        "請拉斐爾接管這個任務",
        "请拉斐尔接管这个任务",
        "大賢者接管這個任務",
        "大贤者接管这个任务",
        "賢者之王接管這個任務",
        "raphaeltakeoverthistask",
        "pleaseraphaeltakeoverthistask",
    }


def _extract_user_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        text = value.get("text") or value.get("content")
        if isinstance(text, str):
            return text.strip()
        if isinstance(text, Sequence) and not isinstance(text, (str, bytes, bytearray)):
            return " ".join(_extract_user_text(item) for item in text).strip()
        return ""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return " ".join(_extract_user_text(item) for item in value).strip()
    return ""


def _extract_attachment_refs(value: Any) -> tuple[str, ...]:
    refs: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            item_type = str(item.get("type") or "").strip().lower()
            image_url = item.get("image_url")
            if isinstance(image_url, Mapping):
                url = image_url.get("url")
                if url:
                    refs.append(str(url))
            elif image_url:
                refs.append(str(image_url))
            for key in ("url", "path", "file", "file_path", "source"):
                candidate = item.get(key)
                if candidate and any(marker in item_type for marker in ("image", "file")):
                    refs.append(str(candidate))
            content = item.get("content")
            if isinstance(content, Sequence) and not isinstance(
                content,
                (str, bytes, bytearray),
            ):
                for child in content:
                    visit(child)
            return
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for child in item:
                visit(child)

    visit(value)
    return tuple(ref for ref in refs if ref.strip())


__all__ = [
    "RaphaelTurnObservation",
    "build_raphael_observation_context",
    "decide_raphael_auto_status_portrait",
    "decide_raphael_visual_trigger",
    "extract_raphael_turn_sketches",
    "observe_raphael_turn",
    "render_raphael_observation",
    "should_inject_raphael_observation",
]
