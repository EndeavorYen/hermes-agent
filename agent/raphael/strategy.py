from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.raphael.appraisal import RaphaelAppraisal


@dataclass(frozen=True)
class RaphaelStrategy:
    strategy_id: str
    label: str
    route: str
    expected_benefit: str
    risk: str
    required_proofs: tuple[str, ...]
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_proofs", tuple(self.required_proofs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "label": self.label,
            "route": self.route,
            "expected_benefit": self.expected_benefit,
            "risk": self.risk,
            "required_proofs": list(self.required_proofs),
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class RaphaelStrategySet:
    candidates: tuple[RaphaelStrategy, ...]
    selected_strategy_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))

    @property
    def selected(self) -> RaphaelStrategy:
        for strategy in self.candidates:
            if strategy.strategy_id == self.selected_strategy_id:
                return strategy
        return self.candidates[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selected_strategy_id": self.selected_strategy_id,
            "selected": self.selected.to_dict(),
        }


def simulate_raphael_strategies(appraisal: RaphaelAppraisal) -> RaphaelStrategySet:
    if appraisal.blockers:
        blocked = RaphaelStrategy(
            strategy_id="blocked",
            label="blocked",
            route="ask_precise_clarification",
            expected_benefit="avoid_wrong_action",
            risk="low",
            required_proofs=appraisal.success_conditions,
            blocked_reason=appraisal.blockers[0],
        )
        return RaphaelStrategySet(candidates=(blocked,), selected_strategy_id="blocked")
    fast = RaphaelStrategy(
        strategy_id="fast",
        label="fast",
        route="minimal_direct_action",
        expected_benefit="shortest_path",
        risk="medium",
        required_proofs=appraisal.success_conditions[:1],
    )
    safe = RaphaelStrategy(
        strategy_id="safe",
        label="safe",
        route="plan_execute_verify",
        expected_benefit="best_reliability",
        risk="low",
        required_proofs=appraisal.success_conditions,
    )
    quality = RaphaelStrategy(
        strategy_id="quality",
        label="quality",
        route="multi_pass_review_and_repair",
        expected_benefit="highest_output_quality",
        risk="medium",
        required_proofs=tuple(
            dict.fromkeys((*appraisal.success_conditions, "hostile_review"))
        ),
    )
    return RaphaelStrategySet(
        candidates=(fast, safe, quality),
        selected_strategy_id=(
            "quality"
            if appraisal.task_type in {"visual_generation", "visual_edit"}
            else "safe"
        ),
    )


__all__ = [
    "RaphaelStrategy",
    "RaphaelStrategySet",
    "simulate_raphael_strategies",
]
