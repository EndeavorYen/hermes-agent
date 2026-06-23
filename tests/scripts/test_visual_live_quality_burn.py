from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone


def _suite_with_quality_failure() -> dict:
    return {
        "success": False,
        "provider_mode": "live",
        "case_count": 2,
        "failures": [
            "fashion_portrait_video:quality_gate_failed",
            "fashion_portrait_video:selected_quality_issue_detected",
        ],
        "recovery_summary": {
            "provider_failure_count": 0,
            "provider_failure_classes": {},
            "provider_error_codes": {},
            "retry_attempt_count": 0,
            "negotiation_attempted_case_count": 0,
            "negotiation_success_case_count": 0,
            "content_moderation_recovered_case_count": 0,
            "recovered_failure_classes": [],
        },
        "quality_repair_summary": {
            "attempt_count": 0,
            "success_count": 0,
            "selected_repair_count": 0,
            "by_modality": {},
        },
        "cases": [
            {
                "case_id": "product_photo_video",
                "success": True,
                "failures": [],
                "evidence": {
                    "quality_gate": {
                        "success": True,
                        "min_score": 0.78,
                        "quality_issues": [],
                    },
                    "image_count": 1,
                    "video_count": 1,
                    "ranking_count": 2,
                },
            },
            {
                "case_id": "fashion_portrait_video",
                "success": False,
                "failures": ["quality_gate_failed", "selected_quality_issue_detected"],
                "evidence": {
                    "quality_gate": {
                        "success": False,
                        "min_score": 0.31,
                        "quality_issues": ["subject_not_attractive", "stockings_bad"],
                        "low_quality_artifacts": ["var_bad"],
                    },
                    "image_count": 1,
                    "video_count": 1,
                    "ranking_count": 2,
                },
            },
        ],
    }


def _suite_with_provider_outage_and_no_quality_evidence() -> dict:
    return {
        "success": False,
        "provider_mode": "live",
        "case_count": 1,
        "failures": [
            "product_photo_video:quality_gate_failed",
            "product_photo_video:provider_generation_failed",
            "product_photo_video:provider_unavailable_after_retry",
        ],
        "recovery_summary": {
            "provider_failure_count": 1,
            "provider_failure_classes": {"provider_unavailable": 1},
            "provider_error_codes": {"connection_error": 1},
            "retry_attempt_count": 1,
            "negotiation_attempted_case_count": 1,
            "negotiation_success_case_count": 0,
            "content_moderation_recovered_case_count": 0,
            "recovered_failure_classes": [],
        },
        "quality_repair_summary": {
            "attempt_count": 0,
            "success_count": 0,
            "selected_repair_count": 0,
            "by_modality": {},
        },
        "cases": [
            {
                "case_id": "product_photo_video",
                "success": False,
                "failures": [
                    "quality_gate_failed",
                    "provider_generation_failed",
                    "provider_unavailable_after_retry",
                ],
                "payload": {
                    "success": False,
                    "package_status": "failed",
                    "image_count": 0,
                    "video_count": 0,
                },
                "evidence": {
                    "artifact_count": 0,
                    "image_count": 0,
                    "video_count": 0,
                    "judgment_count": 0,
                    "judgments_with_learning_metadata": 0,
                    "quality_gate": {
                        "success": False,
                        "min_score": None,
                        "quality_issues": [],
                        "preference_dimension_failures": [],
                    },
                    "provider_error_codes": {"connection_error": 1},
                    "provider_failure_classes": {"provider_unavailable": 1},
                    "video_source": {
                        "image_first_for_video": True,
                        "ranked_selected_image_artifact_id": None,
                        "require_video": True,
                        "single_video_source_image": False,
                        "source_image_artifact_id": None,
                        "uses_ranked_selected_image": False,
                        "video_source_image_count": 0,
                        "video_source_policy": "none",
                    },
                },
            }
        ],
    }


def test_visual_live_quality_burn_writes_report_and_actions(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    calls = []

    def fake_suite(**kwargs):
        calls.append(kwargs)
        return _suite_with_quality_failure()

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        fake_suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path / "burn",
        work_dir=tmp_path / "work",
        max_cases=1,
        case_timeout_seconds=123,
        now=datetime(2026, 6, 22, 10, 0, tzinfo=timezone.utc),
    )

    assert report["success"] is False
    assert report["mode"] == "live"
    assert report["run_id"] == "20260622T100000Z"
    assert report["burn_budget"] == {
        "max_cases": 1,
        "case_timeout_seconds": 123.0,
        "case_count": 1,
    }
    assert calls[0]["mode"] == "live"
    assert calls[0]["work_dir"] == tmp_path / "work"
    assert calls[0]["case_timeout_seconds"] == 123
    assert len(calls[0]["cases"]) == 1
    assert report["summary"]["case_count"] == 2
    assert report["summary"]["failed_case_count"] == 1
    assert report["summary"]["min_quality_score"] == 0.31
    action_types = [action["type"] for action in report["next_actions"]]
    assert action_types == ["increase_candidate_budget", "rerank_before_slack"]
    assert all(action["requires_human_feedback"] is False for action in report["next_actions"])
    assert report["self_review"]["reduces_human_intervention"] is True
    assert report["self_review"]["privacy_safe"] is True
    latest = json.loads((tmp_path / "burn" / "latest.json").read_text())
    assert latest["run_id"] == report["run_id"]
    assert (tmp_path / "burn" / "runs" / "20260622T100000Z.json").exists()


