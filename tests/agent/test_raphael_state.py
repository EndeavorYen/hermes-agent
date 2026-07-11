from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from agent.raphael.models import (
    ActionProposal,
    EVENT_SCHEMA_VERSION,
    RiskLevel,
    STATE_SCHEMA_VERSION,
    RaphaelEvent,
    RaphaelState,
    StatusCard,
)
from agent.raphael.state import (
    append_event,
    get_raphael_events_path,
    get_raphael_state_dir,
    get_raphael_state_path,
    get_raphael_mission_path,
    read_active_mission,
    read_state,
    record_control_decision,
    resolve_action_proposal,
    write_state,
)
from agent.raphael.mission import RaphaelMissionState


def _hermes_home_env(path: Path):
    return patch.dict(os.environ, {"HERMES_HOME": str(path)})


def test_paths_use_active_hermes_home_from_environment(tmp_path):
    home = tmp_path / "active-hermes-home"

    with _hermes_home_env(home):
        assert get_raphael_state_dir() == home / "raphael"
        assert get_raphael_state_path() == home / "raphael" / "state.json"
        assert get_raphael_events_path() == home / "raphael" / "events.jsonl"


def test_missing_state_returns_empty_without_creating_raphael_directory(tmp_path):
    home = tmp_path / "hermes-home"

    with _hermes_home_env(home):
        state = read_state()

    assert state.status_cards == ()
    assert state.action_proposals == ()
    assert state.updated_at.tzinfo == timezone.utc
    assert not (home / "raphael").exists()


def test_write_state_round_trips_status_card_without_tmp_files(tmp_path):
    home = tmp_path / "hermes-home"
    observed_at = datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc)
    card = StatusCard(
        card_id="card-1",
        severity="warning",
        title="Gateway warning",
        summary="Slack gateway warnings need operator attention.",
        observed_at=observed_at,
        expires_at=observed_at + timedelta(hours=1),
        source="gateway-monitor",
        confidence=0.86,
        evidence_refs=("gateway.error.log",),
    )
    state = RaphaelState(
        status_cards=(card,),
        action_proposals=(),
        updated_at=datetime(2026, 6, 16, 9, 5, tzinfo=timezone.utc),
    )

    with _hermes_home_env(home):
        write_state(state)
        payload = json.loads(get_raphael_state_path().read_text(encoding="utf-8"))
        round_tripped = read_state()
        tmp_files = list(get_raphael_state_dir().glob("*.tmp"))

    assert payload["schema_version"] == STATE_SCHEMA_VERSION
    assert round_tripped == state
    assert tmp_files == []


def test_write_state_does_not_claim_existing_fixed_tmp_file(tmp_path):
    home = tmp_path / "hermes-home"
    state = RaphaelState(
        status_cards=(),
        action_proposals=(),
        updated_at=datetime(2026, 6, 16, 9, 5, tzinfo=timezone.utc),
    )

    with _hermes_home_env(home):
        get_raphael_state_dir().mkdir(parents=True)
        stale_tmp = get_raphael_state_path().with_suffix(".json.tmp")
        stale_tmp.write_text("owned by another writer", encoding="utf-8")
        write_state(state)

    assert stale_tmp.read_text(encoding="utf-8") == "owned by another writer"


def test_append_event_writes_jsonl_with_event_schema(tmp_path):
    home = tmp_path / "hermes-home"
    event = RaphaelEvent(
        event_id="event-1",
        kind="state_written",
        created_at=datetime(2026, 6, 16, 9, 10, tzinfo=timezone.utc),
        details={"path": "state.json"},
    )

    with _hermes_home_env(home):
        append_event(event)
        lines = get_raphael_events_path().read_text(encoding="utf-8").splitlines()

    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["schema_version"] == EVENT_SCHEMA_VERSION
    assert payload == event.to_dict()


def test_legacy_mission_is_migrated_once_into_canonical_state(tmp_path):
    home = tmp_path / "hermes-home"
    legacy = RaphaelMissionState(
        mission_id="mission-legacy",
        goal="repair gateway",
        phase="strategy_selected",
        selected_strategy_id="safe",
        active_artifact_id=None,
        blockers=(),
        next_action="run tests",
        proof_status="pending",
        required_proofs=("focused_tests",),
        updated_at=datetime(2026, 7, 11, 8, 0, tzinfo=timezone.utc),
    )

    with _hermes_home_env(home):
        get_raphael_state_dir().mkdir(parents=True)
        get_raphael_mission_path().write_text(
            json.dumps(legacy.to_dict()), encoding="utf-8"
        )
        migrated = read_active_mission()
        stored = read_state()
        events = [
            json.loads(line)
            for line in get_raphael_events_path().read_text(encoding="utf-8").splitlines()
        ]

    assert migrated is not None
    assert migrated.goal == "repair gateway"
    assert migrated.proof_status == "pending"
    assert stored.active_mission == migrated
    assert not (home / "raphael" / "mission.json").exists()
    assert events[-1]["kind"] == "mission_state_migrated"
    assert events[-1]["details"]["source"] == "raphael_mission_v1"


