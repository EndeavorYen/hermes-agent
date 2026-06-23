from __future__ import annotations

import json


def test_visual_feedback_loop_proposes_candidate_budget_without_human_feedback(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_feedback_loop_report import build_visual_feedback_loop_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="private prompt must not leak",
        status="completed",
        metadata={"intent_signature": "visig_glamour"},
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/private-result.jpg",
        content_hash="sha256:low-quality",
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.41,
        verdict="fail",
        details={"scores": {"beauty": 0.35, "composition": 0.44}},
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        platform="slack",
        destination_id="C123",
        delivery_status="sent",
    )

    report = build_visual_feedback_loop_report(tmp_path / "visual.sqlite3")
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["success"] is True
    assert report["counts"]["human_feedback_count"] == 0
    assert report["signals"]["aesthetic"]["low_quality_judgment_count"] == 1
    assert report["self_review"]["reduces_human_intervention"] is True
    assert _action_types(report) >= {"increase_candidate_budget", "rerank_before_slack"}
    assert "private prompt must not leak" not in encoded
    assert "/tmp/private-result.jpg" not in encoded


def test_visual_feedback_loop_extracts_dimension_repairs_from_judge_details(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_feedback_loop_report import build_visual_feedback_loop_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="private prompt must not leak",
        status="completed",
        metadata={"intent_signature": "visig_glamour"},
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/private-low-dimension.jpg",
        content_hash="sha256:low-dimension",
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.44,
        verdict="fail",
        details={
            "quality_issues": ["subject_not_attractive", "stockings_bad"],
            "preference_dimensions": {
                "subject_beauty": 0.34,
                "face_naturalness": 0.76,
                "fashion_material_quality": 0.31,
                "pose_composition": 0.78,
            },
        },
    )

    report = build_visual_feedback_loop_report(tmp_path / "visual.sqlite3")
    actions = [
        action
        for action in report["next_actions"]
        if action["type"] == "repair_low_preference_dimension"
    ]
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["success"] is True
    assert report["signals"]["aesthetic"]["preference_dimension_failures"] == [
        {
            "dimension": "subject_beauty",
            "issue": "subject_not_attractive",
            "score": 0.34,
            "count": 1,
        },
        {
            "dimension": "fashion_material_quality",
            "issue": "stockings_bad",
            "score": 0.31,
            "count": 1,
        },
    ]
    assert actions == [
        {
            "type": "repair_low_preference_dimension",
            "track": "aesthetic",
            "reason": "feedback_loop_preference_dimension_low",
            "confidence": 0.74,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "dimension": "subject_beauty",
            "quality_issue": "subject_not_attractive",
            "repair_hint": "improve_subject_beauty",
            "modalities": ["image"],
        },
        {
            "type": "repair_low_preference_dimension",
            "track": "aesthetic",
            "reason": "feedback_loop_preference_dimension_low",
            "confidence": 0.74,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "dimension": "fashion_material_quality",
            "quality_issue": "stockings_bad",
            "repair_hint": "improve_fashion_material_quality",
            "modalities": ["image"],
        },
    ]
    assert "private prompt must not leak" not in encoded
    assert "/tmp/private-low-dimension.jpg" not in encoded


