from __future__ import annotations

import re
from typing import Any

from agent.visual.feedback import is_visual_feedback_only_text
from agent.visual.feedback import parse_visual_feedback


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
    "character art",
    "anime art",
    "圖片",
    "圖",
    "照片",
    "寫真",
    "產品照",
    "產品攝影",
    "商品照",
    "插畫",
    "繪圖",
    "繪製",
    "漫畫",
    "動漫圖",
    "角色設計",
)
_VIDEO_TOKENS = (
    "video",
    "clip",
    "motion",
    "animate",
    "animated",
    "make it move",
    "bring it to life",
    "影片",
    "視頻",
    "短片",
    "動畫",
    "動圖",
    "動態",
    "動起來",
    "動態化",
    "做成動態",
)
_STORYBOARD_TOKENS = (
    "storyboard",
    "shot list",
    "multi-shot",
    "multishot",
    "sequence",
    "cinematic sequence",
    "coherent video",
    "分鏡",
    "多鏡頭",
    "多段",
    "多幕",
    "連貫影片",
    "連貫",
    "轉場",
    "剪輯",
    "合成一支",
    "組合成",
)
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
_POLISH_TOKENS = (
    "polish",
    "refine",
    "enhance",
    "quality pass",
    "quality polish",
    "web polish",
    "精修",
    "修圖",
    "潤飾",
    "美化",
    "畫質提升",
    "品質提升",
)


def plan_visual_agent_request(
    prompt: str,
    *,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    prompt = str(prompt or "").strip()
    attachments = [item for item in (attachments or []) if isinstance(item, str) and item.strip()]
    if _looks_like_text_only_visual_analysis(prompt):
        return _text_only_visual_analysis_plan()
    feedback_only = _visual_feedback_only_plan(prompt)
    if feedback_only is not None and not (attachments and _requests_visual_polish(prompt)):
        return feedback_only
    reference_binding = _reference_binding_for_prompt(prompt, attachments)
    effective_prompt = _prompt_with_reference_binding(prompt, reference_binding)
    wants_image = _contains_any(prompt, _IMAGE_TOKENS) or _looks_like_draw_image_request(prompt)
    wants_video = _contains_any(prompt, _VIDEO_TOKENS)
    polish_provider = _requested_polish_provider(prompt)
    polish_requested = _requests_visual_polish(prompt)
    if polish_requested and attachments and not wants_video:
        wants_image = True
    if wants_video and attachments and _looks_like_image_to_video(prompt) and not _requests_new_image_output(prompt):
        wants_image = False
    if not wants_image and not wants_video and attachments and polish_requested:
        wants_image = True
    elif not wants_image and not wants_video and attachments:
        wants_video = True
    image_first_for_video = wants_video and not wants_image
    storyboard_video = wants_video and _looks_like_storyboard_request(prompt)
    include_image = wants_image
    should_use_visual_package = wants_image or wants_video
    arguments: dict[str, Any] = {
        "prompt": effective_prompt,
        "include_image": include_image,
        "include_video": wants_video,
    }
    if attachments:
        arguments["attachments"] = attachments
    if reference_binding:
        arguments["reference_binding"] = reference_binding
    elif attachments and wants_image:
        arguments["reference_conditioning_policy"] = "collective_inspiration"
        arguments["reference_strategy"] = {
            "mode": "unassigned_collective_generation",
            "source": "visual_agent_planner",
            "requires_new_composition": True,
            "edit_anchor": False,
        }
    if wants_image or image_first_for_video:
        arguments["candidate_budget"] = 2
        arguments["candidate_budget_source"] = "planner_default"
    if wants_video:
        arguments["video_budget"] = 1
    if storyboard_video:
        arguments["storyboard"] = _build_storyboard_contract(prompt)
    aspect_ratio = _infer_aspect_ratio(prompt)
    if aspect_ratio is not None:
        arguments["aspect_ratio"] = aspect_ratio
    duration = _duration_seconds(prompt)
    if duration is not None:
        arguments["duration"] = duration
    image_provider = _requested_image_provider(prompt)
    image_provider_source = "prompt_override" if image_provider is not None else "visual_agent_default"
    if should_use_visual_package:
        arguments["image_provider"] = image_provider or VISUAL_MEDIA_PROVIDER_DEFAULT
        arguments["image_provider_source"] = image_provider_source
        if polish_provider is not None:
            arguments["polish_provider"] = polish_provider
            arguments["polish_provider_source"] = "prompt_override"
    return {
        "tool_name": "visual_package_generate",
        "should_use_visual_package": should_use_visual_package,
        "confidence": _confidence(wants_image=wants_image, wants_video=wants_video, attachments=attachments),
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
            image_first_for_video=image_first_for_video,
            storyboard_video=storyboard_video,
        ),
    }


