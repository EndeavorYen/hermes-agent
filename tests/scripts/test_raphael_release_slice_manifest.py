from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _pass_check() -> dict:
    return {"status": "pass"}


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
            "wow_experience": _pass_check(),
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


def test_release_slice_manifest_splits_llm_and_deferred_media_paths():
    from scripts.raphael_release_slice_manifest import build_release_slice_manifest

    manifest = build_release_slice_manifest(
        [
            "agent/raphael/control.py",
            "scripts/raphael_completion_audit.py",
            "agent/visual/agent_mode/handoff.py",
            "plugins/image_gen/grok_web_imagine/__init__.py",
        ],
        llm_readiness=_llm_ready(),
        media_readiness=_media_limited(),
    )

    assert manifest["status"] == "reviewable"
    assert manifest["review_strategy"] == "split_required"
    assert manifest["allowed_public_claims"] == ["llm_only"]
    assert manifest["blocked_public_claims"] == [
        "sage_king",
        "wow",
        "big_evolution",
        "full_media",
        "xai_grok_generation",
        "video_generation",
    ]
    assert manifest["counts"] == {
        "llm_slice_paths": 2,
        "deferred_media_paths": 2,
        "unclassified_paths": 0,
        "content_violations": 0,
    }
    assert manifest["slices"][0]["id"] == "llm_scoped_release"
    assert manifest["slices"][0]["release_ready"] is True
    assert manifest["slices"][0]["paths"] == [
        "agent/raphael/control.py",
        "scripts/raphael_completion_audit.py",
    ]
    assert manifest["slices"][1]["id"] == "deferred_media"
    assert manifest["slices"][1]["release_ready"] is False
    assert manifest["slices"][1]["paths"] == [
        "agent/visual/agent_mode/handoff.py",
        "plugins/image_gen/grok_web_imagine/__init__.py",
    ]


def test_release_slice_manifest_blocks_unclassified_paths():
    from scripts.raphael_release_slice_manifest import build_release_slice_manifest

    manifest = build_release_slice_manifest(
        ["agent/raphael/control.py", "unknown/new_surface.py"],
        llm_readiness=_llm_ready(),
        media_readiness=_media_limited(),
    )

    assert manifest["status"] == "blocked"
    assert manifest["review_strategy"] == "classify_or_remove_unknown_paths"
    assert manifest["counts"]["unclassified_paths"] == 1
    assert manifest["blockers"] == ["boundary:unclassified_paths"]


def test_release_slice_manifest_blocks_when_scoped_completion_not_ready():
    from scripts.raphael_release_slice_manifest import build_release_slice_manifest

    llm = _llm_ready()
    llm["checks"].pop("release_docs_audit")

    manifest = build_release_slice_manifest(
        ["agent/raphael/control.py"],
        llm_readiness=llm,
        media_readiness=_media_limited(),
    )

    assert manifest["status"] == "blocked"
    assert manifest["slices"][0]["release_ready"] is False
    assert "llm:release_docs_audit_missing_or_not_pass" in manifest["blockers"]


def test_release_slice_manifest_outputs_stable_required_commands():
    from scripts.raphael_release_slice_manifest import build_release_slice_manifest

    manifest = build_release_slice_manifest(
        ["agent/raphael/control.py"],
        llm_readiness=_llm_ready(),
        media_readiness=_media_limited(),
    )

    assert manifest["required_commands"] == [
        "venv/bin/python scripts/raphael_completion_audit.py --target scoped",
        "venv/bin/python scripts/raphael_release_docs_audit.py",
        "venv/bin/python scripts/raphael_release_slice_boundary.py --profile llm --from-git-status",
        "venv/bin/python -m pytest tests/scripts/test_raphael_release_slice_manifest.py tests/scripts/test_raphael_completion_audit.py tests/scripts/test_raphael_release_slice_boundary.py -q",
        "venv/bin/ruff check scripts/raphael_release_slice_manifest.py tests/scripts/test_raphael_release_slice_manifest.py",
        "git diff --check",
    ]


def test_release_slice_manifest_cli_runs_as_script_path(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    llm_path = tmp_path / "llm.json"
    media_path = tmp_path / "media.json"
    llm_path.write_text(json.dumps(_llm_ready()), encoding="utf-8")
    media_path.write_text(json.dumps(_media_limited()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/raphael_release_slice_manifest.py",
            "--llm-readiness",
            str(llm_path),
            "--media-readiness",
            str(media_path),
            "agent/raphael/control.py",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "reviewable"
    assert payload["review_strategy"] == "single_llm_slice"
