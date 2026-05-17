"""Validation helpers for Layer-2 sidecar payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Layer2ValidationIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class Layer2ValidationResult:
    valid: bool
    payload: dict[str, Any]
    issues: list[Layer2ValidationIssue]


def _source_ids(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_event_id") or "").strip()
        if source_id:
            ids.add(source_id)
    return ids


def _evidence_ids(item: dict[str, Any]) -> set[str]:
    raw = item.get("evidence_source_event_ids")
    if raw is None:
        raw = item.get("evidence_source_event_id")
    if raw is None:
        raw = item.get("source_event_id")
    if isinstance(raw, str):
        return {raw.strip()} if raw.strip() else set()
    if isinstance(raw, (list, tuple, set)):
        return {str(value).strip() for value in raw if str(value).strip()}
    return set()


def validate_layer2_payload(payload: dict[str, Any]) -> Layer2ValidationResult:
    if not isinstance(payload, dict):
        return Layer2ValidationResult(
            valid=False,
            payload={},
            issues=[
                Layer2ValidationIssue(
                    "payload_not_object",
                    "$",
                    "Layer-2 payload must be a JSON object.",
                )
            ],
        )

    normalized = dict(payload)
    issues: list[Layer2ValidationIssue] = []
    observation_ids = _source_ids(normalized.get("observations"))
    events = normalized.get("candidate_events")
    if isinstance(events, list):
        normalized_events: list[Any] = []
        for index, item in enumerate(events):
            if not isinstance(item, dict):
                normalized_events.append(item)
                continue
            cloned = dict(item)
            action = str(cloned.get("action") or cloned.get("event_type") or "").strip().lower()
            wants_recurrence = bool(cloned.get("counts_for_recurrence", True))
            if wants_recurrence and action in {"create", "strengthen", "contradict"}:
                evidence_ids = _evidence_ids(cloned)
                if not evidence_ids or not evidence_ids <= observation_ids:
                    cloned["counts_for_recurrence"] = False
                    issues.append(
                        Layer2ValidationIssue(
                            "unbacked_recurrence_demoted",
                            f"$.candidate_events[{index}]",
                            "Candidate recurrence evidence must link to an observation source_event_id in the same payload.",
                        )
                    )
            normalized_events.append(cloned)
        normalized["candidate_events"] = normalized_events

    return Layer2ValidationResult(valid=True, payload=normalized, issues=issues)