def _text_only_visual_analysis_plan() -> dict[str, Any]:
    return {
        "tool_name": "visual_feedback",
        "should_use_visual_package": False,
        "confidence": 0.91,
        "arguments": {},
        "provider_contract": _provider_contract(None),
        "recovery_policy": {
            "retry_budget": 0,
            "safe_reframe_allowed": False,
            "ask_user_on_low_confidence": False,
        },
        "reason": "text_only_visual_analysis",
    }


def _visual_feedback_only_plan(prompt: str) -> dict[str, Any] | None:
    parsed = parse_visual_feedback(prompt)
    if not is_visual_feedback_only_text(prompt):
        return None
    return {
        "tool_name": "visual_feedback",
        "should_use_visual_package": False,
        "confidence": 0.86,
        "arguments": {},
        "provider_contract": _provider_contract(None),
        "recovery_policy": {
            "retry_budget": 0,
            "safe_reframe_allowed": False,
            "ask_user_on_low_confidence": False,
        },
        "reason": "visual_feedback_only",
        "feedback": {
            "polarity": parsed.polarity,
            "signals": list(parsed.parsed.get("signals") or []),
            "issues": list(parsed.parsed.get("issues") or []),
            "selection_hint": parsed.selection_hint,
            "selection_label": parsed.selection_label,
        },
    }

def _contains_any(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in tokens)


