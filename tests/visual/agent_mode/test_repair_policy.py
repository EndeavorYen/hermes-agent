from __future__ import annotations


def test_repair_policy_retries_retryable_qc_failure_with_budget():
    from agent.visual.agent_mode.repair_policy import decide_visual_repair

    decision = decide_visual_repair(
        mission={"autonomy_level": 3, "repair_budget": 1},
        stage_result={"success": False, "error_type": "qc_failed"},
        reward_trace={"confidence": 0.4},
    )

    assert decision.action == "retry"
    assert decision.reason == "retryable_qc_failure"
    assert decision.remaining_budget == 0


def test_repair_policy_stops_content_moderation():
    from agent.visual.agent_mode.repair_policy import decide_visual_repair

    decision = decide_visual_repair(
        mission={"autonomy_level": 3, "repair_budget": 1},
        stage_result={"success": False, "error_type": "content_moderation"},
        reward_trace={"confidence": 0.1},
    )

    assert decision.action == "stop"
    assert decision.reason == "content_moderation"


def test_repair_policy_stops_when_budget_exhausted():
    from agent.visual.agent_mode.repair_policy import decide_visual_repair

    decision = decide_visual_repair(
        mission={"autonomy_level": 3, "repair_budget": 1},
        stage_result={
            "success": False,
            "error_type": "qc_failed",
            "repair_attempt_count": 1,
        },
        reward_trace={"confidence": 0.4},
    )

    assert decision.action == "stop"
    assert decision.reason == "repair_budget_exhausted"


def test_repair_policy_asks_user_when_autonomy_too_low():
    from agent.visual.agent_mode.repair_policy import decide_visual_repair

    decision = decide_visual_repair(
        mission={"autonomy_level": 2, "repair_budget": 1},
        stage_result={"success": False, "error_type": "qc_failed"},
        reward_trace={"confidence": 0.4},
    )

    assert decision.action == "ask_user"
    assert decision.reason == "autonomy_below_repair"
