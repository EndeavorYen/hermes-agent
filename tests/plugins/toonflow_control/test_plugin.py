from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

import plugins.toonflow_control as plugin
from hermes_cli.plugins import PluginManager


@dataclass
class RegisteredTool:
    name: str
    toolset: str
    schema: dict[str, Any]
    handler: Any
    check_fn: Any


class RecordingPluginContext:
    def __init__(self) -> None:
        self.tools: list[RegisteredTool] = []

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(
            RegisteredTool(
                name=kwargs["name"],
                toolset=kwargs["toolset"],
                schema=kwargs["schema"],
                handler=kwargs["handler"],
                check_fn=kwargs["check_fn"],
            )
        )


def test_register_exposes_only_control_tools():
    ctx = RecordingPluginContext()
    plugin.register(ctx)
    assert [item.name for item in ctx.tools] == [
        "toonflow_capabilities",
        "toonflow_create_project",
        "toonflow_run",
        "toonflow_run_status",
        "toonflow_cancel_run",
        "toonflow_select_artifact",
    ]
    assert {item.toolset for item in ctx.tools} == {"toonflow"}
    assert all(item.check_fn() in {True, False} for item in ctx.tools)


def test_registered_handlers_serialize_for_hermes_registry(monkeypatch):
    monkeypatch.setenv("TOONFLOW_CONTROL_TOKEN", "fixture")
    ctx = RecordingPluginContext()
    plugin.register(ctx)

    class Client:
        def capabilities(self):
            return {
                "contract_version": "1.0",
                "operations": ["generate_shots"],
                "route_profiles": ["image.standard"],
            }

    result = ctx.tools[0].handler({}, client=Client())
    assert isinstance(result, str)
    assert json.loads(result)["success"] is True


def test_check_reports_missing_control_token(monkeypatch):
    monkeypatch.delenv("TOONFLOW_CONTROL_TOKEN", raising=False)
    ok, message = plugin.check_toonflow_configured()
    assert ok is False
    assert "TOONFLOW_CONTROL_TOKEN" in message


def test_check_rejects_remote_url_without_network(monkeypatch):
    monkeypatch.setenv("TOONFLOW_CONTROL_TOKEN", "fixture")
    monkeypatch.setenv("TOONFLOW_CONTROL_URL", "https://toonflow.example")
    ok, message = plugin.check_toonflow_configured()
    assert ok is False
    assert "loopback" in message


def test_check_accepts_local_construction_without_contacting_toonflow(
    monkeypatch,
):
    monkeypatch.setenv("TOONFLOW_CONTROL_TOKEN", "fixture")
    monkeypatch.setenv("TOONFLOW_CONTROL_URL", "http://127.0.0.1:10588")
    monkeypatch.setattr(
        "plugins.toonflow_control.client.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("configuration check must not use the network")
        ),
    )
    assert plugin.check_toonflow_configured() == (True, "configured")


def test_manifest_declares_the_six_tools():
    manifest_path = (
        Path(__file__).resolve().parents[3]
        / "plugins"
        / "toonflow_control"
        / "plugin.yaml"
    )
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"] == "toonflow-control"
    assert manifest["kind"] == "backend"
    assert manifest["provides_tools"] == [
        "toonflow_capabilities",
        "toonflow_create_project",
        "toonflow_run",
        "toonflow_run_status",
        "toonflow_cancel_run",
        "toonflow_select_artifact",
    ]


def test_plugin_is_discoverable_without_toonflow_running(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.delenv("TOONFLOW_CONTROL_TOKEN", raising=False)
    manager = PluginManager()
    manager.discover_and_load()
    loaded = manager._plugins["toonflow-control"]
    assert loaded.manifest.source == "bundled"
    assert loaded.enabled is True
    assert loaded.error is None
