from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from agent.raphael.evolution import (
    build_evolution_action_proposal,
    build_evolution_signal,
    record_evolution_action_proposal,
)
from agent.raphael.models import RaphaelState, RiskLevel
from agent.raphael.state import get_raphael_events_path, read_state, write_state


NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


def _hermes_home_env(path: Path):
    return patch.dict(os.environ, {"HERMES_HOME": str(path)})


def test_user_correction_builds_auditable_approval_gated_proposal():
    signal = build_evolution_signal(
        source="user_correction",
        affected_capability="raphael.mode_router",
        reason_codes=("user_correction",),
        summary="User said the visual edit routed to the wrong artifact.",
        evidence_refs=("turn:123",),
        confidence=0.84,
        proposed_change="tighten active-artifact follow-up routing",
        promotion_gate="focused tests plus LLM smoke",
        rollback_condition="user reports follow-up edits attach to the wrong artifact again",
        metadata={"raw_prompt": "data:image/png;base64,SECRET"},
    )

    proposal = build_evolution_action_proposal((signal,), now=NOW)

    assert proposal is not None
    assert proposal.action_type == "skill_patch"
    assert proposal.risk == RiskLevel.R2
    assert proposal.requires_approval is True
    assert proposal.status == "pending"
    assert proposal.proposal_id.startswith("evolution-")
    assert "Raphael mode router" in proposal.summary
    assert "tighten active-artifact follow-up routing" in proposal.summary
    assert "base64" not in proposal.summary
    assert proposal.evidence_refs == (
        "evolution:raphael.mode_router",
        "turn:123",
        "signal_count:1",
    )
    assert proposal.metadata["affected_capability"] == "raphael.mode_router"
    assert proposal.metadata["confidence"] == 0.84
    assert proposal.metadata["promotion_gate"] == "focused tests plus LLM smoke"
    assert proposal.metadata["rollback_condition"].startswith("user reports")
    assert proposal.metadata["approval_required"] is True
    assert proposal.metadata["rollout_plan"]["manual_steps"] == [
        "Open a scoped issue or PR for raphael.mode_router.",
        "Apply the proposed skill or strategy change only after approval.",
        "Run the promotion gate before enabling the change.",
    ]
    assert "durable_policy_mutated" not in proposal.metadata


def test_repeated_proof_failures_create_proof_gate_proposal():
    first = build_evolution_signal(
        source="proof_gate",
        affected_capability="raphael.proof_gate",
        reason_codes=("failed_proof",),
        summary="Proof gate blocked a vague completion claim.",
        evidence_refs=("proof:1",),
        confidence=0.74,
        proposed_change="tighten proof-gate next-action summaries",
        promotion_gate="focused tests plus LLM smoke",
        rollback_condition="user says proof guidance is still vague",
    )
    second = build_evolution_signal(
        source="proof_gate",
        affected_capability="raphael.proof_gate",
        reason_codes=("failed_proof",),
        summary="Proof gate blocked another unsupported success claim.",
        evidence_refs=("proof:2",),
        confidence=0.78,
        proposed_change="tighten proof-gate next-action summaries",
        promotion_gate="focused tests plus LLM smoke",
        rollback_condition="user says proof guidance is still vague",
    )

    proposal = build_evolution_action_proposal((first, second), now=NOW)

    assert proposal is not None
    assert "Raphael proof gate" in proposal.summary
    assert "2 recurring signals" in proposal.summary
    assert proposal.metadata["recurring_signal_count"] == 2
    assert proposal.metadata["reason_codes"] == ["failed_proof"]
    assert proposal.evidence_refs == (
        "evolution:raphael.proof_gate",
        "proof:1",
        "proof:2",
        "signal_count:2",
    )


def test_single_proof_failure_does_not_create_proof_gate_proposal():
    signal = build_evolution_signal(
        source="proof_gate",
        affected_capability="raphael.proof_gate",
        reason_codes=("failed_proof",),
        summary="Proof gate blocked one unsupported claim.",
        evidence_refs=("proof:1",),
        confidence=0.74,
        proposed_change="tighten proof-gate next-action summaries",
        promotion_gate="focused tests plus LLM smoke",
        rollback_condition="user says proof guidance is still vague",
    )

    assert build_evolution_action_proposal((signal,), now=NOW) is None


def test_hostile_review_and_provider_outcomes_create_bounded_proposals():
    hostile = build_evolution_signal(
        source="hostile_review",
        affected_capability="raphael.evidence_gate",
        reason_codes=("hostile_review_blocker",),
        summary="Reviewer found overblocking in finalizer proof extraction.",
        evidence_refs=("review:13",),
        confidence=0.88,
        proposed_change="accept realistic tool_call proof shapes",
        promotion_gate="regression tests for tool_call proofs",
        rollback_condition="finalizer blocks proven tool outputs again",
    )
    provider = build_evolution_signal(
        source="provider_outcome",
        affected_capability="visual.provider_recovery",
        reason_codes=("provider_health",),
        summary="Provider timeout repeated during no-live fallback planning.",
        evidence_refs=("provider:xai-timeout",),
        confidence=0.7,
        proposed_change="classify provider timeout before retry policy",
        promotion_gate="provider failure taxonomy tests",
        rollback_condition="provider recovery guidance gets less specific",
    )

    assert build_evolution_action_proposal((hostile,), now=NOW) is not None
    assert build_evolution_action_proposal((provider,), now=NOW) is not None


