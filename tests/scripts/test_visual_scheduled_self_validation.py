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
    assert report["summary"]["fixture_quality_suite_success"] is True
    assert report["summary"]["fixture_quality_suite_case_count"] == 3
    assert report["summary"]["scheduled_self_validation_video_repair_covered"] is True
    assert report["summary"]["fixture_quality_suite_negotiation_success_case_count"] == 0
    assert (tmp_path / "latest.json").exists()
    assert json.loads((tmp_path / "latest.json").read_text())["run_id"] == report["run_id"]
    assert (tmp_path / "runs" / f"{report['run_id']}.json").exists()


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
    assert report["summary"]["live_quality_suite_negotiation_success_case_count"] == 1
    assert report["summary"]["live_quality_suite_content_moderation_recovered_case_count"] == 1
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_live_run_at"] == "2026-06-22T08:00:00+00:00"


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
