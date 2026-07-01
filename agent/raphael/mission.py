from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re

from agent.raphael.models import MissionArtifact, RaphaelMission


GENERIC_ARTIFACT_REFERENCES = {
    "",
    "it",
    "this",
    "that",
    "current",
    "selected",
    "這個",
    "這張",
    "這張圖",
    "這份",
    "它",
}

_PUBLIC_TEXT_REDACTIONS = (
    (
        re.compile(r"data:[^\s,)]+;base64,[^\s,)]+", re.IGNORECASE),
        "[redacted-base64]",
    ),
    (re.compile(r"base64:[^\s,)]+", re.IGNORECASE), "[redacted-base64]"),
    (re.compile(r"candidate:[^\s,)]+", re.IGNORECASE), "[redacted-candidate]"),
    (
        re.compile(r"(?:file://)?/(?:private|Users|tmp|var)(?:/[^\s,)]+)*"),
        "[redacted-path]",
    ),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class FollowupResult:
    status: str
    mission: RaphaelMission
    selected_artifact: MissionArtifact | None = None
    clarification_question: str | None = None
    candidate_artifacts: tuple[MissionArtifact, ...] = ()


def create_mission(
    *,
    mission_id: str,
    goal: str,
    success_conditions: tuple[str, ...],
    phase: str,
    next_action: str,
    selected_strategy: str,
    required_proofs: tuple[str, ...],
    active_artifact: MissionArtifact | None = None,
    active_artifact_id: str | None = None,
    artifacts: tuple[MissionArtifact, ...] = (),
    blockers: tuple[str, ...] = (),
    last_evidence: tuple[str, ...] = (),
    last_user_request: str | None = None,
    now: datetime | None = None,
) -> RaphaelMission:
    """Create a mission record without selecting stale artifacts as active."""
    all_artifacts = _merge_artifacts(artifacts, active_artifact)
    resolved_active_id = active_artifact_id
    if active_artifact is not None:
        resolved_active_id = (
            None if active_artifact.stale else active_artifact.artifact_id
        )
    return RaphaelMission(
        mission_id=mission_id,
        goal=goal,
        active_artifact_id=resolved_active_id,
        artifacts=all_artifacts,
        success_conditions=success_conditions,
        phase=phase,
        blockers=blockers,
        next_action=next_action,
        selected_strategy=selected_strategy,
        required_proofs=required_proofs,
        last_evidence=last_evidence,
        updated_at=_ensure_utc(now) if now is not None else _utc_now(),
        last_user_request=last_user_request,
    )


def apply_followup(
    mission: RaphaelMission,
    *,
    user_message: str,
    artifact_reference: str | None = None,
    allow_multi_candidate: bool = False,
    max_candidates: int = 2,
    now: datetime | None = None,
) -> FollowupResult:
    """Attach a follow-up request to the existing mission when safe."""
    updated_at = _ensure_utc(now) if now is not None else _utc_now()
    resolution = _resolve_artifact(
        mission,
        artifact_reference,
        allow_multi_candidate=allow_multi_candidate,
        max_candidates=max_candidates,
    )
    if resolution.status == "resolved" and resolution.selected_artifact is not None:
        artifact = resolution.selected_artifact
        safe_label = sanitize_public_text(artifact.label)
        updated = replace(
            mission,
            active_artifact_id=artifact.artifact_id,
            phase="followup",
            blockers=(),
            next_action=f"Apply follow-up to {safe_label}.",
            last_user_request=user_message,
            updated_at=updated_at,
        )
        return FollowupResult(
            status="updated",
            mission=updated,
            selected_artifact=artifact,
        )

    if resolution.status == "multi_candidate_plan":
        candidates = resolution.candidate_artifacts
        updated = replace(
            mission,
            phase="clarification",
            blockers=(f"Ambiguous artifact reference: {_artifact_labels(candidates)}",),
            next_action=f"Validate {len(candidates)} candidate artifacts before editing.",
            last_user_request=user_message,
            updated_at=updated_at,
        )
        return FollowupResult(
            status="multi_candidate_plan",
            mission=updated,
            candidate_artifacts=candidates,
        )

    question = resolution.clarification_question or _clarification_question(
        mission.current_artifacts
    )
    updated = replace(
        mission,
        phase="clarification",
        blockers=(question,),
        next_action="Ask one precise artifact clarification.",
        last_user_request=user_message,
        updated_at=updated_at,
    )
    return FollowupResult(
        status="clarification_required",
        mission=updated,
        clarification_question=question,
    )


def render_mission_status_summary(mission: RaphaelMission | None) -> str:
    if mission is None:
        return "\n".join(["Raphael mission state", "Current mission: none"])

    artifact = mission.active_artifact
    artifact_label = (
        (
            f"{sanitize_public_text(artifact.label)} "
            f"({sanitize_public_text(artifact.artifact_id)})"
        )
        if artifact is not None
        else "none"
    )
    evidence_count = len(mission.last_evidence)
    evidence_label = (
        "1 recorded" if evidence_count == 1 else f"{evidence_count} recorded"
    )
    return "\n".join(
        [
            "Raphael mission state",
            f"Current mission: {sanitize_public_text(mission.mission_id)}",
            f"Goal: {sanitize_public_text(mission.goal)}",
            f"Phase: {sanitize_public_text(mission.phase)}",
            f"Active artifact: {artifact_label}",
            f"Success conditions: {len(mission.success_conditions)}",
            f"Blockers: {len(mission.blockers)}",
            f"Required proofs: {len(mission.required_proofs)}",
            f"Last evidence: {evidence_label}",
            f"Next mission action: {sanitize_public_text(mission.next_action)}",
        ]
    )


def apply_followup_to_active_mission(
    *,
    user_message: str,
    artifact_reference: str | None = None,
    allow_multi_candidate: bool = False,
    max_candidates: int = 2,
    now: datetime | None = None,
) -> FollowupResult:
    from agent.raphael.state import read_state, write_state

    state = read_state()
    if state.active_mission is None:
        raise ValueError("No active Raphael mission is available for follow-up.")
    result = apply_followup(
        state.active_mission,
        user_message=user_message,
        artifact_reference=artifact_reference,
        allow_multi_candidate=allow_multi_candidate,
        max_candidates=max_candidates,
        now=now,
    )
    write_state(
        replace(
            state,
            active_mission=result.mission,
            updated_at=result.mission.updated_at,
        )
    )
    return result


def sanitize_public_text(value: str) -> str:
    sanitized = str(value)
    for pattern, replacement in _PUBLIC_TEXT_REDACTIONS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def _resolve_artifact(
    mission: RaphaelMission,
    artifact_reference: str | None,
    *,
    allow_multi_candidate: bool,
    max_candidates: int,
) -> FollowupResult:
    reference = _normalize(artifact_reference or "")
    current_artifacts = mission.current_artifacts
    stale_matches = tuple(
        artifact
        for artifact in mission.artifacts
        if artifact.stale and _artifact_matches(artifact, reference)
    )

    if reference in GENERIC_ARTIFACT_REFERENCES:
        if mission.active_artifact is not None:
            return FollowupResult(
                status="resolved",
                mission=mission,
                selected_artifact=mission.active_artifact,
            )
        if len(current_artifacts) == 1:
            return FollowupResult(
                status="resolved",
                mission=mission,
                selected_artifact=current_artifacts[0],
            )
        return _ambiguous_result(
            mission,
            current_artifacts,
            allow_multi_candidate=allow_multi_candidate,
            max_candidates=max_candidates,
        )

    matches = tuple(
        artifact
        for artifact in current_artifacts
        if _artifact_matches(artifact, reference)
    )
    if len(matches) == 1:
        return FollowupResult(
            status="resolved",
            mission=mission,
            selected_artifact=matches[0],
        )
    if len(matches) > 1:
        return _ambiguous_result(
            mission,
            matches,
            allow_multi_candidate=allow_multi_candidate,
            max_candidates=max_candidates,
        )
    if stale_matches:
        return FollowupResult(
            status="clarification_required",
            mission=mission,
            clarification_question=_stale_artifact_question(
                stale_matches, current_artifacts
            ),
        )
    return FollowupResult(
        status="clarification_required",
        mission=mission,
        clarification_question=_clarification_question(current_artifacts),
    )


def _ambiguous_result(
    mission: RaphaelMission,
    artifacts: tuple[MissionArtifact, ...],
    *,
    allow_multi_candidate: bool,
    max_candidates: int,
) -> FollowupResult:
    bounded = artifacts[: max(1, max_candidates)]
    if allow_multi_candidate:
        return FollowupResult(
            status="multi_candidate_plan",
            mission=mission,
            candidate_artifacts=bounded,
        )
    return FollowupResult(
        status="clarification_required",
        mission=mission,
        clarification_question=_clarification_question(bounded),
    )


def _merge_artifacts(
    artifacts: tuple[MissionArtifact, ...],
    active_artifact: MissionArtifact | None,
) -> tuple[MissionArtifact, ...]:
    if active_artifact is None:
        return tuple(artifacts)
    by_id = {artifact.artifact_id: artifact for artifact in artifacts}
    by_id[active_artifact.artifact_id] = active_artifact
    return tuple(by_id.values())


def _artifact_matches(artifact: MissionArtifact, reference: str) -> bool:
    if not reference:
        return False
    return (
        reference in _normalize(artifact.artifact_id)
        or reference in _normalize(artifact.label)
        or _normalize(artifact.artifact_id) in reference
        or _normalize(artifact.label) in reference
    )


def _clarification_question(artifacts: tuple[MissionArtifact, ...]) -> str:
    if not artifacts:
        return "Which current artifact should Raphael update?"
    return f"Which artifact should Raphael update: {_artifact_labels(artifacts)}?"


def _stale_artifact_question(
    stale_matches: tuple[MissionArtifact, ...],
    current_artifacts: tuple[MissionArtifact, ...],
) -> str:
    stale_labels = _artifact_labels(stale_matches)
    if not current_artifacts:
        return (
            f"The referenced artifact is stale ({stale_labels}). "
            "Which current artifact should Raphael update?"
        )
    return (
        f"The referenced artifact is stale ({stale_labels}). "
        f"Which current artifact should Raphael update: {_artifact_labels(current_artifacts)}?"
    )


def _artifact_labels(artifacts: tuple[MissionArtifact, ...]) -> str:
    labels = tuple(sanitize_public_text(artifact.label) for artifact in artifacts)
    if len(labels) <= 1:
        return labels[0] if labels else "none"
    return f"{', '.join(labels[:-1])} or {labels[-1]}"


def _normalize(value: str) -> str:
    return " ".join(value.casefold().strip().split())


__all__ = [
    "FollowupResult",
    "apply_followup",
    "apply_followup_to_active_mission",
    "create_mission",
    "render_mission_status_summary",
    "sanitize_public_text",
]
