import json
import logging
import sys
import types
from types import SimpleNamespace

sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))
sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))
sys.modules.setdefault("fal_client", types.SimpleNamespace())

import run_agent


def _patch_agent_bootstrap(monkeypatch):
    monkeypatch.setattr(
        run_agent,
        "get_tool_definitions",
        lambda **kwargs: [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )
    monkeypatch.setattr(run_agent, "check_toolset_requirements", lambda: {})


def _message_response(text: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    role="assistant",
                    content=text,
                    tool_calls=None,
                    reasoning_content=None,
                ),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        model="gpt-5.5",
    )


def test_run_conversation_emits_request_budget_payload(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("{}\n", encoding="utf-8")
    _patch_agent_bootstrap(monkeypatch)

    agent = run_agent.AIAgent(
        model="gpt-5.5",
        provider="openai",
        api_mode="chat_completions",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        quiet_mode=True,
        max_iterations=2,
        skip_context_files=True,
        skip_memory=True,
        platform="slack",
    )
    agent._cleanup_task_resources = lambda task_id: None
    agent._persist_session = lambda messages, history=None: None
    agent._save_trajectory = lambda messages, user_message, completed: None
    agent._save_session_log = lambda messages: None
    agent._disable_streaming = True
    monkeypatch.setattr(agent, "_interruptible_api_call", lambda api_kwargs: _message_response("OK"))

    with caplog.at_level(logging.INFO):
        result = agent.run_conversation("hello")

    assert result["final_response"] == "OK"
    payload = result["request_budget"]
    assert payload["tool_schema_tokens"] > 0
    assert payload["model_ttfb_ms"] is not None
    assert payload["tool_execution_ms"] == 0

    records = [
        r.getMessage().split("request_budget.v1 ", 1)[1]
        for r in caplog.records
        if "request_budget.v1 " in r.getMessage()
    ]
    assert records
    logged = json.loads(records[-1])
    assert logged["session_id"] == agent.session_id
    assert logged["tool_schema_tokens"] == payload["tool_schema_tokens"]
