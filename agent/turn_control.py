from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def resolve_turn_origin(
    *,
    explicit_origin: str | None = None,
    write_origin: str | None = None,
) -> str:
    explicit = _text(explicit_origin).lower()
    source = explicit or _text(write_origin).lower()
    if source.startswith(("cron", "scheduled")):
        return "scheduled"
    if source.startswith(("replay", "resume")):
        return "resume"
    if source.startswith(
        ("background", "subagent", "child_agent")
    ):
        return "background"
    return "foreground"


def resolve_runtime_contract(
    config: Mapping[str, Any] | None,
    *,
    live_provider: str | None = None,
    live_model: str | None = None,
    live_api_mode: str | None = None,
) -> dict[str, Any]:
    config = config if isinstance(config, Mapping) else {}
    model_config = _mapping(config.get("model"))
    if model_config:
        configured_model = _text(model_config.get("default") or model_config.get("model"))
        configured_provider = _text(model_config.get("provider"))
        configured_api_mode = _text(
            model_config.get("openai_runtime") or model_config.get("api_mode")
        )
    else:
        configured_model = _text(config.get("model"))
        configured_provider = _text(config.get("provider"))
        configured_api_mode = _text(config.get("api_mode"))

    visual_planner = _mapping(config.get("visual_agent"))
    image_gen = _mapping(config.get("image_gen"))
    video_gen = _mapping(config.get("video_gen"))
    has_live_values = any(
        _text(value) for value in (live_provider, live_model, live_api_mode)
    )
    return {
        "base_provider": _text(live_provider) or configured_provider,
        "base_model": _text(live_model) or configured_model,
        "base_api_mode": _text(live_api_mode) or configured_api_mode,
        "visual_planner_provider": _optional_text(visual_planner.get("provider")),
        "visual_planner_model": _optional_text(visual_planner.get("model")),
        "image_provider": _optional_text(image_gen.get("provider")),
        "image_model": _optional_text(image_gen.get("model")),
        "video_provider": _optional_text(video_gen.get("provider")),
        "video_model": _optional_text(video_gen.get("model")),
        "source": "live_agent" if has_live_values else "effective_config",
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


__all__ = ["resolve_runtime_contract", "resolve_turn_origin"]
