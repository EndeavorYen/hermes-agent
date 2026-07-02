from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.raphael.release_candidate import (
    build_release_candidate_gate,
    render_release_candidate_gate,
    write_release_candidate_gate,
)


NOW = datetime(2026, 7, 2, 16, 30, tzinfo=timezone.utc)


def _lifecycle_gate(**overrides):
    payload = {
        "schema_version": "raphael.lifecycle_evidence.v1",
        "install": True,
        "enable": True,
        "disable": True,
        "uninstall": True,
        "private_output_clean": True,
        "checks": {
            "install": {"exit_code": 0, "evidence_ref": "lifecycle:install"},
            "enable": {"exit_code": 0, "evidence_ref": "lifecycle:enable"},
            "disable": {"exit_code": 0, "evidence_ref": "lifecycle:disable"},
            "uninstall": {"exit_code": 0, "evidence_ref": "lifecycle:uninstall"},
        },
    }
    payload.update(overrides)
    return payload


def _llm_gate(**overrides):
    cases = [
        {"case_id": "summon_tool_task", "passed": True},
        {"case_id": "mission_followup", "passed": True},
        {"case_id": "ambiguous_clarification", "passed": True},
        {"case_id": "proof_block", "passed": True},
        {"case_id": "finalizer_proof_block_output", "passed": True},
        {"case_id": "evolution_proposal", "passed": True},
        {"case_id": "proposal_lifecycle_status", "passed": True},
        {"case_id": "public_claim_boundary", "passed": True},
    ]
    payload = {
        "schema_version": "raphael.public_readiness.v1",
        "status": "llm_ready",
        "slices": {
            "llm": {"ready": True, "evidence_refs": ["live-smoke:phase6"]},
            "media": {"ready": False},
            "visual": {"ready": False},
            "grok": {"ready": False},
        },
        "public_claims": ["Raphael LLM control-layer slice is ready."],
        "blocked_claims": [
            "Media and visual generation are not ready in this phase.",
            "Grok and video readiness require separate live evidence.",
        ],
        "simulation": {"status": "passed", "cases": cases},
        "live_smoke": {
            "status": "passed",
            "provider": "openai",
            "model": "gpt-5.5",
            "failure_layer": None,
            "evidence_refs": ["live-smoke:phase6"],
        },
    }
    payload.update(overrides)
    return payload


def _media_gate(**overrides):
    payload = {
        "schema_version": "raphael.media_readiness.v1",
        "status": "openai_image_ready",
        "openai_image": {
            "status": "passed",
            "provider": "openai",
            "capability": "image",
            "selected_artifact_id": "openai-image-1",
            "dimensions": {"width": 1536, "height": 1024},
            "quality_score": 0.89,
            "verification_contract": "raphael.media.openai_image.phase7.current_selected.v1",
            "evidence_refs": [
                "generation:openai-image-1",
                "selection:openai-image-1",
                "freshness:phase7-session",
                "dedupe:openai-image-1",
                "geometry:1536x1024",
                "quality-review:openai-image-1",
            ],
        },
        "slices": {
            "openai_image": {
                "ready": True,
                "evidence_refs": [
                    "generation:openai-image-1",
                    "selection:openai-image-1",
                    "freshness:phase7-session",
                    "dedupe:openai-image-1",
                    "geometry:1536x1024",
                    "quality-review:openai-image-1",
                ],
                "selected_artifact_id": "openai-image-1",
                "dimensions": {"width": 1536, "height": 1024},
                "quality_score": 0.89,
            },
            "grok_web_imagine": {"ready": False},
            "video": {"ready": False},
            "slack_delivery": {"ready": False},
            "full_media": {"ready": False},
        },
        "public_claims": ["OpenAI image slice is ready."],
        "blocked_claims": [
            "Grok Web Imagine readiness requires separate live evidence.",
            "Video readiness requires separate live evidence.",
            "Slack native delivery readiness requires separate live evidence.",
            "Full media readiness remains blocked.",
        ],
    }
    payload.update(overrides)
    return payload


