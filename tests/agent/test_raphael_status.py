from datetime import datetime, timedelta, timezone

from agent.raphael.models import ActionProposal, RaphaelState, RiskLevel, StatusCard
from agent.raphael.status import active_cards, render_status


NOW = datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc)


def _card(card_id: str, *, title: str, expires_at: datetime) -> StatusCard:
    return StatusCard(
        card_id=card_id,
        severity="warning",
        title=title,
        summary=f"{title} summary.",
        observed_at=NOW - timedelta(minutes=15),
        expires_at=expires_at,
        source="raphael-test",
        confidence=0.84,
        evidence_refs=(f"evidence:{card_id}",),
    )


def _proposal(proposal_id: str) -> ActionProposal:
    return ActionProposal(
        proposal_id=proposal_id,
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary="Patch a skill draft after approval.",
        evidence_refs=("card-1",),
        created_at=NOW,
    )


def _evolution_proposal(proposal_id: str) -> ActionProposal:
    return ActionProposal(
        proposal_id=proposal_id,
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary=(
            "Patch proof gate using /private/tmp/raw.log and "
            "data:image/png;base64,SECRET candidate:old-image"
        ),
        evidence_refs=("evolution:raphael.proof_gate",),
        created_at=NOW,
        metadata={
            "affected_capability": "raphael.proof_gate",
            "confidence": 0.82,
            "promotion_gate": "focused tests plus LLM smoke",
            "rollback_condition": "user says 不對 again",
            "rollout_plan": {
                "manual_steps": ["Open a scoped PR for raphael.proof_gate."],
                "verification_commands": [
                    "python -m pytest tests/agent/test_raphael_evolution.py -q"
                ],
                "rollback_condition": "user says 不對 again",
            },
            "approval_required": True,
        },
    )


def _state(
    *,
    cards: tuple[StatusCard, ...] = (),
    proposals: tuple[ActionProposal, ...] = (),
) -> RaphaelState:
    return RaphaelState(
        status_cards=cards,
        action_proposals=proposals,
        updated_at=NOW,
    )


def test_active_cards_filters_expired_cards_and_preserves_order():
    expired = _card("card-1", title="Expired card", expires_at=NOW)
    active_one = _card("card-2", title="First active", expires_at=NOW + timedelta(minutes=1))
    active_two = _card("card-3", title="Second active", expires_at=NOW + timedelta(hours=1))
    state = _state(cards=(expired, active_one, active_two))

    assert active_cards(state, now=NOW) == [active_one, active_two]


def test_empty_status_render_names_advisor_and_read_only_empty_states():
    output = render_status(_state(), now=NOW)

    assert "Raphael Advisor" in output
    assert "Mode: read-only Advisor MVP." in output
    assert "No active status cards." in output
    assert "No pending action proposals." in output
    assert "does not write memory" in output
    assert "edit skills" in output
    assert "change cron" in output
    assert "install tools" in output
    assert "send public messages" in output


def test_render_includes_active_warning_card_and_pending_r2_proposal():
    card = _card("card-1", title="Gateway warning", expires_at=NOW + timedelta(hours=1))
    proposal = _proposal("proposal-1")
    output = render_status(_state(cards=(card,), proposals=(proposal,)), now=NOW)

    assert "warning" in output
    assert "Gateway warning" in output
    assert "raphael-test" in output
    assert "0.84" in output
    assert "proposal-1" in output
    assert "R2" in output
    assert "requires approval" in output


def test_render_status_redacts_evolution_proposal_and_shows_rollout_guidance():
    proposal = _evolution_proposal("proposal-secret")

    output = render_status(_state(proposals=(proposal,)), now=NOW)

    assert "[redacted-path]" in output
    assert "[redacted-base64]" in output
    assert "[redacted-candidate]" in output
    assert "/private/tmp" not in output
    assert "SECRET" not in output
    assert "candidate:old-image" not in output
    assert "Affected capability: raphael.proof_gate" in output
    assert "Confidence: 0.82" in output
    assert "Promotion gate: focused tests plus LLM smoke" in output
    assert "Rollback: user says 不對 again" in output
    assert "Approve: hermes raphael proposal approve" in output
    assert "Reject: hermes raphael proposal reject" in output
    assert "Open a scoped PR for raphael.proof_gate." in output


def test_render_status_respects_max_cards():
    cards = (
        _card("card-1", title="First card", expires_at=NOW + timedelta(hours=1)),
        _card("card-2", title="Second card", expires_at=NOW + timedelta(hours=1)),
        _card("card-3", title="Third card", expires_at=NOW + timedelta(hours=1)),
    )

    output = render_status(_state(cards=cards), now=NOW, max_cards=2)

    assert "First card" in output
    assert "Second card" in output
    assert "Third card" not in output