def test_visual_live_quality_burn_does_not_emit_aesthetic_actions_without_quality_evidence(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_live_quality_burn

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: _suite_with_provider_outage_and_no_quality_evidence(),
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path / "burn",
        work_dir=tmp_path / "work",
        now=datetime(2026, 6, 22, 10, 0, tzinfo=timezone.utc),
    )

    assert report["summary"]["min_quality_score"] is None
    assert report["summary"]["quality_issue_count"] == 0
    assert report["summary"]["provider_failure_count"] == 1
    assert report["summary"]["image_first_video_source_failure_count"] == 0
    assert report["summary"]["image_first_video_source_not_single_count"] == 0
    assert "increase_candidate_budget" not in [
        action["type"] for action in report["next_actions"]
    ]
    assert "rerank_before_slack" not in [
        action["type"] for action in report["next_actions"]
    ]
    assert "prefer_image_first_video" not in [
        action["type"] for action in report["next_actions"]
    ]
    assert "enforce_single_video_source_image" not in [
        action["type"] for action in report["next_actions"]
    ]
    assert all(action["track"] != "aesthetic" for action in report["next_actions"])
    assert [action["type"] for action in report["next_actions"]] == [
        "check_provider_connectivity_or_retry",
    ]


def test_visual_live_quality_burn_can_request_repair_probe(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    calls = []

    def fake_suite(**kwargs):
        calls.append(kwargs)
        return _suite_with_quality_failure()

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        fake_suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path / "burn",
        work_dir=tmp_path / "work",
        max_cases=1,
        include_video_repair_probe=True,
        now=datetime(2026, 6, 22, 10, 0, tzinfo=timezone.utc),
    )

    assert calls[0]["include_video_repair_probe"] is True
    assert len(calls[0]["cases"]) == 1
    assert report["burn_budget"]["include_video_repair_probe"] is True


def test_visual_live_quality_burn_excludes_repair_probe_from_promotion_min_score(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["success"] = True
    suite["failures"] = []
    suite["case_count"] = 3
    suite["cases"][1]["success"] = True
    suite["cases"][1]["failures"] = []
    suite["cases"][1]["evidence"]["quality_gate"]["success"] = True
    suite["cases"][1]["evidence"]["quality_gate"]["min_score"] = 0.84
    suite["cases"][1]["evidence"]["quality_gate"]["quality_issues"] = []
    suite["cases"].append(
        {
            "case_id": "video_quality_repair",
            "success": True,
            "failures": [],
            "evidence": {
                "quality_gate": {
                    "success": True,
                    "min_score": 0.6643,
                    "quality_issues": [],
                },
                "image_count": 1,
                "video_count": 1,
                "ranking_count": 3,
            },
        }
    )

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path / "burn",
        work_dir=tmp_path / "work",
        now=datetime(2026, 6, 22, 10, 0, tzinfo=timezone.utc),
    )

    assert report["summary"]["min_quality_score"] == 0.6643
    assert report["summary"]["promotion_min_quality_score"] == 0.78


