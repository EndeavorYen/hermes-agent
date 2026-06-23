from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone


def _automation_report(*, include_live: bool, include_live_slack_upload: bool = False) -> dict:
    live_e2e = (
        {
            "success": True,
            "provider_mode": "live",
            "payload": {"success": True, "image_count": 1, "video_count": 1},
            "evidence": {
                "quality_gate": {"success": True, "min_score": 0.82, "low_quality_artifacts": []},
                "image_count": 1,
                "video_count": 1,
            },
            "failures": [],
        }
        if include_live
        else {"status": "not_requested"}
    )
    return {
        "success": True,
        "mode": "fixture+live" if include_live else "fixture",
        "failures": [],
        "live_e2e": live_e2e,
        "closed_loop_regression": {
            "success": True,
            "case_count": 3,
            "failure_count": 0,
            "failures": [],
        },
        "live_slack_delivery": (
            {
                "success": True,
                "mode": "live",
                "failures": [],
                "delivery": {
                    "deliverable_count": 2,
                    "sent_count": 2,
                    "duplicate_delivery_count": 0,
                    "unexpected_delivery_artifact_ids": [],
                    "uploaded_image_file_count": 1,
                    "uploaded_video_file_count": 1,
                    "uploaded_remote_video_url_count": 0,
                    "missing_uploaded_artifact_ids": [],
                    "unexpected_uploaded_artifact_ids": [],
                },
            }
            if include_live_slack_upload
            else {"status": "not_requested"}
        ),
        "slack_delivery": {
            "success": True,
            "delivery": {
                "deliverable_count": 2,
                "sent_count": 2,
                "duplicate_delivery_count": 0,
                "unexpected_delivery_artifact_ids": [],
            },
            "failures": [],
        },
        "slack_conversation": {
            "success": True,
            "self_review": {
                "success": True,
                "decision": "accept",
                "requires_human_feedback": False,
                "reduces_human_intervention": True,
                "auto_next_action_count": 0,
                "action_types": [],
                "quality_gate_success": True,
                "provider_failure_count": 0,
                "image_first_video_source_covered": True,
                "native_video_upload_covered": include_live_slack_upload,
                "blocking_reasons": [],
            },
            "next_actions": [],
        },
        "fixture_quality_suite": {
            "success": True,
            "case_count": 3,
            "failures": [],
            "recovery_summary": {
                "provider_failure_count": 0,
                "retry_attempt_count": 0,
                "negotiation_attempted_case_count": 0,
                "negotiation_success_case_count": 0,
                "content_moderation_recovered_case_count": 0,
            },
            "quality_repair_summary": {
                "attempt_count": 1,
                "success_count": 1,
                "selected_repair_count": 1,
                "by_modality": {
                    "video": {
                        "attempt_count": 1,
                        "success_count": 1,
                        "selected_repair_count": 1,
                    }
                },
            },
            "cases": [
                {"case_id": "product_photo_video", "success": True, "failures": []},
                {"case_id": "fashion_portrait_video", "success": True, "failures": []},
                {"case_id": "video_quality_repair", "success": True, "failures": []},
            ],
        },
        "live_quality_suite": (
            {
                "success": True,
                "case_count": 2,
                "failures": [],
                "recovery_summary": {
                    "provider_failure_count": 2,
                    "retry_attempt_count": 2,
                    "negotiation_attempted_case_count": 1,
                    "negotiation_success_case_count": 1,
                    "content_moderation_recovered_case_count": 1,
                },
                "cases": [
                    {"case_id": "product_photo_video", "success": True, "failures": []},
                    {"case_id": "fashion_portrait_video", "success": True, "failures": []},
                ],
            }
            if include_live
            else {"status": "not_requested"}
        ),
        "live_quality_burn": (
            {
                "success": True,
                "summary": {
                    "case_count": 2,
                    "min_quality_score": 0.74,
                    "failed_case_count": 0,
                    "core_quality_contract_case_count": 1,
                    "core_quality_coverage_ready": True,
                    "core_quality_dimensions": [
                        "subject_beauty",
                        "face_naturalness",
                        "glamour_impact",
                        "fashion_material_quality",
                        "pose_composition",
                    ],
                    "core_quality_dimensions_missing": [],
                    "quality_focus_outcome_count": 6,
                    "quality_focus_success_count": 5,
                    "quality_focus_failure_count": 1,
                    "quality_focus_successes": [
                        "adult_fashion_portrait",
                        "natural_face",
                        "long_leg_composition",
                        "tasteful_glamour",
                        "image_first_video",
                    ],
                    "quality_focus_failures": ["legwear_material"],
                    "quality_focus_failed_case_ids": ["fashion_portrait_video"],
                    "image_first_video_source_case_count": 2,
                    "image_first_video_source_covered_count": 2,
                    "image_first_video_source_failure_count": 0,
                    "image_first_video_source_failure_case_ids": [],
                    "image_first_video_source_not_single_count": 0,
                    "image_first_video_source_not_single_case_ids": [],
                    "preference_dimension_failure_count": 2,
                    "preference_dimension_failures": [
                        {"dimension": "face_naturalness", "issue": "face_unnatural", "score": 0.28},
                        {
                            "dimension": "fashion_material_quality",
                            "issue": "stockings_bad",
                            "score": 0.31,
                        },
                    ],
                },
                "next_actions": [
                    {
                        "type": "increase_candidate_budget",
                        "requires_human_feedback": False,
                        "source": "live_quality_burn",
                    },
                    {
                        "type": "repair_low_preference_dimension",
                        "requires_human_feedback": False,
                        "source": "live_quality_burn",
                        "dimension": "face_naturalness",
                    },
                    {
                        "type": "apply_quality_focus_operator",
                        "requires_human_feedback": False,
                        "source": "live_quality_burn",
                        "focus": "legwear_material",
                        "dimension": "fashion_material_quality",
                        "strategy_operator": "refine_legwear_material",
                    },
                    {
                        "type": "safe_reframe_provider_retry",
                        "requires_human_feedback": False,
                        "source": "live_quality_burn",
                        "provider_failure_classes": {"content_moderation": 2},
                        "provider_error_codes": {"api_error": 2},
                    }
                ],
            }
            if include_live
            else {"status": "not_requested"}
        ),
        "feedback_loop": {
            "success": True,
            "next_actions": [
                {"type": "increase_candidate_budget", "requires_human_feedback": False},
                {"type": "rerank_before_slack", "requires_human_feedback": False},
            ],
        },
        "self_improvement": {
            "next_actions": [
                {
                    "type": "prefer_quality_repair_retry",
                    "requires_human_feedback": False,
                    "source": "fixture_quality_suite",
                }
            ],
            "reduces_human_intervention": True,
        },
        "health": {
            "success": True,
            "self_review": {"reduces_human_intervention": True, "privacy_safe": True},
        },
    }


