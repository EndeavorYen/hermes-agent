from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
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
        self.hooks: dict[str, Any] = {}

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

    def register_hook(self, name: str, callback: Any) -> None:
        self.hooks[name] = callback


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


def test_explicit_toonflow_request_claims_turn_before_direct_visual_handoff(
    monkeypatch,
):
    from types import SimpleNamespace

    from agent.visual.agent_mode.handoff import build_direct_visual_agent_handoff

    monkeypatch.setenv("TOONFLOW_CONTROL_TOKEN", "fixture")
    monkeypatch.setenv("TOONFLOW_CONTROL_URL", "http://127.0.0.1:10588")
    ctx = RecordingPluginContext()
    plugin.register(ctx)
    prompt = "請用 ToonFlow 製作一隻約 30 秒、有角色和劇情的短片"

    hook_result = ctx.hooks["pre_llm_call"](
        user_message=prompt,
        session_id="session-configured",
        turn_id="turn-configured",
    )
    handoff = build_direct_visual_agent_handoff(
        SimpleNamespace(
            valid_tool_names={"visual_agent_generate", "toonflow_run"},
            provider="openai-codex",
            model="gpt-5.6",
        ),
        prompt,
        turn_control=hook_result["turn_control"],
    )

    assert hook_result["turn_control"]["mode"] == "external_workflow"
    assert hook_result["turn_control"]["route"]["owner"] == "toonflow"
    assert "toonflow_capabilities" in hook_result["context"]
    assert handoff is None
    assert (
        ctx.hooks["pre_tool_call"](
            tool_name="visual_agent_generate",
            session_id="session-configured",
            turn_id="turn-configured",
        )["action"]
        == "block"
    )
    assert (
        ctx.hooks["pre_tool_call"](
            tool_name="toonflow_capabilities",
            session_id="session-configured",
            turn_id="turn-configured",
        )
        is None
    )


def test_toonflow_turn_claim_ignores_generic_video_requests():
    ctx = RecordingPluginContext()
    plugin.register(ctx)

    assert ctx.hooks["pre_llm_call"](user_message="請幫我做一支短片") is None


def test_explicit_toonflow_request_fails_closed_when_control_is_unconfigured(
    monkeypatch,
):
    monkeypatch.delenv("TOONFLOW_CONTROL_TOKEN", raising=False)
    monkeypatch.delenv("TOONFLOW_CONTROL_TOKEN_FILE", raising=False)
    ctx = RecordingPluginContext()
    plugin.register(ctx)

    hook_result = ctx.hooks["pre_llm_call"](
        user_message="請用 ToonFlow 製作一支短片",
        session_id="session-unconfigured",
        turn_id="turn-unconfigured",
    )

    assert hook_result["turn_control"]["route"]["configured"] is False
    assert "TOONFLOW_WORKFLOW_ROUTE_SETUP_REQUIRED" in hook_result["context"]
    assert "TOONFLOW_CONTROL_TOKEN" in hook_result["context"]
    assert "Do not fall back" in hook_result["context"]
    assert (
        ctx.hooks["pre_tool_call"](
            tool_name="visual_agent_generate",
            session_id="session-unconfigured",
            turn_id="turn-unconfigured",
        )["action"]
        == "block"
    )
    assert (
        ctx.hooks["pre_tool_call"](
            tool_name="toonflow_capabilities",
            session_id="session-unconfigured",
            turn_id="turn-unconfigured",
        )["action"]
        == "block"
    )


@pytest.mark.parametrize(
    "prompt",
    (
        "ToonFlow 幫我做一支短片",
        "用 ToonFlow 製作短片",
        "Can you make a video with ToonFlow?",
        "ToonFlow, please create a short video",
        "Don't use Grok; make it with ToonFlow",
        "Without changing the prompt, use ToonFlow",
    ),
)
def test_toonflow_turn_claim_accepts_natural_explicit_requests(prompt):
    ctx = RecordingPluginContext()
    plugin.register(ctx)

    assert ctx.hooks["pre_llm_call"](user_message=prompt) is not None


@pytest.mark.parametrize(
    "prompt",
    (
        "不要使用 ToonFlow，直接做短片",
        "請勿使用 ToonFlow",
        "Do not use ToonFlow",
        "Do not make this video with ToonFlow",
        "Please don't create it with ToonFlow",
        "Never use ToonFlow",
        "ToonFlow 可以做影片嗎？",
    ),
)
def test_toonflow_turn_claim_rejects_opt_outs_and_questions(prompt):
    ctx = RecordingPluginContext()
    plugin.register(ctx)

    assert ctx.hooks["pre_llm_call"](user_message=prompt) is None


def test_check_reports_missing_control_token(monkeypatch):
    monkeypatch.delenv("TOONFLOW_CONTROL_TOKEN", raising=False)
    monkeypatch.delenv("TOONFLOW_CONTROL_TOKEN_FILE", raising=False)
    ok, message = plugin.check_toonflow_configured()
    assert ok is False
    assert "TOONFLOW_CONTROL_TOKEN" in message


def test_check_accepts_private_control_token_file(tmp_path, monkeypatch):
    token_file = tmp_path / "control-token"
    token_file.write_text("fixture\n", encoding="utf-8")
    token_file.chmod(0o600)
    monkeypatch.delenv("TOONFLOW_CONTROL_TOKEN", raising=False)
    monkeypatch.setenv("TOONFLOW_CONTROL_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("TOONFLOW_CONTROL_URL", "http://127.0.0.1:10588")

    assert plugin.check_toonflow_configured() == (True, "configured")


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
    assert manifest["kind"] == "standalone"
    assert manifest["provides_tools"] == [
        "toonflow_capabilities",
        "toonflow_create_project",
        "toonflow_run",
        "toonflow_run_status",
        "toonflow_cancel_run",
        "toonflow_select_artifact",
    ]


def test_plugin_is_opt_in_without_toonflow_running(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.delenv("TOONFLOW_CONTROL_TOKEN", raising=False)
    manager = PluginManager()
    manager.discover_and_load()
    loaded = manager._plugins["toonflow-control"]
    assert loaded.manifest.source == "bundled"
    assert loaded.enabled is False
    assert "not enabled in config" in str(loaded.error)


def test_plugin_loads_when_explicitly_enabled_without_toonflow_running(
    tmp_path,
    monkeypatch,
):
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - toonflow-control\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("TOONFLOW_CONTROL_TOKEN", raising=False)

    manager = PluginManager()
    manager.discover_and_load()

    loaded = manager._plugins["toonflow-control"]
    assert loaded.enabled is True
    assert loaded.error is None
