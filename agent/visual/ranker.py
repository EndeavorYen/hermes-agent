"""Transparent rule-based ranking for visual artifacts."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


RANKER_VERSION = "visual-ranker-v0"

WEIGHTS = {
    "artifact_validity": 0.35,
    "freshness_stability": 0.25,
    "fit": 0.15,
    "provider_reliability": 0.15,
    "delivery_confidence": 0.10,
}


def rank_visual_candidates(candidates: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Rank visual candidates using deterministic, auditable signals."""
    ranked: List[Dict[str, Any]] = []
    failed_candidates: List[Dict[str, Any]] = []

    for index, candidate in enumerate(candidates or []):
        if not _hard_gate_passed(candidate):
            failed_candidates.append(candidate)
            continue
        ranked.append(_ranked_candidate(candidate, index))

    if not ranked:
        return {
            "ranker_version": RANKER_VERSION,
            "decision": "retry" if _has_retryable_candidate(failed_candidates) else "fail",
            "selected_artifact_id": None,
            "selected_attempt_id": None,
            "confidence": 0.0,
            "ranked_candidates": [],
        }

    ranked.sort(key=lambda item: (-item["confidence"], item["candidate_index"]))
    selected = ranked[0]
    confidence = float(selected["confidence"])
    decision = "post" if confidence >= 0.70 else "ask_user"
    return {
        "ranker_version": RANKER_VERSION,
        "decision": decision,
        "selected_artifact_id": selected.get("artifact_id"),
        "selected_attempt_id": selected.get("attempt_id"),
        "confidence": confidence,
        "ranked_candidates": ranked,
    }


def _ranked_candidate(candidate: Dict[str, Any], index: int) -> Dict[str, Any]:
    scores = _score_map(candidate)
    components = {
        "artifact_validity": _average_score(
            scores,
            ("artifact_exists", "content_hash_present", "mime_valid", "byte_size_valid"),
        ),
        "freshness_stability": _average_score(
            scores,
            ("artifact_fresh", "artifact_stable"),
        ),
        "fit": _average_score(scores, ("aspect_fit", "duration_fit")),
        "provider_reliability": _score_value(
            candidate.get("provider_reliability"),
            default=0.75,
        ),
        "delivery_confidence": _score_value(
            candidate.get("delivery_confidence"),
            default=_score_value(scores.get("delivery_possible"), default=1.0),
        ),
    }
    confidence = round(
        sum(components[key] * weight for key, weight in WEIGHTS.items()),
        4,
    )
    return {
        "candidate_index": index,
        "artifact_id": candidate.get("artifact_id"),
        "attempt_id": candidate.get("attempt_id"),
        "confidence": confidence,
        "component_scores": components,
    }


def _hard_gate_passed(candidate: Dict[str, Any]) -> bool:
    score = candidate.get("deterministic_score") or {}
    hard_gate = score.get("hard_gate") or {}
    return bool(hard_gate.get("passed"))


def _score_map(candidate: Dict[str, Any]) -> Dict[str, Any]:
    score = candidate.get("deterministic_score") or {}
    scores = score.get("scores") or {}
    return scores if isinstance(scores, dict) else {}


def _average_score(
    scores: Dict[str, Any],
    keys: Iterable[str],
    *,
    default: float = 1.0,
) -> float:
    values = [_score_value(scores.get(key), default=default) for key in keys]
    return round(sum(values) / len(values), 4) if values else default


def _score_value(value: Any, *, default: float) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, number))


def _has_retryable_candidate(candidates: List[Dict[str, Any]]) -> bool:
    return any(candidate.get("retryable", True) for candidate in candidates)