def test_visual_feedback_loop_extracts_dimension_repairs_from_human_feedback(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.feedback import parse_visual_feedback
    from scripts.visual_feedback_loop_report import build_visual_feedback_loop_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="private prompt must not leak",
        status="completed",
        metadata={"intent_signature": "visig_glamour"},
    )
    feedback = parse_visual_feedback("幾個問題：人物太醜，絲襪太醜，構圖很普普，影片太慢")
    ledger.record_feedback(
        request_id=request_id,
        feedback_text=feedback.text,
        polarity=feedback.polarity,
        parsed=feedback.parsed,
    )

    report = build_visual_feedback_loop_report(tmp_path / "visual.sqlite3")
    actions = [
        action
        for action in report["next_actions"]
        if action["type"] == "repair_low_preference_dimension"
    ]
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["success"] is True
    assert report["signals"]["human_feedback"]["feedback_issue_counts"] == {
        "composition_bad": 1,
        "static_video": 1,
        "stockings_bad": 1,
        "subject_not_attractive": 1,
        "not_beautiful": 1,
    }
    assert report["signals"]["aesthetic"]["preference_dimension_failures"] == [
        {
            "dimension": "subject_beauty",
            "issue": "subject_not_attractive",
            "score": None,
            "count": 1,
        },
        {
            "dimension": "fashion_material_quality",
            "issue": "stockings_bad",
            "score": None,
            "count": 1,
        },
        {
            "dimension": "pose_composition",
            "issue": "composition_bad",
            "score": None,
            "count": 1,
        },
        {
            "dimension": "motion_quality",
            "issue": "motion_bad",
            "score": None,
            "count": 1,
        },
    ]
    assert actions == [
        {
            "type": "repair_low_preference_dimension",
            "track": "aesthetic",
            "reason": "feedback_loop_preference_dimension_low",
            "confidence": 0.74,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "dimension": "subject_beauty",
            "quality_issue": "subject_not_attractive",
            "repair_hint": "improve_subject_beauty",
            "modalities": ["image"],
        },
        {
            "type": "repair_low_preference_dimension",
            "track": "aesthetic",
            "reason": "feedback_loop_preference_dimension_low",
            "confidence": 0.74,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "dimension": "fashion_material_quality",
            "quality_issue": "stockings_bad",
            "repair_hint": "improve_fashion_material_quality",
            "modalities": ["image"],
        },
        {
            "type": "repair_low_preference_dimension",
            "track": "aesthetic",
            "reason": "feedback_loop_preference_dimension_low",
            "confidence": 0.74,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "dimension": "pose_composition",
            "quality_issue": "composition_bad",
            "repair_hint": "improve_pose_composition",
            "modalities": ["image"],
        },
        {
            "type": "repair_low_preference_dimension",
            "track": "aesthetic",
            "reason": "feedback_loop_preference_dimension_low",
            "confidence": 0.74,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "dimension": "motion_quality",
            "quality_issue": "motion_bad",
            "repair_hint": "improve_motion_quality",
            "modalities": ["video"],
        },
    ]
    assert "private prompt must not leak" not in encoded
    assert "幾個問題" not in encoded


def test_visual_feedback_loop_prefers_image_first_after_video_failure(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_feedback_loop_report import build_visual_feedback_loop_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        status="completed",
        metadata={"intent_signature": "visig_video"},
        normalized_intent={"wants_image": True, "wants_video": True},
    )
    image_attempt = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        status="completed",
    )
    ledger.record_artifact(
        request_id=request_id,
        attempt_id=image_attempt,
        kind="image",
        local_path="/tmp/source-image.jpg",
        content_hash="sha256:source-image",
        freshness_status="fresh",
    )
    ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine-video-1.5",
        status="failed",
        error_type="provider_timeout",
        error_message="timed out",
        parameters_requested={"kind": "video", "duration_seconds": 8},
    )

    report = build_visual_feedback_loop_report(tmp_path / "visual.sqlite3")

    assert report["success"] is True
    assert report["signals"]["provider"]["video_failure_count"] == 1
    assert "prefer_image_first_video" in _action_types(report)


def test_visual_feedback_loop_fails_closed_on_duplicate_delivery(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_feedback_loop_report import build_visual_feedback_loop_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_delivery"})
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/current.jpg",
        content_hash="sha256:duplicate",
        freshness_status="fresh",
    )
    for _ in range(2):
        ledger.record_delivery(
            request_id=request_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            platform="slack",
            destination_id="C123",
            thread_id="T123",
            delivery_status="sent",
        )

    report = build_visual_feedback_loop_report(tmp_path / "visual.sqlite3")

    assert report["success"] is False
    assert "duplicate_delivery" in report["failures"]
    assert report["signals"]["delivery"]["duplicate_delivery_count"] == 1
    assert "repair_delivery_dedup" in _action_types(report)


