from datetime import datetime, timedelta, timezone

from hermes_loop.runtime import LoopRuntime
from hermes_loop.store import LoopStore


def _write_checkpoint(store: LoopStore, *, session_id: str = "sess-1", **payload):
    base_payload = {
        "goal": "Keep going",
        "last_prompt": "Implement the next thin slice.",
        "active": True,
        "state": "waiting",
        "resumable": True,
        "pending_wakeup_at": "",
    }
    base_payload.update(payload)
    return store.write_checkpoint(
        session_id=session_id,
        session_key=str(base_payload.pop("session_key", f"cli:{session_id}")),
        payload=base_payload,
    )


def test_runtime_status_normalizes_waiting_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(store, session_id="sess-waiting", state="", pending_wakeup_at=None)

    result = LoopRuntime(store=store).status("sess-waiting")

    assert result is not None
    assert result["state"] == "waiting"
    assert result["pending_wakeup_at"] == ""
    assert result["resumable"] is True


def test_runtime_resume_on_future_wake_returns_should_tick_now_false(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    future_wakeup = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    _write_checkpoint(store, session_id="sess-future", pending_wakeup_at=future_wakeup)

    result = LoopRuntime(store=store).resume("sess-future")

    assert result["ok"] is True
    assert result["should_tick_now"] is False
    assert result["checkpoint"]["pending_wakeup_at"] == future_wakeup
    assert result["checkpoint"]["state"] == "waiting"
    events = store.read_events("sess-future")
    assert events[-1]["event_type"] == "resumed"
    assert events[-1]["pending_wakeup_at"] == future_wakeup


def test_runtime_resume_on_due_wake_returns_should_tick_now_true(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    due_wakeup = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    _write_checkpoint(store, session_id="sess-due", pending_wakeup_at=due_wakeup)

    result = LoopRuntime(store=store).resume("sess-due")

    assert result["ok"] is True
    assert result["should_tick_now"] is True
    assert result["checkpoint"]["pending_wakeup_at"] == ""
    assert result["checkpoint"]["state"] == "waiting"


def test_runtime_resume_allows_recovery_event_metadata_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    due_wakeup = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    _write_checkpoint(store, session_id="sess-recovery", pending_wakeup_at=due_wakeup)

    result = LoopRuntime(store=store).resume(
        "sess-recovery",
        message="Loop resumed by due wake recovery.",
        metadata={"resume_reason": "due_wake_recovery", "resume_source": "gateway_watcher"},
    )

    assert result["ok"] is True
    events = store.read_events("sess-recovery")
    assert events[-1]["event_type"] == "resumed"
    assert events[-1]["message"] == "Loop resumed by due wake recovery."
    assert events[-1]["resume_reason"] == "due_wake_recovery"
    assert events[-1]["resume_source"] == "gateway_watcher"


def test_runtime_resume_returns_due_wake_checkpoint_for_enqueue_decision(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    due_wakeup = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    _write_checkpoint(
        store,
        session_id="sess-runtime-refresh",
        pending_wakeup_at=due_wakeup,
        last_prompt="Prompt from runtime checkpoint",
        channel_prompt="runtime channel prompt",
    )

    result = LoopRuntime(store=store).resume(
        "sess-runtime-refresh",
        message="Loop resumed by due wake recovery.",
        metadata={"resume_reason": "due_wake_recovery", "resume_source": "gateway_watcher"},
    )

    assert result["ok"] is True
    assert result["should_tick_now"] is True
    assert result["checkpoint"]["pending_wakeup_at"] == ""
    assert result["checkpoint"]["last_prompt"] == "Prompt from runtime checkpoint"
    assert result["checkpoint"]["channel_prompt"] == "runtime channel prompt"


def test_runtime_pause_writes_paused_checkpoint_and_event(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(store, session_id="sess-pause")

    result = LoopRuntime(store=store).pause("sess-pause")

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-pause")
    assert checkpoint["active"] is False
    assert checkpoint["state"] == "paused"
    assert checkpoint["stop_reason"] == "operator_pause"
    events = store.read_events("sess-pause")
    assert events[-1]["event_type"] == "paused"
    assert events[-1]["stop_reason"] == "operator_pause"


def test_runtime_stop_writes_stopped_checkpoint_and_event(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(store, session_id="sess-stop")

    result = LoopRuntime(store=store).stop("sess-stop")

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-stop")
    assert checkpoint["active"] is False
    assert checkpoint["state"] == "stopped"
    assert checkpoint["resumable"] is False
    assert checkpoint["stop_reason"] == "operator_stop"
    events = store.read_events("sess-stop")
    assert events[-1]["event_type"] == "stop_requested"
    assert events[-1]["stop_reason"] == "operator_stop"
