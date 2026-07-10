from __future__ import annotations

import re
from typing import Any


_VISUAL_METADATA_MARKERS = (
    "[Visual Arsenal source images]",
    "The current Slack message includes user-uploaded source/reference images cached on this machine.",
)

_DROP_SECTION_MARKERS = {
    "provider-ready visual prompt",
    "session visual context",
    "reference policy for unassigned uploaded images",
    "reference binding",
}
_REFERENCE_POLICY_MARKERS = {
    "reference policy",
    "provider reference image ordering for generation",
}
_SECTION_LABELS = {
    "objective": "",
    "composition and camera": "Composition",
    "quality target": "Quality",
    "negative constraints": "Negative",
    "first-pass visual quality guidance": "Quality",
    "first-pass video quality guidance": "Video quality",
    "dimension-specific quality guidance": "Quality refinements",
    "visual arsenal candidate strategy": "Creative direction",
    "reference mapping from the user's visible upload order": "Reference use",
    "reference roles for this request": "Reference use",
    "role constraints": "Role constraints",
}
_THREAD_CONTEXT_RE = re.compile(
    r"\[Thread context[^\]]*\].*?(?:\[End of thread context\]|$)",
    flags=re.IGNORECASE | re.DOTALL,
)
_REPLYING_TO_RE = re.compile(
    r'^\s*\[Replying to:\s*"(?:(?:\\.)|[^"])*"\]\s*',
    flags=re.IGNORECASE | re.DOTALL,
)
_XAI_PROMPT_MAX_CHARS = 1200
_XAI_AVOID_MAX_CHARS = 320
_XAI_REFERENCE_SENTENCE = (
    "Use attached references as collective identity/style evidence; create a new cohesive "
    "composition instead of cleaning up, copying, extending, stitching, or averaging one reference."
)
_XAI_NEGATIVE_LABELS = {"avoid", "negative", "negative constraints", "negative prompt"}
_XAI_POSITIVE_LABELS = {
    "composition",
    "creative direction",
    "quality",
    "quality refinements",
    "role constraints",
}


