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
            "live_quality_burn_image_first_video_source_covered": True,
            "live_quality_burn_image_first_video_source_failure_count": 0,
            "live_quality_burn_image_first_video_source_not_single_count": 0,
            "live_quality_burn_action_types": [
                "repair_low_preference_dimension",
                "safe_reframe_provider_retry",
                "prefer_image_first_video",
            ],
            "live_quality_burn_preference_dimensions": [
                "face_naturalness",
                "fashion_material_quality",
            ],
            "live_quality_trend_run_count": 4,
            "live_quality_trend_recent_run_ids": [
                "20260622T183138Z",
                "20260622T191850Z-6407540a",
            ],
            "live_quality_trend_recent_avg_min_quality_score": 0.8206,
            "live_quality_trend_recent_provider_failure_count": 0,
            "live_quality_trend_recent_video_generation_failure_count": 0,
            "live_quality_trend_recent_preference_dimension_failure_count": 0,
            "live_conversation_quality_run_count": 2,
            "live_conversation_quality_recent_run_ids": [
                "20260622T183138Z",
                "20260622T191850Z-6407540a",
            ],
            "live_conversation_quality_recent_avg_min_quality_score": 0.8206,
            "live_conversation_quality_native_video_upload_covered_count": 2,
            "live_conversation_quality_image_first_video_source_failure_count": 0,
            "live_conversation_quality_provider_failure_count": 0,
            "live_conversation_quality_latest_generated_at": "2026-06-22T19:18:50+00:00",
            "live_video_quality_repair_success_count": 1,
            "live_slack_upload_native_delivery_covered": True,
            "live_slack_upload_uploaded_video_file_count": 1,
            "slack_duplicate_delivery_count": 0,
            "slack_conversation_self_review_decision": "accept",
            "slack_conversation_self_review_success": True,
            "slack_conversation_requires_human_feedback": False,
            "slack_conversation_reduces_human_intervention": True,
            "slack_conversation_auto_next_action_count": 0,
            "slack_conversation_quality_gate_success": True,
            "slack_conversation_provider_failure_count": 0,
            "slack_conversation_image_first_video_source_covered": True,
            "slack_conversation_native_video_upload_covered": True,
            "slack_conversation_blocking_reasons": [],
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
    assert status["live"]["image_first_video_source_covered"] is True
    assert status["live"]["image_first_video_source_failure_count"] == 0
    assert status["live"]["image_first_video_source_not_single_count"] == 0
    assert status["live"]["content_moderation_recovered_count"] == 1
    assert status["live"]["provider_failure_classes"] == {"content_moderation": 1}
    assert status["live"]["provider_error_codes"] == {"api_error": 1}
    assert status["live"]["trend_run_count"] == 4
    assert status["live"]["trend_recent_run_ids"] == [
        "20260622T183138Z",
        "20260622T191850Z-6407540a",
    ]
    assert status["live"]["trend_recent_avg_min_quality_score"] == 0.8206
    assert status["live"]["trend_recent_provider_failure_count"] == 0
    assert status["live"]["trend_recent_video_generation_failure_count"] == 0
    assert status["live"]["trend_recent_preference_dimension_failure_count"] == 0
    assert status["live"]["conversation_quality_run_count"] == 2
    assert status["live"]["conversation_quality_recent_run_ids"] == [
        "20260622T183138Z",
        "20260622T191850Z-6407540a",
    ]
    assert status["live"]["conversation_quality_recent_avg_min_quality_score"] == 0.8206
    assert status["live"]["conversation_quality_native_video_upload_covered_count"] == 2
    assert status["live"]["conversation_quality_image_first_video_source_failure_count"] == 0
    assert status["live"]["conversation_quality_provider_failure_count"] == 0
    assert status["live"]["conversation_quality_latest_generated_at"] == "2026-06-22T19:18:50+00:00"
    assert status["live"]["preference_dimensions"] == [
        "face_naturalness",
        "fashion_material_quality",
    ]
    assert status["delivery"]["native_video_upload_covered"] is True
    assert status["conversation"]["self_review_decision"] == "accept"
    assert status["conversation"]["self_review_success"] is True
    assert status["conversation"]["requires_human_feedback"] is False
    assert status["conversation"]["image_first_video_source_covered"] is True
    assert status["conversation"]["native_video_upload_covered"] is True
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


