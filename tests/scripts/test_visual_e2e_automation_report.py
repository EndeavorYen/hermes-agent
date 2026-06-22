from __future__ import annotations

import json


def test_visual_e2e_automation_fixture_default(tmp_path):
    from scripts.visual_e2e_automation_report import build_visual_e2e_automation_report

    report = build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is True
    assert report["mode"] == "fixture"
    assert report["fixture_e2e"]["success"] is True
    assert report["agent_mode"]["success"] is True
    assert report["live_e2e"]["status"] == "not_requested"
    assert report["health"]["success"] is True


def test_visual_e2e_automation_fails_when_agent_mode_regression_fails(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_agent_mode_regression_report",
        lambda: {"success": False, "failures": [{"case_id": "text_video_image_first"}]},
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is False
    assert "agent_mode_failed" in report["failures"]


def test_visual_e2e_automation_live_skips_without_enable(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    monkeypatch.setattr(visual_e2e_automation_report, "live_provider_enabled", lambda: False)

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(
        work_dir=tmp_path,
        include_live=True,
    )

    assert report["success"] is True
    assert report["live_e2e"]["status"] == "skipped"
    assert report["live_e2e"]["reason"] == "live_provider_not_enabled"


def test_visual_e2e_automation_live_uses_runtime_home_not_fixture_work_dir(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    calls = []

    def fake_build_live_provider_e2e_report(*, mode, work_dir=None, **kwargs):
        calls.append({"mode": mode, "work_dir": work_dir, **kwargs})
        return {
            "success": True,
            "provider_mode": mode,
            "failures": [],
            "payload": {"success": True, "image_count": 1, "video_count": 1},
            "evidence": {
                "request_id": f"{mode}_request",
                "image_count": 1,
                "video_count": 1,
                "attempt_count": 2,
                "artifact_count": 2,
                "judgment_count": 2,
                "ranking_count": 2,
                "learning_trace_count": 2,
                "judgments_with_learning_metadata": 2,
                "providers": ["fixture" if mode == "fixture" else "xai"],
                "require_video": True,
            },
        }

    monkeypatch.setattr(visual_e2e_automation_report, "live_provider_enabled", lambda: True)
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_report",
        fake_build_live_provider_e2e_report,
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(
        work_dir=tmp_path,
        include_live=True,
    )

    assert report["success"] is True
    assert calls[0]["mode"] == "fixture"
    assert calls[0]["work_dir"] == tmp_path
    assert calls[1]["mode"] == "live"
    assert calls[1]["work_dir"] is None


def test_visual_e2e_automation_cli_json(capsys, tmp_path):
    from scripts.visual_e2e_automation_report import main

    code = main(["--work-dir", str(tmp_path), "--json"])
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["fixture_e2e"]["success"] is True
