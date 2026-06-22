from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone


def _write_latest(tmp_path, payload):
    report_dir = tmp_path / "visual" / "self_validation"
    report_dir.mkdir(parents=True)
    path = report_dir / "latest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _scheduled_report(*, success=True, live_decision="run"):
    return {
        "success": success,
        "run_id": "20260622T101900Z",
        "generated_at": "2026-06-22T10:19:00+00:00",
        "mode": "fixture+live" if live_decision == "run" else "fixture",
        "failures": [] if success else ["live_quality_suite_failed"],
        "live_policy": {
            "mode": "on",
            "decision": live_decision,
            "live_enabled": live_decision == "run",
        },
        "slack_live_upload_policy": {
            "decision": "run" if live_decision == "run" else "not_requested",
            "enabled": live_decision == "run",
            "target": "D_SECRET",
        },
        "summary": {
            "live_quality_gate_success": True,
            "live_quality_gate_min_score": 0.8206,
            "live_quality_suite_success": True,
            "live_quality_suite_case_count": 2,
            "live_quality_suite_failure_count": 0,
            "live_quality_suite_content_moderation_recovered_case_count": 1,
            "live_quality_burn_success": True,
            "live_quality_burn_case_count": 2,
            "live_quality_burn_min_score": 0.74,
            "live_quality_burn_action_types": [
                "repair_low_preference_dimension",
                "safe_reframe_provider_retry",
                "prefer_image_first_video",
            ],
            "live_quality_burn_preference_dimensions": [
                "face_naturalness",
                "fashion_material_quality",
            ],
            "live_video_quality_repair_success_count": 1,
            "live_slack_upload_native_delivery_covered": True,
            "live_slack_upload_uploaded_video_file_count": 1,
            "slack_duplicate_delivery_count": 0,
        },
        "automation": {
            "self_improvement": {
                "next_actions": [
                    {
                        "type": "safe_reframe_provider_retry",
                        "requires_human_feedback": False,
                        "source": "live_quality_burn",
                        "provider_failure_classes": {"content_moderation": 1},
                        "provider_error_codes": {"api_error": 1},
                        "private_prompt": "do not leak this prompt",
                    },
                    {
                        "type": "prefer_image_first_video",
                        "requires_human_feedback": False,
                        "source": "live_quality_burn",
                    },
                ],
            },
            "artifact_path": "/Users/simon/.hermes/cache/images/private.jpg",
        },
        "self_review": {
            "privacy_safe": True,
            "reduces_human_intervention": True,
        },
    }


def test_visual_self_validation_status_summarizes_latest_live_report(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    latest_path = _write_latest(tmp_path, _scheduled_report())

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["success"] is True
    assert status["health_status"] == "pass"
    assert status["run_id"] == "20260622T101900Z"
    assert status["live_e2e_ran"] is True
    assert status["live_policy"]["decision"] == "run"
    assert status["live"]["quality_gate_min_score"] == 0.8206
    assert status["live"]["suite_success"] is True
    assert status["live"]["burn_success"] is True
    assert status["live"]["content_moderation_recovered_count"] == 1
    assert status["live"]["provider_failure_classes"] == {"content_moderation": 1}
    assert status["live"]["provider_error_codes"] == {"api_error": 1}
    assert status["live"]["preference_dimensions"] == [
        "face_naturalness",
        "fashion_material_quality",
    ]
    assert status["delivery"]["native_video_upload_covered"] is True
    assert status["self_improvement"]["action_types"] == [
        "repair_low_preference_dimension",
        "safe_reframe_provider_retry",
        "prefer_image_first_video",
    ]
    encoded = json.dumps(status, ensure_ascii=False)
    assert "do not leak" not in encoded
    assert "/Users/simon" not in encoded
    assert "D_SECRET" not in encoded
    assert "artifact_path" not in encoded


def test_visual_self_validation_status_marks_missing_report(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    status = build_visual_self_validation_status(latest_path=tmp_path / "missing.json")

    assert status["success"] is False
    assert status["health_status"] == "missing"
    assert status["live_e2e_ran"] is False
    assert status["next_steps"] == ["run_visual_scheduled_self_validation"]


def test_visual_self_validation_status_surfaces_non_live_and_staleness(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    latest_path = _write_latest(
        tmp_path,
        {
            **_scheduled_report(live_decision="skip_not_enabled"),
            "generated_at": "2026-06-20T00:00:00+00:00",
        },
    )

    status = build_visual_self_validation_status(
        latest_path=latest_path,
        now=datetime(2026, 6, 22, 0, 0, tzinfo=timezone.utc),
        stale_after_hours=24,
    )

    assert status["success"] is False
    assert status["health_status"] == "warn"
    assert status["live_e2e_ran"] is False
    assert status["age_hours"] == 48.0
    assert "enable_or_force_live_self_validation" in status["next_steps"]
    assert "refresh_stale_self_validation" in status["next_steps"]


def test_visual_self_validation_status_warns_when_live_slack_upload_not_covered(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report()
    report["slack_live_upload_policy"] = {
        "decision": "skip_not_enabled",
        "enabled": False,
        "target": "D_SECRET",
    }
    report["summary"]["live_slack_upload_native_delivery_covered"] = None
    report["summary"]["live_slack_upload_uploaded_video_file_count"] = None
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["success"] is False
    assert status["health_status"] == "warn"
    assert status["slack_upload_policy"] == {
        "decision": "skip_not_enabled",
        "enabled": False,
    }
    assert "enable_live_slack_upload_self_validation" in status["next_steps"]
    assert "D_SECRET" not in json.dumps(status, ensure_ascii=False)


def test_visual_self_validation_status_asks_for_slack_target_when_upload_enabled_without_target(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report()
    report["slack_live_upload_policy"] = {
        "decision": "skip_missing_target",
        "enabled": True,
        "target": None,
    }
    report["summary"]["live_slack_upload_native_delivery_covered"] = None
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["health_status"] == "warn"
    assert "configure_live_slack_upload_target" in status["next_steps"]
    assert "enable_live_slack_upload_self_validation" not in status["next_steps"]


def test_visual_self_validation_status_cli_json(capsys, tmp_path):
    from scripts.visual_self_validation_status import main

    latest_path = _write_latest(tmp_path, _scheduled_report())

    code = main(["--latest-path", str(latest_path), "--json"])
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["health_status"] == "pass"