def _looks_like_text_only_visual_analysis(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    if not lowered:
        return False
    has_visual_term = (
        _contains_any(lowered, _IMAGE_TOKENS)
        or _contains_any(lowered, _VIDEO_TOKENS)
        or any(token in compact for token in ("產圖", "生圖", "生成圖片", "生成影片"))
    )
    if not has_visual_term:
        return False
    no_media = any(
        marker in compact
        for marker in (
            "不要產圖",
            "不要生圖",
            "不產圖",
            "不能產圖",
            "不得產圖",
            "不准產圖",
            "不能生圖",
            "不要生成圖片",
            "不能生成圖片",
            "不要生成影片",
            "不能生成影片",
            "禁止產圖",
            "禁止生成",
        )
    ) or any(
        marker in lowered
        for marker in (
            "no image generation",
            "no video generation",
            "do not generate image",
            "do not generate video",
            "don't generate image",
            "don't generate video",
        )
    )
    no_tools = any(
        marker in compact
        for marker in (
            "不要用工具",
            "不用工具",
            "不能用工具",
            "不得用工具",
            "不准用工具",
            "不要呼叫工具",
            "不能呼叫工具",
            "不使用工具",
        )
    ) or any(
        marker in lowered
        for marker in (
            "no tools",
            "no-tool",
            "without tools",
            "do not use tools",
            "do not call tools",
            "don't use tools",
            "don't call tools",
        )
    )
    text_only = any(
        marker in compact
        for marker in (
            "純文字",
            "纯文字",
            "文字任務",
            "文字任务",
            "只用六行回答",
            "只用三行回答",
            "只回答",
        )
    ) or any(marker in lowered for marker in ("text-only", "text only", "llm-only", "llm only"))
    meta_or_analysis = any(
        marker in compact
        for marker in (
            "分析",
            "判斷",
            "判断",
            "路由",
            "證據",
            "证据",
            "驗證",
            "验证",
            "公開raphael",
            "宣稱完成",
        )
    ) or any(marker in lowered for marker in ("proof", "route", "routing", "provider", "overclaim"))
    return no_media and (no_tools or text_only or meta_or_analysis)


def _reference_binding_for_prompt(prompt: str, attachments: list[str]) -> dict[str, Any] | None:
    if not attachments:
        return None
    lowered = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    referenced_indices = [
        index
        for index in range(1, len(attachments) + 1)
        if _mentions_reference_index(compact, index)
    ]
    if not referenced_indices:
        return None
    reference_order = []
    for index in referenced_indices:
        role_hint = _role_hint_for_reference(compact, index) or "visual_reference"
        reference_order.append(
            {
                "index": index,
                "role_hint": role_hint,
                "attachment": attachments[index - 1],
            }
        )
    return {
        "mode": "ordered_references",
        "reference_order_source": "user_visible_upload_order",
        "role_policy": "derive_from_user_prompt",
        "reference_order": reference_order,
    }


def _mentions_reference_index(compact_prompt: str, index: int) -> bool:
    return bool(_reference_mention_spans(compact_prompt, index))


def _reference_mention_spans(compact_prompt: str, index: int) -> list[tuple[int, int]]:
    chinese_index = _chinese_reference_index(index)
    tokens = (
        f"ref{index}",
        f"reference{index}",
        f"參考{index}",
        f"參考圖{index}",
        f"第{index}張",
        f"第{chinese_index}張",
    )
    spans: list[tuple[int, int]] = []
    for token in tokens:
        start = compact_prompt.find(token)
        while start != -1:
            spans.append((start, start + len(token)))
            start = compact_prompt.find(token, start + len(token))
    return sorted(spans)


def _chinese_reference_index(index: int) -> str:
    numerals = {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
        10: "十",
    }
    return numerals.get(index, str(index))


_REFERENCE_ROLE_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "character_identity",
        (
            "角色",
            "人物",
            "主角",
            "身份",
            "人設",
            "臉",
            "髮型",
            "character",
            "identity",
            "person",
            "people",
            "subject",
            "face",
            "hair",
        ),
    ),
    (
        "pose_composition",
        (
            "姿勢",
            "動作",
            "構圖",
            "角度",
            "鏡頭",
            "pose",
            "bodyposition",
            "framing",
            "composition",
            "cameraangle",
        ),
    ),
    (
        "wardrobe",
        (
            "服裝",
            "衣服",
            "穿搭",
            "造型",
            "服飾",
            "wardrobe",
            "outfit",
            "clothing",
            "clothes",
            "costume",
        ),
    ),
    (
        "style",
        (
            "風格",
            "畫風",
            "筆觸",
            "style",
            "artstyle",
            "renderingstyle",
        ),
    ),
    (
        "background",
        (
            "背景",
            "場景",
            "環境",
            "background",
            "scene",
            "environment",
        ),
    ),
)


def _role_hint_for_reference(compact_prompt: str, index: int) -> str | None:
    spans = _reference_mention_spans(compact_prompt, index)
    if not spans:
        return None
    all_spans = sorted(
        span
        for ref_index in _candidate_reference_indices(compact_prompt)
        for span in _reference_mention_spans(compact_prompt, ref_index)
    )
    for start, end in spans:
        direct_end = _next_reference_start(all_spans, start) or _clause_end(compact_prompt, end)
        role_hint = _role_hint_from_text(compact_prompt[start:direct_end])
        if role_hint:
            return role_hint
        clause_start = _clause_start(compact_prompt, start)
        clause_end = _clause_end(compact_prompt, end)
        role_hint = _role_hint_from_text(compact_prompt[clause_start:clause_end])
        if role_hint:
            return role_hint
    return None


