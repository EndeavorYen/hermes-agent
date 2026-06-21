from __future__ import annotations

import re
from typing import Any


_IMAGE_TOKENS = ("image", "photo", "picture", "圖片", "圖", "照片", "寫真", "產品攝影")
_VIDEO_TOKENS = ("video", "clip", "motion", "影片", "視頻", "短片", "動畫")


def plan_visual_agent_request(
    prompt: str,
    *,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    prompt = str(prompt or "").strip()
    attachments = [item for item in (attachments or []) if isinstance(item, str) and item.strip()]
    wants_image = _contains_any(prompt, _IMAGE_TOKENS)
    wants_video = _contains_any(prompt, _VIDEO_TOKENS)
    if wants_video and attachments and _looks_like_image_to_video(prompt):
        wants_image = False
    if not wants_image and not wants_video and attachments:
        wants_video = True
    should_use_visual_package = wants_image or wants_video
    arguments: dict[str, Any] = {
        "prompt": prompt,
        "include_image": wants_image,
        "include_video": wants_video,
    }
    if attachments:
        arguments["attachments"] = attachments
    if wants_image:
        arguments["candidate_budget"] = 1
    if wants_video:
        arguments["video_budget"] = 1
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
        "reason": _reason(wants_image=wants_image, wants_video=wants_video, attachments=attachments),
    }


def _contains_any(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in tokens)


def _duration_seconds(value: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:秒|seconds?|sec)", value.lower())
    if not match:
        return None
    duration = int(match.group(1))
    return max(1, min(30, duration))


def _looks_like_image_to_video(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("這張圖", "this image", "this photo", "用這張"))


def _confidence(*, wants_image: bool, wants_video: bool, attachments: list[str]) -> float:
    if wants_image and wants_video:
        return 0.9
    if wants_video and attachments:
        return 0.85
    if wants_image or wants_video:
        return 0.8
    return 0.0


def _reason(*, wants_image: bool, wants_video: bool, attachments: list[str]) -> str:
    if wants_image and wants_video:
        return "image_plus_video_request"
    if wants_video and attachments:
        return "attachment_to_video_request"
    if wants_video:
        return "video_request"
    if wants_image:
        return "image_request"
    return "not_visual_agent_request"
