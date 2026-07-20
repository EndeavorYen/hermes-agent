from __future__ import annotations

import hashlib
import json
from typing import Any


TONE_CATALOG_SCHEMA = "story_video_tone_catalog_v1"

APPROVED_MODIFIERS = (
    "whispered",
    "breathy",
    "trembling",
    "restrained",
    "urgent",
    "hesitant",
    "soft",
    "firm",
)

SAFE_BOUNDS = {
    "speed_multiplier": [0.90, 1.10],
    "temperature_delta": [-0.10, 0.10],
    "ordinary_pause_seconds": [0.08, 0.35],
    "ellipsis_pause_seconds_max": 0.45,
    "pitch_shift_semitones": 0,
}

EMOTION_TO_TONE = {
    "neutral": "general.neutral",
    "wonder": "general.excited",
    "curious": "general.puzzled",
    "joy": "general.joyful",
    "sadness": "general.sad",
    "fear": "general.tense",
    "tension": "general.tense",
    "surprise": "general.excited",
    "humor": "general.joyful",
    "warmth": "general.warm",
}

# Order is semantic precedence. Specific adult concepts precede broader
# closeness words, and adult matches are still gated by content_rating.
ACTION_TO_TONE = (
    ("adult.desirous", ("渴望", "慾望", "欲望")),
    ("adult.breathless", ("氣息急促", "呼吸急促")),
    ("adult.flirtatious", ("挑逗", "撩撥", "調情")),
    ("adult.intimate", ("親密", "貼近", "靠近耳邊")),
    ("adult.shy", ("害羞", "羞怯")),
    ("adult.teasing", ("戲弄", "逗弄")),
    ("adult.commanding", ("命令", "不容拒絕", "強勢")),
    ("adult.receptive", ("接受", "回應", "順從")),
    ("adult.intense", ("強烈", "激烈", "迫切")),
    ("adult.afterglow", ("餘韻", "事後依偎")),
    ("general.warm", ("溫暖", "溫柔", "柔和")),
    ("general.joyful", ("開心", "愉快", "笑著")),
    ("general.excited", ("興奮", "激動", "雀躍")),
    ("general.sad", ("難過", "悲傷", "哀傷")),
    ("general.angry", ("生氣", "憤怒", "惱怒")),
    ("general.tense", ("緊張", "不安", "戒備")),
    ("general.puzzled", ("疑惑", "困惑", "不解")),
)

ACTION_TO_MODIFIER = (
    ("whispered", ("壓低聲音", "耳語", "悄聲", "輕聲")),
    ("breathy", ("氣音", "帶氣聲")),
    ("trembling", ("顫抖", "發抖", "聲音發顫")),
    ("restrained", ("壓抑", "克制", "忍住")),
    ("urgent", ("急促", "急切", "迫切")),
    ("hesitant", ("猶豫", "遲疑", "吞吞吐吐")),
    ("soft", ("輕聲", "柔聲", "輕柔")),
    ("firm", ("堅定", "斬釘截鐵", "強硬")),
)


class ToneMapError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def _definition(
    label: str,
    delivery: str,
    allowed_modifiers: tuple[str, ...],
    instruct: str,
    expressiveness: str,
    speed_multiplier: float,
    temperature_delta: float,
    pause_seconds: float,
) -> dict[str, Any]:
    return {
        "label": label,
        "delivery": delivery,
        "allowed_modifiers": allowed_modifiers,
        "instruct": instruct,
        "expressiveness": expressiveness,
        "speed_multiplier": speed_multiplier,
        "temperature_delta": temperature_delta,
        "pause_seconds": pause_seconds,
    }


