from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agent.raphael.media_readiness import (
    RaphaelMediaEvidence,
    RaphaelMediaReadinessReport,
    build_media_readiness,
    classify_openai_image_evidence,
    render_media_readiness,
    validate_media_claim_boundary,
    write_media_readiness_gate,
)


NOW = datetime(2026, 7, 2, 15, 30, tzinfo=timezone.utc)
SESSION_ID = "phase7-openai-image-session"
SELECTED_ARTIFACT_ID = "openai-image-1"


def _required_evidence_refs():
    return {
        "generation": "generation:openai-image-1",
        "selection": "selection:openai-image-1",
        "freshness": "freshness:phase7-session",
        "dedupe": "dedupe:openai-image-1",
        "geometry": "geometry:1536x1024",
        "quality_review": "quality-review:openai-image-1",
    }


def _passing_openai_image_payload(**overrides):
    payload = {
        "session_id": SESSION_ID,
        "generated_at": NOW.isoformat(),
        "provider": "openai",
        "capability": "image",
        "status": "success",
        "artifact_id": SELECTED_ARTIFACT_ID,
        "selected_artifact_id": SELECTED_ARTIFACT_ID,
        "fresh": True,
        "rejected": False,
        "duplicated": False,
        "dimensions": {"width": 1536, "height": 1024},
        "quality": {
            "passed": True,
            "score": 0.88,
            "review_ref": "vision-review:openai-image-1",
        },
        "evidence_refs": _required_evidence_refs(),
    }
    payload.update(overrides)
    return payload


def _classify(payload):
    return classify_openai_image_evidence(
        payload,
        expected_session_id=SESSION_ID,
        current_selected_artifact_id=SELECTED_ARTIFACT_ID,
        now=NOW,
    )


def test_openai_image_evidence_marks_only_image_slice_ready():
    evidence = _classify(_passing_openai_image_payload())

    report = build_media_readiness(openai_image=evidence, now=NOW)

    assert report.status == "openai_image_ready"
    assert report.slices["openai_image"]["ready"] is True
    assert report.slices["openai_image"]["evidence_refs"] == list(
        _required_evidence_refs().values()
    )
    assert report.slices["grok_web_imagine"]["ready"] is False
    assert report.slices["video"]["ready"] is False
    assert report.slices["slack_delivery"]["ready"] is False
    assert report.slices["full_media"]["ready"] is False
    assert "OpenAI image slice is ready." in report.public_claims
    assert "Grok Web Imagine readiness requires separate live evidence." in report.blocked_claims
    assert "Video readiness requires separate live evidence." in report.blocked_claims
    assert "Full media readiness remains blocked." in report.blocked_claims


@pytest.mark.parametrize(
    ("overrides", "expected_layer", "expected_reason"),
    [
        ({"fresh": False}, "artifact_freshness", "openai_image_artifact_stale"),
        ({"duplicated": True}, "artifact_deduplication", "openai_image_duplicate_artifact"),
        ({"rejected": True}, "artifact_quality", "openai_image_artifact_rejected"),
        (
            {"selected_artifact_id": "different-artifact"},
            "artifact_selection",
            "openai_image_not_selected_artifact",
        ),
    ],
)
def test_openai_image_evidence_rejects_stale_duplicate_rejected_or_wrong_artifacts(
    overrides,
    expected_layer,
    expected_reason,
):
    evidence = _classify(_passing_openai_image_payload(**overrides))

    report = build_media_readiness(openai_image=evidence, now=NOW)

    assert evidence.status == "failed"
    assert evidence.failure_layer == expected_layer
    assert report.status == "blocked"
    assert report.slices["openai_image"]["ready"] is False
    assert expected_reason in report.slices["openai_image"]["blocking_reasons"]
    assert report.slices["full_media"]["ready"] is False


@pytest.mark.parametrize(
    ("overrides", "expected_layer", "expected_reason"),
    [
        ({}, "openai_image_evidence", "openai_image_evidence_refs_missing"),
        (
            {"evidence_refs": {"generation": "generation:openai-image-1"}},
            "openai_image_evidence",
            "openai_image_evidence_refs_incomplete",
        ),
    ],
)
def test_openai_image_evidence_requires_structured_refs(
    overrides,
    expected_layer,
    expected_reason,
):
    payload = _passing_openai_image_payload()
    payload.pop("evidence_refs")
    payload.update(overrides)

    evidence = _classify(payload)
    report = build_media_readiness(openai_image=evidence, now=NOW)

    assert evidence.status == "failed"
    assert evidence.failure_layer == expected_layer
    assert report.status == "blocked"
    assert expected_reason in report.slices["openai_image"]["blocking_reasons"]


