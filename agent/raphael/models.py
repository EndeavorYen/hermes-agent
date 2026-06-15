from __future__ import annotations

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

STATE_SCHEMA_VERSION = "raphael.state.v1"
EVENT_SCHEMA_VERSION = "raphael.event.v1"
SKILL_TRACE_SCHEMA_VERSION = "raphael.skill_trace.v1"


class RiskLevel(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R1_5 = "R1.5"
    R2 = "R2"
    R3 = "R3"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _datetime_to_iso(value: datetime) -> str:
    return _ensure_utc(value).isoformat()


def _datetime_from_iso(value: str) -> datetime:
    normalized = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
    return _ensure_utc(datetime.fromisoformat(normalized))


def _require_schema(payload: Mapping[str, Any], expected: str, label: str) -> None:
    if payload.get("schema_version") != expected:
        raise ValueError(
            f"Unsupported Raphael {label} schema: {payload.get('schema_version')!r}"
        )


@dataclass(frozen=True)
class StatusCard:
    card_id: str
    severity: str
    title: str
    summary: str
    observed_at: datetime
    expires_at: datetime
    source: str
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", str(self.severity))
        object.__setattr__(self, "observed_at", _ensure_utc(self.observed_at))
        object.__setattr__(self, "expires_at", _ensure_utc(self.expires_at))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "severity": self.severity,
            "title": self.title,
            "summary": self.summary,
            "observed_at": _datetime_to_iso(self.observed_at),
            "expires_at": _datetime_to_iso(self.expires_at),
            "source": self.source,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StatusCard:
        return cls(
            card_id=payload["card_id"],
            severity=payload["severity"],
            title=payload["title"],
            summary=payload["summary"],
            observed_at=_datetime_from_iso(payload["observed_at"]),
            expires_at=_datetime_from_iso(payload["expires_at"]),
            source=payload["source"],
            confidence=payload["confidence"],
            evidence_refs=tuple(payload["evidence_refs"]),
        )


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    action_type: str
    risk: RiskLevel
    summary: str
    evidence_refs: tuple[str, ...]
    created_at: datetime
    status: str = "pending"

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk", RiskLevel(self.risk))
        object.__setattr__(self, "created_at", _ensure_utc(self.created_at))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    @property
    def requires_approval(self) -> bool:
        return self.risk in {RiskLevel.R2, RiskLevel.R3}

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "action_type": self.action_type,
            "risk": self.risk.value,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "created_at": _datetime_to_iso(self.created_at),
            "status": self.status,
            "requires_approval": self.requires_approval,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ActionProposal:
        return cls(
            proposal_id=payload["proposal_id"],
            action_type=payload["action_type"],
            risk=RiskLevel(payload["risk"]),
            summary=payload["summary"],
            evidence_refs=tuple(payload["evidence_refs"]),
            created_at=_datetime_from_iso(payload["created_at"]),
            status=payload.get("status", "pending"),
        )


@dataclass(frozen=True)
class RaphaelEvent:
    event_id: str
    kind: str
    created_at: datetime
    details: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _ensure_utc(self.created_at))
        object.__setattr__(self, "details", dict(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": self.event_id,
            "kind": self.kind,
            "created_at": _datetime_to_iso(self.created_at),
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RaphaelEvent:
        _require_schema(payload, EVENT_SCHEMA_VERSION, "event")
        return cls(
            event_id=payload["event_id"],
            kind=payload["kind"],
            created_at=_datetime_from_iso(payload["created_at"]),
            details=payload.get("details", {}),
        )


@dataclass(frozen=True)
class SkillTrace:
    trace_id: str
    task_id: str
    created_at: datetime
    source: str
    skills_used: tuple[str, ...]
    tools_used: tuple[str, ...]
    outcome: str
    user_corrections: tuple[str, ...] = ()
    risk_incidents: tuple[str, ...] = ()
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _ensure_utc(self.created_at))
        object.__setattr__(
            self, "skills_used", tuple(str(skill) for skill in self.skills_used)
        )
        object.__setattr__(
            self, "tools_used", tuple(str(tool) for tool in self.tools_used)
        )
        object.__setattr__(
            self,
            "user_corrections",
            tuple(str(correction) for correction in self.user_corrections),
        )
        object.__setattr__(
            self,
            "risk_incidents",
            tuple(str(incident) for incident in self.risk_incidents),
        )
        if self.metadata is not None:
            if not isinstance(self.metadata, MappingABC):
                raise TypeError("SkillTrace metadata must be a mapping or None")
            object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SKILL_TRACE_SCHEMA_VERSION,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "created_at": _datetime_to_iso(self.created_at),
            "source": self.source,
            "skills_used": list(self.skills_used),
            "tools_used": list(self.tools_used),
            "outcome": self.outcome,
            "user_corrections": list(self.user_corrections),
            "risk_incidents": list(self.risk_incidents),
            "metadata": None if self.metadata is None else dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SkillTrace:
        _require_schema(payload, SKILL_TRACE_SCHEMA_VERSION, "skill trace")
        metadata = payload.get("metadata")
        if metadata is not None and not isinstance(metadata, MappingABC):
            raise ValueError("Raphael skill trace metadata must be a mapping")
        return cls(
            trace_id=payload["trace_id"],
            task_id=payload["task_id"],
            created_at=_datetime_from_iso(payload["created_at"]),
            source=payload["source"],
            skills_used=tuple(payload.get("skills_used", ())),
            tools_used=tuple(payload.get("tools_used", ())),
            outcome=payload["outcome"],
            user_corrections=tuple(payload.get("user_corrections", ())),
            risk_incidents=tuple(payload.get("risk_incidents", ())),
            metadata=metadata,
        )


@dataclass(frozen=True)
class SkillTraceSummary:
    skill_name: str
    use_count: int
    view_count: int
    patch_count: int
    latest_activity_at: datetime | None
    state: str | None
    created_by: str | None
    outcome_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "use_count", int(self.use_count))
        object.__setattr__(self, "view_count", int(self.view_count))
        object.__setattr__(self, "patch_count", int(self.patch_count))
        if self.latest_activity_at is not None:
            object.__setattr__(
                self, "latest_activity_at", _ensure_utc(self.latest_activity_at)
            )
        object.__setattr__(
            self,
            "outcome_counts",
            {str(outcome): int(count) for outcome, count in self.outcome_counts.items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "use_count": self.use_count,
            "view_count": self.view_count,
            "patch_count": self.patch_count,
            "latest_activity_at": (
                None
                if self.latest_activity_at is None
                else _datetime_to_iso(self.latest_activity_at)
            ),
            "state": self.state,
            "created_by": self.created_by,
            "outcome_counts": dict(self.outcome_counts),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SkillTraceSummary:
        latest_activity_at = payload.get("latest_activity_at")
        return cls(
            skill_name=payload["skill_name"],
            use_count=payload.get("use_count", 0),
            view_count=payload.get("view_count", 0),
            patch_count=payload.get("patch_count", 0),
            latest_activity_at=(
                None
                if latest_activity_at is None
                else _datetime_from_iso(latest_activity_at)
            ),
            state=payload.get("state"),
            created_by=payload.get("created_by"),
            outcome_counts=payload.get("outcome_counts", {}),
        )


@dataclass(frozen=True)
class RaphaelState:
    status_cards: tuple[StatusCard, ...]
    action_proposals: tuple[ActionProposal, ...]
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "status_cards", tuple(self.status_cards))
        object.__setattr__(self, "action_proposals", tuple(self.action_proposals))
        object.__setattr__(self, "updated_at", _ensure_utc(self.updated_at))

    @classmethod
    def empty(cls) -> RaphaelState:
        return cls(status_cards=(), action_proposals=(), updated_at=_utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "status_cards": [card.to_dict() for card in self.status_cards],
            "action_proposals": [
                proposal.to_dict() for proposal in self.action_proposals
            ],
            "updated_at": _datetime_to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RaphaelState:
        _require_schema(payload, STATE_SCHEMA_VERSION, "state")
        return cls(
            status_cards=tuple(
                StatusCard.from_dict(card)
                for card in payload.get("status_cards", ())
            ),
            action_proposals=tuple(
                ActionProposal.from_dict(proposal)
                for proposal in payload.get("action_proposals", ())
            ),
            updated_at=_datetime_from_iso(payload["updated_at"]),
        )


__all__ = [
    "ActionProposal",
    "EVENT_SCHEMA_VERSION",
    "RaphaelEvent",
    "RaphaelState",
    "RiskLevel",
    "SKILL_TRACE_SCHEMA_VERSION",
    "STATE_SCHEMA_VERSION",
    "SkillTrace",
    "SkillTraceSummary",
    "StatusCard",
]
