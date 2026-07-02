from __future__ import annotations

import re
from typing import Any

from agent.visual.prompt_disclosure import is_visual_prompt_disclosure_request


BASE_LLM_PROVIDER = "openai-codex"
BASE_LLM_MODEL = "gpt-5.5"
VISUAL_AGENT_LLM_PROVIDER = "xai-oauth"
VISUAL_AGENT_LLM_MODEL = "grok-4.3"
VISUAL_MEDIA_PROVIDER_DEFAULT = "xai"
VISUAL_MEDIA_MODEL_DEFAULT = "grok-imagine-image-quality"

_IMAGE_TOKENS = (
    "image",
    "photo",
    "picture",
    "illustration",
    "圖片",
    "照片",
    "寫真",
    "產品圖",
    "產品照",
    "動漫圖",
    "角色",
    "產出一張",
    "做一張",
    "畫",
)
_VIDEO_TOKENS = (
    "video",
    "clip",
    "motion",
    "animate",
    "animated",
    "影片",
    "視頻",
    "短片",
    "動畫",
    "動圖",
    "動起來",
    "動態化",
    "做成",
)
_PORTRAIT_ASPECT_TOKENS = (
    "portrait",
    "vertical",
    "full body",
    "fashion",
    "全身",
    "直式",
    "直向",
    "人像",
    "寫真",
    "時尚",
)
_LANDSCAPE_ASPECT_TOKENS = (
    "landscape",
    "horizontal",
    "wide",
    "product photography",
    "desk",
    "橫式",
    "橫向",
    "產品攝影",
    "白紙",
    "鋼筆",
)


def plan_visual_agent_request(
    prompt: str,
    *,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    prompt = str(prompt or "").strip()
    attachments = [
        item.strip()
        for item in (attachments or [])
        if isinstance(item, str) and item.strip()
    ]
    if _looks_like_text_only_visual_analysis(prompt):
        return _non_package_plan("text_only_visual_analysis")
    if is_visual_prompt_disclosure_request(prompt):
        return _non_package_plan("visual_prompt_disclosure")

    wants_image = _contains_any(prompt, _IMAGE_TOKENS) or _looks_like_draw_request(prompt)
    wants_video = _contains_any(prompt, _VIDEO_TOKENS)
    if attachments and wants_video and _looks_like_image_to_video(prompt):
        wants_image = False
    elif attachments and not wants_image and not wants_video:
        wants_video = True

    should_use_visual_package = wants_image or wants_video
    if not should_use_visual_package:
        return _non_package_plan("no_visual_request")

    arguments: dict[str, Any] = {
        "prompt": prompt,
        "include_image": wants_image,
        "include_video": wants_video,
    }
    if attachments:
        arguments["attachments"] = attachments
    if wants_image or wants_video:
        arguments["candidate_budget"] = 2
        arguments["candidate_budget_source"] = "planner_default"
    if wants_video:
        arguments["video_budget"] = 1

    duration = _duration_seconds(prompt)
    if duration is not None:
        arguments["duration"] = duration
    aspect_ratio = _infer_aspect_ratio(prompt)
    if aspect_ratio is not None:
        arguments["aspect_ratio"] = aspect_ratio

    image_provider = _requested_image_provider(prompt)
    arguments["image_provider"] = image_provider or VISUAL_MEDIA_PROVIDER_DEFAULT
    arguments["image_provider_source"] = (
        "prompt_override" if image_provider is not None else "visual_agent_default"
    )

    return {
        "tool_name": "visual_package_generate",
        "should_use_visual_package": True,
        "confidence": 0.84,
        "arguments": arguments,
        "provider_contract": _provider_contract(image_provider),
        "recovery_policy": {
            "retry_budget": 1,
            "safe_reframe_allowed": True,
            "ask_user_on_low_confidence": True,
        },
        "reason": _reason(
            wants_image=wants_image,
            wants_video=wants_video,
            attachments=attachments,
        ),
    }


def _non_package_plan(reason: str) -> dict[str, Any]:
    return {
        "tool_name": "visual_package_generate",
        "should_use_visual_package": False,
        "confidence": 0.9,
        "arguments": {},
        "provider_contract": _provider_contract(None),
        "recovery_policy": {
            "retry_budget": 0,
            "safe_reframe_allowed": False,
            "ask_user_on_low_confidence": False,
        },
        "reason": reason,
    }


def _contains_any(prompt: str, tokens: tuple[str, ...]) -> bool:
    lowered = prompt.lower()
    return any(token in lowered for token in tokens)


def _looks_like_draw_request(prompt: str) -> bool:
    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", lowered)
    return any(token in compact for token in ("幫我畫", "帮我画", "畫一", "画一"))


def _looks_like_image_to_video(prompt: str) -> bool:
    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", lowered)
    return (
        "this image" in lowered
        or "this photo" in lowered
        or "這張圖" in compact
        or "这张图" in compact
        or "這張照片" in compact
        or "让这张图" in compact
        or "讓這張圖" in compact
    )


def _looks_like_text_only_visual_analysis(prompt: str) -> bool:
    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", lowered)
    negates_generation = any(
        token in compact
        for token in (
            "不能產圖",
            "不能产图",
            "不要產圖",
            "不要产图",
            "不產圖",
            "不产图",
            "不能用工具",
            "不要用工具",
        )
    ) or any(token in lowered for token in ("do not generate", "no image generation"))
    asks_for_text = any(token in compact for token in ("請只用", "请只用", "回答"))
    return negates_generation and asks_for_text


def _duration_seconds(prompt: str) -> int | None:
    match = re.search(r"(\d{1,2})\s*(?:秒|seconds?|sec|s)", prompt.lower())
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def _infer_aspect_ratio(prompt: str) -> str | None:
    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", lowered)
    if "1:1" in lowered or "square" in lowered or "方形" in compact:
        return "1:1"
    if _contains_any(prompt, _PORTRAIT_ASPECT_TOKENS):
        return "9:16"
    if _contains_any(prompt, _LANDSCAPE_ASPECT_TOKENS):
        return "16:9"
    return None


def _requested_image_provider(prompt: str) -> str | None:
    lowered = prompt.lower()
    compact = re.sub(r"[\s_\-.]+", "", lowered)
    if "grok web imagine" in lowered or "grokwebimagine" in compact:
        return "grok-web-imagine"
    if "openai" in lowered or "codex" in lowered or "image2" in compact:
        return "openai-codex"
    if "grok" in lowered or "x.ai" in lowered or re.search(r"\bxai\b", lowered):
        return "xai"
    return None


def _provider_contract(image_provider: str | None) -> dict[str, Any]:
    return {
        "base_llm_provider": BASE_LLM_PROVIDER,
        "base_llm_model": BASE_LLM_MODEL,
        "visual_agent_llm_provider": VISUAL_AGENT_LLM_PROVIDER,
        "visual_agent_llm_model": VISUAL_AGENT_LLM_MODEL,
        "visual_media_provider_default": VISUAL_MEDIA_PROVIDER_DEFAULT,
        "visual_media_model_default": VISUAL_MEDIA_MODEL_DEFAULT,
        "visual_media_provider_override": image_provider,
    }


def _reason(
    *,
    wants_image: bool,
    wants_video: bool,
    attachments: list[str],
) -> str:
    if wants_image and wants_video:
        return "image_plus_video_request"
    if wants_video and attachments and not wants_image:
        return "attachment_to_video_image_first_request"
    if wants_video and not wants_image:
        return "text_to_video_image_first_request"
    if wants_image:
        return "image_request"
    return "no_visual_request"
