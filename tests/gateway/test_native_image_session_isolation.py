"""Regression tests for gateway native-image turn isolation."""

import base64
import sys
import threading
import types
from types import SimpleNamespace

import pytest

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session import SessionSource


class _CapturingAgent:
    runs = []

    def __init__(self, *args, **kwargs):
        self.tools = []

    def run_conversation(self, user_message, conversation_history=None, task_id=None):
        from agent.image_routing import get_current_image_reference_paths

        type(self).runs.append(
            {
                "user_message": user_message,
                "conversation_history": conversation_history,
                "task_id": task_id,
                "reference_paths": get_current_image_reference_paths(),
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
    runner._decide_image_input_mode = lambda: "native"
    return runner


def _source(chat_id: str, user_id: str) -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id=chat_id,
        chat_type="dm",
        user_id=user_id,
    )


def _image_event(text: str, source: SessionSource, image_path: str) -> MessageEvent:
    return MessageEvent(
        text=text,
        message_type=MessageType.PHOTO,
        source=source,
        media_urls=[image_path],
        media_types=["image/png"],
    )


@pytest.mark.asyncio
async def test_native_image_paths_are_bound_to_prepared_turn_not_runner_state(
    monkeypatch,
    tmp_path,
):
    _install_fake_agent(monkeypatch)
    runner = _make_runner()

    image_a = tmp_path / "session-a.png"
    image_b = tmp_path / "session-b.png"
    image_a.write_bytes(b"session-a-image")
    image_b.write_bytes(b"session-b-image")

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

    source_a = _source("chat-a", "user-a")
    source_b = _source("chat-b", "user-b")
    prepared_a = await runner._prepare_inbound_message(
        event=_image_event("look at A", source_a, str(image_a)),
        source=source_a,
        history=[],
    )
    prepared_b = await runner._prepare_inbound_message(
        event=_image_event("look at B", source_b, str(image_b)),
        source=source_b,
        history=[],
    )

    assert prepared_a is not None
    assert prepared_b is not None

    _CapturingAgent.runs = []
    await runner._run_agent(
        message=prepared_a.text,
        context_prompt="",
        history=[],
        source=source_a,
        session_id="session-a",
        session_key="agent:main:telegram:dm:chat-a",
        native_image_paths=prepared_a.native_image_paths,
        tool_image_reference_paths=prepared_a.tool_image_reference_paths,
    )

    assert len(_CapturingAgent.runs) == 1
    run = _CapturingAgent.runs[0]
    assert run["reference_paths"] == [str(image_a)]

    user_message = run["user_message"]
    assert isinstance(user_message, list)
    encoded_a = base64.b64encode(b"session-a-image").decode("ascii")
    encoded_b = base64.b64encode(b"session-b-image").decode("ascii")
    image_urls = [
        part["image_url"]["url"]
        for part in user_message
        if isinstance(part, dict) and part.get("type") == "image_url"
    ]
    assert any(encoded_a in url for url in image_urls)
    assert not any(encoded_b in url for url in image_urls)