_TONE_DEFINITIONS = {
    "general.neutral": _definition(
        "自然", "clear, stable, unmarked", APPROVED_MODIFIERS,
        "", "natural", 1.00, 0.00, 0.18,
    ),
    "general.warm": _definition(
        "溫暖", "gentle, close, slightly slower",
        ("whispered", "breathy", "restrained", "hesitant", "soft"),
        "語氣溫暖柔和，親近而自然地說", "natural", 0.97, -0.03, 0.22,
    ),
    "general.joyful": _definition(
        "開心", "bright, smiling, light rhythm",
        ("breathy", "urgent", "soft"),
        "帶著自然笑意，明亮輕快地說", "lively", 1.04, 0.04, 0.14,
    ),
    "general.excited": _definition(
        "興奮", "energetic, faster, short pauses",
        ("breathy", "urgent", "firm"),
        "帶著興奮活力，節奏明快但保持清楚咬字", "lively", 1.08, 0.07, 0.10,
    ),
    "general.sad": _definition(
        "難過", "subdued, slower, longer pauses",
        ("whispered", "breathy", "trembling", "restrained", "hesitant", "soft"),
        "語氣低落克制，放慢速度並保持清楚咬字", "restrained", 0.93, -0.06, 0.30,
    ),
    "general.angry": _definition(
        "生氣", "firm, precise articulation",
        ("restrained", "urgent", "firm"),
        "語氣生氣而堅定，清楚有力但不要喊叫", "dramatic", 1.03, 0.03, 0.12,
    ),
    "general.tense": _definition(
        "緊張", "restrained, short phrases",
        ("whispered", "breathy", "trembling", "restrained", "urgent", "hesitant", "firm"),
        "帶著緊張與克制，用較短語句清楚地說", "restrained", 1.01, 0.02, 0.13,
    ),
    "general.puzzled": _definition(
        "疑惑", "hesitant, questioning cadence",
        ("whispered", "trembling", "restrained", "hesitant", "soft"),
        "帶著疑惑與些許猶豫，自然地問", "natural", 0.98, 0.00, 0.22,
    ),
    "adult.flirtatious": _definition(
        "挑逗", "confident, light, smiling",
        ("whispered", "breathy", "restrained", "hesitant", "soft", "firm"),
        "帶著自信而輕巧的挑逗語氣，自然含笑地說", "lively", 1.02, 0.03, 0.16,
    ),
    "adult.intimate": _definition(
        "親密", "warm, close, soft",
        ("whispered", "breathy", "restrained", "hesitant", "soft"),
        "語氣親密溫暖，靠近並柔和地說，保持自然咬字", "natural", 0.95, -0.04, 0.24,
    ),
    "adult.desirous": _definition(
        "渴望", "lower, restrained, gradually rising",
        ("whispered", "breathy", "trembling", "restrained", "urgent", "hesitant", "soft"),
        "帶著壓抑的渴望，聲線稍低並逐漸加強，保持自然咬字", "dramatic", 0.96, 0.04, 0.20,
    ),
    "adult.breathless": _definition(
        "氣息急促", "shorter phrases, bounded irregular pauses",
        ("breathy", "trembling", "restrained", "urgent", "hesitant", "soft"),
        "用較短語句與略不規則但克制的停頓來說，保持完整咬字", "natural", 1.00, 0.00, 0.16,
    ),
    "adult.shy": _definition(
        "害羞", "quiet, hesitant, slightly slower",
        ("whispered", "breathy", "trembling", "restrained", "hesitant", "soft"),
        "語氣安靜害羞，帶些猶豫並稍微放慢", "restrained", 0.94, -0.04, 0.25,
    ),
    "adult.teasing": _definition(
        "戲弄", "playful rhythm and smiling endings",
        ("whispered", "breathy", "restrained", "hesitant", "soft", "firm"),
        "用俏皮節奏戲弄地說，句尾帶自然笑意", "lively", 1.03, 0.04, 0.14,
    ),
    "adult.commanding": _definition(
        "強勢", "steady, deliberate, clearly articulated",
        ("restrained", "urgent", "firm"),
        "語氣強勢沉穩，刻意放清楚每個字", "dramatic", 0.99, 0.02, 0.17,
    ),
    "adult.receptive": _definition(
        "接受", "soft, responsive, lower force",
        ("whispered", "breathy", "trembling", "restrained", "hesitant", "soft"),
        "語氣柔和回應，降低力道並保持親近自然", "natural", 0.96, -0.03, 0.21,
    ),
    "adult.intense": _definition(
        "強烈", "urgent and high-energy within hard bounds",
        ("breathy", "trembling", "restrained", "urgent", "firm"),
        "帶著強烈而急切的能量說，保持清楚並避免喊叫", "dramatic", 1.08, 0.08, 0.10,
    ),
    "adult.afterglow": _definition(
        "餘韻", "relaxed, affectionate, even breathing",
        ("whispered", "breathy", "restrained", "hesitant", "soft"),
        "語氣放鬆而深情，平穩柔和地說", "natural", 0.93, -0.05, 0.28,
    ),
}


