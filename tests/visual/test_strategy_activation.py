import pytest


def test_strategy_activation_records_controlled_decision(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.promotion_policy import evaluate_shadow_promotion
    from agent.visual.shadow_learning import record_shadow_update
    from agent.visual.strategy_activation import record_strategy_activation

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    shadow_update_id = record_shadow_update(
        ledger,
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="composition.full_subject_visible@v1",
        proposed_change={"increase_weight": 0.05},
        evidence={"sample_count": 25},
        confidence=0.9,
    )
    promotion = evaluate_shadow_promotion(
        {
            "bucket_request_count": 25,
            "successful_artifact_count": 12,
            "successful_delivery_count": 10,
            "provider_confidence": 0.95,
            "shadow_confidence": 0.90,
            "duplicate_delivery_count": 0,
            "missing_source_metadata_count": 0,
            "recent_negative_feedback_count": 0,
            "human_veto_count": 0,
            "judge_human_disagreement_rate": 0.0,
            "self_validation_success": True,
        },
        operator_approved=True,
    )

    activation_id = record_strategy_activation(
        ledger,
        shadow_update_id=shadow_update_id,
        intent_signature="visig_demo",
        strategy_signature="composition.full_subject_visible@v1",
        activation_status="controlled",
        promotion_decision=promotion.to_record(),
    )

    row = ledger.get_strategy_activation(activation_id)
    assert row["id"].startswith("vsa_")
    assert row["shadow_update_id"] == shadow_update_id
    assert row["activation_status"] == "controlled"
    assert row["promotion_decision"]["allowed"] is True


def test_strategy_activation_records_rollback_without_deleting_source(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.strategy_activation import record_strategy_activation

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()

    controlled_id = record_strategy_activation(
        ledger,
        shadow_update_id="vsh_demo",
        intent_signature="visig_demo",
        strategy_signature="composition.full_subject_visible@v1",
        activation_status="controlled",
        promotion_decision={"decision": "promote_controlled", "allowed": True},
    )
    rollback_id = record_strategy_activation(
        ledger,
        shadow_update_id="vsh_demo",
        intent_signature="visig_demo",
        strategy_signature="composition.full_subject_visible@v1",
        activation_status="rolled_back",
        promotion_decision={"decision": "rollback", "allowed": False},
        rollback_of=controlled_id,
    )

    controlled = ledger.get_strategy_activation(controlled_id)
    rollback = ledger.get_strategy_activation(rollback_id)
    assert controlled["activation_status"] == "controlled"
    assert rollback["activation_status"] == "rolled_back"
    assert rollback["rollback_of"] == controlled_id


def test_strategy_activation_rejects_unknown_status(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.strategy_activation import record_strategy_activation

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()

    with pytest.raises(ValueError, match="unsupported activation_status"):
        record_strategy_activation(
            ledger,
            shadow_update_id="vsh_demo",
            intent_signature="visig_demo",
            strategy_signature="composition.full_subject_visible@v1",
            activation_status="active",
            promotion_decision={"decision": "promote_controlled", "allowed": True},
        )


def test_strategy_activation_rejects_controlled_prompt_mutation(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.strategy_activation import record_strategy_activation

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()

    with pytest.raises(ValueError, match="controlled strategy activation must be read-only"):
        record_strategy_activation(
            ledger,
            shadow_update_id="vsh_demo",
            intent_signature="visig_demo",
            strategy_signature="composition.full_subject_visible@v1",
            activation_status="controlled",
            promotion_decision={"decision": "promote_controlled", "allowed": True},
            metadata={"prompt_mutation_allowed": True},
        )
