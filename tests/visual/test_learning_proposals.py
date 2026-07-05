def test_learning_proposals_prefer_high_confidence_strategy_and_provider():
    from agent.visual.learning.proposals import propose_visual_policy_updates

    outcomes = {
        "outcomes": [
            {
                "bucket": "visig_glamour",
                "strategy_signature": "vstrat_good",
                "request_count": 24,
                "confidence": 0.86,
                "provider_health": {
                    "attempt_count": 24,
                    "generation_success_rate": 0.92,
                    "policy_failure_rate": 0.0,
                    "providers": {
                        "xai:grok-imagine": {
                            "attempt_count": 24,
                            "generation_success_rate": 0.92,
                            "policy_failure_rate": 0.0,
                        }
                    },
                },
                "delivery": {"delivery_success_rate": 0.96, "duplicate_delivery_count": 0},
                "quality": {"average_confidence": 0.84, "judgment_count": 20},
                "human_feedback": {"average_polarity": 0.75, "human_veto_count": 0},
                "active_learning": {"ask_user_rate": 0.1},
                "disagreement": {"judge_human_disagreement_rate": 0.0},
            }
        ]
    }

    proposals = propose_visual_policy_updates(outcomes)
    proposal_types = {proposal["type"] for proposal in proposals}

    assert "prefer_strategy" in proposal_types
    assert "prefer_provider_for_bucket" in proposal_types
    assert all(proposal["activation_status"] == "shadow" for proposal in proposals)
    assert all("prompt" not in proposal for proposal in proposals)
    assert proposals[0]["evidence_counts"]["request_count"] == 24


def test_learning_proposals_avoid_bad_strategy_and_ask_user_sooner():
    from agent.visual.learning.proposals import propose_visual_policy_updates

    outcomes = {
        "outcomes": [
            {
                "bucket": "visig_portrait",
                "strategy_signature": "vstrat_bad",
                "request_count": 18,
                "confidence": 0.72,
                "provider_health": {
                    "attempt_count": 18,
                    "generation_success_rate": 0.95,
                    "policy_failure_rate": 0.0,
                    "providers": {},
                },
                "delivery": {"delivery_success_rate": 0.90, "duplicate_delivery_count": 0},
                "quality": {"average_confidence": 0.82, "judgment_count": 10},
                "human_feedback": {"average_polarity": -0.8, "human_veto_count": 3},
                "active_learning": {"ask_user_rate": 0.65},
                "disagreement": {"judge_human_disagreement_rate": 0.8},
            }
        ]
    }

    proposals = propose_visual_policy_updates(outcomes)
    proposal_types = {proposal["type"] for proposal in proposals}

    assert "avoid_strategy" in proposal_types
    assert "ask_user_sooner" in proposal_types
    assert all(proposal["activation_status"] == "shadow" for proposal in proposals)


def test_learning_proposals_never_emit_disallowed_mutations():
    from agent.visual.learning.proposals import ALLOWED_PROPOSAL_TYPES
    from agent.visual.learning.proposals import propose_visual_policy_updates

    outcomes = {
        "outcomes": [
            {
                "bucket": "visig_retry",
                "strategy_signature": "vstrat_retry",
                "request_count": 10,
                "confidence": 0.6,
                "provider_health": {
                    "attempt_count": 10,
                    "generation_success_rate": 0.35,
                    "policy_failure_rate": 0.0,
                    "providers": {
                        "xai:grok-video": {
                            "attempt_count": 10,
                            "generation_success_rate": 0.35,
                            "policy_failure_rate": 0.0,
                        }
                    },
                },
                "delivery": {"delivery_success_rate": 0.4, "duplicate_delivery_count": 0},
                "quality": {"average_confidence": 0.45, "judgment_count": 5},
                "human_feedback": {"average_polarity": 0.0, "human_veto_count": 0},
                "retry": {"retry_attempt_count": 5, "retry_success_rate": 0.2},
                "active_learning": {"ask_user_rate": 0.4},
                "disagreement": {"judge_human_disagreement_rate": 0.0},
            }
        ]
    }

    proposals = propose_visual_policy_updates(outcomes)

    assert proposals
    assert {proposal["type"] for proposal in proposals} <= ALLOWED_PROPOSAL_TYPES
    assert not any(proposal["type"] in {"rewrite_prompt", "policy_bypass"} for proposal in proposals)
    assert all(proposal["activation_status"] == "shadow" for proposal in proposals)
