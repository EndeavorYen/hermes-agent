"""Deterministic selection policy for Layer-2 recall candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Layer2SelectionPolicy:
    max_items: int = 6
    min_net_support: int = 1
    exclude_statuses: tuple[str, ...] = ("stale", "quarantine", "pruned", "promoted")


@dataclass(frozen=True)
class Layer2SelectedCandidate:
    candidate: dict[str, Any]
    score: int
    reason_codes: list[str]


def _terms(text: str | None) -> set[str]:
    return {
        term
        for term in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(term) >= 2
    }


def _haystack(candidate: dict[str, Any]) -> str:
    return " ".join(
        str(candidate.get(key) or "")
        for key in ("canonical_text", "kind", "routing_destination", "proposed_target")
    ).lower()


def score_candidate(
    candidate: dict[str, Any],
    *,
    query_text: str | None = None,
    subject_scope: str | None = None,
    subject_id: str | None = None,
    policy: Layer2SelectionPolicy | None = None,
) -> Layer2SelectedCandidate | None:
    active_policy = policy or Layer2SelectionPolicy()
    status = str(candidate.get("status") or "active").strip().lower()
    if status in active_policy.exclude_statuses:
        return None

    support = int(candidate.get("support_count") or 0)
    contradict = int(candidate.get("contradict_count") or 0)
    net_support = support - contradict
    if net_support < active_policy.min_net_support:
        return None

    score = net_support * 10
    reasons = ["net_support"]

    candidate_scope = str(candidate.get("subject_scope") or "").strip()
    candidate_subject = str(candidate.get("subject_id") or "").strip()
    if subject_scope and candidate_scope == subject_scope:
        score += 50
        reasons.append("scope_match")
    if subject_id and candidate_subject == subject_id:
        score += 50
        reasons.append("subject_match")

    query_terms = _terms(query_text)
    if query_terms:
        matches = sum(1 for term in query_terms if term in _haystack(candidate))
        if matches:
            score += matches * 30
            reasons.append("query_match")

    return Layer2SelectedCandidate(
        candidate=candidate,
        score=score,
        reason_codes=reasons,
    )


def select_candidates(
    candidates: list[dict[str, Any]],
    *,
    query_text: str | None = None,
    subject_scope: str | None = None,
    subject_id: str | None = None,
    policy: Layer2SelectionPolicy | None = None,
) -> list[Layer2SelectedCandidate]:
    active_policy = policy or Layer2SelectionPolicy()
    selected: list[Layer2SelectedCandidate] = []
    for candidate in candidates:
        item = score_candidate(
            candidate,
            query_text=query_text,
            subject_scope=subject_scope,
            subject_id=subject_id,
            policy=active_policy,
        )
        if item is not None:
            selected.append(item)

    selected.sort(
        key=lambda item: (
            -item.score,
            -int(item.candidate.get("support_count") or 0),
            str(item.candidate.get("canonical_text") or ""),
        )
    )
    return selected[: max(1, int(active_policy.max_items))]
