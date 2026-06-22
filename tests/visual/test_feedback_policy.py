from __future__ import annotations


def test_feedback_policy_applies_next_actions_to_runtime_strategy():
    from agent.visual.feedback_policy import resolve_visual_feedback_policy

    policy = resolve_visual_feedback_policy(
        {
            "next_actions": [
                {
                    "type": "increase_candidate_budget",
                    "max_candidate_budget": 4,
                    "confidence": 0.65,
                },
                {
                    "type": "prefer_image_first_video",
                    "confidence": 0.75,
                },
                {
                    "type": "rerank_before_slack",
                    "confidence": 0.70,
                },
                {
                    "type": "prefer_quality_repair_retry",
                    "confidence": 0.90,
                    "success_rate": 1.0,
                },
            ]
        },
        wants_image=True,
        wants_video=True,
        explicit_candidate_budget=None,
        default_candidate_budget=2,
    )

    assert policy["candidate_budget"] == 4
    assert policy["candidate_budget_source"] == "feedback_loop"
    assert policy["prefer_image_first_video"] is True
    assert policy["rerank_before_delivery"] is True
    assert policy["quality_repair_mode"] == "preferred"
    assert policy["applied_action_types"] == [
        "increase_candidate_budget",
        "prefer_image_first_video",
        "rerank_before_slack",
        "prefer_quality_repair_retry",
    ]


def test_feedback_policy_respects_explicit_user_candidate_budget():
    from agent.visual.feedback_policy import resolve_visual_feedback_policy

    policy = resolve_visual_feedback_policy(
        {
            "next_actions": [
                {
                    "type": "increase_candidate_budget",
                    "max_candidate_budget": 4,
                    "confidence": 0.65,
                },
                {
                    "type": "prefer_quality_repair_retry",
                    "confidence": 0.90,
                },
            ]
        },
        wants_image=True,
        wants_video=False,
        explicit_candidate_budget=1,
        default_candidate_budget=2,
    )

    assert policy["candidate_budget"] == 1
    assert policy["candidate_budget_source"] == "user"
    assert policy["quality_repair_mode"] == "preferred"
    assert policy["applied_action_types"] == ["prefer_quality_repair_retry"]


def test_feedback_policy_escalates_failed_quality_repair_strategy():
    from agent.visual.feedback_policy import resolve_visual_feedback_policy

    policy = resolve_visual_feedback_policy(
        {
            "next_actions": [
                {
                    "type": "escalate_quality_repair_strategy",
                    "confidence": 1.0,
                    "max_candidate_budget": 4,
                }
            ]
        },
        wants_image=True,
        wants_video=False,
        explicit_candidate_budget=None,
        default_candidate_budget=2,
    )

    assert policy["candidate_budget"] == 4
    assert policy["candidate_budget_source"] == "feedback_loop"
    assert policy["quality_repair_mode"] == "escalated"
    assert policy["applied_action_types"] == ["escalate_quality_repair_strategy"]
