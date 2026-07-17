from __future__ import annotations

from typing import Any

from .state import StoryVideoRunContext


_SECTIONS = {"help", "status", "examples", "voices"}


def normalize_guide_section(value: str) -> str | None:
    normalized = str(value or "").strip().casefold().replace("_", "-")
    aliases = {
        "": "help",
        "help": "help",
        "幫助": "help",
        "帮助": "help",
        "說明": "help",
        "说明": "help",
        "status": "status",
        "狀態": "status",
        "状态": "status",
        "進度": "status",
        "进度": "status",
        "next": "status",
        "examples": "examples",
        "example": "examples",
        "範例": "examples",
        "范例": "examples",
        "prompts": "examples",
        "voices": "voices",
        "voice": "voices",
        "聲線": "voices",
        "声线": "voices",
    }
    return aliases.get(normalized)


def operator_next_call(context: StoryVideoRunContext) -> str | None:
    if context.auto_mode and context.status == "active":
        return None
    if context.status == "stopped":
        return "繼續"
    if context.status == "complete" or context.phase == "complete":
        return "準備上架"
    return context.next_call


def format_raphael_next_action(context: StoryVideoRunContext) -> str | None:
    next_call = operator_next_call(context)
    if not next_call:
        return None
    return f"Raphael 下一步：回覆「{next_call}」。"


def _format_help() -> str:
    return "\n".join(
        (
            "故事影片 Help",
            "",
            "最快開始",
            "`故事影片：<主題>｜<時長>｜<風格>。全自動`",
            "",
            "快速查詢",
            "`/story-video status` 目前進度與下一步",
            "`/story-video examples` 可直接使用的 prompt",
            "`/story-video voices` 可用聲線",
            "",
            "Slack 也可輸入 `/hermes story-video status`。",
            "製作中要中止，直接回覆「停止」。",
        )
    )


def _format_status(context: StoryVideoRunContext | None) -> str:
    if context is None:
        return "\n".join(
            (
                "故事影片狀態",
                "這個 thread 目前沒有綁定故事影片。",
                "開始範例：`故事影片：恐龍起源｜5 分鐘｜寫實電影感。全自動`",
            )
        )

    mode = "全自動" if context.auto_mode else "手動"
    lines = [
        "故事影片狀態",
        f"專案：{context.topic}",
        f"階段：{context.phase}",
        f"模式：{mode}",
        f"狀態：{context.status}",
    ]
    if context.auto_mode and context.status == "active":
        lines.append("下一步：不需要操作；Hermes 會自動推進。要中止請回覆「停止」。")
    elif context.status == "stopped":
        lines.append("下一步：回覆「繼續」恢復手動；要全自動則回覆「全自動」。")
    elif context.status == "complete" or context.phase == "complete":
        lines.append("下一步：回覆「準備上架」建立 YouTube 審核包。")
    else:
        next_call = operator_next_call(context)
        lines.append(
            f"下一步：回覆「{next_call}」。" if next_call else "下一步：目前不需要操作。"
        )
    return "\n".join(lines)


def _format_examples() -> str:
    return "\n".join(
        (
            "故事影片 Prompt 範例",
            "",
            "完整製作",
            "`故事影片：恐龍起源｜5 分鐘｜寫實電影感。全自動`",
            "",
            "只先規劃",
            "`故事影片：恐龍起源｜5 分鐘｜寫實電影感。只規劃`",
            "",
            "創作模式",
            "`創作模式：依這個主題寫成多角色故事；旁白用 simon，其他角色自動選擇可用聲線。`",
            "",
            "重製模式",
            "`重製模式：保留附件故事的核心情節，改寫成 5 歲以上會好奇的繁中故事；旁白用 simon。`",
            "",
            "說書模式",
            "`說書模式：旁白用 simon，完全照附件原文朗讀，不改字。`",
        )
    )


def _format_voices(voices: dict[str, Any] | None) -> str:
    profiles = voices.get("profiles") if isinstance(voices, dict) else None
    rows = profiles if isinstance(profiles, list) else []
    enabled = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("enabled") is not False
        and row.get("selectable") is not False
    ]
    if not enabled:
        return "故事影片聲線\n目前沒有可用聲線。使用 `新增故事影片聲線` 加入錄音。"
    default_profile = str((voices or {}).get("default_profile_id") or "")
    lines = ["故事影片聲線"]
    for row in enabled:
        voice_id = str(row.get("voice_id") or row.get("profile_id") or "").strip()
        profile_id = str(row.get("profile_id") or "").strip()
        display_name = str(row.get("display_name") or voice_id).strip()
        marker = "（預設）" if profile_id == default_profile else ""
        lines.append(f"- `{voice_id}`：{display_name}，目前版本 `{profile_id}`{marker}")
    lines.append("角色分配範例：`旁白用 simon，男主角用 <voice_id>。`")
    return "\n".join(lines)


def format_story_video_guide(
    context: StoryVideoRunContext | None,
    section: str = "help",
    *,
    voices: dict[str, Any] | None = None,
) -> str:
    normalized = normalize_guide_section(section) or "help"
    if normalized not in _SECTIONS:
        normalized = "help"
    if normalized == "status":
        return _format_status(context)
    if normalized == "examples":
        return _format_examples()
    if normalized == "voices":
        return _format_voices(voices)
    return _format_help()