def _candidate_reference_indices(compact_prompt: str) -> list[int]:
    indices = {int(match.group(1)) for match in re.finditer(r"(?:ref|reference|參考圖?|第)(\d+)", compact_prompt)}
    for value, numeral in {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
        10: "十",
    }.items():
        if f"第{numeral}張" in compact_prompt:
            indices.add(value)
    return sorted(indices)


def _next_reference_start(spans: list[tuple[int, int]], current_start: int) -> int | None:
    for start, _end in spans:
        if start > current_start:
            return start
    return None


def _clause_start(value: str, position: int) -> int:
    separators = "，,。.;；\n"
    starts = [value.rfind(separator, 0, position) for separator in separators]
    start = max(starts)
    return 0 if start == -1 else start + 1


def _clause_end(value: str, position: int) -> int:
    separators = "，,。.;；\n"
    ends = [found for separator in separators if (found := value.find(separator, position)) != -1]
    return min(ends) if ends else len(value)


def _role_hint_from_text(value: str) -> str | None:
    best_role: str | None = None
    best_position: int | None = None
    for role, tokens in _REFERENCE_ROLE_TOKENS:
        positions = [position for token in tokens if (position := value.find(token)) != -1]
        if not positions:
            continue
        role_position = min(positions)
        if best_position is None or role_position < best_position:
            best_position = role_position
            best_role = role
    return best_role


def _prompt_with_reference_binding(prompt: str, binding: dict[str, Any] | None) -> str:
    if not binding:
        return prompt
    return f"{prompt}\n\n{_reference_binding_prompt_block(binding)}"


def _reference_binding_prompt_block(binding: dict[str, Any]) -> str:
    parts = [
        "Reference binding: reference N/ref N means the Nth uploaded image in the user's "
        "visible attachment order; reference 1 means the first uploaded image in the user's "
        "visible attachment order. Do not assume fixed roles for any reference index. Derive "
        "each reference role from the user's wording, such as character identity/person, "
        "pose/composition, clothing, wardrobe, style, or background. If a role is not explicit, "
        "treat that reference as a neutral visual reference instead of assigning character or "
        "pose by default."
    ]
    role_block = _reference_role_contract_block(binding)
    if role_block:
        parts.append(role_block)
    return "\n\n".join(parts)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _reference_role_contract_block(binding: dict[str, Any]) -> str:
    role_lines = []
    for item in binding.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        index = _coerce_int(item.get("index"))
        role_hint = str(item.get("role_hint") or "").strip()
        if index is None or not role_hint:
            continue
        role_lines.append(f"- ref {index} role: {role_hint}")
    if not role_lines:
        return ""
    return "\n".join(
        [
            "Reference roles for this request:",
            *role_lines,
            "Use each reference only for its listed role. Do not transfer character identity "
            "from a pose/composition reference, and do not transfer pose/composition from a "
            "character identity reference unless the user explicitly asks for that blend.",
            "For character_identity references, preserve the subject identity, face, hair, eye color, "
            "signature outfit, silhouette, accessories, and palette from that reference.",
            "For pose_composition references, use only pose, camera angle, framing, body orientation, "
            "limb placement, and scene layout; do not copy that reference's character, face, hair, "
            "wardrobe, color palette, or identity traits unless explicitly requested.",
        ]
    )


def _requested_image_provider(value: str) -> str | None:
    lowered = str(value or "").lower()
    compact = re.sub(r"[\s_\-.]+", "", lowered)
    if _requested_polish_provider(value):
        return None
    if (
        "grokwebimagine" in compact
        or "grokweb" in compact
        or "grok web imagine" in lowered
    ):
        return "grok-web-imagine"
    if "grok" in lowered or "x.ai" in lowered or re.search(r"\bxai\b", lowered):
        return "xai"
    if (
        "openai" in lowered
        or "codex" in lowered
        or "gpt-image" in lowered
        or "image2" in compact
    ):
        return "openai-codex"
    return None