_MODIFIER_DEFINITIONS = {
    "whispered": ("壓低音量並靠近地輕聲說", "restrained", 0.96, -0.03, 0.22),
    "breathy": ("保留輕柔氣音但完整清楚地咬字", "restrained", 0.98, 0.00, 0.18),
    "trembling": ("聲線帶著輕微顫抖但保持可懂度", "dramatic", 0.97, 0.04, 0.22),
    "restrained": ("克制情緒，不要過度表演", "restrained", 0.98, -0.03, 0.20),
    "urgent": ("語氣急切，縮短停頓但保持清楚", "dramatic", 1.06, 0.05, 0.10),
    "hesitant": ("帶些猶豫，用短而自然的停頓", "natural", 0.96, -0.01, 0.25),
    "soft": ("降低力道，柔和自然地說", "natural", 0.96, -0.03, 0.21),
    "firm": ("語氣堅定，清楚精準地咬字", "dramatic", 1.00, 0.02, 0.14),
}


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _tone_catalog_entry(tone_id: str, definition: dict[str, Any]) -> dict[str, Any]:
    neutral = tone_id == "general.neutral"
    adapters = {
        "qwen_custom_voice": {},
        "qwen_full_icl": {},
    }
    if not neutral:
        common = {
            "speed_multiplier": definition["speed_multiplier"],
            "temperature_delta": definition["temperature_delta"],
            "pause_seconds": definition["pause_seconds"],
            "pitch_shift_semitones": 0,
        }
        adapters = {
            "qwen_custom_voice": {
                **common,
                "template_id": f"{tone_id}.qwen_custom_voice.v1",
                "instruct": definition["instruct"],
            },
            "qwen_full_icl": {
                **common,
                "expressiveness": definition["expressiveness"],
            },
        }
    return {
        "tone_id": tone_id,
        "label": definition["label"],
        "delivery": definition["delivery"],
        "allowed_modifiers": list(definition["allowed_modifiers"]),
        "adapters": adapters,
    }


def _modifier_catalog_entry(
    modifier_id: str,
    definition: tuple[str, str, float, float, float],
) -> dict[str, Any]:
    instruct, expressiveness, speed, temperature, pause = definition
    common = {
        "speed_multiplier": speed,
        "temperature_delta": temperature,
        "pause_seconds": pause,
        "pitch_shift_semitones": 0,
    }
    return {
        "modifier_id": modifier_id,
        "adapters": {
            "qwen_custom_voice": {
                **common,
                "instruction_fragment": instruct,
            },
            "qwen_full_icl": {
                **common,
                "expressiveness": expressiveness,
            },
        },
    }


def build_tone_catalog() -> dict[str, Any]:
    catalog = {
        "schema": TONE_CATALOG_SCHEMA,
        "version": 1,
        "safe_bounds": {key: list(value) if isinstance(value, list) else value for key, value in SAFE_BOUNDS.items()},
        "modifiers": {
            modifier_id: _modifier_catalog_entry(modifier_id, definition)
            for modifier_id, definition in _MODIFIER_DEFINITIONS.items()
        },
        "tones": {
            tone_id: _tone_catalog_entry(tone_id, definition)
            for tone_id, definition in _TONE_DEFINITIONS.items()
        },
    }
    return {**catalog, "sha256": _canonical_sha256(catalog)}


def _first_action_tone(action: str, *, allow_adult: bool) -> str:
    for tone_id, keywords in ACTION_TO_TONE:
        if tone_id.startswith("adult.") and not allow_adult:
            continue
        if any(keyword in action for keyword in keywords):
            return tone_id
    return ""


