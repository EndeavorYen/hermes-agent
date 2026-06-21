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


def test_strategy_policy_reads_latest_safe_controlled_activation(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.strategy_activation import record_strategy_activation
    from agent.visual.strategy_policy import find_controlled_strategy_plan

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    activation_id = record_strategy_activation(
        ledger,
        shadow_update_id="vsh_demo",
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        activation_status="controlled",
        promotion_decision={
            "decision": "promote_controlled",
            "allowed": True,
            "confidence": 0.91,
            "reasons": [],
        },
        metadata={"atom_signatures": ["composition.full_subject_visible@v1"]},
    )

    plan = find_controlled_strategy_plan(ledger, intent_signature="visig_demo")

    assert plan is not None
    assert plan.strategy_signature == "vstrat_demo"
    assert plan.activation_status == "controlled"
    assert plan.prompt_mutation_allowed is False
    assert plan.to_record()["activation_id"] == activation_id


def test_strategy_policy_ignores_unsafe_or_rolled_back_activation(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.strategy_activation import record_strategy_activation
    from agent.visual.strategy_policy import find_controlled_strategy_plan

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    controlled_id = record_strategy_activation(
        ledger,
        shadow_update_id="vsh_demo",
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        activation_status="controlled",
        promotion_decision={"decision": "promote_controlled", "allowed": True},
    )
    record_strategy_activation(
        ledger,
        shadow_update_id="vsh_demo",
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        activation_status="rolled_back",
        promotion_decision={"decision": "rollback", "allowed": False},
        rollback_of=controlled_id,
    )
    record_strategy_activation(
        ledger,
        shadow_update_id="vsh_unsafe",
        intent_signature="visig_demo",
        strategy_signature="vstrat_unsafe",
        activation_status="controlled",
        promotion_decision={"decision": "shadow_only", "allowed": False},
    )

    plan = find_controlled_strategy_plan(ledger, intent_signature="visig_demo")

    assert plan is None
