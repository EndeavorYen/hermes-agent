from __future__ import annotations

import re
from typing import Any

from agent.visual.prompt_text import strip_visual_prompt_metadata


STORY_VIDEO_IMAGE_PROVIDER = "openai-codex"
STORY_VIDEO_PROVIDER_ERROR_TYPE = "story_video_provider_blocked"

_DIRECT_STORY_VIDEO_MARKERS = (
    "story-video",
    "story video",
    "story_video",
    "story-video-production-pipeline",
    "故事影片",
)

_LONG_FORM_VIDEO_MARKERS = (
    "5-minute",
    "5 minute",
    "5min",
    "5 mins",
    "5mins",
    "minute-long",
    "subtitles",
    "subtitle-safe",
    "narration",
    "scene ledger",
    "scene keyframe",
    "keyframe concept",
    "science explainer",
    "documentary explainer",
    "youtube-style",
)

_CHINESE_LONG_FORM_VIDEO_RE = re.compile(
    r"(?:(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百兩两]+)\s*"
    r"(?:分鐘|分钟|分|mins?|minutes?)|旁白|字幕|場景帳本)"
)
_STORY_SCRIPT_RE = re.compile(
    r"(?:故事(?:劇本|剧本|腳本|脚本|文本|原稿)|story\s+(?:script|text))",
    re.I,
)
_MULTIROLE_DUBBING_RE = re.compile(
    r"(?:多角色(?:配音|聲音|声音|聲線|声线|朗讀|朗读)|"
    r"角色(?:配音|聲音|声音|聲線|声线)(?:安排|分配|對照|对照|設定|设定)?|"
    r"multi[ -]?role\s+(?:dubbing|voice|narration))",
    re.I,
)
_MINUTE_SCALE_RE = re.compile(
    r"(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百兩两]+)"
    r"\s*(?:[-–]\s*)?(?:分鐘|分钟|分|mins?|minutes?)(?![A-Za-z])",
    re.I,
)
_VIDEO_CONTENT_MARKERS = (
    "video",
    "documentary",
    "explainer",
    "影片",
    "紀錄片",
    "纪录片",
    "科普",
    "故事",
    "介紹",
    "介绍",
)
_LONG_FORM_STRUCTURE_RE = re.compile(
    r"\b(?:narration|narrated|subtitles?|multi[ -](?:scene|shot))\b|"
    r"(?:旁白|字幕|多(?:場景|场景|鏡頭|镜头))",
    re.I,
)
_NEGATED_LONG_FORM_STRUCTURE_RE = re.compile(
    r"\b(?:without|no)\s+(?:narration|subtitles?)"
    r"(?:\s+(?:and|or)\s+(?:narration|subtitles?))*\b|"
    r"\bnot\s+(?:narrated|subtitled)\b|"
    r"(?:不要|不需(?:要)?|無|无|沒有|没有)\s*(?:旁白|字幕)"
    r"(?:\s*(?:、|和|或|與|与|及)\s*(?:旁白|字幕))*",
    re.I,
)

_STORY_VIDEO_FLAG_KEYS = (
    "story_video",
    "story_video_mode",
    "story_video_workflow",
    "use_story_video_workflow",
)

_THREAD_CONTEXT_END = "[End of thread context]"
_REPLY_CONTEXT_END = '"]\n\n'
_EXPLICIT_VISUAL_AGENT_ROUTE_RE = re.compile(
    r"^\s*(?:(?:請|请|麻煩|麻烦|幫我|帮我)\s*)?"
    r"(?:(?:呼叫|调用|使用|用|走)\s*)?"
    r"(?:visual[ -]?agent|視覺\s*agent|视觉\s*agent)"
    r"(?:\s*[:：\-]\s*|\s+(?=(?:請|请|幫我|帮我|產出|产出|生成|製作|制作|"
    r"做|畫|画|繪製|绘制|建立|create|generate|make|draw|produce|animate|"
    r"to\s+(?:create|generate|make|draw|produce|animate))))",
    re.I,
)

_XAI_PROVIDER_ALIASES = {
    "xai",
    "x.ai",
    "x-ai",
    "x_ai",
    "grok",
    "grok imagine",
    "grok-imagine",
    "grok_imagine",
    "grok imagine image",
    "grok-imagine-image",
    "grok_imagine_image",
    "grok imagine image quality",
    "grok-imagine-image-quality",
    "grok_imagine_image_quality",
    "grok web imagine",
    "grok-web-imagine",
    "grok_web_imagine",
    "grokwebimagine",
    "grok web",
    "grok-web",
    "grok_web",
    "grokweb",
}

_OPENAI_CODEX_PROVIDER_ALIASES = {
    "codex",
    "image2",
    "image 2",
    "image-2",
    "image_2",
    "codex/image2",
    "openai-codex",
    "openai codex",
    "openai_codex",
    "openai-codex/image2",
    "gpt-image-2",
    "gpt image 2",
    "gpt_image_2",
    "gpt-image-2-high",
}


