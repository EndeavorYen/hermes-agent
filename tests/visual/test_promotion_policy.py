def test_promotion_policy_blocks_under_sampled_bucket():
    from agent.visual.promotion_policy import evaluate_shadow_promotion

    decision = evaluate_shadow_promotion(
        {
            "bucket_request_count": 3,
            "successful_artifact_count": 2,
            "provider_confidence": 0.95,
            "shadow_confidence": 0.90,
            "duplicate_delivery_count": 0,
            "missing_source_metadata_count": 0,
            "recent_negative_feedback_count": 0,
            "self_validation_success": True,
        },
        operator_approved=True,
    )

    assert decision.allowed is False
    assert decision.decision == "shadow_only"
    assert "insufficient_bucket_requests" in decision.reasons


def test_promotion_policy_requires_operator_approval():
    from agent.visual.promotion_policy import evaluate_shadow_promotion

    decision = evaluate_shadow_promotion(
        {
            "bucket_request_count": 25,
            "successful_artifact_count": 12,
            "provider_confidence": 0.95,
            "shadow_confidence": 0.90,
            "duplicate_delivery_count": 0,
            "missing_source_metadata_count": 0,
            "recent_negative_feedback_count": 0,
            "self_validation_success": True,
        },
        operator_approved=False,
    )

    assert decision.allowed is False
    assert decision.decision == "blocked"
    assert "operator_approval_required" in decision.reasons


def test_promotion_policy_allows_controlled_when_all_gates_pass():
    from agent.visual.promotion_policy import evaluate_shadow_promotion

    decision = evaluate_shadow_promotion(
        {
            "bucket_request_count": 25,
            "successful_artifact_count": 12,
            "provider_confidence": 0.95,
            "shadow_confidence": 0.90,
            "duplicate_delivery_count": 0,
            "missing_source_metadata_count": 0,
            "recent_negative_feedback_count": 0,
            "self_validation_success": True,
        },
        operator_approved=True,
    )

    assert decision.allowed is True
    assert decision.decision == "promote_controlled"
    assert decision.confidence == 0.9


def test_promotion_policy_treats_missing_evidence_as_conservative_failure():
    from agent.visual.promotion_policy import evaluate_shadow_promotion

    decision = evaluate_shadow_promotion({}, operator_approved=True)

    assert decision.allowed is False
    assert decision.decision == "shadow_only"
    assert "self_validation_failed" in decision.reasons
    assert decision.observed["bucket_request_count"] == 0
    assert decision.confidence == 0.0
