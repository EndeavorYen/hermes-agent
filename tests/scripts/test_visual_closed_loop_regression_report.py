def test_visual_closed_loop_regression_report_proves_focus_policy_is_applied():
    from scripts.visual_closed_loop_regression_report import build_visual_closed_loop_regression_report

    report = build_visual_closed_loop_regression_report()

    assert report["success"] is True
    assert report["case_count"] >= 4
    assert report["failure_count"] == 0
    assert "closed-loop private prompt" not in str(report)

    focus_case = next(case for case in report["cases"] if case["case_id"] == "focus_operator_legwear")
    assert focus_case["action_type"] == "apply_quality_focus_operator"
    assert focus_case["policy_delta"]["candidate_budget_increased"] is True
    assert focus_case["policy_delta"]["rerank_enabled"] is True
    assert focus_case["policy_delta"]["quality_repair_enabled"] is True
    assert focus_case["quality_guidance"]["image_enabled"] is True
    assert focus_case["quality_guidance"]["prompt_guidance_applied"] is True
    assert "fashion_material_quality" in focus_case["quality_guidance"]["dimension_terms"]

    video_case = next(case for case in report["cases"] if case["case_id"] == "image_first_video_operator")
    assert video_case["policy_delta"]["image_first_video_enabled"] is True
    assert video_case["policy_delta"]["candidate_budget_increased"] is True

    strategy_case = next(case for case in report["cases"] if case["case_id"] == "proven_strategy_operator")
    assert strategy_case["policy_delta"]["strategy_preference_applied"] is True
    assert strategy_case["policy_delta"]["image_first_video_enabled"] is True

    evidence_case = next(case for case in report["cases"] if case["case_id"] == "preference_dimension_evidence_operator")
    assert evidence_case["action_type"] == "require_preference_dimension_evidence"
    assert evidence_case["policy_delta"]["preference_dimension_evidence_required"] is True
    assert evidence_case["policy_delta"]["candidate_budget_increased"] is False
    assert evidence_case["policy_delta"]["quality_repair_enabled"] is False


def test_visual_closed_loop_regression_report_cli_json(capsys):
    from scripts.visual_closed_loop_regression_report import main

    code = main(["--json"])

    assert code == 0
    assert '"success": true' in capsys.readouterr().out
