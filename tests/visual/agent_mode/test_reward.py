from __future__ import annotations


def test_reward_separates_provider_and_preference_tracks():
    from agent.visual.agent_mode.reward import score_visual_outcome

    reward = score_visual_outcome(
        {
            "artifact_valid": True,
            "delivered": True,
            "provider_error_type": None,
            "feedback_polarity": -1.0,
            "composition_score": 0.8,
        }
    )

    assert reward.provider_health == 1.0
    assert reward.artifact_quality == 0.8
    assert reward.delivery_health == 1.0
    assert reward.preference_score < 0.5
    assert reward.overall_score < 1.0


def test_reward_penalizes_provider_failure_without_treating_it_as_preference():
    from agent.visual.agent_mode.reward import score_visual_outcome

    reward = score_visual_outcome(
        {
            "artifact_valid": False,
            "delivered": False,
            "provider_error_type": "content_moderation",
            "feedback_polarity": None,
            "composition_score": 0.9,
        }
    )

    assert reward.provider_health == 0.0
    assert reward.artifact_quality == 0.0
    assert reward.delivery_health == 0.0
    assert reward.preference_score == 0.5
    assert reward.overall_score < 0.3
    assert reward.confidence < 1.0


def test_reward_clamps_inputs_and_exposes_components():
    from agent.visual.agent_mode.reward import score_visual_outcome

    reward = score_visual_outcome(
        {
            "artifact_quality": 1.5,
            "delivery_health": -0.5,
            "provider_health": 2.0,
            "preference_score": -1.0,
            "confidence": 4.0,
        }
    )

    assert reward.provider_health == 1.0
    assert reward.artifact_quality == 1.0
    assert reward.delivery_health == 0.0
    assert reward.preference_score == 0.0
    assert reward.confidence == 1.0
    assert reward.components["provider_health"] == 1.0
