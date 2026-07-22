from __future__ import annotations

import re
from typing import Any

from agent.raphael.appraisal import RaphaelAppraisal
from agent.raphael.mission import RaphaelMissionState
from agent.raphael.strategy import RaphaelStrategySet


SUMMON_MARKERS = (
    "raphael",
    "rafael",
    "拉斐爾",
    "拉斐尔",
    "大賢者",
    "大贤者",
    "賢者之王",
    "贤者之王",
)

_DIRECT_PREFIXES = (
    "",
    "請",
    "请",
    "please",
    "hey",
    "hi",
    "hello",
    "召喚",
    "召唤",
)

_DIRECT_SEPARATORS = ("，", ",", "：", ":", "？", "?", "、", "。", "！", "!", "\n")

_DIRECT_ACTIONS = (
    "analyze",
    "review",
    "take",
    "help",
    "inspect",
    "接管",
    "解析",
    "分析",
    "檢查",
    "检查",
    "幫",
    "帮",
)


def is_raphael_invocation(text: Any) -> bool:
    raw = str(text or "")
    lowered = raw.lower()
    if is_casual_raphael_summon(raw):
        return True
    for marker in SUMMON_MARKERS:
        for match in _iter_marker_matches(lowered, marker.lower()):
            if _is_direct_marker_use(lowered, match.start(), match.end()):
                return True
    return False


def is_casual_raphael_summon(text: Any) -> bool:
    normalized = re.sub(r"[\W_]+", "", str(text or "").lower())
    return normalized in {
        re.sub(r"[\W_]+", "", marker.lower()) for marker in SUMMON_MARKERS
    }


def _iter_marker_matches(text: str, marker: str):
    if marker.isascii():
        pattern = rf"(?<![a-z0-9_./-]){re.escape(marker)}(?![a-z0-9_./-])"
        yield from re.finditer(pattern, text)
        return
    yield from re.finditer(re.escape(marker), text)


def _is_direct_marker_use(text: str, start: int, end: int) -> bool:
    prefix = text[:start].strip(" \t\r\n\"'`「『（([<{")
    if prefix not in _DIRECT_PREFIXES:
        return False
    suffix = text[end:].lstrip()
    if not suffix:
        return True
    if suffix.startswith(_DIRECT_SEPARATORS):
        return True
    return any(suffix.startswith(action) for action in _DIRECT_ACTIONS)


def render_raphael_invocation_response(
    appraisal: RaphaelAppraisal,
    strategies: RaphaelStrategySet,
    mission: RaphaelMissionState | None = None,
) -> str:
    if is_casual_raphael_summon(appraisal.intent) and appraisal.task_type == "general":
        return "\n".join(
            [
                "解析完成。",
                "狀態：Raphael 待命；請給我任務目標。",
                "可接管：目標判讀、策略推演、證據驗證、演化提案。",
                "下一步：說出你要我接管的任務、artifact 或阻塞點。",
            ]
        )
    route_labels = " / ".join(format_raphael_strategy_label(strategy.label) for strategy in strategies.candidates)
    selected = strategies.selected
    required = format_raphael_proof_text(selected.required_proofs)
    lines = [
        "解析完成。",
        f"目標：{appraisal.intent or '等待任務目標'}",
        f"局勢判讀：{_task_type_text(appraisal.task_type)}；{_risk_text(appraisal.risk_level)}",
        f"並列推演：{route_labels}",
        f"最優路線：{format_raphael_strategy_label(selected.label)}",
        f"必要證據：{required}",
        f"下一步：{format_raphael_route_text(selected.route)}",
    ]
    if mission is not None:
        lines.insert(2, f"任務：{_phase_text(mission.phase)}")
    if selected.blocked_reason:
        lines.append(f"阻塞：{_blocker_text(selected.blocked_reason)}")
    return "\n".join(lines)


def _task_type_text(task_type: str) -> str:
    return {
        "tool_runtime": "這是工具/runtime 任務，需要先行動再驗證",
        "runtime_analysis": "這是 LLM-only 文字分析回合，不能宣稱已完成實作、驗證或生成",
        "visual_generation": "這是視覺生成任務，品質與參考一致性是成敗核心",
        "visual_edit": "這是既有視覺 artifact 的延續修改，必須保持目標一致",
        "visual_analysis": "這是視覺路由分析，不應直接消耗生成額度",
        "general": "這是一般對話或低風險判讀",
    }.get(task_type, "這是未分類任務，先用保守路線確認目標")


def _risk_text(risk_level: str) -> str:
    return {
        "low": "風險低，可以直接回應但仍需對齊目標",
        "medium": "風險中等，完成前需要可驗證證據",
        "high": "風險高，必須先釐清與設置防護",
    }.get(risk_level, "風險未明，採取保守推進")


def format_raphael_strategy_label(label: str) -> str:
    return {
        "fast": "快速試探",
        "safe": "穩定執行",
        "quality": "品質優先",
        "blocked": "暫停釐清",
    }.get(label, label)


def format_raphael_route_text(route: str) -> str:
    return {
        "minimal_direct_action": "先做最小可行動作，取得第一層回饋",
        "plan_execute_verify": "先規劃，再執行，最後用證據驗證",
        "multi_pass_review_and_repair": "多輪檢查、修正與自我審核後再交付",
        "ask_precise_clarification": "提出精準澄清，避免對錯 artifact 或錯方向行動",
    }.get(route, route)


def format_raphael_proof_text(proofs: tuple[str, ...]) -> str:
    translated = [_proof_item_text(proof) for proof in proofs]
    return "、".join(translated) if translated else "答案必須貼合目前上下文"


def _proof_item_text(proof: str) -> str:
    return {
        "focused_tests": "聚焦測試通過",
        "diff_hygiene": "git diff hygiene 通過",
        "runtime_smoke_when_live_wiring": "live runtime smoke 通過",
        "runtime_smoke": "runtime smoke 通過",
        "reference_mapping_confirmed": "參考圖語意對應已確認",
        "artifact_continuity": "沿用目前選中的 artifact",
        "quality_gate_passed": "品質閘門通過",
        "selected_current_artifact_only": "只交付本輪選中的 artifact",
        "text_only_plan": "保持文字分析路線",
        "no_tool_call": "不呼叫工具",
        "no_provider_attempt": "不呼叫生成 provider",
        "answer_matches_user_intent": "回覆精準對齊使用者意圖",
        "hostile_review": "嚴格 review 通過",
    }.get(proof, proof.replace("_", " "))


def _phase_text(phase: str) -> str:
    return {
        "strategy_selected": "已選定策略",
        "blocked": "等待釐清",
        "awaiting_mission_target": "等待任務目標",
    }.get(phase, phase)


def _blocker_text(blocker: str) -> str:
    if blocker.startswith("missing_ref"):
        return f"找不到使用者指定的 {blocker.removeprefix('missing_')}"
    return blocker.replace("_", " ")


__all__ = [
    "format_raphael_proof_text",
    "format_raphael_route_text",
    "format_raphael_strategy_label",
    "is_casual_raphael_summon",
    "is_raphael_invocation",
    "render_raphael_invocation_response",
]
