import json


def test_visual_agent_mode_regression_report_passes_default_fixture_set():
    from scripts.visual_agent_mode_regression_report import build_visual_agent_mode_regression_report

    report = build_visual_agent_mode_regression_report()

    assert report["success"] is True
    assert report["case_count"] >= 4
    assert report["failures"] == []
    assert {case["case_id"] for case in report["cases"]} >= {
        "image_plus_video_reference",
        "attachment_to_video",
        "text_video_image_first",
    }
    assert all("prompt" not in case for case in report["cases"])
    product_case = next(case for case in report["cases"] if case["case_id"] == "image_only_product")
    assert product_case["arguments"]["aspect_ratio"] == "16:9"


def test_visual_agent_mode_regression_report_flags_broken_image_first_plan(monkeypatch):
    from scripts import visual_agent_mode_regression_report

    real_planner = visual_agent_mode_regression_report.plan_visual_agent_request

    def fake_planner(prompt, *, attachments=None):
        plan = real_planner(prompt, attachments=attachments)
        if plan["reason"] == "text_to_video_image_first_request":
            plan["arguments"].pop("candidate_budget", None)
        return plan

    monkeypatch.setattr(
        visual_agent_mode_regression_report,
        "plan_visual_agent_request",
        fake_planner,
    )

    report = visual_agent_mode_regression_report.build_visual_agent_mode_regression_report()

    assert report["success"] is False
    assert any(
        failure["case_id"] == "text_video_image_first"
        and "candidate_budget_lt_2" in failure["failures"]
        for failure in report["failures"]
    )


def test_visual_agent_mode_regression_report_cli_json(capsys):
    from scripts.visual_agent_mode_regression_report import main

    code = main(["--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
