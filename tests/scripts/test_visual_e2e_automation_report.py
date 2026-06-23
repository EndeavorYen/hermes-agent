from __future__ import annotations

import json


def test_visual_e2e_automation_fixture_default(tmp_path):
    from scripts.visual_e2e_automation_report import build_visual_e2e_automation_report

    report = build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is True
    assert report["mode"] == "fixture"
    assert report["fixture_e2e"]["success"] is True
    assert report["agent_mode"]["success"] is True
    assert report["closed_loop_regression"]["success"] is True
    assert report["conversation_route"]["success"] is True
    assert report["storyboard_execution"]["success"] is True
    assert report["storyboard_execution"]["evidence"]["storyboard_execution"]["delivers_composed_video"] is True
    assert (
        report["storyboard_execution"]["evidence"]["storyboard_execution"]["shots_use_single_ranked_images"]
        is True
    )
    assert report["storyboard_slack_delivery"]["success"] is True
    assert report["storyboard_slack_delivery"]["delivery"]["deliverable_count"] == 1
    assert report["storyboard_slack_delivery"]["visual"]["storyboard_execution"]["delivers_composed_video"] is True
    assert report["slack_conversation"]["success"] is True
    assert report["live_e2e"]["status"] == "not_requested"
    assert report["health"]["success"] is True
    assert report["quality_calibration"]["success"] is True


def test_visual_e2e_automation_fails_fast_when_live_runner_missing_dependencies(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_e2e_automation_report

    called = []
    action = {
        "type": "configure_visual_runtime_dependencies",
        "track": "operator_setup",
        "reason": "visual_runtime_missing_python_modules",
        "requires_human_feedback": False,
        "requires_operator_setup": True,
        "activation_status": "operator_setup",
        "source": "visual_runtime_environment",
        "missing_modules": ["openai", "aiohttp"],
        "operator_setup_actions": [
            {
                "provider": "python_runtime",
                "missing_env_vars": [],
                "post_setup": "Run with project venv.",
            }
        ],
    }

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_runtime_environment_diagnostic",
        lambda **_kwargs: {
            "success": False,
            "required_modules": ["aiohttp", "openai"],
            "missing_modules": ["openai", "aiohttp"],
            "next_actions": [action],
        },
    )
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_agent_mode_regression_report",
        lambda: called.append("agent_mode") or {"success": True},
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(
        work_dir=tmp_path,
        include_live=True,
        include_live_slack_upload=True,
    )

    assert called == []
    assert report["success"] is False
    assert report["mode"] == "runtime_environment_failed"
    assert report["failures"] == ["runtime_environment_missing_dependencies"]
    assert report["runtime_environment"]["missing_modules"] == ["openai", "aiohttp"]
    assert report["self_improvement"] == {
        "next_actions": [action],
        "action_count": 1,
        "reduces_human_intervention": False,
        "privacy_safe": True,
    }
    assert report["live_e2e"] == {
        "status": "skipped",
        "reason": "runtime_environment_missing_dependencies",
    }


