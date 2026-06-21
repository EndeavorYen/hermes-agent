from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VERSION = "visual_ranker.v0.1"


@dataclass(frozen=True)
class VisualRankDecision:
    request_id: str
    decision: str
    selected_artifact_id: str | None
    selected_attempt_id: str | None
    ranked_artifact_ids: list[str]
    reason: str
    version: str = VERSION


def rank_visual_candidates(
    *,
    request_id: str,
    candidates: list[dict[str, Any]],
    post_threshold: float = 0.70,
    ask_threshold: float = 0.55,
) -> VisualRankDecision:
    if not candidates:
        return VisualRankDecision(
            request_id=request_id,
            decision="fail",
            selected_artifact_id=None,
            selected_attempt_id=None,
            ranked_artifact_ids=[],
            reason="no_candidates",
        )

    passed_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("hard_gate", {}).get("passed") is True
    ]
    ranked = sorted(
        passed_candidates,
        key=lambda candidate: (
            float(candidate.get("scores", {}).get("final_score") or 0.0),
            str(candidate.get("artifact_id") or ""),
        ),
        reverse=True,
    )
    ranked_artifact_ids = [
        str(candidate["artifact_id"])
        for candidate in ranked
        if candidate.get("artifact_id")
    ]
    if not ranked:
        return VisualRankDecision(
            request_id=request_id,
            decision="retry",
            selected_artifact_id=None,
            selected_attempt_id=None,
            ranked_artifact_ids=[],
            reason="no_candidate_passed_hard_gate",
        )

    top = ranked[0]
    top_score = float(top.get("scores", {}).get("final_score") or 0.0)
    if top_score >= post_threshold:
        decision = "post"
        reason = "top_candidate_above_post_threshold"
        selected_artifact_id = top.get("artifact_id")
        selected_attempt_id = top.get("attempt_id")
    elif top_score >= ask_threshold:
        decision = "ask_user"
        reason = "top_candidate_requires_user_review"
        selected_artifact_id = top.get("artifact_id")
        selected_attempt_id = top.get("attempt_id")
    else:
        decision = "retry"
        reason = "top_candidate_below_ask_threshold"
        selected_artifact_id = None
        selected_attempt_id = None

    return VisualRankDecision(
        request_id=request_id,
        decision=decision,
        selected_artifact_id=selected_artifact_id,
        selected_attempt_id=selected_attempt_id,
        ranked_artifact_ids=ranked_artifact_ids,
        reason=reason,
    )
