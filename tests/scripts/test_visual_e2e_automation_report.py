from __future__ import annotations

import json


def test_visual_e2e_automation_fixture_default(tmp_path):
    from scripts.visual_e2e_automation_report import build_visual_e2e_automation_report

    report = build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is True
    assert report["mode"] == "fixture"
    assert report["fixture_e2e"]["success"] is True
    assert report["live_e2e"]["status"] == "not_requested"
    assert report["health"]["success"] is True


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


def test_visual_e2e_automation_cli_json(capsys, tmp_path):
    from scripts.visual_e2e_automation_report import main

    code = main(["--work-dir", str(tmp_path), "--json"])
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["fixture_e2e"]["success"] is True
