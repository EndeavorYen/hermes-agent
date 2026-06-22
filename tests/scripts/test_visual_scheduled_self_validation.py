from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone


def _automation_report(*, include_live: bool) -> dict:
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
        "feedback_loop": {
            "success": True,
            "next_actions": [
                {"type": "increase_candidate_budget", "requires_human_feedback": False},
                {"type": "rerank_before_slack", "requires_human_feedback": False},
            ],
        },
        "health": {
            "success": True,
            "self_review": {"reduces_human_intervention": True, "privacy_safe": True},
        },
    }


def test_scheduled_self_validation_defaults_to_fixture_and_writes_reports(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    calls = []

    def fake_automation(*, work_dir, include_live):
        calls.append({"work_dir": work_dir, "include_live": include_live})
        return _automation_report(include_live=include_live)

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
    assert calls == [{"work_dir": tmp_path / "work", "include_live": False}]
    assert report["summary"]["feedback_action_types"] == [
        "increase_candidate_budget",
        "rerank_before_slack",
    ]
    assert report["summary"]["scheduled_self_validation_reduces_human_intervention"] is True
    assert report["summary"]["autonomous_rollout_reduces_human_intervention"] is True
    assert (tmp_path / "latest.json").exists()
    assert json.loads((tmp_path / "latest.json").read_text())["run_id"] == report["run_id"]
    assert (tmp_path / "runs" / f"{report['run_id']}.json").exists()


def test_scheduled_self_validation_runs_live_when_due(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    calls = []

    def fake_automation(*, work_dir, include_live):
        calls.append({"work_dir": work_dir, "include_live": include_live})
        return _automation_report(include_live=include_live)

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
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_live_run_at"] == "2026-06-22T08:00:00+00:00"


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
        lambda *, work_dir, include_live: (calls.append(include_live) or _automation_report(include_live=include_live)),
    )

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        live_mode="auto",
        live_enabled=True,
        min_live_interval_hours=6,
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert report["live_policy"]["decision"] == "skip_interval"
    assert calls == [False]


def test_scheduled_self_validation_separates_rollout_autonomy_from_validation(monkeypatch, tmp_path):
    from scripts import visual_scheduled_self_validation

    def fake_automation(*, work_dir, include_live):
        payload = _automation_report(include_live=include_live)
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
