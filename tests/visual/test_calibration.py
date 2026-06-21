def test_quality_calibration_report_compares_judgments_with_human_feedback(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.calibration import build_quality_calibration_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    attempt_id = ledger.record_attempt(request_id=request_id, status="completed", provider="fixture", model="image")
    good_artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        content_hash="good-hash",
        freshness_status="fresh",
        is_stable=True,
    )
    bad_artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        content_hash="bad-hash",
        freshness_status="fresh",
        is_stable=True,
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=good_artifact_id,
        judge_name="visual_quality_judge",
        score=0.82,
        verdict="pass",
        details={"uncertainty_reasons": []},
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=good_artifact_id,
        feedback_text="good image",
        polarity=1.0,
        parsed={"source": "explicit"},
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=bad_artifact_id,
        judge_name="visual_quality_judge",
        score=0.78,
        verdict="pass",
        details={"uncertainty_reasons": ["face_unnatural", "face_unnatural"]},
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=bad_artifact_id,
        feedback_text="bad face",
        polarity=-1.0,
        parsed={"source": "explicit"},
    )

    report = build_quality_calibration_report(tmp_path / "visual.sqlite3")

    assert report["success"] is True
    assert report["counts"]["judged_artifacts"] == 2
    assert report["counts"]["human_positive"] == 1
    assert report["counts"]["human_negative"] == 1
    assert report["counts"]["judge_human_agreement"] == 1
    assert report["counts"]["judge_human_disagreement"] == 1
    assert report["top_uncertainty_reasons"][0] == {"reason": "face_unnatural", "count": 1}
    assert "good image" not in str(report)
    assert "bad face" not in str(report)


def test_quality_calibration_report_missing_ledger_is_success(tmp_path):
    from agent.visual.calibration import build_quality_calibration_report

    report = build_quality_calibration_report(tmp_path / "missing.sqlite3")

    assert report["success"] is True
    assert report["counts"]["judged_artifacts"] == 0
    assert report["counts"]["judge_human_disagreement"] == 0
