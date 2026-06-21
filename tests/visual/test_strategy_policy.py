def test_strategy_policy_prefers_reliable_high_confidence_atoms():
    from agent.visual.strategy_policy import select_strategy_plan

    plan = select_strategy_plan(
        "visig_demo",
        provider_stats={"xai:image": {"generation_success_rate": 0.9, "attempt_count": 20}},
        preference_profile={"signals": {"legs_positive": {"weight": 0.8}}, "sample_count": 8},
        exploration_rate=0.0,
    )

    assert plan.mode == "exploit"
    assert plan.confidence >= 0.7
    assert plan.strategy_signature


def test_strategy_policy_stays_shadow_and_private_safe():
    import json

    from agent.visual.strategy_policy import select_strategy_plan

    plan = select_strategy_plan(
        "visig_demo",
        provider_stats={},
        preference_profile={"sample_count": 0, "signals": {}, "issues": {}},
        exploration_rate=0.0,
    )

    payload = plan.to_record()
    assert payload["activation_status"] == "shadow"
    assert payload["prompt_mutation_allowed"] is False
    assert "private" not in json.dumps(payload)
