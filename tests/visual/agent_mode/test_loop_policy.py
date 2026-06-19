from __future__ import annotations

from agent.visual.agent_mode.loop_policy import decide_next_action
from agent.visual.agent_mode.mission_planner import plan_visual_mission


def test_policy_generates_until_candidate_budget_is_met():
    mission = plan_visual_mission("Generate three image options.")

    assert (
        decide_next_action(
            mission,
            candidate_count=1,
            accepted_count=0,
            failure_count=0,
            confidence=0.0,
        )
        == "generate_image"
    )


def test_policy_asks_when_confidence_is_low_after_candidates_exist():
    mission = plan_visual_mission("Generate three image options.", autonomy_level=1)

    assert (
        decide_next_action(
            mission,
            candidate_count=3,
            accepted_count=1,
            failure_count=0,
            confidence=0.42,
        )
        == "ask_user"
    )


def test_policy_can_auto_select_at_autonomy_two():
    mission = plan_visual_mission("Generate three image options.", autonomy_level=2)

    assert (
        decide_next_action(
            mission,
            candidate_count=3,
            accepted_count=2,
            failure_count=0,
            confidence=0.81,
        )
        == "select_images"
    )


def test_policy_fails_after_exhausting_failures_without_acceptance():
    mission = plan_visual_mission("Generate three image options.", autonomy_level=3)

    assert (
        decide_next_action(
            mission,
            candidate_count=3,
            accepted_count=0,
            failure_count=3,
            confidence=0.0,
        )
        == "fail"
    )
