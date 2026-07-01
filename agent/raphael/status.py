from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from agent.raphael.evolution import sanitize_evolution_text
from agent.raphael.models import RaphaelState, StatusCard


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def active_cards(
    state: RaphaelState, *, now: datetime | None = None
) -> list[StatusCard]:
    cutoff = _ensure_utc(now) if now is not None else _utc_now()
    return [card for card in state.status_cards if card.expires_at > cutoff]


def render_status(
    state: RaphaelState, *, now: datetime | None = None, max_cards: int = 20
) -> str:
    cards = active_cards(state, now=now)[:max(0, max_cards)]
    pending_proposals = [
        proposal
        for proposal in state.action_proposals
        if proposal.status == "pending"
    ]

    lines = [
        "Raphael Advisor",
        "Mode: read-only Advisor MVP.",
        "",
        "Status Cards:",
    ]

    if cards:
        for card in cards:
            lines.extend(
                [
                    f"- [{card.severity}] {card.title}",
                    f"  Summary: {card.summary}",
                    f"  Source: {card.source}",
                    f"  Confidence: {card.confidence:.2f}",
                ]
            )
    else:
        lines.append("No active status cards.")

    lines.extend(["", "Pending Action Proposals:"])
    if pending_proposals:
        for proposal in pending_proposals:
            risk = proposal.risk.value
            approval = (
                "requires approval"
                if proposal.requires_approval
                else "auto-allow"
            )
            lines.append(
                f"- {proposal.proposal_id} [{risk}] "
                f"{sanitize_evolution_text(proposal.summary)} ({approval})"
            )
            lines.extend(_render_proposal_metadata(proposal.proposal_id, proposal.metadata))
    else:
        lines.append("No pending action proposals.")

    lines.extend(
        [
            "",
            "Read-only safety: Raphael Advisor does not write memory, edit skills, "
            "change cron, install tools, or send public messages.",
        ]
    )
    return "\n".join(lines)


def _render_proposal_metadata(
    proposal_id: str,
    metadata: Mapping[str, Any] | None,
) -> list[str]:
    if not isinstance(metadata, Mapping):
        return []

    lines: list[str] = []
    affected_capability = metadata.get("affected_capability")
    if affected_capability:
        lines.append(f"  Affected capability: {_public_text(affected_capability)}")

    confidence = metadata.get("confidence")
    if isinstance(confidence, int | float):
        lines.append(f"  Confidence: {confidence:.2f}")

    promotion_gate = metadata.get("promotion_gate")
    if promotion_gate:
        lines.append(f"  Promotion gate: {_public_text(promotion_gate)}")

    rollback_condition = metadata.get("rollback_condition")
    if rollback_condition:
        lines.append(f"  Rollback: {_public_text(rollback_condition)}")

    if metadata.get("approval_required"):
        lines.append(f"  Approve: hermes raphael proposal approve {proposal_id}")
        lines.append(f"  Reject: hermes raphael proposal reject {proposal_id}")

    rollout_plan = metadata.get("rollout_plan")
    if isinstance(rollout_plan, Mapping):
        manual_steps = rollout_plan.get("manual_steps")
        if isinstance(manual_steps, Sequence) and not isinstance(
            manual_steps, (str, bytes, bytearray)
        ):
            for step in manual_steps:
                lines.append(f"  Manual step: {_public_text(step)}")

    return lines


def _public_text(value: Any) -> str:
    return sanitize_evolution_text(value)


__all__ = ["active_cards", "render_status"]