def _truthy_story_video_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _extract_prompt_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if value.get("type") in {"text", "input_text"}:
            return str(value.get("text") or "").strip()
        return _extract_prompt_text(value.get("content"))
    if isinstance(value, (list, tuple)):
        return "\n".join(
            text
            for item in value
            if (text := _extract_prompt_text(item))
        )
    return ""


def current_operator_request_text(prompt: Any) -> str:
    text = _extract_prompt_text(prompt).replace("\r\n", "\n")
    if _THREAD_CONTEXT_END in text:
        return text.rsplit(_THREAD_CONTEXT_END, 1)[1].strip()
    if text.startswith('[Replying to: "') and _REPLY_CONTEXT_END in text:
        return text.split(_REPLY_CONTEXT_END, 1)[1].strip()
    return text


def explicit_visual_agent_request_detected(prompt: Any) -> bool:
    return _EXPLICIT_VISUAL_AGENT_ROUTE_RE.match(
        current_operator_request_text(prompt)
    ) is not None


def story_video_request_detected(
    prompt: Any,
    args: Any = None,
    *,
    preserve_thread_context: bool = False,
) -> bool:
    if isinstance(args, dict) and any(
        _truthy_story_video_flag(args.get(key)) for key in _STORY_VIDEO_FLAG_KEYS
    ):
        return True
    prompt_text = _extract_prompt_text(prompt)
    text = (
        prompt_text
        if preserve_thread_context
        else strip_visual_prompt_metadata(prompt_text)
    )
    if not text:
        return False
    if explicit_visual_agent_request_detected(text):
        return False
    if _STORY_SCRIPT_RE.search(text) and _MULTIROLE_DUBBING_RE.search(text):
        return True
    lowered = text.lower()
    structure_text = _NEGATED_LONG_FORM_STRUCTURE_RE.sub("", text)
    structure_lowered = structure_text.lower()
    compact = re.sub(r"[\s_\-.]+", "", lowered)
    if any(marker in lowered for marker in _DIRECT_STORY_VIDEO_MARKERS):
        return True
    if any(marker.replace("-", "").replace(" ", "") in compact for marker in _DIRECT_STORY_VIDEO_MARKERS):
        return True
    if re.match(
        r"^\s*(?:新(?:的)?\s*)?產影片(?:\s*[:：\-]|\s|$)",
        text,
        re.I,
    ):
        return True
    if _MINUTE_SCALE_RE.search(text) and any(
        marker in lowered for marker in _VIDEO_CONTENT_MARKERS
    ):
        return True
    if _LONG_FORM_STRUCTURE_RE.search(structure_text) and any(
        marker in lowered for marker in _VIDEO_CONTENT_MARKERS
    ):
        return True
    if _CHINESE_LONG_FORM_VIDEO_RE.search(structure_text) and any(
        marker in text for marker in ("科普", "故事", "介紹", "長影片")
    ):
        return True
    long_form_hits = sum(
        1 for marker in _LONG_FORM_VIDEO_MARKERS if marker in structure_lowered
    )
    if long_form_hits >= 2 and any(
        marker in lowered
        for marker in (
            "science explainer",
            "documentary",
            "scene keyframe",
            "keyframe concept",
            "narration",
            "subtitles",
        )
    ):
        return True
    return False


def normalize_visual_provider(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    lowered = re.sub(r"\s+", " ", raw.lower())
    if lowered in _XAI_PROVIDER_ALIASES:
        return "xai"
    if lowered in _OPENAI_CODEX_PROVIDER_ALIASES:
        return STORY_VIDEO_IMAGE_PROVIDER
    return raw


def resolve_story_video_image_provider(
    args: dict[str, Any],
    *,
    prompt: str,
    provider_override: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    if not story_video_request_detected(prompt, args):
        return provider_override, None
    normalized = normalize_visual_provider(provider_override)
    if not normalized:
        return STORY_VIDEO_IMAGE_PROVIDER, None
    if normalized == STORY_VIDEO_IMAGE_PROVIDER:
        return STORY_VIDEO_IMAGE_PROVIDER, None
    provider = str(provider_override or normalized)
    return provider_override, {
        "success": False,
        "image": None,
        "error": (
            "Story-video source art must use OpenAI/openai-codex. "
            f"Blocked provider '{provider}' for this story-video request."
        ),
        "error_type": STORY_VIDEO_PROVIDER_ERROR_TYPE,
        "provider": provider,
        "required_provider": STORY_VIDEO_IMAGE_PROVIDER,
    }


def story_video_video_block_payload(
    args: dict[str, Any],
    *,
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any] | None:
    if not story_video_request_detected(prompt, args):
        return None
    return {
        "success": False,
        "video": None,
        "error": (
            "Story-video requests must use the story-video renderer with "
            "OpenAI/openai-codex source stills, narration-aligned cuts, "
            "subtitles, overlays, and render QC. Do not route the story-video "
            "body through generic video_generate or visual_package video."
        ),
        "error_type": STORY_VIDEO_PROVIDER_ERROR_TYPE,
        "provider": str(provider or ""),
        "model": str(model or ""),
        "required_image_provider": STORY_VIDEO_IMAGE_PROVIDER,
        "required_workflow": "story-video-production-pipeline",
    }
