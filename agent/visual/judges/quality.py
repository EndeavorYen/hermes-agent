from __future__ import annotations

from typing import Any


VERSION = "visual_quality_judge.v0.1"


def judge_visual_quality(
    candidate: dict[str, Any],
    *,
    request_context: dict[str, Any] | None = None,
    recent_artifact_hashes: set[str] | None = None,
) -> dict[str, Any]:
    request_context = request_context or {}
    recent_artifact_hashes = recent_artifact_hashes or set()
    deterministic_scores = candidate.get("scores") if isinstance(candidate.get("scores"), dict) else {}
    hard_gate = candidate.get("hard_gate") if isinstance(candidate.get("hard_gate"), dict) else {}
    uncertainty_reasons: list[str] = []

    reference_adherence = _reference_adherence(candidate, request_context, uncertainty_reasons)
    novelty = _novelty(candidate, recent_artifact_hashes, uncertainty_reasons)
    scores = {
        "reference_adherence": reference_adherence,
        "aesthetic_fit": _aesthetic_fit(deterministic_scores),
        "composition": _composition(deterministic_scores),
        "novelty": novelty,
        "motion_quality": _motion_quality(candidate, deterministic_scores),
        "aspect_integrity": _clamp(deterministic_scores.get("aspect_match", 0.5)),
        "delivery_readiness": 1.0 if hard_gate.get("delivery_possible") is True else 0.5,
    }
    if hard_gate.get("passed") is not True:
        uncertainty_reasons.append("hard_gate_not_passed")
    confidence = _confidence(scores=scores, uncertainty_reasons=uncertainty_reasons)
    return {
        "version": VERSION,
        "scores": {key: round(value, 4) for key, value in scores.items()},
        "confidence": confidence,
        "uncertainty_reasons": sorted(set(uncertainty_reasons)),
    }


def _reference_adherence(
    candidate: dict[str, Any],
    request_context: dict[str, Any],
    uncertainty_reasons: list[str],
) -> float:
    if request_context.get("has_reference_image") is not True:
        return 0.5
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    value = metadata.get("reference_adherence")
    if value is not None:
        return _clamp(value)
    uncertainty_reasons.append("reference_evidence_missing")
    return 0.35


def _aesthetic_fit(deterministic_scores: dict[str, Any]) -> float:
    resolution = _clamp(deterministic_scores.get("resolution", 0.5))
    final_score = _clamp(deterministic_scores.get("final_score", 0.5))
    return _clamp(resolution * 0.55 + final_score * 0.45)


def _composition(deterministic_scores: dict[str, Any]) -> float:
    aspect = _clamp(deterministic_scores.get("aspect_match", 0.5))
    resolution = _clamp(deterministic_scores.get("resolution", 0.5))
    return _clamp(aspect * 0.65 + resolution * 0.35)


def _novelty(
    candidate: dict[str, Any],
    recent_artifact_hashes: set[str],
    uncertainty_reasons: list[str],
) -> float:
    content_hash = candidate.get("content_hash")
    if isinstance(content_hash, str) and content_hash and content_hash in recent_artifact_hashes:
        uncertainty_reasons.append("duplicate_content_hash")
        return 0.0
    return 1.0


def _motion_quality(candidate: dict[str, Any], deterministic_scores: dict[str, Any]) -> float:
    if candidate.get("kind") != "video":
        return 1.0
    return _clamp(deterministic_scores.get("duration", 0.5))


def _confidence(*, scores: dict[str, float], uncertainty_reasons: list[str]) -> float:
    base = sum(scores.values()) / len(scores) if scores else 0.0
    penalty = min(0.4, len(set(uncertainty_reasons)) * 0.1)
    return round(_clamp(base - penalty), 4)


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))
