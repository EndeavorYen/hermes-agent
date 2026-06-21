def test_reward_model_keeps_provider_and_aesthetic_tracks_separate():
    from agent.visual.reward_model import score_visual_candidate

    result = score_visual_candidate(
        {
            "artifact_id": "var_1",
            "kind": "image",
            "hard_gate": {"passed": True},
            "scores": {"final_score": 0.8},
            "judge_scores": {"aesthetic_fit": 0.4},
        },
        provider_stats={"fixture:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0}},
        preference_profile={"signals": {}, "issues": {}, "sample_count": 0},
    )

    assert result["dimensions"]["provider_reliability"] == 1.0
    assert result["dimensions"]["aesthetic_fit"] == 0.4
    assert result["final_score"] < 1.0
    assert result["confidence"] < 0.8


def test_reward_model_fails_closed_when_hard_gate_fails():
    from agent.visual.reward_model import score_visual_candidate

    result = score_visual_candidate(
        {
            "artifact_id": "var_bad",
            "kind": "image",
            "hard_gate": {"passed": False},
            "scores": {"final_score": 0.9},
        },
        provider_stats={"fixture:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0}},
        preference_profile={"signals": {}, "issues": {}, "sample_count": 10},
    )

    assert result["dimensions"]["artifact_validity"] == 0.0
    assert result["final_score"] == 0.0
