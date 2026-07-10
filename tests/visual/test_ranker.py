def test_ranker_selects_highest_fresh_candidate_and_excludes_failed_gate():
    from agent.visual.ranker import rank_visual_candidates

    decision = rank_visual_candidates(
        request_id="vrq_test",
        candidates=[
            {
                "attempt_id": "vat_stale",
                "artifact_id": "var_stale",
                "scores": {"final_score": 0.95},
                "hard_gate": {"passed": False},
            },
            {
                "attempt_id": "vat_good",
                "artifact_id": "var_good",
                "scores": {"final_score": 0.78},
                "hard_gate": {"passed": True},
            },
        ],
        post_threshold=0.70,
        ask_threshold=0.55,
    )

    assert decision.version == "visual_ranker.v0.1"
    assert decision.decision == "post"
    assert decision.selected_artifact_id == "var_good"


def test_ranker_asks_user_when_top_candidate_is_usable_but_weak():
    from agent.visual.ranker import rank_visual_candidates

    decision = rank_visual_candidates(
        request_id="vrq_test",
        candidates=[
            {
                "attempt_id": "vat_ok",
                "artifact_id": "var_ok",
                "scores": {"final_score": 0.62},
                "hard_gate": {"passed": True},
            }
        ],
        post_threshold=0.70,
        ask_threshold=0.55,
    )

    assert decision.decision == "ask_user"
    assert decision.selected_artifact_id == "var_ok"


def test_ranker_retries_when_all_candidates_fail_hard_gate():
    from agent.visual.ranker import rank_visual_candidates

    decision = rank_visual_candidates(
        request_id="vrq_test",
        candidates=[
            {
                "attempt_id": "vat_failed",
                "artifact_id": "var_failed",
                "scores": {"final_score": 0.9},
                "hard_gate": {"passed": False},
            }
        ],
    )

    assert decision.decision == "retry"
    assert decision.selected_artifact_id is None


def test_ranker_fails_when_no_candidates_exist():
    from agent.visual.ranker import rank_visual_candidates

    decision = rank_visual_candidates(request_id="vrq_test", candidates=[])

    assert decision.decision == "fail"
    assert decision.selected_artifact_id is None


def test_ranker_prefers_reward_score_when_available():
    from agent.visual.ranker import rank_visual_candidates

    decision = rank_visual_candidates(
        request_id="vrq_test",
        candidates=[
            {
                "attempt_id": "vat_old",
                "artifact_id": "var_old",
                "scores": {"final_score": 0.95},
                "reward": {"final_score": 0.45, "confidence": 0.9},
                "hard_gate": {"passed": True},
            },
            {
                "attempt_id": "vat_reward",
                "artifact_id": "var_reward",
                "scores": {"final_score": 0.70},
                "reward": {"final_score": 0.82, "confidence": 0.7},
                "hard_gate": {"passed": True},
            },
        ],
        post_threshold=0.80,
        ask_threshold=0.55,
    )

    assert decision.decision == "post"
    assert decision.selected_artifact_id == "var_reward"


def test_ranker_prefers_preference_aligned_reward_over_generic_high_score():
    from agent.visual.ranker import rank_visual_candidates
    from agent.visual.reward_model import score_visual_candidate

    provider_stats = {"xai:image": {"generation_success_rate": 1.0, "delivery_success_rate": 1.0}}
    preference_profile = {"signals": {}, "issues": {}, "sample_count": 0}
    generic = {
        "attempt_id": "vat_generic",
        "artifact_id": "var_generic",
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
    aligned = {
        "attempt_id": "vat_aligned",
        "artifact_id": "var_aligned",
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
    generic["reward"] = score_visual_candidate(
        generic,
        provider_stats=provider_stats,
        preference_profile=preference_profile,
    )
    aligned["reward"] = score_visual_candidate(
        aligned,
        provider_stats=provider_stats,
        preference_profile=preference_profile,
    )

    decision = rank_visual_candidates(
        request_id="vrq_preference_rank",
        candidates=[generic, aligned],
        post_threshold=0.70,
        ask_threshold=0.55,
    )

    assert decision.decision == "post"
    assert decision.selected_artifact_id == "var_aligned"
