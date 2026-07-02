from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

from agent.visual.feedback import is_visual_feedback_only_text

logger = logging.getLogger(__name__)

_PLANNER_IMAGE_MAX_BYTES = 18 * 1024 * 1024


def apply_visual_agent_llm_planner(args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    provider = str(args.get("visual_agent_llm_provider") or "").strip()
    model = str(args.get("visual_agent_llm_model") or "").strip()
    if not provider or not model:
        return args, None

    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return args, None

    plan: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "status": "fallback",
        "prompt_changed": False,
    }
    attachments = _string_list(args.get("attachments"))
    user_content = _planner_user_content(prompt, args, attachments)
    plan["image_input_count"] = (
        sum(1 for item in user_content if item.get("type") == "image_url")
        if isinstance(user_content, list)
        else 0
    )
    try:
        from agent.auxiliary_client import call_llm, extract_content_or_reasoning

        response = call_llm(
            provider=provider,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Hermes visual agent mode's creative prompt planner. "
                        "Rewrite the user's image/video request into a production-ready "
                        "provider prompt for an image/video generator, not a loose summary. "
                        "Preserve the user's intent, subject, constraints, provider choice, "
                        "and language. If reference images are attached, inspect them in "
                        "the user's visible upload order. Convert explicitly role-bound "
                        "references into concrete visual observations, but never invent "
                        "fixed per-image roles when the user did not assign them. If the "
                        "attached images are unassigned, treat them as a collective reference "
                        "set for the requested subject/style and do not emit a reference "
                        "mapping that labels individual refs as identity, pose, wardrobe, "
                        "style, background, or similar roles. For a character_identity ref, "
                        "describe identity, face, hair, silhouette, outfit, and palette. "
                        "For a pose_composition ref, describe only body orientation, limb "
                        "placement, camera angle, framing, composition, and scene layout; "
                        "explicitly say not to copy that ref's identity, face, hair, outfit, "
                        "or color palette. Use compact labeled clauses for objective, "
                        "reference mapping, role constraints, composition/camera, quality "
                        "target, and negative constraints. Be vivid and specific. Return only "
                        "compact JSON with key visual_prompt."
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            temperature=0.85,
            max_tokens=900,
            timeout=60,
        )
        payload = _parse_json_object(extract_content_or_reasoning(response))
        visual_prompt = str(payload.get("visual_prompt") or payload.get("prompt") or "").strip()
        if visual_prompt:
            if _same_prompt(visual_prompt, prompt):
                plan["reason"] = "unchanged_visual_prompt"
                raise _WeakVisualPromptPlan("unchanged_visual_prompt")
            if is_visual_feedback_only_text(visual_prompt):
                plan["reason"] = "feedback_like_visual_prompt"
                raise _WeakVisualPromptPlan("feedback_like_visual_prompt")
            if _unsupported_reference_role_mapping(visual_prompt, args, attachments):
                plan["reason"] = "unsupported_reference_role_mapping"
                raise _WeakVisualPromptPlan("unsupported_reference_role_mapping")
            visual_prompt = _apply_unassigned_reference_policy_guard(visual_prompt, args, attachments)
            next_args = dict(args)
            next_args["prompt"] = visual_prompt
            next_args["visual_agent_original_prompt"] = prompt
            plan.update(
                {
                    "status": "planned",
                    "prompt_changed": visual_prompt != prompt,
                }
            )
            return next_args, plan
        plan["reason"] = "empty_visual_prompt"
    except _WeakVisualPromptPlan:
        pass
    except Exception as exc:
        logger.debug("visual agent Grok planner failed; using deterministic prompt: %s", exc)
        plan["reason"] = exc.__class__.__name__
    fallback_prompt = _deterministic_provider_ready_prompt(prompt, args, attachments)
    if fallback_prompt != prompt:
        next_args = dict(args)
        next_args["prompt"] = fallback_prompt
        next_args["visual_agent_original_prompt"] = prompt
        plan.update(
            {
                "status": "fallback_deterministic_prompt",
                "prompt_changed": True,
            }
        )
        return next_args, plan
    return args, plan


class _WeakVisualPromptPlan(Exception):
    pass


def _same_prompt(candidate: str, original: str) -> bool:
    return re.sub(r"\s+", "", str(candidate or "")).lower() == re.sub(
        r"\s+",
        "",
        str(original or ""),
    ).lower()


