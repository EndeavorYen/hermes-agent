from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from agent.raphael.mission import (
    apply_followup,
    apply_followup_to_active_mission,
    create_mission,
    render_mission_status_summary,
)
from agent.raphael.models import MissionArtifact, RaphaelMission


NOW = datetime(2026, 7, 1, 15, 0, tzinfo=timezone.utc)


def _artifact(
    artifact_id: str,
    label: str,
    *,
    stale: bool = False,
    created_at: datetime = NOW,
) -> MissionArtifact:
    return MissionArtifact(
        artifact_id=artifact_id,
        kind="image",
        label=label,
        uri=f"artifact://{artifact_id}",
        created_at=created_at,
        stale=stale,
    )


def test_create_mission_records_goal_artifact_proofs_and_evidence():
    artifact = _artifact("image-1", "Hero image")

    mission = create_mission(
        mission_id="mission-1",
        goal="Ship Raphael phase 2 without scope drift",
        active_artifact=artifact,
        success_conditions=("records goal", "tracks active artifact"),
        phase="planning",
        blockers=("waiting for red test",),
        next_action="write the smallest failing mission tests",
        selected_strategy="issue-scoped TDD",
        required_proofs=("unit tests", "CLI status smoke"),
        last_evidence=("issue:#8", "program-doc:phase-2"),
        now=NOW,
    )

    assert mission.mission_id == "mission-1"
    assert mission.goal == "Ship Raphael phase 2 without scope drift"
    assert mission.active_artifact == artifact
    assert mission.success_conditions == ("records goal", "tracks active artifact")
    assert mission.phase == "planning"
    assert mission.blockers == ("waiting for red test",)
    assert mission.next_action == "write the smallest failing mission tests"
    assert mission.selected_strategy == "issue-scoped TDD"
    assert mission.required_proofs == ("unit tests", "CLI status smoke")
    assert mission.last_evidence == ("issue:#8", "program-doc:phase-2")
    assert mission.updated_at == NOW
    assert RaphaelMission.from_dict(mission.to_dict()) == mission


def test_followup_updates_existing_mission_instead_of_starting_over():
    artifact = _artifact("image-1", "Hero image")
    mission = create_mission(
        mission_id="mission-1",
        goal="Deliver a polished launch image",
        active_artifact=artifact,
        success_conditions=("composition approved",),
        phase="reviewing",
        next_action="wait for user feedback",
        selected_strategy="image-first review",
        required_proofs=("visual self-review",),
        now=NOW,
    )

    result = apply_followup(
        mission,
        user_message="請把這張圖改亮一點",
        artifact_reference="這張圖",
        now=NOW + timedelta(minutes=5),
    )

    assert result.status == "updated"
    assert result.selected_artifact == artifact
    assert result.clarification_question is None
    assert result.mission.mission_id == "mission-1"
    assert result.mission.goal == mission.goal
    assert result.mission.active_artifact_id == "image-1"
    assert result.mission.phase == "followup"
    assert result.mission.next_action == "Apply follow-up to Hero image."
    assert result.mission.last_user_request == "請把這張圖改亮一點"
    assert result.mission.updated_at == NOW + timedelta(minutes=5)


def test_ambiguous_artifact_reference_asks_one_precise_clarification():
    mission = create_mission(
        mission_id="mission-1",
        goal="Revise the selected launch assets",
        artifacts=(
            _artifact("image-1", "Hero image"),
            _artifact("image-2", "Pose reference"),
        ),
        success_conditions=("right artifact updated",),
        phase="reviewing",
        next_action="wait for user feedback",
        selected_strategy="follow-up continuity",
        required_proofs=("artifact match",),
        now=NOW,
    )

    result = apply_followup(
        mission,
        user_message="請修改這個",
        artifact_reference="這個",
        now=NOW + timedelta(minutes=3),
    )

    assert result.status == "clarification_required"
    assert result.mission.mission_id == mission.mission_id
    assert result.selected_artifact is None
    assert result.clarification_question is not None
    assert result.clarification_question.count("?") == 1
    assert "Hero image" in result.clarification_question
    assert "Pose reference" in result.clarification_question
    assert result.mission.phase == "clarification"
    assert result.mission.next_action == "Ask one precise artifact clarification."


def test_ambiguous_artifact_reference_can_return_bounded_multi_candidate_plan():
    mission = create_mission(
        mission_id="mission-1",
        goal="Revise one of several launch assets",
        artifacts=(
            _artifact("image-1", "Hero image"),
            _artifact("image-2", "Pose reference"),
            _artifact("image-3", "Wardrobe reference"),
        ),
        success_conditions=("right artifact updated",),
        phase="reviewing",
        next_action="wait for user feedback",
        selected_strategy="follow-up continuity",
        required_proofs=("artifact match",),
        now=NOW,
    )

    result = apply_followup(
        mission,
        user_message="請修改這個",
        artifact_reference="這個",
        allow_multi_candidate=True,
        max_candidates=2,
        now=NOW + timedelta(minutes=3),
    )

    assert result.status == "multi_candidate_plan"
    assert result.clarification_question is None
    assert tuple(artifact.artifact_id for artifact in result.candidate_artifacts) == (
        "image-1",
        "image-2",
    )
    assert result.selected_artifact is None
    assert result.mission.phase == "clarification"
    assert result.mission.next_action == "Validate 2 candidate artifacts before editing."


