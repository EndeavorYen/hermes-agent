import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.session import SessionSource, build_session_key
from hermes_loop.store import LoopStore


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_runner():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    runner.adapters = {}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=None, loaded_hooks=False)
    runner._running_agents = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._loop_states = {}
    runner._session_db = None
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._show_reasoning = False
    runner._background_tasks = set()
    return runner


def _read_loop_checkpoint(tmp_path, session_id):
    path = tmp_path / "state" / "loops" / session_id / "checkpoint.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_hydrate_loop_states_from_store_recovers_only_active_well_formed_checkpoints(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    store = LoopStore()
    source = _make_source()
    session_key = build_session_key(source)

    store.write_checkpoint(
        session_id="sess-active",
        session_key=session_key,
        payload={
            "goal": "Keep going",
            "goal_id": "goal-active",
            "run_id": "run-active",
            "expected_evidence": "tests/foo.py",
            "remaining_auto_turns": 2,
            "last_prompt": "Implement the next thin slice.",
            "last_prompt_norm": "implement the next thin slice.",
            "last_result_preview": "",
            "channel_prompt": "channel prompt",
            "active": True,
        },
    )
    store.write_checkpoint(
        session_id="sess-inactive",
        session_key="telegram:u2:c2",
        payload={
            "goal": "Stopped loop",
            "remaining_auto_turns": 0,
            "last_prompt_norm": "",
            "last_result_preview": "done",
            "active": False,
        },
    )
    broken_dir = tmp_path / "state" / "loops" / "sess-bad"
    broken_dir.mkdir(parents=True, exist_ok=True)
    (broken_dir / "checkpoint.json").write_text(
        json.dumps({
            "session_id": "sess-bad",
            "goal": "Missing session key",
            "remaining_auto_turns": 1,
            "active": True,
        }),
        encoding="utf-8",
    )

    recovered = runner._hydrate_loop_states_from_store()

    assert recovered == 1
    assert list(runner._loop_states) == [session_key]
    assert runner._loop_states[session_key] == {
        "session_id": "sess-active",
        "goal": "Keep going",
        "remaining_auto_turns": 2,
        "last_prompt": "Implement the next thin slice.",
        "last_prompt_norm": "implement the next thin slice.",
        "last_result_preview": "",
        "channel_prompt": "channel prompt",
        "active": True,
        "state": "waiting",
        "resumable": False,
        "stop_reason": "",
        "stop_class": "",
        "stop_message": "",
        "last_progress_summary": "",
        "retry_count": 0,
        "max_retry_budget": 2,
        "idle_timeout_seconds": 900,
        "last_activity_at": "",
        "pending_wakeup_at": "",
        "inflight_prompt": "",
        "inflight_started_at": "",
        "goal_id": "goal-active",
        "run_id": "run-active",
        "expected_evidence": "tests/foo.py",
    }


