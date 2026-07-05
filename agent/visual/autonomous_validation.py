from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.tracking import default_visual_ledger_path


def validate_visual_generation_payload(
    payload: dict[str, Any],
    *,
    db_path: str | Path | None = None,
    require_video: bool = True,
) -> dict[str, Any]:
    db_path = Path(db_path) if db_path is not None else default_visual_ledger_path()
    evidence = inspect_visual_generation_evidence(payload, db_path=db_path, require_video=require_video)
    failures = _failures(payload, evidence, require_video=require_video)
    return {
        "success": not failures,
        "decision": _decision(failures),
        "failures": failures,
        "evidence": evidence,
    }


def inspect_visual_generation_evidence(
    payload: dict[str, Any],
    *,
    db_path: str | Path | None = None,
    require_video: bool,
) -> dict[str, Any]:
    request_id = str(payload.get("visual_request_id") or "")
    evidence: dict[str, Any] = {
        "request_id": request_id,
        "image_count": len(payload.get("images") or []),
        "video_count": len(payload.get("videos") or []),
        "attempt_count": 0,
        "artifact_count": 0,
        "judgment_count": 0,
        "ranking_count": 0,
        "shadow_update_count": 0,
        "learning_trace_count": 0,
        "judgments_with_learning_metadata": 0,
        "require_video": require_video,
    }
    if not request_id:
        return evidence
    db_path = Path(db_path) if db_path is not None else default_visual_ledger_path()
    if not db_path.exists():
        evidence["ledger_missing"] = True
        return evidence

    ledger = VisualAttemptLedger(db_path)
    attempts = _rows_for_request(ledger, "visual_attempts", request_id)
    artifacts = _rows_for_request(ledger, "visual_artifacts", request_id)
    judgments = _judgment_rows_for_request(ledger, attempts=attempts, artifacts=artifacts)
    rankings = _rows_for_request(ledger, "visual_rankings", request_id)
    shadow_updates = _rows_for_request(ledger, "visual_shadow_updates", request_id)
    evidence.update(
        {
            "attempt_count": len(attempts),
            "artifact_count": len(artifacts),
            "judgment_count": len(judgments),
            "ranking_count": len(rankings),
            "shadow_update_count": len(shadow_updates),
            "learning_trace_count": sum(1 for row in rankings if _has_active_learning(row)),
            "judgments_with_learning_metadata": sum(1 for row in judgments if _has_judgment_metadata(row)),
        }
    )
    return evidence


def _failures(
    payload: dict[str, Any],
    evidence: dict[str, Any],
    *,
    require_video: bool,
) -> list[str]:
    failures: list[str] = []
    if payload.get("success") is not True:
        failures.append(str(payload.get("error_type") or "provider_generation_failed"))
    if evidence.get("image_count", 0) < 1:
        failures.append("missing_image_output")
    if require_video and evidence.get("video_count", 0) < 1:
        failures.append("missing_video_output")
    expected = 2 if require_video else 1
    if evidence.get("ledger_missing") is True:
        failures.append("missing_ledger")
    elif evidence.get("artifact_count", 0) > 0:
        if evidence.get("judgment_count", 0) < expected:
            failures.append("missing_quality_judgments")
        if evidence.get("ranking_count", 0) < expected:
            failures.append("missing_rankings")
        if evidence.get("learning_trace_count", 0) < expected:
            failures.append("missing_learning_trace")
        if evidence.get("judgments_with_learning_metadata", 0) < expected:
            failures.append("missing_judgment_learning_metadata")
    return sorted(set(failures))


def _decision(failures: list[str]) -> str:
    if not failures:
        return "accept"
    if any(item in failures for item in ("missing_image_output", "missing_video_output", "provider_generation_failed")):
        return "retry_generation"
    if any(item.startswith("provider_unavailable") for item in failures):
        return "provider_blocked"
    if any("judgment" in item or "learning" in item or "ranking" in item for item in failures):
        return "retry_or_rejudge"
    return "ask_user"


def _rows_for_request(
    ledger: VisualAttemptLedger,
    table: str,
    request_id: str,
) -> list[dict[str, Any]]:
    try:
        return ledger._list(table, where="request_id = ?", params=(request_id,))
    except Exception:
        return []


def _judgment_rows_for_request(
    ledger: VisualAttemptLedger,
    *,
    attempts: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    artifact_ids = _id_values(artifacts, "artifact_id", "id")
    attempt_ids = _id_values(attempts, "attempt_id", "id") | _id_values(artifacts, "attempt_id")
    rows: list[dict[str, Any]] = []
    for artifact_id in sorted(artifact_ids):
        rows.extend(_rows_for_column(ledger, "visual_judgments", "artifact_id", artifact_id))
    for attempt_id in sorted(attempt_ids):
        rows.extend(_rows_for_column(ledger, "visual_judgments", "attempt_id", attempt_id))
    return _dedupe(rows, "judgment_id", "id")


def _rows_for_column(
    ledger: VisualAttemptLedger,
    table: str,
    column: str,
    value: str,
) -> list[dict[str, Any]]:
    try:
        return ledger._list(table, where=f"{column} = ?", params=(value,))
    except Exception:
        return []


def _id_values(rows: list[dict[str, Any]], *keys: str) -> set[str]:
    values: set[str] = set()
    for row in rows:
        for key in keys:
            value = row.get(key)
            if isinstance(value, str) and value:
                values.add(value)
    return values


def _dedupe(rows: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        row_id = next((str(row.get(key)) for key in keys if row.get(key)), f"row:{index}")
        if row_id in seen:
            continue
        seen.add(row_id)
        result.append(row)
    return result


def _has_active_learning(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    rationale = row.get("rationale_json") if isinstance(row.get("rationale_json"), dict) else {}
    return isinstance(metadata.get("active_learning"), dict) or isinstance(rationale.get("active_learning"), dict)


def _has_judgment_metadata(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    if all(metadata.get(key) for key in ("intent_signature", "strategy_signature", "modality")):
        return True
    return row.get("judge_name") == "visual_quality_judge" and bool(
        row.get("details") or row.get("score_json") or row.get("confidence")
    )
