from __future__ import annotations

import re
from typing import Any


_IMAGE_TOKENS = (
    "image",
    "photo",
    "picture",
    "illustration",
    "character art",
    "anime art",
    "圖片",
    "圖",
    "照片",
    "寫真",
    "產品攝影",
    "插畫",
    "繪圖",
    "繪製",
    "漫畫",
    "動漫圖",
    "角色設計",
)
_VIDEO_TOKENS = ("video", "clip", "motion", "影片", "視頻", "短片", "動畫")
_PORTRAIT_ASPECT_TOKENS = (
    "portrait",
    "vertical",
    "full body",
    "fashion",
    "全身",
    "直式",
    "直圖",
    "直向",
    "手機",
    "人像",
    "寫真",
    "腿部",
    "美腿",
)
_LANDSCAPE_ASPECT_TOKENS = (
    "landscape",
    "horizontal",
    "wide",
    "product photography",
    "desk",
    "橫式",
    "橫圖",
    "橫向",
    "寬景",
    "產品攝影",
    "商品攝影",
    "桌面",
    "白紙",
    "鋼筆",
)


def plan_visual_agent_request(
    prompt: str,
    *,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    prompt = str(prompt or "").strip()
    attachments = [item for item in (attachments or []) if isinstance(item, str) and item.strip()]
    wants_image = _contains_any(prompt, _IMAGE_TOKENS) or _looks_like_draw_image_request(prompt)
    wants_video = _contains_any(prompt, _VIDEO_TOKENS)
    if wants_video and attachments and _looks_like_image_to_video(prompt) and not _requests_new_image_output(prompt):
        wants_image = False
    if not wants_image and not wants_video and attachments:
        wants_video = True
    image_first_for_video = wants_video and not wants_image
    include_image = wants_image or (image_first_for_video and not attachments)
    should_use_visual_package = wants_image or wants_video
    arguments: dict[str, Any] = {
        "prompt": prompt,
        "include_image": include_image,
        "include_video": wants_video,
    }
    if attachments:
        arguments["attachments"] = attachments
    if wants_image or image_first_for_video:
        arguments["candidate_budget"] = 2 if image_first_for_video else 1
        arguments["candidate_budget_source"] = "planner_default"
    if wants_video:
        arguments["video_budget"] = 1
    aspect_ratio = _infer_aspect_ratio(prompt)
    if aspect_ratio is not None:
        arguments["aspect_ratio"] = aspect_ratio
    duration = _duration_seconds(prompt)
    if duration is not None:
        arguments["duration"] = duration
    return {
        "tool_name": "visual_package_generate",
        "should_use_visual_package": should_use_visual_package,
        "confidence": _confidence(wants_image=wants_image, wants_video=wants_video, attachments=attachments),
        "arguments": arguments,
        "recovery_policy": {
            "retry_budget": 1,
            "safe_reframe_allowed": True,
            "ask_user_on_low_confidence": True,
        },
        "reason": _reason(
            wants_image=wants_image,
            wants_video=wants_video,
            attachments=attachments,
            image_first_for_video=image_first_for_video,
        ),
    }


def _contains_any(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in tokens)


def _looks_like_draw_image_request(value: str) -> bool:
    lowered = str(value or "").lower()
    if any(token in lowered for token in ("draw ", "draw a", "draw an", "illustrate ", "sketch ", "render ")):
        return True
    compact = re.sub(r"\s+", "", str(value or ""))
    return any(
        token in compact
        for token in (
            "幫我畫",
            "請畫",
            "畫一位",
            "畫一個",
            "畫一張",
            "畫出",
            "畫成",
        )
    )


def _duration_seconds(value: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:秒|seconds?|sec)", value.lower())
    if not match:
        return None
    duration = int(match.group(1))
    return max(1, min(30, duration))


def _infer_aspect_ratio(value: str) -> str | None:
    lowered = str(value or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    if re.search(r"(?<!\d)1\s*[:：x/]\s*1(?!\d)", lowered) or "方形" in lowered or "square" in lowered:
        return "1:1"
    if re.search(r"(?<!\d)9\s*[:：x/]\s*16(?!\d)", lowered):
        return "9:16"
    if re.search(r"(?<!\d)16\s*[:：x/]\s*9(?!\d)", lowered):
        return "16:9"
    if any(token in lowered for token in _LANDSCAPE_ASPECT_TOKENS) or any(
        token in compact for token in ("16:9", "16：9")
    ):
        return "16:9"
    if any(token in lowered for token in _PORTRAIT_ASPECT_TOKENS) or any(
        token in compact for token in ("9:16", "9：16")
    ):
        return "9:16"
    return None


def _looks_like_image_to_video(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("這張圖", "this image", "this photo", "用這張"))


def _requests_new_image_output(value: str) -> bool:
    lowered = value.lower()
    return any(
        token in lowered
        for token in (
            "產出一張",
            "生成一張",
            "產生一張",
            "做一張",
            "一張圖片",
            "一張圖",
            "create an image",
            "generate an image",
            "make an image",
            "image plus",
        )
    )


def _confidence(*, wants_image: bool, wants_video: bool, attachments: list[str]) -> float:
    if wants_image and wants_video:
        return 0.9
    if wants_video and attachments:
        return 0.85
    if wants_image or wants_video:
        return 0.8
    return 0.0


def _reason(
    *,
    wants_image: bool,
    wants_video: bool,
    attachments: list[str],
    image_first_for_video: bool = False,
) -> str:
    if wants_image and wants_video:
        return "image_plus_video_request"
    if wants_video and attachments and image_first_for_video:
        return "attachment_to_video_image_first_request"
    if wants_video and attachments:
        return "attachment_to_video_request"
    if image_first_for_video:
        return "text_to_video_image_first_request"
    if wants_video:
        return "video_request"
    if wants_image:
        return "image_request"
    return "not_visual_agent_request"
