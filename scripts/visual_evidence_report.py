from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.provider_stats import top_provider_reliability
from agent.visual.tracking import default_visual_ledger_path


def build_visual_evidence_report(db_path: str | Path, *, request_id: str | None = None) -> dict[str, Any]:
    db_path = Path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        request_count = _count(conn, "visual_requests", request_id=request_id)
        attempt_count = _count(conn, "visual_attempts", request_id=request_id)
        artifact_count = _count(conn, "visual_artifacts", request_id=request_id)
        judgment_count = _count(conn, "visual_judgments", request_id=request_id)
        delivery_count = _count(conn, "visual_deliveries", request_id=request_id)
        feedback_count = _count(conn, "visual_feedback", request_id=request_id)
        duplicate_count = _duplicate_sent_delivery_count(conn, request_id=request_id)
        missing_metadata_count = _missing_source_metadata_count(conn, request_id=request_id)
    provider_reliability = top_provider_reliability(
        VisualAttemptLedger(db_path),
        request_id=request_id,
    )

    proof = {
        "duplicate_artifact_delivery_count": duplicate_count,
        "missing_source_metadata_count": missing_metadata_count,
    }
    return {
        "success": duplicate_count == 0 and missing_metadata_count == 0,
        "requests": {"count": request_count},
        "attempts": {"count": attempt_count},
        "artifacts": {"count": artifact_count},
        "judgments": {"count": judgment_count},
        "deliveries": {"count": delivery_count},
        "feedback": {"count": feedback_count},
        "proof": proof,
        "provider_reliability": {"top": provider_reliability},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a privacy-safe visual evidence report.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--request-id", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_evidence_report(args.db_path, request_id=args.request_id)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual evidence report {status}")
    return 0 if payload["success"] else 1


def _count(conn: sqlite3.Connection, table: str, *, request_id: str | None = None) -> int:
    if not _table_exists(conn, table):
        return 0
    where, params = _request_where(conn, table, request_id=request_id)
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}{where}", params).fetchone()
    return int(row["count"])


def _duplicate_sent_delivery_count(conn: sqlite3.Connection, *, request_id: str | None = None) -> int:
    artifact_id_column = _first_existing_column(conn, "visual_artifacts", ("id", "artifact_id"))
    artifact_identity_expr = _artifact_identity_expr(conn)
    destination_expr = _delivery_destination_expr(conn)
    request_filter = ""
    params: tuple[str, ...] = ()
    if request_id is not None:
        request_filter = " AND d.request_id = ?"
        params = (request_id,)
    rows = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM visual_deliveries d
        JOIN visual_artifacts a ON a.{artifact_id_column} = d.artifact_id
        WHERE d.delivery_status = 'sent'
          AND {artifact_identity_expr} IS NOT NULL
          {request_filter}
        GROUP BY d.request_id, {destination_expr}, {artifact_identity_expr}
        HAVING COUNT(*) > 1
        """,
        params,
    ).fetchall()
    return sum(int(row["count"]) - 1 for row in rows)


def _missing_source_metadata_count(conn: sqlite3.Connection, *, request_id: str | None = None) -> int:
    columns = _column_names(conn, "visual_artifacts")
    source_columns = [column for column in ("local_path", "uri", "source_url") if column in columns]
    missing_source = " AND ".join(f"{column} IS NULL" for column in source_columns)
    if not missing_source:
        missing_source = "1 = 1"
    request_filter = ""
    params: tuple[str, ...] = ()
    if request_id is not None:
        request_filter = " AND request_id = ?"
        params = (request_id,)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM visual_artifacts
        WHERE (
              freshness_status IS NULL
           OR kind IS NULL
           OR ({missing_source})
        )
           {request_filter}
        """,
        params,
    ).fetchone()
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
    column = "request_id" if "request_id" in columns else _first_existing_column(conn, table, ("id", "request_id"))
    return f" WHERE {column} = ?", (request_id,)


def _delivery_destination_expr(conn: sqlite3.Connection) -> str:
    columns = _column_names(conn, "visual_deliveries")
    fallback = "d.platform || ':' || d.destination_id || ':' || COALESCE(d.thread_id, '')"
    if "destination" in columns:
        return f"COALESCE(d.destination, {fallback})"
    return fallback


def _artifact_identity_expr(conn: sqlite3.Connection) -> str:
    columns = _column_names(conn, "visual_artifacts")
    candidates = [
        f"a.{column}"
        for column in ("content_hash", "source_url", "uri", "local_path")
        if column in columns
    ]
    return "COALESCE(" + ", ".join(candidates) + ")" if candidates else "NULL"


def _first_existing_column(conn: sqlite3.Connection, table: str, candidates: tuple[str, ...]) -> str:
    columns = _column_names(conn, table)
    for candidate in candidates:
        if candidate in columns:
            return candidate
    raise sqlite3.OperationalError(f"{table} is missing expected columns: {', '.join(candidates)}")


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


if __name__ == "__main__":
    raise SystemExit(main())
