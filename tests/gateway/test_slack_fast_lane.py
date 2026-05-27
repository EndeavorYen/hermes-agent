"""Tests for Slack fast/deep gateway lane routing."""

import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.session import SessionSource


class _CapturingAgent:
    last_init = None

    def __init__(self, *args, **kwargs):
        type(self).last_init = dict(kwargs)
        self.tools = []

    def run_conversation(
        self,
        user_message,
        conversation_history=None,
        task_id=None,
        persist_user_message=None,
    ):
        return {
            "final_response": "ok",
            "messages": [],
            "api_calls": 1,
            "completed": True,
        }


def _install_fake_agent(monkeypatch):
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)


def _make_runner():
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.adapters = {}
    runner._ephemeral_system_prompt = ""
    runner._prefill_messages = []
    runner._reasoning_config = None
    runner._service_tier = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._running_agents = {}
    runner._pending_model_notes = {}
    runner._session_db = None
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._session_model_overrides = {}
    runner._session_reasoning_overrides = {}
    runner.hooks = SimpleNamespace(loaded_hooks=False)
    runner.config = SimpleNamespace(streaming=None)
    runner.session_store = SimpleNamespace(
        get_or_create_session=lambda source: SimpleNamespace(session_id="session-1"),
        load_transcript=lambda session_id: [],
    )
    runner._get_or_create_gateway_honcho = lambda session_key: (None, None)
    runner._enrich_message_with_vision = AsyncMock(return_value="ENRICHED")
    return runner


def _slack_source() -> SessionSource:
    return SessionSource(
        platform=Platform.SLACK,
        chat_id="C12345",
        chat_type="group",
        user_id="U12345",
    )


def _lane_config():
    return {
        "gateway_lanes": {
            "slack": {
                "enabled": True,
                "default": "fast",
                "lane_triggers": {
                    "deep": ["deep lane:", "stock cron job", "思考", "請好好想想"],
                    "full": ["full tools:", "terminal"],
                },
                "lanes": {
                    "fast": {
                        "model": "gpt-5.5",
                        "reasoning_effort": "medium",
                        "toolsets": [
                            "web",
                            "vision",
                            "image_gen",
                            "memory",
                            "clarify",
                            "skills_read",
                        ],
                    },
                    "deep": {
                        "model": "gpt-5.5",
                        "reasoning_effort": "xhigh",
                        "toolsets": [
                            "web",
                            "vision",
                            "image_gen",
                            "memory",
                            "clarify",
                            "skills_read",
                        ],
                    },
                    "full": {
                        "model": "gpt-5.5",
                        "reasoning_effort": "xhigh",
                        "toolsets": ["hermes-slack"],
                    },
                },
            }
        }
    }


def _runtime_kwargs():
    return {
        "provider": "openai-codex",
        "api_mode": "codex_responses",
        "base_url": "https://chatgpt.com/backend-api/codex",
        "api_key": "***",
    }


def test_slack_lane_defaults_to_gpt55_medium_reasoning_and_small_toolset():
    runner = _make_runner()

    route = gateway_run.GatewayRunner._resolve_gateway_lane_config(
        runner,
        user_config=_lane_config(),
        platform_key="slack",
        user_message="quick answer please",
        model="gpt-5.5",
        runtime_kwargs=_runtime_kwargs(),
        enabled_toolsets=["browser", "terminal", "web"],
        reasoning_config={"enabled": True, "effort": "xhigh"},
        session_key="agent:main:slack:group:C12345",
    )

    assert route["lane"] == "fast"
    assert route["model"] == "gpt-5.5"
    assert route["reasoning_config"] == {"enabled": True, "effort": "medium"}
    assert route["enabled_toolsets"] == [
        "clarify",
        "image_gen",
        "memory",
        "skills_read",
        "vision",
        "web",
    ]
    assert "terminal" not in route["enabled_toolsets"]
    assert "browser" not in route["enabled_toolsets"]


def test_slack_thinking_trigger_uses_deep_reasoning_and_small_toolset():
    runner = _make_runner()

    route = gateway_run.GatewayRunner._resolve_gateway_lane_config(
        runner,
        user_config=_lane_config(),
        platform_key="slack",
        user_message="請好好想想這個設計",
        model="gpt-5.5",
        runtime_kwargs=_runtime_kwargs(),
        enabled_toolsets=["web"],
        reasoning_config={"enabled": True, "effort": "medium"},
        session_key="agent:main:slack:group:C12345",
    )

    assert route["lane"] == "deep"
    assert route["model"] == "gpt-5.5"
    assert route["reasoning_config"] == {"enabled": True, "effort": "xhigh"}
    assert route["enabled_toolsets"] == [
        "clarify",
        "image_gen",
        "memory",
        "skills_read",
        "vision",
        "web",
    ]
    assert "terminal" not in route["enabled_toolsets"]
    assert "browser" not in route["enabled_toolsets"]


