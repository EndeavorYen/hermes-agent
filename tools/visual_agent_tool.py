from __future__ import annotations

import json
from typing import Any

from agent.visual.agent_mode.planner import plan_visual_agent_request
from tools.registry import registry
from tools.registry import tool_error
from tools.visual_package_tool import _handle_visual_package_generate
from tools.visual_package_tool import check_visual_package_requirements


VISUAL_AGENT_SCHEMA: dict[str, Any] = {
    "name": "visual_agent_generate",
    "description": (
        "User-friendly visual agent mode for natural image/video requests. "
        "Use this as the primary entry point when the user asks for images, "
        "videos, image plus video packages, reference-based variations, product "
        "photos, portrait/fashion/glamour visuals, draw/anime/character art prompts, "
        "storyboard/multi-shot video requests, or short motion clips without "
        "advanced parameters. The tool plans the request, then dispatches to "
        "visual_package_generate so Hermes can generate candidates, rank/select "
        "current artifacts, animate the best image when video is requested, and "
        "return only selected media for delivery."
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

    attachments = _normalise_attachments(args.get("attachments"))
    plan = plan_visual_agent_request(prompt, attachments=attachments)
    if not plan.get("should_use_visual_package"):
        return tool_error("visual_agent_generate requires a visual image or video request")

    package_args = dict(plan.get("arguments") or {})
    if args.get("aspect_ratio"):
        package_args["aspect_ratio"] = str(args["aspect_ratio"])
    if args.get("duration") is not None:
        package_args["duration"] = args["duration"]

    raw = await _handle_visual_package_generate(package_args)
    try:
        payload = json.loads(raw)
    except Exception:
        return raw
    if isinstance(payload, dict):
        payload["visual_agent_plan"] = plan
        payload["visual_agent_tool"] = "visual_agent_generate"
        return json.dumps(payload, ensure_ascii=False)
    return raw


def _normalise_attachments(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


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
