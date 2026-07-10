from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


def build_visual_selection_report(
    db_path: str | Path,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return _empty_report(db_path, request_id=request_id)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "visual_requests"):
            return _empty_report(db_path, request_id=request_id)
        effective_request_id = request_id or _latest_request_id(conn)
        if not effective_request_id:
            return _empty_report(db_path, request_id=None)
        artifacts = _rows(conn, "visual_artifacts", effective_request_id)
        attempts = _rows(conn, "visual_attempts", effective_request_id)
        rankings = _rows(conn, "visual_rankings", effective_request_id)

    selected_artifact_ids = [
        str(_row_value(row, "selected_artifact_id"))
        for row in rankings
        if _row_value(row, "selected_artifact_id")
    ]
    failure_classes = Counter(
        failure_class
        for row in attempts
        if (failure_class := _attempt_failure_class(row))
    )
    return {
        "success": True,
        "db_path": str(db_path),
        "request_id": effective_request_id,
        "counts": {
            "generated_candidates": len(artifacts),
            "selected_artifacts": len(selected_artifact_ids),
            "suppressed_stale": _suppressed_stale_count(artifacts),
            "suppressed_duplicate": _suppressed_duplicate_count(artifacts),
            "retry_count": sum(1 for row in attempts if _attempt_retry_of(row) is not None),
        },
        "selected_artifact_ids": selected_artifact_ids,
        "failure_classes": dict(sorted(failure_classes.items())),
        "rank_reasons": [
            str(_row_value(row, "decision"))
            for row in rankings
            if _row_value(row, "decision")
        ],
    }


def _empty_report(db_path: Path, *, request_id: str | None) -> dict[str, Any]:
    return {
        "success": True,
        "db_path": str(db_path),
        "request_id": request_id,
        "counts": {
            "generated_candidates": 0,
            "selected_artifacts": 0,
            "suppressed_stale": 0,
            "suppressed_duplicate": 0,
            "retry_count": 0,
        },
        "selected_artifact_ids": [],
        "failure_classes": {},
        "rank_reasons": [],
    }


def _latest_request_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT * FROM visual_requests ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return str(_row_value(row, "id", "request_id"))


def _rows(conn: sqlite3.Connection, table: str, request_id: str) -> list[sqlite3.Row]:
    if not _table_exists(conn, table):
        return []
    return conn.execute(
        f"SELECT * FROM {table} WHERE request_id = ? ORDER BY created_at, rowid",
        (request_id,),
    ).fetchall()


def _attempt_failure_class(row: sqlite3.Row) -> str | None:
    metadata = _json_value(_row_value(row, "metadata", "metadata_json"))
    if not isinstance(metadata, dict):
        return None
    failure = metadata.get("failure")
    if not isinstance(failure, dict):
        return None
    value = failure.get("failure_class")
    return str(value) if value else None


def _attempt_retry_of(row: sqlite3.Row) -> Any:
    metadata = _json_value(_row_value(row, "metadata", "metadata_json"))
    if not isinstance(metadata, dict):
        return None
    return metadata.get("retry_of")


def _suppressed_stale_count(rows: list[sqlite3.Row]) -> int:
    count = 0
    for row in rows:
        freshness = _row_value(row, "freshness_status")
        is_stable = _row_value(row, "is_stable")
        if freshness not in {None, "fresh"} or is_stable in {0, False}:
            count += 1
    return count


def _suppressed_duplicate_count(rows: list[sqlite3.Row]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for row in rows:
        identity = _artifact_identity(row)
        if not identity:
            continue
        if identity in seen:
            duplicates += 1
        else:
            seen.add(identity)
    return duplicates


def _artifact_identity(row: sqlite3.Row) -> str | None:
    for key in ("content_hash", "source_url", "uri", "local_path"):
        value = _row_value(row, key)
        if value:
            return str(value)
    return None


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
