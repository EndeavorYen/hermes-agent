import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

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
            "remaining_auto_turns": 2,
            "last_prompt": "Implement the next thin slice.",
            "last_prompt_norm": "different prompt",
            "last_result_preview": "previous result",
            "channel_prompt": None,
            "active": True,
        },
    )

    recovered = runner._hydrate_loop_states_from_store()

    assert recovered == 1
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
            session_id="sess-active",
            source=source,
            final_response="Implemented a fresh result.",
        )

    assert stop_notice is None
    assert event is not None
    assert event.internal is True
    assert event.text == "Implement the next thin slice."
    assert runner._loop_states[session_key]["remaining_auto_turns"] == 1
    assert runner._loop_states[session_key]["last_result_preview"] == "Implemented a fresh result."
    checkpoint = _read_loop_checkpoint(tmp_path, "sess-active")
    assert checkpoint["session_key"] == session_key
    assert checkpoint["remaining_auto_turns"] == 1
    assert checkpoint["last_prompt"] == "Implement the next thin slice."
    assert checkpoint["last_result_preview"] == "Implemented a fresh result."
    assert checkpoint["active"] is True


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
            "remaining_auto_turns": 2,
            "last_prompt": "Implement the next thin slice.",
            "last_prompt_norm": "different prompt",
            "last_result_preview": "previous result",
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
        },
    ), patch(
        "hermes_cli.loop.verify_progress_for_session",
        return_value={"verdict": "progress", "reason": "real progress", "should_continue": True},
    ), patch.object(runner, "_append_loop_event", return_value=False):
        event, stop_notice = await runner._maybe_schedule_loop_followup(
            session_key=session_key,
            session_id="sess-active",
            source=source,
            final_response="Implemented a fresh result.",
        )

    assert event is None
    assert "persist" in stop_notice.lower()
    assert session_key not in runner._loop_states
    checkpoint = _read_loop_checkpoint(tmp_path, "sess-active")
    assert checkpoint["active"] is False
    assert checkpoint["stop_reason"] == "loop_event_persist_failed"