def test_scheduled_self_validation_defaults_to_fixture_and_writes_reports(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    calls = []

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        calls.append(
            {
                "work_dir": work_dir,
                "include_live": include_live,
                "include_live_slack_upload": include_live_slack_upload,
            }
        )
        return _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        now=datetime(2026, 6, 22, 4, 0, tzinfo=timezone.utc),
    )

    assert report["success"] is True
    assert report["live_policy"]["decision"] == "not_requested"
    assert calls == [{"work_dir": tmp_path / "work", "include_live": False, "include_live_slack_upload": False}]
    assert report["summary"]["feedback_action_types"] == [
        "increase_candidate_budget",
        "rerank_before_slack",
        "prefer_quality_repair_retry",
    ]
    assert report["summary"]["scheduled_self_validation_reduces_human_intervention"] is True
    assert report["summary"]["autonomous_rollout_reduces_human_intervention"] is True
    assert report["summary"]["slack_conversation_self_review_decision"] == "accept"
    assert report["summary"]["slack_conversation_self_review_success"] is True
    assert report["summary"]["slack_conversation_requires_human_feedback"] is False
    assert report["summary"]["slack_conversation_reduces_human_intervention"] is True
    assert report["summary"]["slack_conversation_image_first_video_source_covered"] is True
    assert report["summary"]["fixture_quality_suite_success"] is True
    assert report["summary"]["fixture_quality_suite_case_count"] == 3
    assert report["summary"]["closed_loop_regression_success"] is True
    assert report["summary"]["closed_loop_regression_case_count"] == 3
    assert report["summary"]["closed_loop_regression_failure_count"] == 0
    assert report["summary"]["scheduled_self_validation_video_repair_covered"] is True
    assert report["summary"]["fixture_quality_suite_negotiation_success_case_count"] == 0
    assert (tmp_path / "latest.json").exists()
    assert json.loads((tmp_path / "latest.json").read_text())["run_id"] == report["run_id"]
    assert (tmp_path / "runs" / f"{report['run_id']}.json").exists()


def test_scheduled_self_validation_tracks_internal_source_image_delivery(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        report = _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )
        report["slack_delivery"]["success"] = False
        report["slack_delivery"]["failures"] = ["internal_source_image_delivered"]
        report["slack_delivery"]["delivery"]["internal_source_image_delivered"] = True
        report["slack_delivery"]["delivery"]["internal_source_image_artifact_ids"] = ["var_source"]
        return report

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        now=datetime(2026, 6, 22, 4, 0, tzinfo=timezone.utc),
    )

    assert report["summary"]["slack_internal_source_image_delivery_count"] == 1
    assert report["summary"]["slack_internal_source_image_artifact_ids"] == ["var_source"]
    assert report["summary"]["scheduled_self_validation_reduces_human_intervention"] is False