def _requested_polish_provider(value: str) -> str | None:
    lowered = str(value or "").lower()
    compact = re.sub(r"[\s_\-.]+", "", lowered)
    if not _requests_visual_polish(value):
        return None
    if "grok web" in lowered or "web polish" in lowered or compact in {"grokwebpolish"}:
        return "grok-web-imagine"
    return None


def _requests_visual_polish(value: str) -> bool:
    lowered = str(value or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    if "prompt" in lowered or "提示詞" in lowered or "提示词" in lowered:
        return False
    return any(token in lowered for token in _POLISH_TOKENS) or any(
        token in compact
        for token in (
            "精修",
            "修圖",
            "润饰",
            "潤飾",
            "美化",
            "畫質提升",
            "画质提升",
            "品質提升",
            "品质提升",
        )
    )


def _provider_contract(image_provider_override: str | None) -> dict[str, Any]:
    return {
        "base_llm_provider": BASE_LLM_PROVIDER,
        "base_llm_model": BASE_LLM_MODEL,
        "visual_agent_llm_provider": VISUAL_AGENT_LLM_PROVIDER,
        "visual_agent_llm_model": VISUAL_AGENT_LLM_MODEL,
        "visual_media_provider_default": VISUAL_MEDIA_PROVIDER_DEFAULT,
        "visual_media_model_default": VISUAL_MEDIA_MODEL_DEFAULT,
        "visual_media_provider_override": image_provider_override,
    }


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


def _looks_like_storyboard_request(value: str) -> bool:
    lowered = str(value or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    return any(token in lowered for token in _STORYBOARD_TOKENS) or any(
        token in compact for token in ("三段", "四段", "五段", "六段", "三幕", "四幕", "五幕", "六幕")
    )


def _build_storyboard_contract(value: str) -> dict[str, Any]:
    shot_count = _storyboard_shot_count(value)
    return {
        "enabled": True,
        "mode": "multi_shot_video",
        "shot_count": shot_count,
        "candidate_budget_per_shot": 2,
        "source_image_policy": "one_ranked_image_per_shot",
        "composition_target": "single_coherent_video",
        "delivery_policy": "deliver_composed_video_when_available_else_selected_clips",
        "shots": _storyboard_shots(shot_count),
    }


def _storyboard_shot_count(value: str) -> int:
    lowered = str(value or "").lower()
    match = re.search(r"(\d+)\s*(?:shots?|clips?|scenes?|segments?|段|幕|個分鏡|鏡頭)", lowered)
    if match:
        return max(2, min(6, int(match.group(1))))
    compact = re.sub(r"\s+", "", lowered)
    chinese_numbers = {
        "二": 2,
        "兩": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
    }
    for text, count in chinese_numbers.items():
        if any(token in compact for token in (f"{text}段", f"{text}幕", f"{text}個分鏡", f"{text}鏡頭")):
            return count
    return 3


def _storyboard_shots(shot_count: int) -> list[dict[str, Any]]:
    roles = [
        "establishing_context",
        "subject_focus",
        "detail_closeup",
        "motion_variation",
        "alternate_angle",
        "closing_hero",
    ]
    shots = []
    for index in range(shot_count):
        shots.append(
            {
                "shot_id": f"shot_{index + 1}",
                "role": roles[index] if index < len(roles) else "continuity_shot",
                "source_image_policy": "single_ranked_image",
                "clip_target": "one_video_clip",
            }
        )
    return shots


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
    return any(
        token in lowered
        for token in (
            "這張圖",
            "這張照片",
            "this image",
            "this photo",
            "this picture",
            "用這張",
        )
    )


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
    storyboard_video: bool = False,
) -> str:
    if storyboard_video:
        return "storyboard_video_request"
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
