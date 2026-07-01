from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

import yaml


def _read_config(home: Path) -> dict:
    path = home / "config.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_config(home: Path, payload: dict) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def test_install_is_idempotent_and_leaves_raphael_disabled(monkeypatch, tmp_path):
    from hermes_cli.raphael_lifecycle import install_raphael

    hermes_home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(hermes_home, {"plugins": {"enabled": ["other"]}})

    first = install_raphael()
    second = install_raphael()

    assert first.changed is True
    assert second.changed is False
    config = _read_config(hermes_home)
    assert config["plugins"]["enabled"].count("raphael") == 1
    assert config["plugins"]["enabled"] == ["other", "raphael"]
    assert config["raphael"]["enabled"] is False
    assert config["raphael"]["default_conversation_mode_enabled"] is False
    assert config["raphael"]["mode"] == "advisor"


def test_enable_turns_on_public_raphael_injection_surfaces(monkeypatch, tmp_path):
    from agent.raphael.governor import should_apply_raphael_response_governor
    from agent.raphael.observer import should_inject_raphael_observation
    from agent.raphael.prompt import build_raphael_mode_prompt
    from hermes_cli.config import load_config
    from hermes_cli.raphael_lifecycle import enable_raphael, install_raphael

    hermes_home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    install_raphael()
    result = enable_raphael()

    assert result.changed is True
    config = load_config()
    assert config["raphael"]["enabled"] is True
    assert config["raphael"]["default_conversation_mode_enabled"] is True
    assert config["plugins"]["enabled"].count("raphael") == 1
    assert "Raphael Mode" in build_raphael_mode_prompt(config)
    assert should_inject_raphael_observation(config)
    assert should_apply_raphael_response_governor(config)


def test_disable_turns_off_public_raphael_injection_surfaces(monkeypatch, tmp_path):
    from agent.raphael.governor import should_apply_raphael_response_governor
    from agent.raphael.observer import should_inject_raphael_observation
    from agent.raphael.prompt import build_raphael_mode_prompt
    from hermes_cli.config import load_config
    from hermes_cli.raphael_lifecycle import disable_raphael, enable_raphael

    hermes_home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    enable_raphael()

    result = disable_raphael()

    assert result.changed is True
    config = load_config()
    assert config["raphael"]["enabled"] is False
    assert config["raphael"]["default_conversation_mode_enabled"] is False
    assert build_raphael_mode_prompt(config) == ""
    assert not should_inject_raphael_observation(config)
    assert not should_apply_raphael_response_governor(config)


def test_status_reports_lifecycle_without_creating_runtime_state(
    monkeypatch, tmp_path, capsys
):
    from hermes_cli.raphael_lifecycle import raphael_command

    hermes_home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    exit_code = raphael_command(Namespace(raphael_action="status"))

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Raphael lifecycle status" in out
    assert "Installed: no" in out
    assert "Enabled: no" in out
    assert "Next action: hermes raphael install" in out
    assert not (hermes_home / "raphael").exists()


def test_status_reports_mission_summary_without_leaking_evidence_refs(
    monkeypatch, tmp_path, capsys
):
    from agent.raphael.models import MissionArtifact, RaphaelMission, RaphaelState
    from agent.raphael.state import write_state
    from hermes_cli.raphael_lifecycle import raphael_command

    hermes_home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    now = datetime(2026, 7, 1, 15, 30, tzinfo=timezone.utc)
    artifact = MissionArtifact(
        artifact_id="image-1",
        kind="image",
        label="Hero image",
        uri="/private/tmp/raphael-secret-selected.png",
        created_at=now,
    )
    mission = RaphaelMission(
        mission_id="mission-1",
        goal="Ship Raphael phase 2",
        active_artifact_id="image-1",
        artifacts=(artifact,),
        success_conditions=("goal state visible",),
        phase="planning",
        blockers=(),
        next_action="run CLI status smoke",
        selected_strategy="issue-scoped TDD",
        required_proofs=("unit tests", "status smoke"),
        last_evidence=(
            "/private/tmp/provider-raw.log",
            "base64:rejected-candidate",
            "candidate:old-image",
        ),
        updated_at=now,
    )

    write_state(
        RaphaelState(
            status_cards=(),
            action_proposals=(),
            active_mission=mission,
            updated_at=now,
        )
    )

    exit_code = raphael_command(Namespace(raphael_action="status"))

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Current mission: mission-1" in out
    assert "Goal: Ship Raphael phase 2" in out
    assert "Phase: planning" in out
    assert "Active artifact: Hero image (image-1)" in out
    assert "Required proofs: 2" in out
    assert "Last evidence: 3 recorded" in out
    assert "Next mission action: run CLI status smoke" in out
    assert "/private/tmp" not in out
    assert "base64" not in out
    assert "candidate:old-image" not in out


def test_uninstall_removes_only_raphael_owned_state(monkeypatch, tmp_path):
    from hermes_cli.raphael_lifecycle import uninstall_raphael

    hermes_home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {
                "enabled": ["other", "raphael"],
                "disabled": ["legacy", "raphael"],
            },
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "mode": "advisor",
            },
        },
    )
    (hermes_home / "raphael").mkdir(parents=True)
    (hermes_home / "raphael" / "state.json").write_text("{}", encoding="utf-8")
    (hermes_home / "memories").mkdir()
    (hermes_home / "memories" / "keep.txt").write_text("keep", encoding="utf-8")

    result = uninstall_raphael()

    assert result.changed is True
    config = _read_config(hermes_home)
    assert config["plugins"]["enabled"] == ["other"]
    assert config["plugins"]["disabled"] == ["legacy"]
    assert config["raphael"]["enabled"] is False
    assert config["raphael"]["default_conversation_mode_enabled"] is False
    assert not (hermes_home / "raphael").exists()
    assert (hermes_home / "memories" / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_uninstall_is_noop_when_raphael_was_never_installed(monkeypatch, tmp_path):
    from hermes_cli.raphael_lifecycle import uninstall_raphael

    hermes_home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    result = uninstall_raphael()

    assert result.changed is False
    assert not (hermes_home / "config.yaml").exists()
    assert not (hermes_home / "raphael").exists()


def test_raphael_parser_registers_lifecycle_actions():
    from hermes_cli._parser import build_top_level_parser
    from hermes_cli.subcommands.raphael import build_raphael_parser

    parser, subparsers, _chat_parser = build_top_level_parser()

    def _dispatch(args):
        return args

    build_raphael_parser(subparsers, cmd_raphael=_dispatch)

    args = parser.parse_args(["raphael", "enable"])

    assert args.raphael_action == "enable"
    assert args.func(args) is args


def test_raphael_is_builtin_subcommand_for_fast_parser_path():
    from hermes_cli.main import _BUILTIN_SUBCOMMANDS

    assert "raphael" in _BUILTIN_SUBCOMMANDS
