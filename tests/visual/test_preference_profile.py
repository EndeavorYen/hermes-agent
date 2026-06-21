def test_preference_profile_uses_feedback_ewma_by_issue_and_signal(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.preference_profile import build_preference_profile

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    artifact_id = ledger.record_artifact(request_id=request_id, kind="image", content_hash="abc")
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="A 不錯，有美腿，但臉不自然",
        polarity=0.4,
        parsed={"signals": ["legs_positive"], "issues": ["face_unnatural"]},
    )

    profile = build_preference_profile(ledger, bucket="visig_demo")

    assert profile["bucket"] == "visig_demo"
    assert profile["signals"]["legs_positive"]["weight"] > 0
    assert profile["issues"]["face_unnatural"]["penalty"] > 0
    assert profile["sample_count"] == 1


def test_preference_profile_is_private_safe_and_low_confidence_with_sparse_data(tmp_path):
    import json

    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.preference_profile import build_preference_profile

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    ledger.record_feedback(
        request_id=request_id,
        feedback_text="private raw feedback: G4 比較好",
        polarity=0.7,
        parsed={"signals": ["composition_positive"], "issues": []},
    )

    profile = build_preference_profile(ledger, bucket="visig_demo")

    serialized = json.dumps(profile, ensure_ascii=False)
    assert "private raw feedback" not in serialized
    assert profile["confidence"] < 1.0
    assert profile["minimum_confidence_sample_count"] == 5
