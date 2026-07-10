from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REDACTED_VALUE = "[redacted]"
TRUNCATED_SUFFIX = "[truncated]"
DEFAULT_MAX_STRING_LENGTH = 240

_SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "refresh_token",
    "secret",
    "token",
)


def _is_secret_key(key: Any) -> bool:
    normalized = str(key).lower()
    return any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS)


def _redact_string(value: str, max_string_length: int) -> str:
    if len(value) <= max_string_length:
        return value
    return value[:max_string_length] + TRUNCATED_SUFFIX


def redact_trace_payload(
    payload: Any,
    *,
    max_string_length: int = DEFAULT_MAX_STRING_LENGTH,
) -> Any:
    """Return a JSON-safe copy of ``payload`` with secrets and large strings redacted."""
    max_length = max(0, int(max_string_length))

    if isinstance(payload, Mapping):
        return {
            str(key): (
                REDACTED_VALUE
                if _is_secret_key(key)
                else redact_trace_payload(value, max_string_length=max_length)
            )
            for key, value in payload.items()
        }
    if isinstance(payload, str):
        return _redact_string(payload, max_length)
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [
            redact_trace_payload(item, max_string_length=max_length)
            for item in payload
        ]
    return payload


__all__ = [
    "DEFAULT_MAX_STRING_LENGTH",
    "REDACTED_VALUE",
    "TRUNCATED_SUFFIX",
    "redact_trace_payload",
]
