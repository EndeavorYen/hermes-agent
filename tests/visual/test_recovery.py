def test_plan_visual_recovery_safe_reframes_content_moderation_when_allowed():
    from agent.visual.recovery import plan_visual_recovery

    result = plan_visual_recovery(
        {
            "prompt": "original user intent",
            "arguments": {"duration": 8, "prompt": "original user intent"},
        },
        {
            "failure_class": "content_moderation",
            "retryable": True,
            "safe_reframe_allowed": True,
        },
        retry_budget_remaining=1,
    )

    assert result["decision"] == "retry"
    assert result["reason"] == "content_moderation_safe_reframe"
    assert result["modified_arguments"]["prompt"] != "original user intent"
    assert result["modified_arguments"]["duration"] == 8
    assert result["audit"]["failure_class"] == "content_moderation"


def test_plan_visual_recovery_blocks_content_moderation_without_safe_reframe():
    from agent.visual.recovery import plan_visual_recovery

    result = plan_visual_recovery(
        {"arguments": {"prompt": "original"}},
        {
            "failure_class": "content_moderation",
            "retryable": True,
            "safe_reframe_allowed": False,
        },
        retry_budget_remaining=1,
    )

    assert result["decision"] == "ask_user"
    assert result["reason"] == "content_moderation_needs_user_choice"


def test_plan_visual_recovery_reduces_duration_after_timeout():
    from agent.visual.recovery import plan_visual_recovery

    result = plan_visual_recovery(
        {"arguments": {"duration": 12, "candidate_budget": 3}},
        {"failure_class": "timeout", "retryable": True},
        retry_budget_remaining=1,
    )

    assert result["decision"] == "retry"
    assert result["reason"] == "timeout_reduce_work"
    assert result["modified_arguments"]["duration"] == 6
    assert result["modified_arguments"]["candidate_budget"] == 1


def test_plan_visual_recovery_recomputes_supported_aspect_from_source_media():
    from agent.visual.recovery import plan_visual_recovery

    result = plan_visual_recovery(
        {
            "arguments": {"aspect_ratio": "4:5"},
            "source_media": {"width": 720, "height": 1280},
            "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
        },
        {"failure_class": "unsupported_aspect_ratio", "retryable": True},
        retry_budget_remaining=1,
    )

    assert result["decision"] == "retry"
    assert result["reason"] == "unsupported_aspect_ratio_nearest_supported"
    assert result["modified_arguments"]["aspect_ratio"] == "9:16"


def test_plan_visual_recovery_fails_when_retry_budget_exhausted():
    from agent.visual.recovery import plan_visual_recovery

    result = plan_visual_recovery(
        {"arguments": {"prompt": "original"}},
        {"failure_class": "empty_response", "retryable": True},
        retry_budget_remaining=0,
    )

    assert result["decision"] == "fail"
    assert result["reason"] == "retry_budget_exhausted"