@pytest.mark.asyncio
async def test_recovered_loop_state_can_drive_followup_logic(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    store = LoopStore()
    source = _make_source()
    session_key = build_session_key(source)

    store.write_checkpoint(
        session_id="sess-active",
        session_key=session_key,
        payload={
            "goal": "Keep going",
            "goal_id": "goal-active",
            "run_id": "run-active",
            "remaining_auto_turns": 2,
            "last_prompt": "Implement the next thin slice.",
            "last_prompt_norm": "different prompt",
            "last_result_preview": "previous result",
            "expected_evidence": "tests/gateway/test_loop_recovery.py",
            "channel_prompt": None,
            "active": True,
        },
    )
    store.write_goal_artifact(
        session_id="sess-active",
        goal_id="goal-active",
        goal_text="Keep going",
        created_by="gateway",
        session_key=session_key,
    )

    recovered = runner._hydrate_loop_states_from_store()

    assert recovered == 1
    with patch(
        "hermes_cli.loop.decide_continuation_for_session",
        return_value={
            "action": "continue",
            "reason": "clear next slice",
            "next_prompt": "Implement the next thin slice.",
            "expected_evidence": "tests/gateway/test_loop_recovery.py",
        },
    ), patch(
        "hermes_cli.loop.verify_progress_for_session",
        return_value={"verdict": "progress", "reason": "real progress", "should_continue": True},
    ):
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-active",
            source=source,
            final_response="Updated tests/gateway/test_loop_recovery.py and reran pytest -q.",
        )

    assert stop_notice is None
    assert event is not None
    assert event.internal is True
    assert event.text == "Implement the next thin slice."
    assert runner._loop_states[session_key]["remaining_auto_turns"] == 1
    assert runner._loop_states[session_key]["last_result_preview"] == "Updated tests/gateway/test_loop_recovery.py and reran pytest -q."
    checkpoint = _read_loop_checkpoint(tmp_path, "sess-active")
    assert checkpoint["session_key"] == session_key
    assert checkpoint["remaining_auto_turns"] == 1
    assert checkpoint["last_prompt"] == "Implement the next thin slice."
    assert checkpoint["last_result_preview"] == "Updated tests/gateway/test_loop_recovery.py and reran pytest -q."
    assert checkpoint["active"] is True
    assert checkpoint["goal_id"] == runner._loop_states[session_key]["goal_id"]
    assert checkpoint["run_id"] == runner._loop_states[session_key]["run_id"]


@pytest.mark.asyncio
async def test_followup_stops_when_persisted_checkpoint_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    source = _make_source()
    session_key = build_session_key(source)
    runner._loop_states[session_key] = {
        "session_id": "sess-active",
        "goal": "Keep going",
        "remaining_auto_turns": 2,
        "last_prompt": "Implement the next thin slice.",
        "last_prompt_norm": "different prompt",
        "last_result_preview": "previous result",
        "active": True,
    }

    event, stop_notice = await runner._maybe_schedule_loop_followup(
        session_key=session_key,
        session_id="sess-active",
        source=source,
        final_response="Implemented a fresh result.",
    )

    assert event is None
    assert "checkpoint" in stop_notice.lower()
    assert session_key not in runner._loop_states


@pytest.mark.asyncio
async def test_followup_stops_when_persisted_checkpoint_diverges_from_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    store = LoopStore()
    source = _make_source()
    session_key = build_session_key(source)

    store.write_checkpoint(
        session_id="sess-active",
        session_key=session_key,
        payload={
            "goal": "Keep going",
            "remaining_auto_turns": 1,
            "last_prompt": "Checkpoint prompt",
            "last_prompt_norm": "checkpoint prompt",
            "last_result_preview": "persisted preview",
            "channel_prompt": None,
            "active": True,
        },
    )
    runner._loop_states[session_key] = {
        "session_id": "sess-active",
        "goal": "Keep going",
        "remaining_auto_turns": 2,
        "last_prompt": "Implement the next thin slice.",
        "last_prompt_norm": "different prompt",
        "last_result_preview": "previous result",
        "active": True,
    }

    event, stop_notice = await runner._maybe_schedule_loop_followup(
        session_key=session_key,
        session_id="sess-active",
        source=source,
        final_response="Implemented a fresh result.",
    )

    assert event is None
    assert "diverged" in stop_notice.lower()
    assert session_key not in runner._loop_states
    checkpoint = _read_loop_checkpoint(tmp_path, "sess-active")
    assert checkpoint["active"] is False
    assert checkpoint["stop_reason"] == "loop_checkpoint_mismatch"