def test_stale_artifact_reference_is_not_selected():
    stale_artifact = _artifact(
        "image-old",
        "Old rejected image",
        stale=True,
        created_at=NOW - timedelta(days=1),
    )
    mission = create_mission(
        mission_id="mission-1",
        goal="Revise only current selected media",
        active_artifact=stale_artifact,
        success_conditions=("never edit stale media",),
        phase="reviewing",
        next_action="wait for user feedback",
        selected_strategy="stale-artifact guard",
        required_proofs=("artifact freshness",),
        now=NOW,
    )

    result = apply_followup(
        mission,
        user_message="請改 old rejected image",
        artifact_reference="Old rejected image",
        now=NOW + timedelta(minutes=2),
    )

    assert mission.active_artifact is None
    assert mission.active_artifact_id is None
    assert mission.to_dict()["active_artifact_id"] is None
    assert result.status == "clarification_required"
    assert result.selected_artifact is None
    assert result.mission.active_artifact is None
    assert "stale" in (result.clarification_question or "").lower()


def test_public_mission_summary_redacts_sensitive_goal_artifact_and_action_text():
    data_uri = "data:image/png;base64,SECRETLOCALPAYLOAD"
    unsafe_artifact = MissionArtifact(
        artifact_id=data_uri,
        kind="image",
        label=f"/private/tmp/rejected-candidate.png {data_uri}",
        uri="/private/tmp/private-source.png",
        created_at=NOW,
    )
    mission = RaphaelMission(
        mission_id="mission-1",
        goal=f"Use provider log /private/tmp/provider-raw.log and {data_uri}",
        active_artifact_id=data_uri,
        artifacts=(unsafe_artifact,),
        success_conditions=("do not leak",),
        phase="planning",
        blockers=(),
        next_action=f"open candidate:old-image from /Users/simon/private.log {data_uri}",
        selected_strategy="sanitized status",
        required_proofs=("status smoke",),
        last_evidence=("base64:raw", "/private/tmp/raw.log"),
        updated_at=NOW,
    )

    output = render_mission_status_summary(mission)

    assert "[redacted-path]" in output
    assert "[redacted-base64]" in output
    assert "[redacted-candidate]" in output
    assert "/private/tmp" not in output
    assert "/Users/simon" not in output
    assert "data:image" not in output
    assert "SECRETLOCALPAYLOAD" not in output
    assert "base64:secret" not in output
    assert "candidate:old-image" not in output


def test_clarification_question_redacts_sensitive_artifact_labels():
    mission = create_mission(
        mission_id="mission-1",
        goal="Revise sensitive artifacts",
        artifacts=(
            _artifact("image-1", "/private/tmp/rejected-one.png"),
            _artifact("image-2", "base64:rejected-two"),
        ),
        success_conditions=("ask safely",),
        phase="reviewing",
        next_action="wait for user feedback",
        selected_strategy="safe clarification",
        required_proofs=("artifact match",),
        now=NOW,
    )

    result = apply_followup(
        mission,
        user_message="請修改這個",
        artifact_reference="這個",
        now=NOW + timedelta(minutes=3),
    )

    assert result.status == "clarification_required"
    assert result.clarification_question is not None
    assert "[redacted-path]" in result.clarification_question
    assert "[redacted-base64]" in result.clarification_question
    assert "/private/tmp" not in result.clarification_question
    assert "base64:rejected" not in result.clarification_question


def test_followup_to_active_mission_persists_updated_state(tmp_path):
    from agent.raphael.models import RaphaelState
    from agent.raphael.state import read_state, write_state

    home = tmp_path / "hermes-home"
    artifact = _artifact("image-1", "Hero image")
    mission = create_mission(
        mission_id="mission-1",
        goal="Keep follow-ups attached to the active mission",
        active_artifact=artifact,
        success_conditions=("persist updated mission",),
        phase="reviewing",
        next_action="wait for user feedback",
        selected_strategy="stateful follow-up",
        required_proofs=("state round trip",),
        now=NOW,
    )

    with _hermes_home_env(home):
        write_state(
            RaphaelState(
                status_cards=(),
                action_proposals=(),
                active_mission=mission,
                updated_at=NOW,
            )
        )
        result = apply_followup_to_active_mission(
            user_message="請把這張圖改亮一點",
            artifact_reference="這張圖",
            now=NOW + timedelta(minutes=4),
        )
        persisted = read_state()

    assert result.status == "updated"
    assert persisted.active_mission is not None
    assert persisted.active_mission.mission_id == "mission-1"
    assert persisted.active_mission.phase == "followup"
    assert persisted.active_mission.last_user_request == "請把這張圖改亮一點"
    assert persisted.active_mission.active_artifact_id == "image-1"


def _hermes_home_env(path: Path):
    return patch.dict(os.environ, {"HERMES_HOME": str(path)})