def test_scheduled_self_validation_tracks_slack_conversation_self_review_actions(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        report = _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )
        report["slack_conversation"]["success"] = True
        report["slack_conversation"]["self_review"] = {
            "success": False,
            "decision": "needs_repair",
            "requires_human_feedback": False,
            "reduces_human_intervention": True,
            "auto_next_action_count": 2,
            "action_types": ["increase_candidate_budget", "rerank_before_slack"],
            "quality_gate_success": False,
            "provider_failure_count": 0,
            "image_first_video_source_covered": True,
            "native_video_upload_covered": False,
            "blocking_reasons": ["video_metadata_missing"],
        }
        report["slack_conversation"]["next_actions"] = [
            {
                "type": "increase_candidate_budget",
                "requires_human_feedback": False,
                "source": "slack_conversation_e2e",
            },
            {
                "type": "rerank_before_slack",
                "requires_human_feedback": False,
                "source": "slack_conversation_e2e",
            },
        ]
        report["self_improvement"] = {
            "next_actions": report["slack_conversation"]["next_actions"],
            "reduces_human_intervention": True,
        }
        return report

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        now=datetime(2026, 6, 22, 4, 0, tzinfo=timezone.utc),
    )

    assert report["summary"]["slack_conversation_self_review_decision"] == "needs_repair"
    assert report["summary"]["slack_conversation_self_review_success"] is False
    assert report["summary"]["slack_conversation_requires_human_feedback"] is False
    assert report["summary"]["slack_conversation_auto_next_action_count"] == 2
    assert report["summary"]["slack_conversation_blocking_reasons"] == ["video_metadata_missing"]
    assert "increase_candidate_budget" in report["summary"]["feedback_action_types"]
    assert "rerank_before_slack" in report["summary"]["feedback_action_types"]


def test_scheduled_self_validation_tracks_slack_conversation_operator_setup(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    operator_setup_actions = [
        {
            "provider": "fal",
            "missing_env_vars": ["FAL_KEY"],
            "post_setup": "",
        }
    ]

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        report = _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )
        report["slack_conversation"]["self_review"] = {
            "success": False,
            "decision": "needs_setup",
            "requires_human_feedback": False,
            "requires_operator_setup": True,
            "operator_setup_actions": operator_setup_actions,
            "operator_setup_action_count": 1,
            "reduces_human_intervention": False,
            "auto_next_action_count": 0,
            "action_types": [],
            "blocking_reasons": ["operator_setup_required"],
        }
        return report

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        now=datetime(2026, 6, 22, 4, 0, tzinfo=timezone.utc),
    )

    assert report["summary"]["slack_conversation_self_review_decision"] == "needs_setup"
    assert report["summary"]["slack_conversation_requires_human_feedback"] is False
    assert report["summary"]["slack_conversation_requires_operator_setup"] is True
    assert report["summary"]["slack_conversation_operator_setup_actions"] == operator_setup_actions
    assert report["summary"]["slack_conversation_operator_setup_action_count"] == 1
    assert report["summary"]["slack_conversation_reduces_human_intervention"] is False