def test_slack_stock_cron_trigger_uses_deep_reasoning_and_small_toolset():
    runner = _make_runner()

    route = gateway_run.GatewayRunner._resolve_gateway_lane_config(
        runner,
        user_config=_lane_config(),
        platform_key="slack",
        user_message="這個跟 stock cron job 有關，幫我分析",
        model="gpt-5.5",
        runtime_kwargs=_runtime_kwargs(),
        enabled_toolsets=["web"],
        reasoning_config={"enabled": True, "effort": "medium"},
        session_key="agent:main:slack:group:C12345",
    )

    assert route["lane"] == "deep"
    assert route["model"] == "gpt-5.5"
    assert route["reasoning_config"] == {"enabled": True, "effort": "xhigh"}
    assert route["enabled_toolsets"] == [
        "clarify",
        "image_gen",
        "memory",
        "skills_read",
        "vision",
        "web",
    ]


def test_slack_explicit_full_tools_trigger_restores_full_toolset():
    runner = _make_runner()

    route = gateway_run.GatewayRunner._resolve_gateway_lane_config(
        runner,
        user_config=_lane_config(),
        platform_key="slack",
        user_message="full tools: please use terminal to inspect this",
        model="gpt-5.5",
        runtime_kwargs=_runtime_kwargs(),
        enabled_toolsets=["web"],
        reasoning_config={"enabled": True, "effort": "medium"},
        session_key="agent:main:slack:group:C12345",
    )

    assert route["lane"] == "full"
    assert route["model"] == "gpt-5.5"
    assert route["reasoning_config"] == {"enabled": True, "effort": "xhigh"}
    assert "terminal" in route["enabled_toolsets"]
    assert "browser" in route["enabled_toolsets"]


def test_slack_lane_does_not_clobber_session_model_override():
    runner = _make_runner()
    session_key = "agent:main:slack:group:C12345"
    runner._session_model_overrides[session_key] = {
        "model": "custom-model",
        "provider": "openai-codex",
    }

    route = gateway_run.GatewayRunner._resolve_gateway_lane_config(
        runner,
        user_config=_lane_config(),
        platform_key="slack",
        user_message="quick answer please",
        model="custom-model",
        runtime_kwargs=_runtime_kwargs(),
        enabled_toolsets=["browser", "terminal", "web"],
        reasoning_config={"enabled": True, "effort": "xhigh"},
        session_key=session_key,
    )

    assert route["lane"] == "fast"
    assert route["model"] == "custom-model"
    assert route["enabled_toolsets"] == [
        "clarify",
        "image_gen",
        "memory",
        "skills_read",
        "vision",
        "web",
    ]


@pytest.mark.asyncio
async def test_run_agent_uses_slack_fast_lane(monkeypatch):
    _install_fake_agent(monkeypatch)
    runner = _make_runner()

    monkeypatch.setattr(gateway_run, "_load_gateway_config", _lane_config)
    monkeypatch.setattr(gateway_run, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda config=None: "gpt-5.5")
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _runtime_kwargs)

    _CapturingAgent.last_init = None
    result = await runner._run_agent(
        message="quick answer please",
        context_prompt="",
        history=[],
        source=_slack_source(),
        session_id="session-1",
        session_key="agent:main:slack:group:C12345",
    )

    assert result["final_response"] == "ok"
    assert _CapturingAgent.last_init["model"] == "gpt-5.5"
    assert _CapturingAgent.last_init["reasoning_config"] == {
        "enabled": True,
        "effort": "medium",
    }
    assert _CapturingAgent.last_init["enabled_toolsets"] == [
        "clarify",
        "image_gen",
        "memory",
        "skills_read",
        "vision",
        "web",
    ]


@pytest.mark.asyncio
async def test_run_agent_uses_slack_deep_lane(monkeypatch):
    _install_fake_agent(monkeypatch)
    runner = _make_runner()

    monkeypatch.setattr(gateway_run, "_load_gateway_config", _lane_config)
    monkeypatch.setattr(gateway_run, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda config=None: "gpt-5.5")
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _runtime_kwargs)

    _CapturingAgent.last_init = None
    result = await runner._run_agent(
        message="請好好想想這個設計",
        context_prompt="",
        history=[],
        source=_slack_source(),
        session_id="session-1",
        session_key="agent:main:slack:group:C12345",
    )

    assert result["final_response"] == "ok"
    assert _CapturingAgent.last_init["model"] == "gpt-5.5"
    assert _CapturingAgent.last_init["reasoning_config"] == {
        "enabled": True,
        "effort": "xhigh",
    }
    assert _CapturingAgent.last_init["enabled_toolsets"] == [
        "clarify",
        "image_gen",
        "memory",
        "skills_read",
        "vision",
        "web",
    ]
