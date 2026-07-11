from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows only.
    fcntl = None
try:
    import msvcrt
except ImportError:  # pragma: no cover - Unix only.
    msvcrt = None

from hermes_constants import get_hermes_home
from utils import atomic_json_write

from agent.raphael.labels import format_control_decision_summary
from agent.raphael.mission import RaphaelMissionState
from agent.raphael.models import (
    MissionArtifact,
    RaphaelEvent,
    RaphaelMission,
    RaphaelState,
    StatusCard,
    action_proposal_ref,
)
from agent.raphael.redaction import REDACTED_VALUE, redact_trace_payload
from agent.raphael.runtime_contract import (
    RaphaelTurnOrigin,
    resolve_raphael_turn_origin,
)

_ACTION_PROPOSAL_RESOLUTION_STATUSES = frozenset({"approved", "rejected"})
_SECRET_VALUE_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{3,}|xox[baprs]-[A-Za-z0-9_\-]{3,}|"
    r"gh[pousr]_[A-Za-z0-9_\-]{3,}|ya29\.[A-Za-z0-9_\-]{3,}|"
    r"AIza[A-Za-z0-9_\-]{3,})\b"
)
_PRIVATE_PATH_RE = re.compile(
    r"(?:(?:/Users|/private/tmp|/private/var|/tmp)/[^\s,;:'\")\]}]+)"
)
_DATA_URI_RE = re.compile(r"data:[a-z0-9.+/-]+;base64,[a-z0-9+/=_-]+", re.I)
_LONG_BASE64ISH_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{80,}\b")
_RESOLUTION_TEXT_LIMIT = 240
_STATE_LOCK = threading.RLock()
_STATE_LOCK_CONTEXT = threading.local()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def raphael_state_lock():
    """Serialize Raphael state transactions across threads and processes."""
    with _STATE_LOCK:
        depth = getattr(_STATE_LOCK_CONTEXT, "depth", 0)
        if depth:
            _STATE_LOCK_CONTEXT.depth = depth + 1
            try:
                yield
            finally:
                _STATE_LOCK_CONTEXT.depth -= 1
            return

        state_dir = get_raphael_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        lock_file = (state_dir / ".state.lock").open("a+b")
        try:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            elif msvcrt is not None:  # pragma: no branch - platform-specific.
                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            else:  # pragma: no cover - supported platforms provide one backend.
                raise RuntimeError("Raphael cross-process state locking is unavailable")
            _STATE_LOCK_CONTEXT.depth = 1
            try:
                yield
            finally:
                _STATE_LOCK_CONTEXT.depth = 0
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                else:  # pragma: no branch - platform-specific.
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            lock_file.close()


def get_raphael_state_dir() -> Path:
    return get_hermes_home() / "raphael"


def get_raphael_state_path() -> Path:
    return get_raphael_state_dir() / "state.json"


def get_raphael_events_path() -> Path:
    return get_raphael_state_dir() / "events.jsonl"


def get_raphael_skill_traces_path() -> Path:
    return get_raphael_state_dir() / "skill_traces.jsonl"


def get_raphael_mission_path() -> Path:
    return get_raphael_state_dir() / "mission.json"


def read_state() -> RaphaelState:
    path = get_raphael_state_path()
    if not path.exists():
        return RaphaelState.empty()
    with raphael_state_lock():
        if not path.exists():
            return RaphaelState.empty()
        return RaphaelState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def write_state(state: RaphaelState) -> None:
    with raphael_state_lock():
        atomic_json_write(get_raphael_state_path(), state.to_dict(), sort_keys=True)


def append_event(event: RaphaelEvent) -> None:
    with raphael_state_lock():
        state_dir = get_raphael_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        with get_raphael_events_path().open("a", encoding="utf-8") as events_file:
            events_file.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")


