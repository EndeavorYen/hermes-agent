"""Rule-based mission planner for Visual Agent Mode."""

from __future__ import annotations

import re
import uuid
from typing import List, Optional

from agent.visual.agent_mode.types import VisualMission, VisualMissionType


_VIDEO_TOKENS = (
    "video",
    "videos",
    "clip",
    "clips",
    "animate",
    "animation",
    "影片",
    "视频",
    "視頻",
    "短片",
    "動畫",
    "动画",
    "動圖",
    "动图",
    "動態",
    "动态",
)
_IMAGE_TOKENS = (
    "image",
    "images",
    "photo",
    "photos",
    "picture",
    "pictures",
    "portrait",
    "portraits",
    "圖片",
    "图片",
    "照片",
    "相片",
    "圖",
    "图",
    "寫真",
    "写真",
    "產圖",
    "产图",
    "出圖",
    "出图",
    "畫圖",
    "画图",
)
_VISUAL_PACKAGE_IMAGE_HINTS = (
    "視覺素材",
    "视觉素材",
    "視覺資產",
    "视觉资产",
    "visual material",
    "visual materials",
    "visual asset",
    "visual assets",
    "visual package",
    "product showcase",
)
_REPAIR_TOKENS = ("repair", "fix", "revise", "improve", "retry", "修復", "修正", "修改", "重試", "重试")
_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}
_ZH_COUNT_WORDS = {
    "一": 1,
    "二": 2,
    "兩": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def plan_visual_mission(
    user_prompt: str,
    attachments: Optional[List[str]] = None,
    autonomy_level: int = 1,
) -> VisualMission:
    text = (user_prompt or "").strip()
    lowered = text.lower()
    wants_video = _contains_any(lowered, _VIDEO_TOKENS)
    wants_image = _contains_any(lowered, _IMAGE_TOKENS) or (
        wants_video and _contains_any(lowered, _VISUAL_PACKAGE_IMAGE_HINTS)
    )
    wants_repair = _contains_any(lowered, _REPAIR_TOKENS)
    count = _extract_requested_count(text, default=3)
    mission_type = _mission_type(
        wants_image=wants_image,
        wants_video=wants_video,
        wants_repair=wants_repair,
    )
    requested_outputs = []
    if wants_image or not wants_video:
        requested_outputs.append("image")
    if wants_video:
        requested_outputs.append("video")

    return VisualMission(
        mission_id=_new_mission_id(),
        mission_type=mission_type,
        user_prompt=text,
        output_goal=text,
        requested_outputs=requested_outputs,
        input_assets=list(attachments or []),
        candidate_budget=count if wants_image or not wants_video else 1,
        video_budget=1 if wants_video else 0,
        autonomy_level=_clamp_autonomy(autonomy_level),
    )


def _new_mission_id() -> str:
    return f"vms_{uuid.uuid4().hex}"


def _mission_type(*, wants_image: bool, wants_video: bool, wants_repair: bool) -> VisualMissionType:
    if wants_repair:
        return VisualMissionType.REPAIR_EXISTING
    if wants_video and wants_image:
        return VisualMissionType.VISUAL_PACKAGE
    if wants_video:
        return VisualMissionType.IMAGE_TO_VIDEO
    return VisualMissionType.IMAGE_SET


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _extract_requested_count(text: str, *, default: int) -> int:
    lowered = text.lower()
    zh_image_count_match = re.search(
        r"([一二兩两三四五六七八九十]|[1-9]\d?)\s*"
        r"(?:張|张|幅|個|个|組|组)?\s*"
        r"[\w\s\-（）()，、的]{0,16}?"
        r"(?:圖片|图片|照片|相片|產品圖|产品图|靜態圖|静态图|圖|图|寫真|写真)",
        text,
    )
    if zh_image_count_match:
        return _count_token_to_int(zh_image_count_match.group(1))

    count_tokens = "|".join(["[1-9]\\d?", *_COUNT_WORDS.keys()])
    image_count_match = re.search(
        rf"\b({count_tokens})\s+(?:editorial\s+)?(?:image|images|photo|photos|picture|pictures|portrait|portraits|option|options)\b",
        lowered,
    )
    if image_count_match:
        return _count_token_to_int(image_count_match.group(1))
    number_match = re.search(r"\b([1-9]\d?)\b", lowered)
    if number_match:
        return max(1, min(12, int(number_match.group(1))))
    for word, value in _COUNT_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return value
    return default


def _count_token_to_int(token: str) -> int:
    if token.isdigit():
        return max(1, min(12, int(token)))
    if token in _ZH_COUNT_WORDS:
        return _ZH_COUNT_WORDS[token]
    return _COUNT_WORDS[token]


def _clamp_autonomy(value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 1
    return max(0, min(4, number))
