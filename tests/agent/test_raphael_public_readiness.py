from __future__ import annotations

import json
from datetime import datetime, timezone

from agent.raphael.public_readiness import (
    build_public_llm_slice_readiness,
    classify_llm_smoke,
    load_llm_smoke_evidence,
    render_public_readiness,
    write_public_readiness_gate,
    run_public_llm_slice_simulation,
    validate_public_claim_boundary,
)


NOW = datetime(2026, 7, 2, 13, 0, tzinfo=timezone.utc)


def test_public_llm_slice_simulation_covers_core_non_visual_journeys():
    simulation = run_public_llm_slice_simulation(now=NOW)

    assert simulation.status == "passed"
    case_ids = {case.case_id for case in simulation.cases}
    assert {
        "summon_tool_task",
        "mission_followup",
        "ambiguous_clarification",
        "proof_block",
        "finalizer_proof_block_output",
        "evolution_proposal",
        "proposal_lifecycle_status",
        "public_claim_boundary",
    } <= case_ids
    assert all(case.passed for case in simulation.cases)
    assert simulation.media_claim_ready is False
    assert simulation.visual_claim_ready is False
    assert simulation.grok_claim_ready is False


def test_readiness_report_blocks_llm_without_live_smoke_and_never_claims_media():
    simulation = run_public_llm_slice_simulation(now=NOW)

    report = build_public_llm_slice_readiness(
        simulation=simulation,
        live_smoke=None,
        now=NOW,
    )

    assert report.status == "blocked"
    assert report.slices["llm"]["ready"] is False
    assert "live_llm_smoke_missing" in report.slices["llm"]["blocking_reasons"]
    assert report.slices["media"]["ready"] is False
    assert report.slices["visual"]["ready"] is False
    assert report.slices["grok"]["ready"] is False
    assert "LLM slice is not ready until live smoke passes." in report.public_claims
    assert "Media and visual generation are not ready in this phase." in report.blocked_claims


def test_readiness_report_marks_only_llm_slice_ready_with_live_smoke():
    simulation = run_public_llm_slice_simulation(now=NOW)
    smoke = classify_llm_smoke(
        exit_code=0,
        response_text=(
            "Raphael maintained mission state, blocked unsupported success, "
            "and proposed auditable evolution."
        ),
        provider="openai",
        model="gpt-5.5",
        evidence_ref="live-smoke:phase6",
    )

    report = build_public_llm_slice_readiness(
        simulation=simulation,
        live_smoke=smoke,
        now=NOW,
    )

    assert report.status == "llm_ready"
    assert report.slices["llm"]["ready"] is True
    assert report.slices["llm"]["evidence_refs"] == ["live-smoke:phase6"]
    assert report.slices["media"]["ready"] is False
    assert report.slices["visual"]["ready"] is False
    assert report.slices["grok"]["ready"] is False
    assert "Raphael LLM control-layer slice is ready." in report.public_claims
    assert "Media and visual generation are not ready in this phase." in report.blocked_claims


def test_smoke_evidence_loader_requires_existing_matching_session_file(tmp_path):
    smoke_path = tmp_path / "smoke.json"
    smoke_path.write_text(
        json.dumps(
            {
                "session_id": "phase6-smoke-session",
                "source": "rtk hermes chat",
                "command": "rtk hermes chat -Q --max-turns 1 -q <phase6 smoke>",
                "exit_code": 0,
                "provider": "openai",
                "model": "gpt-5.5",
                "response_text": (
                    "This LLM-only smoke proves text control layer only; "
                    "media/visual/Grok are not ready."
                ),
                "evidence_ref": "live-smoke:phase6",
                "phase6_checks": {
                    "summon_ux": True,
                    "mission_followup": True,
                    "proof_block": True,
                    "evolution_proposal": True,
                    "llm_only_boundary": True,
                },
            }
        ),
        encoding="utf-8",
    )

    smoke = load_llm_smoke_evidence(
        smoke_path,
        expected_session_id="phase6-smoke-session",
    )

    assert smoke.status == "passed"
    assert smoke.evidence_refs == ("live-smoke:phase6 session:phase6-smoke-session",)


def test_smoke_evidence_loader_rejects_fake_or_mismatched_session(tmp_path):
    smoke_path = tmp_path / "smoke.json"
    smoke_path.write_text(
        json.dumps(
            {
                "session_id": "different-session",
                "exit_code": 0,
                "provider": "openai",
                "model": "gpt-5.5",
                "response_text": "looks plausible",
                "evidence_ref": "live-smoke:phase6",
            }
        ),
        encoding="utf-8",
    )

    smoke = load_llm_smoke_evidence(
        smoke_path,
        expected_session_id="phase6-smoke-session",
    )

    assert smoke.status == "failed"
    assert smoke.failure_layer == "llm_smoke_evidence"
    assert smoke.next_action == "Provide a matching LLM smoke evidence file."