def resolve_action_proposal(
    proposal_id: str,
    status: str,
    *,
    reviewer: str | None = None,
    reason: str = "",
    evidence_refs: tuple[str, ...] = (),
    now: datetime | None = None,
    resolved_by: str | None = None,
    note: str | None = None,
) -> Any | None:
    """Approve or reject a pending Raphael action proposal with an audit event."""
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in _ACTION_PROPOSAL_RESOLUTION_STATUSES:
        raise ValueError(
            "Raphael action proposal status must be 'approved' or 'rejected'"
        )
    proposal_key = str(proposal_id or "").strip()
    if not proposal_key:
        return None
    reviewer = reviewer or resolved_by or "operator"
    if not reason and note:
        reason = note
    resolved_at = now or _utc_now()
    with raphael_state_lock():
        state = read_state()
        updated_proposals = []
        updated_proposal = None
        previous_status = ""
        for proposal in state.action_proposals:
            if (
                proposal.proposal_id != proposal_key
                and action_proposal_ref(proposal.proposal_id) != proposal_key.lower()
            ):
                updated_proposals.append(proposal)
                continue
            previous_status = str(proposal.status or "").strip().lower()
            if previous_status != "pending":
                updated_proposals.append(proposal)
                continue
            metadata = _proposal_metadata_with_resolution(
                proposal.metadata,
                status=normalized_status,
                reviewer=reviewer,
                reason=reason,
                evidence_refs=evidence_refs,
                resolved_at=resolved_at,
            )
            updated_proposal = replace(
                proposal,
                status=normalized_status,
                metadata=metadata,
            )
            updated_proposals.append(updated_proposal)
        if updated_proposal is None:
            return None
        write_state(
            RaphaelState(
                status_cards=state.status_cards,
                action_proposals=tuple(updated_proposals),
                updated_at=resolved_at,
                active_mission=state.active_mission,
            )
        )
    append_event(
        RaphaelEvent(
            event_id=_action_proposal_resolution_event_id(
                proposal_id=updated_proposal.proposal_id,
                status=normalized_status,
                resolved_at=resolved_at,
            ),
            kind="action_proposal_resolved",
            created_at=resolved_at,
            details={
                "proposal_id": updated_proposal.proposal_id,
                "action_type": updated_proposal.action_type,
                "risk": updated_proposal.risk.value,
                "from_status": previous_status,
                "to_status": normalized_status,
                "reviewer": _redacted_resolution_text(reviewer, limit=80),
                "reason": _redacted_resolution_text(reason),
                "evidence_refs": [
                    _redacted_resolution_text(ref, limit=120)
                    for ref in evidence_refs
                    if str(ref).strip()
                ],
            },
        )
    )
    return updated_proposal


def _proposal_metadata_with_resolution(
    metadata: Mapping[str, Any] | None,
    *,
    status: str,
    reviewer: str,
    reason: str,
    evidence_refs: tuple[str, ...],
    resolved_at: datetime,
) -> dict[str, Any]:
    updated = dict(metadata) if isinstance(metadata, Mapping) else {}
    rollout_plan = updated.get("rollout_plan")
    if isinstance(rollout_plan, Mapping):
        updated["rollout_plan"] = {**dict(rollout_plan), "status": status}
    updated["resolution"] = {
        "status": status,
        "reviewer": _redacted_resolution_text(reviewer, limit=80),
        "reason": _redacted_resolution_text(reason),
        "resolved_at": resolved_at.isoformat(),
        "durable_policy_mutated": False,
        "evidence_refs": [
            _redacted_resolution_text(ref, limit=120)
            for ref in evidence_refs
            if str(ref).strip()
        ],
    }
    return updated


def _action_proposal_resolution_event_id(
    *,
    proposal_id: str,
    status: str,
    resolved_at: datetime,
) -> str:
    seed = "|".join((proposal_id, status, resolved_at.isoformat()))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"action-proposal-{digest}"


