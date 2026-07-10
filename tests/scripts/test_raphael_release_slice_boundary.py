from __future__ import annotations

import pytest


def test_raphael_llm_slice_boundary_classifies_changed_paths():
    from scripts import raphael_release_slice_boundary as boundary

    result = boundary.classify_paths(
        [
            "agent/raphael/control.py",
            ".github/workflows/tests.yml",
            "agent/conversation_loop.py",
            "docs/plans/2026-07-05-raphael-learning-absorption-plan.md",
            "hermes_cli/raphael_cmd.py",
            "hermes_cli/raphael_lifecycle.py",
            "scripts/release.py",
            "scripts/raphael_completion_audit.py",
            "scripts/raphael_package_install_smoke.py",
            "scripts/raphael_release_slice_manifest.py",
            "tests/cli/test_cli_save_config_value.py",
            "tests/scripts/test_raphael_completion_audit.py",
            "tests/scripts/test_raphael_release_slice_manifest.py",
            "tests/test_tui_gateway_server.py",
            "utils.py",
            "plugins/image_gen/grok_web_imagine/__init__.py",
            "scripts/visual_live_provider_e2e.py",
            "tests/scripts/test_visual_live_provider_e2e.py",
            "agent/visual/agent_mode/handoff.py",
            "tools/visual_package_tool.py",
        ],
        profile="llm",
    )

    assert result.unclassified == (
        ".github/workflows/tests.yml",
        "agent/conversation_loop.py",
        "docs/plans/2026-07-05-raphael-learning-absorption-plan.md",
        "scripts/release.py",
        "tests/cli/test_cli_save_config_value.py",
        "tests/test_tui_gateway_server.py",
        "utils.py",
    )
    assert "agent/raphael/control.py" in result.included
    assert "hermes_cli/raphael_cmd.py" in result.included
    assert "hermes_cli/raphael_lifecycle.py" in result.included
    assert "scripts/raphael_completion_audit.py" in result.included
    assert "scripts/raphael_package_install_smoke.py" in result.included
    assert "scripts/raphael_release_slice_manifest.py" in result.included
    assert "tests/scripts/test_raphael_completion_audit.py" in result.included
    assert "tests/scripts/test_raphael_release_slice_manifest.py" in result.included
    assert "plugins/image_gen/grok_web_imagine/__init__.py" in result.deferred_media
    assert "scripts/visual_live_provider_e2e.py" in result.deferred_media
    assert "tests/scripts/test_visual_live_provider_e2e.py" in result.deferred_media
    assert "agent/visual/agent_mode/handoff.py" in result.deferred_media
    assert "tools/visual_package_tool.py" in result.deferred_media


def test_source_and_packaged_boundary_policy_are_identical():
    from hermes_cli.release_evidence.raphael import (
        raphael_release_slice_boundary as packaged,
    )
    from scripts import raphael_release_slice_boundary as source

    paths = [
        "agent/raphael/control.py",
        "hermes_cli/raphael_lifecycle.py",
        ".github/workflows/tests.yml",
        "scripts/release.py",
        "scripts/openai_visual_live_e2e.py",
    ]

    assert source.LLM_INCLUDE_PREFIXES == packaged.LLM_INCLUDE_PREFIXES
    assert source.LLM_DEFERRED_MEDIA_PREFIXES == packaged.LLM_DEFERRED_MEDIA_PREFIXES
    assert source.STRICT_CONTENT_BOUNDARY_PREFIXES == (
        packaged.STRICT_CONTENT_BOUNDARY_PREFIXES
    )
    assert source.classify_paths(paths) == packaged.classify_paths(paths)


def test_raphael_llm_slice_boundary_flags_unclassified_paths():
    from scripts import raphael_release_slice_boundary as boundary

    result = boundary.classify_paths(
        [
            "agent/raphael/control.py",
            "some/new_surface.py",
        ],
        profile="llm",
    )

    assert result.ready is False
    assert result.unclassified == ("some/new_surface.py",)
    assert result.included == ("agent/raphael/control.py",)


def test_raphael_llm_slice_boundary_flags_deferred_imports(tmp_path):
    from scripts import raphael_release_slice_boundary as boundary

    source = tmp_path / "agent" / "raphael"
    source.mkdir(parents=True)
    (source / "control.py").write_text(
        "from agent.visual.agent_mode.planner import plan_visual_agent_request\n",
        encoding="utf-8",
    )

    result = boundary.inspect_content_boundaries(
        ["agent/raphael/control.py"],
        root=tmp_path,
        profile="llm",
    )

    assert result.ready is False
    assert result.violations == (
        "agent/raphael/control.py imports deferred media module agent.visual.agent_mode.planner",
    )


def test_raphael_llm_slice_boundary_flags_deferred_imports_in_cli_slice(tmp_path):
    from scripts import raphael_release_slice_boundary as boundary

    source = tmp_path / "hermes_cli"
    source.mkdir(parents=True)
    (source / "raphael_cmd.py").write_text(
        "from agent.visual.agent_mode.planner import plan_visual_agent_request\n",
        encoding="utf-8",
    )

    result = boundary.inspect_content_boundaries(
        ["hermes_cli/raphael_cmd.py"],
        root=tmp_path,
        profile="llm",
    )

    assert result.ready is False
    assert result.violations == (
        "hermes_cli/raphael_cmd.py imports deferred media module agent.visual.agent_mode.planner",
    )


def test_raphael_llm_slice_boundary_parses_git_status_lines():
    from scripts import raphael_release_slice_boundary as boundary

    assert boundary._path_from_status_line(" M gateway/run.py") == "gateway/run.py"
    assert boundary._path_from_status_line("?? scripts/new.py") == "scripts/new.py"
    assert (
        boundary._path_from_status_line(" R old/path.py -> agent/raphael/new.py")
        == "agent/raphael/new.py"
    )


def test_from_git_status_fails_closed_on_clean_checkout(monkeypatch, capsys):
    from hermes_cli.release_evidence.raphael import (
        raphael_release_slice_boundary as boundary,
    )

    monkeypatch.setattr(boundary, "git_status_paths", lambda: ())

    exit_code = boundary.main(["--from-git-status"])

    assert exit_code != 0
    assert "committed diff" in capsys.readouterr().out.lower()


def test_clean_checkout_can_use_explicit_committed_diff_base(monkeypatch):
    from hermes_cli.release_evidence.raphael import (
        raphael_release_slice_boundary as boundary,
    )

    monkeypatch.setattr(boundary, "git_status_paths", lambda: ())
    observed: list[str] = []
    monkeypatch.setattr(
        boundary,
        "git_diff_paths",
        lambda revision: observed.append(revision) or ("agent/raphael/control.py",),
        raising=False,
    )

    try:
        exit_code = boundary.main(
            ["--from-git-status", "--diff-base", "v2026.7.7.2"]
        )
    except SystemExit as exc:
        pytest.fail(f"explicit committed diff base is unsupported: {exc}")

    assert exit_code == 0
    assert observed == ["v2026.7.7.2...HEAD"]
