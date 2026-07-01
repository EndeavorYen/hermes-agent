from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.raphael.mission import create_mission
from agent.raphael.models import MissionArtifact
from agent.raphael.proof import (
    RaphaelProofEvidence,
    claim_kind_from_text,
    evaluate_raphael_proof_gate,
    extract_raphael_proof_evidence,
    render_proof_gate_user_message,
    required_proofs_for_claim,
    required_proofs_for_route,
    should_render_proof_gate_for_text,
)
from agent.raphael.router import route_raphael_message


NOW = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)


def _evidence(
    proof_type: str,
    *,
    layer: str = "focused_tests",
    success: bool = True,
    summary: str | None = None,
) -> RaphaelProofEvidence:
    return RaphaelProofEvidence(
        proof_type=proof_type,
        layer=layer,
        success=success,
        summary=summary or f"{proof_type} fixture",
        source="fixture",
    )


def _artifact() -> MissionArtifact:
    return MissionArtifact(
        artifact_id="image-1",
        kind="image",
        label="Selected launch image",
        uri="/tmp/selected.png",
        created_at=NOW,
    )


def test_tool_success_alone_cannot_mark_visual_route_complete():
    route = route_raphael_message("請生成一張產品攝影圖片")
    result = evaluate_raphael_proof_gate(
        route=route,
        evidence=(
            _evidence(
                "tool_success",
                layer="tool",
                summary="visual_agent_generate returned success",
            ),
        ),
    )

    assert result.status == "blocked"
    assert result.failure_layer == "proof_gate"
    assert "artifact_quality_evidence" in result.missing_proofs
    assert "selected_current_artifact_only" in result.missing_proofs
    assert "tool_success" in result.available_proofs
    assert result.self_review.proven == ("tool_success",)
    assert "artifact_quality_evidence" in result.self_review.weaknesses
    assert result.self_review.next_action == result.next_action
    assert "artifact quality evidence" in result.next_action
    assert result.next_proof_command == (
        "raphael visual-quality-review <selected-artifact>"
    )
    assert "tool success" in render_proof_gate_user_message(result).lower()
    assert result.next_proof_command in render_proof_gate_user_message(result)


def test_all_required_proofs_pass_and_self_review_allows_reporting():
    route = route_raphael_message("請幫我搜尋 repo 內 pytest 失敗並修復")
    result = evaluate_raphael_proof_gate(
        route=route,
        evidence=(
            _evidence("focused_tests"),
            _evidence("diff_hygiene", layer="static_checks"),
        ),
        required_proofs=("focused_tests", "diff_hygiene"),
    )

    assert result.status == "passed"
    assert result.failure_layer is None
    assert result.missing_proofs == ()
    assert result.self_review.proven == ("diff_hygiene", "focused_tests")
    assert result.self_review.weaknesses == ()
    assert result.next_action == "Report success with the passing proof evidence."


def test_extracts_real_tool_call_command_arguments_for_pytest_and_diff_proofs():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_pytest",
                    "function": {
                        "name": "exec_command",
                        "arguments": '{"cmd": "python -m pytest tests/foo.py -q"}',
                    },
                },
                {
                    "id": "call_diff",
                    "function": {
                        "name": "exec_command",
                        "arguments": '{"cmd": "git diff --check"}',
                    },
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_pytest",
            "exit_code": 0,
            "content": "1 passed in 0.10s",
        },
        {
            "role": "tool",
            "tool_call_id": "call_diff",
            "exit_code": 0,
            "content": "",
        },
    ]

    events = extract_raphael_proof_evidence(messages)

    assert tuple(event.proof_type for event in events) == (
        "focused_tests",
        "diff_hygiene",
    )


def test_missing_mission_proof_keeps_current_mission_and_changes_next_action():
    mission = create_mission(
        mission_id="mission-1",
        goal="Ship a runtime fix",
        active_artifact=_artifact(),
        success_conditions=("runtime behavior proven",),
        phase="executing",
        next_action="run focused tests and runtime smoke",
        selected_strategy="proof-first repair",
        required_proofs=("focused_tests", "runtime_smoke_when_live_wiring"),
        now=NOW,
    )
    route = route_raphael_message("fix this runtime bug", active_mission=mission)

    result = evaluate_raphael_proof_gate(
        route=route,
        mission=mission,
        evidence=(_evidence("focused_tests"),),
    )

    assert result.status == "blocked"
    assert result.active_mission_id == "mission-1"
    assert result.required_proofs == (
        "focused_tests",
        "runtime_smoke_when_live_wiring",
    )
    assert result.missing_proofs == ("runtime_smoke_when_live_wiring",)
    assert result.self_review.proven == ("focused_tests",)
    assert result.self_review.weaknesses == ("runtime_smoke_when_live_wiring",)
    assert result.next_action == "Run runtime smoke before claiming completion."
    assert result.next_proof_command == "hermes gateway status"