def test_visual_live_quality_burn_promotes_strategy_despite_diagnostic_repair_action(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["success"] = True
    suite["failures"] = []
    suite["case_count"] = 3
    for case in suite["cases"]:
        case["success"] = True
        case["failures"] = []
        case["evidence"]["quality_gate"]["success"] = True
        case["evidence"]["quality_gate"]["min_score"] = 0.84
        case["evidence"]["quality_gate"]["quality_issues"] = []
    suite["cases"].append(
        {
            "case_id": "video_quality_repair",
            "success": True,
            "failures": [],
            "evidence": {
                "quality_gate": {
                    "success": True,
                    "min_score": 0.6643,
                    "quality_issues": [],
                },
                "image_count": 1,
                "video_count": 1,
                "ranking_count": 3,
            },
        }
    )
    suite["quality_repair_summary"] = {
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

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    action_types = [action["type"] for action in report["next_actions"]]
    assert action_types == ["prefer_quality_repair_retry", "prefer_strategy"]
    strategy = report["next_actions"][1]
    assert strategy["activation_status"] == "shadow"
    assert strategy["confidence"] == 0.84
    assert strategy["evidence_count"] == 2


def test_visual_live_quality_burn_summarizes_core_quality_contract_coverage(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["quality_contract_summary"] = {
        "contract_case_count": 1,
        "contract_case_ids": ["fashion_portrait_video"],
        "required_dimensions": [
            "subject_beauty",
            "face_naturalness",
            "glamour_impact",
            "fashion_material_quality",
            "pose_composition",
        ],
        "core_quality_dimensions": [
            "subject_beauty",
            "face_naturalness",
            "glamour_impact",
            "fashion_material_quality",
            "pose_composition",
        ],
        "core_quality_dimensions_missing": [],
        "core_quality_coverage_ready": True,
        "image_first_video_contract_case_ids": ["fashion_portrait_video"],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert report["summary"]["core_quality_contract_case_count"] == 1
    assert report["summary"]["core_quality_dimensions"] == [
        "subject_beauty",
        "face_naturalness",
        "glamour_impact",
        "fashion_material_quality",
        "pose_composition",
    ]
    assert report["summary"]["core_quality_dimensions_missing"] == []
    assert report["summary"]["core_quality_coverage_ready"] is True
    assert report["summary"]["core_quality_contract_case_ids"] == ["fashion_portrait_video"]


def test_visual_live_quality_burn_summarizes_quality_focus_outcomes(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["quality_focus_summary"] = {
        "outcome_count": 2,
        "success_count": 1,
        "failure_count": 1,
        "successful_focuses": ["natural_face"],
        "failed_focuses": ["legwear_material"],
        "outcomes": [
            {
                "case_id": "fashion_portrait_video",
                "focus": "natural_face",
                "success": True,
                "dimension": "face_naturalness",
                "min_quality_score": 0.78,
                "quality_issues": [],
                "preference_dimension_failures": [],
            },
            {
                "case_id": "fashion_portrait_video",
                "focus": "legwear_material",
                "success": False,
                "dimension": "fashion_material_quality",
                "min_quality_score": 0.31,
                "quality_issues": ["stockings_bad"],
                "preference_dimension_failures": [
                    {
                        "dimension": "fashion_material_quality",
                        "issue": "stockings_bad",
                        "score": 0.31,
                    }
                ],
            },
        ],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert report["summary"]["quality_focus_outcome_count"] == 2
    assert report["summary"]["quality_focus_success_count"] == 1
    assert report["summary"]["quality_focus_failure_count"] == 1
    assert report["summary"]["quality_focus_successes"] == ["natural_face"]
    assert report["summary"]["quality_focus_failures"] == ["legwear_material"]
    assert report["summary"]["quality_focus_failed_case_ids"] == ["fashion_portrait_video"]


def test_visual_live_quality_burn_exports_quality_focus_operator_actions(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["quality_focus_summary"] = {
        "outcome_count": 3,
        "success_count": 0,
        "failure_count": 3,
        "successful_focuses": [],
        "failed_focuses": ["natural_face", "legwear_material", "image_first_video"],
        "outcomes": [
            {
                "case_id": "fashion_portrait_video",
                "focus": "natural_face",
                "success": False,
                "dimension": "face_naturalness",
                "min_quality_score": 0.28,
                "quality_issues": ["face_unnatural"],
                "preference_dimension_failures": [
                    {
                        "dimension": "face_naturalness",
                        "issue": "face_unnatural",
                        "score": 0.28,
                    }
                ],
            },
            {
                "case_id": "fashion_portrait_video",
                "focus": "legwear_material",
                "success": False,
                "dimension": "fashion_material_quality",
                "min_quality_score": 0.31,
                "quality_issues": ["stockings_bad"],
                "preference_dimension_failures": [
                    {
                        "dimension": "fashion_material_quality",
                        "issue": "stockings_bad",
                        "score": 0.31,
                    }
                ],
            },
            {
                "case_id": "fashion_portrait_video",
                "focus": "image_first_video",
                "success": False,
                "min_quality_score": 0.31,
                "quality_issues": [],
                "preference_dimension_failures": [],
            },
        ],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert {
        "type": "apply_quality_focus_operator",
        "track": "aesthetic",
        "reason": "live_quality_burn_quality_focus_failed",
        "confidence": 0.76,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
        "focus": "natural_face",
        "dimension": "face_naturalness",
        "strategy_operator": "refine_face_naturalness",
        "repair_hint": "improve_face_naturalness",
        "case_ids": ["fashion_portrait_video"],
        "quality_issues": ["face_unnatural"],
    } in report["next_actions"]
    assert {
        "type": "apply_quality_focus_operator",
        "track": "aesthetic",
        "reason": "live_quality_burn_quality_focus_failed",
        "confidence": 0.76,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
        "focus": "legwear_material",
        "dimension": "fashion_material_quality",
        "strategy_operator": "refine_legwear_material",
        "repair_hint": "improve_fashion_material_quality",
        "case_ids": ["fashion_portrait_video"],
        "quality_issues": ["stockings_bad"],
    } in report["next_actions"]
    assert {
        "type": "prefer_image_first_video",
        "track": "provider",
        "reason": "live_quality_burn_quality_focus_image_first_video_failed",
        "confidence": 0.82,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
        "focus": "image_first_video",
        "strategy_operator": "image_first_rank_then_video",
        "case_ids": ["fashion_portrait_video"],
    } in report["next_actions"]


def test_visual_live_quality_burn_exports_evaluation_action_for_missing_dimension_evidence(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["quality_focus_summary"] = {
        "outcome_count": 1,
        "success_count": 0,
        "failure_count": 1,
        "successful_focuses": [],
        "failed_focuses": ["adult_fashion_portrait"],
        "outcomes": [
            {
                "case_id": "fashion_portrait_video",
                "focus": "adult_fashion_portrait",
                "success": False,
                "dimension": "subject_beauty",
                "dimension_evidence_count": 0,
                "min_quality_score": 0.83,
                "quality_issues": ["missing_preference_dimension_evidence:subject_beauty"],
                "preference_dimension_failures": [],
            },
        ],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert {
        "type": "require_preference_dimension_evidence",
        "track": "evaluation",
        "reason": "live_quality_burn_missing_preference_dimension_evidence",
        "confidence": 0.84,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
        "focus": "adult_fashion_portrait",
        "dimension": "subject_beauty",
        "evaluation_operator": "inline_vision_preference_dimensions",
        "case_ids": ["fashion_portrait_video"],
        "quality_issues": ["missing_preference_dimension_evidence:subject_beauty"],
    } in report["next_actions"]
    assert not any(
        action.get("type") == "apply_quality_focus_operator"
        and action.get("focus") == "adult_fashion_portrait"
        for action in report["next_actions"]
    )


def test_visual_live_quality_burn_exports_preference_dimension_repair_actions(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["cases"][1]["evidence"]["quality_gate"]["preference_dimension_failures"] = [
        {
            "dimension": "face_naturalness",
            "score": 0.28,
            "issue": "face_unnatural",
            "artifact_id": "var_bad",
        },
        {
            "dimension": "fashion_material_quality",
            "score": 0.31,
            "issue": "stockings_bad",
            "artifact_id": "var_bad",
        },
    ]

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert report["summary"]["preference_dimension_failure_count"] == 2
    assert report["summary"]["preference_dimension_failures"] == [
        {"dimension": "face_naturalness", "issue": "face_unnatural", "score": 0.28},
        {"dimension": "fashion_material_quality", "issue": "stockings_bad", "score": 0.31},
    ]
    assert {
        "type": "repair_low_preference_dimension",
        "track": "aesthetic",
        "reason": "live_quality_burn_preference_dimension_low",
        "confidence": 0.72,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
        "dimension": "face_naturalness",
        "quality_issue": "face_unnatural",
        "repair_hint": "improve_face_naturalness",
    } in report["next_actions"]


def test_visual_live_quality_burn_exports_repair_action(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["success"] = True
    suite["failures"] = []
    suite["quality_repair_summary"] = {
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
    suite["cases"][1]["success"] = True
    suite["cases"][1]["failures"] = []
    suite["cases"][1]["evidence"]["quality_gate"] = {
        "success": True,
        "min_score": 0.82,
        "quality_issues": [],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="fixture",
        output_dir=tmp_path,
    )

    assert report["success"] is True
    assert report["summary"]["min_quality_score"] == 0.78
    assert report["next_actions"] == [
        {
            "type": "prefer_quality_repair_retry",
            "track": "repair",
            "reason": "live_quality_burn_video_repair_succeeded",
            "confidence": 0.9,
            "evidence_count": 1,
            "requires_human_feedback": False,
            "activation_status": "next_run",
            "source": "live_quality_burn",
            "modality": "video",
            "success_rate": 1.0,
            "selected_repair_rate": 1.0,
        }
    ]


def test_visual_live_quality_burn_summarizes_repair_effectiveness(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["success"] = True
    suite["failures"] = []
    suite["quality_repair_summary"] = {
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
    suite["cases"][1]["success"] = True
    suite["cases"][1]["failures"] = []
    suite["cases"][1]["evidence"]["quality_gate"] = {
        "success": True,
        "min_score": 0.81,
        "quality_issues": [],
    }
    suite["cases"][1]["evidence"]["quality_repair_effectiveness"] = {
        "attempt_count": 1,
        "improved_count": 1,
        "regressed_count": 0,
        "avg_score_delta": 0.39,
        "resolved_quality_issues": ["motion_bad"],
        "remaining_quality_issues": [],
        "by_modality": {
            "video": {
                "attempt_count": 1,
                "improved_count": 1,
                "regressed_count": 0,
                "avg_score_delta": 0.39,
                "resolved_quality_issues": ["motion_bad"],
                "remaining_quality_issues": [],
            }
        },
        "outcomes": [
            {
                "modality": "video",
                "baseline_artifact_id": "initial_video",
                "repair_artifact_id": "repair_video",
                "score_before": 0.42,
                "score_after": 0.81,
                "score_delta": 0.39,
                "quality_issues_before": ["motion_bad"],
                "quality_issues_after": [],
                "resolved_quality_issues": ["motion_bad"],
                "remaining_quality_issues": [],
                "improved": True,
                "regressed": False,
            }
        ],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert report["summary"]["quality_repair_effectiveness_attempt_count"] == 1
    assert report["summary"]["quality_repair_effectiveness_improved_count"] == 1
    assert report["summary"]["quality_repair_effectiveness_regressed_count"] == 0
    assert report["summary"]["quality_repair_effectiveness_avg_score_delta"] == 0.39
    assert report["summary"]["quality_repair_effectiveness_resolved_issues"] == ["motion_bad"]
    assert report["summary"]["quality_repair_effectiveness_remaining_issues"] == []
    assert {
        "type": "prefer_quality_repair_retry",
        "track": "repair",
        "reason": "live_quality_burn_video_repair_improved_quality",
        "confidence": 0.9,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
        "modality": "video",
        "success_rate": 1.0,
        "selected_repair_rate": 1.0,
        "improved_count": 1,
        "regressed_count": 0,
        "avg_score_delta": 0.39,
        "resolved_quality_issues": ["motion_bad"],
        "remaining_quality_issues": [],
    } in report["next_actions"]


def test_visual_live_quality_burn_exports_provider_failure_context(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["recovery_summary"] = {
        "provider_failure_count": 3,
        "provider_failure_classes": {"content_moderation": 2, "timeout": 1},
        "provider_error_codes": {"api_error": 2, "case_timeout": 1},
        "retry_attempt_count": 2,
        "negotiation_attempted_case_count": 2,
        "negotiation_success_case_count": 1,
        "content_moderation_recovered_case_count": 1,
        "recovered_failure_classes": ["content_moderation"],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert {
        "type": "safe_reframe_provider_retry",
        "track": "provider",
        "reason": "live_quality_burn_provider_failures",
        "confidence": 0.7,
        "evidence_count": 3,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
        "provider_failure_classes": {"content_moderation": 2, "timeout": 1},
        "provider_error_codes": {"api_error": 2, "case_timeout": 1},
    } in report["next_actions"]


def test_visual_live_quality_burn_routes_provider_unavailable_to_connectivity_action(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_live_quality_burn

    suite = _suite_with_provider_outage_and_no_quality_evidence()
    suite["recovery_summary"] = {
        "provider_failure_count": 15,
        "provider_failure_classes": {"provider_unavailable": 15},
        "provider_error_codes": {"connection_error": 12, "api_error": 3},
        "retry_attempt_count": 12,
        "negotiation_attempted_case_count": 2,
        "negotiation_success_case_count": 0,
        "content_moderation_recovered_case_count": 0,
        "recovered_failure_classes": [],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert {
        "type": "check_provider_connectivity_or_retry",
        "track": "provider",
        "reason": "live_quality_burn_provider_unavailable",
        "confidence": 0.88,
        "evidence_count": 15,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
        "provider_failure_classes": {"provider_unavailable": 15},
        "provider_error_codes": {"connection_error": 12, "api_error": 3},
    } in report["next_actions"]
    assert "safe_reframe_provider_retry" not in [
        action["type"] for action in report["next_actions"]
    ]


def test_visual_live_quality_burn_routes_quota_to_provider_account_action(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["case_count"] = 1
    suite["failures"] = ["quota_blocked:visual_generation_failed", "quota_blocked:quality_gate_failed"]
    suite["cases"] = [
        {
            "case_id": "quota_blocked",
            "success": False,
            "failures": ["visual_generation_failed", "quality_gate_failed"],
            "evidence": {
                "quality_gate": {
                    "success": False,
                    "min_score": None,
                    "quality_issues": [],
                },
                "image_count": 0,
                "video_count": 0,
                "ranking_count": 0,
            },
        }
    ]
    suite["recovery_summary"] = {
        "provider_failure_count": 1,
        "provider_failure_classes": {"quota_exceeded": 1},
        "provider_error_codes": {"personal-team-blocked:spending-limit": 1},
        "retry_attempt_count": 0,
        "negotiation_attempted_case_count": 0,
        "negotiation_success_case_count": 0,
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    action_types = [action["type"] for action in report["next_actions"]]
    assert action_types == ["resolve_provider_quota_or_switch_provider"]
    assert {
        "type": "resolve_provider_quota_or_switch_provider",
        "track": "provider",
        "reason": "live_quality_burn_provider_quota_exceeded",
        "confidence": 0.95,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
        "provider_failure_classes": {"quota_exceeded": 1},
        "provider_error_codes": {"personal-team-blocked:spending-limit": 1},
    } in report["next_actions"]


def test_visual_live_quality_burn_routes_missing_video_fallback_to_provider_action(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["case_count"] = 1
    suite["failures"] = ["video_quota_blocked:visual_generation_failed"]
    suite["cases"] = [
        {
            "case_id": "video_quota_blocked",
            "success": False,
            "failures": ["visual_generation_failed"],
            "evidence": {
                "quality_gate": {
                    "success": False,
                    "min_score": None,
                    "quality_issues": [],
                },
                "image_count": 1,
                "video_count": 0,
                "ranking_count": 1,
                "require_video": True,
            },
        }
    ]
    suite["recovery_summary"] = {
        "provider_failure_count": 2,
        "provider_failure_classes": {"quota_exceeded": 2},
        "provider_error_codes": {"personal-team-blocked:spending-limit": 2},
        "no_video_fallback_available_count": 1,
        "provider_quarantine_count": 1,
        "provider_quarantine_classes": ["quota_exceeded"],
        "video_fallback_diagnostics": [
            {
                "failed_provider": "xai",
                "failed_provider_family": "xai",
                "registered_provider_names": ["fal", "xai"],
                "available_provider_names": [],
                "unavailable_provider_names": ["fal"],
                "fallback_provider_names": [],
                "setup_actions": [
                        {
                            "provider": "fal",
                            "env_vars": ["FAL_KEY"],
                            "configured_env_vars": [],
                            "missing_env_vars": ["FAL_KEY"],
                            "post_setup": "",
                        }
                ],
            }
        ],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    action = next(
        action
        for action in report["next_actions"]
        if action["type"] == "configure_video_fallback_provider"
    )
    assert action["track"] == "provider"
    assert action["reason"] == "live_quality_burn_no_video_fallback_available"
    assert action["confidence"] == 0.9
    assert action["evidence_count"] == 1
    assert action["requires_human_feedback"] is False
    assert action["activation_status"] == "next_run"
    assert action["source"] == "live_quality_burn"
    assert action["provider_failure_classes"] == {"quota_exceeded": 2}
    assert action["provider_error_codes"] == {
        "personal-team-blocked:spending-limit": 2
    }
    assert action["video_fallback_diagnostics"] == [
        {
            "failed_provider": "xai",
            "failed_provider_family": "xai",
            "registered_provider_names": ["fal", "xai"],
            "available_provider_names": [],
            "unavailable_provider_names": ["fal"],
            "fallback_provider_names": [],
            "setup_actions": [
                {
                    "provider": "fal",
                    "env_vars": ["FAL_KEY"],
                    "configured_env_vars": [],
                    "missing_env_vars": ["FAL_KEY"],
                    "post_setup": "",
                }
            ],
        }
    ]
    assert action["requires_operator_setup"] is True
    assert action["operator_setup_actions"] == [
        {
            "provider": "fal",
            "missing_env_vars": ["FAL_KEY"],
            "post_setup": "",
        }
    ]
    assert report["self_review"]["requires_operator_setup"] is True
    assert report["self_review"]["operator_setup_actions"] == action["operator_setup_actions"]
    assert report["self_review"]["human_feedback_required"] is False
    assert report["self_review"]["reduces_human_intervention"] is False


def test_visual_live_quality_burn_prefers_image_first_when_video_missing_after_image(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["failures"] = ["fashion_portrait_video:missing_video_output"]
    suite["cases"][1]["failures"] = ["missing_video_output"]
    suite["cases"][1]["evidence"]["image_count"] = 1
    suite["cases"][1]["evidence"]["video_count"] = 0
    suite["cases"][1]["evidence"]["require_video"] = True
    suite["cases"][1]["evidence"]["quality_gate"] = {
        "success": True,
        "min_score": 0.79,
        "quality_issues": [],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert report["summary"]["video_missing_after_image_count"] == 1
    assert report["summary"]["video_missing_after_image_case_ids"] == ["fashion_portrait_video"]
    assert {
        "type": "prefer_image_first_video",
        "track": "provider",
        "reason": "live_quality_burn_video_missing_after_image",
        "confidence": 0.78,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
    } in report["next_actions"]


def test_visual_live_quality_burn_does_not_prefer_image_first_when_provider_fallback_explains_missing_video(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["failures"] = ["product_photo_video:missing_video_output"]
    suite["cases"][0]["success"] = False
    suite["cases"][0]["failures"] = ["missing_video_output"]
    suite["cases"][0]["evidence"]["image_count"] = 1
    suite["cases"][0]["evidence"]["video_count"] = 0
    suite["cases"][0]["evidence"]["require_video"] = True
    suite["cases"][0]["evidence"]["video_source"] = {
        "image_first_for_video": True,
        "ranked_selected_image_artifact_id": "var_selected",
        "require_video": True,
        "single_video_source_image": True,
        "source_image_artifact_id": "var_selected",
        "uses_ranked_selected_image": True,
        "video_source_image_count": 1,
        "video_source_policy": "single_ranked_selected_image",
    }
    suite["cases"][0]["evidence"]["quality_gate"] = {
        "success": True,
        "min_score": 0.79,
        "quality_issues": [],
    }
    suite["recovery_summary"] = {
        "provider_failure_count": 3,
        "provider_failure_classes": {"quota_exceeded": 3},
        "provider_error_codes": {"personal-team-blocked:spending-limit": 2, "provider_quarantined": 1},
        "no_video_fallback_available_count": 1,
        "provider_quarantine_count": 1,
        "provider_quarantine_classes": ["quota_exceeded"],
        "video_fallback_diagnostics": [
            {
                "failed_provider": "xai",
                "failed_provider_family": "xai",
                "registered_provider_names": ["fal", "xai"],
                "available_provider_names": [],
                "unavailable_provider_names": ["fal"],
                "fallback_provider_names": [],
                "setup_actions": [
                    {
                        "provider": "fal",
                        "env_vars": ["FAL_KEY"],
                        "configured_env_vars": [],
                        "missing_env_vars": ["FAL_KEY"],
                        "post_setup": "",
                    }
                ],
            }
        ],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert report["summary"]["video_missing_after_image_count"] == 1
    assert report["summary"]["image_first_video_source_failure_count"] == 0
    assert "prefer_image_first_video" not in [
        action["type"] for action in report["next_actions"]
    ]
    action_types = [action["type"] for action in report["next_actions"]]
    assert "resolve_provider_quota_or_switch_provider" in action_types
    assert "configure_video_fallback_provider" in action_types
    assert report["self_review"]["requires_operator_setup"] is True


def test_visual_live_quality_burn_flags_video_source_not_ranked_image(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["success"] = False
    suite["failures"] = ["fashion_portrait_video:video_not_using_ranked_image_source"]
    suite["cases"][0]["evidence"]["video_source"] = {
        "source_image_artifact_id": "var_product_selected",
        "ranked_selected_image_artifact_id": "var_product_selected",
        "uses_ranked_selected_image": True,
    }
    suite["cases"][1]["success"] = False
    suite["cases"][1]["failures"] = ["video_not_using_ranked_image_source"]
    suite["cases"][1]["evidence"]["video_source"] = {
        "source_image_artifact_id": None,
        "ranked_selected_image_artifact_id": "var_fashion_selected",
        "uses_ranked_selected_image": False,
    }
    suite["cases"][1]["evidence"]["quality_gate"] = {
        "success": True,
        "min_score": 0.82,
        "quality_issues": [],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert report["summary"]["image_first_video_source_case_count"] == 2
    assert report["summary"]["image_first_video_source_covered_count"] == 1
    assert report["summary"]["image_first_video_source_failure_count"] == 1
    assert report["summary"]["image_first_video_source_failure_case_ids"] == ["fashion_portrait_video"]
    assert {
        "type": "prefer_image_first_video",
        "track": "provider",
        "reason": "live_quality_burn_video_source_not_ranked_image",
        "confidence": 0.82,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
    } in report["next_actions"]


def test_visual_live_quality_burn_flags_video_source_not_single_image(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["success"] = False
    suite["failures"] = ["fashion_portrait_video:video_source_not_single_image"]
    suite["cases"][0]["evidence"]["video_source"] = {
        "source_image_artifact_id": "var_product_selected",
        "ranked_selected_image_artifact_id": "var_product_selected",
        "uses_ranked_selected_image": True,
        "video_source_image_count": 1,
        "single_video_source_image": True,
    }
    suite["cases"][1]["success"] = False
    suite["cases"][1]["failures"] = ["video_source_not_single_image"]
    suite["cases"][1]["evidence"]["video_source"] = {
        "source_image_artifact_id": "var_fashion_selected",
        "ranked_selected_image_artifact_id": "var_fashion_selected",
        "uses_ranked_selected_image": True,
        "video_source_image_count": 4,
        "single_video_source_image": False,
    }
    suite["cases"][1]["evidence"]["quality_gate"] = {
        "success": True,
        "min_score": 0.82,
        "quality_issues": [],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert report["summary"]["image_first_video_source_case_count"] == 2
    assert report["summary"]["image_first_video_source_covered_count"] == 1
    assert report["summary"]["image_first_video_source_failure_count"] == 1
    assert report["summary"]["image_first_video_source_not_single_count"] == 1
    assert report["summary"]["image_first_video_source_not_single_case_ids"] == [
        "fashion_portrait_video"
    ]
    assert {
        "type": "prefer_image_first_video",
        "track": "provider",
        "reason": "live_quality_burn_video_source_not_single_image",
        "confidence": 0.84,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
    } in report["next_actions"]
    assert {
        "type": "enforce_single_video_source_image",
        "track": "provider",
        "reason": "live_quality_burn_video_source_not_single_image",
        "confidence": 0.86,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
        "modality": "video",
        "quality_issue": "source_frame_grid",
        "repair_hint": "use_single_ranked_selected_image",
    } in report["next_actions"]


def test_visual_live_quality_burn_repairs_video_aspect_mismatch(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["success"] = False
    suite["failures"] = ["product_photo_video:video_aspect_ratio_mismatch"]
    suite["cases"][0]["success"] = False
    suite["cases"][0]["failures"] = ["video_aspect_ratio_mismatch"]
    suite["cases"][0]["evidence"]["video_media_quality"] = {
        "success": False,
        "checked_video_count": 1,
        "bad_video_artifact_ids": ["var_stretched_video"],
        "videos": [
            {
                "artifact_id": "var_stretched_video",
                "requested_aspect_ratio": "16:9",
                "actual_aspect_ratio": "1:1",
                "aspect_ratio_matches": False,
            }
        ],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert {
        "type": "enforce_video_source_aspect_ratio",
        "track": "provider",
        "reason": "live_quality_burn_video_aspect_ratio_mismatch",
        "confidence": 0.86,
        "evidence_count": 1,
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_burn",
        "modality": "video",
        "quality_issue": "aspect_integrity_bad",
        "repair_hint": "preserve_source_aspect_ratio",
    } in report["next_actions"]


def test_visual_live_quality_burn_does_not_treat_generic_video_media_failure_as_aspect_mismatch(
    monkeypatch,
    tmp_path,
):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["success"] = False
    suite["failures"] = ["product_photo_video:video_upload_failed"]
    suite["cases"][0]["success"] = False
    suite["cases"][0]["failures"] = ["video_upload_failed"]
    suite["cases"][0]["evidence"]["video_media_quality"] = {
        "success": False,
        "checked_video_count": 1,
        "bad_video_artifact_ids": ["var_missing_video"],
        "videos": [
            {
                "artifact_id": "var_missing_video",
                "requested_aspect_ratio": "16:9",
                "actual_aspect_ratio": "",
                "aspect_ratio_matches": None,
            }
        ],
    }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert all(
        action["type"] != "enforce_video_source_aspect_ratio"
        for action in report["next_actions"]
    )


def test_visual_live_quality_burn_promotes_high_quality_pass_without_repair(monkeypatch, tmp_path):
    from scripts import visual_live_quality_burn

    suite = _suite_with_quality_failure()
    suite["success"] = True
    suite["failures"] = []
    suite["quality_repair_summary"] = {
        "attempt_count": 0,
        "success_count": 0,
        "selected_repair_count": 0,
        "by_modality": {},
    }
    for case in suite["cases"]:
        case["success"] = True
        case["failures"] = []
        case["evidence"]["quality_gate"] = {
            "success": True,
            "min_score": 0.84,
            "quality_issues": [],
        }

    monkeypatch.setattr(
        visual_live_quality_burn,
        "build_visual_live_provider_e2e_suite_report",
        lambda **_kwargs: suite,
    )

    report = visual_live_quality_burn.build_visual_live_quality_burn_report(
        mode="live",
        output_dir=tmp_path,
    )

    assert report["success"] is True
    assert report["self_review"]["reduces_human_intervention"] is True
    assert report["self_review"]["human_feedback_required"] is False
    assert report["next_actions"] == [
        {
            "type": "prefer_strategy",
            "track": "aesthetic",
            "reason": "live_quality_burn_high_quality_pass",
            "confidence": 0.84,
            "evidence_count": 2,
            "requires_human_feedback": False,
            "activation_status": "shadow",
            "source": "live_quality_burn",
            "bucket": "live_visual_agent_mode",
            "strategy_signature": "image_first_rank_then_video",
            "candidate_budget": 2,
        }
    ]
