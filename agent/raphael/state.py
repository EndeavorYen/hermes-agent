from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

from hermes_constants import get_hermes_home
from utils import atomic_json_write

from agent.raphael.models import ActionProposal, RaphaelEvent, RaphaelState


RESOLVED_ACTION_PROPOSAL_STATUSES = frozenset({"approved", "rejected"})


def get_raphael_state_dir() -> Path:
    return get_hermes_home() / "raphael"


def get_raphael_state_path() -> Path:
    return get_raphael_state_dir() / "state.json"


def get_raphael_events_path() -> Path:
    return get_raphael_state_dir() / "events.jsonl"


def get_raphael_skill_traces_path() -> Path:
    return get_raphael_state_dir() / "skill_traces.jsonl"


def read_state() -> RaphaelState:
    path = get_raphael_state_path()
    if not path.exists():
        return RaphaelState.empty()
    return RaphaelState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def write_state(state: RaphaelState) -> None:
    atomic_json_write(get_raphael_state_path(), state.to_dict(), sort_keys=True)


def append_event(event: RaphaelEvent) -> None:
    state_dir = get_raphael_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    with get_raphael_events_path().open("a", encoding="utf-8") as events_file:
        events_file.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")


def resolve_action_proposal(
    proposal_id: str,
    *,
    status: str,
    resolved_by: str,
    note: str = "",
    now: datetime | None = None,
) -> ActionProposal:
    resolution_status = str(status)
    if resolution_status not in RESOLVED_ACTION_PROPOSAL_STATUSES:
        raise ValueError(
            "Raphael action proposal status must be approved or rejected"
        )

    resolved_at = _ensure_utc(now) if now is not None else _utc_now()
    state = read_state()
    proposals = list(state.action_proposals)
    for index, proposal in enumerate(proposals):
        if proposal.proposal_id != proposal_id:
            continue
        metadata = dict(proposal.metadata or {})
        metadata["resolution"] = {
            "status": resolution_status,
            "resolved_by": str(resolved_by),
            "resolved_at": resolved_at.isoformat(),
            "note": str(note),
            "durable_policy_mutated": False,
        }
        updated = replace(proposal, status=resolution_status, metadata=metadata)
        proposals[index] = updated
        write_state(
            replace(
                state,
                action_proposals=tuple(proposals),
                updated_at=resolved_at,
            )
        )
        append_event(
            RaphaelEvent(
                event_id=f"action-proposal-resolved-{proposal_id}-{resolved_at.isoformat()}",
                kind="action_proposal_resolved",
                created_at=resolved_at,
                details={
                    "proposal_id": proposal_id,
                    "action_type": proposal.action_type,
                    "risk": proposal.risk.value,
                    "status": resolution_status,
                    "resolved_by": str(resolved_by),
                    "note": str(note),
                    "durable_policy_mutated": False,
                },
            )
        )
        return updated

    raise KeyError(f"Raphael action proposal not found: {proposal_id}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "append_event",
    "get_raphael_events_path",
    "get_raphael_skill_traces_path",
    "get_raphael_state_dir",
    "get_raphael_state_path",
    "read_state",
    "resolve_action_proposal",
    "write_state",
]
