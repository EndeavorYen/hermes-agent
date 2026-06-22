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


def test_feedback_policy_exposes_preferred_strategy_without_prompt_mutation():
    from agent.visual.feedback_policy import resolve_visual_feedback_policy

    policy = resolve_visual_feedback_policy(
        {
            "next_actions": [
                {
                    "type": "prefer_strategy",
                    "track": "aesthetic",
                    "strategy_signature": "image_first_rank_then_video",
                    "source": "live_quality_burn",
                    "bucket": "live_visual_agent_mode",
                    "activation_status": "shadow",
                    "confidence": 0.91,
                    "requires_human_feedback": False,
                }
            ],
            "policy_sources": ["scheduled_self_validation"],
        },
        wants_image=True,
        wants_video=True,
        explicit_candidate_budget=None,
        default_candidate_budget=1,
    )

    assert policy["candidate_budget"] == 2
    assert policy["candidate_budget_source"] == "feedback_loop"
    assert policy["prefer_image_first_video"] is True
    assert policy["rerank_before_delivery"] is True
    assert policy["strategy_preference"] == {
        "strategy_signature": "image_first_rank_then_video",
        "source": "live_quality_burn",
        "bucket": "live_visual_agent_mode",
        "activation_status": "shadow",
        "confidence": 0.91,
        "prompt_mutation_allowed": False,
    }
    assert policy["applied_action_types"] == ["prefer_strategy"]


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


def test_feedback_policy_applies_preference_dimension_repair_actions():
    from agent.visual.feedback_policy import resolve_visual_feedback_policy

    policy = resolve_visual_feedback_policy(
        {
            "next_actions": [
                {
                    "type": "repair_low_preference_dimension",
                    "dimension": "face_naturalness",
                    "quality_issue": "face_unnatural",
                    "repair_hint": "improve_face_naturalness",
                    "confidence": 0.72,
                },
                {
                    "type": "repair_low_preference_dimension",
                    "dimension": "fashion_material_quality",
                    "quality_issue": "stockings_bad",
                    "repair_hint": "improve_fashion_material_quality",
                    "confidence": 0.72,
                },
            ]
        },
        wants_image=True,
        wants_video=True,
        explicit_candidate_budget=None,
        default_candidate_budget=1,
    )

    assert policy["quality_repair_mode"] == "preferred"
    assert policy["rerank_before_delivery"] is True
    assert policy["candidate_budget"] == 2
    assert policy["candidate_budget_source"] == "feedback_loop"
    assert policy["repair_dimensions"] == [
        {
            "dimension": "face_naturalness",
            "quality_issue": "face_unnatural",
            "repair_hint": "improve_face_naturalness",
        },
        {
            "dimension": "fashion_material_quality",
            "quality_issue": "stockings_bad",
            "repair_hint": "improve_fashion_material_quality",
        },
    ]
    assert policy["applied_action_types"] == ["repair_low_preference_dimension"]


def test_feedback_policy_applies_safe_reframe_provider_retry():
    from agent.visual.feedback_policy import resolve_visual_feedback_policy

    policy = resolve_visual_feedback_policy(
        {
            "next_actions": [
                {
                    "type": "safe_reframe_provider_retry",
                    "track": "provider",
                    "confidence": 0.7,
                    "requires_human_feedback": False,
                    "provider_failure_classes": {"content_moderation": 2, "timeout": 1},
                    "provider_error_codes": {"api_error": 2, "case_timeout": 1},
                }
            ]
        },
        wants_image=True,
        wants_video=True,
        explicit_candidate_budget=None,
        default_candidate_budget=1,
    )

    assert policy["provider_recovery_mode"] == "safe_reframe"
    assert policy["provider_retry_budget"] == 2
    assert policy["provider_failure_context"] == {
        "provider_failure_classes": {"content_moderation": 2, "timeout": 1},
        "provider_error_codes": {"api_error": 2, "case_timeout": 1},
    }
    assert policy["applied_action_types"] == ["safe_reframe_provider_retry"]
