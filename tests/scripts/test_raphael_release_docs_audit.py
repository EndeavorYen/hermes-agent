from __future__ import annotations

from pathlib import Path


def _llm_readiness() -> dict:
    return {
        "profile": "llm",
        "release_state": "ready_for_llm_only_release",
        "public_claim_scope": "llm_only",
        "public_claim_exclusions": [
            "media",
            "Grok",
            "video",
            "full Sage King",
        ],
        "checks": {
            "llm_live_smoke": {"session_id": "llm-session-1"},
            "package_install_smoke": {"run_id": "package-install-1"},
            "hostile_review": {"run_id": "hostile-review-1"},
            "non_visual_regression": {
                "run_id": "non-visual-llm-1",
                "passed_count": 1529,
            },
        },
    }


def _media_readiness() -> dict:
    return {
        "profile": "media",
        "release_state": "ready_for_limited_media_public_release",
        "media_release_scope": "media_openai_image_only",
        "public_claim_scope": "media_openai_image_only",
        "public_claim_exclusions": ["xai_grok_generation", "video_generation"],
        "remaining_media_gaps": ["xai_grok_generation", "video_generation"],
        "verified_media_capabilities": ["openai_image_generation"],
        "checks": {
            "llm_live_smoke": {"session_id": "media-session-1"},
            "package_install_smoke": {"run_id": "package-install-1"},
            "hostile_review": {"run_id": "hostile-review-1"},
            "non_visual_regression": {
                "run_id": "non-visual-media-1",
                "passed_count": 1541,
            },
        },
    }


def test_raphael_release_docs_audit_accepts_scoped_current_claims():
    from scripts.raphael_release_docs_audit import audit_release_docs

    release_audit_doc = """
    LLM-only public slice: ready_for_llm_only_release.
    Public claim scope: llm_only.
    Package install package-install-1 and hostile review hostile-review-1.
    LLM smoke llm-session-1 and non-visual non-visual-llm-1 records 1529 passing tests.
    Current media-profile evidence: media-session-1 and non-visual-media-1 records 1541 passing tests.
    OpenAI image-only media slice: ready_for_limited_media_public_release with scope media_openai_image_only.
    Verified media capabilities: openai_image_generation.
    Full media gaps: xai_grok_generation and video_generation.
    Raphael completion audit: partial.
    Ultimate Sage King ready: no.
    Raphael release slice manifest records split_required review strategy.
    This boundary summary is local review evidence, not a field in the readiness JSON.
    User simulation matrix requires user_prompt, expected_visible_behavior, critical_assertions,
    next_action, proof_layer, and visual_quota_used:false.
    Public wording must stay limited to the current gate state, scope, and explicit exclusions.
    """
    llm_slice_doc = """
    This is an LLM-only public slice.
    Release scope: llm_only.
    Package install package-install-1 and hostile review hostile-review-1.
    LLM-only live summon smoke llm-session-1.
    non-visual-llm-1 records 1529 passing tests.
    Boundary summary is local review evidence, not a field in the readiness JSON.
    User simulation matrix requires user_prompt, expected_visible_behavior, critical_assertions,
    next_action, proof_layer, and visual_quota_used:false.
    It does not prove default Grok, xAI, video, or full image-first media readiness.
    """

    result = audit_release_docs(
        release_audit_doc=release_audit_doc,
        llm_slice_doc=llm_slice_doc,
        llm_readiness=_llm_readiness(),
        media_readiness=_media_readiness(),
    )

    assert result.ready is True
    assert result.violations == ()


def test_repository_release_docs_do_not_describe_historical_evidence_as_current():
    root = Path(__file__).resolve().parents[2]
    texts = {
        path.name: path.read_text(encoding="utf-8")
        for path in (
            root / "docs" / "raphael-llm-public-slice.md",
            root / "docs" / "raphael-release-slice-audit.md",
        )
    }

    for name, text in texts.items():
        lowered = text.lower()
        assert "current live evidence" not in lowered, name
        assert "currently passes" not in lowered, name
        assert "fresh llm live smoke `20260701" not in lowered, name
        assert "fresh media-profile llm smoke `20260701" not in lowered, name