def test_visual_feedback_loop_tracks_successful_quality_repairs(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_feedback_loop_report import build_visual_feedback_loop_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_glamour"})
    blocked_attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        status="completed",
    )
    blocked_artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=blocked_attempt_id,
        kind="image",
        local_path="/tmp/blocked.jpg",
        content_hash="sha256:blocked",
        freshness_status="fresh",
    )
    repair_attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        status="completed",
        metadata={
            "quality_repair": {
                "reason": "active_learning_fail_closed",
                "quality_issues": ["subject_not_attractive"],
            },
            "retry_of": blocked_attempt_id,
        },
    )
    repair_artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=repair_attempt_id,
        kind="image",
        local_path="/tmp/repaired.jpg",
        content_hash="sha256:repaired",
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=blocked_attempt_id,
        artifact_id=blocked_artifact_id,
        judge_name="visual_quality_judge",
        score=0.35,
        verdict="fail",
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=repair_attempt_id,
        artifact_id=repair_artifact_id,
        judge_name="visual_quality_judge",
        score=0.86,
        verdict="pass",
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=repair_attempt_id,
        artifact_id=repair_artifact_id,
        platform="slack",
        destination_id="C123",
        delivery_status="sent",
    )

    report = build_visual_feedback_loop_report(tmp_path / "visual.sqlite3")
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["success"] is True
    assert report["signals"]["repair"]["quality_repair_attempt_count"] == 1
    assert report["signals"]["repair"]["quality_repair_success_count"] == 1
    assert report["signals"]["repair"]["quality_repair_delivery_success_count"] == 1
    assert report["signals"]["repair"]["quality_repair_success_rate"] == 1.0
    assert "prefer_quality_repair_retry" in _action_types(report)
    assert "/tmp/repaired.jpg" not in encoded


def test_visual_feedback_loop_flags_failed_quality_repairs(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_feedback_loop_report import build_visual_feedback_loop_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_glamour"})
    for index in range(3):
        repair_attempt_id = ledger.record_attempt(
            request_id=request_id,
            provider="xai",
            model="grok-imagine-image-quality",
            status="failed" if index == 0 else "completed",
            error_type="delivery_gate_blocked" if index == 0 else None,
            metadata={
                "quality_repair": {
                    "reason": "active_learning_fail_closed",
                    "quality_issues": ["composition_bad"],
                }
            },
        )
        if index > 0:
            artifact_id = ledger.record_artifact(
                request_id=request_id,
                attempt_id=repair_attempt_id,
                kind="image",
                local_path=f"/tmp/repair-{index}.jpg",
                content_hash=f"sha256:repair-{index}",
                freshness_status="fresh",
            )
            ledger.record_judgment(
                request_id=request_id,
                attempt_id=repair_attempt_id,
                artifact_id=artifact_id,
                judge_name="visual_quality_judge",
                score=0.38,
                verdict="fail",
            )

    report = build_visual_feedback_loop_report(tmp_path / "visual.sqlite3")

    assert report["success"] is True
    assert report["signals"]["repair"]["quality_repair_attempt_count"] == 3
    assert report["signals"]["repair"]["quality_repair_success_count"] == 0
    assert report["signals"]["repair"]["quality_repair_success_rate"] == 0.0
    assert "escalate_quality_repair_strategy" in _action_types(report)


def test_visual_e2e_automation_includes_feedback_loop_gate(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_feedback_loop_report",
        lambda _path: {"success": False, "failures": ["duplicate_delivery"]},
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is False
    assert "feedback_loop_failed" in report["failures"]
    assert report["feedback_loop"]["failures"] == ["duplicate_delivery"]


def _action_types(report: dict) -> set[str]:
    return {str(action.get("type")) for action in report["next_actions"]}
