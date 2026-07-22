from __future__ import annotations

import json


def _pass_check() -> dict:
    return {"status": "pass"}


def _wow_check() -> dict:
    cases = (
        "standby_summon",
        "vague_takeover_preserves_mission",
        "runtime_log_attachment_routes_tool_task",
        "blank_screen_repair_routes_tool_task",
        "prompt_builder_question_not_prompt_disclosure",
        "negated_media_summon_stays_text_only",
    )
    return {
        "status": "pass",
        "user_simulation_cases": [
            {
                "case": case,
                "status": "pass",
                "visual_quota_used": False,
                "user_prompt": f"user prompt for {case}",
                "expected_visible_behavior": f"expected behavior for {case}",
                "critical_assertions": [
                    f"{case}_assertion_1",
                    f"{case}_assertion_2",
                ],
                "evidence": f"{case} verified",
                "next_action": f"next action for {case}",
                "proof_layer": "runtime_smoke",
            }
            for case in cases
        ],
    }


def _llm_ready() -> dict:
    return {
        "profile": "llm",
        "release_state": "ready_for_llm_only_release",
        "public_release_ready": True,
        "public_claim_scope": "llm_only",
        "checks": {
            "install_disable_uninstall": _pass_check(),
            "package_install_smoke": _pass_check(),
            "slash_command_surface": _pass_check(),
            "mode_router_contract": _pass_check(),
            "goal_state_contract": _pass_check(),
            "evolution_contract": _pass_check(),
            "llm_live_smoke": _pass_check(),
            "hostile_review": {
                "status": "pass",
                "llm_ux_claims": {
                    "sage_king_claim_allowed": False,
                    "wow_claim_allowed": False,
                    "big_evolution_claim_allowed": False,
                },
            },
            "non_visual_regression": _pass_check(),
            "release_docs_audit": _pass_check(),
            "wow_experience": _wow_check(),
        },
    }


def _media_limited() -> dict:
    return {
        "profile": "media",
        "release_state": "ready_for_limited_media_public_release",
        "limited_media_release_ready": True,
        "full_media_release_ready": False,
        "public_release_ready": "limited",
        "public_claim_scope": "media_openai_image_only",
        "media_release_scope": "media_openai_image_only",
        "remaining_media_gaps": ["xai_grok_generation", "video_generation"],
        "verified_media_capabilities": ["openai_image_generation"],
        "checks": {
            "visual_live_e2e": _pass_check(),
            "hostile_review": {
                "status": "pass",
                "llm_ux_claims": {
                    "sage_king_claim_allowed": False,
                    "wow_claim_allowed": False,
                    "big_evolution_claim_allowed": False,
                },
            },
            "release_docs_audit": _pass_check(),
        },
    }


def _media_limited_with_capability_records() -> dict:
    media = _media_limited()
    media["verified_media_capabilities"] = [
        {
            "capability_id": "openai_image_generation",
            "status": "verified",
            "public_slice_ready": True,
        }
    ]
    return media


def _media_full_ready() -> dict:
    media = _media_limited()
    media.update(
        {
            "release_state": "ready_for_public_release",
            "limited_media_release_ready": True,
            "full_media_release_ready": True,
            "public_release_ready": True,
            "public_claim_scope": "full_media",
            "media_release_scope": "full_media",
            "remaining_media_gaps": [],
            "verified_media_capabilities": [
                "openai_image_generation",
                "xai_grok_generation",
                "video_generation",
            ],
        }
    )
    media["checks"]["hostile_review"]["llm_ux_claims"] = {
        "sage_king_claim_allowed": True,
        "wow_claim_allowed": True,
        "big_evolution_claim_allowed": True,
    }
    return media


