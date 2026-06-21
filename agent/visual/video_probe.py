from __future__ import annotations

from typing import Any


def build_video_probe_observation(candidate: dict[str, Any]) -> dict[str, Any]:
    width = _positive_float(candidate.get("width"))
    height = _positive_float(candidate.get("height"))
    duration = _positive_float(candidate.get("duration_seconds"))
    requested = candidate.get("requested_parameters")
    requested_parameters = requested if isinstance(requested, dict) else {}
    requested_aspect = _parse_aspect_ratio(requested_parameters.get("aspect_ratio"))
    requested_duration = _positive_float(requested_parameters.get("duration_seconds"))
    motion = _clamp(candidate.get("motion_score", _duration_motion_score(duration, requested_duration)))

    defects: list[str] = []
    if width is None or height is None:
        aspect_integrity = 0.25
        defects.append("missing_video_dimensions")
    else:
        actual_aspect = width / height
        if requested_aspect is None:
            aspect_integrity = 0.75
        else:
            aspect_integrity = _aspect_score(actual_aspect, requested_aspect)
            if aspect_integrity < 0.75:
                defects.append("aspect_mismatch")

    if duration is None:
        defects.append("missing_video_duration")
    elif requested_duration is not None and _duration_score(duration, requested_duration) < 0.75:
        defects.append("duration_mismatch")

    if motion < 0.4:
        defects.append("weak_motion_evidence")

    metadata_confidence = 1.0
    if width is None or height is None:
        metadata_confidence -= 0.35
    if duration is None:
        metadata_confidence -= 0.25

    confidence = _clamp((aspect_integrity + motion + metadata_confidence) / 3)
    return {
        "aspect_integrity": round(_clamp(aspect_integrity), 4),
        "motion_quality": round(motion, 4),
        "confidence": round(confidence, 4),
        "artifact_defects": list(dict.fromkeys(defects)),
        "evidence": {
            "source": "video_probe",
            "summary": "video metadata, aspect, and motion quality observation",
        },
    }


def _parse_aspect_ratio(value: Any) -> float | None:
    if isinstance(value, str):
        text = value.strip().lower()
        if ":" in text:
            left, right = text.split(":", 1)
            numerator = _positive_float(left)
            denominator = _positive_float(right)
            if numerator and denominator:
                return numerator / denominator
        number = _positive_float(text)
        if number:
            return number
    return _positive_float(value)


def _aspect_score(actual: float, requested: float) -> float:
    if actual <= 0 or requested <= 0:
        return 0.0
    ratio = min(actual, requested) / max(actual, requested)
    return _clamp((ratio - 0.55) / 0.45)


def _duration_motion_score(duration: float | None, requested_duration: float | None) -> float:
    if duration is None:
        return 0.25
    if requested_duration is None:
        return 0.6
    return _duration_score(duration, requested_duration)


def _duration_score(duration: float, requested_duration: float) -> float:
    if duration <= 0 or requested_duration <= 0:
        return 0.0
    ratio = min(duration, requested_duration) / max(duration, requested_duration)
    return _clamp(ratio)


def _positive_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    return numeric


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))
