from __future__ import annotations

from typing import Any

from agent.visual.judges.vision_observation import normalize_vision_observation


VERSION = "visual_quality_judge.v0.1"
ROLE_ADHERENCE_THRESHOLD = 0.5


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
        if request_context.get("has_reference_image"):
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
        _surface_artifact_defects(vision, uncertainty_reasons, request_context=request_context)
    else:
        aesthetic_fit = _aesthetic_fit(deterministic_scores)
        composition = _composition(deterministic_scores)
        aspect_integrity = _clamp(deterministic_scores.get("aspect_match", 0.5))
        motion_quality = _motion_quality(candidate, deterministic_scores)
    reference_adherence = _reference_adherence_with_role_scores(
        reference_adherence,
        vision,
        request_context,
        judge_sources,
    )
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
    preference_dimensions = _preference_dimensions(vision, request_context)
    quality_issues = _quality_issues_from_observation(
        vision,
        request_context=request_context,
        candidate_kind=str(candidate.get("kind") or ""),
        preference_dimensions=preference_dimensions,
        uncertainty_reasons=uncertainty_reasons,
    )
    confidence = _confidence(scores=scores, uncertainty_reasons=uncertainty_reasons)
    result = {
        "version": VERSION,
        "scores": {key: round(value, 4) for key, value in scores.items()},
        "quality_issues": quality_issues,
        "confidence": confidence,
        "uncertainty_reasons": sorted(set(uncertainty_reasons)),
        "judge_sources": judge_sources,
    }
    if preference_dimensions:
        result["preference_dimensions"] = preference_dimensions
    return result


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
    elif _portrait_like_context(request_context) and _has_vision_dimension(vision, "subject_quality"):
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
    if not _portrait_like_context(request_context):
        return 0.0
    defects = vision.get("artifact_defects")
    if not isinstance(defects, list):
        return 0.0
    penalty = 0.0
    for defect in defects:
        defect_text = str(defect)
        if defect_text in {"blurred_face", "distorted_face", "extra_fingers", "face_quality_low"}:
            uncertainty_reasons.append(f"vision_defect_{defect_text}")
            penalty += 0.2
    return min(0.5, penalty)


def _surface_artifact_defects(
    vision: dict[str, Any],
    uncertainty_reasons: list[str],
    *,
    request_context: dict[str, Any],
) -> None:
    defects = vision.get("artifact_defects")
    if not isinstance(defects, list):
        return
    portrait_like = _portrait_like_context(request_context)
    has_reference_image = request_context.get("has_reference_image") is True
    for defect in defects:
        defect_text = str(defect)
        if defect_text == "reference_identity_drift" and not has_reference_image:
            continue
        if defect_text == "face_quality_low" and not portrait_like:
            continue
        if defect_text.startswith("weak_") or defect_text in {
            "aspect_mismatch",
            "duration_mismatch",
            "distorted_anatomy",
            "guide_artifact_contamination",
            "melted_or_wavy_contours",
            "missing_video_dimensions",
            "missing_video_duration",
            "reference_identity_drift",
            "reference_overcopy",
            "visual_appeal_low",
            "composition_weak",
        }:
            uncertainty_reasons.append(f"vision_defect_{defect_text}")


