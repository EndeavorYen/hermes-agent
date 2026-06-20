"""Task-local source metadata for visual generation requests."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VisualSourceContext:
    platform: Optional[str] = None
    channel_id: Optional[str] = None
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    message_id: Optional[str] = None
    conversation_id: Optional[str] = None

    @classmethod
    def from_gateway_event(cls, event: object) -> "VisualSourceContext":
        source = getattr(event, "source", None)
        platform = _platform_value(getattr(source, "platform", None))
        channel_id = _clean(getattr(source, "chat_id", None))
        message_id = (
            _clean(getattr(event, "message_id", None))
            or _clean(getattr(source, "message_id", None))
        )
        conversation_id = (
            f"{platform}:{channel_id}" if platform and channel_id else None
        )
        return cls(
            platform=platform,
            channel_id=channel_id,
            thread_id=_clean(getattr(source, "thread_id", None)),
            user_id=_clean(getattr(source, "user_id", None)),
            message_id=message_id,
            conversation_id=conversation_id,
        )

    def __post_init__(self) -> None:
        for field_name in (
            "platform",
            "channel_id",
            "thread_id",
            "user_id",
            "message_id",
            "conversation_id",
        ):
            value = _clean(getattr(self, field_name))
            if field_name == "platform" and value is not None:
                value = value.lower()
            object.__setattr__(self, field_name, value)


_visual_source_context: ContextVar[Optional[VisualSourceContext]] = ContextVar(
    "visual_source_context",
    default=None,
)


def set_visual_source_context(
    context: VisualSourceContext | None,
) -> Token[Optional[VisualSourceContext]]:
    return _visual_source_context.set(context)


def get_visual_source_context() -> VisualSourceContext | None:
    return _visual_source_context.get()


def clear_visual_source_context(
    token: Token[Optional[VisualSourceContext]] | None = None,
) -> None:
    if token is None:
        _visual_source_context.set(None)
    else:
        _visual_source_context.reset(token)


def _clean(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _platform_value(value: object) -> Optional[str]:
    raw = getattr(value, "value", value)
    return _clean(raw)