def test_record_evolution_action_proposal_deduplicates_pending_state(tmp_path):
    home = tmp_path / "hermes-home"
    first_signal = build_evolution_signal(
        source="proof_gate",
        affected_capability="raphael.proof_gate",
        reason_codes=("failed_proof",),
        summary="Proof gate blocked an unsupported claim.",
        evidence_refs=("proof:1",),
        confidence=0.8,
        proposed_change="tighten proof-gate next-action summaries",
        promotion_gate="focused tests",
        rollback_condition="user says 不對 again",
    )
    second_signal = build_evolution_signal(
        source="proof_gate",
        affected_capability="raphael.proof_gate",
        reason_codes=("failed_proof",),
        summary="Proof gate blocked another unsupported claim.",
        evidence_refs=("proof:2",),
        confidence=0.81,
        proposed_change="tighten proof-gate next-action summaries",
        promotion_gate="focused tests",
        rollback_condition="user says 不對 again",
    )
    signals = (first_signal, second_signal)

    with _hermes_home_env(home):
        write_state(RaphaelState(status_cards=(), action_proposals=(), updated_at=NOW))
        first = record_evolution_action_proposal(signals, now=NOW)
        second = record_evolution_action_proposal(signals, now=NOW)
        state = read_state()

    assert first is not None
    assert second is not None
    assert second.proposal_id == first.proposal_id
    assert len(state.action_proposals) == 1
    assert state.action_proposals[0].proposal_id == first.proposal_id
    assert state.action_proposals[0].requires_approval is True


def test_resolved_proposal_allows_new_pending_follow_up(tmp_path):
    from agent.raphael.state import resolve_action_proposal

    home = tmp_path / "hermes-home"
    signals = (
        build_evolution_signal(
            source="proof_gate",
            affected_capability="raphael.proof_gate",
            reason_codes=("failed_proof",),
            summary="Proof gate blocked an unsupported claim.",
            evidence_refs=("proof:1",),
            confidence=0.8,
            proposed_change="tighten proof-gate next-action summaries",
            promotion_gate="focused tests",
            rollback_condition="user says 不對 again",
        ),
        build_evolution_signal(
            source="proof_gate",
            affected_capability="raphael.proof_gate",
            reason_codes=("failed_proof",),
            summary="Proof gate blocked another unsupported claim.",
            evidence_refs=("proof:2",),
            confidence=0.81,
            proposed_change="tighten proof-gate next-action summaries",
            promotion_gate="focused tests",
            rollback_condition="user says 不對 again",
        ),
    )

    with _hermes_home_env(home):
        write_state(RaphaelState(status_cards=(), action_proposals=(), updated_at=NOW))
        first = record_evolution_action_proposal(signals, now=NOW)
        assert first is not None
        resolve_action_proposal(
            first.proposal_id,
            status="rejected",
            resolved_by="operator",
            note="Rejected to wait for more evidence.",
            now=NOW,
        )
        follow_up = record_evolution_action_proposal(signals, now=NOW)
        state = read_state()

    assert follow_up is not None
    assert follow_up.proposal_id != first.proposal_id
    assert follow_up.status == "pending"
    assert [proposal.status for proposal in state.action_proposals] == [
        "rejected",
        "pending",
    ]


def test_approval_records_audit_event_without_mutating_policy(tmp_path):
    from agent.raphael.state import resolve_action_proposal

    home = tmp_path / "hermes-home"
    signal = build_evolution_signal(
        source="user_correction",
        affected_capability="raphael.proof_gate",
        reason_codes=("user_correction",),
        summary="User said proof guidance was vague.",
        evidence_refs=("turn:1",),
        confidence=0.82,
        proposed_change="tighten proof-gate next-action summaries",
        promotion_gate="focused tests",
        rollback_condition="user says 不對 again",
    )

    with _hermes_home_env(home):
        proposal = record_evolution_action_proposal((signal,), now=NOW)
        assert proposal is not None
        resolved = resolve_action_proposal(
            proposal.proposal_id,
            status="approved",
            resolved_by="operator",
            note="Approved for a follow-up PR only.",
            now=NOW,
        )
        state = read_state()
        event_payload = json.loads(
            get_raphael_events_path().read_text(encoding="utf-8").splitlines()[-1]
        )

    assert resolved.status == "approved"
    assert state.action_proposals[0].status == "approved"
    assert state.action_proposals[0].metadata["resolution"] == {
        "status": "approved",
        "resolved_by": "operator",
        "resolved_at": NOW.isoformat(),
        "note": "Approved for a follow-up PR only.",
        "durable_policy_mutated": False,
    }
    assert event_payload["kind"] == "action_proposal_resolved"
    assert event_payload["details"]["proposal_id"] == proposal.proposal_id
    assert event_payload["details"]["status"] == "approved"
    assert event_payload["details"]["durable_policy_mutated"] is False
