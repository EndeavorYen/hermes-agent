from __future__ import annotations

from typing import Any


NUMERIC_KEYS = {
    "subject_quality",
    "face_quality",
    "reference_adherence",
    "edit_anchor_adherence",
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
    "composition",
    "pose_composition",
    "visual_appeal",
    "glamour_impact",
    "fashion_material_quality",
    "product_appeal",
    "aspect_integrity",
    "motion_quality",
    "confidence",
}

SAFE_EVIDENCE_KEYS = {
    "summary",
    "observations",
    "defects",
    "reason",
    "source",
}


def normalize_vision_observation(observation: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    if not isinstance(observation, dict):
        observation = {}

    for key in NUMERIC_KEYS:
        if key in observation:
            normalized[key] = _clamp(observation.get(key))

    defects = observation.get("artifact_defects")
    normalized["artifact_defects"] = [
        str(item)
        for item in defects
        if isinstance(item, str) and item.strip()
    ] if isinstance(defects, list) else []

    normalized["confidence"] = _clamp(observation.get("confidence", normalized.get("confidence", 0.0)))
    normalized["evidence"] = _safe_evidence(observation.get("evidence"))
    return normalized


def empty_vision_observation(reason: str) -> dict[str, Any]:
    safe_reason = str(reason or "unavailable").strip() or "unavailable"
    return {
        "confidence": 0.0,
        "artifact_defects": [],
        "evidence": {"reason": safe_reason},
    }


def _safe_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in SAFE_EVIDENCE_KEYS:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            safe[key] = item.strip()
        elif isinstance(item, list):
            safe[key] = [str(part) for part in item if isinstance(part, str) and part.strip()]
    return safe


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))
