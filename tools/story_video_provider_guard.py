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
    "科普影片",
    "介紹影片",
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
    r"(?:\d+\s*分鐘|\d+\s*mins?|\d+\s*min|大概\s*\d+|旁白|字幕|場景帳本)"
)

_STORY_VIDEO_FLAG_KEYS = (
    "story_video",
    "story_video_mode",
    "story_video_workflow",
    "use_story_video_workflow",
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


def story_video_request_detected(prompt: Any, args: Any = None) -> bool:
    if isinstance(args, dict) and any(
        _truthy_story_video_flag(args.get(key)) for key in _STORY_VIDEO_FLAG_KEYS
    ):
        return True
    text = strip_visual_prompt_metadata(prompt) if isinstance(prompt, str) else ""
    if not text:
        return False
    lowered = text.lower()
    compact = re.sub(r"[\s_\-.]+", "", lowered)
    if any(marker in lowered for marker in _DIRECT_STORY_VIDEO_MARKERS):
        return True
    if any(marker.replace("-", "").replace(" ", "") in compact for marker in _DIRECT_STORY_VIDEO_MARKERS):
        return True
    if _CHINESE_LONG_FORM_VIDEO_RE.search(text) and any(
        marker in text for marker in ("科普", "故事", "介紹", "長影片")
    ):
        return True
    long_form_hits = sum(1 for marker in _LONG_FORM_VIDEO_MARKERS if marker in lowered)
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
