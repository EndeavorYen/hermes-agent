import os
import subprocess
import sys


def test_visual_conversation_route_report_verifies_friendly_agent_entrypoint():
    from scripts.visual_conversation_route_report import build_visual_conversation_route_report

    report = build_visual_conversation_route_report()

    assert report["success"] is True
    assert report["recommended_tool"] == "visual_agent_generate"
    assert report["case_count"] >= 3
    assert report["failures"] == []
    assert report["contract"]["raw_image_video_tool_avoidance_present"] is True
    assert {case["case_id"] for case in report["cases"]} >= {
        "friendly_product_image_video",
        "friendly_draw_character",
        "friendly_text_video",
        "friendly_move_attachment_video",
        "friendly_storyboard_video",
    }
    storyboard_case = next(case for case in report["cases"] if case["case_id"] == "friendly_storyboard_video")
    assert storyboard_case["arguments"]["storyboard_enabled"] is True
    assert storyboard_case["arguments"]["storyboard_shot_count"] == 3
    assert all("prompt" not in case for case in report["cases"])
    assert all(case["arguments"]["has_autonomy_level"] is False for case in report["cases"])


def test_visual_conversation_route_report_fails_without_visual_agent_guidance(monkeypatch):
    from scripts import visual_conversation_route_report

    monkeypatch.setattr(
        visual_conversation_route_report,
        "build_visual_package_tool_guidance",
        lambda _tools: "# Visual package generation\nUse visual_package_generate directly.",
    )

    report = visual_conversation_route_report.build_visual_conversation_route_report()

    assert report["success"] is False
    assert "visual_agent_guidance_missing" in report["failures"]


def test_visual_conversation_route_report_cli_json(capsys):
    from scripts.visual_conversation_route_report import main

    code = main(["--json"])

    assert code == 0
    assert '"success": true' in capsys.readouterr().out


def test_visual_conversation_route_report_script_runs_directly_from_repo_root():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, "scripts/visual_conversation_route_report.py", "--json"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"success": true' in result.stdout
