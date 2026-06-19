"""Bounded loop policy for Visual Agent Mode."""

from __future__ import annotations

from dataclasses import dataclass

from agent.visual.agent_mode.types import VisualMission


@dataclass(frozen=True)
class VisualLoopPolicy:
    low_confidence_threshold: float = 0.55
    auto_select_threshold: float = 0.70

    def decide(
        self,
        mission: VisualMission,
        *,
        candidate_count: int,
        accepted_count: int,
        failure_count: int,
        confidence: float,
    ) -> str:
        if candidate_count < mission.candidate_budget:
            return "generate_image"
        if failure_count >= max(3, mission.candidate_budget) and accepted_count == 0:
            return "fail"
        if confidence < self.low_confidence_threshold:
            return "ask_user"
        if (
            mission.autonomy_level >= 2
            and accepted_count > 0
            and confidence >= self.auto_select_threshold
        ):
            return "select_images"
        return "ask_user"


def decide_next_action(
    mission: VisualMission,
    *,
    candidate_count: int,
    accepted_count: int,
    failure_count: int,
    confidence: float,
) -> str:
    return VisualLoopPolicy().decide(
        mission,
        candidate_count=candidate_count,
        accepted_count=accepted_count,
        failure_count=failure_count,
        confidence=confidence,
    )
