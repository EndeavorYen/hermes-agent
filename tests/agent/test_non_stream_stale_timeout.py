"""Tests for Codex non-stream stale-call timeout sizing."""

from __future__ import annotations

from pathlib import Path


def _write_config(tmp_path: Path, body: str) -> None:
    (tmp_path / "config.yaml").write_text(body or "{}\n", encoding="utf-8")


def _make_agent(tmp_path: Path, **overrides):
    from run_agent import AIAgent

    kwargs = dict(
        model="gpt-5.5",
        provider="openai-codex",
        api_key="sk-dummy",
        base_url="https://chatgpt.com/backend-api/codex",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        platform="cli",
    )
    kwargs.update(overrides)
    return AIAgent(**kwargs)


def test_estimator_responses_api_long_session_triggers_tier():
    from agent.chat_completion_helpers import estimate_request_context_tokens

    payload = {
        "model": "gpt-5.5",
        "input": "x" * 240_000,
        "instructions": "s" * 4000,
    }

    assert estimate_request_context_tokens(payload) > 50_000


def test_estimator_bare_list_back_compat():
    from agent.chat_completion_helpers import estimate_request_context_tokens

    messages = [{"role": "user", "content": "x" * 800}]

    assert estimate_request_context_tokens(messages) >= 200


def test_default_base_is_90s(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("", encoding="utf-8")
    monkeypatch.delenv("HERMES_API_CALL_STALE_TIMEOUT", raising=False)
    _write_config(tmp_path, "")

    agent = _make_agent(tmp_path)

    assert agent._resolved_api_call_stale_timeout_base() == (90.0, True)


def test_long_codex_request_bumps_to_50k_tier(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("", encoding="utf-8")
    monkeypatch.delenv("HERMES_API_CALL_STALE_TIMEOUT", raising=False)
    _write_config(tmp_path, "")

    agent = _make_agent(tmp_path)
    payload = {"model": "gpt-5.5", "input": "x" * 240_000, "instructions": ""}

    assert agent._compute_non_stream_stale_timeout(payload) == 150.0


def test_very_long_codex_request_bumps_to_100k_tier(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("", encoding="utf-8")
    monkeypatch.delenv("HERMES_API_CALL_STALE_TIMEOUT", raising=False)
    _write_config(tmp_path, "")

    agent = _make_agent(tmp_path)
    payload = {"model": "gpt-5.5", "input": "x" * 500_000, "instructions": ""}

    assert agent._compute_non_stream_stale_timeout(payload) == 240.0


def test_explicit_user_config_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("", encoding="utf-8")
    _write_config(
        tmp_path,
        """\
providers:
  openai-codex:
    stale_timeout_seconds: 1800
""",
    )
    monkeypatch.delenv("HERMES_API_CALL_STALE_TIMEOUT", raising=False)

    import importlib
    from hermes_cli import timeouts as to_mod

    importlib.reload(to_mod)

    agent = _make_agent(tmp_path)

    assert agent._compute_non_stream_stale_timeout({"input": "hi"}) == 1800.0
