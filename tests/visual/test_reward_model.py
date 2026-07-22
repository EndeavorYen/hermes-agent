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


def test_reward_model_penalizes_low_preference_dimensions_even_before_human_profile():
    from agent.visual.reward_model import score_visual_candidate

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
        "quality_issues": [],
    }

    clean = score_visual_candidate(
        {
            **base_candidate,
            "artifact_id": "clean",
            "preference_dimensions": {
                "subject_beauty": 0.84,
                "face_naturalness": 0.86,
                "fashion_material_quality": 0.82,
                "pose_composition": 0.78,
            },
        },
        provider_stats={"fixture:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0}},
        preference_profile={"signals": {}, "issues": {}, "sample_count": 0},
    )
    flawed = score_visual_candidate(
        {
            **base_candidate,
            "artifact_id": "flawed",
            "preference_dimensions": {
                "subject_beauty": 0.34,
                "face_naturalness": 0.28,
                "fashion_material_quality": 0.31,
                "pose_composition": 0.42,
            },
        },
        provider_stats={"fixture:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0}},
        preference_profile={"signals": {}, "issues": {}, "sample_count": 0},
    )

    assert clean["dimensions"]["preference_dimension_fit"] > 0.8
    assert flawed["dimensions"]["preference_dimension_fit"] < 0.4
    assert clean["final_score"] > flawed["final_score"]
    assert "low_preference_dimension_face_naturalness" in flawed["uncertainty_reasons"]


def test_reward_model_strongly_penalizes_low_glamour_preference_dimensions():
    from agent.visual.reward_model import score_visual_candidate

    provider_stats = {"xai:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0}}
    preference_profile = {"signals": {}, "issues": {}, "sample_count": 0}
    generic_high_score = {
        "artifact_id": "generic_high_score",
        "kind": "image",
        "provider": "xai",
        "model": "image",
        "hard_gate": {"passed": True},
        "scores": {"final_score": 0.96},
        "judge_scores": {
            "aesthetic_fit": 0.96,
            "reference_adherence": 0.9,
            "novelty": 0.9,
            "motion_quality": 1.0,
        },
        "preference_dimensions": {
            "subject_beauty": 0.24,
            "face_naturalness": 0.26,
            "glamour_impact": 0.25,
            "fashion_material_quality": 0.28,
            "pose_composition": 0.3,
        },
    }
    aligned_candidate = {
        "artifact_id": "aligned_candidate",
        "kind": "image",
        "provider": "xai",
        "model": "image",
        "hard_gate": {"passed": True},
        "scores": {"final_score": 0.78},
        "judge_scores": {
            "aesthetic_fit": 0.78,
            "reference_adherence": 0.82,
            "novelty": 0.74,
            "motion_quality": 1.0,
        },
        "preference_dimensions": {
            "subject_beauty": 0.82,
            "face_naturalness": 0.84,
            "glamour_impact": 0.8,
            "fashion_material_quality": 0.83,
            "pose_composition": 0.78,
        },
    }

    generic = score_visual_candidate(
        generic_high_score,
        provider_stats=provider_stats,
        preference_profile=preference_profile,
    )
    aligned = score_visual_candidate(
        aligned_candidate,
        provider_stats=provider_stats,
        preference_profile=preference_profile,
    )

    assert aligned["final_score"] > generic["final_score"]
    assert generic["dimensions"]["preference_dimension_fit"] < 0.3
    assert "preference_dimension_soft_gate_penalty" in generic["uncertainty_reasons"]


def test_reward_model_penalizes_reference_role_quality_issues_without_human_profile():
    from agent.visual.reward_model import score_visual_candidate

    provider_stats = {"xai:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0}}
    preference_profile = {"signals": {}, "issues": {}, "sample_count": 0}
    base_candidate = {
        "kind": "image",
        "provider": "xai",
        "model": "image",
        "hard_gate": {"passed": True},
        "scores": {"final_score": 0.9},
        "judge_scores": {
            "aesthetic_fit": 0.9,
            "reference_adherence": 0.82,
            "novelty": 1.0,
            "motion_quality": 1.0,
        },
    }

    clean = score_visual_candidate(
        {**base_candidate, "artifact_id": "clean", "quality_issues": []},
        provider_stats=provider_stats,
        preference_profile=preference_profile,
    )
    drift = score_visual_candidate(
        {
            **base_candidate,
            "artifact_id": "drift",
            "quality_issues": ["reference_identity_drift"],
        },
        provider_stats=provider_stats,
        preference_profile=preference_profile,
    )

    assert clean["final_score"] - drift["final_score"] >= 0.08
    assert drift["dimensions"]["user_preference_fit"] <= 0.25
    assert "candidate_quality_issue_reference_identity_drift" in drift["uncertainty_reasons"]


def test_reward_model_uses_effective_preference_sample_count_for_confidence():
    from agent.visual.reward_model import score_visual_candidate

    result = score_visual_candidate(
        {
            "artifact_id": "candidate",
            "kind": "image",
            "provider": "fixture",
            "model": "image",
            "hard_gate": {"passed": True},
            "scores": {"final_score": 0.9},
            "judge_scores": {
                "aesthetic_fit": 0.9,
                "reference_adherence": 0.9,
                "novelty": 0.9,
                "motion_quality": 0.9,
            },
        },
        provider_stats={"fixture:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0, "attempt_count": 20}},
        preference_profile={
            "signals": {},
            "issues": {},
            "sample_count": 20,
            "effective_sample_count": 1.0,
        },
    )

    assert result["confidence"] < 0.8
    assert "low_preference_sample_count" in result["uncertainty_reasons"]


def test_reward_model_matches_positive_dimension_signals_from_profile():
    from agent.visual.reward_model import score_visual_candidate

    provider_stats = {"fixture:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0, "attempt_count": 20}}
    preference_profile = {
        "sample_count": 6,
        "effective_sample_count": 6,
        "issues": {},
        "signals": {
            "glamour_positive": {"weight": 0.9},
            "fashion_material_positive": {"weight": 0.8},
        },
    }
    base_candidate = {
        "kind": "image",
        "provider": "fixture",
        "model": "image",
        "hard_gate": {"passed": True},
        "scores": {"final_score": 0.8},
        "judge_scores": {
            "aesthetic_fit": 0.8,
            "reference_adherence": 0.8,
            "novelty": 0.8,
            "motion_quality": 1.0,
        },
        "quality_issues": [],
    }

    aligned = score_visual_candidate(
        {
            **base_candidate,
            "artifact_id": "aligned",
            "preference_dimensions": {
                "glamour_impact": 0.86,
                "fashion_material_quality": 0.84,
                "subject_beauty": 0.75,
                "face_naturalness": 0.75,
                "pose_composition": 0.75,
            },
        },
        provider_stats=provider_stats,
        preference_profile=preference_profile,
    )
    generic = score_visual_candidate(
        {
            **base_candidate,
            "artifact_id": "generic",
            "preference_dimensions": {
                "glamour_impact": 0.55,
                "fashion_material_quality": 0.55,
                "subject_beauty": 0.87,
                "face_naturalness": 0.87,
                "pose_composition": 0.87,
            },
        },
        provider_stats=provider_stats,
        preference_profile=preference_profile,
    )

    assert aligned["dimensions"]["user_preference_fit"] > generic["dimensions"]["user_preference_fit"]
    assert aligned["final_score"] > generic["final_score"]
