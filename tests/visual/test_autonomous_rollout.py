from __future__ import annotations


def test_autonomous_rollout_allows_low_risk_high_evidence_candidate():
    from agent.visual.autonomous_rollout import evaluate_autonomous_rollout_candidate

    decision = evaluate_autonomous_rollout_candidate(
        {
            "type": "prefer_provider_for_bucket",
            "confidence": 0.92,
            "activation_status": "shadow",
            "evidence_counts": {
                "request_count": 40,
                "attempt_count": 40,
                "delivery_count": 20,
                "judgment_count": 20,
                "feedback_count": 6,
                "human_veto_count": 0,
            },
        },
        runtime_checks={
            "duplicate_delivery_count": 0,
            "missing_source_metadata_count": 0,
            "prompt_mutation_read_count": 0,
            "unsafe_activation_count": 0,
        },
        autonomy_level=2,
    )

    assert decision["decision"] == "controlled_candidate"
    assert decision["allowed"] is True
    assert decision["reasons"] == []


def test_autonomous_rollout_blocks_prompt_mutation_and_low_evidence():
    from agent.visual.autonomous_rollout import evaluate_autonomous_rollout_candidate

    decision = evaluate_autonomous_rollout_candidate(
        {
            "type": "rewrite_prompt",
            "confidence": 0.99,
            "activation_status": "shadow",
            "evidence_counts": {"request_count": 2, "human_veto_count": 0},
        },
        runtime_checks={"prompt_mutation_read_count": 1},
        autonomy_level=2,
    )

    assert decision["decision"] == "shadow_only"
    assert decision["allowed"] is False
    assert "proposal_type_not_low_risk" in decision["reasons"]
    assert "prompt_mutation_detected" in decision["reasons"]


def test_autonomous_rollout_requires_autonomy_level_two():
    from agent.visual.autonomous_rollout import evaluate_autonomous_rollout_candidate

    decision = evaluate_autonomous_rollout_candidate(
        {
            "type": "reduce_video_duration",
            "confidence": 0.9,
            "activation_status": "shadow",
            "evidence_counts": {
                "request_count": 40,
                "attempt_count": 40,
                "delivery_count": 20,
                "judgment_count": 20,
                "feedback_count": 6,
                "human_veto_count": 0,
            },
        },
        runtime_checks={},
        autonomy_level=1,
    )

    assert decision["allowed"] is False
    assert "autonomy_level_below_controlled_threshold" in decision["reasons"]