def _planner_user_content(prompt: str, args: dict[str, Any], attachments: list[str]) -> str | list[dict[str, Any]]:
    text = _planner_user_text(prompt, args, attachments)
    if _uses_unassigned_reference_set(args, attachments):
        return text
    image_parts = [_image_content_part(attachment) for attachment in attachments]
    image_parts = [part for part in image_parts if part]
    if not image_parts:
        return text
    return [{"type": "text", "text": text}, *image_parts]


def _planner_user_text(prompt: str, args: dict[str, Any], attachments: list[str]) -> str:
    lines = [prompt]
    role_lines = _reference_role_lines(args.get("reference_binding"), attachments)
    if role_lines:
        lines.extend(
            [
                "",
                "Reference roles from the user's visible upload order:",
                *role_lines,
                (
                    "Use these roles when rewriting the prompt. If one ref is pose_composition, "
                    "turn its visible pose/camera/framing into text and warn the generator not "
                    "to copy that ref's identity or styling."
                ),
            ]
        )
    elif attachments:
        lines.extend(
            [
                "",
                "Attached references are an unassigned collective reference set in the user's visible "
                "upload order. Inspect them before rewriting, but do not assign fixed per-image roles "
                "such as ref 1 = identity, ref 2 = pose, ref 3 = wardrobe/style unless the user "
                "explicitly mapped those roles. If the request says to fix/lock this character, use "
                "the attached set as collective identity/style evidence and invent new pose candidates "
                "from the user's request instead of copying pose/composition from one unassigned ref.",
            ]
        )
    return "\n".join(lines).strip()


def _reference_role_lines(binding: Any, attachments: list[str]) -> list[str]:
    if not isinstance(binding, dict):
        return []
    lines: list[str] = []
    for item in binding.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        index = _coerce_int(item.get("index"))
        if index is None or index < 1:
            continue
        role_hint = str(item.get("role_hint") or "visual_reference").strip() or "visual_reference"
        if index <= len(attachments):
            lines.append(f"- ref {index}: {role_hint}")
    return lines


def _deterministic_provider_ready_prompt(prompt: str, args: dict[str, Any], attachments: list[str]) -> str:
    role_items = _reference_role_items(args.get("reference_binding"), attachments)
    base_prompt = _strip_reference_binding_block(prompt)
    lines = [
        "Provider-ready visual prompt:",
        f"Objective: {base_prompt}",
    ]

    if role_items:
        lines.extend(["", "Reference mapping from the user's visible upload order:"])
        for index, role_hint in role_items:
            lines.append(f"- ref {index} = {role_hint}")
    elif attachments:
        lines.extend(
            [
                "",
                "Reference policy for unassigned uploaded images:",
                "- Treat all attached images as an unassigned collective reference set for the requested "
                "subject, character identity, style, and visual consistency.",
                "- Do not assign fixed per-image roles such as ref 1 = identity, ref 2 = pose, or "
                "ref 3 = wardrobe/style unless the user explicitly mapped those roles.",
                "- If the user asks to fix/lock this character, preserve the character identity supported "
                "by the reference set as a whole; generate new pose/composition candidates from the "
                "request rather than copying pose/composition from any one unassigned reference.",
            ]
        )

    role_constraints = _role_constraint_lines(role_items)
    if role_constraints:
        lines.extend(["", "Role constraints:", *role_constraints])

    lines.extend(
        [
            "",
            "Composition and camera: choose a confident, intentional frame that makes the subject readable; "
            "use coherent perspective, balanced crop, and a clear focal point.",
            "",
            "Quality target: polished high-quality final image, beautiful subject rendering, coherent anatomy, "
            "clean face and hands, natural limb geometry, refined lighting, attractive material texture, "
            "intentional composition, no candidate grid or collage.",
            "",
            "Negative constraints: do not ignore explicit material/coverage constraints; do not mix reference "
            "roles; no malformed anatomy, duplicated limbs, warped face, broken feet or hands, bad crop, "
            "low-detail texture, plastic material artifacts, text overlays, watermark, or multiple unrelated outputs.",
        ]
    )
    return "\n".join(lines).strip()


def _reference_role_items(binding: Any, attachments: list[str]) -> list[tuple[int, str]]:
    if not isinstance(binding, dict):
        return []
    items: list[tuple[int, str]] = []
    for item in binding.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        index = _coerce_int(item.get("index"))
        if index is None or index < 1 or index > len(attachments):
            continue
        role_hint = str(item.get("role_hint") or "visual_reference").strip() or "visual_reference"
        items.append((index, role_hint))
    return items


def _has_role_specific_reference_binding(binding: Any, attachments: list[str]) -> bool:
    return any(role != "visual_reference" for _index, role in _reference_role_items(binding, attachments))