def test_raphael_release_docs_audit_rejects_grok_overclaim_for_openai_scope():
    from scripts.raphael_release_docs_audit import audit_release_docs

    result = audit_release_docs(
        release_audit_doc=(
            "Visual routing routes image/video tasks to Grok visual mode. "
            "Media provider evidence: Grok preflight now."
        ),
        llm_slice_doc="Release scope: llm_only.",
        llm_readiness=_llm_readiness(),
        media_readiness=_media_readiness(),
    )

    assert result.ready is False
    assert "release_audit_doc:grok_ready_overclaim" in result.violations


def test_raphael_release_docs_audit_rejects_mixed_media_evidence_identity():
    from scripts.raphael_release_docs_audit import audit_release_docs

    release_audit_doc = """
    LLM smoke llm-session-1 and non-visual non-visual-llm-1 records 1529 passing tests.
    OpenAI image-only media slice: ready_for_limited_media_public_release with scope media_openai_image_only.
    Full media gaps: xai_grok_generation and video_generation.
    Boundary summary is local review evidence, not a field in the readiness JSON.
    """

    result = audit_release_docs(
        release_audit_doc=release_audit_doc,
        llm_slice_doc="Release scope: llm_only. llm-session-1 non-visual-llm-1 1529",
        llm_readiness=_llm_readiness(),
        media_readiness=_media_readiness(),
    )

    assert result.ready is False
    assert "release_audit_doc:media_profile_evidence_missing" in result.violations


def test_raphael_release_docs_audit_rejects_percentage_release_evidence():
    from scripts.raphael_release_docs_audit import audit_release_docs

    result = audit_release_docs(
        release_audit_doc="Overall Raphael target: about `71%`.",
        llm_slice_doc="LLM-only public slice: about `93%`.",
        llm_readiness=_llm_readiness(),
        media_readiness=_media_readiness(),
    )

    assert result.ready is False
    assert "release_audit_doc:percentage_release_evidence" in result.violations
    assert "llm_slice_doc:percentage_release_evidence" in result.violations


def test_raphael_release_docs_audit_rejects_missing_reviewable_wow_matrix_fields():
    from scripts.raphael_release_docs_audit import audit_release_docs

    release_audit_doc = """
    LLM-only public slice: ready_for_llm_only_release.
    Package install package-install-1 and hostile review hostile-review-1.
    LLM smoke llm-session-1 and non-visual non-visual-llm-1 records 1529 passing tests.
    Current media-profile evidence: media-session-1 and non-visual-media-1 records 1541 passing tests.
    OpenAI image-only media slice: ready_for_limited_media_public_release with scope media_openai_image_only.
    Full media gaps: xai_grok_generation and video_generation.
    Raphael completion audit: partial.
    Ultimate Sage King ready: no.
    Raphael release slice manifest records split_required review strategy.
    This boundary summary is local review evidence, not a field in the readiness JSON.
    User simulation matrix requires next_action, proof_layer, and visual_quota_used:false.
    """
    llm_slice_doc = """
    Release scope: llm_only.
    Package install package-install-1 and hostile review hostile-review-1.
    LLM-only live summon smoke llm-session-1.
    non-visual-llm-1 records 1529 passing tests.
    Boundary summary is local review evidence, not a field in the readiness JSON.
    It does not prove default Grok, xAI, video, or full image-first media readiness.
    User simulation matrix requires next_action, proof_layer, and visual_quota_used:false.
    """

    result = audit_release_docs(
        release_audit_doc=release_audit_doc,
        llm_slice_doc=llm_slice_doc,
        llm_readiness=_llm_readiness(),
        media_readiness=_media_readiness(),
    )

    assert result.ready is False
    assert "release_audit_doc:wow_matrix_fields_missing" in result.violations
    assert "llm_slice_doc:wow_matrix_fields_missing" in result.violations


