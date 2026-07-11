from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from agent.raphael.config import raphael_effective_enabled
from agent.raphael.control import (
    RaphaelEvidenceDecision,
    RaphaelGoalDecision,
    RaphaelRouteDecision,
    build_raphael_control_decision,
)
from agent.raphael.runtime_contract import (
    RaphaelRuntimeContract,
    RaphaelTurnOrigin,
    resolve_raphael_turn_origin,
)
from agent.raphael.state import read_active_mission, record_turn_decision


@dataclass(frozen=True)
class RaphaelTurnDecision:
    turn_id: str
    origin: RaphaelTurnOrigin
    mission_id: str | None
    mode: str
    goal: RaphaelGoalDecision
    route: RaphaelRouteDecision
    evidence: RaphaelEvidenceDecision
    next_action: str
    reference_resolution: str
    clarification_question: str | None
    confidence: float
    completion_policy: str
    runtime_contract: RaphaelRuntimeContract

    @property
    def target_artifact(self) -> str:
        return self.goal.target_artifact

    @property
    def required_proofs(self) -> tuple[str, ...]:
        return self.evidence.required_proofs

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "origin": self.origin.value,
            "mission_id": self.mission_id,
            "mode": self.mode,
            "goal": self.goal.to_dict(),
            "route": self.route.to_dict(),
            "evidence": self.evidence.to_dict(),
            "next_action": self.next_action,
            "reference_resolution": self.reference_resolution,
            "clarification_question": self.clarification_question,
            "confidence": self.confidence,
            "completion_policy": self.completion_policy,
            "runtime_contract": self.runtime_contract.to_dict(),
        }


def prepare_raphael_turn(
    *,
    turn_id: str,
    origin: str | RaphaelTurnOrigin,
    runtime_contract: Mapping[str, Any] | RaphaelRuntimeContract,
    config: Mapping[str, Any] | None,
    user_message: Any,
    attachments: Sequence[str] | None = None,
    conversation_history: Sequence[Mapping[str, Any]] | None = None,
    visual_plan: Mapping[str, Any] | None = None,
) -> RaphaelTurnDecision | None:
    resolved_origin = resolve_raphael_turn_origin(explicit_origin=origin)
    if resolved_origin is not RaphaelTurnOrigin.FOREGROUND:
        return None
    if not raphael_effective_enabled(config):
        return None
    contract = (
        runtime_contract
        if isinstance(runtime_contract, RaphaelRuntimeContract)
        else RaphaelRuntimeContract.from_mapping(runtime_contract)
    )
    mission = read_active_mission()
    decision = _build_raphael_turn_decision(
        turn_id=str(turn_id),
        origin=resolved_origin,
        runtime_contract=contract,
        user_message=user_message,
        mission=mission,
        attachments=attachments,
        conversation_history=conversation_history,
        visual_plan=visual_plan,
    )
    record_turn_decision(decision.to_dict())
    return decision


def replay_raphael_turn(
    *,
    turn_id: str,
    runtime_contract: Mapping[str, Any] | RaphaelRuntimeContract,
    user_message: Any,
    mission: Any | None = None,
    attachments: Sequence[str] | None = None,
    conversation_history: Sequence[Mapping[str, Any]] | None = None,
    visual_plan: Mapping[str, Any] | None = None,
) -> RaphaelTurnDecision:
    """Run the production decision kernel without mutating live runtime state."""
    contract = (
        runtime_contract
        if isinstance(runtime_contract, RaphaelRuntimeContract)
        else RaphaelRuntimeContract.from_mapping(runtime_contract)
    )
    return _build_raphael_turn_decision(
        turn_id=str(turn_id),
        origin=RaphaelTurnOrigin.REPLAY,
        runtime_contract=contract,
        user_message=user_message,
        mission=mission,
        attachments=attachments,
        conversation_history=conversation_history,
        visual_plan=visual_plan,
    )


def _build_raphael_turn_decision(
    *,
    turn_id: str,
    origin: RaphaelTurnOrigin,
    runtime_contract: RaphaelRuntimeContract,
    user_message: Any,
    mission: Any | None,
    attachments: Sequence[str] | None,
    conversation_history: Sequence[Mapping[str, Any]] | None,
    visual_plan: Mapping[str, Any] | None,
) -> RaphaelTurnDecision:
    control = build_raphael_control_decision(
        user_message,
        active_mission=mission,
        attachments=attachments,
        conversation_history=conversation_history,
        visual_plan=visual_plan,
    )
    route = _route_with_runtime_contract(control.route, runtime_contract)
    return RaphaelTurnDecision(
        turn_id=turn_id,
        origin=origin,
        mission_id=mission.mission_id if mission is not None else None,
        mode=control.mode,
        goal=control.goal,
        route=route,
        evidence=control.evidence,
        next_action=control.next_action,
        reference_resolution=control.reference_resolution,
        clarification_question=control.clarification_question,
        confidence=control.confidence,
        completion_policy=_completion_policy(control.mode),
        runtime_contract=runtime_contract,
    )


def render_raphael_turn_decision_context(decision: RaphaelTurnDecision) -> str:
    proofs = ", ".join(decision.required_proofs) or "none"
    return "\n".join(
        [
            "Raphael Canonical Turn Decision (internal):",
            f"turn_id: {decision.turn_id}",
            f"mode: {decision.mode}",
            f"completion_policy: {decision.completion_policy}",
            f"target_artifact: {decision.target_artifact}",
            f"required_proofs: {proofs}",
            f"next_action: {decision.next_action}",
            "runtime: "
            f"{decision.runtime_contract.base_provider}/"
            f"{decision.runtime_contract.base_model}",
        ]
    )


def _route_with_runtime_contract(
    route: RaphaelRouteDecision,
    contract: RaphaelRuntimeContract,
) -> RaphaelRouteDecision:
    media_provider = route.visual_media_provider
    media_model = route.visual_media_model
    if route.visual_media_provider_source != "prompt_override":
        media_provider = contract.image_provider or media_provider
        media_model = contract.image_model or media_model
    return replace(
        route,
        base_llm_provider=contract.base_provider or route.base_llm_provider,
        base_llm_model=contract.base_model or route.base_llm_model,
        visual_agent_llm_provider=(
            contract.visual_planner_provider or route.visual_agent_llm_provider
        ),
        visual_agent_llm_model=(
            contract.visual_planner_model or route.visual_agent_llm_model
        ),
        visual_media_provider=media_provider,
        visual_media_model=media_model,
    )


def _completion_policy(mode: str) -> str:
    if mode in {"tool_task", "learn_skill"}:
        return "mutation"
    if mode.startswith("visual_agent"):
        return "visual"
    if mode == "needs_clarification":
        return "blocked"
    return "informational"


__all__ = [
    "RaphaelTurnDecision",
    "prepare_raphael_turn",
    "replay_raphael_turn",
    "render_raphael_turn_decision_context",
]
