from datetime import datetime, timedelta, timezone

from agent.raphael import (
    ActionProposal,
    RaphaelState,
    RiskLevel,
    StatusCard,
)
from agent.raphael.models import STATE_SCHEMA_VERSION


def test_status_card_round_trips_with_utc_iso_datetimes():
    observed_at = datetime(2026, 6, 16, 8, 30, tzinfo=timezone.utc)
    expires_at = observed_at + timedelta(hours=2)
    card = StatusCard(
        card_id="card-1",
        severity=RiskLevel.R1_5,
        title="Market volatility",
        summary="Intraday volatility moved above the advisory threshold.",
        observed_at=observed_at,
        expires_at=expires_at,
        source="market-monitor",
        confidence=0.82,
        evidence_refs=("quote:SPY", "risk:threshold"),
    )

    payload = card.to_dict()

    assert payload == {
        "card_id": "card-1",
        "severity": "R1.5",
        "title": "Market volatility",
        "summary": "Intraday volatility moved above the advisory threshold.",
        "observed_at": "2026-06-16T08:30:00+00:00",
        "expires_at": "2026-06-16T10:30:00+00:00",
        "source": "market-monitor",
        "confidence": 0.82,
        "evidence_refs": ["quote:SPY", "risk:threshold"],
    }
    assert StatusCard.from_dict(payload) == card


def test_r2_action_proposal_requires_approval_and_round_trips_pending_status():
    created_at = datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc)
    proposal = ActionProposal(
        proposal_id="proposal-1",
        action_type="rebalance",
        risk=RiskLevel.R2,
        summary="Trim oversized allocation before market close.",
        evidence_refs=("card-1",),
        created_at=created_at,
    )

    payload = proposal.to_dict()

    assert proposal.requires_approval is True
    assert payload == {
        "proposal_id": "proposal-1",
        "action_type": "rebalance",
        "risk": "R2",
        "summary": "Trim oversized allocation before market close.",
        "evidence_refs": ["card-1"],
        "created_at": "2026-06-16T09:00:00+00:00",
        "status": "pending",
    }
    assert ActionProposal.from_dict(payload) == proposal


def test_empty_state_round_trips_with_defaults():
    state = RaphaelState.empty()

    payload = state.to_dict()

    assert state.status_cards == ()
    assert state.action_proposals == ()
    assert state.updated_at.tzinfo == timezone.utc
    assert payload == {
        "schema_version": STATE_SCHEMA_VERSION,
        "status_cards": [],
        "action_proposals": [],
        "updated_at": state.updated_at.isoformat(),
    }
    assert RaphaelState.from_dict(payload) == state