@pytest.mark.asyncio
async def test_resume_recovered_loops_replays_persisted_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    source = _make_source()
    session_key = build_session_key(source)
    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-active",
        session_key=session_key,
        payload={
            "goal": "Keep going",
            "remaining_auto_turns": 1,
            "last_prompt": "Implement the next thin slice.",
            "last_prompt_norm": "implement the next thin slice.",
            "last_result_preview": "",
            "channel_prompt": "channel prompt",
            "active": True,
        },
    )
    runner._loop_states[session_key] = {
        "session_id": "sess-active",
        "goal": "Keep going",
        "remaining_auto_turns": 1,
        "last_prompt": "Implement the next thin slice.",
        "last_prompt_norm": "implement the next thin slice.",
        "last_result_preview": "",
        "channel_prompt": "channel prompt",
        "active": True,
    }
    runner.session_store = SimpleNamespace(
        _ensure_loaded=lambda: None,
        _entries={session_key: SimpleNamespace(origin=source)},
    )

    seen = []
    handled = asyncio.Event()

    async def _fake_handle_message(event):
        seen.append(event)
        handled.set()
        return None

    runner._handle_message = _fake_handle_message

    resumed = runner._resume_recovered_loops()
    await asyncio.wait_for(handled.wait(), timeout=1)

    assert resumed == 1
    assert len(seen) == 1
    assert seen[0].internal is True
    assert seen[0].text == "Implement the next thin slice."
    assert seen[0].channel_prompt == "channel prompt"


