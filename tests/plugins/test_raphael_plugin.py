"""Tests for the Raphael Sage King evolution plugin."""

import importlib.util
import sys
import types
from pathlib import Path

import yaml


DISABLED_STATUS_MESSAGE = (
    "Raphael mode is disabled. Use /raphael-enable or `hermes raphael enable` "
    "to re-enable /raphael-status."
)
DISABLED_SKILLS_MESSAGE = (
    "Raphael Skill Trace is disabled. Use /raphael-enable or "
    "`hermes raphael enable` first, then set raphael.skill_trace.enabled: true "
    "to enable /raphael-skills."
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_config(hermes_home: Path, payload: dict) -> None:
    hermes_home.mkdir(parents=True, exist_ok=True)
    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump(payload), encoding="utf-8"
    )


def _relative_paths(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def _load_plugin_init():
    plugin_dir = _repo_root() / "plugins" / "raphael"
    module_name = "hermes_plugins.raphael"
    spec = importlib.util.spec_from_file_location(
        module_name,
        plugin_dir / "__init__.py",
        submodule_search_locations=[str(plugin_dir)],
    )
    assert spec is not None
    assert spec.loader is not None

    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns

    sys.modules.pop(module_name, None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = module_name
    mod.__path__ = [str(plugin_dir)]
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_plugin_command_not_registered_without_plugins_enabled(
    monkeypatch, tmp_path
):
    import hermes_cli.plugins as plugins_mod

    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": []},
            "raphael": {"enabled": True},
        },
    )

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()

    mgr = plugins_mod._plugin_manager
    assert mgr is not None
    loaded = mgr._plugins["raphael"]
    assert not loaded.enabled
    assert loaded.error and "not enabled" in loaded.error
    assert "raphael-status" not in mgr._plugin_commands


def test_enabled_plugin_registers_raphael_status_command(monkeypatch, tmp_path):
    import hermes_cli.plugins as plugins_mod

    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"]},
            "raphael": {"enabled": False},
        },
    )

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()

    mgr = plugins_mod._plugin_manager
    assert mgr is not None
    loaded = mgr._plugins["raphael"]
    assert loaded.enabled
    assert loaded.manifest.name == "raphael"
    assert loaded.commands_registered == [
        "raphael-status",
        "raphael-skills",
        "raphael-doctor",
        "raphael-enable",
        "raphael-disable",
    ]
    assert mgr._plugin_commands["raphael-status"] == {
        "handler": loaded.module.handle_status,
        "description": "Show Raphael Sage King status",
        "plugin": "raphael",
        "args_hint": "",
    }
    assert mgr._plugin_commands["raphael-skills"] == {
        "handler": loaded.module.handle_skills,
        "description": "Show Raphael skill evolution traces",
        "plugin": "raphael",
        "args_hint": "",
    }
    assert mgr._plugin_commands["raphael-doctor"] == {
        "handler": loaded.module.handle_doctor,
        "description": "Check Raphael local setup",
        "plugin": "raphael",
        "args_hint": "",
    }
    assert mgr._plugin_commands["raphael-enable"] == {
        "handler": loaded.module.handle_enable,
        "description": "Enable Raphael mode",
        "plugin": "raphael",
        "args_hint": "",
    }
    assert mgr._plugin_commands["raphael-disable"] == {
        "handler": loaded.module.handle_disable,
        "description": "Disable Raphael mode",
        "plugin": "raphael",
        "args_hint": "",
    }


def test_enabled_plugin_injects_ephemeral_raphael_context(monkeypatch, tmp_path):
    import hermes_cli.plugins as plugins_mod

    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"]},
            "raphael": {
                "enabled": True,
                "mode": "sage_king",
                "default_conversation_mode_enabled": True,
            },
        },
    )

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()
    loaded = plugins_mod._plugin_manager._plugins["raphael"]

    assert loaded.hooks_registered == ["pre_llm_call"]
    results = plugins_mod.invoke_hook(
        "pre_llm_call",
        user_message="請 patch gateway fallback bug 並驗證",
        conversation_history=[],
    )
    assert len(results) == 1
    assert "Raphael State Observer" in results[0]["context"]
    assert "task_state: mutation_or_delivery_request" in results[0]["context"]


