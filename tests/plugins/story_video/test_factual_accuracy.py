from __future__ import annotations

from copy import deepcopy

from plugins.story_video.factual_accuracy import validate_factual_evidence


def _valid_bundle() -> tuple[dict, dict, str, dict]:
    script = (
        "### S00\n月亮反射太陽光，所以白天也可能看得見。\n\n"
        "### S01\n抬頭找找看，今天能不能發現它？"
    )
    ledger = {"production_type": "science_explainer"}
    evidence = {
        "schema": "story_video_factual_evidence_v1",
        "status": "PASS",
        "sources": [
            {
                "source_id": "nasa-moon-daylight",
                "title": "Why Can We See the Moon During the Day?",
                "publisher": "NASA",
                "url": "https://spaceplace.nasa.gov/moon-day/en/",
                "source_type": "official",
                "accessed_at": "2026-07-19",
            }
        ],
        "claims": [
            {
                "claim_id": "C001",
                "segment_id": "S00",
                "quote": "月亮反射太陽光，所以白天也可能看得見。",
                "importance": "central",
                "confidence": "established",
                "source_ids": ["nasa-moon-daylight"],
                "verification_status": "verified",
                "verification_note": "NASA explains reflected sunlight and daytime visibility.",
            }
        ],
        "nonfactual_segments": [
            {"segment_id": "S01", "reason": "viewer invitation with no factual claim"}
        ],
    }
    fact_checker = {
        "reviewer_id": "fact_checker",
        "evidence_source_ids": ["nasa-moon-daylight"],
        "verified_claim_ids": ["C001"],
        "claim_coverage_status": "PASS",
        "coverage_verified_segment_ids": ["S00", "S01"],
    }
    return evidence, ledger, script, fact_checker


def test_valid_factual_evidence_binds_claims_sources_and_segments() -> None:
    evidence, ledger, script, fact_checker = _valid_bundle()

    assert validate_factual_evidence(
        evidence,
        ledger=ledger,
        script_text=script,
        fact_checker=fact_checker,
    ) == ()


def test_factual_evidence_rejects_unknown_source_and_nonexact_quote() -> None:
    evidence, ledger, script, fact_checker = _valid_bundle()
    evidence["claims"][0]["source_ids"] = ["invented-source"]
    evidence["claims"][0]["quote"] = "月亮自己發光。"

    violations = validate_factual_evidence(
        evidence,
        ledger=ledger,
        script_text=script,
        fact_checker=fact_checker,
    )

    assert "factual_evidence claim C001 references unknown source: invented-source" in violations
    assert "factual_evidence claim C001 quote is not exact in S00" in violations


def test_factual_evidence_requires_every_script_segment_to_be_classified() -> None:
    evidence, ledger, script, fact_checker = _valid_bundle()
    evidence["nonfactual_segments"] = []

    violations = validate_factual_evidence(
        evidence,
        ledger=ledger,
        script_text=script,
        fact_checker=fact_checker,
    )

    assert "factual_evidence segment S01 is uncovered" in violations


def test_central_claim_requires_authoritative_source_or_corroboration() -> None:
    evidence, ledger, script, fact_checker = _valid_bundle()
    evidence["sources"][0]["source_type"] = "authoritative_reference"

    violations = validate_factual_evidence(
        evidence,
        ledger=ledger,
        script_text=script,
        fact_checker=fact_checker,
    )

    assert "factual_evidence central claim C001 lacks authoritative or corroborated support" in violations


def test_fact_checker_must_verify_exact_current_claim_and_source_sets() -> None:
    evidence, ledger, script, fact_checker = _valid_bundle()
    mismatched = deepcopy(fact_checker)
    mismatched["verified_claim_ids"] = ["C999"]
    mismatched["evidence_source_ids"] = []

    violations = validate_factual_evidence(
        evidence,
        ledger=ledger,
        script_text=script,
        fact_checker=mismatched,
    )

    assert "script_review_report fact_checker verified_claim_ids mismatch" in violations
    assert "script_review_report fact_checker evidence_source_ids mismatch" in violations


def test_fact_checker_must_attest_complete_current_segment_coverage() -> None:
    evidence, ledger, script, fact_checker = _valid_bundle()
    fact_checker["claim_coverage_status"] = "PASS"
    fact_checker["coverage_verified_segment_ids"] = ["S00"]

    violations = validate_factual_evidence(
        evidence,
        ledger=ledger,
        script_text=script,
        fact_checker=fact_checker,
    )

    assert "script_review_report fact_checker coverage_verified_segment_ids mismatch" in violations
