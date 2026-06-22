from __future__ import annotations

from typing import Any


def classify_visual_provider_failure(payload: dict[str, Any] | Exception) -> dict[str, Any]:
    status_code = _status_code(payload)
    text = _failure_text(payload)
    code = _message_code(payload, text)

    if _is_timeout(payload, text):
        return _result("timeout", retryable=True, safe_reframe_allowed=False, provider_message_code=code)
    if _contains(text, "content_moderation", "moderation", "safety", "policy rejected", "blocked", "policy_violation"):
        return _result("content_moderation", retryable=True, safe_reframe_allowed=True, provider_message_code=code)
    if _contains(text, "empty_response", "empty response", "no output", "blank response"):
        return _result("empty_response", retryable=True, safe_reframe_allowed=False, provider_message_code=code)
    if _contains(
        text,
        "reference_images not supported",
        "reference image not supported",
        "unsupported reference",
        "does not support reference_images",
        "reference_images conditioning",
    ):
        return _result("unsupported_reference", retryable=True, safe_reframe_allowed=False, provider_message_code=code)
    if _contains(text, "aspect ratio", "invalid aspect", "unsupported aspect"):
        return _result("unsupported_aspect_ratio", retryable=True, safe_reframe_allowed=False, provider_message_code=code)
    if status_code == 429 or _contains(text, "rate limit", "rate_limited", "too many requests"):
        return _result("rate_limited", retryable=True, safe_reframe_allowed=False, provider_message_code=code)
    if status_code in {500, 502, 503, 504} or _is_provider_unavailable_text(text):
        return _result("provider_unavailable", retryable=True, safe_reframe_allowed=False, provider_message_code=code)
    return _result("unknown", retryable=False, safe_reframe_allowed=False, provider_message_code=code)


def _result(
    failure_class: str,
    *,
    retryable: bool,
    safe_reframe_allowed: bool,
    provider_message_code: str,
) -> dict[str, Any]:
    return {
        "failure_class": failure_class,
        "retryable": retryable,
        "safe_reframe_allowed": safe_reframe_allowed,
        "provider_message_code": provider_message_code,
        "operator_summary": _operator_summary(failure_class),
    }


def _operator_summary(failure_class: str) -> str:
    return {
        "content_moderation": "provider rejected the request for content moderation",
        "timeout": "provider request timed out",
        "empty_response": "provider returned no usable output",
        "unsupported_reference": "provider does not support the requested reference conditioning",
        "unsupported_aspect_ratio": "provider does not support the requested aspect ratio",
        "rate_limited": "provider rate limit was hit",
        "provider_unavailable": "provider is unavailable",
    }.get(failure_class, "provider failure could not be classified")


def _failure_text(payload: dict[str, Any] | Exception) -> str:
    if isinstance(payload, Exception):
        return f"{type(payload).__name__} {payload}".lower()
    if not isinstance(payload, dict):
        return str(payload).lower()
    parts = [
        payload.get("error_type"),
        payload.get("error"),
        payload.get("message"),
        payload.get("reason"),
    ]
    return " ".join(_flatten_text(part) for part in parts if part).lower()


def _message_code(payload: dict[str, Any] | Exception, text: str) -> str:
    if isinstance(payload, dict):
        for key in ("error_type", "code", "status_code"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        nested_code = _nested_code(payload.get("error"))
        if nested_code:
            return nested_code
    if "content_moderation" in text:
        return "content_moderation"
    return "unknown"


def _status_code(payload: dict[str, Any] | Exception) -> int | None:
    if not isinstance(payload, dict):
        return None
    try:
        return int(payload.get("status_code"))
    except (TypeError, ValueError):
        return None


def _is_timeout(payload: dict[str, Any] | Exception, text: str) -> bool:
    return isinstance(payload, TimeoutError) or _contains(text, "timeout", "timed out", "deadline")


def _contains(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _is_provider_unavailable_text(text: str) -> bool:
    return _contains(
        text,
        "(500)",
        "(502)",
        "(503)",
        "(504)",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "unavailable",
        "bad gateway",
        "service down",
        "connection refused",
        "connect error",
        "connection failure",
        "remote connection failure",
        "transport failure",
        "reset before headers",
    )


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


def _nested_code(value: Any) -> str | None:
    if isinstance(value, dict):
        code = value.get("code") or value.get("error_code") or value.get("type")
        if code not in (None, ""):
            return str(code)
    return None
