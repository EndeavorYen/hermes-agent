from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class RaphaelTurnOrigin(str, Enum):
    FOREGROUND = "foreground"
    BACKGROUND_REVIEW = "background_review"
    CRON = "cron"
    SUBAGENT = "subagent"
    REPLAY = "replay"


@dataclass(frozen=True)
class RaphaelRuntimeContract:
    base_provider: str
    base_model: str
    base_api_mode: str
    visual_planner_provider: str | None = None
    visual_planner_model: str | None = None
    image_provider: str | None = None
    image_model: str | None = None
    video_provider: str | None = None
    video_model: str | None = None
    source: str = "effective_config"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RaphaelRuntimeContract":
        return cls(
            base_provider=_text(payload.get("base_provider")),
            base_model=_text(payload.get("base_model")),
            base_api_mode=_text(payload.get("base_api_mode")),
            visual_planner_provider=_optional_text(
                payload.get("visual_planner_provider")
            ),
            visual_planner_model=_optional_text(payload.get("visual_planner_model")),
            image_provider=_optional_text(payload.get("image_provider")),
            image_model=_optional_text(payload.get("image_model")),
            video_provider=_optional_text(payload.get("video_provider")),
            video_model=_optional_text(payload.get("video_model")),
            source=_text(payload.get("source")) or "effective_config",
        )


def resolve_raphael_turn_origin(
    *,
    explicit_origin: str | RaphaelTurnOrigin | None = None,
    write_origin: str | None = None,
) -> RaphaelTurnOrigin:
    if isinstance(explicit_origin, RaphaelTurnOrigin):
        return explicit_origin
    explicit = _text(explicit_origin).lower()
    if explicit:
        try:
            return RaphaelTurnOrigin(explicit)
        except ValueError:
            pass

    write_value = _text(write_origin).lower()
    if write_value.startswith("background_review"):
        return RaphaelTurnOrigin.BACKGROUND_REVIEW
    if write_value.startswith(("cron", "scheduled")):
        return RaphaelTurnOrigin.CRON
    if write_value.startswith(("subagent", "child_agent")):
        return RaphaelTurnOrigin.SUBAGENT
    if write_value.startswith("replay"):
        return RaphaelTurnOrigin.REPLAY
    return RaphaelTurnOrigin.FOREGROUND


def resolve_raphael_runtime_contract(
    config: Mapping[str, Any] | None,
    *,
    live_provider: str | None = None,
    live_model: str | None = None,
    live_api_mode: str | None = None,
) -> RaphaelRuntimeContract:
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

    raphael = _mapping(config.get("raphael"))
    visual_planner = _mapping(
        raphael.get("visual_planner") or config.get("visual_agent")
    )
    image_gen = _mapping(config.get("image_gen"))
    video_gen = _mapping(config.get("video_gen"))
    has_live_values = any(
        _text(value) for value in (live_provider, live_model, live_api_mode)
    )

    return RaphaelRuntimeContract(
        base_provider=_text(live_provider) or configured_provider,
        base_model=_text(live_model) or configured_model,
        base_api_mode=_text(live_api_mode) or configured_api_mode,
        visual_planner_provider=_optional_text(visual_planner.get("provider")),
        visual_planner_model=_optional_text(visual_planner.get("model")),
        image_provider=_optional_text(image_gen.get("provider")),
        image_model=_optional_text(image_gen.get("model")),
        video_provider=_optional_text(video_gen.get("provider")),
        video_model=_optional_text(video_gen.get("model")),
        source="live_agent" if has_live_values else "effective_config",
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


__all__ = [
    "RaphaelRuntimeContract",
    "RaphaelTurnOrigin",
    "resolve_raphael_runtime_contract",
    "resolve_raphael_turn_origin",
]