def test_release_candidate_gate_marks_verified_public_slices_ready_only():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(
            "Raphael release candidate is ready for LLM control and OpenAI image slice. "
            "Grok Web Imagine, video, Slack delivery, and full media are not ready.",
        ),
        now=NOW,
    )

    assert report.status == "release_candidate_ready"
    assert report.slices["lifecycle"]["ready"] is True
    assert report.slices["llm"]["ready"] is True
    assert report.slices["openai_image"]["ready"] is True
    assert report.slices["grok_web_imagine"]["ready"] is False
    assert report.slices["video"]["ready"] is False
    assert report.slices["slack_delivery"]["ready"] is False
    assert report.slices["full_media"]["ready"] is False
    assert "Raphael release candidate is ready for verified LLM and OpenAI image slices." in report.public_claims
    assert "Grok Web Imagine, video, Slack delivery, and full media remain blocked." in report.blocked_claims


def test_release_candidate_gate_blocks_docs_that_overclaim_unverified_media():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(
            "Raphael release candidate: Grok Web Imagine, video, and full media are ready.",
        ),
        now=NOW,
    )

    assert report.status == "blocked"
    assert report.slices["public_claims"]["ready"] is False
    assert "public_claim_boundary_failed" in report.slices["public_claims"]["blocking_reasons"]
    assert "forbidden_claim:grok_web_imagine" in report.slices["public_claims"]["evidence_refs"]
    assert "forbidden_claim:video" in report.slices["public_claims"]["evidence_refs"]
    assert "forbidden_claim:full_media" in report.slices["public_claims"]["evidence_refs"]


def test_release_candidate_gate_blocks_generic_media_or_visual_overclaims_from_raw_string():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("Media readiness is approved. Visual generation is ready."),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:full_media" in report.slices["public_claims"]["evidence_refs"]


def test_release_candidate_gate_allows_negative_certification_boundary_wording():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(
            "This release candidate does not certify Grok Web Imagine, video, "
            "Slack delivery, or full media readiness. Do not publish claims "
            "that Grok, video, Slack delivery, or full media are ready.\n"
            "Public wording does not claim media, visual, video, Grok, or full release readiness.\n"
            "The evidence contains no forbidden media, visual, Grok, video, or full-release ready claim.\n"
            "These remain blocked until later evidence:\n"
            "- Grok Web Imagine readiness remains blocked.\n"
            "- Video readiness remains blocked.\n"
            "- Slack delivery readiness remains blocked.\n"
            "- Full media readiness remains blocked.",
        ),
        now=NOW,
    )

    assert report.status == "release_candidate_ready"
    assert report.slices["public_claims"]["ready"] is True


def test_release_candidate_gate_handles_markdown_code_fences_headings_and_bullets():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(
            "```bash\n"
            "hermes raphael readiness --gate-output /tmp/raphael-readiness.json\n"
            "```\n"
            "## Gate\n"
            "- the LLM gate reports `llm_ready`\n"
            "- the media gate reports `openai_image_ready`\n"
            "- Grok Web Imagine, video, Slack delivery, and full media are still blocked\n"
            "## Public Claim\n"
            "`Raphael release candidate is ready for verified LLM and OpenAI image slices.`\n"
        ),
        now=NOW,
    )

    assert report.status == "release_candidate_ready"
    assert report.slices["public_claims"]["ready"] is True


def test_release_candidate_gate_accepts_checked_in_public_docs():
    docs = (
        Path("docs/raphael-release-candidate.md").read_text(),
        Path("docs/raphael-llm-public-slice.md").read_text(),
        Path("docs/raphael-media-readiness.md").read_text(),
    )

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=docs,
        now=NOW,
    )

    assert report.status == "release_candidate_ready"
    assert report.slices["public_claims"]["ready"] is True


