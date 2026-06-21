from __future__ import annotations

from typing import Any

from agent.visual.judges.vision_observation import normalize_vision_observation


VERSION = "visual_quality_judge.v0.1"


def judge_visual_quality(
    candidate: dict[str, Any],
    *,
    request_context: dict[str, Any] | None = None,
    recent_artifact_hashes: set[str] | None = None,
    vision_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_context = request_context or {}
    recent_artifact_hashes = recent_artifact_hashes or set()
    vision = normalize_vision_observation(vision_observation or {})
    vision_confidence = _clamp(vision.get("confidence", 0.0))
    deterministic_scores = candidate.get("scores") if isinstance(candidate.get("scores"), dict) else {}
    hard_gate = candidate.get("hard_gate") if isinstance(candidate.get("hard_gate"), dict) else {}
    uncertainty_reasons: list[str] = []

    reference_adherence = _reference_adherence(candidate, request_context, uncertainty_reasons)
    novelty = _novelty(candidate, recent_artifact_hashes, uncertainty_reasons)
    judge_sources = {
        "reference_adherence": "deterministic" if request_context.get("has_reference_image") else "fallback",
        "aesthetic_fit": "deterministic",
        "composition": "deterministic",
        "novelty": "deterministic",
        "motion_quality": "deterministic",
        "aspect_integrity": "deterministic",
        "delivery_readiness": "deterministic",
    }
    if vision_confidence > 0.0:
        reference_adherence = _vision_dimension(
            vision,
            "reference_adherence",
            reference_adherence,
            judge_sources,
        )
        aesthetic_fit = _vision_aesthetic_fit(
            vision,
            _aesthetic_fit(deterministic_scores),
            request_context,
            uncertainty_reasons,
        )
        if _has_vision_dimension(vision, "visual_appeal") or _has_vision_dimension(vision, "subject_quality"):
            judge_sources["aesthetic_fit"] = "vision"
        composition = _vision_dimension(vision, "composition", _composition(deterministic_scores), judge_sources)
        aspect_integrity = _vision_dimension(
            vision,
            "aspect_integrity",
            _clamp(deterministic_scores.get("aspect_match", 0.5)),
            judge_sources,
        )
        motion_quality = _vision_dimension(
            vision,
            "motion_quality",
            _motion_quality(candidate, deterministic_scores),
            judge_sources,
        )
        _surface_artifact_defects(vision, uncertainty_reasons)
    else:
        aesthetic_fit = _aesthetic_fit(deterministic_scores)
        composition = _composition(deterministic_scores)
        aspect_integrity = _clamp(deterministic_scores.get("aspect_match", 0.5))
        motion_quality = _motion_quality(candidate, deterministic_scores)
    scores = {
        "reference_adherence": reference_adherence,
        "aesthetic_fit": aesthetic_fit,
        "composition": composition,
        "novelty": novelty,
        "motion_quality": motion_quality,
        "aspect_integrity": aspect_integrity,
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
        "judge_sources": judge_sources,
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


def _vision_dimension(
    vision: dict[str, Any],
    key: str,
    default: float,
    judge_sources: dict[str, str],
) -> float:
    if _has_vision_dimension(vision, key):
        judge_sources[_score_key(key)] = "vision"
        return _clamp(vision.get(key))
    return default


def _vision_aesthetic_fit(
    vision: dict[str, Any],
    default: float,
    request_context: dict[str, Any],
    uncertainty_reasons: list[str],
) -> float:
    if _has_vision_dimension(vision, "visual_appeal"):
        value = _clamp(vision.get("visual_appeal"))
    elif _has_vision_dimension(vision, "subject_quality"):
        value = _clamp(vision.get("subject_quality"))
    else:
        value = default
    penalty = _defect_penalty(vision, request_context, uncertainty_reasons)
    return _clamp(value - penalty)


def _defect_penalty(
    vision: dict[str, Any],
    request_context: dict[str, Any],
    uncertainty_reasons: list[str],
) -> float:
    category = str(request_context.get("category") or "").lower()
    portrait_like = any(token in category for token in ("portrait", "fashion", "character", "cosplay"))
    if not portrait_like:
        return 0.0
    defects = vision.get("artifact_defects")
    if not isinstance(defects, list):
        return 0.0
    penalty = 0.0
    for defect in defects:
        defect_text = str(defect)
        if defect_text in {"blurred_face", "distorted_face", "extra_fingers"}:
            uncertainty_reasons.append(f"vision_defect_{defect_text}")
            penalty += 0.2
    return min(0.5, penalty)


def _surface_artifact_defects(vision: dict[str, Any], uncertainty_reasons: list[str]) -> None:
    defects = vision.get("artifact_defects")
    if not isinstance(defects, list):
        return
    for defect in defects:
        defect_text = str(defect)
        if defect_text.startswith("weak_"):
            uncertainty_reasons.append(f"vision_defect_{defect_text}")


def _has_vision_dimension(vision: dict[str, Any], key: str) -> bool:
    return key in vision and vision.get(key) is not None


def _score_key(vision_key: str) -> str:
    if vision_key == "visual_appeal":
        return "aesthetic_fit"
    return vision_key


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
