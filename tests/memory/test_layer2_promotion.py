from memory.layer2_promotion import L1Pressure, evaluate_promotion


def test_evaluate_promotion_allows_high_support_when_l1_has_room():
    decision = evaluate_promotion(
        {
            "canonical_text": "User prefers concise Traditional Chinese stock memos",
            "support_count": 4,
            "contradict_count": 0,
            "status": "active",
            "routing_destination": "user",
        },
        pressure=L1Pressure(current_chars=800, char_limit=2200),
    )

    assert decision.allowed is True
    assert decision.reason == "high_confidence_and_l1_room"


def test_evaluate_promotion_blocks_when_l1_is_near_limit():
    decision = evaluate_promotion(
        {
            "canonical_text": "Repository uses uv",
            "support_count": 5,
            "contradict_count": 0,
            "status": "active",
            "routing_destination": "prior",
        },
        pressure=L1Pressure(current_chars=2150, char_limit=2200),
    )

    assert decision.allowed is False
    assert decision.reason == "l1_pressure_too_high"
    assert decision.recommended_action == "keep_in_layer2"


def test_evaluate_promotion_blocks_contradicted_or_quarantined_candidates():
    decision = evaluate_promotion(
        {
            "canonical_text": "Weak memory",
            "support_count": 4,
            "contradict_count": 4,
            "status": "quarantine",
            "routing_destination": "user",
        },
        pressure=L1Pressure(current_chars=500, char_limit=2200),
    )

    assert decision.allowed is False
    assert decision.reason == "not_recallable_or_low_net_support"
