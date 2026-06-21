from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agent.visual.tracking import default_visual_ledger_path
from scripts.visual_evidence_report import build_visual_evidence_report


_REQUIRED_TABLES = {
    "visual_requests",
    "visual_attempts",
    "visual_artifacts",
    "visual_rankings",
    "visual_deliveries",
    "visual_feedback",
    "visual_shadow_updates",
}


def run_visual_self_validation(
    db_path: str | Path | None = None,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    db_path = Path(db_path) if db_path is not None else default_visual_ledger_path()
    failures: list[str] = []
    if not db_path.exists():
        return _result(db_path, request_id=request_id, failures=["missing_ledger"])

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        missing_tables = sorted(_REQUIRED_TABLES - _table_names(conn))
        failures.extend(f"missing_table:{table}" for table in missing_tables)
        if missing_tables:
            return _result(db_path, request_id=request_id, failures=failures)

        report = build_visual_evidence_report(db_path, request_id=request_id)
        if report["proof"]["duplicate_artifact_delivery_count"]:
            failures.append("duplicate_delivery")
        if report["proof"]["missing_source_metadata_count"]:
            failures.append("missing_source_metadata")

        artifact_count = _count(conn, "visual_artifacts", request_id=request_id)
        if artifact_count > 0 and not _has_reward_trace(conn, request_id=request_id):
            failures.append("missing_reward_trace")

        if _package_request_count(conn, request_id=request_id) > 0 and not _has_active_learning_trace(
            conn,
            request_id=request_id,
        ):
            failures.append("missing_active_learning_decision")

        if _active_shadow_update_count(conn, request_id=request_id) > 0:
            failures.append("active_shadow_update")

    return _result(db_path, request_id=request_id, failures=failures)


def _result(
    db_path: Path,
    *,
    request_id: str | None,
    failures: list[str],
) -> dict[str, Any]:
    return {
        "success": not failures,
        "db_path": str(db_path),
        "request_id": request_id,
        "failures": failures,
    }


def _has_reward_trace(conn: sqlite3.Connection, *, request_id: str | None) -> bool:
    rows = _ranking_rows(conn, request_id=request_id)
    for row in rows:
        scores = _json_value(_row_value(row, "scores", "score_json"))
        if _contains_reward(scores):
            return True
    return False


def _has_active_learning_trace(conn: sqlite3.Connection, *, request_id: str | None) -> bool:
    rows = _ranking_rows(conn, request_id=request_id)
    for row in rows:
        metadata = _json_value(_row_value(row, "metadata", "rationale_json"))
        if isinstance(metadata, dict) and "active_learning" in metadata:
            return True
    return False


def _contains_reward(value: Any) -> bool:
    if isinstance(value, dict):
        if "reward" in value and _contains_reward(value["reward"]):
            return True
        return "final_score" in value and "confidence" in value
    return False


def _ranking_rows(conn: sqlite3.Connection, *, request_id: str | None) -> list[sqlite3.Row]:
    where, params = _request_where(conn, "visual_rankings", request_id=request_id)
    return conn.execute(f"SELECT * FROM visual_rankings{where}", params).fetchall()


def _package_request_count(conn: sqlite3.Connection, *, request_id: str | None) -> int:
    where, params = _request_where(conn, "visual_requests", request_id=request_id)
    operation_column = "operation" if "operation" in _column_names(conn, "visual_requests") else None
    if operation_column is None:
        return 0
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM visual_requests
        {where}
        {"AND" if where else "WHERE"} operation = 'visual_package_generate'
        """,
        params,
    ).fetchone()
    return int(row["count"])


def _active_shadow_update_count(conn: sqlite3.Connection, *, request_id: str | None) -> int:
    where, params = _request_where(conn, "visual_shadow_updates", request_id=request_id)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM visual_shadow_updates
        {where}
        {"AND" if where else "WHERE"} activation_status = 'active'
        """,
        params,
    ).fetchone()
    return int(row["count"])


def _count(conn: sqlite3.Connection, table: str, *, request_id: str | None) -> int:
    where, params = _request_where(conn, table, request_id=request_id)
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}{where}", params).fetchone()
    return int(row["count"])


def _request_where(
    conn: sqlite3.Connection,
    table: str,
    *,
    request_id: str | None,
) -> tuple[str, tuple[str, ...]]:
    if request_id is None:
        return "", ()
    columns = _column_names(conn, table)
    column = "request_id" if "request_id" in columns else "id"
    return f" WHERE {column} = ?", (request_id,)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value


def _row_value(row: sqlite3.Row, *columns: str) -> Any:
    row_columns = set(row.keys())
    for column in columns:
        if column in row_columns:
            return row[column]
    return None


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