def strip_visual_prompt_metadata(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    cut_at = len(text)
    for marker in _VISUAL_METADATA_MARKERS:
        index = text.find(marker)
        if index >= 0:
            cut_at = min(cut_at, index)
    text = text[:cut_at].strip()
    text = _THREAD_CONTEXT_RE.sub("", text)
    text = _REPLYING_TO_RE.sub("", text).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def build_provider_facing_visual_prompt(
    value: Any,
    *,
    provider: str | None = None,
    request_category: str | None = None,
) -> str:
    """Return the prompt text that should be sent to image/video providers.

    Agent-mode prompts can include Slack reply context, audit headers, reference
    policies, and strategy metadata that are useful inside Hermes but poor input
    for image providers. This keeps the creative request and compact useful
    constraints while dropping orchestration prose.
    """

    text = strip_visual_prompt_metadata(value)
    if not text:
        return ""

    sections = _provider_prompt_sections(text)
    if not sections:
        return _normalise_provider_prompt_text(text)

    output: list[str] = []
    saw_collective_reference_policy = False
    saw_reference_mapping = False
    for label, body in sections:
        normalized_label = _normalise_section_label(label)
        cleaned_body = _clean_provider_section_body(body)
        if not cleaned_body:
            continue
        if normalized_label in _DROP_SECTION_MARKERS:
            continue
        if normalized_label in _REFERENCE_POLICY_MARKERS:
            if _section_is_collective_reference_policy(cleaned_body):
                saw_collective_reference_policy = True
            elif cleaned_body:
                output.append(f"Reference use: {cleaned_body}")
            continue
        display_label = _SECTION_LABELS.get(normalized_label)
        if display_label is None:
            output.append(cleaned_body)
            continue
        if normalized_label == "reference mapping from the user's visible upload order":
            saw_reference_mapping = True
        if display_label:
            output.append(f"{display_label}: {cleaned_body}")
        else:
            output.append(cleaned_body)

    if saw_collective_reference_policy and not saw_reference_mapping:
        output.append(
            "Reference use: use attached images as collective visual evidence for identity, style, "
            "palette, and recurring design cues only; create a new coherent image, not a cleanup, "
            "canvas extension, watermark removal, stitched blend, collage, or average of one reference."
        )
    prompt = "\n\n".join(_dedupe_prompt_blocks(output)).strip()
    prompt = _normalise_provider_prompt_text(prompt)
    if _should_compact_for_xai(provider, request_category, prompt):
        return _compact_xai_creative_brief_prompt(prompt)
    return prompt


def _provider_prompt_sections(text: str) -> list[tuple[str | None, list[str]]]:
    sections: list[tuple[str | None, list[str]]] = []
    current_label: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        if current_label is None and not any(line.strip() for line in current_lines):
            current_lines = []
            return
        sections.append((current_label, current_lines))
        current_lines = []

    for raw_line in _normalise_line_endings(text).split("\n"):
        line = raw_line.strip()
        header = _provider_prompt_header(line)
        if header is not None:
            flush()
            current_label, rest = header
            current_lines = [rest] if rest else []
        else:
            current_lines.append(raw_line)
    flush()
    return sections


def _provider_prompt_header(line: str) -> tuple[str, str] | None:
    if not line:
        return None
    stripped = line.strip()
    lower = stripped.lower()
    if lower == "provider-ready visual prompt:" or lower == "provider-ready visual prompt":
        return "provider-ready visual prompt", ""
    for label in sorted(
        {*_SECTION_LABELS.keys(), *_DROP_SECTION_MARKERS, *_REFERENCE_POLICY_MARKERS},
        key=len,
        reverse=True,
    ):
        prefix = f"{label}:"
        if lower.startswith(prefix):
            return label, stripped[len(prefix) :].strip()
    return None


def _clean_provider_section_body(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    if not text:
        return ""
    text = _THREAD_CONTEXT_RE.sub("", text)
    text = _REPLYING_TO_RE.sub("", text).strip()
    text = re.sub(
        r"\bDimension-specific quality guidance:\s*",
        "Additional quality refinements: ",
        text,
        flags=re.IGNORECASE,
    )
    cleaned_lines = []
    for line in text.split("\n"):
        item = line.strip()
        if not item:
            continue
        if item.lower().startswith("[thread parent]"):
            continue
        if item.lower().startswith("when provider image ordering and user ref labels differ"):
            continue
        item = re.sub(r"^\s*[-*]\s*", "", item).strip()
        item = re.sub(r"\bprovider image(s?)\b", r"reference image\1", item, flags=re.IGNORECASE)
        item = re.sub(r"\bprovider ref\b", "reference image", item, flags=re.IGNORECASE)
        item = re.sub(
            r"\b(?:subject_beauty|face_naturalness|glamour_impact|fashion_material_quality|"
            r"pose_composition|motion_quality|stocking_quality):\s*",
            "",
            item,
            flags=re.IGNORECASE,
        )
        if item:
            cleaned_lines.append(item)
    return _normalise_provider_prompt_text("; ".join(cleaned_lines))


def _section_is_collective_reference_policy(text: str) -> bool:
    lowered = str(text or "").lower()
    return (
        "unassigned collective" in lowered
        or "collective identity/style" in lowered
        or "collective visual evidence" in lowered
        or "collective reference" in lowered
    )


def _normalise_section_label(label: str | None) -> str:
    return str(label or "").strip().lower()


def _normalise_line_endings(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")


def _normalise_provider_prompt_text(text: str) -> str:
    value = _normalise_line_endings(text).strip()
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()


def _dedupe_prompt_blocks(blocks: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for block in blocks:
        value = _normalise_provider_prompt_text(block)
        if not value:
            continue
        key = re.sub(r"\s+", " ", value).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _should_compact_for_xai(
    provider: str | None,
    request_category: str | None,
    prompt: str,
) -> bool:
    provider_text = str(provider or "").strip().lower()
    if (
        provider_text in {"xai", "grok", "grok-web-imagine", "xai-grok"}
        or "grok" in provider_text
        or re.search(r"\bxai\b", provider_text)
    ):
        return True
    category_text = str(request_category or "").strip().lower()
    prompt_text = str(prompt or "").strip().lower()
    return "grok" in prompt_text and ("anime" in category_text or "anime" in prompt_text)


def _compact_xai_creative_brief_prompt(prompt: str) -> str:
    paragraphs = [
        _normalise_provider_prompt_text(block)
        for block in re.split(r"\n{2,}", _normalise_provider_prompt_text(prompt))
        if _normalise_provider_prompt_text(block)
    ]
    positive_blocks: list[str] = []
    reference_blocks: list[str] = []
    avoid_items: list[str] = []
    reference_added = False

    for block in paragraphs:
        label, body = _xai_prompt_block_label(block)
        if label in _XAI_NEGATIVE_LABELS:
            avoid_items.extend(_xai_prompt_items(body))
            continue
        if label == "reference use":
            reference_sentence = _xai_reference_sentence(body)
            if reference_sentence:
                reference_blocks.append(reference_sentence)
                reference_added = reference_added or reference_sentence == _XAI_REFERENCE_SENTENCE
            continue
        if label in _XAI_POSITIVE_LABELS:
            positive_blocks.append(_xai_positive_label_sentence(label, body))
            continue
        positive_blocks.append(block)

    positive_blocks = _dedupe_prompt_blocks(positive_blocks)
    if not reference_added and _prompt_mentions_collective_reference_policy(prompt):
        reference_blocks.append(_XAI_REFERENCE_SENTENCE)
    reference_blocks = _dedupe_prompt_blocks(reference_blocks)
    if positive_blocks and reference_blocks:
        positive_blocks = [positive_blocks[0], *reference_blocks, *positive_blocks[1:]]
    elif reference_blocks:
        positive_blocks = reference_blocks

    positive_text = _normalise_provider_prompt_text(" ".join(positive_blocks))
    avoid_clause = _xai_avoid_clause(avoid_items)
    if avoid_clause:
        positive_budget = max(360, _XAI_PROMPT_MAX_CHARS - len(avoid_clause) - 2)
        positive_text = _trim_xai_text(positive_text, positive_budget)
        prompt_text = f"{positive_text}\n\n{avoid_clause}" if positive_text else avoid_clause
    else:
        prompt_text = _trim_xai_text(positive_text, _XAI_PROMPT_MAX_CHARS)
    return _normalise_provider_prompt_text(prompt_text)


def _xai_prompt_block_label(block: str) -> tuple[str | None, str]:
    value = _normalise_provider_prompt_text(block)
    lower = value.lower()
    labels = {"reference use", *_XAI_NEGATIVE_LABELS, *_XAI_POSITIVE_LABELS}
    for label in sorted(labels, key=len, reverse=True):
        prefix = f"{label}:"
        if lower.startswith(prefix):
            return label, value[len(prefix) :].strip()
    return None, value


def _xai_reference_sentence(body: str) -> str:
    text = _normalise_provider_prompt_text(body)
    if not text:
        return ""
    lowered = text.lower()
    if _prompt_mentions_explicit_reference_roles(text):
        return f"Follow explicit reference roles: {text}"
    if _prompt_mentions_collective_reference_policy(text):
        return _XAI_REFERENCE_SENTENCE
    return f"Use attached references as visual guidance: {text}"


def _xai_positive_label_sentence(label: str, body: str) -> str:
    text = _normalise_provider_prompt_text(body)
    if not text:
        return ""
    if label == "role constraints":
        return f"Follow reference role constraints: {text}"
    return _capitalise_ascii_sentence(text)


def _xai_prompt_items(text: str) -> list[str]:
    items: list[str] = []
    for item in re.split(r"[;,]\s*|\n+", _normalise_provider_prompt_text(text)):
        value = re.sub(r"^(?:no|avoid)\s+", "", item.strip(" ."), flags=re.IGNORECASE)
        if value:
            items.append(value)
    return _dedupe_prompt_blocks(items)


def _xai_avoid_clause(items: list[str]) -> str:
    cleaned = _dedupe_prompt_blocks([item.strip(" .") for item in items if item.strip(" .")])
    if not cleaned:
        return ""
    text = ", ".join(cleaned)
    text = _trim_xai_text(text, _XAI_AVOID_MAX_CHARS).strip(" .,;")
    return f"Avoid: {text}."


def _trim_xai_text(text: str, max_chars: int) -> str:
    value = _normalise_provider_prompt_text(text)
    if len(value) <= max_chars:
        return value
    cutoff = max_chars
    for marker in (". ", "; ", ", "):
        index = value.rfind(marker, 0, max_chars)
        if index >= max_chars * 0.55:
            cutoff = index + len(marker.rstrip())
            break
    return value[:cutoff].rstrip(" ,;.") + "."


def _prompt_mentions_collective_reference_policy(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "collective visual evidence",
            "collective identity/style",
            "collective reference",
            "unassigned collective",
            "not a cleanup",
            "stitched blend",
            "average of one reference",
        )
    )


def _prompt_mentions_explicit_reference_roles(text: str) -> bool:
    lowered = str(text or "").lower()
    return (
        bool(re.search(r"\bref\s*\d+\b", lowered))
        or "character_identity" in lowered
        or "pose_composition" in lowered
        or "wardrobe_reference" in lowered
    )


def _capitalise_ascii_sentence(text: str) -> str:
    value = _normalise_provider_prompt_text(text)
    if not value:
        return ""
    first = value[0]
    if "a" <= first <= "z":
        return first.upper() + value[1:]
    return value
