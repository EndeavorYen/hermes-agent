from __future__ import annotations

import json
from typing import Any

from agent.visual.agent_mode.grok_planner import apply_visual_agent_llm_planner
from agent.visual.agent_mode.handoff import is_visual_prompt_disclosure_request
from agent.visual.agent_mode.handoff import is_visual_prompt_builder_request
from agent.visual.agent_mode.handoff import normalise_visual_agent_attachment
from agent.visual.agent_mode.planner import plan_visual_agent_request
from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.production_kernel.integration import attach_visual_production_kernel
from agent.visual.production_kernel.providers import build_provider_quality_profiles
from agent.visual.tracking import default_visual_ledger_path
from tools.registry import registry
from tools.registry import tool_error
from tools.visual_package_tool import _handle_visual_package_generate
from tools.visual_package_tool import _visual_request_category
from tools.visual_package_tool import check_visual_package_requirements


_DIRECT_VISUAL_PACKAGE_OVERRIDE_KEYS = frozenset(
    {
        "aspect_ratio",
        "autonomy_level",
        "candidate_budget",
        "candidate_budget_source",
        "duration",
        "execution_deadline_seconds",
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
        "Use this only when the user explicitly asks to generate, output, deliver, "
        "revise, or regenerate media: images, videos, image plus video packages, "
        "reference-based variations, product photos, portrait/fashion/glamour "
        "visuals, draw/anime/character art, animate/make-it-move requests, "
        "draw/anime/character art prompts, "
        "storyboard/multi-shot video requests, or short motion clips without "
        "advanced parameters. The tool plans the request, then dispatches to "
        "visual_package_generate so Hermes can generate candidates, rank/select "
        "current artifacts, apply image quality gates for image-only requests, "
        "animate the best image when video is requested, and "
        "return only selected media for delivery. Grok Imagine/xAI image "
        "requests with reference images or fixed-character follow-ups should use "
        "this tool path; xAI reference image generation is not text-to-image only. "
        "For a visual brief with references but no explicit media-output request, "
        "do not call this tool; answer with a stronger prompt in text."
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
            "visual_agent_llm_rounds": {
                "type": "integer",
                "description": "Optional operator control for visual prompt-planner rounds; defaults to 2 and clamps to 2-3.",
            },
            "execution_deadline_seconds": {
                "type": "number",
                "description": (
                    "Optional operator override for the visual package execution deadline. "
                    "Natural requests use the configured default."
                ),
            },
        },
        "required": ["prompt"],
    },
}


def check_visual_agent_requirements() -> bool:
    return check_visual_package_requirements()


def _handle_visual_agent_generate(args: dict[str, Any], **_kw: Any) -> str:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return tool_error("prompt is required for visual agent generation")
    if is_visual_prompt_disclosure_request(prompt):
        return tool_error(
            "visual_agent_generate is for image/video generation, not prompt disclosure",
            request_type="visual_prompt_disclosure",
    )
    if is_visual_prompt_builder_request(prompt):
        return tool_error(
            "visual_agent_generate is for image/video generation, not prompt drafting",
            request_type="visual_prompt_builder",
            recommended_action="return a copyable visual prompt in text instead of generating media",
        )

    attachments = _normalise_attachments(args.get("attachments"))
    force_image_output = bool(
        args.get("include_image")
        or args.get("image_operation")
        or args.get("grok_web_operation")
        or str(args.get("visual_agent_handoff_mode") or "") == "pre_llm_direct"
    )
    plan = plan_visual_agent_request(
        prompt,
        attachments=attachments,
        force_image_output=force_image_output,
    )
    if not plan.get("should_use_visual_package"):
        if attachments and plan.get("reason") == "not_visual_agent_request":
            return tool_error(
                "visual_agent_generate requires an explicit image or video output request",
                request_type="visual_prompt_draft_default",
            )
        return tool_error("visual_agent_generate requires a visual image or video request")

    package_args = dict(plan.get("arguments") or {})
    _merge_direct_visual_package_overrides(package_args, args)
    if args.get("candidate_budget") is not None:
        package_args["candidate_budget_source"] = str(
            args.get("candidate_budget_source") or "user"
        )
    if args.get("image_provider"):
        package_args["image_provider_source"] = str(
            args.get("image_provider_source") or "direct_override"
        )
    for key in (
        "visual_agent_llm_provider",
        "visual_agent_llm_model",
        "visual_agent_handoff_mode",
        "visual_agent_llm_rounds",
    ):
        if args.get(key):
            package_args[key] = args[key]
    package_args, llm_plan = apply_visual_agent_llm_planner(package_args)
    request_category = _visual_request_category(prompt)
    package_args["provider_profiles"] = _runtime_provider_quality_profiles(
        category=request_category
    )
    package_args = attach_visual_production_kernel(prompt, package_args)

    raw = _handle_visual_package_generate(package_args)
    try:
        payload = json.loads(raw)
    except Exception:
        return raw
    if isinstance(payload, dict):
        provider_contract = dict(plan.get("provider_contract") or {})
        provider_contract["image_provider"] = package_args.get("image_provider")
        provider_contract["visual_media_provider_selected"] = package_args.get(
            "image_provider"
        )
        provider_contract["visual_media_provider_selection_reason"] = (
            package_args.get("provider_decision") or {}
        ).get("reason")
        for key in (
            "visual_agent_llm_provider",
            "visual_agent_llm_model",
        ):
            if package_args.get(key):
                provider_contract[key] = package_args[key]
        for key in (
            "image_provider",
            "image_model",
            "video_provider",
            "video_model",
        ):
            if args.get(key):
                provider_contract[key] = args[key]
        payload["visual_agent_plan"] = plan
        payload["visual_agent_provider_contract"] = provider_contract
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


def _runtime_provider_quality_profiles(
    *,
    category: str | None = None,
) -> dict[str, dict[str, Any]]:
    ledger_path = default_visual_ledger_path()
    if not ledger_path.exists():
        return {}
    try:
        return build_provider_quality_profiles(
            VisualAttemptLedger(ledger_path),
            category=category,
        )
    except Exception:
        return {}


registry.register(
    name="visual_agent_generate",
    toolset="image_gen",
    schema=VISUAL_AGENT_SCHEMA,
    handler=_handle_visual_agent_generate,
    check_fn=check_visual_agent_requirements,
    requires_env=[],
    is_async=False,
    emoji="🧭",
)