def _quality_issues_from_observation(
    vision: dict[str, Any],
    *,
    request_context: dict[str, Any],
    candidate_kind: str,
    preference_dimensions: dict[str, float] | None = None,
    uncertainty_reasons: list[str] | None = None,
) -> list[str]:
    issues: list[str] = []
    for issue in _reference_role_quality_issues(vision, request_context):
        if issue not in issues:
            issues.append(issue)
    if _reference_role_evidence_missing(vision, request_context):
        issues.append("reference_role_evidence_missing")
        if uncertainty_reasons is not None:
            uncertainty_reasons.append("reference_role_evidence_missing")
    defects = vision.get("artifact_defects")
    if not isinstance(defects, list):
        return issues
    portrait_like = _portrait_like_context(request_context)
    has_reference_image = request_context.get("has_reference_image") is True
    video_like = candidate_kind == "video"
    defect_set = {str(defect) for defect in defects}
    for defect in defects:
        defect_text = str(defect)
        issue = _issue_for_defect(defect_text)
        if issue == "reference_identity_drift" and not has_reference_image:
            continue
        if issue in {"aspect_integrity_bad", "motion_bad", "video_metadata_missing"} and not video_like:
            continue
        if issue == "aspect_integrity_bad" and "missing_video_dimensions" in defect_set:
            continue
        if (
            issue == "motion_bad"
            and defect_text in {"weak_motion_evidence", "weak_motion_or_duration_evidence"}
            and "missing_video_duration" in defect_set
        ):
            continue
        if (
            issue
            in {
                "subject_not_attractive",
                "face_unnatural",
                "not_beautiful",
                "not_glamorous",
                "stockings_bad",
            }
            and not portrait_like
        ):
            continue
        if issue == "composition_bad" and defect_text == "pose_composition_weak" and not portrait_like:
            continue
        if issue and issue not in issues:
            issues.append(issue)
    for issue in _preference_dimension_issues(
        preference_dimensions or {},
        uncertainty_reasons=uncertainty_reasons,
    ):
        if issue not in issues:
            issues.append(issue)
    return issues


def _reference_adherence_with_role_scores(
    reference_adherence: float,
    vision: dict[str, Any],
    request_context: dict[str, Any],
    judge_sources: dict[str, str],
) -> float:
    role_scores = _reference_role_scores(vision, request_context)
    if not role_scores:
        return reference_adherence
    for role_hint in role_scores:
        judge_sources[f"{role_hint}_adherence"] = "vision"
    values = list(role_scores.values())
    averaged = sum(values) / len(values)
    adjusted = max(reference_adherence, averaged)
    weakest = min(values)
    if weakest < ROLE_ADHERENCE_THRESHOLD:
        adjusted = min(adjusted, weakest)
    return _clamp(adjusted)