def test_openai_image_evidence_rejects_replayed_or_wrong_selected_artifact_context():
    session_mismatch = classify_openai_image_evidence(
        _passing_openai_image_payload(session_id="old-session"),
        expected_session_id=SESSION_ID,
        current_selected_artifact_id=SELECTED_ARTIFACT_ID,
        now=NOW,
    )
    selected_mismatch = classify_openai_image_evidence(
        _passing_openai_image_payload(),
        expected_session_id=SESSION_ID,
        current_selected_artifact_id="new-current-artifact",
        now=NOW,
    )

    assert session_mismatch.status == "failed"
    assert session_mismatch.failure_layer == "artifact_freshness"
    assert session_mismatch.blocking_reason == "openai_image_session_mismatch"
    assert selected_mismatch.status == "failed"
    assert selected_mismatch.failure_layer == "artifact_selection"
    assert selected_mismatch.blocking_reason == "openai_image_not_current_selected_artifact"


def test_openai_image_evidence_rejects_old_generated_at_even_when_fresh_flag_is_true():
    evidence = classify_openai_image_evidence(
        _passing_openai_image_payload(generated_at="2026-07-01T00:00:00+00:00"),
        expected_session_id=SESSION_ID,
        current_selected_artifact_id=SELECTED_ARTIFACT_ID,
        max_age_seconds=60,
        now=NOW,
    )

    assert evidence.status == "failed"
    assert evidence.failure_layer == "artifact_freshness"
    assert evidence.blocking_reason == "openai_image_evidence_stale"


@pytest.mark.parametrize("quality_score", [float("nan"), float("inf"), float("-inf"), "nan"])
def test_openai_image_evidence_rejects_non_finite_quality_scores(quality_score):
    payload = _passing_openai_image_payload()
    payload["quality"] = {"passed": True, "score": quality_score}

    evidence = _classify(payload)

    assert evidence.status == "failed"
    assert evidence.failure_layer == "artifact_quality"
    assert evidence.blocking_reason == "openai_image_quality_below_threshold"


@pytest.mark.parametrize(
    ("field", "expected_layer", "expected_reason"),
    [
        ("duplicated", "artifact_deduplication", "openai_image_duplicate_status_missing"),
        ("rejected", "artifact_quality", "openai_image_rejection_status_missing"),
    ],
)
def test_openai_image_evidence_requires_explicit_negative_duplicate_and_rejection_flags(
    field,
    expected_layer,
    expected_reason,
):
    payload = _passing_openai_image_payload()
    payload.pop(field)

    evidence = _classify(payload)

    assert evidence.status == "failed"
    assert evidence.failure_layer == expected_layer
    assert evidence.blocking_reason == expected_reason


@pytest.mark.parametrize(
    ("failure_payload", "expected_layer", "expected_reason"),
    [
        (
            {
                "status": "failed",
                "error_type": "auth_required",
                "message": "OPENAI_API_KEY missing",
            },
            "setup_required",
            "openai_image_setup_required",
        ),
        (
            {
                "status": "failed",
                "status_code": 401,
                "message": "invalid_api_key unauthorized",
            },
            "setup_required",
            "openai_image_setup_required",
        ),
        (
            {"status": "failed", "error": {"code": "insufficient_credits"}, "message": "quota exceeded"},
            "quota_required",
            "openai_image_quota_required",
        ),
        (
            {"status": "failed", "status_code": 503, "message": "provider unavailable"},
            "provider_health",
            "openai_image_provider_health_failed",
        ),
    ],
)
def test_openai_image_failures_classify_setup_quota_and_provider_health(
    failure_payload,
    expected_layer,
    expected_reason,
):
    payload = {
        "session_id": SESSION_ID,
        "provider": "openai",
        "capability": "image",
        "evidence_refs": _required_evidence_refs(),
        **failure_payload,
    }

    evidence = _classify(payload)
    report = build_media_readiness(openai_image=evidence, now=NOW)

    assert evidence.status == "failed"
    assert evidence.failure_layer == expected_layer
    assert report.status == "blocked"
    assert expected_reason in report.slices["openai_image"]["blocking_reasons"]
    assert "openai_image_artifact_rejected" not in report.slices["openai_image"]["blocking_reasons"]


def test_media_claim_boundary_allows_openai_image_but_blocks_grok_video_and_full_media():
    allowed = validate_media_claim_boundary(
        (
            "OpenAI image slice is ready.",
            "Grok Web Imagine and video are not ready.",
            "Full media readiness remains blocked.",
        )
    )
    forbidden = validate_media_claim_boundary(
        (
            "OpenAI image slice is ready.",
            "Grok Web Imagine, video, Slack delivery, and full media are ready.",
            "Grok Web Imagine readiness is certified and video readiness passed.",
        )
    )

    assert allowed.passed is True
    assert forbidden.passed is False
    assert "forbidden_claim:grok_web_imagine" in forbidden.evidence_refs
    assert "forbidden_claim:video" in forbidden.evidence_refs
    assert "forbidden_claim:slack_delivery" in forbidden.evidence_refs
    assert "forbidden_claim:full_media" in forbidden.evidence_refs


