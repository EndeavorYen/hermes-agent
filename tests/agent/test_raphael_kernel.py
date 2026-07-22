from __future__ import annotations

from unittest.mock import patch

from agent.raphael.finalization import enforce_raphael_completion
from agent.raphael.kernel import prepare_raphael_turn, replay_raphael_turn
from agent.raphael.mission import create_mission
from agent.raphael.runtime_contract import (
    RaphaelTurnOrigin,
    resolve_raphael_runtime_contract,
)
from agent.raphael.state import read_state
from agent.raphael.observer import build_raphael_observation_context


def _enabled_config():
    return {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "sage_king",
        },
        "model": {"provider": "openai-codex", "default": "gpt-5.5"},
    }


def test_prepare_foreground_turn_records_canonical_decision(tmp_path):
    runtime_contract = resolve_raphael_runtime_contract(
        _enabled_config(),
        live_provider="openai-codex",
        live_model="gpt-5.6-terra",
        live_api_mode="codex_app_server",
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        decision = prepare_raphael_turn(
            turn_id="turn-1",
            origin=RaphaelTurnOrigin.FOREGROUND,
            runtime_contract=runtime_contract,
            config=_enabled_config(),
            user_message="請修復 gateway bug 並跑測試",
            conversation_history=[],
        )
        state = read_state()

    assert decision is not None
    assert decision.mode == "tool_task"
    assert decision.runtime_contract.base_model == "gpt-5.6-terra"
    assert decision.route.base_llm_model == "gpt-5.6-terra"
    assert decision.completion_policy == "mutation"
    assert state.last_decision is not None
    assert state.last_decision["turn_id"] == "turn-1"
    assert state.last_decision["mode"] == "tool_task"


def test_story_video_planning_turn_is_not_visual_finalization_work(tmp_path):
    runtime_contract = resolve_raphael_runtime_contract(_enabled_config())
    prompt = (
        "故事影片測試：影子為什麼會跟著我，30 秒，給 5 歲以上小朋友。"
        "只規劃，嚴禁產圖、語音或影片。"
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        decision = prepare_raphael_turn(
            turn_id="turn-story-video-planning",
            origin=RaphaelTurnOrigin.FOREGROUND,
            runtime_contract=runtime_contract,
            config=_enabled_config(),
            user_message=prompt,
            conversation_history=[],
        )

    assert decision is not None
    assert decision.mode == "general_conversation"
    assert decision.completion_policy == "informational"
    assert decision.required_proofs == ("story_video_phase_proof",)

    result = enforce_raphael_completion(
        decision=decision.to_dict(),
        final_response="規劃已完成。STORY_VIDEO_PHASE_PROOF: planning PASS",
        messages=[
            {"role": "user", "content": prompt},
            {
                "role": "assistant",
                "content": "規劃已完成。STORY_VIDEO_PHASE_PROOF: planning PASS",
            },
        ],
    )

    assert result.status == "informational"
    assert result.final_response.endswith("STORY_VIDEO_PHASE_PROOF: planning PASS")
    assert "direct_handoff_metadata" not in result.required_proofs


def test_observer_is_read_only_and_kernel_owns_canonical_mission(tmp_path):
    runtime_contract = resolve_raphael_runtime_contract(_enabled_config())

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        build_raphael_observation_context(
            "請產出一張圖片",
            _enabled_config(),
            include_control_context=False,
        )
        assert read_state().active_mission is None

        decision = prepare_raphael_turn(
            turn_id="turn-visual-owner",
            origin=RaphaelTurnOrigin.FOREGROUND,
            runtime_contract=runtime_contract,
            config=_enabled_config(),
            user_message="請產出一張圖片",
        )
        mission = read_state().active_mission

    assert decision is not None
    assert mission is not None
    assert mission.mission_id == decision.mission_id
    assert mission.goal == decision.goal.summary
    assert mission.phase == decision.goal.phase
    assert mission.next_action == decision.next_action
    assert mission.required_proofs == decision.required_proofs
    assert mission.blockers == decision.goal.blockers


def test_kernel_reconciles_existing_mission_to_latest_decision(tmp_path):
    runtime_contract = resolve_raphael_runtime_contract(_enabled_config())
    stale = create_mission(
        mission_id="mission-existing",
        goal="stale observer goal",
        success_conditions=("stale condition",),
        phase="strategy_selected",
        next_action="multi_pass_review_and_repair",
        selected_strategy="old-strategy",
        required_proofs=("stale_proof",),
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        from agent.raphael.state import write_active_mission

        write_active_mission(stale)
        decision = prepare_raphael_turn(
            turn_id="turn-reconcile",
            origin=RaphaelTurnOrigin.FOREGROUND,
            runtime_contract=runtime_contract,
            config=_enabled_config(),
            user_message="請產出一張圖片",
        )
        mission = read_state().active_mission

    assert decision is not None
    assert mission is not None
    assert mission.mission_id == "mission-existing"
    assert mission.goal == decision.goal.summary
    assert mission.phase == decision.goal.phase
    assert mission.next_action == decision.next_action
    assert mission.required_proofs == decision.required_proofs
    assert mission.selected_strategy == decision.mode


def test_kernel_records_blocked_reference_goal_and_visual_artifact_identity(tmp_path):
    runtime_contract = resolve_raphael_runtime_contract(_enabled_config())

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        blocked = prepare_raphael_turn(
            turn_id="turn-blocked-reference",
            origin=RaphaelTurnOrigin.FOREGROUND,
            runtime_contract=runtime_contract,
            config=_enabled_config(),
            user_message="用 ref3 的服裝，ref1 的角色，產出圖片",
            attachments=["ref1", "ref2"],
        )
        blocked_mission = read_state().active_mission

        from agent.raphael.state import write_active_mission

        write_active_mission(None)
        visual = prepare_raphael_turn(
            turn_id="turn-visual-reference",
            origin=RaphaelTurnOrigin.FOREGROUND,
            runtime_contract=runtime_contract,
            config=_enabled_config(),
            user_message="把剛剛那張圖改亮一點，比例不要變",
            conversation_history=[
                {
                    "role": "assistant",
                    "content": "已產出圖片。",
                    "metadata": {"selected_artifact_id": "artifact-current"},
                }
            ],
        )
        visual_mission = read_state().active_mission

    assert blocked is not None
    assert blocked.completion_policy == "blocked"
    assert blocked_mission is not None
    assert blocked_mission.proof_status == "blocked"
    assert blocked_mission.blockers == blocked.goal.blockers
    assert visual is not None
    assert visual_mission is not None
    assert visual_mission.active_artifact_id == "artifact-current"
    assert visual_mission.active_artifact is not None
    assert visual_mission.active_artifact.uri == "artifact://artifact-current"


def test_background_turn_does_not_create_or_record_foreground_decision(tmp_path):
    runtime_contract = resolve_raphael_runtime_contract(_enabled_config())

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        decision = prepare_raphael_turn(
            turn_id="turn-background",
            origin=RaphaelTurnOrigin.BACKGROUND_REVIEW,
            runtime_contract=runtime_contract,
            config=_enabled_config(),
            user_message="Review the conversation above and update skills",
            conversation_history=[],
        )
        state = read_state()

    assert decision is None
    assert state.last_decision is None


def test_disabled_raphael_does_not_prepare_decision(tmp_path):
    config = {"plugins": {"enabled": []}, "raphael": {"enabled": False}}
    runtime_contract = resolve_raphael_runtime_contract(config)

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        decision = prepare_raphael_turn(
            turn_id="turn-disabled",
            origin=RaphaelTurnOrigin.FOREGROUND,
            runtime_contract=runtime_contract,
            config=config,
            user_message="hello",
            conversation_history=[],
        )

    assert decision is None


def test_production_replay_continues_mission_without_writing_runtime_state(tmp_path):
    runtime_contract = resolve_raphael_runtime_contract(_enabled_config())
    mission = create_mission(
        mission_id="mission-replay",
        goal="repair the production control path",
        success_conditions=("focused tests pass",),
        phase="implementation",
        next_action="run focused tests",
        selected_strategy="minimal repair",
        required_proofs=("focused_tests",),
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        decision = replay_raphael_turn(
            turn_id="turn-replay",
            runtime_contract=runtime_contract,
            user_message="接下來請繼續剛剛的目標",
            mission=mission,
        )
        state = read_state()

    assert decision.origin is RaphaelTurnOrigin.REPLAY
    assert decision.mission_id == "mission-replay"
    assert decision.mode == "tool_task"
    assert decision.required_proofs == ("focused_tests",)
    assert state.last_decision is None