def test_completion_audit_allows_scoped_release_but_blocks_ultimate_claims():
    from scripts.raphael_completion_audit import audit_completion

    result = audit_completion(
        llm_readiness=_llm_ready(),
        media_readiness=_media_limited(),
        boundary_summary={
            "unclassified_paths": [],
            "content_violations": [],
            "deferred_media_paths": ["agent/visual/foo.py"],
        },
    )

    assert result.scoped_release_ready is True
    assert result.ultimate_ready is False
    assert result.status == "partial"
    assert "ultimate_claim:sage_king_denied" in result.blockers
    assert "ultimate_claim:wow_denied" in result.blockers
    assert "ultimate_claim:big_evolution_denied" in result.blockers
    assert "full_media:xai_grok_generation_missing" in result.blockers
    assert "full_media:video_generation_missing" in result.blockers


def test_completion_audit_does_not_trust_release_state_without_required_checks():
    from scripts.raphael_completion_audit import audit_completion

    llm = _llm_ready()
    llm["checks"].pop("release_docs_audit")

    result = audit_completion(
        llm_readiness=llm,
        media_readiness=_media_full_ready(),
        boundary_summary={"unclassified_paths": [], "content_violations": []},
    )

    assert result.scoped_release_ready is False
    assert result.ultimate_ready is False
    assert "llm:release_docs_audit_missing_or_not_pass" in result.blockers


def test_completion_audit_requires_clean_boundary_for_scoped_release():
    from scripts.raphael_completion_audit import audit_completion

    result = audit_completion(
        llm_readiness=_llm_ready(),
        media_readiness=_media_limited(),
        boundary_summary={
            "unclassified_paths": ["unknown.py"],
            "content_violations": ["agent/raphael/foo.py imports agent.visual"],
        },
    )

    assert result.scoped_release_ready is False
    assert result.ultimate_ready is False
    assert "boundary:unclassified_paths" in result.blockers
    assert "boundary:content_violations" in result.blockers


def test_completion_audit_marks_ultimate_ready_only_with_full_media_and_claims():
    from scripts.raphael_completion_audit import audit_completion

    llm = _llm_ready()
    llm["checks"]["hostile_review"]["llm_ux_claims"] = {
        "sage_king_claim_allowed": True,
        "wow_claim_allowed": True,
        "big_evolution_claim_allowed": True,
    }

    result = audit_completion(
        llm_readiness=llm,
        media_readiness=_media_full_ready(),
        boundary_summary={"unclassified_paths": [], "content_violations": []},
    )

    assert result.scoped_release_ready is True
    assert result.ultimate_ready is True
    assert result.status == "ready"
    assert result.blockers == ()