def test_scheduled_self_validation_runs_live_when_due(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    calls = []

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        calls.append(
            {
                "work_dir": work_dir,
                "include_live": include_live,
                "include_live_slack_upload": include_live_slack_upload,
            }
        )
        return _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        live_mode="auto",
        live_enabled=True,
        min_live_interval_hours=6,
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["success"] is True
    assert report["live_policy"]["decision"] == "run"
    assert calls[0]["include_live"] is True
    assert report["summary"]["live_quality_gate_min_score"] == 0.82
    assert report["summary"]["live_quality_suite_success"] is True
    assert report["summary"]["live_quality_suite_case_count"] == 2
    assert report["summary"]["live_quality_burn_success"] is True
    assert report["summary"]["live_quality_burn_case_count"] == 2
    assert report["summary"]["live_quality_burn_min_score"] == 0.74
    assert "increase_candidate_budget" in report["summary"]["live_quality_burn_action_types"]
    assert "repair_low_preference_dimension" in report["summary"]["live_quality_burn_action_types"]
    assert "apply_quality_focus_operator" in report["summary"]["live_quality_burn_action_types"]
    assert report["summary"]["live_quality_burn_preference_dimension_failure_count"] == 2
    assert report["summary"]["live_quality_burn_preference_dimensions"] == [
        "face_naturalness",
        "fashion_material_quality",
    ]
    assert report["summary"]["live_quality_burn_core_quality_coverage_ready"] is True
    assert report["summary"]["live_quality_burn_core_quality_dimensions"] == [
        "subject_beauty",
        "face_naturalness",
        "glamour_impact",
        "fashion_material_quality",
        "pose_composition",
    ]
    assert report["summary"]["live_quality_burn_core_quality_dimensions_missing"] == []
    assert report["summary"]["live_quality_burn_quality_focus_failure_count"] == 1
    assert report["summary"]["live_quality_burn_quality_focus_failures"] == ["legwear_material"]
    assert report["summary"]["live_quality_burn_quality_focus_failed_case_ids"] == [
        "fashion_portrait_video"
    ]
    assert report["summary"]["live_quality_burn_image_first_video_source_covered"] is True
    assert report["summary"]["live_quality_burn_image_first_video_source_failure_count"] == 0
    assert report["summary"]["live_quality_burn_image_first_video_source_not_single_count"] == 0
    assert report["summary"]["live_quality_burn_image_first_video_source_not_single_case_ids"] == []
    assert report["summary"]["live_quality_suite_negotiation_success_case_count"] == 1
    assert report["summary"]["live_quality_suite_content_moderation_recovered_case_count"] == 1
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_live_run_at"] == "2026-06-22T08:00:00+00:00"


def test_scheduled_self_validation_includes_live_quality_trends(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        return _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    output_dir = tmp_path / "self_validation"
    runs_dir = tmp_path / "live_quality_burn" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "run01.json").write_text(
        json.dumps(
            {
                "success": True,
                "run_id": "run01",
                "generated_at": "2026-06-22T01:00:00+00:00",
                "summary": {
                    "case_count": 2,
                    "min_quality_score": 0.86,
                    "provider_failure_count": 0,
                    "video_missing_after_image_count": 0,
                    "image_first_video_source_failure_count": 0,
                    "preference_dimension_failure_count": 0,
                    "preference_dimension_failures": [],
                },
            }
        ),
        encoding="utf-8",
    )
    (runs_dir / "run02.json").write_text(
        json.dumps(
            {
                "success": False,
                "run_id": "run02",
                "generated_at": "2026-06-22T02:00:00+00:00",
                "summary": {
                    "case_count": 2,
                    "min_quality_score": 0.52,
                    "provider_failure_count": 1,
                    "video_missing_after_image_count": 1,
                    "image_first_video_source_failure_count": 0,
                    "preference_dimension_failure_count": 1,
                    "preference_dimension_failures": [
                        {"dimension": "subject_beauty", "issue": "subject_not_attractive", "score": 0.3}
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (runs_dir / "run03.json").write_text(
        json.dumps(
            {
                "success": True,
                "run_id": "run03",
                "generated_at": "2026-06-22T03:00:00+00:00",
                "source": "slack_conversation_e2e",
                "summary": {
                    "case_count": 1,
                    "min_quality_score": 0.82,
                    "provider_failure_count": 0,
                    "video_missing_after_image_count": 0,
                    "image_first_video_source_failure_count": 0,
                    "preference_dimension_failure_count": 0,
                    "preference_dimension_failures": [],
                },
                "self_review": {
                    "native_video_upload_covered": True,
                    "image_first_video_source_covered": True,
                },
            }
        ),
        encoding="utf-8",
    )
    (runs_dir / "run04.json").write_text(
        json.dumps(
            {
                "success": True,
                "run_id": "run04",
                "generated_at": "2026-06-22T04:00:00+00:00",
                "source": "slack_conversation_e2e",
                "summary": {
                    "case_count": 1,
                    "min_quality_score": 0.84,
                    "provider_failure_count": 0,
                    "video_missing_after_image_count": 0,
                    "image_first_video_source_failure_count": 0,
                    "preference_dimension_failure_count": 0,
                    "preference_dimension_failures": [],
                },
                "self_review": {
                    "native_video_upload_covered": True,
                    "image_first_video_source_covered": True,
                },
            }
        ),
        encoding="utf-8",
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=output_dir,
        live_mode="off",
        now=datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc),
    )

    assert report["live_quality_trends"]["run_count"] == 4
    assert report["summary"]["live_quality_trend_run_count"] == 4
    assert report["summary"]["live_quality_trend_recent_run_ids"] == ["run03", "run04"]
    assert report["summary"]["live_quality_trend_recent_avg_min_quality_score"] == 0.83
    assert report["summary"]["live_quality_trend_recent_provider_failure_count"] == 0
    assert report["summary"]["live_quality_trend_recent_video_generation_failure_count"] == 0
    assert report["summary"]["live_quality_trend_recent_preference_dimension_failure_count"] == 0
    assert report["summary"]["live_conversation_quality_run_count"] == 2
    assert report["summary"]["live_conversation_quality_recent_run_ids"] == ["run03", "run04"]
    assert report["summary"]["live_conversation_quality_recent_avg_min_quality_score"] == 0.83
    assert report["summary"]["live_conversation_quality_native_video_upload_covered_count"] == 2
    assert report["summary"]["live_conversation_quality_image_first_video_source_failure_count"] == 0
    assert report["summary"]["live_conversation_quality_provider_failure_count"] == 0
    assert report["summary"]["live_conversation_quality_latest_generated_at"] == "2026-06-22T04:00:00+00:00"
    assert report["summary"]["live_quality_trend_degradations"] == []
    assert report["summary"]["live_quality_trend_action_types"] == []


def test_scheduled_self_validation_refreshes_live_quality_trends_after_live_run(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_scheduled_self_validation

    output_dir = tmp_path / "self_validation"
    live_runs_dir = tmp_path / "live_quality_burn" / "runs"

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        assert include_live is True
        live_runs_dir.mkdir(parents=True)
        (live_runs_dir / "current.json").write_text(
            json.dumps(
                {
                    "success": True,
                    "run_id": "current",
                    "generated_at": "2026-06-22T08:00:00+00:00",
                    "summary": {
                        "case_count": 2,
                        "min_quality_score": 0.86,
                        "quality_issue_count": 0,
                        "provider_failure_count": 0,
                        "video_missing_after_image_count": 0,
                        "image_first_video_source_failure_count": 0,
                        "preference_dimension_failure_count": 0,
                        "preference_dimension_failures": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        return _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=output_dir,
        live_mode="on",
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["live_quality_trends"]["run_count"] == 1
    assert report["summary"]["live_quality_trend_recent_run_ids"] == ["current"]


def test_scheduled_self_validation_live_mode_on_forces_live_without_env_gate(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    calls = []

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        calls.append(
            {
                "work_dir": work_dir,
                "include_live": include_live,
                "include_live_slack_upload": include_live_slack_upload,
            }
        )
        return _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        live_mode="on",
        live_enabled=False,
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["live_policy"] == {"mode": "on", "decision": "run", "live_enabled": True}
    assert calls == [{"work_dir": tmp_path / "work", "include_live": True, "include_live_slack_upload": False}]
    assert report["mode"] == "fixture+live"
    assert report["self_review"]["live_e2e_requires_opt_in"] is False


def test_scheduled_self_validation_auto_still_requires_live_env_gate(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    calls = []
    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        lambda *, work_dir, include_live, include_live_slack_upload=False: (
            calls.append({"include_live": include_live, "include_live_slack_upload": include_live_slack_upload})
            or _automation_report(
                include_live=include_live,
                include_live_slack_upload=include_live_slack_upload,
            )
        ),
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        live_mode="auto",
        live_enabled=False,
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["live_policy"] == {"mode": "auto", "decision": "skip_not_enabled", "live_enabled": False}
    assert calls == [{"include_live": False, "include_live_slack_upload": False}]


def test_scheduled_self_validation_summarizes_quality_repair_coverage(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        payload = _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )
        payload["fixture_quality_suite"]["quality_repair_summary"] = {
            "attempt_count": 1,
            "success_count": 1,
            "selected_repair_count": 1,
            "by_modality": {
                "video": {
                    "attempt_count": 1,
                    "success_count": 1,
                    "selected_repair_count": 1,
                }
            },
        }
        return payload

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        now=datetime(2026, 6, 22, 4, 0, tzinfo=timezone.utc),
    )

    assert report["summary"]["fixture_quality_repair_attempt_count"] == 1
    assert report["summary"]["fixture_quality_repair_success_count"] == 1
    assert report["summary"]["fixture_quality_repair_selected_count"] == 1
    assert report["summary"]["fixture_video_quality_repair_success_count"] == 1
    assert report["summary"]["scheduled_self_validation_video_repair_covered"] is True


def test_scheduled_self_validation_passes_case_timeout_to_automation(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    calls = []

    def fake_automation(
        *,
        work_dir,
        include_live,
        include_live_slack_upload=False,
        case_timeout_seconds=None,
    ):
        calls.append(
            {
                "work_dir": work_dir,
                "include_live": include_live,
                "include_live_slack_upload": include_live_slack_upload,
                "case_timeout_seconds": case_timeout_seconds,
            }
        )
        return _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        live_mode="auto",
        live_enabled=True,
        case_timeout_seconds=321,
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["success"] is True
    assert calls == [
        {
            "work_dir": tmp_path / "work",
            "include_live": True,
            "include_live_slack_upload": False,
            "case_timeout_seconds": 321,
        }
    ]


def test_scheduled_self_validation_skips_live_until_interval_elapsed(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    (tmp_path / "state.json").write_text(
        json.dumps({"last_live_run_at": "2026-06-22T06:30:00+00:00"}),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        lambda *, work_dir, include_live, include_live_slack_upload=False: (
            calls.append({"include_live": include_live, "include_live_slack_upload": include_live_slack_upload})
            or _automation_report(
                include_live=include_live,
                include_live_slack_upload=include_live_slack_upload,
            )
        ),
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        live_mode="auto",
        live_enabled=True,
        min_live_interval_hours=6,
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["live_policy"]["decision"] == "skip_interval"
    assert calls == [{"include_live": False, "include_live_slack_upload": False}]


def test_scheduled_self_validation_auto_runs_live_when_quality_trend_degrades(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    output_dir = tmp_path / "self_validation"
    output_dir.mkdir(parents=True)
    (output_dir / "state.json").write_text(
        json.dumps({"last_live_run_at": "2026-06-22T06:30:00+00:00"}),
        encoding="utf-8",
    )
    runs_dir = tmp_path / "live_quality_burn" / "runs"
    runs_dir.mkdir(parents=True)
    for run_id, hour, score in (
        ("run01", 1, 0.86),
        ("run02", 2, 0.84),
        ("run03", 3, 0.48),
        ("run04", 4, 0.49),
    ):
        (runs_dir / f"{run_id}.json").write_text(
            json.dumps(
                {
                    "success": score >= 0.8,
                    "run_id": run_id,
                    "generated_at": f"2026-06-22T0{hour}:00:00+00:00",
                    "summary": {
                        "case_count": 2,
                        "min_quality_score": score,
                        "quality_issue_count": 1 if score < 0.8 else 0,
                        "provider_failure_count": 0,
                        "video_missing_after_image_count": 0,
                        "image_first_video_source_failure_count": 0,
                        "preference_dimension_failure_count": 0,
                        "preference_dimension_failures": [],
                    },
                }
            ),
            encoding="utf-8",
        )
    calls = []

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        calls.append({"include_live": include_live, "include_live_slack_upload": include_live_slack_upload})
        return _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=output_dir,
        live_mode="auto",
        live_enabled=True,
        min_live_interval_hours=6,
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["live_policy"]["decision"] == "run"
    assert report["live_policy"]["reason"] == "live_quality_trend_degraded"
    assert report["live_policy"]["degradations"] == ["quality_score_degraded"]
    assert calls == [{"include_live": True, "include_live_slack_upload": False}]
    assert "increase_candidate_budget" in report["summary"]["live_quality_trend_action_types"]


def test_scheduled_self_validation_exports_safe_runtime_policy_even_when_report_fails(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_scheduled_self_validation

    output_dir = tmp_path / "self_validation"

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        assert include_live is True
        return {
            **_automation_report(
                include_live=include_live,
                include_live_slack_upload=include_live_slack_upload,
            ),
            "success": False,
            "failures": ["live_quality_suite_failed"],
            "self_improvement": {
                "next_actions": [
                    {
                        "type": "prefer_image_first_video",
                        "requires_human_feedback": False,
                        "activation_status": "next_run",
                        "source": "live_quality_burn",
                        "private_prompt": "do not leak this prompt",
                    },
                    {
                        "type": "prefer_quality_repair_retry",
                        "requires_human_feedback": True,
                        "activation_status": "next_run",
                        "source": "human_review",
                    },
                    {
                        "type": "unknown_prompt_mutation",
                        "requires_human_feedback": False,
                        "activation_status": "next_run",
                        "source": "unsafe",
                    },
                ]
            },
        }

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=output_dir,
        live_mode="on",
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["success"] is False
    assert report["runtime_policy"]["success"] is True
    assert report["runtime_policy"]["decision"] == "apply_next_run"
    assert report["runtime_policy"]["generated_at"] == "2026-06-22T08:00:00+00:00"
    assert report["runtime_policy"]["expires_at"] == "2026-06-23T08:00:00+00:00"
    assert report["runtime_policy"]["next_actions"] == [
        {
            "type": "prefer_image_first_video",
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "source": "live_quality_burn",
        }
    ]
    encoded = json.dumps(report["runtime_policy"], ensure_ascii=False)
    assert "do not leak" not in encoded
    assert "unknown_prompt_mutation" not in encoded


def test_scheduled_self_validation_summarizes_runtime_policy_effect(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    def fake_trends(_output_dir):
        return {
            "run_count": 4,
            "summary": {
                "recent_run_ids": ["baseline"],
                "recent_avg_min_quality_score": 0.82,
            },
            "degradations": [],
            "next_actions": [],
        }

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        report = _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )
        report["fixture_e2e"] = {
            "success": False,
            "evidence": {
                "runtime_policy_effect": {
                    "policy_active": True,
                    "applied": False,
                    "expected_action_types": ["increase_candidate_budget"],
                    "applied_action_types": [],
                    "missing_action_types": ["increase_candidate_budget"],
                }
            },
        }
        report["live_e2e"] = {
            "success": True,
            "evidence": {
                "runtime_policy_effect": {
                    "policy_active": True,
                    "applied": True,
                    "expected_action_types": ["increase_candidate_budget"],
                    "applied_action_types": ["increase_candidate_budget"],
                    "missing_action_types": [],
                    "quality_gate_success": True,
                    "quality_gate_min_score": 0.72,
                },
                "quality_gate": {"success": True, "min_score": 0.72},
            },
        }
        return report

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )
    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_live_quality_trend_report_from_dir",
        fake_trends,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path / "self_validation",
        live_mode="off",
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["summary"]["fixture_runtime_policy_active"] is True
    assert report["summary"]["fixture_runtime_policy_applied"] is False
    assert report["summary"]["fixture_runtime_policy_expected_action_types"] == [
        "increase_candidate_budget"
    ]
    assert report["summary"]["fixture_runtime_policy_missing_action_types"] == [
        "increase_candidate_budget"
    ]
    assert report["summary"]["live_runtime_policy_quality_gate_min_score"] == 0.72
    assert report["summary"]["live_runtime_policy_quality_delta_vs_recent_trend"] == -0.1
    assert report["summary"]["live_runtime_policy_quality_regressed"] is True


def test_scheduled_self_validation_suspends_runtime_policy_after_quality_regression(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_scheduled_self_validation

    def fake_trends(_output_dir):
        return {
            "run_count": 4,
            "summary": {
                "recent_run_ids": ["baseline"],
                "recent_avg_min_quality_score": 0.82,
            },
            "degradations": [],
            "next_actions": [],
        }

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        report = _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )
        report["self_improvement"] = {
            "next_actions": [
                {
                    "type": "increase_candidate_budget",
                    "requires_human_feedback": False,
                    "activation_status": "next_run",
                    "source": "live_quality_trends",
                    "max_candidate_budget": 4,
                },
                {
                    "type": "prefer_image_first_video",
                    "requires_human_feedback": False,
                    "activation_status": "next_run",
                    "source": "live_quality_trends",
                },
            ]
        }
        report["live_e2e"] = {
            "success": True,
            "evidence": {
                "runtime_policy_effect": {
                    "policy_active": True,
                    "applied": True,
                    "expected_action_types": [
                        "increase_candidate_budget",
                        "prefer_image_first_video",
                    ],
                    "applied_action_types": [
                        "increase_candidate_budget",
                        "prefer_image_first_video",
                    ],
                    "missing_action_types": [],
                    "quality_gate_success": True,
                    "quality_gate_min_score": 0.72,
                },
                "quality_gate": {"success": True, "min_score": 0.72},
            },
        }
        return report

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )
    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_live_quality_trend_report_from_dir",
        fake_trends,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path / "self_validation",
        live_mode="off",
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["summary"]["live_runtime_policy_quality_regressed"] is True
    assert report["runtime_policy"] == {
        "success": False,
        "decision": "suspend_quality_regressed",
        "reason": "runtime_policy_quality_regressed",
        "generated_at": "2026-06-22T08:00:00+00:00",
        "expires_at": "2026-06-23T08:00:00+00:00",
        "next_actions": [],
        "suspended_action_types": [
            "increase_candidate_budget",
            "prefer_image_first_video",
        ],
        "privacy_safe": True,
        "source": "scheduled_self_validation",
    }


def test_scheduled_self_validation_carries_forward_recent_live_burn_actions(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    calls = []

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        calls.append({"include_live": include_live, "include_live_slack_upload": include_live_slack_upload})
        return _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        live_mode="auto",
        live_enabled=True,
        min_live_interval_hours=6,
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        live_mode="auto",
        live_enabled=True,
        min_live_interval_hours=6,
        now=datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc),
    )

    assert calls == [
        {"include_live": True, "include_live_slack_upload": False},
        {"include_live": False, "include_live_slack_upload": False},
    ]
    assert report["live_policy"]["decision"] == "skip_interval"
    assert report["automation"]["live_quality_burn"]["status"] == "carried_forward"
    assert "increase_candidate_budget" in report["summary"]["live_quality_burn_action_types"]
    assert "repair_low_preference_dimension" in report["summary"]["live_quality_burn_action_types"]
    assert "safe_reframe_provider_retry" in report["summary"]["live_quality_burn_action_types"]
    assert {
        "type": "increase_candidate_budget",
        "requires_human_feedback": False,
        "source": "live_quality_burn",
    } in report["automation"]["self_improvement"]["next_actions"]
    assert {
        "type": "safe_reframe_provider_retry",
        "requires_human_feedback": False,
        "source": "live_quality_burn",
        "provider_failure_classes": {"content_moderation": 2},
        "provider_error_codes": {"api_error": 2},
    } in report["automation"]["self_improvement"]["next_actions"]


def test_scheduled_self_validation_dedupe_preserves_distinct_quality_actions():
    from scripts.visual_scheduled_self_validation import _dedupe_actions

    face_repair = {
        "type": "repair_low_preference_dimension",
        "source": "live_quality_burn",
        "dimension": "face_naturalness",
    }
    material_repair = {
        "type": "repair_low_preference_dimension",
        "source": "live_quality_burn",
        "dimension": "fashion_material_quality",
    }
    legwear_focus = {
        "type": "apply_quality_focus_operator",
        "source": "live_quality_trends",
        "dimension": "fashion_material_quality",
        "focus": "legwear_material",
        "strategy_operator": "refine_legwear_material",
    }
    composition_focus = {
        "type": "apply_quality_focus_operator",
        "source": "live_quality_trends",
        "dimension": "pose_composition",
        "focus": "long_leg_composition",
        "strategy_operator": "refine_long_leg_composition",
    }

    assert _dedupe_actions(
        [
            face_repair,
            material_repair,
            legwear_focus,
            composition_focus,
            dict(legwear_focus),
        ]
    ) == [
        face_repair,
        material_repair,
        legwear_focus,
        composition_focus,
    ]


def test_scheduled_self_validation_separates_rollout_autonomy_from_validation(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        payload = _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )
        payload["health"]["self_review"]["reduces_human_intervention"] = False
        return payload

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        now=datetime(2026, 6, 22, 4, 0, tzinfo=timezone.utc),
    )

    assert report["summary"]["scheduled_self_validation_reduces_human_intervention"] is True
    assert report["summary"]["autonomous_rollout_reduces_human_intervention"] is False


def test_scheduled_self_validation_skips_live_slack_upload_without_target(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    calls = []

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        calls.append({"include_live": include_live, "include_live_slack_upload": include_live_slack_upload})
        return _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )
    monkeypatch.setattr(visual_scheduled_self_validation, "_live_slack_upload_enabled", lambda: True)
    monkeypatch.setattr(visual_scheduled_self_validation, "_resolve_live_slack_target", lambda: None)

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        live_mode="on",
        live_enabled=True,
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["live_policy"]["decision"] == "run"
    assert report["slack_live_upload_policy"]["decision"] == "skip_missing_target"
    assert calls == [{"include_live": True, "include_live_slack_upload": False}]
    assert report["summary"]["live_slack_upload_success"] is None


def test_scheduled_self_validation_runs_live_slack_upload_when_target_is_ready(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    calls = []

    def fake_automation(*, work_dir, include_live, include_live_slack_upload=False):
        calls.append({"include_live": include_live, "include_live_slack_upload": include_live_slack_upload})
        return _automation_report(
            include_live=include_live,
            include_live_slack_upload=include_live_slack_upload,
        )

    monkeypatch.setattr(
        visual_scheduled_self_validation,
        "build_visual_e2e_automation_report",
        fake_automation,
    )
    monkeypatch.setattr(visual_scheduled_self_validation, "_live_slack_upload_enabled", lambda: True)
    monkeypatch.setattr(visual_scheduled_self_validation, "_resolve_live_slack_target", lambda: "D_TEST")

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        live_mode="on",
        live_enabled=True,
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["slack_live_upload_policy"] == {
        "decision": "run",
        "enabled": True,
        "target": "D_TEST",
    }
    assert calls == [{"include_live": True, "include_live_slack_upload": True}]
    assert report["summary"]["live_slack_upload_success"] is True
    assert report["summary"]["live_slack_upload_sent_count"] == 2
    assert report["summary"]["live_slack_upload_uploaded_image_file_count"] == 1
    assert report["summary"]["live_slack_upload_uploaded_video_file_count"] == 1
    assert report["summary"]["live_slack_upload_uploaded_remote_video_url_count"] == 0
    assert report["summary"]["live_slack_upload_missing_native_upload_count"] == 0
    assert report["summary"]["live_slack_upload_unexpected_native_upload_count"] == 0
    assert report["summary"]["live_slack_upload_native_delivery_covered"] is True
