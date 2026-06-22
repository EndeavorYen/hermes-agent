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


def test_quality_calibration_report_fails_when_judge_disagrees_with_enough_feedback(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.calibration import build_quality_calibration_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    attempt_id = ledger.record_attempt(request_id=request_id, status="completed", provider="fixture", model="image")

    for index in range(6):
        artifact_id = ledger.record_artifact(
            request_id=request_id,
            attempt_id=attempt_id,
            kind="image",
            content_hash=f"artifact-{index}",
            freshness_status="fresh",
            is_stable=True,
        )
        human_liked = index >= 4
        judge_score = 0.9 if not human_liked else 0.2
        ledger.record_judgment(
            request_id=request_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            judge_name="visual_quality_judge",
            score=judge_score,
            verdict="pass" if judge_score >= 0.5 else "fail",
            details={"uncertainty_reasons": []},
        )
        ledger.record_feedback(
            request_id=request_id,
            artifact_id=artifact_id,
            feedback_text="private feedback text",
            polarity=1.0 if human_liked else -1.0,
            parsed={"source": "explicit"},
        )

    report = build_quality_calibration_report(tmp_path / "visual.sqlite3")

    assert report["success"] is False
    assert report["matched_feedback_count"] == 6
    assert report["judge_human_disagreement_rate"] == 1.0
    assert "judge_human_disagreement_rate_high" in report["failures"]
    assert "private feedback text" not in str(report)


def test_quality_calibration_report_fails_when_human_feedback_has_no_matching_judgments(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.calibration import build_quality_calibration_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    attempt_id = ledger.record_attempt(request_id=request_id, status="completed", provider="fixture", model="image")

    for index in range(5):
        artifact_id = ledger.record_artifact(
            request_id=request_id,
            attempt_id=attempt_id,
            kind="image",
            content_hash=f"unjudged-{index}",
            freshness_status="fresh",
            is_stable=True,
        )
        ledger.record_feedback(
            request_id=request_id,
            artifact_id=artifact_id,
            feedback_text="private unmatched feedback",
            polarity=-1.0,
            parsed={"source": "explicit"},
        )

    report = build_quality_calibration_report(tmp_path / "visual.sqlite3")

    assert report["success"] is False
    assert report["unmatched_human_feedback_count"] == 5
    assert "human_feedback_unmatched_to_judgments" in report["failures"]
    assert "private unmatched feedback" not in str(report)


def test_quality_calibration_report_uses_latest_quality_judgment_per_artifact(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.calibration import build_quality_calibration_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    attempt_id = ledger.record_attempt(request_id=request_id, status="completed", provider="fixture", model="image")
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        content_hash="same-artifact",
        freshness_status="fresh",
        is_stable=True,
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.9,
        verdict="pass",
        details={"source": "old_weak_judge"},
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.2,
        verdict="review",
        details={"source": "new_vision_judge"},
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="private negative feedback",
        polarity=-1.0,
        parsed={"source": "explicit"},
    )

    report = build_quality_calibration_report(tmp_path / "visual.sqlite3")

    assert report["matched_feedback_count"] == 1
    assert report["counts"]["judge_human_agreement"] == 1
    assert report["counts"]["judge_human_disagreement"] == 0
    assert "private negative feedback" not in str(report)


def test_quality_calibration_report_uses_quality_alignment_not_confidence_as_sentiment(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.calibration import build_quality_calibration_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    attempt_id = ledger.record_attempt(request_id=request_id, status="completed", provider="fixture", model="image")
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        content_hash="quality-issue-artifact",
        freshness_status="fresh",
        is_stable=True,
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.9,
        verdict="pass",
        details={
            "confidence": 0.9,
            "scores": {"aesthetic_fit": 0.9},
            "quality_issues": ["stockings_bad"],
        },
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="private negative feedback",
        polarity=-1.0,
        parsed={"source": "explicit"},
    )

    report = build_quality_calibration_report(tmp_path / "visual.sqlite3")

    assert report["matched_feedback_count"] == 1
    assert report["counts"]["judge_human_agreement"] == 1
    assert report["counts"]["judge_human_disagreement"] == 0
    assert "private negative feedback" not in str(report)