def test_media_claim_boundary_rejects_readiness_certification_wording():
    result = validate_media_claim_boundary(
        (
            "OpenAI image slice is ready.",
            "Grok Web Imagine readiness is certified.",
            "Video readiness passed.",
            "Full media release readiness approved.",
        )
    )

    assert result.passed is False
    assert "forbidden_claim:grok_web_imagine" in result.evidence_refs
    assert "forbidden_claim:video" in result.evidence_refs
    assert "forbidden_claim:full_media" in result.evidence_refs


def test_media_readiness_gate_output_sanitizes_private_paths_and_raw_provider_payloads(tmp_path):
    evidence = _classify(
        _passing_openai_image_payload(
            artifact_path="/private/tmp/secret-selected-openai.png",
            provider_response="data:image/png;base64,abc123",
            rejected_candidate_uri="candidate:/private/tmp/old.png",
        )
    )
    report = build_media_readiness(openai_image=evidence, now=NOW)
    output_path = tmp_path / "media-readiness.json"

    write_media_readiness_gate(report, output_path)

    payload_text = output_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    rendered = render_media_readiness(report)

    assert payload["status"] == "openai_image_ready"
    assert payload["slices"]["openai_image"]["ready"] is True
    assert payload["slices"]["openai_image"]["selected_artifact_id"] == "openai-image-1"
    assert payload["slices"]["openai_image"]["dimensions"] == {"width": 1536, "height": 1024}
    assert "/private/tmp" not in payload_text
    assert "secret-selected-openai" not in payload_text
    assert "base64" not in payload_text
    assert "data:image" not in payload_text
    assert "candidate:" not in payload_text
    assert "/private/tmp" not in rendered
    assert "base64" not in rendered


def test_media_readiness_gate_output_sanitizes_report_boundary_even_for_manual_evidence(tmp_path):
    evidence = RaphaelMediaEvidence(
        status="passed",
        provider="openai",
        capability="image",
        evidence_refs=("/private/tmp/raw-provider.log", "base64:secret"),
        failure_layer=None,
        blocking_reason=None,
        next_action="Keep /private/tmp/secret.png private.",
        artifact_id="/private/tmp/secret-artifact.png",
        selected_artifact_id="/private/tmp/secret-selected.png",
        dimensions={"width": "/private/tmp/width", "height": "base64:height"},
        quality_score="/private/tmp/score base64:secret",
    )
    report = build_media_readiness(openai_image=evidence, now=NOW)
    output_path = tmp_path / "media-readiness.json"

    write_media_readiness_gate(report, output_path)

    payload_text = output_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    rendered = render_media_readiness(report)

    assert payload["status"] == "blocked"
    assert payload["slices"]["openai_image"]["ready"] is False
    assert "openai_image_contract_unverified" in payload["slices"]["openai_image"]["blocking_reasons"]
    assert "/private/tmp" not in payload_text
    assert "base64" not in payload_text
    assert "/private/tmp" not in rendered
    assert "base64" not in rendered


def test_render_media_readiness_sanitizes_foreign_report_dynamic_values():
    report = RaphaelMediaReadinessReport(
        status="/private/tmp/status base64:secret",
        slices={
            "openai_image": {
                "ready": False,
                "blocking_reasons": [
                    "/private/tmp/blocker.log",
                    "base64:secret-blocker",
                ],
                "evidence_refs": [],
                "selected_artifact_id": "/private/tmp/secret.png",
                "dimensions": {
                    "width": "/private/tmp/width",
                    "height": "base64:height",
                },
            },
            "grok_web_imagine": {"ready": False},
            "video": {"ready": False},
            "slack_delivery": {"ready": False},
            "full_media": {"ready": False},
        },
        public_claims=("/private/tmp/public base64:claim",),
        blocked_claims=("/private/tmp/blocked base64:claim",),
        openai_image=None,
        created_at=NOW,
    )

    output = render_media_readiness(report)

    assert "/private/tmp" not in output
    assert "base64" not in output


def test_media_readiness_gate_json_sanitizes_foreign_report_dynamic_values(tmp_path):
    report = RaphaelMediaReadinessReport(
        status="/private/tmp/status base64:secret",
        slices={
            "openai_image": {
                "ready": False,
                "blocking_reasons": ["/private/tmp/blocker.log"],
                "evidence_refs": [],
            },
            "/private/tmp/foreign_slice": {
                "ready": False,
                "blocking_reasons": ["base64:foreign"],
                "evidence_refs": [],
            },
            "grok_web_imagine": {"ready": False},
            "video": {"ready": False},
            "slack_delivery": {"ready": False},
            "full_media": {"ready": False},
        },
        public_claims=("/private/tmp/public base64:claim",),
        blocked_claims=("/private/tmp/blocked base64:claim",),
        openai_image=None,
        created_at=NOW,
    )
    output_path = tmp_path / "media-readiness.json"

    write_media_readiness_gate(report, output_path)

    payload_text = output_path.read_text(encoding="utf-8")

    assert "/private/tmp" not in payload_text
    assert "base64" not in payload_text
