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


def test_reward_model_penalizes_candidate_quality_issues_matching_preferences():
    from agent.visual.reward_model import score_visual_candidate

    profile = {
        "signals": {},
        "issues": {
            "subject_not_attractive": {"penalty": 0.9, "sample_count": 3},
            "stockings_bad": {"penalty": 0.8, "sample_count": 2},
        },
        "sample_count": 6,
    }
    base_candidate = {
        "kind": "image",
        "provider": "fixture",
        "model": "image",
        "hard_gate": {"passed": True},
        "scores": {"final_score": 0.9},
        "judge_scores": {
            "aesthetic_fit": 0.9,
            "reference_adherence": 0.8,
            "novelty": 1.0,
            "motion_quality": 1.0,
        },
    }

    clean = score_visual_candidate(
        {**base_candidate, "artifact_id": "clean", "quality_issues": []},
        provider_stats={"fixture:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0}},
        preference_profile=profile,
    )
    flawed = score_visual_candidate(
        {
            **base_candidate,
            "artifact_id": "flawed",
            "quality_issues": ["subject_not_attractive", "stockings_bad"],
        },
        provider_stats={"fixture:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0}},
        preference_profile=profile,
    )

    assert clean["dimensions"]["user_preference_fit"] > flawed["dimensions"]["user_preference_fit"]
    assert clean["final_score"] > flawed["final_score"]
    assert "matched_preference_issue_subject_not_attractive" in flawed["uncertainty_reasons"]
