def test_active_learning_auto_posts_high_score_high_confidence():
    from agent.visual.active_learning import decide_visual_action

    decision = decide_visual_action(
        {"decision": "post", "top_score": 0.86, "top_confidence": 0.82, "uncertainty_reasons": []},
        request_context={"has_reference_image": False, "candidate_count": 3},
    )

    assert decision["action"] == "auto_post"
    assert decision["requires_user"] is False


def test_active_learning_asks_on_reference_uncertainty():
    from agent.visual.active_learning import decide_visual_action

    decision = decide_visual_action(
        {
            "decision": "post",
            "top_score": 0.78,
            "top_confidence": 0.62,
            "uncertainty_reasons": ["reference_adherence_missing"],
        },
        request_context={"has_reference_image": True, "candidate_count": 2},
    )

    assert decision["action"] == "ask_user"
    assert decision["requires_user"] is True


def test_active_learning_auto_retries_actionable_generation_gap():
    from agent.visual.active_learning import decide_visual_action

    decision = decide_visual_action(
        {
            "decision": "retry",
            "top_score": 0.0,
            "top_confidence": 0.2,
            "uncertainty_reasons": ["no_candidate_passed_hard_gate"],
        },
        request_context={"retry_budget_remaining": 1, "failure_type": "artifact_stale"},
    )

    assert decision["action"] == "auto_retry"
    assert decision["requires_user"] is False


def test_active_learning_fails_closed_on_policy_without_retry_path():
    from agent.visual.active_learning import decide_visual_action

    decision = decide_visual_action(
        {
            "decision": "retry",
            "top_score": 0.0,
            "top_confidence": 0.1,
            "uncertainty_reasons": ["policy_failure"],
        },
        request_context={"retry_budget_remaining": 0, "failure_type": "content_moderation"},
    )

    assert decision["action"] == "fail_closed"
    assert decision["requires_user"] is False