def test_smoke_evidence_loader_rejects_matching_session_without_manifest(tmp_path):
    smoke_path = tmp_path / "smoke.json"
    smoke_path.write_text(
        json.dumps(
            {
                "session_id": "phase6-smoke-session",
                "exit_code": 0,
                "provider": "openai",
                "model": "gpt-5.5",
                "response_text": "safe looking but unproven",
                "evidence_ref": "live-smoke:phase6",
            }
        ),
        encoding="utf-8",
    )

    smoke = load_llm_smoke_evidence(
        smoke_path,
        expected_session_id="phase6-smoke-session",
    )

    assert smoke.status == "failed"
    assert smoke.failure_layer == "llm_smoke_manifest"
    assert smoke.next_action == "Provide Phase 6 smoke checks from the approved chat path."


def test_smoke_evidence_loader_rejects_malformed_exit_code(tmp_path):
    smoke_path = tmp_path / "smoke.json"
    smoke_path.write_text(
        json.dumps(
            {
                "session_id": "phase6-smoke-session",
                "source": "rtk hermes chat",
                "command": "rtk hermes chat -Q --max-turns 1 -q <phase6 smoke>",
                "exit_code": "not-an-int",
                "provider": "openai",
                "model": "gpt-5.5",
                "response_text": "safe looking but malformed",
                "evidence_ref": "live-smoke:phase6",
                "phase6_checks": {
                    "summon_ux": True,
                    "mission_followup": True,
                    "proof_block": True,
                    "evolution_proposal": True,
                    "llm_only_boundary": True,
                },
            }
        ),
        encoding="utf-8",
    )

    smoke = load_llm_smoke_evidence(
        smoke_path,
        expected_session_id="phase6-smoke-session",
    )

    assert smoke.status == "failed"
    assert smoke.failure_layer == "llm_smoke_evidence"


def test_public_claim_boundary_rejects_forbidden_ready_claims():
    result = validate_public_claim_boundary(
        (
            "Raphael LLM control-layer slice is ready.",
            "Grok video media image Slack delivery release candidate full release ready.",
            "Grok 已就緒，OpenAI image generation 可用。",
        )
    )

    assert result.passed is False
    assert "forbidden_claim:grok" in result.evidence_refs
    assert "forbidden_claim:video" in result.evidence_refs
    assert "forbidden_claim:media" in result.evidence_refs
    assert "forbidden_claim:image" in result.evidence_refs
    assert "forbidden_claim:slack" in result.evidence_refs
    assert "forbidden_claim:delivery" in result.evidence_refs
    assert "forbidden_claim:release_candidate" in result.evidence_refs
    assert "forbidden_claim:full_release" in result.evidence_refs


def test_public_claim_boundary_allows_chinese_negative_ready_claims():
    result = validate_public_claim_boundary(
        ("media/visual/Grok 不能在這個 smoke 中宣稱 ready；本輪只證明文字控制層。",)
    )

    assert result.passed is True
    assert result.evidence_refs == ("claim_boundary:clean",)


def test_release_gate_writes_durable_llm_only_report(tmp_path):
    simulation = run_public_llm_slice_simulation(now=NOW)
    smoke = classify_llm_smoke(
        exit_code=0,
        response_text=(
            "Raphael maintained mission state and explicitly says media/visual/Grok "
            "are not ready."
        ),
        provider="openai",
        model="gpt-5.5",
        evidence_ref="live-smoke:phase6 session:phase6-smoke-session",
    )
    report = build_public_llm_slice_readiness(
        simulation=simulation,
        live_smoke=smoke,
        now=NOW,
    )
    output_path = tmp_path / "raphael-readiness.json"

    write_public_readiness_gate(report, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["status"] == "llm_ready"
    assert payload["slices"]["llm"]["ready"] is True
    assert payload["slices"]["media"]["ready"] is False
    assert payload["slices"]["visual"]["ready"] is False
    assert payload["slices"]["grok"]["ready"] is False
    assert payload["simulation"]["status"] == "passed"
    assert payload["live_smoke"]["status"] == "passed"
    assert "full release ready" not in json.dumps(payload).lower()


def test_failed_llm_smoke_classifies_layer_and_next_action():
    smoke = classify_llm_smoke(
        exit_code=1,
        response_text="",
        provider="openai",
        model="gpt-5.5",
        evidence_ref="live-smoke:failed",
    )

    assert smoke.status == "failed"
    assert smoke.failure_layer == "llm_runtime"
    assert smoke.next_action == "Run the LLM smoke again after fixing runtime/auth/config."


def test_render_public_readiness_is_clean_and_explicit_about_boundaries():
    simulation = run_public_llm_slice_simulation(now=NOW)
    report = build_public_llm_slice_readiness(
        simulation=simulation,
        live_smoke=None,
        now=NOW,
    )

    output = render_public_readiness(report)

    assert "Raphael Public LLM Slice Readiness" in output
    assert "Overall: blocked" in output
    assert "LLM slice: blocked" in output
    assert "Media slice: not ready" in output
    assert "Visual slice: not ready" in output
    assert "Grok slice: not ready" in output
    assert "live_llm_smoke_missing" in output
    assert "base64" not in output
