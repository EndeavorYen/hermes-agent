from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualitySnapshot:
    artifact_id: str
    score: float
    blocker_codes: tuple[str, ...]
    deliverable: bool
    artifact_valid: bool

    def to_record(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "score": round(self.score, 4),
            "blocker_codes": list(self.blocker_codes),
            "deliverable": self.deliverable,
            "artifact_valid": self.artifact_valid,
        }


@dataclass(frozen=True)
class QualityLoopAttemptDecision:
    allowed: bool
    stop_reason: str | None


@dataclass(frozen=True)
class QualityLoopObservation:
    accepted: bool
    prior_champion: QualitySnapshot
    champion: QualitySnapshot
    challenger: QualitySnapshot
    stop_reason: str | None
    score_improvement: float
    blocker_reduction: int
    introduced_blocker_codes: tuple[str, ...]

    def to_record(self, *, round_index: int, repair_fingerprint: str) -> dict[str, Any]:
        return {
            "round": round_index,
            "repair_fingerprint": repair_fingerprint,
            "accepted": self.accepted,
            "prior_champion_artifact_id": self.prior_champion.artifact_id,
            "champion_artifact_id": self.champion.artifact_id,
            "challenger_artifact_id": self.challenger.artifact_id,
            "score_improvement": round(self.score_improvement, 4),
            "blocker_reduction": self.blocker_reduction,
            "introduced_blocker_codes": list(self.introduced_blocker_codes),
            "stop_reason": self.stop_reason,
        }


class BoundedQualityLoop:
    """Keep the best visual artifact while spending only productive repair rounds."""

    def __init__(
        self,
        champion: QualitySnapshot,
        *,
        max_rounds: int,
        min_score_improvement: float = 0.02,
        score_regression_tolerance: float = 0.01,
    ) -> None:
        self.champion = champion
        self.max_rounds = max(0, min(4, int(max_rounds)))
        self.min_score_improvement = max(0.0, float(min_score_improvement))
        self.score_regression_tolerance = max(0.0, float(score_regression_tolerance))
        self.rounds_attempted = 0
        self.stop_reason = "quality_gate_passed" if champion.deliverable else None
        self.history: list[dict[str, Any]] = []
        self._attempted_fingerprints: set[str] = set()

    def can_attempt(self, repair_fingerprint: str) -> QualityLoopAttemptDecision:
        fingerprint = str(repair_fingerprint or "").strip()
        if fingerprint and fingerprint in self._attempted_fingerprints:
            self.stop_reason = "repeated_strategy"
            return QualityLoopAttemptDecision(False, self.stop_reason)
        if self.stop_reason:
            return QualityLoopAttemptDecision(False, self.stop_reason)
        if self.champion.deliverable:
            self.stop_reason = "quality_gate_passed"
            return QualityLoopAttemptDecision(False, self.stop_reason)
        if self.rounds_attempted >= self.max_rounds:
            self.stop_reason = "budget_exhausted"
            return QualityLoopAttemptDecision(False, self.stop_reason)
        return QualityLoopAttemptDecision(True, None)

    def observe(
        self,
        challenger: QualitySnapshot,
        *,
        repair_fingerprint: str,
    ) -> QualityLoopObservation:
        decision = self.can_attempt(repair_fingerprint)
        if not decision.allowed:
            raise RuntimeError(f"quality loop cannot attempt repair: {decision.stop_reason}")

        previous = self.champion
        accepted = _challenger_improves(
            previous,
            challenger,
            min_score_improvement=self.min_score_improvement,
            score_regression_tolerance=self.score_regression_tolerance,
        )
        score_improvement = challenger.score - previous.score
        blocker_reduction = len(previous.blocker_codes) - len(challenger.blocker_codes)
        introduced_blocker_codes = tuple(
            code for code in challenger.blocker_codes if code not in previous.blocker_codes
        )
        self.rounds_attempted += 1
        fingerprint = str(repair_fingerprint or "").strip()
        if fingerprint:
            self._attempted_fingerprints.add(fingerprint)
        if accepted:
            self.champion = challenger

        if self.champion.deliverable:
            self.stop_reason = "quality_gate_passed"
        elif not accepted:
            retryable_near_equal = (
                challenger.artifact_valid
                and score_improvement >= -self.score_regression_tolerance
                and self.rounds_attempted < self.max_rounds
            )
            if not retryable_near_equal:
                self.stop_reason = "no_progress"
        elif self.rounds_attempted >= self.max_rounds:
            self.stop_reason = "budget_exhausted"

        observation = QualityLoopObservation(
            accepted=accepted,
            prior_champion=previous,
            champion=self.champion,
            challenger=challenger,
            stop_reason=self.stop_reason,
            score_improvement=score_improvement,
            blocker_reduction=blocker_reduction,
            introduced_blocker_codes=introduced_blocker_codes,
        )
        self.history.append(
            observation.to_record(
                round_index=self.rounds_attempted,
                repair_fingerprint=str(repair_fingerprint or "").strip(),
            )
        )
        return observation

    def to_record(self) -> dict[str, Any]:
        return {
            "mode": "bounded_champion_challenger",
            "max_rounds": self.max_rounds,
            "rounds_attempted": self.rounds_attempted,
            "min_score_improvement": self.min_score_improvement,
            "stop_reason": self.stop_reason,
            "champion": self.champion.to_record(),
            "history": list(self.history),
        }


def snapshot_from_candidate(
    candidate: dict[str, Any] | None,
    gate: dict[str, Any] | None,
) -> QualitySnapshot:
    candidate = candidate if isinstance(candidate, dict) else {}
    gate = gate if isinstance(gate, dict) else {}
    reward = candidate.get("reward") if isinstance(candidate.get("reward"), dict) else {}
    hard_gate = (
        candidate.get("hard_gate")
        if isinstance(candidate.get("hard_gate"), dict)
        else {}
    )
    blockers = gate.get("blocker_codes")
    if not isinstance(blockers, list):
        kernel = gate.get("visual_kernel") if isinstance(gate.get("visual_kernel"), dict) else {}
        blockers = kernel.get("blocker_codes")
    if not isinstance(blockers, list):
        blockers = gate.get("quality_issues")
    return QualitySnapshot(
        artifact_id=str(candidate.get("artifact_id") or ""),
        score=_float(reward.get("final_score")),
        blocker_codes=tuple(
            dict.fromkeys(str(item).strip() for item in (blockers or []) if str(item).strip())
        ),
        deliverable=gate.get("allowed") is True,
        artifact_valid=hard_gate.get("passed") is True,
    )


def _challenger_improves(
    champion: QualitySnapshot,
    challenger: QualitySnapshot,
    *,
    min_score_improvement: float,
    score_regression_tolerance: float,
) -> bool:
    if not challenger.artifact_valid:
        return False
    if set(challenger.blocker_codes) - set(champion.blocker_codes):
        return False
    if challenger.deliverable and not champion.deliverable:
        return challenger.score >= champion.score - score_regression_tolerance
    if champion.deliverable and not challenger.deliverable:
        return False
    blocker_reduction = len(champion.blocker_codes) - len(challenger.blocker_codes)
    score_improvement = challenger.score - champion.score
    if blocker_reduction > 0 and score_improvement >= -score_regression_tolerance:
        return True
    return score_improvement >= min_score_improvement


def _float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