def test_visual_e2e_automation_includes_quality_suite(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    calls = []
    burn_calls = []

    def fake_quality_suite(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "provider_mode": kwargs["mode"],
            "case_count": 2,
            "failures": [],
            "cases": [
                {"case_id": "product_photo_video", "success": True, "failures": []},
                {"case_id": "fashion_portrait_video", "success": True, "failures": []},
            ],
        }

    def fake_live_provider_e2e_report(*, mode, work_dir=None, **kwargs):
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

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_report",
        fake_live_provider_e2e_report,
    )
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_suite_report",
        fake_quality_suite,
    )
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_quality_burn_report",
        lambda **kwargs: (
            burn_calls.append(kwargs)
            or {
                "success": True,
                "mode": "live",
                "suite": {
                    "success": True,
                    "provider_mode": "live",
                    "case_count": 2,
                    "failures": [],
                    "cases": [],
                },
                "next_actions": [
                    {
                        "type": "increase_candidate_budget",
                        "track": "aesthetic",
                        "reason": "live_quality_burn_quality_gate_failed",
                        "confidence": 0.7,
                        "evidence_count": 1,
                        "requires_human_feedback": False,
                        "activation_status": "next_run",
                        "source": "live_quality_burn",
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(visual_e2e_automation_report, "live_provider_enabled", lambda: True)

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(
        work_dir=tmp_path,
        include_live=True,
    )

    assert report["success"] is True
    assert report["fixture_quality_suite"]["case_count"] == 2
    assert report["live_quality_suite"]["case_count"] == 2
    assert report["live_quality_burn"]["success"] is True
    assert report["self_improvement"]["next_actions"][-1]["source"] == "live_quality_burn"
    assert calls[0]["mode"] == "fixture"
    assert calls[0]["work_dir"] == tmp_path
    assert calls[0]["include_video_repair_probe"] is True
    assert calls[0]["include_storyboard_probe"] is True
    assert calls[1]["mode"] == "live"
    assert calls[1]["work_dir"] is None
    assert calls[1]["include_video_repair_probe"] is True
    assert calls[1]["include_storyboard_probe"] is True
    assert burn_calls[0]["mode"] == "live"
    assert burn_calls[0]["work_dir"] is None
    assert burn_calls[0]["include_storyboard_probe"] is True


def test_visual_e2e_automation_quarantines_later_live_suites_after_live_e2e_quota(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_e2e_automation_report

    suite_calls = []
    burn_calls = []

    def fake_live_provider_e2e_report(*, mode, work_dir=None, **kwargs):
        if mode == "fixture":
            return {
                "success": True,
                "provider_mode": mode,
                "failures": [],
                "payload": {"success": True, "image_count": 1, "video_count": 1},
                "evidence": {"quality_gate": {"success": True, "min_score": 0.82}},
            }
        return {
            "success": False,
            "provider_mode": mode,
            "failures": ["provider_generation_failed"],
            "payload": {"success": False, "error_type": "api_error"},
            "evidence": {
                "recovery_summary": {
                    "provider_failure_count": 1,
                    "provider_failure_classes": {"quota_exceeded": 1},
                    "provider_error_codes": {
                        "personal-team-blocked:spending-limit": 1,
                    },
                    "retry_attempt_count": 0,
                    "negotiation_attempted": False,
                    "negotiation_success": False,
                    "content_moderation_recovered": False,
                    "recovered_failure_classes": [],
                }
            },
        }

    def fake_quality_suite(**kwargs):
        suite_calls.append(kwargs)
        return {
            "success": True,
            "provider_mode": kwargs["mode"],
            "case_count": 1,
            "failures": [],
            "recovery_summary": {
                "provider_failure_count": 0,
                "provider_failure_classes": {},
                "provider_error_codes": {},
            },
            "quality_repair_summary": {},
            "cases": [],
        }

    def fake_live_quality_burn_report(**kwargs):
        burn_calls.append(kwargs)
        return {
            "success": False,
            "mode": "live",
            "summary": {"provider_failure_count": 1},
            "next_actions": [
                {
                    "type": "resolve_provider_quota_or_switch_provider",
                    "track": "provider",
                    "reason": "live_quality_burn_provider_quota_exceeded",
                    "requires_human_feedback": False,
                    "requires_operator_setup": True,
                    "source": "live_quality_burn",
                }
            ],
            "suite": kwargs["suite_report"],
        }

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_report",
        fake_live_provider_e2e_report,
    )
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_suite_report",
        fake_quality_suite,
    )
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_quality_burn_report",
        fake_live_quality_burn_report,
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(
        work_dir=tmp_path,
        include_live=True,
    )

    assert [call["mode"] for call in suite_calls] == ["fixture"]
    assert report["live_e2e"]["success"] is False
    assert report["live_quality_suite"]["status"] == "skipped_provider_account_blocked"
    assert report["live_quality_suite"]["recovery_summary"]["provider_failure_classes"] == {
        "quota_exceeded": 1
    }
    assert report["live_quality_suite"]["recovery_summary"]["provider_error_codes"] == {
        "personal-team-blocked:spending-limit": 1
    }
    assert burn_calls[0]["suite_report"] == report["live_quality_suite"]
    assert [
        action["type"]
        for action in report["self_improvement"]["next_actions"]
        if action.get("source") == "live_quality_burn"
    ] == ["resolve_provider_quota_or_switch_provider"]


def test_visual_e2e_automation_fails_when_closed_loop_regression_fails(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_closed_loop_regression_report",
        lambda: {
            "success": False,
            "case_count": 1,
            "failure_count": 1,
            "failures": [{"case_id": "focus_operator_legwear", "failures": ["policy_not_applied"]}],
            "cases": [],
        },
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is False
    assert "closed_loop_regression_failed" in report["failures"]
    assert report["closed_loop_regression"]["failure_count"] == 1


def test_visual_e2e_automation_exports_quality_suite_next_actions(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    def fake_quality_suite(**kwargs):
        return {
            "success": True,
            "provider_mode": kwargs["mode"],
            "case_count": 1,
            "failures": [],
            "quality_repair_summary": {
                "attempt_count": 1,
                "success_count": 1,
                "selected_repair_count": 1,
                "success_rate": 1.0,
                "selected_repair_rate": 1.0,
                "by_modality": {
                    "video": {
                        "attempt_count": 1,
                        "success_count": 1,
                        "selected_repair_count": 1,
                    }
                },
            },
            "cases": [],
        }

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_suite_report",
        fake_quality_suite,
    )
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_feedback_loop_report",
        lambda _path: {"success": True, "failures": [], "next_actions": []},
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["self_improvement"]["next_actions"] == [
        {
            "type": "prefer_quality_repair_retry",
            "track": "repair",
            "reason": "fixture_quality_suite_video_repair_succeeded",
            "confidence": 0.9,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "source": "fixture_quality_suite",
            "modality": "video",
            "success_rate": 1.0,
            "selected_repair_rate": 1.0,
        }
    ]
    assert report["self_improvement"]["reduces_human_intervention"] is True


def test_visual_e2e_automation_exports_quality_focus_actions_from_failed_fixture_suite(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_e2e_automation_report

    def fake_quality_suite(**kwargs):
        return {
            "success": False,
            "provider_mode": kwargs["mode"],
            "case_count": 1,
            "failures": [
                "fashion_portrait_video:quality_focus_failed:adult_fashion_portrait",
                "fashion_portrait_video:quality_focus_failed:legwear_material",
            ],
            "quality_repair_summary": {},
            "quality_focus_summary": {
                "outcome_count": 2,
                "success_count": 0,
                "failure_count": 2,
                "successful_focuses": [],
                "failed_focuses": ["adult_fashion_portrait", "legwear_material"],
                "outcomes": [
                    {
                        "case_id": "fashion_portrait_video",
                        "focus": "adult_fashion_portrait",
                        "success": False,
                        "dimension": "subject_beauty",
                        "quality_issues": ["subject_not_attractive"],
                        "preference_dimension_failures": [
                            {
                                "artifact_id": "var_subject",
                                "dimension": "subject_beauty",
                                "score": 0.31,
                                "issue": "subject_not_attractive",
                            }
                        ],
                    },
                    {
                        "case_id": "fashion_portrait_video",
                        "focus": "legwear_material",
                        "success": False,
                        "dimension": "fashion_material_quality",
                        "quality_issues": ["stockings_bad"],
                        "preference_dimension_failures": [
                            {
                                "artifact_id": "var_legwear",
                                "dimension": "fashion_material_quality",
                                "score": 0.28,
                                "issue": "stockings_bad",
                            }
                        ],
                    },
                ],
            },
            "cases": [],
        }

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_suite_report",
        fake_quality_suite,
    )
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_feedback_loop_report",
        lambda _path: {"success": True, "failures": [], "next_actions": []},
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is False
    assert "fixture_quality_suite_failed" in report["failures"]
    quality_actions = [
        action
        for action in report["self_improvement"]["next_actions"]
        if action["source"] == "fixture_quality_suite"
    ]
    assert quality_actions == [
        {
            "type": "apply_quality_focus_operator",
            "track": "aesthetic",
            "reason": "fixture_quality_suite_quality_focus_failed",
            "confidence": 0.76,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "source": "fixture_quality_suite",
            "focus": "adult_fashion_portrait",
            "dimension": "subject_beauty",
            "strategy_operator": "refine_adult_fashion_portrait",
            "repair_hint": "improve_subject_beauty",
            "case_ids": ["fashion_portrait_video"],
            "quality_issues": ["subject_not_attractive"],
        },
        {
            "type": "apply_quality_focus_operator",
            "track": "aesthetic",
            "reason": "fixture_quality_suite_quality_focus_failed",
            "confidence": 0.76,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "source": "fixture_quality_suite",
            "focus": "legwear_material",
            "dimension": "fashion_material_quality",
            "strategy_operator": "refine_legwear_material",
            "repair_hint": "improve_fashion_material_quality",
            "case_ids": ["fashion_portrait_video"],
            "quality_issues": ["stockings_bad"],
        },
    ]
    assert report["self_improvement"]["reduces_human_intervention"] is True


def test_visual_e2e_automation_passes_case_timeout_to_quality_suites(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    suite_calls = []

    def fake_quality_suite(**kwargs):
        suite_calls.append(kwargs)
        return {
            "success": True,
            "provider_mode": kwargs["mode"],
            "case_count": 1,
            "failures": [],
            "cases": [],
        }

    def fake_live_provider_e2e_report(*, mode, work_dir=None, **kwargs):
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

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_report",
        fake_live_provider_e2e_report,
    )
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_suite_report",
        fake_quality_suite,
    )
    monkeypatch.setattr(visual_e2e_automation_report, "live_provider_enabled", lambda: True)

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(
        work_dir=tmp_path,
        include_live=True,
        case_timeout_seconds=123,
    )

    assert report["success"] is True
    assert suite_calls == [
            {
                "mode": "fixture",
                "work_dir": tmp_path,
                "include_video_repair_probe": True,
                "include_storyboard_probe": True,
                "case_timeout_seconds": 123,
            },
            {
                "mode": "live",
                "work_dir": None,
                "include_video_repair_probe": True,
                "include_storyboard_probe": True,
                "case_timeout_seconds": 123,
            },
        ]


def test_visual_e2e_automation_fails_when_quality_suite_fails(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_suite_report",
        lambda **kwargs: {
            "success": False,
            "provider_mode": kwargs["mode"],
            "case_count": 2,
            "failures": ["fashion_portrait_video:selected_quality_issue_detected"],
            "cases": [],
        },
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is False
    assert "fixture_quality_suite_failed" in report["failures"]


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


def test_visual_e2e_automation_fails_when_conversation_route_fails(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_conversation_route_report",
        lambda: {"success": False, "failures": ["visual_agent_guidance_missing"]},
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is False
    assert "conversation_route_failed" in report["failures"]
    assert report["conversation_route"]["failures"] == ["visual_agent_guidance_missing"]


def test_visual_e2e_automation_fails_when_slack_conversation_fails(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_slack_conversation_e2e_report",
        lambda **_kwargs: {"success": False, "failures": ["slack_ingress_not_dispatched"]},
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is False
    assert "slack_conversation_failed" in report["failures"]
    assert report["slack_conversation"]["failures"] == ["slack_ingress_not_dispatched"]


def test_visual_e2e_automation_exports_slack_conversation_repair_actions(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    repair_action = {
        "type": "safe_reframe_provider_retry",
        "track": "provider",
        "reason": "slack_conversation_content_moderation_failure",
        "confidence": 0.75,
        "evidence_count": 2,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "slack_conversation_e2e",
        "provider_failure_classes": {"content_moderation": 2},
        "provider_error_codes": {"api_error": 2},
    }
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_slack_conversation_e2e_report",
        lambda **_kwargs: {"success": True, "failures": [], "next_actions": [repair_action]},
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is True
    assert repair_action in report["self_improvement"]["next_actions"]
    assert report["self_improvement"]["reduces_human_intervention"] is True


def test_visual_e2e_automation_exports_feedback_loop_next_actions(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    feedback_action = {
        "type": "increase_candidate_budget",
        "track": "aesthetic",
        "reason": "provider_renders_but_auto_judge_rejected_quality",
        "confidence": 0.65,
        "evidence_count": 12,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "feedback_loop",
    }
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_feedback_loop_report",
        lambda _path: {"success": True, "failures": [], "next_actions": [feedback_action]},
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is True
    assert feedback_action in report["self_improvement"]["next_actions"]
    assert report["self_improvement"]["reduces_human_intervention"] is True


def test_visual_e2e_automation_dedupe_preserves_distinct_quality_actions():
    from scripts.visual_e2e_automation_report import _dedupe_actions

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
        "source": "live_quality_burn",
        "dimension": "fashion_material_quality",
        "focus": "legwear_material",
        "strategy_operator": "refine_legwear_material",
    }
    composition_focus = {
        "type": "apply_quality_focus_operator",
        "source": "live_quality_burn",
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
            dict(face_repair),
        ]
    ) == [
        face_repair,
        material_repair,
        legwear_focus,
        composition_focus,
    ]


def test_visual_e2e_automation_fails_when_quality_calibration_fails(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_quality_calibration_report",
        lambda _path: {"success": False, "failures": ["judge_human_disagreement_rate_high"]},
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(work_dir=tmp_path)

    assert report["success"] is False
    assert "quality_calibration_failed" in report["failures"]
    assert report["quality_calibration"]["failures"] == ["judge_human_disagreement_rate_high"]


def test_visual_e2e_automation_include_live_bypasses_env_gate(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    calls = []

    def fake_build_live_provider_e2e_report(*, mode, work_dir=None, **kwargs):
        calls.append({"tool": "live_e2e", "mode": mode, "work_dir": work_dir})
        return {
            "success": True,
            "provider_mode": mode,
            "payload": {"success": True, "image_count": 1, "video_count": 1},
            "evidence": {"quality_gate": {"success": True, "min_score": 0.82}},
            "failures": [],
        }

    def fake_build_live_provider_e2e_suite_report(*, mode, work_dir=None, **kwargs):
        calls.append({"tool": "live_suite", "mode": mode, "work_dir": work_dir})
        return {
            "success": True,
            "case_count": 1,
            "failures": [],
            "quality_repair_summary": {},
            "recovery_summary": {},
        }

    def fake_build_live_quality_burn_report(**kwargs):
        calls.append({"tool": "live_burn", "mode": kwargs.get("mode"), "work_dir": kwargs.get("work_dir")})
        return {
            "success": True,
            "summary": {"case_count": 1, "min_quality_score": 0.82},
            "next_actions": [],
        }

    monkeypatch.setattr(visual_e2e_automation_report, "live_provider_enabled", lambda: False)
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_report",
        fake_build_live_provider_e2e_report,
    )
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_suite_report",
        fake_build_live_provider_e2e_suite_report,
    )
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_quality_burn_report",
        fake_build_live_quality_burn_report,
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(
        work_dir=tmp_path,
        include_live=True,
    )

    assert report["success"] is True
    assert report["live_e2e"]["success"] is True
    assert report["live_quality_suite"]["success"] is True
    assert report["live_quality_burn"]["success"] is True
    assert {"tool": "live_e2e", "mode": "live", "work_dir": None} in calls
    assert {"tool": "live_suite", "mode": "live", "work_dir": None} in calls
    assert {"tool": "live_burn", "mode": "live", "work_dir": None} in calls


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

    suite_calls = []

    def fake_quality_suite(*, mode, work_dir=None, **kwargs):
        suite_calls.append({"mode": mode, "work_dir": work_dir, **kwargs})
        return {
            "success": True,
            "provider_mode": mode,
            "case_count": 2,
            "failures": [],
            "cases": [],
        }

    monkeypatch.setattr(visual_e2e_automation_report, "live_provider_enabled", lambda: True)
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_report",
        fake_build_live_provider_e2e_report,
    )
    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_live_provider_e2e_suite_report",
        fake_quality_suite,
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
    assert suite_calls[0]["mode"] == "fixture"
    assert suite_calls[0]["work_dir"] == tmp_path
    assert suite_calls[1]["mode"] == "live"
    assert suite_calls[1]["work_dir"] is None


def test_visual_e2e_automation_can_run_live_slack_upload_with_runtime_home(monkeypatch, tmp_path):
    from scripts import visual_e2e_automation_report

    calls = []

    def fake_slack_delivery(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "mode": kwargs["mode"],
            "failures": [],
            "delivery": {"deliverable_count": 2, "sent_count": 2},
        }

    monkeypatch.setattr(
        visual_e2e_automation_report,
        "build_visual_slack_delivery_e2e_report",
        fake_slack_delivery,
    )

    report = visual_e2e_automation_report.build_visual_e2e_automation_report(
        work_dir=tmp_path,
        include_live_slack_upload=True,
    )

    assert report["success"] is True
    assert calls[0]["mode"] == "fixture"
    assert calls[0]["work_dir"] == tmp_path
    assert calls[0].get("upload") is None
    fixture_calls = [call for call in calls if call["mode"] == "fixture"]
    live_call = next(call for call in calls if call["mode"] == "live")
    assert len(fixture_calls) == 2
    assert any(call.get("storyboard") for call in fixture_calls)
    assert live_call["work_dir"] is None
    assert live_call["upload"] is True
    assert report["live_slack_delivery"]["success"] is True


def test_visual_e2e_automation_cli_json(capsys, tmp_path):
    from scripts.visual_e2e_automation_report import main

    code = main(["--work-dir", str(tmp_path), "--json"])
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["fixture_e2e"]["success"] is True
