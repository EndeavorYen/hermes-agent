from __future__ import annotations

from typing import Any

from .state import StoryVideoRunContext


_SECTIONS = {"help", "status", "examples", "voices", "writing"}


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
        "writing": "writing",
        "text": "writing",
        "文本": "writing",
        "寫作": "writing",
        "写作": "writing",
        "難度": "writing",
        "难度": "writing",
        "淺白": "writing",
        "浅白": "writing",
    }
    return aliases.get(normalized)


def operator_next_call(context: StoryVideoRunContext) -> str | None:
    if context.auto_mode and context.status == "active":
        return None
    if context.status == "stopped":
        return "繼續"
    if context.phase == "planning" and context.status == "complete":
        return "全自動"
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
            "`/story-video writing` 文本難度與淺白化設定",
            "",
            "多角色配音",
            "1. 先用 `/story-video voices` 查看可用聲線。",
            "2. 提供故事文本或故事需求。",
            "3. 每個角色都要明確指定聲線（Phase 1 不會自動選角）。",
            "`多角色配音：旁白用 simon_clean_v2，安安用 Vivian，媽媽用 Serena，船長用 Uncle_Fu。`",
            "",
            "輸出模式（成品都是 MP4）",
            "- 圖片故事影片：角色配音 + 故事圖片 + 硬字幕。",
            "- 全黑字幕影片：角色配音 + 純黑背景 + 中央大字硬字幕；每個角色固定一種顏色，不會呼叫產圖；適合 NSFW 或不宜配圖的文本。",
            "  角色與情緒標籤只顯示在字幕，不會念出來。",
            "可在需求中直接寫「圖片故事影片」或「全黑背景字幕，不要產圖」。",
            "",
            "科普與解釋內容預設採用「淺顯但不幼稚」模式。",
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
        "輸出：全黑字幕 MP4" if context.visual_mode == "black_subtitle" else "輸出：圖片故事 MP4",
        f"狀態：{context.status}",
    ]
    if context.auto_mode and context.status == "active":
        lines.append("下一步：不需要操作；Hermes 會自動推進。要中止請回覆「停止」。")
    elif context.status == "stopped":
        lines.append("下一步：回覆「繼續」恢復手動；要全自動則回覆「全自動」。")
    elif context.phase == "planning" and context.status == "complete":
        lines.append("下一步：回覆「全自動」開始製作影像、旁白與影片。")
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
            "`圖片故事影片：請把以下故事做成多角色配音、圖片與字幕的 MP4。`",
            "",
            "全黑字幕影片",
            "`全黑字幕影片：使用以下文本做多角色配音與硬字幕，不要產圖；旁白用 simon_clean_v2，女主用 Vivian，朋友用 Serena，長輩用 Uncle_Fu。`",
            "",
            "只先規劃",
            "`故事影片：恐龍起源｜5 分鐘｜寫實電影感。只規劃`",
            "",
            "創作模式",
            "`創作模式：依這個主題寫成多角色故事。旁白用 simon_clean_v2，安安用 Vivian，媽媽用 Serena，船長用 Uncle_Fu。`",
            "",
            "重製模式",
            "`重製模式：保留附件故事的核心情節，改寫成 5 歲以上會好奇的繁中故事；旁白用 simon_clean_v2。`",
            "",
            "說書模式",
            "`說書模式：旁白用 simon_clean_v2，完全照附件原文朗讀，不改字。`",
            "",
            "科普預設（淺顯但不幼稚）",
            "`故事影片：凱因斯經濟學｜5 分鐘｜電影感科普。全自動`",
            "",
            "提高難度",
            "`故事影片：凱因斯經濟學｜5 分鐘｜進階版。全自動`",
            "`故事影片：凱因斯經濟學｜5 分鐘｜專業版，不要淺白化。全自動`",
        )
    )


def _format_writing() -> str:
    return "\n".join(
        (
            "故事影片文本難度",
            "",
            "預設：淺顯但不幼稚",
            "先建立具體直覺與因果，再介紹正式名詞，並說清楚比喻的界線。",
            "預設也會選一條敘事主軸，用冷開場、跨場懸念、證據反轉、因果接棒與回扣結尾推進，而不是逐段列知識。",
            "題材保持真實；不會為了張力虛構危險、衝突或結論。",
            "科普、歷史與紀錄內容會把重要主張逐項綁定可核驗來源，再由 fact checker 獨立確認。",
            "審稿預設走單輪快速路徑；不會為了加速省略內容正確性審稿。",
            "",
            "提高難度",
            "`進階版`：保留更多技術細節，仍照顧非本科觀眾。",
            "`專業版` 或 `不要淺白化`：以領域讀者為主，不套用普及化改寫。",
            "",
            "範例：`故事影片：凱因斯經濟學｜5 分鐘｜進階版。全自動`",
        )
    )


def _format_voices(voices: dict[str, Any] | None) -> str:
    payload = voices if isinstance(voices, dict) else {}
    catalog_rows = payload.get("voices")
    if isinstance(catalog_rows, list):
        enabled = [
            row
            for row in catalog_rows
            if isinstance(row, dict) and row.get("selectable") is not False
        ]
        default_voice = str(
            payload.get("default_voice_id")
            or payload.get("default_profile_id")
            or ""
        )
        lines = ["故事影片聲線"]
        for row in enabled:
            voice_id = str(row.get("voice_id") or "").strip()
            display_name = str(row.get("display_name") or voice_id).strip()
            engine = str(row.get("engine") or "")
            engine_label = (
                "Qwen CustomVoice"
                if engine == "qwen_custom_voice"
                else "完整聲線克隆"
            )
            marker = "（預設）" if voice_id == default_voice else ""
            lines.append(f"- `{voice_id}`：{display_name}｜{engine_label}{marker}")
        if enabled:
            lines.append("角色分配範例：`旁白用 simon_clean_v2，安安用 Vivian。`")
            return "\n".join(lines)

    profiles = payload.get("profiles")
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
    default_profile = str(payload.get("default_profile_id") or "")
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
    if normalized == "writing":
        return _format_writing()
    return _format_help()
