from __future__ import annotations

import json
from pathlib import Path

from hermes_constants import get_hermes_home

from agent.raphael.models import RaphaelEvent, RaphaelState


def get_raphael_state_dir() -> Path:
    return get_hermes_home() / "raphael"


def get_raphael_state_path() -> Path:
    return get_raphael_state_dir() / "state.json"


def get_raphael_events_path() -> Path:
    return get_raphael_state_dir() / "events.jsonl"


def read_state() -> RaphaelState:
    path = get_raphael_state_path()
    if not path.exists():
        return RaphaelState.empty()
    return RaphaelState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def write_state(state: RaphaelState) -> None:
    state_dir = get_raphael_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    path = get_raphael_state_path()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(
            json.dumps(state.to_dict(), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def append_event(event: RaphaelEvent) -> None:
    state_dir = get_raphael_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    with get_raphael_events_path().open("a", encoding="utf-8") as events_file:
        events_file.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")


__all__ = [
    "append_event",
    "get_raphael_events_path",
    "get_raphael_state_dir",
    "get_raphael_state_path",
    "read_state",
    "write_state",
]
