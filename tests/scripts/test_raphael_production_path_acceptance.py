from __future__ import annotations

import json

from scripts.raphael_production_path_acceptance import (
    build_quota_free_production_scenarios,
    evaluate_pr_target,
    validate_acceptance,
)


def _report(**overrides):
    report = {
        "schema_version": "raphael.production_acceptance.v1",
        "feature_head": "abc123",
        "scenarios": [
            {"scenario_id": name, "status": "passed"}
            for name in (
                "conversation",
                "tool_task",
                "visual_routing",
                "same_artifact_followup",
                "provider_failure_classification",
                "missing_proof",
                "background_isolation",
                "codex_transport_parity",
            )
        ],
        "verification": {
            "tests": "passed",
            "static_checks": "passed",
            "diff_hygiene": "passed",
        },
        "runtime": {
            "routing_truth": "passed",
            "isolated_feature_smoke": "passed",
        },
        "reviews": {
            "codex": {"status": "pass", "head": "abc123"},
            "grok": {"status": "pass", "head": "abc123"},
        },
        "privacy_safe": True,
    }
    report.update(overrides)
    return report


def test_acceptance_rejects_missing_dual_review():
    report = _report(
        reviews={
            "codex": {"status": "pass", "head": "abc123"},
            "grok": None,
        }
    )

    result = validate_acceptance(report)

    assert result.status == "blocked"
    assert "grok_review_missing" in result.blocking_reasons


def test_acceptance_rejects_review_for_different_head():
    report = _report(
        reviews={
            "codex": {"status": "pass", "head": "older"},
            "grok": {"status": "pass", "head": "abc123"},
        }
    )

    result = validate_acceptance(report)

    assert "codex_review_head_mismatch" in result.blocking_reasons


def test_pr_gate_rejects_main_even_when_remote_reports_main_default():
    gate = evaluate_pr_target(default_branch="main")

    assert gate.allowed is False
    assert gate.reason == "default_branch_must_not_be_main"


def test_pr_gate_allows_verified_non_main_default_branch():
    gate = evaluate_pr_target(default_branch="stable")

    assert gate.allowed is True
    assert gate.target_branch == "stable"


def test_quota_free_scenarios_use_production_adapters_without_private_payloads():
    scenarios = build_quota_free_production_scenarios()

    assert {scenario["scenario_id"] for scenario in scenarios} == {
        "conversation",
        "tool_task",
        "visual_routing",
        "same_artifact_followup",
        "provider_failure_classification",
        "missing_proof",
        "background_isolation",
        "codex_transport_parity",
    }
    assert all(scenario["status"] == "passed" for scenario in scenarios)
    serialized = json.dumps(scenarios, sort_keys=True)
    assert "/Users/" not in serialized
    assert "/private/" not in serialized
    assert "raw_prompt" not in serialized
    assert "user_message" not in serialized