def _redacted_resolution_text(
    value: Any,
    *,
    limit: int = _RESOLUTION_TEXT_LIMIT,
) -> str:
    redacted = redact_trace_payload(value, max_string_length=limit)
    text = "" if redacted is None else str(redacted)
    text = _SECRET_VALUE_RE.sub(REDACTED_VALUE, text)
    text = _DATA_URI_RE.sub("[redacted-media]", text)
    text = _PRIVATE_PATH_RE.sub("[redacted-path]", text)
    text = _LONG_BASE64ISH_RE.sub("[redacted-payload]", text)
    text = " ".join(text.split())
    return text[: max(0, limit)]


def read_active_mission() -> RaphaelMission | None:
    if not get_raphael_state_path().exists() and not get_raphael_mission_path().exists():
        return None
    with raphael_state_lock():
        state = read_state()
        if state.active_mission is not None:
            return state.active_mission

        legacy = _read_legacy_mission_state()
        if legacy is None:
            return None
        mission = _mission_from_legacy_state(legacy)
        write_state(
            RaphaelState(
                status_cards=state.status_cards,
                action_proposals=state.action_proposals,
                updated_at=mission.updated_at,
                active_mission=mission,
            )
        )
        path = get_raphael_mission_path()
        if path.exists():
            path.unlink()
        append_event(
            RaphaelEvent(
                event_id=f"mission-migrated-{legacy.mission_id}",
                kind="mission_state_migrated",
                created_at=_utc_now(),
                details={
                    "source": "raphael_mission_v1",
                    "target": "raphael_state_active_mission",
                    "mission_id": legacy.mission_id,
                },
            )
        )
        return mission


def write_active_mission(
    mission: RaphaelMission | None,
    *,
    origin: str | RaphaelTurnOrigin = RaphaelTurnOrigin.FOREGROUND,
) -> RaphaelMission | None:
    resolved_origin = resolve_raphael_turn_origin(explicit_origin=origin)
    with raphael_state_lock():
        state = read_state()
        if resolved_origin is not RaphaelTurnOrigin.FOREGROUND:
            return state.active_mission
        updated_at = mission.updated_at if mission is not None else _utc_now()
        write_state(
            RaphaelState(
                status_cards=state.status_cards,
                action_proposals=state.action_proposals,
                updated_at=updated_at,
                active_mission=mission,
            )
        )
        legacy_path = get_raphael_mission_path()
        if legacy_path.exists():
            legacy_path.unlink()
        return mission


def _read_legacy_mission_state() -> RaphaelMissionState | None:
    path = get_raphael_mission_path()
    if not path.exists():
        return None
    return RaphaelMissionState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _mission_from_legacy_state(legacy: RaphaelMissionState) -> RaphaelMission:
    artifacts: tuple[MissionArtifact, ...] = ()
    if legacy.active_artifact_id:
        artifact_id = str(legacy.active_artifact_id)
        artifacts = (
            MissionArtifact(
                artifact_id=artifact_id,
                kind="legacy_reference",
                label=artifact_id,
                uri=f"artifact://{artifact_id}",
                created_at=legacy.updated_at,
            ),
        )
    return RaphaelMission(
        mission_id=legacy.mission_id,
        goal=legacy.goal,
        active_artifact_id=legacy.active_artifact_id,
        artifacts=artifacts,
        success_conditions=legacy.required_proofs,
        phase=legacy.phase,
        blockers=legacy.blockers,
        next_action=legacy.next_action,
        selected_strategy=legacy.selected_strategy_id,
        required_proofs=legacy.required_proofs,
        last_evidence=(),
        updated_at=legacy.updated_at,
        proof_status=legacy.proof_status,
        created_at=legacy.updated_at,
    )


def _legacy_state_from_mission(mission: RaphaelMission) -> RaphaelMissionState:
    return RaphaelMissionState(
        mission_id=mission.mission_id,
        goal=mission.goal,
        phase=mission.phase,
        selected_strategy_id=mission.selected_strategy,
        active_artifact_id=mission.active_artifact_id,
        blockers=mission.blockers,
        next_action=mission.next_action,
        proof_status=mission.proof_status,
        required_proofs=mission.required_proofs,
        updated_at=mission.updated_at,
    )