def test_record_control_decision_writes_user_facing_status_card(tmp_path):
    home = tmp_path / "hermes-home"

    with _hermes_home_env(home):
        record_control_decision(
            {
                "mode": "visual_agent_generation",
                "goal": {
                    "target_artifact": "new_visual_package",
                    "phase": "route_and_handoff",
                    "blockers": ["missing_ref3"],
                },
                "next_action": "call_visual_agent_generate",
                "evidence": {"failure_layer": "handoff_failure"},
                "confidence": 0.91,
            },
            turn_id="turn-1",
            task_id="task-1",
            source="general_tool_proof_gate",
        )
        state = read_state()

    assert len(state.status_cards) == 1
    card = state.status_cards[0]
    assert "視覺生成" in card.summary
    assert "新視覺作品" in card.summary
    assert "路由與交接" in card.summary
    assert "呼叫 visual agent 生成" in card.summary
    assert "需要 ref3" in card.summary
    assert "handoff failure" in card.summary
    assert "mode=" not in card.summary
    assert "target=" not in card.summary
    assert "phase=" not in card.summary
    assert "next_action=" not in card.summary
    assert "blockers=" not in card.summary
    assert "failure_layer=" not in card.summary


def _action_proposal(
    proposal_id: str = "proposal-1",
    *,
    status: str = "pending",
) -> ActionProposal:
    return ActionProposal(
        proposal_id=proposal_id,
        action_type="skill_patch",
        risk=RiskLevel.R2,
        summary="Patch Raphael proof gate after recurring failed-proof signals.",
        evidence_refs=("evolution:raphael.proof_gate", "pattern_count:2"),
        created_at=datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc),
        status=status,
        metadata={
            "affected_capability": "raphael.proof_gate",
            "rollout_plan": {
                "status": "pending_approval",
                "verification_commands": [
                    "pytest tests/agent/test_raphael_evolution.py -q",
                ],
                "promotion_gate": "focused tests plus LLM smoke",
                "rollback_condition": "next evidence shows worse behavior",
            },
        },
    )


def test_resolve_action_proposal_rejects_pending_proposal_with_audit_event(tmp_path):
    home = tmp_path / "hermes-home"
    state = RaphaelState(
        status_cards=(),
        action_proposals=(_action_proposal(),),
        updated_at=datetime(2026, 6, 16, 9, 1, tzinfo=timezone.utc),
    )

    with _hermes_home_env(home):
        write_state(state)
        updated = resolve_action_proposal(
            "proposal-1",
            "rejected",
            reviewer="operator",
            reason="Declined; contains sk-secret123 and /Users/example/private/trace.json",
            now=datetime(2026, 6, 16, 9, 5, tzinfo=timezone.utc),
        )
        stored = read_state()
        event_payload = json.loads(
            get_raphael_events_path().read_text(encoding="utf-8").splitlines()[0]
        )

    assert updated is not None
    assert stored.action_proposals[0].status == "rejected"
    metadata = stored.action_proposals[0].metadata
    assert metadata is not None
    assert metadata["rollout_plan"]["status"] == "rejected"
    assert metadata["resolution"]["status"] == "rejected"
    assert metadata["resolution"]["reviewer"] == "operator"
    assert "sk-secret123" not in metadata["resolution"]["reason"]
    assert "/Users/example/private/trace.json" not in metadata["resolution"]["reason"]
    assert event_payload["kind"] == "action_proposal_resolved"
    assert event_payload["details"]["proposal_id"] == "proposal-1"
    assert event_payload["details"]["from_status"] == "pending"
    assert event_payload["details"]["to_status"] == "rejected"
    assert "sk-secret123" not in json.dumps(event_payload)
    assert "/Users/example/private/trace.json" not in json.dumps(event_payload)


def test_resolve_action_proposal_approves_without_marking_applied(tmp_path):
    home = tmp_path / "hermes-home"
    state = RaphaelState(
        status_cards=(),
        action_proposals=(_action_proposal(),),
        updated_at=datetime(2026, 6, 16, 9, 1, tzinfo=timezone.utc),
    )

    with _hermes_home_env(home):
        write_state(state)
        updated = resolve_action_proposal(
            "proposal-1",
            "approved",
            reviewer="operator",
            reason="Approved for manual rollout after tests.",
            now=datetime(2026, 6, 16, 9, 5, tzinfo=timezone.utc),
        )
        stored = read_state()

    assert updated is not None
    assert stored.action_proposals[0].status == "approved"
    metadata = stored.action_proposals[0].metadata
    assert metadata is not None
    assert metadata["rollout_plan"]["status"] == "approved"
    assert metadata["resolution"]["status"] == "approved"
    assert metadata["resolution"]["status"] != "applied"
    assert metadata["rollout_plan"]["status"] != "applied"


def test_resolve_action_proposal_unknown_id_preserves_state_without_event(tmp_path):
    home = tmp_path / "hermes-home"
    state = RaphaelState(
        status_cards=(),
        action_proposals=(_action_proposal("proposal-1"),),
        updated_at=datetime(2026, 6, 16, 9, 1, tzinfo=timezone.utc),
    )

    with _hermes_home_env(home):
        write_state(state)
        updated = resolve_action_proposal(
            "missing-proposal",
            "rejected",
            reviewer="operator",
            reason="No such proposal.",
            now=datetime(2026, 6, 16, 9, 5, tzinfo=timezone.utc),
        )
        stored = read_state()

    assert updated is None
    assert stored == state
    assert not (home / "raphael" / "events.jsonl").exists()