def _action_modifiers(action: str) -> list[str]:
    return [
        modifier_id
        for modifier_id, keywords in ACTION_TO_MODIFIER
        if any(keyword in action for keyword in keywords)
    ]


def _normalize_explicit_modifiers(modifiers: list[str]) -> list[str]:
    if not isinstance(modifiers, list):
        raise ToneMapError(
            "tone_modifier_invalid",
            "tone modifiers must be a list",
        )
    normalized: list[str] = []
    for value in modifiers:
        modifier_id = str(value or "").strip().casefold()
        if modifier_id not in APPROVED_MODIFIERS:
            raise ToneMapError(
                "tone_modifier_invalid",
                f"unsupported tone modifier: {value!r}",
            )
        if modifier_id not in normalized:
            normalized.append(modifier_id)
    return normalized


def resolve_utterance_tone(
    *,
    emotion: str,
    action: str,
    pace: str,
    tone_id: str = "",
    intensity: int | None = None,
    modifiers: list[str] | None = None,
    content_rating: str = "general",
) -> dict[str, Any]:
    if intensity is None:
        resolved_intensity = 2
    elif isinstance(intensity, bool) or not isinstance(intensity, int) or not 1 <= intensity <= 3:
        raise ToneMapError(
            "tone_intensity_invalid",
            "tone intensity must be an integer from 1 to 3",
        )
    else:
        resolved_intensity = intensity

    requested_tone_id = str(tone_id or "").strip().casefold()
    source_emotion = str(emotion or "").strip()
    source_action = str(action or "").strip()
    source_pace = str(pace or "").strip()
    normalized_content_rating = str(content_rating or "").strip().casefold()
    warning = ""
    if requested_tone_id:
        resolved_tone_id = requested_tone_id
        resolution = "explicit"
    else:
        action_tone_id = _first_action_tone(
            source_action,
            allow_adult=normalized_content_rating == "adult_explicit",
        )
        normalized_emotion = source_emotion.casefold()
        if action_tone_id:
            resolved_tone_id = action_tone_id
            resolution = "mapped"
        elif not normalized_emotion or normalized_emotion == "neutral":
            resolved_tone_id = "general.neutral"
            resolution = "mapped"
        elif normalized_emotion in EMOTION_TO_TONE:
            resolved_tone_id = EMOTION_TO_TONE[normalized_emotion]
            resolution = "mapped"
        else:
            resolved_tone_id = "general.neutral"
            resolution = "fallback"
            warning = (
                f"unknown automatic emotion {source_emotion!r}; "
                "fell back to general.neutral"
            )

    tone_definition = _TONE_DEFINITIONS.get(resolved_tone_id)
    if tone_definition is None:
        raise ToneMapError(
            "tone_id_invalid",
            f"unsupported tone_id: {resolved_tone_id!r}",
        )
    if (
        resolved_tone_id.startswith("adult.")
        and normalized_content_rating != "adult_explicit"
    ):
        raise ToneMapError(
            "tone_content_rating_invalid",
            f"tone {resolved_tone_id!r} requires adult_explicit content rating",
        )

    resolved_modifiers = (
        _action_modifiers(source_action)
        if modifiers is None
        else _normalize_explicit_modifiers(modifiers)
    )
    allowed_modifiers = set(tone_definition["allowed_modifiers"])
    incompatible = [
        modifier_id
        for modifier_id in resolved_modifiers
        if modifier_id not in allowed_modifiers
    ]
    if incompatible:
        raise ToneMapError(
            "tone_modifier_incompatible",
            f"tone {resolved_tone_id!r} does not allow modifiers: {', '.join(incompatible)}",
        )

    resolved = {
        "tone_id": resolved_tone_id,
        "intensity": resolved_intensity,
        "modifiers": resolved_modifiers,
        "resolution": resolution,
        "source": {
            "emotion": source_emotion,
            "action": source_action,
            "pace": source_pace,
        },
    }
    if warning:
        resolved["warning"] = warning
    return resolved
