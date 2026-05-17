import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import gateway.run as gateway_run
from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource, build_session_key


class _CapturingAgent:
    runs = []

    def __init__(self, *args, **kwargs):
        self.tools = []

    def run_conversation(self, user_message, conversation_history=None, task_id=None):
        from agent import image_routing

        type(self).runs.append(
            {
                "user_message": user_message,
                "conversation_history": conversation_history,
                "task_id": task_id,
                "reference_paths": image_routing.get_current_image_reference_paths(),
            }
        )
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


def _make_runner() -> GatewayRunner:
    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="fake")},
    )
    runner.adapters = {}
    runner._model = "openai/gpt-4.1-mini"
    runner._base_url = None
    runner._decide_image_input_mode = lambda: "native"
    return runner


def _make_run_runner() -> GatewayRunner:
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
    runner.hooks = SimpleNamespace(loaded_hooks=False)
    runner.config = SimpleNamespace(
        streaming=None,
        group_sessions_per_user=True,
        thread_sessions_per_user=False,
    )
    runner.session_store = SimpleNamespace(
        get_or_create_session=lambda source: SimpleNamespace(session_id="session-1"),
        load_transcript=lambda session_id: [],
    )
    runner._get_or_create_gateway_honcho = lambda session_key: (None, None)
    runner._model = "openai/gpt-4.1-mini"
    runner._base_url = None
    runner._decide_image_input_mode = lambda: "native"
    return runner


def _source(chat_id: str) -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id=chat_id,
        chat_type="private",
        user_name=f"user-{chat_id}",
    )


def _image_event(source: SessionSource, path: str) -> MessageEvent:
    return MessageEvent(
        text="see image",
        message_type=MessageType.PHOTO,
        source=source,
        media_urls=[path],
        media_types=["image/png"],
    )


@pytest.mark.asyncio
async def test_native_image_buffer_isolated_per_session():
    runner = _make_runner()
    source_a = _source("chat-a")
    source_b = _source("chat-b")

    await runner._prepare_inbound_message_text(
        event=_image_event(source_a, "/tmp/a.png"),
        source=source_a,
        history=[],
    )
    await runner._prepare_inbound_message_text(
        event=_image_event(source_b, "/tmp/b.png"),
        source=source_b,
        history=[],
    )

    assert runner._consume_pending_native_image_paths(build_session_key(source_a)) == ["/tmp/a.png"]
    assert runner._consume_pending_native_image_paths(build_session_key(source_b)) == ["/tmp/b.png"]


@pytest.mark.asyncio
async def test_native_image_buffer_not_cleared_by_other_sessions_without_images():
    runner = _make_runner()
    source_a = _source("chat-a")
    source_b = _source("chat-b")

    await runner._prepare_inbound_message_text(
        event=_image_event(source_a, "/tmp/a.png"),
        source=source_a,
        history=[],
    )
    await runner._prepare_inbound_message_text(
        event=MessageEvent(text="plain text", source=source_b),
        source=source_b,
        history=[],
    )

    assert runner._consume_pending_native_image_paths(build_session_key(source_a)) == ["/tmp/a.png"]
    assert runner._consume_pending_native_image_paths(build_session_key(source_b)) == []


@pytest.mark.asyncio
async def test_native_image_paths_are_bound_to_current_turn_tool_references(
    monkeypatch,
    tmp_path,
):
    _install_fake_agent(monkeypatch)
    runner = _make_run_runner()

    image = tmp_path / "uploaded.png"
    image.write_bytes(b"uploaded-image")
    source = _source("chat-a")
    prepared = await runner._prepare_inbound_message_text(
        event=_image_event(source, str(image)),
        source=source,
        history=[],
    )
    session_key = runner._session_key_for_source(source)

    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {})
    monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda config=None: "gpt-5.4")
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {
            "provider": "openrouter",
            "api_mode": "chat_completions",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "test-key",
        },
    )

    import hermes_cli.tools_config as tools_config

    monkeypatch.setattr(tools_config, "_get_platform_tools", lambda user_config, platform_key: {"core"})

    _CapturingAgent.runs = []
    result = await runner._run_agent(
        message=prepared,
        context_prompt="",
        history=[],
        source=source,
        session_id="session-a",
        session_key=session_key,
    )

    assert result["final_response"] == "ok"
    assert len(_CapturingAgent.runs) == 1
    assert _CapturingAgent.runs[0]["reference_paths"] == [str(image)]


@pytest.mark.asyncio
async def test_text_mode_image_paths_are_still_bound_to_tool_references(
    monkeypatch,
    tmp_path,
):
    _install_fake_agent(monkeypatch)
    runner = _make_run_runner()
    runner._decide_image_input_mode = lambda: "text"
    runner._enrich_message_with_vision = AsyncMock(return_value="ENRICHED")

    image = tmp_path / "uploaded.png"
    image.write_bytes(b"uploaded-image")
    source = _source("chat-text")
    prepared = await runner._prepare_inbound_message_text(
        event=_image_event(source, str(image)),
        source=source,
        history=[],
    )
    session_key = runner._session_key_for_source(source)

    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {})
    monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda config=None: "gpt-5.4")
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {
            "provider": "openrouter",
            "api_mode": "chat_completions",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "test-key",
        },
    )

    import hermes_cli.tools_config as tools_config

    monkeypatch.setattr(tools_config, "_get_platform_tools", lambda user_config, platform_key: {"core"})

    _CapturingAgent.runs = []
    result = await runner._run_agent(
        message=prepared,
        context_prompt="",
        history=[],
        source=source,
        session_id="session-text",
        session_key=session_key,
    )

    assert result["final_response"] == "ok"
    assert len(_CapturingAgent.runs) == 1
    assert _CapturingAgent.runs[0]["user_message"] == "ENRICHED"
    assert _CapturingAgent.runs[0]["reference_paths"] == [str(image)]
