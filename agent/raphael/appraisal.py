from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from agent.raphael.artifacts import (
    latest_selected_artifact_id,
    recover_reference_attachment_paths,
)


_VISUAL_MARKERS = (
    "image",
    "video",
    "photo",
    "picture",
    "illustration",
    "圖片",
    "图像",
    "圖像",
    "圖",
    "照片",
    "影像",
    "畫面",
    "画面",
    "產圖",
    "产图",
    "生圖",
    "生图",
    "影片",
    "動畫",
    "动画",
)

_FOLLOWUP_ARTIFACT_MARKERS = (
    "剛剛那張",
    "刚刚那张",
    "剛才那張",
    "刚才那张",
    "上一張",
    "上一张",
    "上一個",
    "上一个",
    "這張",
    "这张",
    "那張",
    "那张",
    "latest",
    "previous",
    "current",
)

_EDIT_MARKERS = (
    "改",
    "修改",
    "修正",
    "調整",
    "调整",
    "改成",
    "換成",
    "变成",
    "變成",
    "不要",
    "微笑",
    "edit",
    "change",
    "adjust",
    "revise",
    "fix",
)

_TEXT_ONLY_MARKERS = (
    "llm-only",
    "llm only",
    "text-only",
    "text only",
    "純文字",
    "只分析",
    "只用文字",
)

_NO_TOOL_MARKERS = (
    "no tools",
    "without tools",
    "不要呼叫工具",
    "不要工具",
    "不呼叫工具",
)

_NO_MEDIA_MARKERS = (
    "no image",
    "no images",
    "no video",
    "no media",
    "不要產圖",
    "不要生圖",
    "不要圖片",
    "不要影片",
    "不產圖",
    "不生成圖片",
    "不生成影片",
)

_RUNTIME_MARKERS = (
    "修復",
    "實作",
    "工具任務",
    "工具任务",
    "tool task",
    "install",
    "runtime",
    "deploy",
    "上線",
    "設定",
)
_UI_RUNTIME_BUG_MARKERS = (
    "畫面空白",
    "画面空白",
    "空白畫面",
    "空白画面",
    "頁面空白",
    "页面空白",
    "ui bug",
    "blank screen",
    "blank page",
)


@dataclass(frozen=True)
class RaphaelAppraisal:
    intent: str
    task_type: str
    risk_level: str
    success_conditions: tuple[str, ...]
    blockers: tuple[str, ...] = ()
    active_artifact_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "success_conditions", tuple(self.success_conditions))
        object.__setattr__(self, "blockers", tuple(self.blockers))

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "task_type": self.task_type,
            "risk_level": self.risk_level,
            "success_conditions": list(self.success_conditions),
            "blockers": list(self.blockers),
            "active_artifact_id": self.active_artifact_id,
        }


def appraise_raphael_situation(
    user_message: Any,
    *,
    conversation_history: Sequence[Mapping[str, Any]] | None = None,
    attachments: Sequence[str] | None = None,
) -> RaphaelAppraisal:
    text = _extract_text(user_message)
    active_artifact_id = latest_selected_artifact_id(conversation_history)
    attachment_count = len([item for item in attachments or () if str(item).strip()])
    if attachment_count == 0 and conversation_history:
        attachment_count = len(recover_reference_attachment_paths(conversation_history))
    missing_ref = _missing_reference_index(text, attachment_count)
    if missing_ref is not None:
        return RaphaelAppraisal(
            intent=_summary(text),
            task_type="visual_generation",
            risk_level="medium",
            success_conditions=("reference_mapping_confirmed",),
            blockers=(f"missing_ref{missing_ref}",),
            active_artifact_id=active_artifact_id,
        )
    if _looks_like_text_only_runtime_analysis(text):
        return RaphaelAppraisal(
            intent=_summary(text),
            task_type="runtime_analysis",
            risk_level="low",
            success_conditions=("text_only_plan", "no_tool_call", "no_provider_attempt"),
            active_artifact_id=active_artifact_id,
        )
    if _looks_like_visual_analysis(text):
        return RaphaelAppraisal(
            intent=_summary(text),
            task_type="visual_analysis",
            risk_level="low",
            success_conditions=("text_only_plan", "no_provider_attempt"),
            active_artifact_id=active_artifact_id,
        )
    if _contains_any(text, _UI_RUNTIME_BUG_MARKERS):
        return RaphaelAppraisal(
            intent=_summary(text),
            task_type="tool_runtime",
            risk_level="medium",
            success_conditions=("focused_tests", "runtime_smoke_when_live_wiring"),
            active_artifact_id=active_artifact_id,
        )
    if active_artifact_id and (
        _contains_any(text, _EDIT_MARKERS)
        or _contains_any(text, _FOLLOWUP_ARTIFACT_MARKERS)
    ):
        return RaphaelAppraisal(
            intent=_summary(text),
            task_type="visual_edit",
            risk_level="medium",
            success_conditions=("artifact_continuity", "quality_gate_passed"),
            active_artifact_id=active_artifact_id,
        )
    if _contains_any(text, _VISUAL_MARKERS):
        return RaphaelAppraisal(
            intent=_summary(text),
            task_type="visual_generation",
            risk_level="medium",
            success_conditions=("selected_current_artifact_only", "quality_gate_passed"),
            active_artifact_id=active_artifact_id,
        )
    if _contains_any(text, _RUNTIME_MARKERS):
        return RaphaelAppraisal(
            intent=_summary(text),
            task_type="tool_runtime",
            risk_level="medium",
            success_conditions=("focused_tests", "runtime_smoke_when_live_wiring"),
            active_artifact_id=active_artifact_id,
        )
    return RaphaelAppraisal(
        intent=_summary(text),
        task_type="general",
        risk_level="low",
        success_conditions=("answer_matches_user_intent",),
        active_artifact_id=active_artifact_id,
    )


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return " ".join(parts).strip()
    return str(value or "").strip()


def _summary(text: str, limit: int = 96) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "..."


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _looks_like_visual_analysis(text: str) -> bool:
    lowered = str(text or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    has_visual = _contains_any(lowered, _VISUAL_MARKERS)
    if not has_visual:
        return False
    has_analysis = any(
        marker in lowered
        for marker in (
            "route",
            "provider",
            "proof",
            "proof gate",
            "mode",
            "handoff",
        )
    ) or any(
        marker in compact
        for marker in (
            "分析",
            "如果",
            "路由",
            "判斷",
            "判断",
            "應該",
            "应该",
            "證據",
            "证据",
            "驗證",
            "验证",
            "provider",
            "proofgate",
        )
    )
    return has_analysis


def _looks_like_text_only_runtime_analysis(text: str) -> bool:
    has_text_only = _contains_any(text, _TEXT_ONLY_MARKERS)
    has_no_tool = _contains_any(text, _NO_TOOL_MARKERS)
    has_no_media = _contains_any(text, _NO_MEDIA_MARKERS)
    has_runtime = _contains_any(text, _RUNTIME_MARKERS)
    if has_no_tool and has_no_media:
        return True
    if has_runtime:
        return has_text_only or has_no_tool or has_no_media
    return has_text_only and (has_no_tool or has_no_media)


def _mentioned_ref_indices(text: str) -> tuple[int, ...]:
    return tuple(int(match) for match in re.findall(r"\bref\s*(\d+)\b", text.lower()))


def _missing_reference_index(text: str, attachment_count: int) -> int | None:
    for index in _mentioned_ref_indices(text):
        if index > attachment_count:
            return index
    return None


__all__ = ["RaphaelAppraisal", "appraise_raphael_situation"]
