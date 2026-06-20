"""Self-scoring primitives for visual agent outcomes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class VisualReward:
    provider_health: float
    artifact_quality: float
    delivery_health: float
    preference_score: float
    overall_score: float
    confidence: float
    components: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def score_visual_outcome(evidence: Dict[str, Any]) -> VisualReward:
    data = dict(evidence or {})
    provider_health = _score_provider_health(data)
    artifact_quality = _score_artifact_quality(data)
    delivery_health = _score_delivery_health(data)
    preference_score = _score_preference(data)
    components = {
        "provider_health": provider_health,
        "artifact_quality": artifact_quality,
        "delivery_health": delivery_health,
        "preference_score": preference_score,
    }
    overall_score = round(
        (0.25 * provider_health)
        + (0.35 * artifact_quality)
        + (0.25 * delivery_health)
        + (0.15 * preference_score),
        4,
    )
    confidence = _score_confidence(data)
    return VisualReward(
        provider_health=provider_health,
        artifact_quality=artifact_quality,
        delivery_health=delivery_health,
        preference_score=preference_score,
        overall_score=_clamp(overall_score),
        confidence=confidence,
        components=components,
    )


def _score_provider_health(data: Dict[str, Any]) -> float:
    if "provider_health" in data:
        return _clamp(data.get("provider_health"))
    return 0.0 if _clean(data.get("provider_error_type")) else 1.0


def _score_artifact_quality(data: Dict[str, Any]) -> float:
    if "artifact_quality" in data:
        return _clamp(data.get("artifact_quality"))
    if data.get("artifact_valid") is False:
        return 0.0
    for key in ("composition_score", "quality_score", "score"):
        if key in data:
            return _clamp(data.get(key))
    return 1.0 if data.get("artifact_valid") is True else 0.5


def _score_delivery_health(data: Dict[str, Any]) -> float:
    if "delivery_health" in data:
        return _clamp(data.get("delivery_health"))
    if "delivered" in data:
        return 1.0 if bool(data.get("delivered")) else 0.0
    return 0.5


def _score_preference(data: Dict[str, Any]) -> float:
    if "preference_score" in data:
        return _clamp(data.get("preference_score"))
    polarity = data.get("feedback_polarity")
    if polarity is None:
        return 0.5
    try:
        return _clamp((float(polarity) + 1.0) / 2.0)
    except (TypeError, ValueError):
        return 0.5


def _score_confidence(data: Dict[str, Any]) -> float:
    if "confidence" in data:
        return _clamp(data.get("confidence"))
    evidence_count = 0
    if "provider_health" in data or "provider_error_type" in data:
        evidence_count += 1
    if (
        "artifact_quality" in data
        or "artifact_valid" in data
        or "composition_score" in data
        or "quality_score" in data
        or "score" in data
    ):
        evidence_count += 1
    if "delivery_health" in data or "delivered" in data:
        evidence_count += 1
    if "preference_score" in data or data.get("feedback_polarity") is not None:
        evidence_count += 1
    return _clamp(evidence_count / 4.0)


def _clamp(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return round(max(0.0, min(1.0, number)), 4)


def _clean(value: Any) -> str:
    return str(value or "").strip()
