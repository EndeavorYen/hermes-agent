from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VisualScoreBreakdown:
    dimensions: dict[str, float]
    weights: dict[str, float]
    final_score: float
    confidence: float | None = None
    metadata: dict[str, Any] | None = None


def combine_weighted_scores(scores: dict[str, float], weights: dict[str, float]) -> float:
    weighted_total = 0.0
    weight_total = 0.0
    for dimension, weight in weights.items():
        numeric_weight = _coerce_float(weight)
        if numeric_weight <= 0:
            continue
        weighted_total += _clamp_score(scores.get(dimension, 0.0)) * numeric_weight
        weight_total += numeric_weight
    if weight_total <= 0:
        return 0.0
    return round(weighted_total / weight_total, 4)


def _clamp_score(value: Any) -> float:
    numeric = _coerce_float(value)
    return max(0.0, min(1.0, numeric))


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
