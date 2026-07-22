def test_combine_weighted_scores_clamps_and_normalizes():
    from agent.visual.eval_dimensions import combine_weighted_scores

    score = combine_weighted_scores(
        scores={
            "artifact_validity": 1.0,
            "provider_reliability": 0.5,
            "aesthetic_fit": 2.0,
        },
        weights={
            "artifact_validity": 2.0,
            "provider_reliability": 1.0,
            "aesthetic_fit": 1.0,
        },
    )

    assert score == 0.875
