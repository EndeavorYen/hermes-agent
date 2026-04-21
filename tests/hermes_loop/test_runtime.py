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


def test_runtime_schedule_continue_writes_waiting_checkpoint_and_event(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(
        store,
        session_id="sess-continue",
        session_key="telegram:sess-continue",
        goal="Keep going",
        goal_id="goal-continue",
        run_id="run-continue",
        remaining_auto_turns=2,
        last_prompt="Old prompt",
        last_prompt_norm="old prompt",
        expected_evidence="tests/old.py",
        last_result_preview="Old preview",
        last_progress_summary="Old preview",
        stop_reason="old_stop",
        stop_class="internal",
        stop_message="old message",
        retry_count=3,
        pending_wakeup_at="2026-01-01T00:00:00+00:00",
        inflight_prompt="Old inflight",
        inflight_started_at="2026-01-01T00:00:00+00:00",
    )

    result = LoopRuntime(store=store).schedule_continue(
        "sess-continue",
        next_prompt="Implement the next thin slice.",
        next_prompt_norm="implement the next thin slice.",
        expected_evidence="tests/new.py",
        remaining_auto_turns=1,
        result_preview="Updated tests/new.py and reran pytest -q.",
    )

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-continue")
    assert checkpoint["session_key"] == "telegram:sess-continue"
    assert checkpoint["last_prompt"] == "Implement the next thin slice."
    assert checkpoint["last_prompt_norm"] == "implement the next thin slice."
    assert checkpoint["expected_evidence"] == "tests/new.py"
    assert checkpoint["remaining_auto_turns"] == 1
    assert checkpoint["active"] is True
    assert checkpoint["state"] == "waiting"
    assert checkpoint["resumable"] is True
    assert checkpoint["stop_reason"] == ""
    assert checkpoint["stop_class"] == ""
    assert checkpoint["stop_message"] == ""
    assert checkpoint["retry_count"] == 0
    assert checkpoint["pending_wakeup_at"] == ""
    assert checkpoint["inflight_prompt"] == ""
    assert checkpoint["inflight_started_at"] == ""
    assert checkpoint["last_result_preview"] == "Updated tests/new.py and reran pytest -q."
    assert checkpoint["last_progress_summary"] == "Updated tests/new.py and reran pytest -q."
    assert checkpoint["last_activity_at"]
    events = store.read_events("sess-continue")
    assert events[-1]["event_type"] == "loop_followup_scheduled"
    assert events[-1]["next_prompt"] == "Implement the next thin slice."
    assert events[-1]["expected_evidence"] == "tests/new.py"
    assert events[-1]["remaining_auto_turns"] == 1
    assert events[-1]["result_preview"] == "Updated tests/new.py and reran pytest -q."
    assert events[-1].get("deferred") in (None, False)


def test_runtime_schedule_wait_writes_waiting_checkpoint_and_deferred_event(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    pending_wakeup_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    _write_checkpoint(
        store,
        session_id="sess-wait",
        session_key="telegram:sess-wait",
        goal="Keep going",
        goal_id="goal-wait",
        run_id="run-wait",
        remaining_auto_turns=2,
        last_prompt="Old prompt",
        last_prompt_norm="old prompt",
        expected_evidence="tests/old.py",
        last_result_preview="Old preview",
        last_progress_summary="Old preview",
        stop_reason="old_stop",
        stop_class="internal",
        stop_message="old message",
        retry_count=3,
        pending_wakeup_at="2026-01-01T00:00:00+00:00",
        inflight_prompt="Old inflight",
        inflight_started_at="2026-01-01T00:00:00+00:00",
    )

    result = LoopRuntime(store=store).schedule_wait(
        "sess-wait",
        next_prompt="Resume the next thin slice.",
        next_prompt_norm="resume the next thin slice.",
        expected_evidence="tests/deferred.py",
        remaining_auto_turns=1,
        result_preview="Implemented the current slice and waiting on external change.",
        pending_wakeup_at=pending_wakeup_at,
    )

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-wait")
    assert checkpoint["session_key"] == "telegram:sess-wait"
    assert checkpoint["last_prompt"] == "Resume the next thin slice."
    assert checkpoint["last_prompt_norm"] == "resume the next thin slice."
    assert checkpoint["expected_evidence"] == "tests/deferred.py"
    assert checkpoint["remaining_auto_turns"] == 1
    assert checkpoint["active"] is True
    assert checkpoint["state"] == "waiting"
    assert checkpoint["resumable"] is True
    assert checkpoint["stop_reason"] == ""
    assert checkpoint["stop_class"] == ""
    assert checkpoint["stop_message"] == ""
    assert checkpoint["retry_count"] == 0
    assert checkpoint["pending_wakeup_at"] == pending_wakeup_at
    assert checkpoint["inflight_prompt"] == ""
    assert checkpoint["inflight_started_at"] == ""
    assert checkpoint["last_result_preview"] == "Implemented the current slice and waiting on external change."
    assert checkpoint["last_progress_summary"] == "Implemented the current slice and waiting on external change."
    assert checkpoint["last_activity_at"]
    events = store.read_events("sess-wait")
    assert events[-1]["event_type"] == "loop_followup_scheduled"
    assert events[-1]["goal"] == "Keep going"
    assert events[-1]["goal_id"] == "goal-wait"
    assert events[-1]["run_id"] == "run-wait"
    assert events[-1]["next_prompt"] == "Resume the next thin slice."
    assert events[-1]["expected_evidence"] == "tests/deferred.py"
    assert events[-1]["remaining_auto_turns"] == 1
    assert events[-1]["result_preview"] == "Implemented the current slice and waiting on external change."
    assert events[-1]["pending_wakeup_at"] == pending_wakeup_at
    assert events[-1]["deferred"] is True


def test_runtime_apply_followup_decision_continue_delegates_to_schedule_continue(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(
        store,
        session_id="sess-apply-continue",
        session_key="telegram:sess-apply-continue",
        goal="Keep going",
        goal_id="goal-apply-continue",
        run_id="run-apply-continue",
        remaining_auto_turns=2,
        last_prompt="Old prompt",
        last_prompt_norm="old prompt",
        expected_evidence="tests/old.py",
    )

    result = LoopRuntime(store=store).apply_followup_decision(
        session_id="sess-apply-continue",
        decision={
            "action": "continue",
            "next_prompt": "Implement the next thin slice.",
            "expected_evidence": "tests/new.py",
        },
        result_preview="Updated tests/new.py and reran pytest -q.",
        remaining_auto_turns=1,
    )

    assert result["ok"] is True
    assert result["kind"] == "continue"
    assert result["stop_reason"] == ""
    assert result["checkpoint"]["last_prompt"] == "Implement the next thin slice."
    assert result["checkpoint"]["last_prompt_norm"] == "implement the next thin slice."
    assert result["checkpoint"]["expected_evidence"] == "tests/new.py"
    assert result["checkpoint"]["remaining_auto_turns"] == 1
    assert result["event"]["event_type"] == "loop_followup_scheduled"


def test_runtime_apply_followup_decision_wait_delegates_to_schedule_wait(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    pending_wakeup_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    _write_checkpoint(
        store,
        session_id="sess-apply-wait",
        session_key="telegram:sess-apply-wait",
        goal="Keep going",
        goal_id="goal-apply-wait",
        run_id="run-apply-wait",
        remaining_auto_turns=2,
        last_prompt="Old prompt",
        last_prompt_norm="old prompt",
        expected_evidence="tests/old.py",
    )

    result = LoopRuntime(store=store).apply_followup_decision(
        session_id="sess-apply-wait",
        decision={
            "action": "wait",
            "next_prompt": "Resume the next thin slice.",
            "expected_evidence": "tests/deferred.py",
        },
        result_preview="Implemented the current slice and waiting on external change.",
        remaining_auto_turns=1,
        pending_wakeup_at=pending_wakeup_at,
    )

    assert result["ok"] is True
    assert result["kind"] == "wait"
    assert result["checkpoint"]["last_prompt"] == "Resume the next thin slice."
    assert result["checkpoint"]["last_prompt_norm"] == "resume the next thin slice."
    assert result["checkpoint"]["expected_evidence"] == "tests/deferred.py"
    assert result["checkpoint"]["pending_wakeup_at"] == pending_wakeup_at
    assert result["pending_wakeup_at"] == pending_wakeup_at
    assert result["event"]["event_type"] == "loop_followup_scheduled"


def test_runtime_apply_followup_decision_repeated_next_prompt_finalizes_stop(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(
        store,
        session_id="sess-apply-stop",
        session_key="telegram:sess-apply-stop",
        goal="Keep going",
        goal_id="goal-apply-stop",
        run_id="run-apply-stop",
        remaining_auto_turns=2,
        last_prompt="Implement the next thin slice.",
        last_prompt_norm="implement the next thin slice.",
        expected_evidence="tests/foo.py",
        pending_wakeup_at="2026-01-01T00:05:00+00:00",
        inflight_prompt="Current inflight prompt",
        inflight_started_at="2026-01-01T00:00:00+00:00",
    )

    result = LoopRuntime(store=store).apply_followup_decision(
        session_id="sess-apply-stop",
        decision={
            "action": "continue",
            "next_prompt": "Implement the next thin slice.",
            "expected_evidence": "tests/bar.py",
        },
        result_preview="Different new result tests/foo.py",
        remaining_auto_turns=1,
    )

    assert result["ok"] is True
    assert result["kind"] == "stop"
    assert result["stop_reason"] == "repeated_next_prompt"
    assert result["stop_message"] == "repeated next prompt (stall suppression)."
    checkpoint = store.read_checkpoint("sess-apply-stop")
    assert checkpoint["active"] is False
    assert checkpoint["state"] == "stopped"
    assert checkpoint["stop_reason"] == "repeated_next_prompt"
    assert checkpoint["pending_wakeup_at"] == ""
    assert checkpoint["inflight_prompt"] == ""
    events = store.read_events("sess-apply-stop")
    assert events[-1]["event_type"] == "loop_stopped"
    assert events[-1]["stop_reason"] == "repeated_next_prompt"


def test_runtime_schedule_initial_writes_waiting_checkpoint_and_event_for_immediate_start(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()

    result = LoopRuntime(store=store).schedule_initial(
        session_id="sess-start-now",
        session_key="telegram:sess-start-now",
        goal="Finish the refactor",
        goal_id="goal-start-now",
        run_id="run-start-now",
        next_prompt="Implement the next thin slice and verify it.",
        next_prompt_norm="implement the next thin slice and verify it.",
        expected_evidence="tests/foo.py",
        remaining_auto_turns=5,
        max_retry_budget=3,
        idle_timeout_seconds=1800,
        channel_prompt="channel context",
        pending_wakeup_at="",
        deferred=False,
    )

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-start-now")
    assert checkpoint["session_key"] == "telegram:sess-start-now"
    assert checkpoint["goal"] == "Finish the refactor"
    assert checkpoint["goal_id"] == "goal-start-now"
    assert checkpoint["run_id"] == "run-start-now"
    assert checkpoint["last_prompt"] == "Implement the next thin slice and verify it."
    assert checkpoint["last_prompt_norm"] == "implement the next thin slice and verify it."
    assert checkpoint["expected_evidence"] == "tests/foo.py"
    assert checkpoint["remaining_auto_turns"] == 5
    assert checkpoint["max_retry_budget"] == 3
    assert checkpoint["idle_timeout_seconds"] == 1800
    assert checkpoint["channel_prompt"] == "channel context"
    assert checkpoint["active"] is True
    assert checkpoint["state"] == "waiting"
    assert checkpoint["resumable"] is True
    assert checkpoint["stop_reason"] == ""
    assert checkpoint["stop_class"] == ""
    assert checkpoint["stop_message"] == ""
    assert checkpoint["retry_count"] == 0
    assert checkpoint["last_result_preview"] == ""
    assert checkpoint["last_progress_summary"] == ""
    assert checkpoint["pending_wakeup_at"] == ""
    assert checkpoint["inflight_prompt"] == ""
    assert checkpoint["inflight_started_at"] == ""
    assert checkpoint["last_activity_at"]
    events = store.read_events("sess-start-now")
    assert events[-1]["event_type"] == "loop_started"
    assert events[-1]["goal"] == "Finish the refactor"
    assert events[-1]["goal_id"] == "goal-start-now"
    assert events[-1]["run_id"] == "run-start-now"
    assert events[-1]["next_prompt"] == "Implement the next thin slice and verify it."
    assert events[-1]["expected_evidence"] == "tests/foo.py"
    assert events[-1]["remaining_auto_turns"] == 5
    assert events[-1]["max_retry_budget"] == 3
    assert events[-1]["idle_timeout_seconds"] == 1800
    assert events[-1]["pending_wakeup_at"] == ""
    assert events[-1]["deferred"] is False


def test_runtime_schedule_initial_writes_deferred_start_with_pending_wakeup(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    pending_wakeup_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    result = LoopRuntime(store=store).schedule_initial(
        session_id="sess-start-later",
        session_key="telegram:sess-start-later",
        goal="Finish the refactor",
        goal_id="goal-start-later",
        run_id="run-start-later",
        next_prompt="Resume the thin slice.",
        next_prompt_norm="resume the thin slice.",
        expected_evidence="tests/wait.py",
        remaining_auto_turns=2,
        max_retry_budget=2,
        idle_timeout_seconds=900,
        channel_prompt=None,
        pending_wakeup_at=pending_wakeup_at,
        deferred=True,
    )

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-start-later")
    assert checkpoint["pending_wakeup_at"] == pending_wakeup_at
    assert checkpoint["state"] == "waiting"
    assert checkpoint["active"] is True
    events = store.read_events("sess-start-later")
    assert events[-1]["event_type"] == "loop_started"
    assert events[-1]["pending_wakeup_at"] == pending_wakeup_at
    assert events[-1]["deferred"] is True


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


def test_runtime_finalize_stop_writes_stopped_checkpoint_and_event(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(
        store,
        session_id="sess-finalize-stop",
        session_key="telegram:sess-finalize-stop",
        goal="Finish the refactor",
        goal_id="goal-finalize-stop",
        run_id="run-finalize-stop",
        remaining_auto_turns=1,
        last_prompt="Implement the next thin slice.",
        last_prompt_norm="implement the next thin slice.",
        expected_evidence="tests/foo.py",
        last_result_preview="Old preview",
        last_progress_summary="Old summary",
        pending_wakeup_at="2026-01-01T00:05:00+00:00",
        inflight_prompt="Current inflight prompt",
        inflight_started_at="2026-01-01T00:00:00+00:00",
    )

    result = LoopRuntime(store=store).finalize_stop(
        "sess-finalize-stop",
        stop_reason="expected_evidence_missing",
        stop_message="continuation did not include expected evidence marker: tests/foo.py",
        result_preview="Updated tests/bar.py only.",
        expected_evidence="tests/foo.py",
    )

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-finalize-stop")
    assert checkpoint["session_key"] == "telegram:sess-finalize-stop"
    assert checkpoint["goal"] == "Finish the refactor"
    assert checkpoint["goal_id"] == "goal-finalize-stop"
    assert checkpoint["run_id"] == "run-finalize-stop"
    assert checkpoint["active"] is False
    assert checkpoint["state"] == "stopped"
    assert checkpoint["resumable"] is False
    assert checkpoint["stop_reason"] == "expected_evidence_missing"
    assert checkpoint["stop_class"] == "verification"
    assert checkpoint["stop_message"] == "continuation did not include expected evidence marker: tests/foo.py"
    assert checkpoint["pending_wakeup_at"] == ""
    assert checkpoint["inflight_prompt"] == ""
    assert checkpoint["inflight_started_at"] == ""
    assert checkpoint["last_result_preview"] == "Updated tests/bar.py only."
    assert checkpoint["expected_evidence"] == "tests/foo.py"
    assert checkpoint["last_activity_at"]
    events = store.read_events("sess-finalize-stop")
    assert events[-1]["event_type"] == "loop_stopped"
    assert events[-1]["goal"] == "Finish the refactor"
    assert events[-1]["goal_id"] == "goal-finalize-stop"
    assert events[-1]["run_id"] == "run-finalize-stop"
    assert events[-1]["stop_reason"] == "expected_evidence_missing"
    assert events[-1]["stop_class"] == "verification"
    assert events[-1]["message"] == "continuation did not include expected evidence marker: tests/foo.py"
    assert events[-1]["result_preview"] == "Updated tests/bar.py only."
    assert events[-1]["expected_evidence"] == "tests/foo.py"


def test_runtime_apply_validated_stop_duplicate_result_preview(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(
        store,
        session_id="sess-avs-dup",
        session_key="telegram:sess-avs-dup",
        goal="Refactor the pipeline",
        goal_id="goal-avs-dup",
        run_id="run-avs-dup",
        last_result_preview="Previous output.",
        inflight_prompt="Current prompt",
        inflight_started_at="2026-01-01T00:00:00+00:00",
        pending_wakeup_at="2026-01-01T00:05:00+00:00",
    )

    result = LoopRuntime(store=store).apply_validated_stop(
        "sess-avs-dup",
        stop_reason="duplicate_result_preview",
        stop_message="continuation produced no meaningful new result.",
        result_preview="Previous output.",
    )

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-avs-dup")
    assert checkpoint["active"] is False
    assert checkpoint["state"] == "stopped"
    assert checkpoint["stop_reason"] == "duplicate_result_preview"
    assert checkpoint["stop_class"] == "verification"
    assert checkpoint["stop_message"] == "continuation produced no meaningful new result."
    assert checkpoint["last_result_preview"] == "Previous output."
    assert checkpoint["inflight_prompt"] == ""
    assert checkpoint["pending_wakeup_at"] == ""
    events = store.read_events("sess-avs-dup")
    assert events[-1]["event_type"] == "loop_stopped"
    assert events[-1]["stop_reason"] == "duplicate_result_preview"
    assert events[-1]["stop_class"] == "verification"
    assert events[-1]["result_preview"] == "Previous output."


def test_runtime_apply_validated_stop_expected_evidence_missing_passes_extra_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(
        store,
        session_id="sess-avs-ev",
        session_key="telegram:sess-avs-ev",
        goal="Add the test file",
        goal_id="goal-avs-ev",
        run_id="run-avs-ev",
        expected_evidence="tests/foo.py",
    )

    result = LoopRuntime(store=store).apply_validated_stop(
        "sess-avs-ev",
        stop_reason="expected_evidence_missing",
        stop_message="continuation did not include expected evidence marker: tests/foo.py",
        result_preview="Updated tests/bar.py only.",
        expected_evidence="tests/foo.py",
    )

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-avs-ev")
    assert checkpoint["active"] is False
    assert checkpoint["stop_reason"] == "expected_evidence_missing"
    assert checkpoint["stop_class"] == "verification"
    assert checkpoint["expected_evidence"] == "tests/foo.py"
    assert checkpoint["last_result_preview"] == "Updated tests/bar.py only."
    events = store.read_events("sess-avs-ev")
    assert events[-1]["event_type"] == "loop_stopped"
    assert events[-1]["stop_reason"] == "expected_evidence_missing"
    assert events[-1]["stop_class"] == "verification"
    assert events[-1]["expected_evidence"] == "tests/foo.py"


def test_runtime_apply_validated_stop_progress_verifier_stalled(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(
        store,
        session_id="sess-avs-stall",
        session_key="telegram:sess-avs-stall",
        goal="Migrate the schema",
        goal_id="goal-avs-stall",
        run_id="run-avs-stall",
        last_result_preview="Partial migration.",
    )

    stalled_message = "Latest continuation did not materially advance the goal."
    result = LoopRuntime(store=store).apply_validated_stop(
        "sess-avs-stall",
        stop_reason="progress_verifier_stalled",
        stop_message=stalled_message,
        result_preview="Partial migration.",
    )

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-avs-stall")
    assert checkpoint["active"] is False
    assert checkpoint["stop_reason"] == "progress_verifier_stalled"
    assert checkpoint["stop_class"] == "verification"
    assert checkpoint["stop_message"] == stalled_message
    events = store.read_events("sess-avs-stall")
    assert events[-1]["event_type"] == "loop_stopped"
    assert events[-1]["stop_reason"] == "progress_verifier_stalled"
    assert events[-1]["stop_class"] == "verification"
    assert events[-1]["message"] == stalled_message


def test_runtime_apply_validated_stop_empty_continuation_result(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(
        store,
        session_id="sess-avs-empty",
        session_key="telegram:sess-avs-empty",
        goal="Finish the feature",
        goal_id="goal-avs-empty",
        run_id="run-avs-empty",
        last_result_preview="Prior output.",
        inflight_prompt="Current prompt",
        inflight_started_at="2026-01-01T00:00:00+00:00",
        pending_wakeup_at="2026-01-01T00:05:00+00:00",
    )

    result = LoopRuntime(store=store).apply_validated_stop(
        "sess-avs-empty",
        stop_reason="empty_continuation_result",
        stop_message="continuation produced no visible result.",
        result_preview="Prior output.",
    )

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-avs-empty")
    assert checkpoint["active"] is False
    assert checkpoint["state"] == "stopped"
    assert checkpoint["resumable"] is False
    assert checkpoint["stop_reason"] == "empty_continuation_result"
    assert checkpoint["stop_class"] == "normal"
    assert checkpoint["stop_message"] == "continuation produced no visible result."
    assert checkpoint["last_result_preview"] == "Prior output."
    assert checkpoint["inflight_prompt"] == ""
    assert checkpoint["pending_wakeup_at"] == ""
    events = store.read_events("sess-avs-empty")
    assert events[-1]["event_type"] == "loop_stopped"
    assert events[-1]["stop_reason"] == "empty_continuation_result"
    assert events[-1]["stop_class"] == "normal"
    assert events[-1]["message"] == "continuation produced no visible result."
    assert events[-1]["result_preview"] == "Prior output."


def test_runtime_apply_validated_stop_missing_observable_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(
        store,
        session_id="sess-avs-moe",
        session_key="telegram:sess-avs-moe",
        goal="Migrate the schema",
        goal_id="goal-avs-moe",
        run_id="run-avs-moe",
        last_result_preview="Some text output.",
        inflight_prompt="Current prompt",
        inflight_started_at="2026-01-01T00:00:00+00:00",
        pending_wakeup_at="2026-01-01T00:05:00+00:00",
    )

    result = LoopRuntime(store=store).apply_validated_stop(
        "sess-avs-moe",
        stop_reason="missing_observable_evidence",
        stop_message="continuation lacked observable evidence (no code, diff, file path, test, or command).",
        result_preview="Some text output.",
    )

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-avs-moe")
    assert checkpoint["active"] is False
    assert checkpoint["state"] == "stopped"
    assert checkpoint["resumable"] is False
    assert checkpoint["stop_reason"] == "missing_observable_evidence"
    assert checkpoint["stop_class"] == "verification"
    assert checkpoint["stop_message"] == "continuation lacked observable evidence (no code, diff, file path, test, or command)."
    assert checkpoint["last_result_preview"] == "Some text output."
    assert checkpoint["inflight_prompt"] == ""
    assert checkpoint["pending_wakeup_at"] == ""
    events = store.read_events("sess-avs-moe")
    assert events[-1]["event_type"] == "loop_stopped"
    assert events[-1]["stop_reason"] == "missing_observable_evidence"
    assert events[-1]["stop_class"] == "verification"
    assert events[-1]["message"] == "continuation lacked observable evidence (no code, diff, file path, test, or command)."
    assert events[-1]["result_preview"] == "Some text output."


def test_runtime_apply_validated_stop_progress_verifier_done(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    _write_checkpoint(
        store,
        session_id="sess-avs-done",
        session_key="telegram:sess-avs-done",
        goal="Add the new endpoint",
        goal_id="goal-avs-done",
        run_id="run-avs-done",
        last_result_preview="Endpoint implemented and tests passing.",
        inflight_prompt="Current prompt",
        inflight_started_at="2026-01-01T00:00:00+00:00",
        pending_wakeup_at="2026-01-01T00:05:00+00:00",
    )

    done_message = "The endpoint is fully implemented and all tests pass."
    result = LoopRuntime(store=store).apply_validated_stop(
        "sess-avs-done",
        stop_reason="progress_verifier_done",
        stop_message=done_message,
        result_preview="Endpoint implemented and tests passing.",
    )

    assert result["ok"] is True
    checkpoint = store.read_checkpoint("sess-avs-done")
    assert checkpoint["active"] is False
    assert checkpoint["state"] == "stopped"
    assert checkpoint["resumable"] is False
    assert checkpoint["stop_reason"] == "progress_verifier_done"
    assert checkpoint["stop_class"] == "verification"
    assert checkpoint["stop_message"] == done_message
    assert checkpoint["last_result_preview"] == "Endpoint implemented and tests passing."
    assert checkpoint["inflight_prompt"] == ""
    assert checkpoint["pending_wakeup_at"] == ""
    events = store.read_events("sess-avs-done")
    assert events[-1]["event_type"] == "loop_stopped"
    assert events[-1]["stop_reason"] == "progress_verifier_done"
    assert events[-1]["stop_class"] == "verification"
    assert events[-1]["message"] == done_message
    assert events[-1]["result_preview"] == "Endpoint implemented and tests passing."
