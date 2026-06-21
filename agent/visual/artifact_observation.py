from __future__ import annotations

from typing import Any


def build_artifact_observation(candidate: dict[str, Any]) -> dict[str, Any]:
    scores = candidate.get("scores") if isinstance(candidate.get("scores"), dict) else {}
    hard_gate = candidate.get("hard_gate") if isinstance(candidate.get("hard_gate"), dict) else {}
    kind = str(candidate.get("kind") or "")
    aspect = _clamp(scores.get("aspect_match", 0.5))
    resolution = _clamp(scores.get("resolution", 0.5))
    final_score = _clamp(scores.get("final_score", 0.5))
    motion = _clamp(scores.get("duration", 1.0 if kind != "video" else 0.5))
    delivery = 1.0 if hard_gate.get("delivery_possible") is True else 0.5
    defects = _defects(kind=kind, aspect=aspect, resolution=resolution, motion=motion, delivery=delivery)
    confidence = _clamp((aspect + resolution + final_score + delivery) / 4)
    if kind == "video":
        confidence = _clamp((confidence + motion) / 2)
    return {
        "reference_adherence": 0.5,
        "composition": round(_clamp(aspect * 0.65 + resolution * 0.35), 4),
        "visual_appeal": round(_clamp(resolution * 0.55 + final_score * 0.45), 4),
        "aspect_integrity": round(aspect, 4),
        "motion_quality": round(motion, 4),
        "confidence": round(confidence, 4),
        "artifact_defects": defects,
        "evidence": {
            "source": "artifact_observation",
            "summary": f"{kind or 'artifact'} metadata quality observation",
        },
    }


def _defects(
    *,
    kind: str,
    aspect: float,
    resolution: float,
    motion: float,
    delivery: float,
) -> list[str]:
    defects: list[str] = []
    if aspect < 0.6:
        defects.append("weak_aspect_integrity")
    if resolution < 0.4:
        defects.append("weak_resolution_evidence")
    if kind == "video" and motion < 0.4:
        defects.append("weak_motion_or_duration_evidence")
    if delivery < 1.0:
        defects.append("delivery_readiness_uncertain")
    return defects


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))