def _reference_role_quality_issues(vision: dict[str, Any], request_context: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    role_scores = _reference_role_scores(vision, request_context)
    if role_scores.get("character_identity", 1.0) < ROLE_ADHERENCE_THRESHOLD:
        issues.append("reference_identity_drift")
    if role_scores.get("pose_composition", 1.0) < ROLE_ADHERENCE_THRESHOLD:
        issues.append("composition_bad")
    return issues


def _reference_role_scores(vision: dict[str, Any], request_context: dict[str, Any]) -> dict[str, float]:
    binding = request_context.get("reference_binding")
    if not isinstance(binding, dict):
        return {}
    scores: dict[str, float] = {}
    for item in binding.get("reference_order") or []:
        if not isinstance(item, dict):
            continue
        role_hint = str(item.get("role_hint") or "").strip()
        if not role_hint or role_hint == "visual_reference" or role_hint in scores:
            continue
        value = _role_evidence_score(vision, role_hint)
        if value is not None:
            scores[role_hint] = value
    return scores


def _role_evidence_score(vision: dict[str, Any], role_hint: str) -> float | None:
    evidence_keys = _role_evidence_keys(role_hint)
    if not evidence_keys:
        return None
    primary_key = evidence_keys[0]
    if _has_vision_dimension(vision, primary_key):
        return _clamp(vision.get(primary_key))
    values = [
        _clamp(vision.get(key))
        for key in evidence_keys[1:]
        if _has_vision_dimension(vision, key)
    ]
    if not values:
        return None
    return max(values)


def _reference_role_evidence_missing(vision: dict[str, Any], request_context: dict[str, Any]) -> bool:
    binding = request_context.get("reference_binding")
    if not isinstance(binding, dict):
        return False
    role_hints = {
        str(item.get("role_hint") or "").strip()
        for item in binding.get("reference_order") or []
        if isinstance(item, dict)
    }
    role_hints.discard("")
    role_hints.discard("visual_reference")
    if not role_hints:
        return False
    return not all(_has_role_evidence(vision, role_hint) for role_hint in role_hints)


def _has_role_evidence(vision: dict[str, Any], role_hint: str) -> bool:
    return any(_has_vision_dimension(vision, key) for key in _role_evidence_keys(role_hint))


def _role_evidence_keys(role_hint: str) -> tuple[str, ...]:
    evidence_keys = {
        "character_identity": (
            "character_identity_adherence",
            "identity_adherence",
            "character_adherence",
            "face_identity_adherence",
        ),
        "pose_composition": (
            "pose_composition_adherence",
            "pose_adherence",
            "composition_adherence",
        ),
        "edit_anchor": (
            "edit_anchor_adherence",
            "previous_output_adherence",
            "image_preservation",
            "reference_adherence",
        ),
        "wardrobe": (
            "wardrobe_adherence",
            "clothing_adherence",
            "outfit_adherence",
        ),
        "style": (
            "style_adherence",
            "art_style_adherence",
        ),
        "background": (
            "background_adherence",
            "scene_adherence",
        ),
    }
    return evidence_keys.get(role_hint, ())


def _preference_dimensions(vision: dict[str, Any], request_context: dict[str, Any]) -> dict[str, float]:
    if not _portrait_like_context(request_context):
        return {}
    dimensions: dict[str, float] = {}
    mapping = {
        "subject_beauty": "subject_quality",
        "face_naturalness": "face_quality",
        "glamour_impact": "glamour_impact",
        "fashion_material_quality": "fashion_material_quality",
        "pose_composition": "pose_composition",
    }
    for dimension, vision_key in mapping.items():
        if _has_vision_dimension(vision, vision_key):
            dimensions[dimension] = round(_clamp(vision.get(vision_key)), 4)
    return dimensions


def _preference_dimension_issues(
    dimensions: dict[str, float],
    *,
    uncertainty_reasons: list[str] | None,
) -> list[str]:
    issues: list[str] = []
    issue_map = {
        "subject_beauty": "subject_not_attractive",
        "face_naturalness": "face_unnatural",
        "glamour_impact": "not_glamorous",
        "fashion_material_quality": "stockings_bad",
        "pose_composition": "composition_bad",
    }
    for dimension, score in dimensions.items():
        if score >= 0.5:
            continue
        issue = issue_map.get(dimension)
        if issue:
            issues.append(issue)
        if uncertainty_reasons is not None:
            uncertainty_reasons.append(f"preference_dimension_{dimension}_low")
    return issues


def _issue_for_defect(defect: str) -> str | None:
    return {
        "blurred_face": "subject_not_attractive",
        "distorted_face": "subject_not_attractive",
        "face_quality_low": "subject_not_attractive",
        "face_unnatural": "face_unnatural",
        "visual_appeal_low": "not_beautiful",
        "glamour_impact_low": "not_glamorous",
        "stocking_quality_low": "stockings_bad",
        "stockings_quality_low": "stockings_bad",
        "bad_stockings": "stockings_bad",
        "composition_weak": "composition_bad",
        "pose_composition_weak": "composition_bad",
        "guide_artifact_contamination": "composition_bad",
        "melted_or_wavy_contours": "composition_bad",
        "distorted_anatomy": "composition_bad",
        "candidate_grid_layout": "source_frame_grid",
        "contact_sheet_layout": "source_frame_grid",
        "collage_layout": "source_frame_grid",
        "split_screen_layout": "source_frame_grid",
        "multi_panel_layout": "source_frame_grid",
        "reference_identity_drift": "reference_identity_drift",
        "reference_overcopy": "reference_overcopy",
        "aspect_mismatch": "aspect_integrity_bad",
        "weak_aspect_integrity": "aspect_integrity_bad",
        "duration_mismatch": "motion_bad",
        "weak_motion_evidence": "motion_bad",
        "weak_motion_or_duration_evidence": "motion_bad",
        "missing_video_dimensions": "video_metadata_missing",
        "missing_video_duration": "video_metadata_missing",
    }.get(defect)


def _portrait_like_context(request_context: dict[str, Any]) -> bool:
    category = str(request_context.get("category") or "").lower()
    return any(token in category for token in ("portrait", "fashion", "character", "cosplay"))


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
