from __future__ import annotations

import json
from typing import Any

from .audit import normalize_provider
from .state import StoryVideoRunContext


def _flatten(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str).lower()
    except Exception:
        return str(value or "").lower()


def _is_openai(value: Any) -> bool:
    return normalize_provider(value) in {"openai", "openai-codex"}


def guard_tool_call(
    context: StoryVideoRunContext,
    tool_name: str,
    args: dict[str, Any] | None,
) -> str | None:
    name = str(tool_name or "").strip().lower()
    payload = dict(args or {})

    if name == "image_generate":
        provider = payload.get("provider") or payload.get("_provider")
        if not provider:
            return (
                "Story-video image provider is missing. Retry this scene with "
                "provider=openai-codex; configured xAI defaults are forbidden."
            )
        if not _is_openai(provider):
            return (
                f"Story-video blocked image provider {provider!r}. "
                "Use provider=openai-codex."
            )
        return None

    if name == "video_generate":
        return (
            "Story-video body generation must use the narration-aligned local "
            "renderer, not generic video_generate."
        )

    if name == "visual_package_generate":
        include_video = payload.get("include_video")
        if include_video is not False:
            return (
                "Story-video visual packages cannot include a generic video body; "
                "use the narration-aligned local renderer."
            )
        provider = payload.get("image_provider") or payload.get("provider")
        if not _is_openai(provider):
            return "Story-video visual package images require image_provider=openai-codex."
        return None

    if name == "text_to_speech":
        return (
            "Story-video narration must use the locked OpenAI or local narration "
            "path. The generic TTS tool may follow the configured Edge/xAI fallback."
        )

    if name in {"terminal", "delegate_task", "delegate", "code_execution"}:
        text = _flatten(payload)
        if any(token in text for token in ("xai", "x.ai", "grok")):
            return f"Story-video blocked explicit xAI/Grok use through {name}."

    return None