def test_raphael_release_docs_audit_rejects_stale_package_install_evidence():
    from scripts.raphael_release_docs_audit import audit_release_docs

    release_audit_doc = """
    Package install package-install-old.
    Hostile review hostile-review-1.
    Current media-profile evidence: media-session-1 and non-visual-media-1 records 1541 passing tests.
    OpenAI image-only media slice: scope media_openai_image_only.
    Full media gaps: xai_grok_generation and video_generation.
    """
    llm_slice_doc = """
    Release scope: llm_only.
    Package install package-install-old.
    Hostile review hostile-review-1.
    LLM-only live summon smoke llm-session-1.
    non-visual-llm-1 records 1529 passing tests.
    It does not prove default Grok, xAI, video, or full image-first media readiness.
    """

    result = audit_release_docs(
        release_audit_doc=release_audit_doc,
        llm_slice_doc=llm_slice_doc,
        llm_readiness=_llm_readiness(),
        media_readiness=_media_readiness(),
    )

    assert result.ready is False
    assert "release_audit_doc:package_install_evidence_missing" in result.violations
    assert "llm_slice_doc:package_install_evidence_missing" in result.violations


def test_raphael_release_docs_audit_rejects_stale_hostile_review_evidence():
    from scripts.raphael_release_docs_audit import audit_release_docs

    release_audit_doc = """
    Package install package-install-1.
    Hostile review hostile-review-old.
    Current media-profile evidence: media-session-1 and non-visual-media-1 records 1541 passing tests.
    OpenAI image-only media slice: scope media_openai_image_only.
    Full media gaps: xai_grok_generation and video_generation.
    """
    llm_slice_doc = """
    Release scope: llm_only.
    Package install package-install-1.
    Hostile review hostile-review-old.
    LLM-only live summon smoke llm-session-1.
    non-visual-llm-1 records 1529 passing tests.
    It does not prove default Grok, xAI, video, or full image-first media readiness.
    """

    result = audit_release_docs(
        release_audit_doc=release_audit_doc,
        llm_slice_doc=llm_slice_doc,
        llm_readiness=_llm_readiness(),
        media_readiness=_media_readiness(),
    )

    assert result.ready is False
    assert "release_audit_doc:hostile_review_evidence_missing" in result.violations
    assert "llm_slice_doc:hostile_review_evidence_missing" in result.violations


def test_raphael_release_docs_audit_rejects_missing_completion_audit():
    from scripts.raphael_release_docs_audit import audit_release_docs

    release_audit_doc = """
    Package install package-install-1.
    Hostile review hostile-review-1.
    Current media-profile evidence: media-session-1 and non-visual-media-1 records 1541 passing tests.
    OpenAI image-only media slice: scope media_openai_image_only.
    Full media gaps: xai_grok_generation and video_generation.
    """
    llm_slice_doc = """
    Release scope: llm_only.
    Package install package-install-1.
    Hostile review hostile-review-1.
    LLM-only live summon smoke llm-session-1.
    non-visual-llm-1 records 1529 passing tests.
    It does not prove default Grok, xAI, video, or full image-first media readiness.
    """

    result = audit_release_docs(
        release_audit_doc=release_audit_doc,
        llm_slice_doc=llm_slice_doc,
        llm_readiness=_llm_readiness(),
        media_readiness=_media_readiness(),
    )

    assert result.ready is False
    assert "release_audit_doc:completion_audit_missing" in result.violations


def test_raphael_release_docs_audit_rejects_missing_slice_manifest_boundary():
    from scripts.raphael_release_docs_audit import audit_release_docs

    release_audit_doc = """
    Package install package-install-1.
    Hostile review hostile-review-1.
    Raphael completion audit: partial.
    Ultimate Sage King ready: no.
    Current media-profile evidence: media-session-1 and non-visual-media-1 records 1541 passing tests.
    OpenAI image-only media slice: scope media_openai_image_only.
    Full media gaps: xai_grok_generation and video_generation.
    """
    llm_slice_doc = """
    Release scope: llm_only.
    Package install package-install-1.
    Hostile review hostile-review-1.
    LLM-only live summon smoke llm-session-1.
    non-visual-llm-1 records 1529 passing tests.
    It does not prove default Grok, xAI, video, or full image-first media readiness.
    """

    result = audit_release_docs(
        release_audit_doc=release_audit_doc,
        llm_slice_doc=llm_slice_doc,
        llm_readiness=_llm_readiness(),
        media_readiness=_media_readiness(),
    )

    assert result.ready is False
    assert "release_audit_doc:slice_manifest_missing" in result.violations
