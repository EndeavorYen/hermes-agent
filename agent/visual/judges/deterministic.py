"""Deterministic artifact scoring for visual generation."""

from __future__ import annotations

from typing import Any, Dict, Optional


VALID_MIME_PREFIXES = ("image/", "video/")
VALID_IMAGE_MIME_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}
VALID_VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/mpeg",
    "video/quicktime",
    "video/webm",
    "video/x-m4v",
}


def score_deterministic_artifact(
    artifact: Dict[str, Any],
    *,
    requested: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score metadata signals that do not require a vision model."""
    requested = requested or {}

    scores = {
        "artifact_exists": _score_artifact_exists(artifact),
        "content_hash_present": _score_content_hash(artifact),
        "artifact_stable": 1.0 if _truthy(artifact.get("is_stable")) else 0.0,
        "artifact_fresh": _score_freshness(artifact.get("freshness_status")),
        "mime_valid": _score_mime(artifact.get("mime_type")),
        "byte_size_valid": _score_bytes(artifact.get("bytes")),
        "aspect_fit": _score_aspect_fit(artifact, requested),
        "duration_fit": _score_duration_fit(artifact, requested),
        "delivery_possible": _score_delivery_possible(artifact),
    }
    failed = [
        key
        for key in (
            "artifact_exists",
            "content_hash_present",
            "artifact_stable",
            "artifact_fresh",
            "mime_valid",
            "byte_size_valid",
            "delivery_possible",
        )
        if scores[key] < 1.0
    ]
    return {
        "judge_name": "deterministic",
        "judge_version": "v0",
        "hard_gate": {
            "passed": not failed,
            "failed": failed,
        },
        "scores": scores,
        "confidence": round(sum(scores.values()) / len(scores), 4),
    }


def _score_artifact_exists(artifact: Dict[str, Any]) -> float:
    if _present(artifact.get("local_path")):
        return 1.0
    if _present(artifact.get("source_url")):
        return 1.0
    return 0.0


def _score_content_hash(artifact: Dict[str, Any]) -> float:
    value = str(artifact.get("content_hash") or "").strip()
    return 1.0 if value.startswith("sha256:") else 0.0


def _score_freshness(value: Any) -> float:
    status = str(value or "").strip().lower()
    if status == "fresh":
        return 1.0
    if status in {"unknown", ""}:
        return 0.5
    return 0.0


def _score_mime(value: Any) -> float:
    mime_type = str(value or "").strip().lower()
    if mime_type in VALID_IMAGE_MIME_TYPES or mime_type in VALID_VIDEO_MIME_TYPES:
        return 1.0
    if any(mime_type.startswith(prefix) for prefix in VALID_MIME_PREFIXES):
        return 0.5
    return 0.0


def _score_bytes(value: Any) -> float:
    try:
        return 1.0 if int(value or 0) > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _score_aspect_fit(artifact: Dict[str, Any], requested: Dict[str, Any]) -> float:
    requested_ratio = _parse_ratio(requested.get("aspect_ratio"))
    if requested_ratio is None:
        return 1.0
    width = _positive_float(artifact.get("width"))
    height = _positive_float(artifact.get("height"))
    if not width or not height:
        return 0.0
    actual_ratio = width / height
    relative_error = abs(actual_ratio - requested_ratio) / requested_ratio
    if relative_error <= 0.02:
        return 1.0
    return max(0.0, round(1.0 - relative_error, 4))


def _score_duration_fit(artifact: Dict[str, Any], requested: Dict[str, Any]) -> float:
    target_ms = _requested_duration_ms(requested)
    if target_ms is None:
        return 1.0
    duration_ms = _positive_float(artifact.get("duration_ms"))
    if not duration_ms:
        return 0.0
    relative_error = abs(duration_ms - target_ms) / target_ms
    if relative_error <= 0.10:
        return 1.0
    return max(0.0, round(1.0 - relative_error, 4))


def _score_delivery_possible(artifact: Dict[str, Any]) -> float:
    if _score_artifact_exists(artifact) < 1.0:
        return 0.0
    return min(_score_mime(artifact.get("mime_type")), _score_bytes(artifact.get("bytes")))


def _parse_ratio(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if ":" in text:
        left, right = text.split(":", 1)
    elif "x" in text:
        left, right = text.split("x", 1)
    else:
        try:
            ratio = float(text)
            return ratio if ratio > 0 else None
        except ValueError:
            return None
    width = _positive_float(left)
    height = _positive_float(right)
    if not width or not height:
        return None
    return width / height


def _requested_duration_ms(requested: Dict[str, Any]) -> Optional[float]:
    for key in ("duration_ms", "target_duration_ms"):
        value = _positive_float(requested.get(key))
        if value:
            return value
    seconds = _positive_float(requested.get("duration_seconds"))
    return seconds * 1000 if seconds else None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _present(value: Any) -> bool:
    return bool(str(value or "").strip())


def _positive_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