def test_completion_audit_cli_scoped_target_exits_zero_for_limited_release(tmp_path, capsys):
    from scripts.raphael_completion_audit import main

    llm_path = tmp_path / "llm.json"
    media_path = tmp_path / "media.json"
    llm_path.write_text(json.dumps(_llm_ready()), encoding="utf-8")
    media_path.write_text(json.dumps(_media_limited()), encoding="utf-8")

    exit_code = main(
        [
            "--target",
            "scoped",
            "--llm-readiness",
            str(llm_path),
            "--media-readiness",
            str(media_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Scoped release ready: yes" in output
    assert "Ultimate Sage King ready: no" in output


def test_completion_audit_cli_default_target_exits_nonzero_for_limited_release(
    tmp_path, capsys
):
    from scripts.raphael_completion_audit import main

    llm_path = tmp_path / "llm.json"
    media_path = tmp_path / "media.json"
    llm_path.write_text(json.dumps(_llm_ready()), encoding="utf-8")
    media_path.write_text(json.dumps(_media_limited()), encoding="utf-8")

    exit_code = main(
        [
            "--llm-readiness",
            str(llm_path),
            "--media-readiness",
            str(media_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Ultimate Sage King ready: no" in output


def test_completion_audit_reports_progress_layers_for_sage_king_gap():
    from scripts.raphael_completion_audit import audit_completion

    result = audit_completion(
        llm_readiness=_llm_ready(),
        media_readiness=_media_limited(),
        boundary_summary={"unclassified_paths": [], "content_violations": []},
    )

    assert 50 <= result.progress_percent < 100
    progress_by_layer = {layer["id"]: layer for layer in result.progress_layers}
    assert progress_by_layer["intent_mode_routing"]["percent"] >= 80
    assert progress_by_layer["visual_coordination"]["percent"] < 70
    assert "xai_grok_generation" in progress_by_layer["visual_coordination"]["gaps"]
    assert "video_generation" in progress_by_layer["visual_coordination"]["gaps"]
    assert progress_by_layer["summon_wow_ux"]["percent"] == 80
    assert "full_wow_claim_not_allowed" in progress_by_layer["summon_wow_ux"]["gaps"]


def test_completion_audit_counts_reviewable_llm_wow_matrix_separately_from_full_wow_claim():
    from scripts.raphael_completion_audit import audit_completion

    result = audit_completion(
        llm_readiness=_llm_ready(),
        media_readiness=_media_limited(),
        boundary_summary={"unclassified_paths": [], "content_violations": []},
    )

    progress_by_layer = {layer["id"]: layer for layer in result.progress_layers}
    assert progress_by_layer["summon_wow_ux"]["percent"] == 80
    assert progress_by_layer["summon_wow_ux"]["evidence"] == (
        "wow_experience",
        "reviewable_user_simulation_matrix",
    )
    assert progress_by_layer["summon_wow_ux"]["gaps"] == (
        "full_wow_claim_not_allowed",
    )
    assert "ultimate_claim:wow_denied" in result.blockers


def test_completion_audit_keeps_summon_wow_lower_without_reviewable_matrix():
    from scripts.raphael_completion_audit import audit_completion

    llm = _llm_ready()
    llm["checks"]["wow_experience"] = _pass_check()

    result = audit_completion(
        llm_readiness=llm,
        media_readiness=_media_limited(),
        boundary_summary={"unclassified_paths": [], "content_violations": []},
    )

    progress_by_layer = {layer["id"]: layer for layer in result.progress_layers}
    assert progress_by_layer["summon_wow_ux"]["percent"] == 50
    assert "reviewable_user_simulation_matrix_missing" in progress_by_layer[
        "summon_wow_ux"
    ]["gaps"]


def test_completion_audit_reads_capability_records_and_layer_gaps():
    from scripts.raphael_completion_audit import audit_completion

    result = audit_completion(
        llm_readiness=_llm_ready(),
        media_readiness=_media_limited_with_capability_records(),
        boundary_summary={"unclassified_paths": [], "content_violations": []},
    )

    progress_by_layer = {layer["id"]: layer for layer in result.progress_layers}
    assert "openai_image_generation" in progress_by_layer["visual_coordination"][
        "evidence"
    ]
    assert progress_by_layer["visual_coordination"]["gaps"] == (
        "video_generation",
        "xai_grok_generation",
    )


def test_completion_audit_progress_reaches_ultimate_only_with_full_claims():
    from scripts.raphael_completion_audit import audit_completion

    llm = _llm_ready()
    llm["checks"]["hostile_review"]["llm_ux_claims"] = {
        "sage_king_claim_allowed": True,
        "wow_claim_allowed": True,
        "big_evolution_claim_allowed": True,
    }

    result = audit_completion(
        llm_readiness=llm,
        media_readiness=_media_full_ready(),
        boundary_summary={"unclassified_paths": [], "content_violations": []},
    )

    assert result.ultimate_ready is True
    assert result.progress_percent == 100
    assert all(layer["percent"] == 100 for layer in result.progress_layers)


def test_completion_audit_cli_prints_progress_as_non_release_evidence(
    tmp_path, capsys
):
    from scripts.raphael_completion_audit import main

    llm_path = tmp_path / "llm.json"
    media_path = tmp_path / "media.json"
    llm_path.write_text(json.dumps(_llm_ready()), encoding="utf-8")
    media_path.write_text(json.dumps(_media_limited()), encoding="utf-8")

    exit_code = main(
        [
            "--llm-readiness",
            str(llm_path),
            "--media-readiness",
            str(media_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Progress estimate: " in output
    assert "not release evidence" in output
    assert (
        "- visual_coordination: 55% "
        "(gaps: video_generation, xai_grok_generation)"
    ) in output
    assert "xai_grok_generation" in output
    assert "video_generation" in output
