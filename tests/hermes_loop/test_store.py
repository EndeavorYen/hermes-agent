import json

from hermes_loop.store import LoopStore


def test_loop_store_persists_checkpoint_and_events(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    store = LoopStore()
    checkpoint = store.write_checkpoint(
        session_id="sess-1",
        session_key="telegram:u1:c1",
        payload={
            "goal": "Keep going",
            "remaining_auto_turns": 2,
            "last_prompt": "Implement thin slice",
            "last_prompt_norm": "implement thin slice",
            "active": True,
        },
    )
    event = store.append_event(
        session_id="sess-1",
        event_type="loop_started",
        payload={"goal": "Keep going", "remaining_auto_turns": 2},
    )

    checkpoint_path = tmp_path / "state" / "loops" / "sess-1" / "checkpoint.json"
    events_path = tmp_path / "state" / "loops" / "sess-1" / "events.jsonl"

    assert checkpoint_path.exists()
    assert events_path.exists()
    assert checkpoint["session_id"] == "sess-1"
    assert checkpoint["session_key"] == "telegram:u1:c1"
    assert checkpoint["active"] is True
    assert event["event_type"] == "loop_started"

    saved_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    saved_events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert saved_checkpoint["goal"] == "Keep going"
    assert saved_checkpoint["remaining_auto_turns"] == 2
    assert saved_checkpoint["last_prompt"] == "Implement thin slice"
    assert saved_events[-1]["event_type"] == "loop_started"
    assert saved_events[-1]["goal"] == "Keep going"


def test_loop_store_mark_stopped_updates_checkpoint_and_appends_stop_event(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-1",
        session_key="telegram:u1:c1",
        payload={"goal": "Keep going", "active": True, "remaining_auto_turns": 1},
    )

    checkpoint = store.mark_stopped(
        session_id="sess-1",
        session_key="telegram:u1:c1",
        stop_reason="progress_verifier_stalled",
        payload={"goal": "Keep going", "result_preview": "Fresh result"},
    )

    checkpoint_path = tmp_path / "state" / "loops" / "sess-1" / "checkpoint.json"
    events_path = tmp_path / "state" / "loops" / "sess-1" / "events.jsonl"
    saved_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    saved_events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert checkpoint["active"] is False
    assert checkpoint["stop_reason"] == "progress_verifier_stalled"
    assert saved_checkpoint["active"] is False
    assert saved_checkpoint["stop_reason"] == "progress_verifier_stalled"
    assert saved_events[-1]["event_type"] == "loop_stopped"
    assert saved_events[-1]["stop_reason"] == "progress_verifier_stalled"
    assert saved_events[-1]["result_preview"] == "Fresh result"


def test_loop_store_read_checkpoint_read_events_and_list_helpers(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-active",
        session_key="telegram:u1:c1",
        payload={
            "goal": "Keep going",
            "remaining_auto_turns": 2,
            "last_prompt": "Implement thin slice",
            "last_prompt_norm": "implement thin slice",
            "last_result_preview": "",
            "channel_prompt": "channel-specific prompt",
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
            "stop_reason": "model_stop",
        },
    )
    store.append_event(
        session_id="sess-active",
        event_type="loop_started",
        payload={"goal": "Keep going", "remaining_auto_turns": 2},
    )
    store.append_event(
        session_id="sess-active",
        event_type="loop_progressed",
        payload={"result_preview": "fresh result"},
    )
    store.append_event(
        session_id="sess-active",
        event_type="loop_progressed",
        payload={"result_preview": "newest result"},
    )

    checkpoint = store.read_checkpoint("sess-active")
    assert checkpoint is not None
    assert checkpoint["session_id"] == "sess-active"
    assert checkpoint["session_key"] == "telegram:u1:c1"
    assert checkpoint["last_prompt"] == "Implement thin slice"
    assert checkpoint["channel_prompt"] == "channel-specific prompt"

    events = store.read_events("sess-active", limit=2)
    assert [event["event_type"] for event in events] == ["loop_progressed", "loop_progressed"]
    assert events[-1]["result_preview"] == "newest result"

    all_checkpoints = store.list_checkpoints()
    assert [checkpoint["session_id"] for checkpoint in all_checkpoints] == ["sess-inactive", "sess-active"]

    active_checkpoints = store.list_checkpoints(active_only=True)
    assert [checkpoint["session_id"] for checkpoint in active_checkpoints] == ["sess-active"]


def test_loop_store_read_helpers_fail_closed_for_missing_or_malformed_data(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    store = LoopStore()
    broken_dir = tmp_path / "state" / "loops" / "sess-broken"
    broken_dir.mkdir(parents=True, exist_ok=True)
    (broken_dir / "checkpoint.json").write_text("not json", encoding="utf-8")
    (broken_dir / "events.jsonl").write_text(
        '{"event_type": "loop_started"}\nnot json\n{"event_type": "loop_progressed", "step": 2}\n',
        encoding="utf-8",
    )

    assert store.read_checkpoint("missing") is None
    assert store.read_checkpoint("sess-broken") is None
    assert store.read_events("missing") == []
    assert [event["event_type"] for event in store.read_events("sess-broken")] == [
        "loop_started",
        "loop_progressed",
    ]
    assert store.list_checkpoints() == []