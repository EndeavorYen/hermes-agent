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
