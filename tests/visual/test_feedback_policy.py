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


def test_feedback_policy_preserves_live_quality_trend_action_source():
    from agent.visual.feedback_policy import resolve_visual_feedback_policy

    policy = resolve_visual_feedback_policy(
        {
            "next_actions": [
                {
                    "type": "increase_candidate_budget",
                    "source": "live_quality_trends",
                    "max_candidate_budget": 4,
                    "requires_human_feedback": False,
                },
                {
                    "type": "prefer_image_first_video",
                    "source": "live_quality_trends",
                    "requires_human_feedback": False,
                },
                {
                    "type": "repair_low_preference_dimension",
                    "source": "live_quality_trends",
                    "dimension": "fashion_material_quality",
                    "quality_issue": "stockings_bad",
                    "repair_hint": "improve_fashion_material_quality",
                    "requires_human_feedback": False,
                },
            ],
            "policy_sources": ["feedback_loop", "scheduled_self_validation"],
        },
        wants_image=True,
        wants_video=True,
        explicit_candidate_budget=None,
        default_candidate_budget=1,
    )

    assert policy["candidate_budget"] == 4
    assert policy["candidate_budget_source"] == "live_quality_trends"
    assert policy["prefer_image_first_video"] is True
    assert policy["rerank_before_delivery"] is True
    assert policy["repair_dimensions"] == [
        {
            "dimension": "fashion_material_quality",
            "quality_issue": "stockings_bad",
            "repair_hint": "improve_fashion_material_quality",
            "source": "live_quality_trends",
        }
    ]
    assert policy["applied_action_sources"] == ["live_quality_trends"]


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
        "candidate_budget": None,
        "prompt_mutation_allowed": False,
    }
    assert policy["applied_action_types"] == ["prefer_strategy"]


def test_feedback_policy_uses_proven_strategy_budget_over_stale_budget_increase():
    from agent.visual.feedback_policy import resolve_visual_feedback_policy

    policy = resolve_visual_feedback_policy(
        {
            "next_actions": [
                {
                    "type": "increase_candidate_budget",
                    "max_candidate_budget": 4,
                    "source": "feedback_loop",
                    "requires_human_feedback": False,
                },
                {
                    "type": "prefer_strategy",
                    "track": "aesthetic",
                    "strategy_signature": "image_first_rank_then_video",
                    "source": "live_quality_burn",
                    "bucket": "live_visual_agent_mode",
                    "activation_status": "shadow",
                    "confidence": 0.82,
                    "candidate_budget": 2,
                    "requires_human_feedback": False,
                },
            ],
            "policy_sources": ["feedback_loop", "scheduled_self_validation"],
        },
        wants_image=True,
        wants_video=True,
        explicit_candidate_budget=None,
        default_candidate_budget=2,
    )

    assert policy["candidate_budget"] == 2
    assert policy["candidate_budget_source"] == "live_quality_burn"
    assert policy["prefer_image_first_video"] is True
    assert policy["rerank_before_delivery"] is True
    assert policy["strategy_preference"]["candidate_budget"] == 2
    assert policy["applied_action_types"] == ["increase_candidate_budget", "prefer_strategy"]


def test_feedback_policy_makes_image_first_video_action_executable():
    from agent.visual.feedback_policy import resolve_visual_feedback_policy

    policy = resolve_visual_feedback_policy(
        {
            "next_actions": [
                {
                    "type": "prefer_image_first_video",
                    "track": "provider",
                    "reason": "live_quality_burn_video_missing_after_image",
                    "confidence": 0.78,
                    "requires_human_feedback": False,
                }
            ]
        },
        wants_image=True,
        wants_video=True,
        explicit_candidate_budget=None,
        default_candidate_budget=1,
    )

    assert policy["prefer_image_first_video"] is True
    assert policy["rerank_before_delivery"] is True
    assert policy["candidate_budget"] == 2
    assert policy["candidate_budget_source"] == "feedback_loop"
    assert policy["applied_action_types"] == ["prefer_image_first_video"]


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


def test_feedback_policy_applies_quality_focus_operator_actions():
    from agent.visual.feedback_policy import resolve_visual_feedback_policy

    policy = resolve_visual_feedback_policy(
        {
            "next_actions": [
                {
                    "type": "apply_quality_focus_operator",
                    "track": "aesthetic",
                    "source": "live_quality_burn",
                    "focus": "legwear_material",
                    "dimension": "fashion_material_quality",
                    "strategy_operator": "refine_legwear_material",
                    "repair_hint": "improve_fashion_material_quality",
                    "quality_issues": ["stockings_bad"],
                    "requires_human_feedback": False,
                }
            ],
            "policy_sources": ["feedback_loop", "scheduled_self_validation"],
        },
        wants_image=True,
        wants_video=True,
        explicit_candidate_budget=None,
        default_candidate_budget=1,
    )

    assert policy["candidate_budget"] == 2
    assert policy["candidate_budget_source"] == "live_quality_burn"
    assert policy["rerank_before_delivery"] is True
    assert policy["quality_repair_mode"] == "preferred"
    assert policy["quality_repair_modes"]["image"] == "preferred"
    assert policy["repair_dimensions"] == [
        {
            "dimension": "fashion_material_quality",
            "quality_issue": "stockings_bad",
            "repair_hint": "improve_fashion_material_quality",
        }
    ]
    assert policy["quality_focus_operators"] == [
        {
            "focus": "legwear_material",
            "dimension": "fashion_material_quality",
            "strategy_operator": "refine_legwear_material",
            "source": "live_quality_burn",
        }
    ]
    assert policy["applied_action_types"] == ["apply_quality_focus_operator"]
    assert policy["applied_action_sources"] == ["live_quality_burn"]


def test_feedback_policy_applies_preference_dimension_evidence_action_without_prompt_repair():
    from agent.visual.feedback_policy import resolve_visual_feedback_policy

    policy = resolve_visual_feedback_policy(
        {
            "next_actions": [
                {
                    "type": "require_preference_dimension_evidence",
                    "track": "evaluation",
                    "source": "live_quality_burn",
                    "focus": "adult_fashion_portrait",
                    "dimension": "subject_beauty",
                    "evaluation_operator": "inline_vision_preference_dimensions",
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

    assert policy["candidate_budget"] == 1
    assert policy["candidate_budget_source"] == "default"
    assert policy["quality_repair_mode"] == "default"
    assert policy["repair_dimensions"] == []
    assert policy["require_preference_dimension_evidence"] is True
    assert policy["required_preference_dimensions"] == ["subject_beauty"]
    assert policy["applied_action_types"] == ["require_preference_dimension_evidence"]
    assert policy["applied_action_sources"] == ["live_quality_burn"]


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
