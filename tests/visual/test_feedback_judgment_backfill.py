def test_backfill_feedback_judgments_dry_run_does_not_write(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.feedback_judgment_backfill import backfill_feedback_judgments

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    artifact_id = _record_feedback_artifact(ledger)

    report = backfill_feedback_judgments(tmp_path / "visual.sqlite3", dry_run=True)

    assert report["success"] is True
    assert report["backfillable_count"] == 1
    assert report["created_count"] == 0
    assert report["artifact_ids"] == [artifact_id]
    assert ledger._list("visual_judgments") == []


def test_backfill_feedback_judgments_records_missing_visual_quality_judgment(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.calibration import build_quality_calibration_report
    from agent.visual.feedback_judgment_backfill import backfill_feedback_judgments

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    artifact_id = _record_feedback_artifact(ledger)

    report = backfill_feedback_judgments(tmp_path / "visual.sqlite3")

    judgments = ledger._list("visual_judgments")
    calibration = build_quality_calibration_report(tmp_path / "visual.sqlite3")

    assert report["success"] is True
    assert report["created_count"] == 1
    assert report["artifact_ids"] == [artifact_id]
    assert len(judgments) == 1
    assert judgments[0]["judge_name"] == "visual_quality_judge"
    assert "private feedback text" not in str(judgments)
    assert calibration["matched_feedback_count"] == 1
    assert calibration["unmatched_human_feedback_count"] == 0


def test_backfill_feedback_judgments_skips_already_judged_artifacts(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.feedback_judgment_backfill import backfill_feedback_judgments

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    request_id, attempt_id, artifact_id = _record_feedback_artifact_with_ids(ledger)
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.8,
        verdict="pass",
        details={"uncertainty_reasons": []},
    )

    report = backfill_feedback_judgments(tmp_path / "visual.sqlite3")

    assert report["success"] is True
    assert report["backfillable_count"] == 0
    assert report["created_count"] == 0
    assert len(ledger._list("visual_judgments")) == 1


def _record_feedback_artifact(ledger):
    return _record_feedback_artifact_with_ids(ledger)[2]


def _record_feedback_artifact_with_ids(ledger):
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    attempt_id = ledger.record_attempt(request_id=request_id, status="completed", provider="fixture", model="image")
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/backfill-image.jpg",
        content_hash="backfill-image-hash",
        mime_type="image/jpeg",
        width=1024,
        height=1024,
        freshness_status="fresh",
        is_stable=True,
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="private feedback text",
        polarity=-1.0,
        parsed={"source": "explicit"},
    )
    return request_id, attempt_id, artifact_id
