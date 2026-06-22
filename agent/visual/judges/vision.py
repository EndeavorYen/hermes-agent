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

    confidence = sum(
        (
            reference_adherence,
            subject_quality,
            visual_appeal,
            composition,
            pose_novelty,
        )
    ) / 5
    return {
        "reference_adherence": round(reference_adherence, 4),
        "subject_quality": round(subject_quality, 4),
        "visual_appeal": round(visual_appeal, 4),
        "composition": round(composition, 4),
        "pose_novelty": round(pose_novelty, 4),
        "confidence": round(_clamp(confidence), 4),
        "artifact_defects": defects,
        "evidence": {
            "source": "vision_judge",
            "summary": "privacy-safe visual observation",
        },
    }


def _dimension(source: dict[str, Any], key: str, default: float) -> float:
    if key not in source:
        return default
    return _clamp(source.get(key))


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))
