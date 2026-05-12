import json

from memory.layer2_signals import detect_layer2_signals, main
from memory.layer2_store import Layer2Store


def test_detect_layer2_signals_triggers_on_new_quarantine(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Unstable candidate",
        kind="heuristic",
        proposed_target="memory",
        source_ref="test:1",
        source_event_id="evt-1",
        event_ts="2026-05-13T00:00:00+00:00",
    )
    store.record_event(
        event_type="contradict",
        canonical_text="Unstable candidate",
        source_ref="test:2",
        source_event_id="evt-2",
        event_ts="2026-05-13T01:00:00+00:00",
    )

    signal = detect_layer2_signals(store=store, since="2026-05-12T00:00:00+00:00")

    assert signal.should_run_dream is True
    assert "contradiction_spike" in signal.reason_codes


def test_detect_layer2_signals_stays_silent_without_high_signal_changes(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Low signal",
        kind="fact",
        proposed_target="memory",
        source_ref="test:1",
        source_event_id="evt-1",
        counts_for_recurrence=False,
        event_ts="2026-05-13T00:00:00+00:00",
    )

    signal = detect_layer2_signals(store=store, since="2026-05-12T00:00:00+00:00")

    assert signal.should_run_dream is False
    assert signal.reason_codes == []


def test_layer2_signals_cli_can_emit_cron_wake_gate(tmp_path, capsys):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Unstable candidate",
        kind="heuristic",
        proposed_target="memory",
        source_ref="test:1",
        source_event_id="evt-1",
        event_ts="2026-05-13T00:00:00+00:00",
    )
    store.record_event(
        event_type="contradict",
        canonical_text="Unstable candidate",
        source_ref="test:2",
        source_event_id="evt-2",
        event_ts="2026-05-13T01:00:00+00:00",
    )

    assert main(
        [
            "--since",
            "2026-05-12T00:00:00+00:00",
            "--db",
            str(store.db_path),
            "--wake-gate",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["wakeAgent"] is True
    assert payload["should_run_dream"] is True
    assert payload["reason_codes"] == ["contradiction_spike"]
