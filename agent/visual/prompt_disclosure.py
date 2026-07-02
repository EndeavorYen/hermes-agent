from __future__ import annotations

import re


def is_visual_prompt_builder_request(prompt: str) -> bool:
    """True when the user wants a prompt artifact, not prior prompt disclosure."""
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    has_prompt_term = "prompt" in text or "提示詞" in text or "提示词" in text
    if not has_prompt_term:
        return False

    prompt_as_artifact = any(
        marker in compact
        for marker in (
            "prompt就好",
            "prompt即可",
            "只要prompt",
            "只給prompt",
            "只给prompt",
            "給我prompt就好",
            "给我prompt就好",
            "提示詞就好",
            "提示词就好",
            "提示詞即可",
            "提示词即可",
            "只要提示詞",
            "只要提示词",
            "只給提示詞",
            "只给提示词",
            "給我提示詞就好",
            "给我提示词就好",
        )
    ) or any(
        marker in text
        for marker in (
            "prompt only",
            "only prompt",
            "only the prompt",
            "give me a prompt",
            "write a prompt",
            "make a prompt",
        )
    )
    if prompt_as_artifact:
        return True

    no_generation = any(
        marker in compact
        for marker in (
            "不須產圖",
            "不需產圖",
            "不用產圖",
            "不必產圖",
            "不要產圖",
            "不須生圖",
            "不需生圖",
            "不用生圖",
            "不須生成圖片",
            "不需生成圖片",
            "不用生成圖片",
            "不要生成圖片",
            "不须产图",
            "不需产图",
            "不用产图",
            "不要产图",
            "不须生成图片",
            "不用生成图片",
        )
    ) or any(
        marker in text
        for marker in (
            "do not generate",
            "don't generate",
            "no image generation",
            "no need to generate",
            "without generating",
        )
    )
    asks_for_prompt = any(
        marker in compact
        for marker in (
            "給我prompt",
            "给我prompt",
            "產生prompt",
            "生成prompt",
            "寫prompt",
            "写prompt",
            "做prompt",
            "給我提示詞",
            "给我提示词",
            "產生提示詞",
            "生成提示詞",
            "寫提示詞",
            "写提示词",
            "做提示詞",
            "做提示词",
        )
    )
    return no_generation and asks_for_prompt


def is_visual_prompt_disclosure_request(prompt: str) -> bool:
    """True when the user asks for a prior provider prompt instead of media."""
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    has_prompt_term = "prompt" in text or "提示詞" in text or "提示词" in text
    if not has_prompt_term:
        return False
    if is_visual_prompt_builder_request(prompt):
        return False

    direct_patterns = (
        "what prompt",
        "which prompt",
        "show me the prompt",
        "tell me the prompt",
        "give me the prompt",
        "share the prompt",
        "prompt you used",
        "used prompt",
        "actual prompt",
        "final prompt",
    )
    if any(pattern in text for pattern in direct_patterns):
        return True

    compact_patterns = (
        "給我剛剛產圖用的prompt",
        "给我刚刚产图用的prompt",
        "剛剛產圖用的prompt",
        "刚刚产图用的prompt",
        "產圖用的prompt給我",
        "产图用的prompt给我",
        "你用的prompt",
        "你使用的prompt",
        "使用的prompt",
        "用的prompt",
        "用了什麼prompt",
        "用了什么prompt",
        "prompt是什麼",
        "prompt是什么",
        "給我prompt",
        "给我prompt",
        "貼出prompt",
        "贴出prompt",
        "列出prompt",
        "顯示prompt",
        "显示prompt",
        "你用的提示詞",
        "你用的提示词",
        "使用的提示詞",
        "使用的提示词",
        "用的提示詞",
        "用的提示词",
        "用了什麼提示詞",
        "用了什么提示词",
        "提示詞是什麼",
        "提示词是什么",
        "給我提示詞",
        "给我提示词",
    )
    return any(pattern in compact for pattern in compact_patterns)
