"""Tests for gateway warning when an unrecognized /command is dispatched.

Without this warning, unknown slash commands get forwarded to the LLM as plain
text, which often leads to silent failure (e.g. the model inventing a bogus
delegate_task call instead of telling the user the command doesn't exist).
"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource, build_session_key
from hermes_loop.store import LoopStore


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(text=text, source=_make_source(), message_id="m1")


def _make_runner():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)

    session_entry = SessionEntry(
        session_key=build_session_key(_make_source()),
        session_id="sess-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
    )
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = session_entry
    runner.session_store.load_transcript.return_value = []
    runner.session_store.has_any_sessions.return_value = True
    runner.session_store.append_to_transcript = MagicMock()
    runner.session_store.rewrite_transcript = MagicMock()
    runner.session_store.update_session = MagicMock()
    runner._running_agents = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._loop_states = {}
    runner._session_db = None
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._show_reasoning = False
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    runner._should_send_voice_reply = lambda *_args, **_kwargs: False
    runner._send_voice_reply = AsyncMock()
    runner._capture_gateway_honcho_if_configured = lambda *args, **kwargs: None
    runner._emit_gateway_run_progress = AsyncMock()
    return runner


def _read_background_reviews(tmp_path):
    path = tmp_path / "logs" / "background_reviews.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_loop_checkpoint(tmp_path, session_id="sess-1"):
    path = tmp_path / "state" / "loops" / session_id / "checkpoint.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _read_loop_events(tmp_path, session_id="sess-1"):
    path = tmp_path / "state" / "loops" / session_id / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _seed_loop_state(tmp_path, runner, *, session_id="sess-1", session_key=None, **state):
    from hermes_cli.loop import _stable_goal_id

    session_key = session_key or build_session_key(_make_source())
    is_active = bool(state.get("active", True))
    goal = str(state.get("goal") or "Keep going")
    payload = {
        "goal": goal,
        "goal_id": str(state.get("goal_id") or _stable_goal_id(session_id, goal)),
        "run_id": str(state.get("run_id") or "run-123"),
        "remaining_auto_turns": int(state.get("remaining_auto_turns", 0) or 0),
        "last_prompt": str(state.get("last_prompt") or ""),
        "last_prompt_norm": str(state.get("last_prompt_norm") or ""),
        "last_result_preview": str(state.get("last_result_preview") or ""),
        "channel_prompt": state.get("channel_prompt"),
        "active": is_active,
        "state": str(state.get("state") or ("waiting" if is_active else "stopped")),
        "resumable": bool(state.get("resumable", False)),
        "stop_reason": str(state.get("stop_reason") or ""),
        "stop_class": str(state.get("stop_class") or ""),
        "stop_message": str(state.get("stop_message") or ""),
        "last_progress_summary": str(state.get("last_progress_summary") or ""),
        "retry_count": int(state.get("retry_count", 0) or 0),
        "max_retry_budget": int(state.get("max_retry_budget", 2) or 0),
        "idle_timeout_seconds": int(state.get("idle_timeout_seconds", 900) or 0),
        "last_activity_at": str(state.get("last_activity_at") or ""),
        "pending_wakeup_at": str(state.get("pending_wakeup_at") or ""),
        "inflight_prompt": str(state.get("inflight_prompt") or ""),
        "inflight_started_at": str(state.get("inflight_started_at") or ""),
    }
    LoopStore().write_checkpoint(
        session_id=session_id,
        session_key=session_key,
        payload=payload,
    )
    runner._loop_states[session_key] = {"session_id": session_id, **payload}
    return session_key


@pytest.mark.asyncio
async def test_unknown_slash_command_returns_guidance(monkeypatch):
    """A genuinely unknown /foobar should return user-facing guidance, not
    silently drop through to the LLM."""
    import gateway.run as gateway_run

    runner = _make_runner()
    # If the LLM were called, this would fail: the guard must short-circuit
    # before _run_agent is invoked.
    runner._run_agent = AsyncMock(
        side_effect=AssertionError(
            "unknown slash command leaked through to the agent"
        )
    )

    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "***"}
    )

    result = await runner._handle_message(_make_event("/definitely-not-a-command"))

    assert result is not None
    assert "Unknown command" in result
    assert "/definitely-not-a-command" in result
    assert "/commands" in result
    runner._run_agent.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_slash_command_underscored_form_also_guarded(monkeypatch):
    """Telegram may send /foo_bar — same guard must trigger for underscored
    commands that normalize to unknown hyphenated names."""
    import gateway.run as gateway_run

    runner = _make_runner()
    runner._run_agent = AsyncMock(
        side_effect=AssertionError(
            "unknown slash command leaked through to the agent"
        )
    )

    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "***"}
    )

    result = await runner._handle_message(_make_event("/made_up_thing"))

    assert result is not None
    assert "Unknown command" in result
    assert "/made_up_thing" in result
    runner._run_agent.assert_not_called()


@pytest.mark.asyncio
async def test_known_slash_command_not_flagged_as_unknown(monkeypatch):
    """A real built-in like /status must NOT hit the unknown-command guard."""
    runner = _make_runner()
    # Make _handle_status_command exist via the normal path by running a real
    # dispatch. If the guard fires, the return string will mention "Unknown".
    runner._running_agents[build_session_key(_make_source())] = MagicMock()

    result = await runner._handle_message(_make_event("/status"))

    assert result is not None
    assert "Unknown command" not in result


@pytest.mark.asyncio
async def test_underscored_alias_for_hyphenated_builtin_not_flagged(monkeypatch):
    """Telegram autocomplete sends /reload_mcp for the /reload-mcp built-in.
    That must NOT be flagged as unknown."""
    import gateway.run as gateway_run

    runner = _make_runner()
    # Prevent real MCP work; we only care that the unknown guard doesn't fire.
    async def _noop_reload(*_a, **_kw):
        return "mcp reloaded"

    runner._handle_reload_mcp_command = _noop_reload  # type: ignore[attr-defined]

    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "***"}
    )

    result = await runner._handle_message(_make_event("/reload_mcp"))

    # Whatever /reload_mcp returns, it must not be the unknown-command guard.
    if result is not None:
        assert "Unknown command" not in result


@pytest.mark.asyncio
async def test_loop_built_in_command_routes_through_bounded_controller(monkeypatch, tmp_path):
    import gateway.run as gateway_run

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    runner._handle_message_with_agent = AsyncMock(return_value="handled")

    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "***"}
    )

    with patch(
        "hermes_cli.loop.decide_continuation_for_session",
        return_value={
            "action": "continue",
            "reason": "clear next slice",
            "next_prompt": "Implement the next thin slice and verify it.",
            "session_id": "sess-1",
        },
    ) as mock_decide:
        result = await runner._handle_message(_make_event("/loop 請繼續完成後續任務"))

    assert result == "handled"
    mock_decide.assert_called_once_with("sess-1", "請繼續完成後續任務")
    assert runner._loop_states[build_session_key(_make_source())]["goal"] == "請繼續完成後續任務"
    assert runner._loop_states[build_session_key(_make_source())]["remaining_auto_turns"] == 2
    assert runner._loop_states[build_session_key(_make_source())]["goal_id"]
    assert runner._loop_states[build_session_key(_make_source())]["run_id"]
    checkpoint = _read_loop_checkpoint(tmp_path)
    assert checkpoint["goal_id"] == runner._loop_states[build_session_key(_make_source())]["goal_id"]
    assert checkpoint["run_id"] == runner._loop_states[build_session_key(_make_source())]["run_id"]
    events = _read_loop_events(tmp_path)
    assert events[-1]["event_type"] == "loop_started"
    assert events[-1]["goal_id"] == checkpoint["goal_id"]
    assert events[-1]["run_id"] == checkpoint["run_id"]
    runner._handle_message_with_agent.assert_awaited_once()
    forwarded_event = runner._handle_message_with_agent.await_args.args[0]
    assert forwarded_event.text == "Implement the next thin slice and verify it."


@pytest.mark.asyncio
async def test_loop_built_in_command_returns_stop_reason_without_running_agent(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    runner._handle_message_with_agent = AsyncMock(return_value="handled")

    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "***"}
    )

    with patch(
        "hermes_cli.loop.decide_continuation_for_session",
        return_value={
            "action": "stop",
            "reason": "No clear bounded next step.",
            "stop_reason": "model_stop",
            "session_id": "sess-1",
        },
    ):
        result = await runner._handle_message(_make_event("/loop"))

    assert result == "Loop stopped: No clear bounded next step. (model_stop)"
    runner._handle_message_with_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_loop_built_in_command_falls_back_to_skill_mode_on_controller_error(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    runner._handle_message_with_agent = AsyncMock(return_value="handled")

    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "***"}
    )

    with patch(
        "hermes_cli.loop.decide_continuation_for_session",
        side_effect=RuntimeError("boom"),
    ), patch(
        "agent.skill_commands.build_multi_skill_invocation_message",
        return_value='[SYSTEM: The user has invoked the "continuation-loop-controller-slices" skill.]',
    ) as mock_build:
        result = await runner._handle_message(_make_event("/loop 請繼續完成後續任務"))

    assert result == "handled"
    mock_build.assert_called_once()
    assert mock_build.call_args.args[0] == [
        "/continuation-loop-controller-slices",
        "/autonomous-continuation-loop",
    ]
    assert mock_build.call_args.args[1] == "請繼續完成後續任務"
    assert "sess-1" in mock_build.call_args.kwargs["runtime_note"]
    runner._handle_message_with_agent.assert_awaited_once()
    forwarded_event = runner._handle_message_with_agent.await_args.args[0]
    assert "continuation-loop-controller-slices" in forwarded_event.text


@pytest.mark.asyncio
async def test_maybe_schedule_loop_followup_returns_internal_event(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    session_key = _seed_loop_state(
        tmp_path,
        runner,
        goal="Keep going",
        remaining_auto_turns=2,
        last_prompt_norm="initial prompt",
        last_result_preview="",
    )

    with patch(
        "hermes_cli.loop.decide_continuation_for_session",
        return_value={
            "action": "continue",
            "reason": "clear next slice",
            "next_prompt": "Implement the next thin slice.",
        },
    ), patch(
        "hermes_cli.loop.verify_progress_for_session",
        return_value={"verdict": "progress", "reason": "real progress", "should_continue": True},
    ):
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-1",
            source=_make_source(),
            final_response="Implemented the next thin slice in tests/foo.py.",
        )

    assert event is not None
    assert stop_notice is None
    assert event.internal is True
    assert event.text == "Implement the next thin slice."
    assert runner._loop_states[session_key]["remaining_auto_turns"] == 1
    assert runner._loop_states[session_key]["last_result_preview"] == "Implemented the next thin slice in tests/foo.py."
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "meaningful_result"
    assert reviews[-1]["source"] == "bounded_loop_gateway"
    checkpoint = _read_loop_checkpoint(tmp_path)
    assert checkpoint["remaining_auto_turns"] == 1
    assert checkpoint["last_result_preview"] == "Implemented the next thin slice in tests/foo.py."
    assert checkpoint["goal_id"] == runner._loop_states[session_key]["goal_id"]
    assert checkpoint["run_id"] == runner._loop_states[session_key]["run_id"]
    events = _read_loop_events(tmp_path)
    assert events[-1]["event_type"] == "loop_followup_scheduled"
    assert events[-1]["goal_id"] == checkpoint["goal_id"]
    assert events[-1]["run_id"] == checkpoint["run_id"]


@pytest.mark.asyncio
async def test_maybe_schedule_loop_followup_stops_on_repeated_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    session_key = _seed_loop_state(
        tmp_path,
        runner,
        goal="Keep going",
        remaining_auto_turns=2,
        last_prompt_norm="implement the next thin slice.",
        last_result_preview="fresh result",
    )

    with patch(
        "hermes_cli.loop.decide_continuation_for_session",
        return_value={
            "action": "continue",
            "reason": "clear next slice",
            "next_prompt": "Implement the next thin slice.",
        },
    ), patch(
        "hermes_cli.loop.verify_progress_for_session",
        return_value={"verdict": "progress", "reason": "real progress", "should_continue": True},
    ):
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-1",
            source=_make_source(),
            final_response="Different new result tests/foo.py",
        )

    assert event is None
    assert "repeated next prompt" in stop_notice.lower()
    assert session_key not in runner._loop_states
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "repeated_prompt"
    assert reviews[-1]["stop_reason"] == "repeated_next_prompt"


@pytest.mark.asyncio
async def test_maybe_schedule_loop_followup_stops_on_duplicate_result_preview(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    session_key = _seed_loop_state(
        tmp_path,
        runner,
        goal="Keep going",
        remaining_auto_turns=2,
        last_prompt_norm="different prompt",
        last_result_preview="Repeated summary tests/foo.py",
    )

    with patch(
        "hermes_cli.loop.decide_continuation_for_session",
        return_value={
            "action": "continue",
            "reason": "clear next slice",
            "next_prompt": "Do the next thing.",
        },
    ), patch(
        "hermes_cli.loop.verify_progress_for_session",
        return_value={"verdict": "progress", "reason": "real progress", "should_continue": True},
    ):
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-1",
            source=_make_source(),
            final_response="Repeated summary tests/foo.py",
        )

    assert event is None
    assert "no meaningful new result" in stop_notice.lower()
    assert session_key not in runner._loop_states
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "duplicate_result"
    assert reviews[-1]["stop_reason"] == "duplicate_result_preview"


@pytest.mark.asyncio
async def test_maybe_schedule_loop_followup_stops_on_semantic_stall(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    session_key = _seed_loop_state(
        tmp_path,
        runner,
        goal="Keep going",
        remaining_auto_turns=2,
        last_prompt_norm="different prompt",
        last_result_preview="Older result",
    )

    with patch(
        "hermes_cli.loop.verify_progress_for_session",
        return_value={"verdict": "stalled", "reason": "Mostly restated prior status.", "should_continue": False},
    ):
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-1",
            source=_make_source(),
            final_response="Fresh result tests/foo.py",
        )

    assert event is None
    assert (
        "did not materially advance" in stop_notice.lower()
        or "no meaningful new result" in stop_notice.lower()
        or "mostly restated prior status" in stop_notice.lower()
    )
    assert session_key not in runner._loop_states
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "semantic_stall"
    assert reviews[-1]["stop_reason"] == "progress_verifier_stalled"


@pytest.mark.asyncio
async def test_maybe_schedule_loop_followup_stops_on_semantic_done(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    session_key = _seed_loop_state(
        tmp_path,
        runner,
        goal="Keep going",
        remaining_auto_turns=2,
        last_prompt_norm="different prompt",
        last_result_preview="Older result",
    )

    with patch(
        "hermes_cli.loop.verify_progress_for_session",
        return_value={"verdict": "done", "reason": "Latest continuation appears effectively complete.", "should_continue": False},
    ):
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-1",
            source=_make_source(),
            final_response="Fresh result tests/foo.py",
        )

    assert event is None
    assert "effectively complete" in stop_notice.lower() or "no clear bounded next step" in stop_notice.lower()
    assert session_key not in runner._loop_states
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "semantic_done"
    assert reviews[-1]["stop_reason"] == "progress_verifier_done"


@pytest.mark.asyncio
async def test_maybe_schedule_loop_followup_stops_on_missing_observable_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    session_key = _seed_loop_state(
        tmp_path,
        runner,
        goal="Keep going",
        remaining_auto_turns=2,
        last_prompt_norm="different prompt",
        last_result_preview="Older result tests/foo.py",
    )

    with patch(
        "hermes_cli.loop.verify_progress_for_session",
        return_value={"verdict": "progress", "reason": "looks fine", "should_continue": True},
    ) as mock_verifier, patch(
        "hermes_cli.loop.decide_continuation_for_session",
        return_value={"action": "continue", "reason": "more to do", "next_prompt": "Keep going."},
    ) as mock_decide:
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-1",
            source=_make_source(),
            final_response="All good, I implemented and verified everything. Done.",
        )

    assert event is None
    assert "observable evidence" in stop_notice.lower()
    assert session_key not in runner._loop_states
    mock_verifier.assert_not_called()
    mock_decide.assert_not_called()
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "missing_observable_evidence"
    assert reviews[-1]["stop_reason"] == "missing_observable_evidence"


@pytest.mark.asyncio
async def test_maybe_schedule_loop_followup_reports_max_auto_turns(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    session_key = _seed_loop_state(
        tmp_path,
        runner,
        goal="Keep going",
        remaining_auto_turns=0,
        last_prompt_norm="prompt",
        last_result_preview="Recent progress",
    )

    event, stop_notice = await runner._maybe_schedule_loop_followup(
        session_key=session_key,
        session_id="sess-1",
        source=_make_source(),
        final_response="Recent progress",
    )

    assert event is None
    assert "auto-turn budget" in stop_notice.lower()
    assert session_key not in runner._loop_states
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "max_auto_turns"
    assert reviews[-1]["stop_reason"] == "max_auto_turns_reached"


def test_apply_loop_stop_notice_appends_to_final_response():
    runner = _make_runner()
    result = {"final_response": "Did step 1"}

    updated = runner._apply_loop_stop_notice(result, "Loop stopped: repeated next prompt (repeated_next_prompt)")

    assert updated["final_response"] == "Did step 1\n\nLoop stopped: repeated next prompt (repeated_next_prompt)"


@pytest.mark.asyncio
async def test_non_loop_user_message_clears_existing_loop_state(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    runner._handle_message_with_agent = AsyncMock(return_value="handled")
    runner._loop_states[build_session_key(_make_source())] = {
        "goal": "Keep going",
        "remaining_auto_turns": 2,
        "last_prompt_norm": "implement the next thin slice.",
    }

    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "***"}
    )

    await runner._handle_message(_make_event("hello"))

    assert build_session_key(_make_source()) not in runner._loop_states


@pytest.mark.asyncio
async def test_direct_continuation_skill_routes_through_bounded_controller(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    runner._handle_message_with_agent = AsyncMock(return_value="handled")

    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "***"}
    )

    with patch(
        "agent.skill_commands.get_skill_commands",
        return_value={
            "/continuation-loop-controller-slices": {
                "name": "continuation-loop-controller-slices"
            },
            "/autonomous-continuation-loop": {
                "name": "autonomous-continuation-loop"
            },
        },
    ), patch(
        "hermes_cli.loop.decide_continuation_for_session",
        return_value={
            "action": "continue",
            "reason": "clear next slice",
            "next_prompt": "Implement the next thin slice and verify it.",
            "session_id": "sess-1",
        },
    ) as mock_decide:
        result = await runner._handle_message(
            _make_event("/continuation-loop-controller-slices 請繼續")
        )

    assert result == "handled"
    mock_decide.assert_called_once_with("sess-1", "請繼續")
    assert runner._loop_states[build_session_key(_make_source())]["remaining_auto_turns"] == 2
    forwarded_event = runner._handle_message_with_agent.await_args.args[0]
    assert forwarded_event.text == "Implement the next thin slice and verify it."


@pytest.mark.asyncio
async def test_bare_loop_invocation_routes_through_bounded_controller(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    runner._handle_message_with_agent = AsyncMock(return_value="handled")

    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "***"}
    )

    with patch(
        "hermes_cli.loop.decide_continuation_for_session",
        return_value={
            "action": "continue",
            "reason": "clear next slice",
            "next_prompt": "Implement the next thin slice and verify it.",
            "session_id": "sess-1",
        },
    ) as mock_decide:
        result = await runner._handle_message(
            _make_event("loop\n請繼續完成後續任務\n多和 Claude 辯論 + 討論")
        )

    assert result == "handled"
    mock_decide.assert_called_once_with("sess-1", "請繼續完成後續任務\n多和 Claude 辯論 + 討論")
    assert runner._loop_states[build_session_key(_make_source())]["remaining_auto_turns"] == 2
    runner._handle_message_with_agent.assert_awaited_once()
    forwarded_event = runner._handle_message_with_agent.await_args.args[0]
    assert forwarded_event.text == "Implement the next thin slice and verify it."


@pytest.mark.asyncio
async def test_bare_continuation_skill_invocation_routes_through_bounded_controller(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    runner._handle_message_with_agent = AsyncMock(return_value="handled")

    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "***"}
    )

    with patch(
        "agent.skill_commands.get_skill_commands",
        return_value={
            "/continuation-loop-controller-slices": {
                "name": "continuation-loop-controller-slices"
            },
            "/autonomous-continuation-loop": {
                "name": "autonomous-continuation-loop"
            },
        },
    ), patch(
        "hermes_cli.loop.decide_continuation_for_session",
        return_value={
            "action": "continue",
            "reason": "clear next slice",
            "next_prompt": "Implement the next thin slice and verify it.",
            "session_id": "sess-1",
        },
    ) as mock_decide:
        result = await runner._handle_message(
            _make_event("continuation-loop-controller-slices\n請繼續完成後續任務")
        )

    assert result == "handled"
    mock_decide.assert_called_once_with("sess-1", "請繼續完成後續任務")
    assert runner._loop_states[build_session_key(_make_source())]["remaining_auto_turns"] == 2
    forwarded_event = runner._handle_message_with_agent.await_args.args[0]
    assert forwarded_event.text == "Implement the next thin slice and verify it."