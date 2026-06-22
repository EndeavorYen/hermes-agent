from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

MIN_MATCHED_FEEDBACK_FOR_FAILURE = 5
MAX_JUDGE_HUMAN_DISAGREEMENT_RATE = 0.5


def build_quality_calibration_report(db_path: str | Path) -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return _empty_report(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "visual_judgments"):
            return _empty_report(db_path)
        judgments = _judgment_rows(conn)
        feedback_by_artifact = _feedback_by_artifact(conn)

    confidence_values = [_float(_row_value(row, "score", "confidence")) for row in judgments]
    uncertainty_reasons = _uncertainty_reasons(judgments)
    agreement = 0
    disagreement = 0
    for row in judgments:
        artifact_id = str(_row_value(row, "artifact_id") or "")
        if not artifact_id or artifact_id not in feedback_by_artifact:
            continue
        judge_positive = _float(_row_value(row, "score", "confidence")) >= 0.5
        human_positive = feedback_by_artifact[artifact_id] > 0
        if judge_positive == human_positive:
            agreement += 1
        else:
            disagreement += 1

    judged_artifact_ids = {
        str(_row_value(row, "artifact_id") or "")
        for row in judgments
        if str(_row_value(row, "artifact_id") or "")
    }
    human_polarities = list(feedback_by_artifact.values())
    unmatched_human_feedback_count = sum(
        1
        for artifact_id, polarity in feedback_by_artifact.items()
        if artifact_id not in judged_artifact_ids and polarity != 0
    )
    matched_feedback_count = agreement + disagreement
    disagreement_rate = (
        round(disagreement / matched_feedback_count, 4)
        if matched_feedback_count
        else 0.0
    )
    failures = []
    if (
        matched_feedback_count >= MIN_MATCHED_FEEDBACK_FOR_FAILURE
        and disagreement_rate > MAX_JUDGE_HUMAN_DISAGREEMENT_RATE
    ):
        failures.append("judge_human_disagreement_rate_high")
    if (
        matched_feedback_count == 0
        and unmatched_human_feedback_count >= MIN_MATCHED_FEEDBACK_FOR_FAILURE
    ):
        failures.append("human_feedback_unmatched_to_judgments")
    return {
        "success": not failures,
        "db_path": str(db_path),
        "failures": failures,
        "matched_feedback_count": matched_feedback_count,
        "unmatched_human_feedback_count": unmatched_human_feedback_count,
        "judge_human_disagreement_rate": disagreement_rate,
        "thresholds": {
            "min_matched_feedback_for_failure": MIN_MATCHED_FEEDBACK_FOR_FAILURE,
            "max_judge_human_disagreement_rate": MAX_JUDGE_HUMAN_DISAGREEMENT_RATE,
        },
        "counts": {
            "judged_artifacts": len(judgments),
            "low_confidence": sum(1 for value in confidence_values if value < 0.5),
            "human_positive": sum(1 for value in human_polarities if value > 0),
            "human_negative": sum(1 for value in human_polarities if value < 0),
            "judge_human_agreement": agreement,
            "judge_human_disagreement": disagreement,
        },
        "average_judge_confidence": round(
            sum(confidence_values) / len(confidence_values),
            4,
        ) if confidence_values else 0.0,
        "top_uncertainty_reasons": [
            {"reason": reason, "count": count}
            for reason, count in uncertainty_reasons.most_common(10)
        ],
    }


def _empty_report(db_path: Path) -> dict[str, Any]:
    return {
        "success": True,
        "db_path": str(db_path),
        "failures": [],
        "matched_feedback_count": 0,
        "unmatched_human_feedback_count": 0,
        "judge_human_disagreement_rate": 0.0,
        "thresholds": {
            "min_matched_feedback_for_failure": MIN_MATCHED_FEEDBACK_FOR_FAILURE,
            "max_judge_human_disagreement_rate": MAX_JUDGE_HUMAN_DISAGREEMENT_RATE,
        },
        "counts": {
            "judged_artifacts": 0,
            "low_confidence": 0,
            "human_positive": 0,
            "human_negative": 0,
            "judge_human_agreement": 0,
            "judge_human_disagreement": 0,
        },
        "average_judge_confidence": 0.0,
        "top_uncertainty_reasons": [],
    }


def _judgment_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM visual_judgments ORDER BY created_at, rowid").fetchall()


def _feedback_by_artifact(conn: sqlite3.Connection) -> dict[str, float]:
    if not _table_exists(conn, "visual_feedback"):
        return {}
    rows = conn.execute("SELECT * FROM visual_feedback ORDER BY created_at, rowid").fetchall()
    values: dict[str, list[float]] = {}
    for row in rows:
        artifact_id = str(_row_value(row, "artifact_id") or "")
        if not artifact_id:
            continue
        values.setdefault(artifact_id, []).append(_float(_row_value(row, "polarity")))
    return {
        artifact_id: sum(polarities) / len(polarities)
        for artifact_id, polarities in values.items()
        if polarities
    }


def _uncertainty_reasons(rows: list[sqlite3.Row]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        details = _json_value(_row_value(row, "details", "score_json"))
        reasons = details.get("uncertainty_reasons") if isinstance(details, dict) else None
        if not isinstance(reasons, list):
            continue
        for reason in sorted({str(item) for item in reasons if isinstance(item, str) and item.strip()}):
            counter[reason] += 1
    return counter


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value


def _row_value(row: sqlite3.Row, *keys: str) -> Any:
    available = set(row.keys())
    for key in keys:
        if key in available:
            return row[key]
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