def test_raphael_manifest_declares_public_slash_commands(monkeypatch, tmp_path):
    import hermes_cli.plugins as plugins_mod

    plugin_dir = _repo_root() / "plugins" / "raphael"
    manifest = yaml.safe_load((plugin_dir / "plugin.yaml").read_text(encoding="utf-8"))
    expected = [
        "raphael-status",
        "raphael-skills",
        "raphael-doctor",
        "raphael-enable",
        "raphael-disable",
    ]

    assert manifest["provides_commands"] == expected

    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"]},
            "raphael": {"enabled": False},
        },
    )

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()
    loaded = plugins_mod._plugin_manager._plugins["raphael"]

    assert loaded.manifest.provides_commands == expected
    assert loaded.commands_registered == expected


def test_enabled_status_command_does_not_initialize_runtime_scaffold(
    monkeypatch, tmp_path
):
    import hermes_cli.plugins as plugins_mod

    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"]},
            "raphael": {"enabled": True},
        },
    )

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()
    handler = plugins_mod.get_plugin_command_handler("raphael-status")

    assert handler is not None
    assert "Raphael Sage King" in handler("")
    assert not (hermes_home / "raphael").exists()


def test_status_command_includes_persisted_current_mission(monkeypatch, tmp_path):
    import hermes_cli.plugins as plugins_mod
    import agent.raphael.state as raphael_state
    from agent.raphael.appraisal import RaphaelAppraisal
    from agent.raphael.mission import update_raphael_mission
    from agent.raphael.strategy import RaphaelStrategy, RaphaelStrategySet

    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(raphael_state, "get_hermes_home", lambda: hermes_home)
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"]},
            "raphael": {"enabled": True},
        },
    )
    strategy = RaphaelStrategy(
        strategy_id="safe",
        label="safe",
        route="plan_execute_verify",
        expected_benefit="best_reliability",
        risk="low",
        required_proofs=("focused_tests", "runtime_smoke_when_live_wiring"),
    )
    mission = update_raphael_mission(
        None,
        RaphaelAppraisal(
            "修復 gateway fallback bug",
            "tool_runtime",
            "medium",
            ("focused_tests", "runtime_smoke_when_live_wiring"),
        ),
        RaphaelStrategySet(candidates=(strategy,), selected_strategy_id="safe"),
    )
    raphael_state.write_mission_state(mission)

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()
    handler = plugins_mod.get_plugin_command_handler("raphael-status")

    output = handler("")

    assert "Current Mission:" in output
    assert mission.mission_id not in output
    assert "任務：修復 gateway fallback bug" in output
    assert "修復 gateway fallback bug" in output
    assert "live runtime smoke 通過" in output
    assert "runtime_smoke_when_live_wiring" not in output


def test_enabled_skills_command_does_not_initialize_runtime_scaffold(
    monkeypatch, tmp_path
):
    import hermes_cli.plugins as plugins_mod

    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"]},
            "raphael": {"enabled": True},
        },
    )

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()
    handler = plugins_mod.get_plugin_command_handler("raphael-skills")

    assert handler is not None
    assert "Raphael Skill Evolution Trace" in handler("")
    assert not (hermes_home / "raphael").exists()


def test_enabled_doctor_command_checks_setup_without_runtime_scaffold(
    monkeypatch, tmp_path
):
    import hermes_cli.plugins as plugins_mod

    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True, "default_conversation_mode_enabled": True},
        },
    )

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()
    handler = plugins_mod.get_plugin_command_handler("raphael-doctor")
    before_paths = _relative_paths(hermes_home)

    assert handler is not None
    output = handler("")
    assert "Raphael Setup Doctor" in output
    assert "Local setup ready: yes" in output
    assert "Public release ready: yes" not in output
    assert _relative_paths(hermes_home) == before_paths