@pytest.mark.asyncio
async def test_resume_recovered_loops_skips_future_wakeup(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    source = _make_source()
    session_key = build_session_key(source)
    future_wakeup = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    runner._loop_states[session_key] = {
        "session_id": "sess-active",
        "goal": "Keep going",
        "remaining_auto_turns": 1,
        "last_prompt": "Implement the next thin slice.",
        "last_prompt_norm": "implement the next thin slice.",
        "last_result_preview": "",
        "pending_wakeup_at": future_wakeup,
        "channel_prompt": "channel prompt",
        "active": True,
    }
    runner.session_store = SimpleNamespace(
        _ensure_loaded=lambda: None,
        _entries={session_key: SimpleNamespace(origin=source)},
    )
    runner._handle_message = AsyncMock()

    class _FakeRuntime:
        def resume(self, session_id, **kwargs):
            return {
                "ok": True,
                "should_tick_now": False,
                "checkpoint": {
                    **runner._loop_states[session_key],
                    "session_id": session_id,
                    "session_key": session_key,
                    "pending_wakeup_at": future_wakeup,
                    "last_activity_at": "runtime-future",
                },
            }

    with patch("gateway.run.LoopRuntime", return_value=_FakeRuntime()):
        resumed = runner._resume_recovered_loops()

    assert resumed == 0
    runner._handle_message.assert_not_awaited()
    assert runner._loop_states[session_key]["pending_wakeup_at"] == future_wakeup


@pytest.mark.asyncio
async def test_resume_recovered_loops_replays_due_wakeup_via_runtime_resume(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    source = _make_source()
    session_key = build_session_key(source)
    due_wakeup = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    runner._loop_states[session_key] = {
        "session_id": "sess-active",
        "goal": "Keep going",
        "remaining_auto_turns": 1,
        "last_prompt": "Implement the next thin slice.",
        "last_prompt_norm": "implement the next thin slice.",
        "last_result_preview": "",
        "pending_wakeup_at": due_wakeup,
        "channel_prompt": "channel prompt",
        "active": True,
    }
    runner.session_store = SimpleNamespace(
        _ensure_loaded=lambda: None,
        _entries={session_key: SimpleNamespace(origin=source)},
    )

    seen = []
    handled = asyncio.Event()
    runtime_calls = []

    async def _fake_handle_message(event):
        seen.append(event)
        handled.set()
        return None

    runner._handle_message = _fake_handle_message

    class _FakeRuntime:
        def resume(self, session_id, **kwargs):
            runtime_calls.append((session_id, kwargs))
            return {
                "ok": True,
                "should_tick_now": True,
                "checkpoint": {
                    **runner._loop_states[session_key],
                    "session_id": session_id,
                    "session_key": session_key,
                    "pending_wakeup_at": "",
                    "last_activity_at": "runtime-updated",
                },
            }

    with patch("gateway.run.LoopRuntime", return_value=_FakeRuntime()):
        resumed = runner._resume_recovered_loops()
    await asyncio.wait_for(handled.wait(), timeout=1)

    assert resumed == 1
    assert runtime_calls == [
        (
            "sess-active",
            {
                "message": "Loop resumed by due wake recovery.",
                "metadata": {"resume_reason": "due_wake_recovery", "resume_source": "gateway_watcher"},
            },
        )
    ]
    assert len(seen) == 1
    assert seen[0].text == "Implement the next thin slice."
    assert runner._loop_states[session_key]["pending_wakeup_at"] == ""
    assert runner._loop_states[session_key]["last_activity_at"] == "runtime-updated"


@pytest.mark.asyncio
async def test_queue_due_loop_event_uses_runtime_checkpoint_for_enqueued_message(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    source = _make_source()
    session_key = build_session_key(source)
    due_wakeup = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    runner._loop_states[session_key] = {
        "session_id": "sess-active",
        "goal": "Keep going",
        "remaining_auto_turns": 1,
        "last_prompt": "stale prompt",
        "last_prompt_norm": "stale prompt",
        "last_result_preview": "",
        "pending_wakeup_at": due_wakeup,
        "channel_prompt": "stale channel prompt",
        "active": True,
    }
    runner.session_store = SimpleNamespace(
        _ensure_loaded=lambda: None,
        _entries={session_key: SimpleNamespace(origin=source)},
    )

    seen = []
    handled = asyncio.Event()

    async def _fake_handle_message(event):
        seen.append(event)
        handled.set()
        return None

    runner._handle_message = _fake_handle_message

    class _FakeRuntime:
        def resume(self, session_id, **kwargs):
            return {
                "ok": True,
                "should_tick_now": True,
                "checkpoint": {
                    **runner._loop_states[session_key],
                    "session_id": session_id,
                    "session_key": session_key,
                    "pending_wakeup_at": "",
                    "last_prompt": "Prompt from runtime checkpoint",
                    "last_prompt_norm": "prompt from runtime checkpoint",
                    "channel_prompt": "runtime channel prompt",
                    "last_activity_at": "runtime-updated",
                },
            }

    with patch("gateway.run.LoopRuntime", return_value=_FakeRuntime()):
        queued = runner._queue_due_loop_event(session_key, runner._loop_states[session_key])
    await asyncio.wait_for(handled.wait(), timeout=1)

    assert queued is True
    assert len(seen) == 1
    assert seen[0].text == "Prompt from runtime checkpoint"
    assert seen[0].channel_prompt == "runtime channel prompt"
    assert runner._loop_states[session_key]["last_prompt"] == "Prompt from runtime checkpoint"
    assert runner._loop_states[session_key]["channel_prompt"] == "runtime channel prompt"


@pytest.mark.asyncio
async def test_queue_due_loop_event_does_not_enqueue_when_runtime_resume_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    source = _make_source()
    session_key = build_session_key(source)
    runner._loop_states[session_key] = {
        "session_id": "sess-active",
        "goal": "Keep going",
        "remaining_auto_turns": 1,
        "last_prompt": "Implement the next thin slice.",
        "last_prompt_norm": "implement the next thin slice.",
        "last_result_preview": "",
        "pending_wakeup_at": "",
        "channel_prompt": "channel prompt",
        "active": True,
    }
    runner.session_store = SimpleNamespace(
        _ensure_loaded=lambda: None,
        _entries={session_key: SimpleNamespace(origin=source)},
    )
    runner._handle_message = AsyncMock()

    class _FakeRuntime:
        def resume(self, session_id, **kwargs):
            return {"ok": False, "error": "missing_prompt", "checkpoint": runner._loop_states[session_key]}

    with patch("gateway.run.LoopRuntime", return_value=_FakeRuntime()):
        queued = runner._queue_due_loop_event(session_key, runner._loop_states[session_key])

    assert queued is False
    runner._handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_recovered_loops_pauses_when_origin_cannot_be_rebuilt(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    source = _make_source()
    session_key = build_session_key(source)
    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-active",
        session_key=session_key,
        payload={
            "goal": "Keep going",
            "remaining_auto_turns": 1,
            "last_prompt": "Implement the next thin slice.",
            "last_prompt_norm": "implement the next thin slice.",
            "last_result_preview": "",
            "active": True,
        },
    )
    runner._loop_states[session_key] = {
        "session_id": "sess-active",
        "goal": "Keep going",
        "remaining_auto_turns": 1,
        "last_prompt": "Implement the next thin slice.",
        "last_prompt_norm": "implement the next thin slice.",
        "last_result_preview": "",
        "active": True,
    }
    runner.session_store = SimpleNamespace(_ensure_loaded=lambda: None, _entries={})
    runner._handle_message = AsyncMock()

    resumed = runner._resume_recovered_loops()

    assert resumed == 0
    runner._handle_message.assert_not_awaited()
    assert session_key not in runner._loop_states
    checkpoint = _read_loop_checkpoint(tmp_path, "sess-active")
    assert checkpoint["active"] is False
    assert checkpoint["state"] == "paused"
    assert checkpoint["stop_reason"] == "recovery_incomplete"


@pytest.mark.asyncio
async def test_queue_due_loop_event_does_not_enqueue_when_runtime_resume_returns_no_tick(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    source = _make_source()
    session_key = build_session_key(source)
    future_wakeup = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    runner._loop_states[session_key] = {
        "session_id": "sess-active",
        "goal": "Keep going",
        "remaining_auto_turns": 1,
        "last_prompt": "Implement the next thin slice.",
        "last_prompt_norm": "implement the next thin slice.",
        "last_result_preview": "",
        "pending_wakeup_at": "",
        "channel_prompt": "channel prompt",
        "active": True,
    }
    runner.session_store = SimpleNamespace(
        _ensure_loaded=lambda: None,
        _entries={session_key: SimpleNamespace(origin=source)},
    )
    runner._handle_message = AsyncMock()

    class _FakeRuntime:
        def resume(self, session_id, **kwargs):
            return {
                "ok": True,
                "should_tick_now": False,
                "checkpoint": {
                    **runner._loop_states[session_key],
                    "session_id": session_id,
                    "session_key": session_key,
                    "pending_wakeup_at": future_wakeup,
                    "last_activity_at": "runtime-deferred",
                },
            }

    with patch("gateway.run.LoopRuntime", return_value=_FakeRuntime()):
        queued = runner._queue_due_loop_event(session_key, runner._loop_states[session_key])

    assert queued is False
    runner._handle_message.assert_not_awaited()
    assert runner._loop_states[session_key]["pending_wakeup_at"] == future_wakeup
    assert runner._loop_states[session_key]["last_activity_at"] == "runtime-deferred"


@pytest.mark.asyncio
async def test_followup_stops_conservatively_when_loop_event_persist_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    store = LoopStore()
    source = _make_source()
    session_key = build_session_key(source)

    store.write_checkpoint(
        session_id="sess-active",
        session_key=session_key,
        payload={
            "goal": "Keep going",
            "goal_id": "goal-active",
            "run_id": "run-active",
            "remaining_auto_turns": 2,
            "last_prompt": "Implement the next thin slice.",
            "last_prompt_norm": "different prompt",
            "last_result_preview": "previous result",
            "expected_evidence": "tests/gateway/test_loop_recovery.py",
            "channel_prompt": None,
            "active": True,
        },
    )
    store.write_goal_artifact(
        session_id="sess-active",
        goal_id="goal-active",
        goal_text="Keep going",
        created_by="gateway",
        session_key=session_key,
    )
    runner._loop_states[session_key] = {
        "session_id": "sess-active",
        "goal": "Keep going",
        "goal_id": "goal-active",
        "run_id": "run-active",
        "remaining_auto_turns": 2,
        "last_prompt": "Implement the next thin slice.",
        "last_prompt_norm": "different prompt",
        "last_result_preview": "previous result",
        "expected_evidence": "tests/gateway/test_loop_recovery.py",
        "active": True,
        "state": "waiting",
        "resumable": False,
        "stop_reason": "",
        "stop_class": "",
        "stop_message": "",
        "last_progress_summary": "",
        "retry_count": 0,
        "max_retry_budget": 2,
        "idle_timeout_seconds": 900,
        "last_activity_at": "",
        "pending_wakeup_at": "",
        "inflight_prompt": "",
        "inflight_started_at": "",
        "channel_prompt": None,
    }

    with patch(
        "hermes_cli.loop.decide_continuation_for_session",
        return_value={
            "action": "continue",
            "reason": "clear next slice",
            "next_prompt": "Implement the next thin slice.",
            "expected_evidence": "tests/gateway/test_loop_recovery.py",
        },
    ), patch(
        "hermes_cli.loop.verify_progress_for_session",
        return_value={"verdict": "progress", "reason": "real progress", "should_continue": True},
    ), patch(
        "gateway.run.LoopRuntime.schedule_continue",
        return_value={"ok": False, "error": "event_append_failed"},
    ):
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-active",
            source=source,
            final_response="Updated tests/gateway/test_loop_recovery.py and reran pytest -q.",
        )

    assert event is None
    assert "persist" in stop_notice.lower()
    assert session_key not in runner._loop_states
    checkpoint = _read_loop_checkpoint(tmp_path, "sess-active")
    assert checkpoint["active"] is False
    assert checkpoint["stop_reason"] == "loop_schedule_continue_failed"


@pytest.mark.asyncio
async def test_recovered_followup_stops_conservatively_when_goal_artifact_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    store = LoopStore()
    source = _make_source()
    session_key = build_session_key(source)

    store.write_checkpoint(
        session_id="sess-active",
        session_key=session_key,
        payload={
            "goal": "Keep going",
            "goal_id": "goal-active",
            "run_id": "run-active",
            "remaining_auto_turns": 2,
            "last_prompt": "Implement the next thin slice.",
            "last_prompt_norm": "different prompt",
            "last_result_preview": "previous result",
            "expected_evidence": "tests/gateway/test_loop_recovery.py",
            "channel_prompt": None,
            "active": True,
        },
    )
    # Intentionally do NOT write a goal artifact

    recovered = runner._hydrate_loop_states_from_store()
    assert recovered == 1

    with patch(
        "hermes_cli.loop.verify_progress_for_session",
        return_value={"verdict": "progress", "reason": "real progress", "should_continue": True},
    ) as mock_verifier:
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-active",
            source=source,
            final_response="Updated tests/gateway/test_loop_recovery.py and reran pytest -q.",
        )

    assert event is None
    assert "goal artifact" in stop_notice.lower()
    assert "missing" in stop_notice.lower()
    assert session_key not in runner._loop_states
    mock_verifier.assert_not_called()
    checkpoint = _read_loop_checkpoint(tmp_path, "sess-active")
    assert checkpoint["active"] is False
    assert checkpoint["stop_reason"] == "loop_goal_artifact_missing"


def _full_loop_state(session_id: str, session_key: str, *, last_result_preview: str = "", expected_evidence: str = "") -> dict:
    return {
        "session_id": session_id,
        "goal": "Keep going",
        "goal_id": f"goal-{session_id}",
        "run_id": f"run-{session_id}",
        "remaining_auto_turns": 2,
        "last_prompt": "Implement the next thin slice.",
        "last_prompt_norm": "implement the next thin slice.",
        "last_result_preview": last_result_preview,
        "expected_evidence": expected_evidence,
        "active": True,
        "state": "waiting",
        "resumable": False,
        "stop_reason": "",
        "stop_class": "",
        "stop_message": "",
        "last_progress_summary": "",
        "retry_count": 0,
        "max_retry_budget": 2,
        "idle_timeout_seconds": 900,
        "last_activity_at": "",
        "pending_wakeup_at": "",
        "inflight_prompt": "",
        "inflight_started_at": "",
        "channel_prompt": None,
    }


def _write_store_state(store: LoopStore, session_id: str, session_key: str, *, last_result_preview: str = "", expected_evidence: str = "") -> None:
    store.write_checkpoint(
        session_id=session_id,
        session_key=session_key,
        payload={
            "goal": "Keep going",
            "goal_id": f"goal-{session_id}",
            "run_id": f"run-{session_id}",
            "remaining_auto_turns": 2,
            "last_prompt": "Implement the next thin slice.",
            "last_prompt_norm": "implement the next thin slice.",
            "last_result_preview": last_result_preview,
            "expected_evidence": expected_evidence,
            "channel_prompt": None,
            "active": True,
        },
    )
    store.write_goal_artifact(
        session_id=session_id,
        goal_id=f"goal-{session_id}",
        goal_text="Keep going",
        created_by="gateway",
        session_key=session_key,
    )


@pytest.mark.asyncio
async def test_followup_routes_duplicate_result_preview_through_apply_validated_stop(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    store = LoopStore()
    source = _make_source()
    session_key = build_session_key(source)

    _write_store_state(store, "sess-dup", session_key, last_result_preview="same result")
    runner._loop_states[session_key] = _full_loop_state("sess-dup", session_key, last_result_preview="same result")

    with patch(
        "gateway.run.LoopRuntime.apply_validated_stop",
        return_value={"ok": True, "checkpoint": {}, "event": {}},
    ) as mock_stop:
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-dup",
            source=source,
            final_response="same result",
        )

    assert event is None
    assert stop_notice is not None
    assert mock_stop.called
    assert mock_stop.call_args.kwargs["stop_reason"] == "duplicate_result_preview"
    assert session_key not in runner._loop_states


@pytest.mark.asyncio
async def test_followup_routes_expected_evidence_missing_through_apply_validated_stop(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    store = LoopStore()
    source = _make_source()
    session_key = build_session_key(source)

    _write_store_state(store, "sess-ev", session_key, last_result_preview="", expected_evidence="EVIDENCE_MARKER")
    runner._loop_states[session_key] = _full_loop_state("sess-ev", session_key, last_result_preview="", expected_evidence="EVIDENCE_MARKER")

    with patch(
        "gateway.run.LoopRuntime.apply_validated_stop",
        return_value={"ok": True, "checkpoint": {}, "event": {}},
    ) as mock_stop:
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-ev",
            source=source,
            final_response="Updated tests/foo.py and reran pytest -q.",
        )

    assert event is None
    assert stop_notice is not None
    assert mock_stop.called
    assert mock_stop.call_args.kwargs["stop_reason"] == "expected_evidence_missing"
    assert session_key not in runner._loop_states


@pytest.mark.asyncio
async def test_followup_routes_progress_verifier_stalled_through_apply_validated_stop(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = _make_runner()
    store = LoopStore()
    source = _make_source()
    session_key = build_session_key(source)

    _write_store_state(store, "sess-stall", session_key, last_result_preview="previous result")
    runner._loop_states[session_key] = _full_loop_state("sess-stall", session_key, last_result_preview="previous result")

    with patch(
        "hermes_cli.loop.verify_progress_for_session",
        return_value={"verdict": "stalled", "reason": "Semantic stall detected.", "should_continue": False},
    ), patch(
        "gateway.run.LoopRuntime.apply_validated_stop",
        return_value={"ok": True, "checkpoint": {}, "event": {}},
    ) as mock_stop:
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-stall",
            source=source,
            final_response="Updated tests/foo.py and reran pytest -q.",
        )

    assert event is None
    assert stop_notice is not None
    assert mock_stop.called
    assert mock_stop.call_args.kwargs["stop_reason"] == "progress_verifier_stalled"
    assert session_key not in runner._loop_states
