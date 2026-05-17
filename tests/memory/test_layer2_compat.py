import json
import sqlite3

from hermes_constants import get_hermes_home


def test_layer2_store_default_migrates_legacy_cron_db():
    from memory.layer2_store import Layer2Store

    hermes_home = get_hermes_home()
    legacy_db = hermes_home / "cron" / "layer2_memory.sqlite3"
    legacy = Layer2Store(legacy_db)
    legacy.record_event(
        event_type="create",
        canonical_text="Layer-2 legacy cron data must remain readable",
        kind="heuristic",
        proposed_target="memory",
        source_ref="cron:legacy:run-1",
        source_event_id="legacy-event-1",
        event_ts="2026-05-17T00:00:00+00:00",
    )

    default = Layer2Store()

    assert default.db_path == hermes_home / "memory" / "layer2.sqlite3"
    assert default.get_candidate("Layer-2 legacy cron data must remain readable") is not None


def test_layer2_signals_cli_emits_wake_gate_for_high_signal_changes(tmp_path, capsys):
    from memory.layer2_signals import main
    from memory.layer2_store import Layer2Store

    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Contradicted learning candidate",
        source_ref="cron:daily:run-1",
        source_event_id="event-1",
        event_ts="2026-05-17T00:00:00+00:00",
    )
    store.record_event(
        event_type="contradict",
        canonical_text="Contradicted learning candidate",
        source_ref="cron:daily:run-2",
        source_event_id="event-2",
        event_ts="2026-05-17T01:00:00+00:00",
    )

    assert main(
        [
            "--since",
            "2026-05-16T00:00:00+00:00",
            "--db",
            str(store.db_path),
            "--wake-gate",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["wakeAgent"] is True
    assert payload["should_run_dream"] is True
    assert payload["reason_codes"] == ["contradiction_spike"]


def test_layer2_consolidate_json_keeps_maintenance_job_available(tmp_path, capsys):
    from memory.layer2_consolidate import main
    from memory.layer2_store import Layer2Store

    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Old weak candidate",
        source_ref="cron:daily:run-1",
        source_event_id="old-event-1",
        event_ts="2026-04-01T00:00:00+00:00",
    )

    assert main(
        [
            "--db",
            str(store.db_path),
            "--now",
            "2026-05-17T00:00:00+00:00",
            "--json",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert any(change["audit_label"] == "candidate_marked_stale" for change in payload["changes"])
    with sqlite3.connect(store.db_path) as conn:
        status = conn.execute("SELECT status FROM candidates WHERE canonical_text = ?", ("Old weak candidate",)).fetchone()[0]
    assert status == "stale"
