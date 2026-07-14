from agent.visual.production_kernel.quality import classify_quality_blockers
from agent.visual.production_kernel.quality import evaluate_visual_quality


def test_stale_contract_blocks_delivery_before_aesthetic_scoring():
    decision = evaluate_visual_quality(
        contract_hash="current",
        artifact_contract_hash="old",
        artifact_id="artifact-1",
        quality_issues=(),
        hard_gate_passed=True,
        vision_confidence=0.9,
    )

    assert decision.deliverable is False
    assert decision.blocker_codes == ("stale_contract",)
    assert decision.reason == "artifact_contract_mismatch"


def test_missing_vision_evidence_cannot_create_false_quality_pass():
    decision = evaluate_visual_quality(
        contract_hash="current",
        artifact_contract_hash="current",
        artifact_id="artifact-1",
        quality_issues=(),
        hard_gate_passed=True,
        vision_confidence=0.0,
    )

    assert decision.deliverable is False
    assert decision.blocker_codes == ("vision_evidence_missing",)


def test_quality_issue_taxonomy_maps_existing_visual_judge_output():
    blockers = classify_quality_blockers(
        [
            "reference_identity_drift",
            "composition_bad",
            "face_unnatural",
            "style_adherence_low",
        ]
    )

    assert blockers == (
        "artifact_defect",
        "composition_weak",
        "reference_identity_drift",
        "style_mismatch",
    )


def test_provider_failure_is_not_misclassified_as_visual_preference():
    decision = evaluate_visual_quality(
        contract_hash="current",
        artifact_contract_hash="current",
        artifact_id="artifact-1",
        quality_issues=("not_beautiful",),
        hard_gate_passed=False,
        provider_failure={"error_type": "provider_unavailable"},
        vision_confidence=None,
    )

    assert "provider_failure" in decision.blocker_codes
    assert decision.deliverable is False
