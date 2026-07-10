import json
from datetime import datetime
from datetime import timezone


def test_scheduled_self_validation_defaults_to_fixture_and_writes_reports(tmp_path):
    from scripts import visual_scheduled_self_validation

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        now=datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc),
    )

    assert report["success"] is True
    assert report["mode"] == "fixture"
    assert report["live_policy"] == {
        "mode": "off",
        "decision": "not_requested",
        "live_enabled": False,
    }
    assert report["summary"]["visual_agent_tool_registered"] is True
    assert report["summary"]["visual_package_tool_registered"] is True
    assert report["summary"]["visual_agent_planner_image_plus_video"] is True
    assert report["summary"]["visual_agent_planner_image_first_video"] is True
    assert report["summary"]["prompt_disclosure_guard_active"] is True
    assert report["self_review"]["cron_safe"] is True
    assert report["self_review"]["live_e2e_requires_opt_in"] is True
    assert (tmp_path / "latest.json").exists()
    assert json.loads((tmp_path / "latest.json").read_text())["run_id"] == report["run_id"]
    assert (tmp_path / "runs" / f"{report['run_id']}.json").exists()


def test_scheduled_self_validation_auto_live_requires_env_opt_in(tmp_path):
    from scripts import visual_scheduled_self_validation

    report = visual_scheduled_self_validation.build_visual_scheduled_self_validation_report(
        output_dir=tmp_path,
        live_mode="auto",
        live_enabled=False,
        now=datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc),
    )

    assert report["success"] is True
    assert report["mode"] == "fixture"
    assert report["live_policy"] == {
        "mode": "auto",
        "decision": "skip_not_enabled",
        "live_enabled": False,
    }
    assert report["self_review"]["live_e2e_requires_opt_in"] is True


def test_scheduled_self_validation_cli_json_allow_failures(capsys, tmp_path):
    from scripts import visual_scheduled_self_validation

    exit_code = visual_scheduled_self_validation.main(
        [
            "--output-dir",
            str(tmp_path),
            "--live-mode",
            "off",
            "--json",
            "--allow-failures",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["mode"] == "fixture"
    assert payload["summary"]["scheduled_self_validation_entrypoint_ready"] is True
