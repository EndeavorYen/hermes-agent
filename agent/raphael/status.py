from __future__ import annotations

from datetime import datetime, timezone

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
                f"- {proposal.proposal_id} [{risk}] {proposal.summary} ({approval})"
            )
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


__all__ = ["active_cards", "render_status"]