@pytest.mark.parametrize(
    ("claim", "expected"),
    (
        ("runtime", ("runtime_smoke_when_live_wiring",)),
        ("llm", ("live_llm_smoke",)),
        ("install", ("package_install_smoke",)),
        (
            "media",
            (
                "artifact_quality_evidence",
                "selected_current_artifact_only",
                "delivery_cleanliness",
            ),
        ),
        (
            "artifact",
            ("artifact_quality_evidence", "stale_artifact_guard"),
        ),
    ),
)
def test_claim_types_map_to_distinct_required_proofs(claim, expected):
    assert required_proofs_for_claim(claim) == expected


def test_llm_only_fixture_passes_with_live_llm_smoke_without_visual_claims():
    route = route_raphael_message("請分析這個策略是否合理")

    assert required_proofs_for_claim("llm") == ("live_llm_smoke",)

    result = evaluate_raphael_proof_gate(
        route=route,
        evidence=(_evidence("live_llm_smoke", layer="llm_runtime"),),
        claim_kind="llm",
    )

    assert result.status == "passed"
    assert result.required_proofs == ("live_llm_smoke",)
    assert result.missing_proofs == ()
    assert "artifact_quality_evidence" not in result.required_proofs


def test_no_live_visual_fixture_requires_artifact_evidence_not_live_generation():
    route = route_raphael_message("請生成一張產品攝影圖片")

    required = required_proofs_for_route(route)

    assert "artifact_quality_evidence" in required
    assert "selected_current_artifact_only" in required
    assert "live_visual_e2e" not in required
    assert route.visual_handoff is not None
    assert route.visual_handoff["claim_live_media_ready"] is False


def test_completion_claim_detector_does_not_block_casual_readiness():
    assert not should_render_proof_gate_for_text("I'm ready to help.")
    assert not should_render_proof_gate_for_text("我準備好了，可以幫你。")
    assert should_render_proof_gate_for_text("The release is ready to ship.")
    assert should_render_proof_gate_for_text("完成了，測試也通過。")


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("Runtime is working and complete.", "runtime"),
        ("The LLM slice is ready to ship.", "llm"),
        ("Install is complete.", "install"),
        ("Media delivery is complete.", "media"),
        ("The selected artifact is complete.", "artifact"),
        ("完成了，測試也通過。", None),
    ),
)
def test_completion_claim_kind_is_inferred_from_response_text(text, expected):
    assert claim_kind_from_text(text) == expected


@pytest.mark.parametrize(
    ("failure_layer", "expected_action"),
    (
        (
            "provider_health",
            "Check provider health or choose a fallback provider.",
        ),
        (
            "prompt_moderation",
            "Revise the user-visible prompt or ask for a safe alternative.",
        ),
        (
            "handoff_failure",
            "Repair handoff metadata before retrying the specialist mode.",
        ),
        (
            "browser_automation_failure",
            "Run browser readiness smoke before polling for artifacts.",
        ),
        (
            "artifact_quality_failure",
            "Regenerate or repair the artifact with quality evidence.",
        ),
    ),
)
def test_failure_layers_are_distinguishable_and_actionable(
    failure_layer,
    expected_action,
):
    route = route_raphael_message("請生成一張產品攝影圖片")

    result = evaluate_raphael_proof_gate(
        route=route,
        evidence=(
            _evidence(
                "provider_response",
                layer=failure_layer,
                success=False,
                summary=f"{failure_layer} fixture failure",
            ),
        ),
    )
    message = render_proof_gate_user_message(result)

    assert result.status == "failed"
    assert result.failure_layer == failure_layer
    assert result.next_action == expected_action
    assert failure_layer in message
    assert expected_action in message
