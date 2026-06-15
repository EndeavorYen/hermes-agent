"""Tests for the read-only Raphael advisor plugin."""

import importlib.util
import sys
import types
from pathlib import Path

import yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_config(hermes_home: Path, payload: dict) -> None:
    hermes_home.mkdir(parents=True, exist_ok=True)
    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump(payload), encoding="utf-8"
    )


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
    assert loaded.commands_registered == ["raphael-status"]
    assert mgr._plugin_commands["raphael-status"] == {
        "handler": loaded.module.handle_status,
        "description": "Show read-only Raphael advisor status",
        "plugin": "raphael",
        "args_hint": "",
    }


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

    assert (
        plugin.handle_status("")
        == "Raphael Advisor is disabled. Set raphael.enabled: true to enable /raphael-status."
    )
    assert not (hermes_home / "raphael").exists()


def test_enabled_status_renders_empty_state_without_mutating_runtime(
    monkeypatch, tmp_path
):
    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(
        hermes_home,
        {"raphael": {"enabled": True}},
    )
    plugin = _load_plugin_init()

    out = plugin.handle_status("")

    assert "Raphael Advisor" in out
    assert "No active status cards." in out
    assert "No pending action proposals." in out
    assert not (hermes_home / "memories").exists()
    assert not (hermes_home / "cron" / "jobs.json").exists()


def test_non_empty_args_return_usage(monkeypatch, tmp_path):
    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    _write_config(hermes_home, {"raphael": {"enabled": True}})
    plugin = _load_plugin_init()

    assert plugin.handle_status("extra") == "Usage: /raphael-status"
    assert plugin.handle_status("  extra  ") == "Usage: /raphael-status"


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
