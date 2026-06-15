from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

STATE_SCHEMA_VERSION = "raphael.state.v1"
EVENT_SCHEMA_VERSION = "raphael.event.v1"


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


@dataclass(frozen=True)
class StatusCard:
    card_id: str
    severity: RiskLevel
    title: str
    summary: str
    observed_at: datetime
    expires_at: datetime
    source: str
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", RiskLevel(self.severity))
        object.__setattr__(self, "observed_at", _ensure_utc(self.observed_at))
        object.__setattr__(self, "expires_at", _ensure_utc(self.expires_at))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "severity": self.severity.value,
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
            severity=RiskLevel(payload["severity"]),
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
    "STATE_SCHEMA_VERSION",
    "StatusCard",
]
