from __future__ import annotations

from typing import Any


def build_vision_judge_observation(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    reference_adherence = _dimension(source, "reference_adherence", 0.5)
    subject_quality = _dimension(source, "face_quality", _dimension(source, "subject_quality", 0.5))
    visual_appeal = _dimension(source, "visual_appeal", 0.5)
    composition = _dimension(source, "composition", 0.5)
    pose_novelty = _dimension(source, "pose_novelty", 0.5)
    stocking_quality = _dimension(source, "stocking_quality", _dimension(source, "tights_quality", 0.5))
    aspect_integrity = _optional_dimension(source, "aspect_integrity")
    motion_quality = _optional_dimension(source, "motion_quality")

    defects: list[str] = []
    if reference_adherence < 0.5:
        defects.append("reference_identity_drift")
    if subject_quality < 0.5:
        defects.append("face_quality_low")
    if visual_appeal < 0.5:
        defects.append("visual_appeal_low")
    if composition < 0.45:
        defects.append("composition_weak")
    if stocking_quality < 0.5:
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
            visual_appeal,
            composition,
            pose_novelty,
        )
    ) / 5
    observation = {
        "reference_adherence": round(reference_adherence, 4),
        "subject_quality": round(subject_quality, 4),
        "visual_appeal": round(visual_appeal, 4),
        "composition": round(composition, 4),
        "pose_novelty": round(pose_novelty, 4),
        "confidence": round(_clamp(confidence), 4),
        "artifact_defects": list(dict.fromkeys(defects)),
        "evidence": {
            "source": "vision_judge",
            "summary": "privacy-safe visual observation",
        },
    }
    if aspect_integrity is not None:
        observation["aspect_integrity"] = round(aspect_integrity, 4)
    if motion_quality is not None:
        observation["motion_quality"] = round(motion_quality, 4)
    return observation


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