def read_mission_state() -> RaphaelMissionState | None:
    mission = read_active_mission()
    return None if mission is None else _legacy_state_from_mission(mission)


def write_mission_state(mission: RaphaelMissionState | None) -> None:
    active = None if mission is None else _mission_from_legacy_state(mission)
    write_active_mission(active)


def record_control_decision(
    decision: Mapping[str, Any],
    *,
    turn_id: str | None = None,
    task_id: str | None = None,
    source: str = "raphael_control",
) -> None:
    now = _utc_now()
    mode = str(decision.get("mode") or "unknown")
    goal = decision.get("goal") if isinstance(decision.get("goal"), Mapping) else {}
    evidence = (
        decision.get("evidence")
        if isinstance(decision.get("evidence"), Mapping)
        else {}
    )
    blockers = [
        str(blocker)
        for blocker in (goal.get("blockers") if isinstance(goal, Mapping) else ()) or ()
        if str(blocker)
    ]
    failure_layer = str(evidence.get("failure_layer") or "").strip()
    next_action = str(decision.get("next_action") or "unknown")
    phase = str(goal.get("phase") or "unknown") if isinstance(goal, Mapping) else "unknown"
    target = (
        str(goal.get("target_artifact") or "unknown")
        if isinstance(goal, Mapping)
        else "unknown"
    )
    severity = "warning" if mode == "needs_clarification" or failure_layer else "info"
    title = (
        "Raphael blocked visual handoff"
        if mode == "needs_clarification"
        else "Raphael control decision"
    )
    summary = format_control_decision_summary(
        mode=mode,
        target=target,
        phase=phase,
        next_action=next_action,
        blockers=blockers[:4],
        failure_layer=failure_layer,
    )
    event_seed = "|".join(
        part
        for part in (
            turn_id or "",
            task_id or "",
            source,
            mode,
            next_action,
            ",".join(blockers),
            failure_layer,
        )
        if part
    )
    event_hash = hashlib.sha256(event_seed.encode("utf-8")).hexdigest()[:16]
    event_id = f"control-{event_hash}"
    evidence_refs = tuple(
        ref for ref in (f"turn:{turn_id}" if turn_id else "", f"task:{task_id}" if task_id else "") if ref
    )
    with raphael_state_lock():
        state = read_state()
        existing_cards = tuple(
            card for card in state.status_cards if card.expires_at > now
        )[:19]
        card = StatusCard(
            card_id=f"card-{event_hash}",
            severity=severity,
            title=title,
            summary=summary,
            observed_at=now,
            expires_at=now + timedelta(hours=6),
            source=source,
            confidence=float(decision.get("confidence") or 0.0),
            evidence_refs=evidence_refs,
        )
        write_state(
            RaphaelState(
                status_cards=(card, *existing_cards),
                action_proposals=state.action_proposals,
                updated_at=now,
                active_mission=state.active_mission,
            )
        )
    append_event(
        RaphaelEvent(
            event_id=event_id,
            kind="control_decision",
            created_at=now,
            details={
                "mode": mode,
                "target_artifact": target,
                "phase": phase,
                "next_action": next_action,
                "reference_resolution": str(
                    decision.get("reference_resolution") or "unknown"
                ),
                "blockers": blockers,
                "failure_layer": failure_layer or None,
                "source": source,
                "turn_id": turn_id,
                "task_id": task_id,
            },
        )
    )


__all__ = [
    "append_event",
    "get_raphael_events_path",
    "get_raphael_mission_path",
    "get_raphael_skill_traces_path",
    "get_raphael_state_dir",
    "get_raphael_state_path",
    "read_active_mission",
    "read_mission_state",
    "read_state",
    "raphael_state_lock",
    "record_control_decision",
    "resolve_action_proposal",
    "write_mission_state",
    "write_active_mission",
    "write_state",
]
