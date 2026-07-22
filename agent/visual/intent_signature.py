from __future__ import annotations

import hashlib
import json
from typing import Any


_SIGNATURE_PREFIX = "visig_"
_SIGNATURE_KEYS = {
    "aspect_ratio",
    "bucket",
    "camera",
    "composition",
    "content_type",
    "duration",
    "duration_seconds",
    "has_reference_image",
    "lighting",
    "locks",
    "modality",
    "mood",
    "motion",
    "operation",
    "provider",
    "reference_policy",
    "scene",
    "setting",
    "soft_preferences",
    "style",
    "style_family",
    "subject_type",
    "wants_image",
    "wants_video",
}


def build_intent_signature(intent: dict[str, Any]) -> str:
    """Build a stable private-safe bucket signature for visual learning."""
    public_bucket = {
        key: _normalise_value(intent[key])
        for key in sorted(_SIGNATURE_KEYS)
        if key in intent and intent[key] is not None
    }
    canonical = json.dumps(public_bucket, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{_SIGNATURE_PREFIX}{digest}"


def _normalise_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalise_value(inner)
            for key, inner in sorted(value.items(), key=lambda item: str(item[0]))
            if inner is not None
        }
    if isinstance(value, (list, tuple)):
        return [_normalise_value(item) for item in value if item is not None]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
