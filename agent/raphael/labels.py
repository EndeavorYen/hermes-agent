from __future__ import annotations

from collections.abc import Iterable, Mapping

from agent.raphael.invocation import format_raphael_route_text


_MODE_LABELS = {
    "visual_agent_generation": "視覺生成",
    "needs_clarification": "需要釐清",
    "tool_task": "工具任務",
    "runtime_analysis": "runtime 分析",
    "prompt_disclosure": "prompt disclosure",
    "visual_feedback": "視覺回饋",
    "general_conversation": "一般對話",
}

_TARGET_LABELS = {
    "new_visual_package": "新視覺作品",
    "current_visual_artifact": "目前視覺 artifact",
    "latest_visual_prompt_trace": "最新視覺 prompt trace",
    "runtime_state": "runtime 狀態",
    "answer": "文字回答",
    "unknown": "未指定",
}

_PHASE_LABELS = {
    "route_and_handoff": "路由與交接",
    "awaiting_clarification": "等待釐清",
    "plan_execute_verify": "規劃、執行、驗證",
    "strategy_selected": "已選定策略",
    "blocked": "等待釐清",
}

_ACTION_LABELS = {
    "call_visual_agent_generate": "呼叫 visual agent 生成",
    "record_visual_feedback": "記錄視覺回饋",
    "answer_with_runtime_analysis": "回覆 runtime 分析",
    "answer_from_latest_visual_prompt_trace": "回覆最新 visual prompt trace",
    "answer_directly": "直接回覆",
    "run required proofs before completion claim": "先補齊必要證據，再宣稱完成",
    "run_required_proofs_before_completion_claim": "先補齊必要證據，再宣稱完成",
}

_SOURCE_LABELS = {
    "general_tool_proof_gate": "Raphael proof gate",
    "raphael_control": "Raphael control",
    "visual_agent_handoff": "visual agent handoff",
    "direct_visual_agent_handoff": "visual agent handoff",
}


def format_control_decision_summary(
    *,
    mode: str,
    target: str,
    phase: str,
    next_action: str,
    blockers: Iterable[str] = (),
    failure_layer: str = "",
) -> str:
    parts = [
        f"模式：{_label(mode, _MODE_LABELS)}",
        f"目標：{_label(target, _TARGET_LABELS)}",
        f"階段：{_label(phase, _PHASE_LABELS)}",
        f"下一步：{_action_label(next_action)}",
    ]
    blocker_text = "、".join(_blocker_label(blocker) for blocker in blockers if blocker)
    if blocker_text:
        parts.append(f"阻塞：{blocker_text}")
    if failure_layer:
        parts.append(f"失敗層：{_humanize_identifier(failure_layer)}")
    return "；".join(parts)


def format_status_card_summary(summary: str) -> str:
    parsed = _parse_key_value_summary(summary)
    if not parsed:
        return _humanize_legacy_summary(summary)
    blockers = tuple(
        item.strip()
        for item in str(parsed.get("blockers") or "").split(",")
        if item.strip()
    )
    return _humanize_legacy_summary(format_control_decision_summary(
        mode=str(parsed.get("mode") or "unknown"),
        target=str(parsed.get("target") or "unknown"),
        phase=str(parsed.get("phase") or "unknown"),
        next_action=str(parsed.get("next_action") or "unknown"),
        blockers=blockers,
        failure_layer=str(parsed.get("failure_layer") or ""),
    ))


def format_status_card_source(source: str) -> str:
    text = str(source or "").strip()
    return _SOURCE_LABELS.get(text, text)


def _parse_key_value_summary(summary: str) -> Mapping[str, str]:
    parsed: dict[str, str] = {}
    for part in str(summary or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _action_label(value: str) -> str:
    text = str(value or "unknown").strip()
    if text in _ACTION_LABELS:
        return _ACTION_LABELS[text]
    translated = format_raphael_route_text(text)
    return translated if translated != text else _humanize_identifier(text)


def _label(value: str, labels: Mapping[str, str]) -> str:
    text = str(value or "unknown").strip()
    return labels.get(text, _humanize_identifier(text))


def _blocker_label(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("missing_ref"):
        return f"需要 {text.removeprefix('missing_')}"
    return _humanize_identifier(text)


def _humanize_legacy_summary(summary: str) -> str:
    text = str(summary or "").replace(
        "目標：runtime or repo state",
        "目標：runtime / repo 狀態",
    )
    return text.replace(
        "下一步：run required proofs before completion claim",
        "下一步：先補齊必要證據，再宣稱完成",
    )


def _humanize_identifier(value: str) -> str:
    return str(value or "unknown").strip().replace("_", " ")


__all__ = [
    "format_control_decision_summary",
    "format_status_card_source",
    "format_status_card_summary",
]