def test_visual_self_validation_status_reports_auto_live_trend_override(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    payload = _scheduled_report()
    payload["live_policy"] = {
        "mode": "auto",
        "decision": "run",
        "live_enabled": True,
        "reason": "live_quality_trend_degraded",
        "degradations": ["quality_score_degraded"],
        "min_live_interval_hours": 6,
        "elapsed_hours": 1.5,
    }
    latest_path = _write_latest(tmp_path, payload)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["live_policy"]["reason"] == "live_quality_trend_degraded"
    assert status["live_policy"]["degradations"] == ["quality_score_degraded"]


def test_visual_self_validation_status_sanitizes_auto_live_policy_degradations(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    payload = _scheduled_report()
    payload["live_policy"] = {
        "mode": "auto",
        "decision": "run",
        "live_enabled": True,
        "reason": "private prompt should not leak",
        "degradations": ["quality_score_degraded", "private visual prompt"],
    }
    latest_path = _write_latest(tmp_path, payload)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["live_policy"].get("reason") is None
    assert status["live_policy"]["degradations"] == ["quality_score_degraded"]
    encoded = json.dumps(status, ensure_ascii=False)
    assert "private visual prompt" not in encoded


def test_visual_self_validation_status_reports_runtime_policy_without_leaking_details(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    payload = _scheduled_report(success=False)
    payload["runtime_policy"] = {
        "success": True,
        "decision": "apply_next_run",
        "generated_at": "2026-06-22T10:19:00+00:00",
        "expires_at": "2026-06-23T10:19:00+00:00",
        "next_actions": [
            {
                "type": "prefer_image_first_video",
                "requires_human_feedback": False,
                "private_prompt": "do not leak this prompt",
            },
            {
                "type": "increase_candidate_budget",
                "requires_human_feedback": False,
                "max_candidate_budget": 4,
            },
        ],
    }
    latest_path = _write_latest(tmp_path, payload)

    status = build_visual_self_validation_status(
        latest_path=latest_path,
        now=datetime(2026, 6, 22, 11, 0, tzinfo=timezone.utc),
    )

    assert status["runtime_policy"] == {
        "success": True,
        "decision": "apply_next_run",
        "generated_at": "2026-06-22T10:19:00+00:00",
        "expires_at": "2026-06-23T10:19:00+00:00",
        "expired": False,
        "action_types": ["prefer_image_first_video", "increase_candidate_budget"],
        "fixture_effect": {
            "active": None,
            "applied": None,
            "expected_action_types": [],
            "missing_action_types": [],
            "quality_gate_min_score": None,
            "quality_delta_vs_recent_trend": None,
            "quality_regressed": None,
        },
        "live_effect": {
            "active": None,
            "applied": None,
            "expected_action_types": [],
            "missing_action_types": [],
            "quality_gate_min_score": None,
            "quality_delta_vs_recent_trend": None,
            "quality_regressed": None,
        },
    }
    assert "prefer_image_first_video" in status["self_improvement"]["action_types"]
    encoded = json.dumps(status, ensure_ascii=False)
    assert "do not leak" not in encoded
    assert "private_prompt" not in encoded


def test_visual_self_validation_status_reports_runtime_policy_effect(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    payload = _scheduled_report()
    payload["summary"]["live_runtime_policy_active"] = True
    payload["summary"]["live_runtime_policy_applied"] = False
    payload["summary"]["live_runtime_policy_expected_action_types"] = [
        "increase_candidate_budget",
        "prefer_image_first_video",
    ]
    payload["summary"]["live_runtime_policy_missing_action_types"] = [
        "increase_candidate_budget"
    ]
    payload["summary"]["live_runtime_policy_quality_gate_min_score"] = 0.72
    payload["summary"]["live_runtime_policy_quality_delta_vs_recent_trend"] = -0.1
    payload["summary"]["live_runtime_policy_quality_regressed"] = True
    latest_path = _write_latest(tmp_path, payload)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["runtime_policy"]["live_effect"] == {
        "active": True,
        "applied": False,
        "expected_action_types": [
            "increase_candidate_budget",
            "prefer_image_first_video",
        ],
        "missing_action_types": ["increase_candidate_budget"],
        "quality_gate_min_score": 0.72,
        "quality_delta_vs_recent_trend": -0.1,
        "quality_regressed": True,
    }
    assert "verify_runtime_policy_application" in status["next_steps"]
    assert "inspect_runtime_policy_quality_regression" in status["next_steps"]


def test_visual_self_validation_status_reports_suspended_runtime_policy(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    payload = _scheduled_report()
    payload["runtime_policy"] = {
        "success": False,
        "decision": "suspend_quality_regressed",
        "reason": "runtime_policy_quality_regressed",
        "generated_at": "2026-06-22T10:19:00+00:00",
        "expires_at": "2026-06-23T10:19:00+00:00",
        "next_actions": [],
        "suspended_action_types": [
            "increase_candidate_budget",
            "prefer_image_first_video",
            "/Users/simon/.hermes/cache/private-prompt.txt",
        ],
        "privacy_safe": True,
    }
    latest_path = _write_latest(tmp_path, payload)

    status = build_visual_self_validation_status(
        latest_path=latest_path,
        now=datetime(2026, 6, 22, 11, 0, tzinfo=timezone.utc),
    )

    assert status["runtime_policy"]["decision"] == "suspend_quality_regressed"
    assert status["runtime_policy"]["suspended_action_types"] == [
        "increase_candidate_budget",
        "prefer_image_first_video",
    ]
    assert "review_suspended_runtime_policy" in status["next_steps"]
    encoded = json.dumps(status, ensure_ascii=False)
    assert "/Users/simon" not in encoded
    assert "private-prompt" not in encoded


def test_visual_self_validation_status_flags_internal_source_image_delivery(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    payload = _scheduled_report()
    payload["summary"]["slack_internal_source_image_delivery_count"] = 1
    payload["summary"]["slack_internal_source_image_artifact_ids"] = ["var_source"]
    latest_path = _write_latest(tmp_path, payload)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["success"] is False
    assert status["health_status"] == "warn"
    assert status["delivery"]["internal_source_image_delivery_count"] == 1
    assert "fix_internal_source_image_delivery" in status["next_steps"]


def test_visual_self_validation_status_surfaces_closed_loop_regression_failure(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    payload = _scheduled_report(success=False)
    payload["failures"] = ["closed_loop_regression_failed"]
    payload["summary"]["closed_loop_regression_success"] = False
    payload["summary"]["closed_loop_regression_failure_count"] = 1
    latest_path = _write_latest(tmp_path, payload)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["success"] is False
    assert status["health_status"] == "fail"
    assert "inspect_closed_loop_policy_application" in status["next_steps"]


def test_visual_self_validation_status_marks_missing_report(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    status = build_visual_self_validation_status(latest_path=tmp_path / "missing.json")

    assert status["success"] is False
    assert status["health_status"] == "missing"
    assert status["live_e2e_ran"] is False
    assert status["next_steps"] == ["run_visual_scheduled_self_validation"]
    assert status["promotion_readiness"]["ready"] is False
    assert "self_validation_report_missing" in status["promotion_readiness"]["blocking_reasons"]


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


def test_visual_self_validation_status_accepts_recent_carried_live_burn_on_interval_skip(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report(live_decision="skip_interval")
    report["mode"] = "fixture"
    report["live_policy"] = {
        "mode": "auto",
        "decision": "skip_interval",
        "live_enabled": True,
        "min_live_interval_hours": 6,
        "last_live_run_at": "2026-06-22T11:35:17+00:00",
        "elapsed_hours": 5.2,
    }
    report["slack_live_upload_policy"] = {
        "decision": "not_requested",
        "enabled": True,
        "target": "D_SECRET",
    }
    report["summary"]["live_quality_gate_success"] = None
    report["summary"]["live_quality_gate_min_score"] = None
    report["summary"]["live_quality_suite_success"] = None
    report["summary"]["live_quality_suite_case_count"] = 0
    report["summary"]["live_quality_suite_failure_count"] = 0
    report["summary"]["live_slack_upload_native_delivery_covered"] = None
    report["summary"]["live_slack_upload_uploaded_video_file_count"] = None
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(
        latest_path=latest_path,
        now=datetime(2026, 6, 22, 16, 47, tzinfo=timezone.utc),
    )

    assert status["success"] is True
    assert status["health_status"] == "pass"
    assert status["live_e2e_ran"] is False
    assert status["live"]["burn_success"] is True
    assert status["live"]["image_first_video_source_covered"] is True
    assert status["next_steps"] == ["continue_visual_agent_mode_rollout"]
    assert status["self_review"]["reduces_human_intervention"] is True
    assert "D_SECRET" not in json.dumps(status, ensure_ascii=False)


def test_visual_self_validation_status_warns_on_slack_conversation_self_review_repair(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report()
    report["summary"]["slack_conversation_self_review_decision"] = "needs_repair"
    report["summary"]["slack_conversation_self_review_success"] = False
    report["summary"]["slack_conversation_requires_human_feedback"] = False
    report["summary"]["slack_conversation_auto_next_action_count"] = 2
    report["summary"]["slack_conversation_quality_gate_success"] = False
    report["summary"]["slack_conversation_blocking_reasons"] = ["video_metadata_missing"]
    report["automation"]["self_improvement"]["next_actions"].append(
        {
            "type": "rerank_before_slack",
            "requires_human_feedback": False,
            "source": "slack_conversation_e2e",
        }
    )
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["success"] is False
    assert status["health_status"] == "warn"
    assert status["conversation"]["self_review_decision"] == "needs_repair"
    assert status["conversation"]["self_review_success"] is False
    assert status["conversation"]["requires_human_feedback"] is False
    assert status["conversation"]["blocking_reasons"] == ["video_metadata_missing"]
    assert "apply_slack_conversation_self_review_actions" in status["next_steps"]
    assert "rerank_before_slack" in status["self_improvement"]["action_types"]


def test_visual_self_validation_status_warns_on_slack_conversation_operator_setup(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report()
    operator_setup_actions = [
        {
            "provider": "fal",
            "missing_env_vars": ["FAL_KEY"],
            "post_setup": "",
        }
    ]
    report["summary"]["slack_conversation_self_review_decision"] = "needs_setup"
    report["summary"]["slack_conversation_self_review_success"] = False
    report["summary"]["slack_conversation_requires_human_feedback"] = False
    report["summary"]["slack_conversation_requires_operator_setup"] = True
    report["summary"]["slack_conversation_operator_setup_actions"] = operator_setup_actions
    report["summary"]["slack_conversation_operator_setup_action_count"] = 1
    report["summary"]["slack_conversation_blocking_reasons"] = ["operator_setup_required"]
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["success"] is False
    assert status["health_status"] == "warn"
    assert status["conversation"]["self_review_decision"] == "needs_setup"
    assert status["conversation"]["requires_human_feedback"] is False
    assert status["conversation"]["requires_operator_setup"] is True
    assert status["conversation"]["operator_setup_actions"] == operator_setup_actions
    assert "configure_operator_setup_prerequisites" in status["next_steps"]
    assert "apply_slack_conversation_self_review_actions" not in status["next_steps"]


def test_visual_self_validation_status_warns_on_visual_runtime_dependency_setup(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report(success=False)
    action = {
        "type": "configure_visual_runtime_dependencies",
        "track": "operator_setup",
        "reason": "visual_runtime_missing_python_modules",
        "requires_human_feedback": False,
        "requires_operator_setup": True,
        "activation_status": "operator_setup",
        "source": "visual_runtime_environment",
        "missing_modules": ["openai", "slack_sdk"],
        "operator_setup_actions": [
            {
                "provider": "python_runtime",
                "missing_env_vars": [],
                "post_setup": "rtk uv run --extra dev --extra slack python3 <script>",
            }
        ],
    }
    report["failures"] = ["runtime_environment_missing_dependencies"]
    report["summary"]["feedback_action_types"] = ["configure_visual_runtime_dependencies"]
    report["runtime_policy"] = {
        "success": True,
        "decision": "apply_next_run",
        "generated_at": "2026-06-22T10:19:00+00:00",
        "expires_at": "2026-06-23T10:19:00+00:00",
        "next_actions": [action],
    }
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["success"] is False
    assert status["health_status"] == "warn"
    assert "configure_visual_runtime_dependencies" in status["self_improvement"]["action_types"]
    assert "configure_visual_runtime_dependencies" in status["runtime_policy"]["action_types"]
    assert "configure_visual_runtime_dependencies" in status["next_steps"]
    encoded = json.dumps(status, ensure_ascii=False)
    assert "private_prompt" not in encoded


def test_visual_self_validation_status_warns_on_live_quality_trend_degradation(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report()
    report["summary"]["live_quality_trend_degradations"] = [
        "video_generation_degraded",
        "provider_failures_spiked",
    ]
    report["summary"]["live_quality_trend_action_types"] = [
        "prefer_image_first_video",
        "safe_reframe_provider_retry",
    ]
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["success"] is False
    assert status["health_status"] == "warn"
    assert status["live"]["trend_degradations"] == [
        "video_generation_degraded",
        "provider_failures_spiked",
    ]
    assert "stabilize_live_quality_trends" in status["next_steps"]
    assert "prefer_image_first_video" in status["self_improvement"]["action_types"]
    assert "safe_reframe_provider_retry" in status["self_improvement"]["action_types"]


def test_visual_self_validation_status_reports_strategy_promotion_readiness(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report()
    report["summary"]["live_quality_burn_min_score"] = 0.8206
    report["automation"]["self_improvement"]["next_actions"].append(
        {
            "type": "prefer_strategy",
            "source": "live_quality_burn",
            "track": "aesthetic",
            "strategy_signature": "image_first_rank_then_video",
            "bucket": "image-video:product-editorial",
            "activation_status": "shadow",
            "confidence": 0.8206,
            "evidence_count": 4,
            "private_prompt": "do not leak strategy prompt",
        }
    )
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    readiness = status["promotion_readiness"]
    assert readiness["ready"] is True
    assert readiness["blocking_reasons"] == []
    assert readiness["candidate"] == {
        "type": "prefer_strategy",
        "source": "live_quality_burn",
        "track": "aesthetic",
        "strategy_signature": "image_first_rank_then_video",
        "bucket": "image-video:product-editorial",
        "activation_status": "shadow",
        "confidence": 0.8206,
        "evidence_count": 4,
    }
    assert readiness["self_review"]["privacy_safe"] is True
    encoded = json.dumps(status, ensure_ascii=False)
    assert "do not leak" not in encoded


def test_visual_self_validation_status_blocks_strategy_promotion_on_non_single_video_source(
    tmp_path,
):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report()
    report["summary"]["live_quality_burn_min_score"] = 0.86
    report["summary"]["live_quality_burn_image_first_video_source_not_single_count"] = 1
    report["automation"]["self_improvement"]["next_actions"].append(
        {
            "type": "prefer_strategy",
            "source": "live_quality_burn",
            "track": "aesthetic",
            "strategy_signature": "image_first_rank_then_video",
            "bucket": "image-video:product-editorial",
            "activation_status": "shadow",
            "confidence": 0.88,
            "evidence_count": 4,
        }
    )
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["live"]["image_first_video_source_not_single_count"] == 1
    assert status["promotion_readiness"]["ready"] is False
    assert "video_source_not_single_image" in status["promotion_readiness"]["blocking_reasons"]


def test_visual_self_validation_status_uses_promotion_min_score_for_strategy_readiness(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report()
    report["summary"]["live_quality_burn_min_score"] = 0.6643
    report["summary"]["live_quality_burn_promotion_min_score"] = 0.8206
    report["summary"]["live_conversation_quality_run_count"] = 0
    report["summary"]["live_conversation_quality_recent_avg_min_quality_score"] = None
    report["summary"]["live_conversation_quality_native_video_upload_covered_count"] = 0
    report["summary"]["live_conversation_quality_image_first_video_source_failure_count"] = 0
    report["summary"]["live_conversation_quality_provider_failure_count"] = 0
    report["automation"]["self_improvement"]["next_actions"].append(
        {
            "type": "prefer_strategy",
            "source": "live_quality_burn",
            "track": "aesthetic",
            "strategy_signature": "image_first_rank_then_video",
            "bucket": "image-video:product-editorial",
            "activation_status": "shadow",
            "confidence": 0.8206,
            "evidence_count": 4,
        }
    )
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["promotion_readiness"]["ready"] is True
    assert "live_quality_score_below_threshold" not in status["promotion_readiness"]["blocking_reasons"]


def test_visual_self_validation_status_blocks_strategy_promotion_on_trend_degradation(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report()
    report["summary"]["live_quality_burn_min_score"] = 0.86
    report["summary"]["live_quality_trend_degradations"] = ["provider_failures_spiked"]
    report["automation"]["self_improvement"]["next_actions"].append(
        {
            "type": "prefer_strategy",
            "source": "live_quality_burn",
            "track": "aesthetic",
            "strategy_signature": "image_first_rank_then_video",
            "bucket": "image-video:product-editorial",
            "activation_status": "shadow",
            "confidence": 0.88,
            "evidence_count": 4,
        }
    )
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["promotion_readiness"]["ready"] is False
    assert "live_quality_trend_degraded" in status["promotion_readiness"]["blocking_reasons"]


def test_visual_self_validation_status_reports_low_strategy_confidence_blocker(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report()
    report["summary"]["live_quality_burn_min_score"] = 0.86
    report["automation"]["self_improvement"]["next_actions"].append(
        {
            "type": "prefer_strategy",
            "source": "live_quality_burn",
            "track": "aesthetic",
            "strategy_signature": "image_first_rank_then_video",
            "bucket": "image-video:product-editorial",
            "activation_status": "shadow",
            "confidence": 0.72,
            "evidence_count": 4,
        }
    )
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["promotion_readiness"]["ready"] is False
    assert "strategy_confidence_below_threshold" in status["promotion_readiness"]["blocking_reasons"]
    assert "no_shadow_strategy_candidate" not in status["promotion_readiness"]["blocking_reasons"]


def test_visual_self_validation_status_requires_current_live_run_for_promotion(tmp_path):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report(live_decision="skip_interval")
    report["mode"] = "fixture"
    report["summary"]["live_quality_gate_success"] = None
    report["summary"]["live_quality_suite_success"] = None
    report["summary"]["live_quality_burn_min_score"] = 0.86
    report["summary"]["live_conversation_quality_run_count"] = 0
    report["summary"]["live_conversation_quality_recent_avg_min_quality_score"] = None
    report["summary"]["live_conversation_quality_native_video_upload_covered_count"] = 0
    report["automation"]["self_improvement"]["next_actions"].append(
        {
            "type": "prefer_strategy",
            "source": "live_quality_burn",
            "track": "aesthetic",
            "strategy_signature": "image_first_rank_then_video",
            "bucket": "image-video:product-editorial",
            "activation_status": "shadow",
            "confidence": 0.88,
            "evidence_count": 4,
        }
    )
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(
        latest_path=latest_path,
        now=datetime(2026, 6, 22, 16, 47, tzinfo=timezone.utc),
    )

    assert status["health_status"] == "pass"
    assert status["promotion_readiness"]["ready"] is False
    assert "current_live_run_required" in status["promotion_readiness"]["blocking_reasons"]


def test_visual_self_validation_status_allows_promotion_with_live_conversation_quality_evidence(
    tmp_path,
):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report(live_decision="skip_not_enabled")
    report["mode"] = "fixture"
    report["summary"]["live_quality_gate_success"] = None
    report["summary"]["live_quality_suite_success"] = None
    report["summary"]["live_quality_burn_success"] = None
    report["summary"]["live_quality_burn_case_count"] = 0
    report["summary"]["live_quality_burn_min_score"] = None
    report["summary"]["live_quality_burn_image_first_video_source_covered"] = None
    report["summary"]["live_slack_upload_native_delivery_covered"] = None
    report["automation"]["self_improvement"]["next_actions"].append(
        {
            "type": "prefer_strategy",
            "source": "slack_conversation_e2e",
            "track": "aesthetic",
            "strategy_signature": "image_first_rank_then_video",
            "bucket": "image-video:product-editorial",
            "activation_status": "shadow",
            "confidence": 0.83,
            "evidence_count": 5,
        }
    )
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["health_status"] == "pass"
    readiness = status["promotion_readiness"]
    assert readiness["ready"] is True
    assert readiness["blocking_reasons"] == []
    assert readiness["thresholds"]["allows_live_conversation_quality_evidence"] is True
    assert readiness["thresholds"]["min_live_conversation_quality_cases"] == 2
    assert readiness["thresholds"]["min_live_conversation_quality_score"] == 0.8
    assert readiness["self_review"]["conversation_evidence_gated"] is True
    assert status["next_steps"] == ["continue_visual_agent_mode_rollout"]


def test_visual_self_validation_status_blocks_promotion_when_conversation_upload_evidence_missing(
    tmp_path,
):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report(live_decision="skip_not_enabled")
    report["mode"] = "fixture"
    report["summary"]["live_quality_gate_success"] = None
    report["summary"]["live_quality_suite_success"] = None
    report["summary"]["live_quality_burn_success"] = None
    report["summary"]["live_quality_burn_case_count"] = 0
    report["summary"]["live_quality_burn_min_score"] = None
    report["summary"]["live_quality_burn_image_first_video_source_covered"] = None
    report["summary"]["live_slack_upload_native_delivery_covered"] = None
    report["summary"]["live_conversation_quality_native_video_upload_covered_count"] = 1
    report["automation"]["self_improvement"]["next_actions"].append(
        {
            "type": "prefer_strategy",
            "source": "slack_conversation_e2e",
            "track": "aesthetic",
            "strategy_signature": "image_first_rank_then_video",
            "bucket": "image-video:product-editorial",
            "activation_status": "shadow",
            "confidence": 0.83,
            "evidence_count": 5,
        }
    )
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["health_status"] == "warn"
    readiness = status["promotion_readiness"]
    assert readiness["ready"] is False
    assert "live_conversation_native_upload_not_covered" in readiness["blocking_reasons"]
    assert "slack_native_upload_not_covered" not in readiness["blocking_reasons"]


def test_visual_self_validation_status_keeps_promotion_ready_when_live_burn_passes_but_conversation_partial(
    tmp_path,
):
    from scripts.visual_self_validation_status import build_visual_self_validation_status

    report = _scheduled_report()
    report["summary"]["live_quality_burn_min_score"] = 0.86
    report["summary"]["live_conversation_quality_native_video_upload_covered_count"] = 1
    report["automation"]["self_improvement"]["next_actions"].append(
        {
            "type": "prefer_strategy",
            "source": "live_quality_burn",
            "track": "aesthetic",
            "strategy_signature": "image_first_rank_then_video",
            "bucket": "image-video:product-editorial",
            "activation_status": "shadow",
            "confidence": 0.86,
            "evidence_count": 5,
        }
    )
    latest_path = _write_latest(tmp_path, report)

    status = build_visual_self_validation_status(latest_path=latest_path)

    assert status["health_status"] == "pass"
    readiness = status["promotion_readiness"]
    assert readiness["ready"] is True
    assert "live_conversation_native_upload_not_covered" not in readiness["blocking_reasons"]


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