def test_release_candidate_gate_blocks_media_gate_that_marks_unverified_video_ready():
    media_gate = _media_gate()
    media_gate["slices"]["video"] = {"ready": True, "evidence_refs": ["video:fake"]}

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=media_gate,
        doc_texts=("OpenAI image slice is ready; video is not ready.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert report.slices["media_gate"]["ready"] is False
    assert "media_gate_unverified_slice_ready:video" in report.slices["media_gate"]["blocking_reasons"]


def test_release_candidate_gate_blocks_status_only_llm_and_media_json():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate={"status": "llm_ready", "slices": {"llm": {"ready": True}}},
        media_gate={
            "status": "openai_image_ready",
            "slices": {
                "openai_image": {"ready": True},
                "grok_web_imagine": {"ready": False},
                "video": {"ready": False},
                "slack_delivery": {"ready": False},
                "full_media": {"ready": False},
            },
        },
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "llm_gate_schema_invalid" in report.slices["llm"]["blocking_reasons"]
    assert "llm_live_smoke_missing" in report.slices["llm"]["blocking_reasons"]
    assert "media_gate_schema_invalid" in report.slices["media_gate"]["blocking_reasons"]
    assert "openai_image_contract_unverified" in report.slices["media_gate"]["blocking_reasons"]


def test_release_candidate_gate_blocks_schema_shaped_llm_without_cases_or_smoke_details():
    llm_gate = _llm_gate()
    llm_gate["simulation"] = {"status": "passed", "cases": []}
    llm_gate["live_smoke"] = {
        "status": "passed",
        "provider": "unknown",
        "model": "unknown",
        "failure_layer": None,
        "evidence_refs": [],
    }

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=llm_gate,
        media_gate=_media_gate(),
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "llm_simulation_cases_incomplete" in report.slices["llm"]["blocking_reasons"]
    assert "llm_live_smoke_details_missing" in report.slices["llm"]["blocking_reasons"]


@pytest.mark.parametrize(
    "quality_score",
    [float("nan"), float("inf"), float("-inf"), "nan"],
)
def test_release_candidate_gate_blocks_non_finite_media_quality_score(quality_score):
    media_gate = _media_gate()
    media_gate["openai_image"]["quality_score"] = quality_score

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "openai_image_quality_below_threshold" in report.slices["media_gate"]["blocking_reasons"]


def test_release_candidate_gate_blocks_contradictory_openai_image_evidence():
    media_gate = _media_gate()
    media_gate["openai_image"]["status"] = "failed"
    media_gate["openai_image"]["provider"] = "grok"
    media_gate["openai_image"]["capability"] = "video"

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "openai_image_status_not_passed" in report.slices["media_gate"]["blocking_reasons"]
    assert "openai_image_wrong_provider_or_capability" in report.slices["media_gate"]["blocking_reasons"]


def test_release_candidate_gate_requires_evidence_ref_classes_not_just_count():
    media_gate = _media_gate()
    media_gate["openai_image"]["evidence_refs"] = [
        "generation:one",
        "generation:two",
        "generation:three",
        "generation:four",
        "generation:five",
        "generation:six",
    ]

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "openai_image_evidence_refs_incomplete" in report.slices["media_gate"]["blocking_reasons"]


def test_release_candidate_gate_accepts_canonical_underscore_quality_review_ref_class():
    media_gate = _media_gate()
    media_gate["openai_image"]["evidence_refs"] = [
        "generation:openai-image-1",
        "selection:openai-image-1",
        "freshness:phase7-session",
        "dedupe:openai-image-1",
        "geometry:1536x1024",
        "quality_review:openai-image-1",
    ]

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "release_candidate_ready"


def test_release_candidate_gate_blocks_stub_lifecycle_without_command_evidence():
    report = build_release_candidate_gate(
        lifecycle_gate={
            "install": True,
            "enable": True,
            "disable": True,
            "uninstall": True,
            "private_output_clean": True,
        },
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "lifecycle_schema_invalid" in report.slices["lifecycle"]["blocking_reasons"]
    assert "lifecycle_install_evidence_missing" in report.slices["lifecycle"]["blocking_reasons"]


@pytest.mark.parametrize(
    ("llm_claims", "media_claims", "expected_ref"),
    [
        (
            ["Grok Web Imagine readiness is verified."],
            None,
            "llm_gate:forbidden_claim:grok_web_imagine",
        ),
        (
            None,
            ["Video readiness is verified. Slack delivery readiness is confirmed."],
            "media_gate:forbidden_claim:video",
        ),
    ],
)
def test_release_candidate_gate_blocks_overclaims_inside_input_gate_claims(
    llm_claims,
    media_claims,
    expected_ref,
):
    llm_gate = _llm_gate()
    media_gate = _media_gate()
    if llm_claims is not None:
        llm_gate["public_claims"] = llm_claims
    if media_claims is not None:
        media_gate["public_claims"] = media_claims

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=llm_gate,
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert report.slices["gate_input_claims"]["ready"] is False
    assert "gate_input_claim_boundary_failed" in report.slices["gate_input_claims"]["blocking_reasons"]
    assert expected_ref in report.slices["gate_input_claims"]["evidence_refs"]


def test_release_candidate_gate_blocks_unreadable_requested_doc():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        doc_failures=("/private/tmp/missing-release-doc.md",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert report.slices["public_claims"]["ready"] is False
    assert "release_doc_unreadable:[redacted-path]" in report.slices["public_claims"]["blocking_reasons"]


def test_release_candidate_gate_rejects_contrastive_overclaim_wording():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(
            "Video was blocked before, but video readiness is approved. "
            "Do not worry, Grok Web Imagine is ready.",
        ),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:video" in report.slices["public_claims"]["evidence_refs"]
    assert "forbidden_claim:grok_web_imagine" in report.slices["public_claims"]["evidence_refs"]


def test_release_candidate_gate_rejects_unrelated_blocked_wording_before_overclaim():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("Grok remains blocked and video readiness is approved.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:video" in report.slices["public_claims"]["evidence_refs"]


def test_release_candidate_gate_rejects_leading_do_not_phrase_before_overclaim():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("Do not delay, Grok Web Imagine is ready.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:grok_web_imagine" in report.slices["public_claims"]["evidence_refs"]


def test_release_candidate_gate_rejects_unrelated_does_not_claim_before_overclaim():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("This report does not claim to be final, video readiness is approved.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:video" in report.slices["public_claims"]["evidence_refs"]


def test_release_candidate_gate_rejects_overclaim_after_scoped_negative_clause():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("Do not publish claims that Grok is ready, video readiness is approved.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:video" in report.slices["public_claims"]["evidence_refs"]


def test_release_candidate_gate_rejects_readiness_verified_complete_or_confirmed():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(
            "Grok Web Imagine readiness is verified. "
            "Video readiness is complete. "
            "Slack delivery readiness is confirmed. "
            "Full media readiness is verified.",
        ),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:grok_web_imagine" in report.slices["public_claims"]["evidence_refs"]
    assert "forbidden_claim:video" in report.slices["public_claims"]["evidence_refs"]
    assert "forbidden_claim:slack_delivery" in report.slices["public_claims"]["evidence_refs"]
    assert "forbidden_claim:full_media" in report.slices["public_claims"]["evidence_refs"]


@pytest.mark.parametrize(
    "doc_text",
    [
        "Video is not ready, Slack delivery readiness is approved.",
        "Grok remains blocked, video readiness is approved.",
        "Video readiness requires separate evidence, Slack delivery readiness is confirmed.",
        "No forbidden claim here, video readiness is approved.",
        "Video is not ready while Slack delivery readiness is approved.",
        "Grok remains blocked although video readiness is approved.",
        "Video readiness requires separate evidence while Slack delivery readiness is confirmed.",
        "Video is not ready despite Slack delivery readiness being approved.",
        "Video is not ready even as Slack delivery readiness is confirmed.",
        "Video is not ready notwithstanding Slack delivery readiness is approved.",
        "Grok remains blocked nevertheless video readiness is approved.",
        "Video readiness requires separate evidence nonetheless Slack delivery readiness is confirmed.",
    ],
)
def test_release_candidate_gate_rejects_overclaim_after_negative_clause_variants(doc_text):
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(doc_text,),
        now=NOW,
    )

    assert report.status == "blocked"
    assert report.slices["public_claims"]["ready"] is False


@pytest.mark.parametrize(
    "gate_claim",
    [
        "Video is not ready, Slack delivery readiness is approved.",
        "Grok remains blocked, video readiness is approved.",
        "Video readiness requires separate evidence, Slack delivery readiness is confirmed.",
        "No forbidden claim here, video readiness is approved.",
        "Video is not ready while Slack delivery readiness is approved.",
        "Grok remains blocked although video readiness is approved.",
        "Video readiness requires separate evidence while Slack delivery readiness is confirmed.",
        "Video is not ready despite Slack delivery readiness being approved.",
        "Video is not ready even as Slack delivery readiness is confirmed.",
        "Video is not ready notwithstanding Slack delivery readiness is approved.",
        "Grok remains blocked nevertheless video readiness is approved.",
        "Video readiness requires separate evidence nonetheless Slack delivery readiness is confirmed.",
    ],
)
def test_release_candidate_gate_rejects_input_overclaim_after_negative_clause_variants(
    gate_claim,
):
    media_gate = _media_gate(public_claims=[gate_claim])

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert report.slices["gate_input_claims"]["ready"] is False


@pytest.mark.parametrize(
    "doc_text",
    [
        "Grok evidence is unverified.",
        "Video readiness is incomplete.",
        "Grok Web Imagine readiness is unconfirmed.",
        "Video support is not enabled.",
        "Grok Web Imagine does not work.",
        "Full media is not shipping.",
        "Video support is not released.",
        "Grok Web Imagine is not launched.",
        "Video support is not in production.",
        "Grok Web Imagine is not public.",
        "Video support has not rolled out.",
        "Grok Web Imagine cannot be used.",
        "Slack delivery is not on by default.",
        "Users cannot use video generation.",
        "Video generation is not open to users.",
        "Users cannot generate video.",
        "Video generation is not accessible to users.",
        "Users do not have access to video generation.",
        "Users are not able to generate video.",
        "Grok Web Imagine cannot now generate images.",
        "Slack delivery cannot now upload media.",
    ],
)
def test_release_candidate_gate_allows_negative_prefix_words_without_ready_claim(doc_text):
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(doc_text,),
        now=NOW,
    )

    assert report.status == "release_candidate_ready"


@pytest.mark.parametrize(
    "doc_text",
    [
        "Documentation delivery is complete.",
        "Release notes delivery is complete.",
        "PR artifact delivery passed.",
    ],
)
def test_release_candidate_gate_allows_benign_non_slack_delivery_wording(doc_text):
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(doc_text,),
        now=NOW,
    )

    assert report.status == "release_candidate_ready"


def test_release_candidate_gate_allows_benign_non_slack_delivery_gate_input_wording():
    llm_gate = _llm_gate(public_claims=["Documentation delivery is complete."])

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=llm_gate,
        media_gate=_media_gate(),
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "release_candidate_ready"


def test_release_candidate_gate_blocks_slack_delivery_completion_claim():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("Slack delivery is complete.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:slack_delivery" in report.slices["public_claims"]["evidence_refs"]


def test_release_candidate_gate_allows_benign_imagine_documentation_wording():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("Imagine documentation is complete.",),
        now=NOW,
    )

    assert report.status == "release_candidate_ready"


def test_release_candidate_gate_allows_benign_imagine_gate_input_wording():
    llm_gate = _llm_gate(public_claims=["Imagine documentation is complete."])

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=llm_gate,
        media_gate=_media_gate(),
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "release_candidate_ready"


def test_release_candidate_gate_blocks_contextual_grok_imagine_completion_claim():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("Grok Imagine is complete.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:grok_web_imagine" in report.slices["public_claims"]["evidence_refs"]


@pytest.mark.parametrize(
    "doc_text",
    [
        "Grok documentation is complete.",
        "Video documentation is complete.",
        "Video tests passed.",
        "Media readiness documentation is complete.",
        "Grok docs are complete.",
        "Video tests are complete.",
    ],
)
def test_release_candidate_gate_allows_benign_capability_documentation_or_tests(doc_text):
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(doc_text,),
        now=NOW,
    )

    assert report.status == "release_candidate_ready"


def test_release_candidate_gate_allows_benign_capability_documentation_gate_input():
    llm_gate = _llm_gate(public_claims=["Grok docs are complete."])
    media_gate = _media_gate(public_claims=["Video tests are complete."])

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=llm_gate,
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "release_candidate_ready"


def test_release_candidate_gate_blocks_overclaim_after_benign_meta_completion():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("Grok docs are complete, video readiness is approved.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:video" in report.slices["public_claims"]["evidence_refs"]


def test_release_candidate_gate_still_blocks_video_readiness_completion_claim():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("Video readiness is complete.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:video" in report.slices["public_claims"]["evidence_refs"]


@pytest.mark.parametrize(
    "doc_text",
    [
        "Video is available.",
        "Slack delivery is available.",
        "Grok Web Imagine is available.",
        "Full media is available.",
        "Video is operational.",
        "Grok Web Imagine is live.",
    ],
)
def test_release_candidate_gate_blocks_direct_availability_or_live_claims(doc_text):
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(doc_text,),
        now=NOW,
    )

    assert report.status == "blocked"


@pytest.mark.parametrize(
    "doc_text",
    [
        "Video support is enabled.",
        "Slack delivery works.",
        "Full media support ships.",
        "Grok Web Imagine is shipping.",
    ],
)
def test_release_candidate_gate_blocks_capability_enabled_works_or_ships_claims(doc_text):
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(doc_text,),
        now=NOW,
    )

    assert report.status == "blocked"


@pytest.mark.parametrize(
    "doc_text",
    [
        "Video is supported.",
        "Slack delivery is supported.",
        "Grok Web Imagine is usable.",
        "Full media is functioning.",
        "Video support is active.",
        "Grok Web Imagine is activated.",
        "Video is turned on.",
    ],
)
def test_release_candidate_gate_blocks_support_or_usability_release_claims(doc_text):
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(doc_text,),
        now=NOW,
    )

    assert report.status == "blocked"


@pytest.mark.parametrize(
    "doc_text",
    [
        "Video support is GA.",
        "Full media support is released.",
        "Grok Web Imagine is launched.",
        "Video support is in production.",
        "Grok Web Imagine is public.",
        "Slack delivery is generally available.",
        "Video support is publicly available.",
        "Video support has rolled out.",
        "Grok Web Imagine can be used.",
        "Slack delivery is on by default.",
        "Users can use video generation.",
        "Users can use Grok Web Imagine.",
        "Video generation is open to users.",
        "Users can generate video.",
        "Users can create video.",
        "Users can produce video.",
        "Users can make video.",
        "Video generation is accessible to users.",
        "Users have access to video generation.",
        "Users are able to generate video.",
        "Grok Web Imagine can now generate images.",
        "Slack delivery can now upload media.",
    ],
)
def test_release_candidate_gate_blocks_release_marketing_claims(doc_text):
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=(doc_text,),
        now=NOW,
    )

    assert report.status == "blocked"


def test_release_candidate_gate_blocks_input_direct_availability_or_live_claims():
    llm_gate = _llm_gate(public_claims=["Grok Web Imagine is live."])
    media_gate = _media_gate(public_claims=["Video is available."])

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=llm_gate,
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "llm_gate:forbidden_claim:grok_web_imagine" in report.slices["gate_input_claims"]["evidence_refs"]
    assert "media_gate:forbidden_claim:video" in report.slices["gate_input_claims"]["evidence_refs"]


def test_release_candidate_gate_blocks_input_release_marketing_claims():
    llm_gate = _llm_gate(
        public_claims=[
            "Grok Web Imagine is launched.",
            "Grok Web Imagine can be used.",
            "Users can use Grok Web Imagine.",
        ]
    )
    media_gate = _media_gate(
        public_claims=[
            "Video support is in production.",
            "Slack delivery is on by default.",
            "Video generation is open to users.",
        ]
    )

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=llm_gate,
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "llm_gate:forbidden_claim:grok_web_imagine" in report.slices["gate_input_claims"]["evidence_refs"]
    assert "media_gate:forbidden_claim:video" in report.slices["gate_input_claims"]["evidence_refs"]
    assert "media_gate:forbidden_claim:slack_delivery" in report.slices["gate_input_claims"]["evidence_refs"]


def test_release_candidate_gate_blocks_input_active_voice_usage_claims():
    llm_gate = _llm_gate(
        public_claims=[
            "Users can use Grok Web Imagine.",
            "Grok Web Imagine can now generate images.",
        ]
    )
    media_gate = _media_gate(
        public_claims=[
            "Video generation is open to users.",
            "Users can generate video.",
            "Video generation is accessible to users.",
            "Users are able to generate video.",
            "Slack delivery can now upload media.",
        ]
    )

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=llm_gate,
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "llm_gate:forbidden_claim:grok_web_imagine" in report.slices["gate_input_claims"]["evidence_refs"]
    assert "media_gate:forbidden_claim:video" in report.slices["gate_input_claims"]["evidence_refs"]


def test_release_candidate_gate_blocks_input_support_or_usability_release_claims():
    llm_gate = _llm_gate(public_claims=["Grok Web Imagine is usable."])
    media_gate = _media_gate(public_claims=["Video is supported."])

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=llm_gate,
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "llm_gate:forbidden_claim:grok_web_imagine" in report.slices["gate_input_claims"]["evidence_refs"]
    assert "media_gate:forbidden_claim:video" in report.slices["gate_input_claims"]["evidence_refs"]


def test_release_candidate_gate_blocks_input_enabled_or_works_claims():
    llm_gate = _llm_gate(public_claims=["Grok Web Imagine is enabled."])
    media_gate = _media_gate(public_claims=["Video generation works."])

    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=llm_gate,
        media_gate=media_gate,
        doc_texts=("OpenAI image is ready; video remains blocked.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "llm_gate:forbidden_claim:grok_web_imagine" in report.slices["gate_input_claims"]["evidence_refs"]
    assert "media_gate:forbidden_claim:video" in report.slices["gate_input_claims"]["evidence_refs"]


def test_release_candidate_gate_blocks_capability_claim_after_benign_meta_completion():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("Video tests are complete, Slack delivery works.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:slack_delivery" in report.slices["public_claims"]["evidence_refs"]


def test_release_candidate_gate_allows_meta_support_claim_but_blocks_later_capability_claim():
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(),
        llm_gate=_llm_gate(),
        media_gate=_media_gate(),
        doc_texts=("Video documentation support is active, Slack delivery is usable.",),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "forbidden_claim:slack_delivery" in report.slices["public_claims"]["evidence_refs"]
    assert "forbidden_claim:video" not in report.slices["public_claims"]["evidence_refs"]


def test_release_candidate_gate_json_and_render_are_privacy_safe(tmp_path):
    report = build_release_candidate_gate(
        lifecycle_gate=_lifecycle_gate(
            checks={
                "install": {
                    "exit_code": 0,
                    "evidence_ref": "/private/tmp/lifecycle.log sk-test-secret",
                },
                "enable": {
                    "exit_code": 0,
                    "evidence_ref": "base64:lifecycle xoxb-secret",
                },
                "disable": {"exit_code": 0, "evidence_ref": "lifecycle:disable"},
                "uninstall": {"exit_code": 0, "evidence_ref": "lifecycle:uninstall"},
            }
        ),
        llm_gate=_llm_gate(
            public_claims=["/private/tmp/llm base64:claim sk-test-secret"]
        ),
        media_gate=_media_gate(
            public_claims=["/private/tmp/media base64:claim xoxb-secret"],
        ),
        doc_texts=("OpenAI image ready. /private/tmp/doc base64:secret sk-test-secret",),
        now=NOW,
    )
    output_path = tmp_path / "raphael-release-candidate.json"

    write_release_candidate_gate(report, output_path)

    payload_text = output_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    rendered = render_release_candidate_gate(report)

    assert payload["schema_version"] == "raphael.release_candidate.v1"
    assert "/private/tmp" not in payload_text
    assert "base64" not in payload_text
    assert "sk-test-secret" not in payload_text
    assert "xoxb-secret" not in payload_text
    assert "/private/tmp" not in rendered
    assert "base64" not in rendered
    assert "sk-test-secret" not in rendered
    assert "xoxb-secret" not in rendered
