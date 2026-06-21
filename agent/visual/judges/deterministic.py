from __future__ import annotations

from typing import Any


VERSION = "deterministic_judge.v0.1"


def judge_artifact(
    artifact: dict[str, Any],
    *,
    expected_kind: str,
    requested_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested_parameters = requested_parameters or {}
    hard_gate = _hard_gate(artifact, expected_kind=expected_kind)
    scores = _soft_scores(
        artifact,
        expected_kind=expected_kind,
        requested_parameters=requested_parameters,
        hard_gate_passed=hard_gate["passed"],
    )
    return {
        "version": VERSION,
        "hard_gate": hard_gate,
        "scores": scores,
    }


def _hard_gate(artifact: dict[str, Any], *, expected_kind: str) -> dict[str, bool]:
    exists = _artifact_exists(artifact)
    artifact_fresh = artifact.get("freshness_status") == "fresh" and artifact.get("is_stable") is not False
    mime_valid = _mime_matches_kind(artifact.get("mime_type"), expected_kind)
    kind_match = artifact.get("kind") == expected_kind
    no_provider_error = not artifact.get("error_type") and artifact.get("status") != "failed"
    delivery_possible = bool(artifact.get("local_path") or artifact.get("uri") or artifact.get("source"))
    passed = all(
        [
            exists,
            artifact_fresh,
            mime_valid,
            kind_match,
            no_provider_error,
            delivery_possible,
        ]
    )
    return {
        "passed": passed,
        "exists": exists,
        "artifact_fresh": artifact_fresh,
        "mime_valid": mime_valid,
        "kind_match": kind_match,
        "no_provider_error": no_provider_error,
        "delivery_possible": delivery_possible,
    }


def _soft_scores(
    artifact: dict[str, Any],
    *,
    expected_kind: str,
    requested_parameters: dict[str, Any],
    hard_gate_passed: bool,
) -> dict[str, float]:
    aspect_match = _aspect_match_score(
        width=artifact.get("width"),
        height=artifact.get("height"),
        requested_aspect=requested_parameters.get("aspect_ratio"),
    )
    resolution = _resolution_score(artifact.get("width"), artifact.get("height"))
    duration = _duration_score(
        expected_kind=expected_kind,
        artifact_duration=artifact.get("duration_seconds"),
        requested_duration=requested_parameters.get("duration_seconds"),
    )
    provider_reliability = 0.5
    raw_score = (
        aspect_match * 0.30
        + resolution * 0.30
        + duration * 0.20
        + provider_reliability * 0.20
    )
    final_score = raw_score if hard_gate_passed else 0.0
    return {
        "aspect_match": round(aspect_match, 4),
        "resolution": round(resolution, 4),
        "duration": round(duration, 4),
        "provider_reliability": provider_reliability,
        "final_score": round(final_score, 4),
    }


def _artifact_exists(artifact: dict[str, Any]) -> bool:
    byte_count = artifact.get("bytes")
    return bool(
        artifact.get("content_hash")
        or artifact.get("local_path")
        or artifact.get("uri")
        or (isinstance(byte_count, int | float) and byte_count > 0)
    )


def _mime_matches_kind(mime_type: str | None, expected_kind: str) -> bool:
    if not mime_type:
        return False
    if expected_kind == "image":
        return mime_type.startswith("image/")
    if expected_kind == "video":
        return mime_type.startswith("video/")
    return True


def _aspect_match_score(width: Any, height: Any, requested_aspect: Any) -> float:
    if not requested_aspect or not width or not height:
        return 0.5
    target = _parse_aspect_ratio(str(requested_aspect))
    if target is None:
        return 0.5
    actual = float(width) / float(height)
    error = abs(actual - target) / target
    if error <= 0.02:
        return 1.0
    return max(0.0, 1.0 - error)


def _parse_aspect_ratio(value: str) -> float | None:
    if ":" in value:
        left, right = value.split(":", 1)
        try:
            return float(left) / float(right)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _resolution_score(width: Any, height: Any) -> float:
    if not width or not height:
        return 0.5
    pixels = float(width) * float(height)
    return min(1.0, pixels / float(1280 * 720))


def _duration_score(
    *,
    expected_kind: str,
    artifact_duration: Any,
    requested_duration: Any,
) -> float:
    if expected_kind != "video" or not requested_duration:
        return 1.0
    if not artifact_duration:
        return 0.5
    target = float(requested_duration)
    if target <= 0:
        return 0.5
    error = abs(float(artifact_duration) - target) / target
    return max(0.0, 1.0 - error)
