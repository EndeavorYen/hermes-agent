from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.judges.deterministic import judge_artifact
from agent.visual.judges.quality import judge_visual_quality


def backfill_feedback_judgments(
    db_path: str | Path,
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    ledger = VisualAttemptLedger(Path(db_path))
    if not Path(db_path).exists():
        return _report(db_path, [], created_count=0)

    backfillable = _backfillable_feedback_artifacts(ledger)
    if limit is not None:
        backfillable = backfillable[: max(0, int(limit))]
    created_count = 0
    if not dry_run:
        for artifact in backfillable:
            quality = _judge_artifact_quality(artifact)
            ledger.record_judgment(
                request_id=artifact.get("request_id") or "",
                attempt_id=artifact.get("attempt_id") or "",
                artifact_id=artifact.get("artifact_id") or artifact.get("id") or "",
                judge_name="visual_quality_judge",
                score=quality["confidence"],
                verdict="pass" if quality["confidence"] >= 0.5 else "review",
                details=quality,
                metadata={"source": "feedback_judgment_backfill"},
            )
            created_count += 1
    return _report(db_path, backfillable, created_count=created_count)


def _backfillable_feedback_artifacts(ledger: VisualAttemptLedger) -> list[dict[str, Any]]:
    feedback_artifact_ids = _feedback_artifact_ids(ledger)
    judged_artifact_ids = _judged_artifact_ids(ledger)
    backfillable: list[dict[str, Any]] = []
    for artifact_id in sorted(feedback_artifact_ids - judged_artifact_ids):
        try:
            artifact = ledger.get_artifact(artifact_id)
        except KeyError:
            continue
        if not artifact.get("attempt_id"):
            continue
        backfillable.append(artifact)
    return backfillable


def _feedback_artifact_ids(ledger: VisualAttemptLedger) -> set[str]:
    artifact_ids: set[str] = set()
    for row in ledger._list("visual_feedback"):
        polarity = _float(row.get("polarity"))
        artifact_id = str(row.get("artifact_id") or row.get("id") or "")
        if artifact_id and polarity != 0:
            artifact_ids.add(artifact_id)
    return artifact_ids


def _judged_artifact_ids(ledger: VisualAttemptLedger) -> set[str]:
    return {
        str(row.get("artifact_id") or "")
        for row in ledger._list("visual_judgments")
        if row.get("judge_name") == "visual_quality_judge" and row.get("artifact_id")
    }


def _judge_artifact_quality(artifact: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(artifact)
    duration_ms = normalized.get("duration_ms")
    if duration_ms is not None and normalized.get("duration_seconds") is None:
        normalized["duration_seconds"] = _float(duration_ms) / 1000.0
    expected_kind = str(normalized.get("kind") or "image")
    deterministic = judge_artifact(
        normalized,
        expected_kind=expected_kind,
        requested_parameters={},
    )
    candidate = {
        **normalized,
        "scores": deterministic["scores"],
        "hard_gate": deterministic["hard_gate"],
    }
    return judge_visual_quality(
        candidate,
        request_context={"has_reference_image": False},
        recent_artifact_hashes=set(),
    )


def _report(
    db_path: str | Path,
    backfillable: list[dict[str, Any]],
    *,
    created_count: int,
) -> dict[str, Any]:
    artifact_ids = [
        str(row.get("artifact_id") or row.get("id") or "")
        for row in backfillable
        if row.get("artifact_id") or row.get("id")
    ]
    return {
        "success": True,
        "db_path": str(db_path),
        "backfillable_count": len(artifact_ids),
        "created_count": created_count,
        "artifact_ids": artifact_ids,
    }


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
