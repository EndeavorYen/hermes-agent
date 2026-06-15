from datetime import datetime, timedelta, timezone

import pytest

from agent.raphael import (
    ActionProposal,
    RaphaelEvent,
    RaphaelState,
    RiskLevel,
    StatusCard,
)
from agent.raphael.models import EVENT_SCHEMA_VERSION, STATE_SCHEMA_VERSION


def test_status_card_round_trips_with_utc_iso_datetimes():
    observed_at = datetime(2026, 6, 16, 8, 30, tzinfo=timezone.utc)
    expires_at = observed_at + timedelta(hours=2)
    card = StatusCard(
        card_id="card-1",
        severity="warning",
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
        "severity": "warning",
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
        "requires_approval": True,
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


@pytest.mark.parametrize("schema_version", [None, "raphael.state.v2"])
def test_state_rejects_missing_or_wrong_schema_version(schema_version):
    payload = {
        "status_cards": [],
        "action_proposals": [],
        "updated_at": "2026-06-16T09:00:00+00:00",
    }
    if schema_version is not None:
        payload["schema_version"] = schema_version

    with pytest.raises(ValueError, match="Unsupported Raphael state schema"):
        RaphaelState.from_dict(payload)


def test_event_round_trips_with_schema_version():
    event = RaphaelEvent(
        event_id="event-1",
        kind="state_written",
        created_at=datetime(2026, 6, 16, 9, 30, tzinfo=timezone.utc),
        details={"path": "state.json"},
    )

    payload = event.to_dict()

    assert payload == {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": "event-1",
        "kind": "state_written",
        "created_at": "2026-06-16T09:30:00+00:00",
        "details": {"path": "state.json"},
    }
    assert RaphaelEvent.from_dict(payload) == event


def test_status_card_accepts_warning_severity_from_phase_one_schema():
    payload = {
        "card_id": "card-2",
        "severity": "warning",
        "title": "Gateway warning",
        "summary": "Slack socket errors were observed.",
        "observed_at": "2026-06-16T08:30:00+00:00",
        "expires_at": "2026-06-16T10:30:00+00:00",
        "source": "raphael-test",
        "confidence": 0.82,
        "evidence_refs": ["gateway.log:latest"],
    }

    card = StatusCard.from_dict(payload)

    assert card.severity == "warning"
    assert card.to_dict()["severity"] == "warning"
