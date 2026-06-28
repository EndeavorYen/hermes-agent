from __future__ import annotations

from typing import Any


def build_vision_judge_observation(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    reference_adherence = _dimension(source, "reference_adherence", 0.5)
    face_quality = _dimension(source, "face_quality", 0.5)
    subject_quality = _dimension(source, "subject_quality", face_quality)
    visual_appeal = _dimension(source, "visual_appeal", 0.5)
    glamour_impact = _dimension(source, "glamour_impact", visual_appeal)
    composition = _dimension(source, "composition", 0.5)
    pose_composition = _dimension(source, "pose_composition", composition)
    pose_novelty = _dimension(source, "pose_novelty", 0.5)
    fashion_material_quality = _dimension(
        source,
        "fashion_material_quality",
        _dimension(source, "stocking_quality", _dimension(source, "tights_quality", 0.5)),
    )
    role_dimensions = _role_dimensions(source)
    aspect_integrity = _optional_dimension(source, "aspect_integrity")
    motion_quality = _optional_dimension(source, "motion_quality")

    defects: list[str] = []
    if reference_adherence < 0.5:
        defects.append("reference_identity_drift")
    if role_dimensions.get("character_identity_adherence", 1.0) < 0.5:
        defects.append("reference_identity_drift")
    if role_dimensions.get("pose_composition_adherence", 1.0) < 0.5:
        defects.append("pose_composition_weak")
    if face_quality < 0.5:
        defects.append("face_quality_low")
    if subject_quality < 0.5:
        defects.append("subject_quality_low")
    if visual_appeal < 0.5:
        defects.append("visual_appeal_low")
    if glamour_impact < 0.5:
        defects.append("glamour_impact_low")
    if composition < 0.45:
        defects.append("composition_weak")
    if pose_composition < 0.45:
        defects.append("pose_composition_weak")
    if fashion_material_quality < 0.5:
        defects.append("stockings_quality_low")
    if aspect_integrity is not None and aspect_integrity < 0.5:
        defects.append("weak_aspect_integrity")
    if motion_quality is not None and motion_quality < 0.4:
        defects.append("weak_motion_or_duration_evidence")
    defects.extend(_explicit_artifact_defects(source.get("artifact_defects")))

    confidence = sum(
        (
            reference_adherence,
            subject_quality,
            face_quality,
            visual_appeal,
            glamour_impact,
            composition,
            pose_composition,
        )
    ) / 7
    observation = {
        "reference_adherence": round(reference_adherence, 4),
        "subject_quality": round(subject_quality, 4),
        "face_quality": round(face_quality, 4),
        "visual_appeal": round(visual_appeal, 4),
        "glamour_impact": round(glamour_impact, 4),
        "composition": round(composition, 4),
        "pose_composition": round(pose_composition, 4),
        "pose_novelty": round(pose_novelty, 4),
        "fashion_material_quality": round(fashion_material_quality, 4),
        "confidence": round(_clamp(confidence), 4),
        "artifact_defects": list(dict.fromkeys(defects)),
        "evidence": {
            "source": "vision_judge",
            "summary": "privacy-safe visual observation",
        },
    }
    observation.update(role_dimensions)
    if aspect_integrity is not None:
        observation["aspect_integrity"] = round(aspect_integrity, 4)
    if motion_quality is not None:
        observation["motion_quality"] = round(motion_quality, 4)
    return observation


def _role_dimensions(source: dict[str, Any]) -> dict[str, float]:
    dimensions: dict[str, float] = {}
    for key in (
        "character_identity_adherence",
        "identity_adherence",
        "character_adherence",
        "face_identity_adherence",
        "pose_composition_adherence",
        "pose_adherence",
        "composition_adherence",
        "wardrobe_adherence",
        "clothing_adherence",
        "outfit_adherence",
        "style_adherence",
        "art_style_adherence",
        "background_adherence",
        "scene_adherence",
    ):
        if key in source:
            dimensions[key] = round(_clamp(source.get(key)), 4)
    return dimensions


def _dimension(source: dict[str, Any], key: str, default: float) -> float:
    if key not in source:
        return default
    return _clamp(source.get(key))


def _optional_dimension(source: dict[str, Any], key: str) -> float | None:
    if key not in source:
        return None
    return _clamp(source.get(key))


def _explicit_artifact_defects(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))
