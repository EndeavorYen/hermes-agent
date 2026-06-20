from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from agent.raphael.models import (
    EVENT_SCHEMA_VERSION,
    STATE_SCHEMA_VERSION,
    RaphaelEvent,
    RaphaelState,
    StatusCard,
)
from agent.raphael.state import (
    append_event,
    get_raphael_events_path,
    get_raphael_state_dir,
    get_raphael_state_path,
    read_state,
    write_state,
)


def _hermes_home_env(path: Path):
    return patch.dict(os.environ, {"HERMES_HOME": str(path)})


def test_paths_use_active_hermes_home_from_environment(tmp_path):
    home = tmp_path / "active-hermes-home"

    with _hermes_home_env(home):
        assert get_raphael_state_dir() == home / "raphael"
        assert get_raphael_state_path() == home / "raphael" / "state.json"
        assert get_raphael_events_path() == home / "raphael" / "events.jsonl"


def test_missing_state_returns_empty_without_creating_raphael_directory(tmp_path):
    home = tmp_path / "hermes-home"

    with _hermes_home_env(home):
        state = read_state()

    assert state.status_cards == ()
    assert state.action_proposals == ()
    assert state.updated_at.tzinfo == timezone.utc
    assert not (home / "raphael").exists()


def test_write_state_round_trips_status_card_without_tmp_files(tmp_path):
    home = tmp_path / "hermes-home"
    observed_at = datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc)
    card = StatusCard(
        card_id="card-1",
        severity="warning",
        title="Gateway warning",
        summary="Slack gateway warnings need operator attention.",
        observed_at=observed_at,
        expires_at=observed_at + timedelta(hours=1),
        source="gateway-monitor",
        confidence=0.86,
        evidence_refs=("gateway.error.log",),
    )
    state = RaphaelState(
        status_cards=(card,),
        action_proposals=(),
        updated_at=datetime(2026, 6, 16, 9, 5, tzinfo=timezone.utc),
    )

    with _hermes_home_env(home):
        write_state(state)
        payload = json.loads(get_raphael_state_path().read_text(encoding="utf-8"))
        round_tripped = read_state()
        tmp_files = list(get_raphael_state_dir().glob("*.tmp"))

    assert payload["schema_version"] == STATE_SCHEMA_VERSION
    assert round_tripped == state
    assert tmp_files == []


def test_write_state_does_not_claim_existing_fixed_tmp_file(tmp_path):
    home = tmp_path / "hermes-home"
    state = RaphaelState(
        status_cards=(),
        action_proposals=(),
        updated_at=datetime(2026, 6, 16, 9, 5, tzinfo=timezone.utc),
    )

    with _hermes_home_env(home):
        get_raphael_state_dir().mkdir(parents=True)
        stale_tmp = get_raphael_state_path().with_suffix(".json.tmp")
        stale_tmp.write_text("owned by another writer", encoding="utf-8")
        write_state(state)

    assert stale_tmp.read_text(encoding="utf-8") == "owned by another writer"


def test_append_event_writes_jsonl_with_event_schema(tmp_path):
    home = tmp_path / "hermes-home"
    event = RaphaelEvent(
        event_id="event-1",
        kind="state_written",
        created_at=datetime(2026, 6, 16, 9, 10, tzinfo=timezone.utc),
        details={"path": "state.json"},
    )

    with _hermes_home_env(home):
        append_event(event)
        lines = get_raphael_events_path().read_text(encoding="utf-8").splitlines()

    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["schema_version"] == EVENT_SCHEMA_VERSION
    assert payload == event.to_dict()
