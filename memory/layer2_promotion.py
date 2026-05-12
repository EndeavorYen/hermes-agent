"""Promotion policy for moving Layer-2 candidates into bounded L1 memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class L1Pressure:
    current_chars: int
    char_limit: int

    @property
    def usage_ratio(self) -> float:
        if self.char_limit <= 0:
            return 1.0
        return max(0.0, self.current_chars / self.char_limit)


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    reason: str
    recommended_action: str


def evaluate_promotion(
    candidate: dict[str, Any],
    *,
    pressure: L1Pressure,
    min_net_support: int = 3,
    max_l1_usage_ratio: float = 0.85,
) -> PromotionDecision:
    status = str(candidate.get("status") or "active").strip().lower()
    support = int(candidate.get("support_count") or 0)
    contradict = int(candidate.get("contradict_count") or 0)
    net_support = support - contradict
    if status != "active" or net_support < min_net_support:
        return PromotionDecision(False, "not_recallable_or_low_net_support", "keep_in_layer2")
    if pressure.usage_ratio >= max_l1_usage_ratio:
        return PromotionDecision(False, "l1_pressure_too_high", "keep_in_layer2")
    return PromotionDecision(True, "high_confidence_and_l1_room", "promote_to_l1")