def test_disabled_status_does_not_read_or_create_state(
    monkeypatch, tmp_path
):
    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {"raphael": {"enabled": False}},
    )
    plugin = _load_plugin_init()

    def _fail_read_state():
        raise AssertionError("disabled Raphael status must not read state")

    monkeypatch.setattr(plugin, "read_state", _fail_read_state)

    assert plugin.handle_status("") == DISABLED_STATUS_MESSAGE
    assert not (hermes_home / "raphael").exists()


def test_disabled_skills_does_not_read_usage_or_create_state(
    monkeypatch, tmp_path
):
    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {"raphael": {"enabled": True, "skill_trace": {"enabled": False}}},
    )
    plugin = _load_plugin_init()

    def _fail_summarize_skill_usage(**_kwargs):
        raise AssertionError("disabled Raphael skills must not read usage")

    monkeypatch.setattr(plugin, "summarize_skill_usage", _fail_summarize_skill_usage)

    assert plugin.handle_skills("") == DISABLED_SKILLS_MESSAGE
    assert not (hermes_home / "raphael").exists()


def test_direct_status_and_skills_handlers_respect_disabled_plugin(
    monkeypatch, tmp_path
):
    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"], "disabled": ["raphael"]},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "skill_trace": {"enabled": True},
            },
        },
    )
    plugin = _load_plugin_init()

    assert plugin.handle_status("") == DISABLED_STATUS_MESSAGE
    assert plugin.handle_skills("") == DISABLED_SKILLS_MESSAGE
    assert not (hermes_home / "raphael").exists()


def test_enabled_status_renders_empty_state_without_mutating_runtime(
    monkeypatch, tmp_path
):
    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True},
        },
    )
    plugin = _load_plugin_init()

    out = plugin.handle_status("")

    assert "Raphael Sage King" in out
    assert "No active status cards." in out
    assert "No pending action proposals." in out
    assert not (hermes_home / "memories").exists()
    assert not (hermes_home / "cron" / "jobs.json").exists()


def test_non_empty_args_return_usage(monkeypatch, tmp_path):
    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {"enabled": True},
        },
    )
    plugin = _load_plugin_init()

    assert plugin.handle_status("extra") == "Usage: /raphael-status"
    assert plugin.handle_status("  extra  ") == "Usage: /raphael-status"
    assert plugin.handle_skills("extra") == "Usage: /raphael-skills"
    assert plugin.handle_skills("  extra  ") == "Usage: /raphael-skills"
    assert plugin.handle_doctor("extra") == "Usage: /raphael-doctor"
    assert plugin.handle_doctor("  extra  ") == "Usage: /raphael-doctor"


def test_max_status_cards_invalid_values_fall_back_and_minimum_is_one(
    monkeypatch, tmp_path
):
    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    plugin = _load_plugin_init()

    _write_config(
        hermes_home,
        {"raphael": {"enabled": True, "max_status_cards": "invalid"}},
    )
    assert plugin._max_status_cards() == 20

    _write_config(
        hermes_home,
        {"raphael": {"enabled": True, "max_status_cards": 0}},
    )
    assert plugin._max_status_cards() == 1


def test_skill_trace_limits_invalid_values_fall_back_and_minimum_is_zero(
    monkeypatch, tmp_path
):
    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    plugin = _load_plugin_init()

    _write_config(
        hermes_home,
        {
            "raphael": {
                "enabled": True,
                "skill_trace": {
                    "max_summary_rows": "invalid",
                    "max_trace_events": "invalid",
                },
            }
        },
    )
    assert plugin._max_skill_summary_rows() == 20
    assert plugin._max_trace_events() == 500

    _write_config(
        hermes_home,
        {
            "raphael": {
                "enabled": True,
                "skill_trace": {
                    "max_summary_rows": -1,
                    "max_trace_events": -1,
                },
            }
        },
    )
    assert plugin._max_skill_summary_rows() == 0
    assert plugin._max_trace_events() == 0