def _uses_unassigned_reference_set(args: dict[str, Any], attachments: list[str]) -> bool:
    return bool(attachments) and not _has_role_specific_reference_binding(
        args.get("reference_binding"),
        attachments,
    )


def _unsupported_reference_role_mapping(
    visual_prompt: str,
    args: dict[str, Any],
    attachments: list[str],
) -> bool:
    if not _uses_unassigned_reference_set(args, attachments):
        return False
    text = str(visual_prompt or "").lower()
    compact = re.sub(r"\s+", " ", text)
    assignment_pattern = re.compile(
        r"(?:\bref(?:erence)?\s*\d+|img_[a-z0-9._-]+|image[_\s-]?\d+|"
        r"第[一二三四五六七八九十\d]+張)\s*(?:=|:|is\s+|as\s+|為|當作|作為)"
    )
    mapping_marker = "reference_mapping" in compact or "reference mapping" in compact
    has_assignment = bool(assignment_pattern.search(compact))
    if not (mapping_marker or has_assignment):
        return False
    role_terms = (
        "primary",
        "secondary",
        "identity",
        "character",
        "pose",
        "composition",
        "wardrobe",
        "outfit",
        "clothing",
        "style",
        "background",
        "facial",
        "face",
        "hair",
        "hand pose",
        "full-body",
        "角色",
        "人物",
        "身份",
        "姿勢",
        "動作",
        "構圖",
        "鏡頭",
        "服裝",
        "衣服",
        "風格",
        "背景",
    )
    return any(term in compact for term in role_terms)


def _apply_unassigned_reference_policy_guard(
    visual_prompt: str,
    args: dict[str, Any],
    attachments: list[str],
) -> str:
    if not _uses_unassigned_reference_set(args, attachments):
        return visual_prompt
    lowered_prompt = visual_prompt.lower()
    if "collective reference set" in lowered_prompt and "fixed per-image roles" in lowered_prompt:
        return visual_prompt
    guard = (
        "Reference policy: treat attached images as an unassigned collective reference set. "
        "Do not assign fixed per-image roles or copy pose/composition/wardrobe/style from a "
        "single reference unless the user explicitly mapped that role; preserve requested "
        "character identity/style from the set as a whole.\n\n"
    )
    return f"{guard}{visual_prompt}".strip()


def _strip_reference_binding_block(prompt: str) -> str:
    text = str(prompt or "").strip()
    if "\n\nReference binding:" in text:
        text = text.split("\n\nReference binding:", 1)[0].strip()
    return text


def _role_constraint_lines(role_items: list[tuple[int, str]]) -> list[str]:
    lines: list[str] = []
    seen_roles = {role for _, role in role_items}
    for index, role in role_items:
        if role == "edit_anchor":
            lines.append(
                f"- ref {index}: treat as the previous selected image/edit target; preserve stable identity, "
                "composition, and style unless the user explicitly asks to change them."
            )
        elif role == "character_identity":
            lines.append(
                f"- ref {index}: preserve character identity, face, hair, silhouette, signature outfit, "
                "accessories, and palette."
            )
        elif role == "pose_composition":
            lines.append(
                f"- ref {index}: use only pose, body orientation, limb placement, camera angle, framing, "
                "composition, and scene layout."
            )
        elif role == "wardrobe":
            lines.append(f"- ref {index}: use clothing, material, cut, pattern, and color details only.")
        elif role == "style":
            lines.append(f"- ref {index}: use rendering style, lighting mood, finish, and color grading only.")
        elif role == "background":
            lines.append(f"- ref {index}: use setting, background layout, environment, and props only.")
        else:
            lines.append(f"- ref {index}: use only the role implied by the user's request; do not over-copy.")
    if "pose_composition" in seen_roles:
        lines.append(
            "- Do not copy identity, face, hair, wardrobe, color palette, or styling from pose refs."
        )
    return lines


def _image_content_part(reference: str) -> dict[str, Any] | None:
    url = _image_reference_url(reference)
    if not url:
        return None
    return {"type": "image_url", "image_url": {"url": url, "detail": "high"}}


def _image_reference_url(reference: str) -> str | None:
    value = str(reference or "").strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered.startswith(("http://", "https://", "data:image/")):
        return value
    try:
        path = Path(os.path.expanduser(value))
        if not path.is_file() or path.stat().st_size > _PLANNER_IMAGE_MAX_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    if not mime.startswith("image/"):
        return None
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and str(item).strip()]


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_json_object(text: str) -> dict[str, Any]:
    text = str(text or "").strip()
    if not text:
        return {}
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        payload = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
        except Exception:
            return {}
    return payload if isinstance(payload, dict) else {}
