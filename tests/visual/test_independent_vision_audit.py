def test_parse_vision_judge_analysis_extracts_json_from_text():
    from agent.visual.independent_vision_audit import parse_vision_judge_analysis

    observation = parse_vision_judge_analysis(
        """
        ```json
        {
          "reference_adherence": 0.8,
          "face_quality": 0.3,
          "visual_appeal": 0.4,
          "composition": 0.7,
          "pose_novelty": 0.6,
          "stocking_quality": 0.2
        }
        ```
        """
    )

    assert observation["subject_quality"] == 0.3
    assert "face_quality_low" in observation["artifact_defects"]
    assert "stockings_quality_low" in observation["artifact_defects"]


def test_independent_vision_audit_dry_run_counts_feedback_artifacts(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.independent_vision_audit import audit_independent_vision_judgments

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    artifact_id = _record_feedback_image(ledger)

    report = audit_independent_vision_judgments(tmp_path / "visual.sqlite3", dry_run=True)

    assert report["success"] is True
    assert report["candidate_count"] == 1
    assert report["created_count"] == 0
    assert report["artifact_ids"] == [artifact_id]


def test_independent_vision_audit_records_latest_visual_quality_judgment(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.calibration import build_quality_calibration_report
    from agent.visual.independent_vision_audit import audit_independent_vision_judgments

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    request_id, attempt_id, artifact_id = _record_feedback_image_with_ids(ledger)
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.9,
        verdict="pass",
        details={"source": "old_metadata_judge"},
    )

    def fake_analyzer(_artifact):
        return {
            "analysis": {
                "face_quality": 0.2,
                "visual_appeal": 0.3,
                "composition": 0.7,
                "stocking_quality": 0.2,
            }
        }

    report = audit_independent_vision_judgments(
        tmp_path / "visual.sqlite3",
        analyzer=fake_analyzer,
    )
    calibration = build_quality_calibration_report(tmp_path / "visual.sqlite3")
    judgments = ledger._list("visual_judgments")

    assert report["success"] is True
    assert report["created_count"] == 1
    assert judgments[-1]["metadata"]["source"] == "independent_vision_judge"
    assert judgments[-1]["details"]["quality_issues"] == [
        "subject_not_attractive",
        "not_beautiful",
        "stockings_bad",
    ]
    assert calibration["matched_feedback_count"] == 1
    assert calibration["counts"]["judge_human_agreement"] == 1
    assert calibration["counts"]["judge_human_disagreement"] == 0


def test_independent_vision_audit_does_not_record_failed_analyzer_result(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.independent_vision_audit import audit_independent_vision_judgments

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    _record_feedback_image(ledger)

    report = audit_independent_vision_judgments(
        tmp_path / "visual.sqlite3",
        analyzer=lambda _artifact: {"success": False, "analysis": "Connection error."},
    )

    assert report["success"] is False
    assert report["created_count"] == 0
    assert report["error_count"] == 1
    assert ledger._list("visual_judgments") == []


def _record_feedback_image(ledger):
    return _record_feedback_image_with_ids(ledger)[2]


def _record_feedback_image_with_ids(ledger):
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    attempt_id = ledger.record_attempt(request_id=request_id, status="completed", provider="fixture", model="image")
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/vision-audit-image.jpg",
        content_hash="vision-audit-image-hash",
        mime_type="image/jpeg",
        width=1024,
        height=1024,
        freshness_status="fresh",
        is_stable=True,
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="private negative feedback",
        polarity=-1.0,
        parsed={"source": "explicit"},
    )
    return request_id, attempt_id, artifact_id
