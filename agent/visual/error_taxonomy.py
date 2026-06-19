"""Shared error taxonomy for visual generation attempts."""

from __future__ import annotations

from typing import Optional

CANONICAL_VISUAL_ERROR_TYPES = {
    "success",
    "auth_required",
    "permission_denied",
    "rate_limited",
    "timeout",
    "connection_error",
    "invalid_request",
    "unsupported_feature",
    "content_moderation",
    "provider_unavailable",
    "empty_response",
    "cache_failed",
    "delivery_failed",
    "stale_artifact",
    "provider_error",
}

_ALIASES = {
    "api_error": "provider_error",
    "connectionerror": "connection_error",
    "connect_error": "connection_error",
    "connect_timeout": "timeout",
    "content_filter": "content_moderation",
    "content_policy": "content_moderation",
    "http_401": "auth_required",
    "http_403": "permission_denied",
    "http_429": "rate_limited",
    "memory_quota_exceeded_non_retryable": "provider_unavailable",
    "moderation": "content_moderation",
    "permission_error": "permission_denied",
    "policy_refusal": "content_moderation",
    "read_timeout": "timeout",
    "request_timeout": "timeout",
    "safety": "content_moderation",
    "timeout_error": "timeout",
    "tool_timeout": "timeout",
    "valueerror": "invalid_request",
    "write_timeout": "timeout",
}


def normalize_visual_error_type(
    error_type: Optional[str],
    *,
    success: bool = False,
) -> str:
    if success:
        return "success"
    normalized = str(error_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return "provider_error"
    if normalized in CANONICAL_VISUAL_ERROR_TYPES:
        return normalized
    return _ALIASES.get(normalized, "provider_error")
