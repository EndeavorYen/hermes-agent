from __future__ import annotations

import json
from typing import Any

from agent.visual.agent_mode.grok_planner import apply_visual_agent_llm_planner
from agent.visual.agent_mode.handoff import is_visual_prompt_disclosure_request
from agent.visual.agent_mode.handoff import normalise_visual_agent_attachment
from agent.visual.agent_mode.planner import plan_visual_agent_request
from tools.registry import registry
from tools.registry import tool_error
from tools.visual_package_tool import _handle_visual_package_generate
from tools.visual_package_tool import check_visual_package_requirements


_DIRECT_VISUAL_PACKAGE_OVERRIDE_KEYS = frozenset(
    {
        "aspect_ratio",
        "autonomy_level",
        "candidate_budget",
        "candidate_budget_source",
        "duration",
        "grok_web_operation",
        "image_model",
        "image_operation",
        "image_provider",
        "image_provider_source",
        "include_image",
        "include_video",
        "operation",
        "polish_provider",
        "polish_provider_source",
        "reference_binding",
        "reference_conditioning_policy",
        "reference_strategy",
        "storyboard",
        "video_budget",
        "video_model",
        "video_provider",
        "video_provider_source",
    }
)


VISUAL_AGENT_SCHEMA: dict[str, Any] = {
    "name": "visual_agent_generate",
    "description": (
        "User-friendly visual agent mode for natural image/video requests. "
        "Use this as the primary entry point when the user asks for images, "
        "videos, image plus video packages, reference-based variations, product "
        "photos, portrait/fashion/glamour visuals, draw/anime/character art prompts, "
        "animate/make-it-move requests, storyboard/multi-shot video requests, or short motion clips without "
        "advanced parameters. The tool plans the request, then dispatches to "
        "visual_package_generate so Hermes can generate candidates, rank/select "
        "current artifacts, apply image quality gates for image-only requests, "
        "animate the best image when video is requested, and "
        "return only selected media for delivery. Grok Imagine/xAI image "
        "requests with reference images or fixed-character follow-ups should use "
        "this tool path; xAI reference image generation is not text-to-image only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Natural-language visual request from the user.",
            },
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional image paths or URLs supplied by the user.",
            },
            "aspect_ratio": {
                "type": "string",
                "description": "Optional requested output aspect ratio when the user explicitly asks for one.",
            },
            "duration": {
                "type": "integer",
                "description": "Optional video duration in seconds when explicitly requested outside the prompt text.",
            },
        },
        "required": ["prompt"],
    },
}


def check_visual_agent_requirements() -> bool:
    return check_visual_package_requirements()


async def _handle_visual_agent_generate(args: dict[str, Any], **_kw: Any) -> str:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return tool_error("prompt is required for visual agent generation")
    if is_visual_prompt_disclosure_request(prompt):
        return tool_error(
            "visual_agent_generate is for image/video generation, not prompt disclosure",
            request_type="visual_prompt_disclosure",
        )

    attachments = _normalise_attachments(args.get("attachments"))
    plan = plan_visual_agent_request(prompt, attachments=attachments)
    if not plan.get("should_use_visual_package"):
        return tool_error("visual_agent_generate requires a visual image or video request")

    package_args = dict(plan.get("arguments") or {})
    _merge_direct_visual_package_overrides(package_args, args)
    for key in ("visual_agent_llm_provider", "visual_agent_llm_model", "visual_agent_handoff_mode"):
        if args.get(key):
            package_args[key] = args[key]
    package_args, llm_plan = apply_visual_agent_llm_planner(package_args)

    raw = await _handle_visual_package_generate(package_args)
    try:
        payload = json.loads(raw)
    except Exception:
        return raw
    if isinstance(payload, dict):
        payload["visual_agent_plan"] = plan
        payload["visual_agent_provider_contract"] = plan.get("provider_contract")
        if llm_plan is not None:
            payload["visual_agent_llm_plan"] = llm_plan
        payload["visual_agent_tool"] = "visual_agent_generate"
        return json.dumps(payload, ensure_ascii=False)
    return raw


def _merge_direct_visual_package_overrides(
    package_args: dict[str, Any],
    args: dict[str, Any],
) -> None:
    for key in _DIRECT_VISUAL_PACKAGE_OVERRIDE_KEYS:
        if key not in args:
            continue
        value = args[key]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        package_args[key] = str(value) if key == "aspect_ratio" else value


def _normalise_attachments(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    attachments: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        attachment = normalise_visual_agent_attachment(item)
        if attachment:
            attachments.append(attachment)
    return attachments


registry.register(
    name="visual_agent_generate",
    toolset="image_gen",
    schema=VISUAL_AGENT_SCHEMA,
    handler=_handle_visual_agent_generate,
    check_fn=check_visual_agent_requirements,
    requires_env=[],
    is_async=True,
    emoji="🧭",
)
