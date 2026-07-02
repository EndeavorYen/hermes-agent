from __future__ import annotations

import inspect
import json
from typing import Any

from agent.visual.agent_mode.planner import plan_visual_agent_request
from agent.visual.prompt_disclosure import is_visual_prompt_disclosure_request
from tools.registry import registry, tool_error
from tools.visual_package_tool import _handle_visual_package_generate


VISUAL_AGENT_SCHEMA: dict[str, Any] = {
    "name": "visual_agent_generate",
    "description": (
        "Plan and execute natural visual requests for image generation, video "
        "generation, image plus video, draw/anime/character art, reference "
        "image workflows, and image-first video. Use this for user-facing "
        "visual agent mode requests; it delegates selected media generation "
        "to visual_package_generate."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Natural-language request for an image, video, or visual package.",
            },
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional image paths, data URIs, or URLs supplied by the user.",
            },
        },
        "required": ["prompt"],
    },
}


def check_visual_agent_requirements() -> bool:
    try:
        from tools.visual_package_tool import check_visual_package_requirements

        return bool(check_visual_package_requirements())
    except Exception:
        return False


async def _handle_visual_agent_generate(args: dict[str, Any], **kw: Any) -> str:
    args = args or {}
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return tool_error("prompt is required for visual agent generation")
    if is_visual_prompt_disclosure_request(prompt):
        return tool_error(
            "visual_agent_generate is for image/video generation, not prompt disclosure",
            request_type="visual_prompt_disclosure",
        )

    attachments = args.get("attachments")
    plan = plan_visual_agent_request(
        prompt,
        attachments=attachments if isinstance(attachments, list) else None,
    )
    if not plan.get("should_use_visual_package"):
        return tool_error("visual_agent_generate requires a visual image or video request")

    package_args = dict(plan.get("arguments") or {})
    package_args.update(_explicit_package_overrides(args))
    raw = _handle_visual_package_generate(package_args, **kw)
    if inspect.isawaitable(raw):
        raw = await raw
    payload = _loads_tool_payload(raw)
    payload["visual_agent_plan"] = plan
    payload["visual_agent_provider_contract"] = plan.get("provider_contract") or {}
    return json.dumps(payload, ensure_ascii=False)


def _explicit_package_overrides(args: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "include_image",
        "include_video",
        "candidate_budget",
        "candidate_budget_source",
        "video_budget",
        "duration",
        "aspect_ratio",
        "image_provider",
        "image_provider_source",
        "storyboard",
    }
    return {key: args[key] for key in allowed if key in args}


def _loads_tool_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {"success": False, "error": "visual_package_generate returned a non-string response"}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"visual_package_generate returned invalid JSON: {exc}"}
    if isinstance(payload, dict):
        return payload
    return {"success": False, "error": "visual_package_generate returned non-object JSON"}


registry.register(
    name="visual_agent_generate",
    toolset="image_gen",
    schema=VISUAL_AGENT_SCHEMA,
    handler=_handle_visual_agent_generate,
    check_fn=check_visual_agent_requirements,
    requires_env=[],
    is_async=True,
    emoji="VA",
)
