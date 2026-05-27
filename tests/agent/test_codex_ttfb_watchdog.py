"""Regression tests for the Codex time-to-first-byte watchdog."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest


def _make_codex_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("{}\n", encoding="utf-8")

    from run_agent import AIAgent

    agent = AIAgent(
        model="gpt-5.5",
        provider="openai-codex",
        api_key="sk-dummy",
        base_url="https://chatgpt.com/backend-api/codex",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        platform="cli",
    )
    agent.api_mode = "codex_responses"
    monkeypatch.setattr(agent, "_emit_status", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_compute_non_stream_stale_timeout", lambda *a, **k: 60.0)
    return agent


def test_ttfb_kills_when_no_stream_event(tmp_path, monkeypatch):
    agent = _make_codex_agent(tmp_path, monkeypatch)
    monkeypatch.setenv("HERMES_CODEX_TTFB_TIMEOUT_SECONDS", "1")

    closes: list[str] = []
    dummy_client = SimpleNamespace()
    monkeypatch.setattr(agent, "_create_request_openai_client", lambda **k: dummy_client)
    monkeypatch.setattr(agent, "_close_request_openai_client", lambda c, reason=None: closes.append(reason))

    stop = {"flag": False}

    def fake_hang(api_kwargs, client=None, on_first_delta=None):
        deadline = time.time() + 30
        while time.time() < deadline and not stop["flag"] and not agent._interrupt_requested:
            time.sleep(0.02)
        raise RuntimeError("connection closed")

    monkeypatch.setattr(agent, "_run_codex_stream", fake_hang)

    try:
        with pytest.raises(TimeoutError) as excinfo:
            agent._interruptible_api_call({"model": "gpt-5.5", "input": "hi"})
        assert "TTFB" in str(excinfo.value)
        assert "codex_ttfb_kill" in closes
    finally:
        stop["flag"] = True


def test_ttfb_status_includes_silent_hang_hint_for_gpt_5_5(tmp_path, monkeypatch):
    agent = _make_codex_agent(tmp_path, monkeypatch)
    monkeypatch.setenv("HERMES_CODEX_TTFB_TIMEOUT_SECONDS", "0.01")

    statuses: list[str] = []
    stop = {"flag": False}
    dummy_client = SimpleNamespace()
    monkeypatch.setattr(agent, "_emit_status", lambda msg, *a, **k: statuses.append(msg))
    monkeypatch.setattr(agent, "_create_request_openai_client", lambda **k: dummy_client)
    monkeypatch.setattr(agent, "_close_request_openai_client", lambda client, reason=None: None)

    def fake_hang(api_kwargs, client=None, on_first_delta=None):
        while not stop["flag"] and not agent._interrupt_requested:
            time.sleep(0.01)
        raise RuntimeError("connection closed")

    monkeypatch.setattr(agent, "_run_codex_stream", fake_hang)

    try:
        with pytest.raises(TimeoutError):
            agent._interruptible_api_call({"model": "gpt-5.5", "input": "hi"})
    finally:
        stop["flag"] = True

    assert statuses
    assert "Codex backend appears to be silently rejecting" in statuses[-1]
    assert "gpt-5.3-codex" in statuses[-1]


def test_ttfb_does_not_kill_after_any_stream_event(tmp_path, monkeypatch):
    agent = _make_codex_agent(tmp_path, monkeypatch)
    monkeypatch.setenv("HERMES_CODEX_TTFB_TIMEOUT_SECONDS", "1")

    closes: list[str] = []
    dummy_client = SimpleNamespace()
    monkeypatch.setattr(agent, "_create_request_openai_client", lambda **k: dummy_client)
    monkeypatch.setattr(agent, "_close_request_openai_client", lambda c, reason=None: closes.append(reason))

    sentinel = SimpleNamespace(ok=True)

    def fake_stream(api_kwargs, client=None, on_first_delta=None):
        agent._codex_stream_last_event_ts = time.time()
        time.sleep(1.2)
        return sentinel

    monkeypatch.setattr(agent, "_run_codex_stream", fake_stream)

    assert agent._interruptible_api_call({"model": "gpt-5.5", "input": "hi"}) is sentinel
    assert "codex_ttfb_kill" not in closes
