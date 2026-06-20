#!/usr/bin/env python3
"""Summarize Visual Agent Mode evidence without exposing raw prompts."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

from agent.visual.tracking import default_visual_ledger_path
from scripts.visual_agent_live_proof import _resolve_since


def build_visual_agent_report(
    ledger_path: str | Path,
    *,
    since: Optional[str] = None,
    strategy_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(ledger_path).expanduser()
    strategy = (
        Path(strategy_path).expanduser()
        if strategy_path is not None
        else path.with_name("strategy_atoms.sqlite3")
    )
    report: dict[str, Any] = {
        "ledger_path": str(path),
        "since": since,
        "requests": {"total": 0, "status": {}},
        "attempts": {"total": 0},
        "artifacts": {},
        "delivery": {"duplicate_artifact_delivery": 0},
        "provider_errors": {},
        "source_metadata": {
            "requests": 0,
            "missing_request_source_metadata": 0,
        },
        "strategy_atoms": [],
    }
    if not path.exists():
        report["missing"] = ["ledger_missing"]
        return report

    with _connect(path) as conn:
        report["requests"] = {
            "total": _count_rows(conn, "visual_requests", "created_at", since),
            "status": _group_counts(
                conn,
                "visual_requests",
                "status",
                since_column="created_at",
                since=since,
            ),
        }
        report["attempts"] = {
            "total": _count_rows(conn, "visual_attempts", "created_at", since),
        }
        report["artifacts"] = _group_counts(
            conn,
            "visual_artifacts",
            "kind",
            since_column="created_at",
            since=since,
        )
        report["delivery"] = {
            **_group_counts(
                conn,
                "visual_deliveries",
                "delivery_status",
                since_column="delivered_at",
                since=since,
            ),
            "duplicate_artifact_delivery": _duplicate_delivery_count(conn, since),
        }
        report["provider_errors"] = _group_counts(
            conn,
            "visual_attempts",
            "provider_error_type",
            since_column="created_at",
            since=since,
            where_not_null=True,
        )
        report["source_metadata"] = {
            "requests": report["requests"]["total"],
            "missing_request_source_metadata": _missing_source_count(conn, since),
        }
    report["strategy_atoms"] = _strategy_atoms(strategy)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize Visual Agent Mode evidence without raw prompts."
    )
    parser.add_argument(
        "--ledger-path",
        default=None,
        help="Path to visual attempt ledger. Defaults to Hermes visual_tracking config.",
    )
    parser.add_argument("--strategy-path", default=None)
    parser.add_argument("--since", default=None)
    parser.add_argument("--since-local-date", default=None)
    parser.add_argument("--timezone", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        since = _resolve_since(
            since=args.since,
            since_local_date=args.since_local_date,
            timezone_name=args.timezone,
        )
    except ValueError as exc:
        parser.error(str(exc))
    ledger_path = (
        Path(args.ledger_path).expanduser()
        if args.ledger_path
        else default_visual_ledger_path()
    )
    payload = build_visual_agent_report(
        ledger_path,
        since=since,
        strategy_path=args.strategy_path,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _count_rows(
    conn: sqlite3.Connection,
    table: str,
    since_column: str,
    since: Optional[str],
) -> int:
    query = f"SELECT COUNT(*) AS count FROM {table}"
    params: list[Any] = []
    if since:
        query += f" WHERE {since_column} >= ?"
        params.append(since)
    row = conn.execute(query, tuple(params)).fetchone()
    return int(row["count"]) if row is not None else 0


def _group_counts(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    *,
    since_column: str,
    since: Optional[str],
    where_not_null: bool = False,
) -> dict[str, int]:
    query = f"SELECT {column} AS key, COUNT(*) AS count FROM {table}"
    clauses: list[str] = []
    params: list[Any] = []
    if since:
        clauses.append(f"{since_column} >= ?")
        params.append(since)
    if where_not_null:
        clauses.append(f"{column} IS NOT NULL AND {column} != ''")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += f" GROUP BY {column} ORDER BY {column}"
    rows = conn.execute(query, tuple(params)).fetchall()
    return {
        str(row["key"]): int(row["count"])
        for row in rows
        if row["key"] is not None and str(row["key"]).strip()
    }


def _missing_source_count(conn: sqlite3.Connection, since: Optional[str]) -> int:
    clauses = [
        "(platform IS NULL OR platform = '')",
        "(channel_id IS NULL OR channel_id = '')",
        "(user_id IS NULL OR user_id = '')",
        "(message_id IS NULL OR message_id = '')",
        "(conversation_id IS NULL OR conversation_id = '')",
    ]
    query = (
        "SELECT COUNT(*) AS count FROM visual_requests WHERE ("
        + " OR ".join(clauses)
        + ")"
    )
    params: list[Any] = []
    if since:
        query += " AND created_at >= ?"
        params.append(since)
    row = conn.execute(query, tuple(params)).fetchone()
    return int(row["count"]) if row is not None else 0


def _duplicate_delivery_count(
    conn: sqlite3.Connection,
    since: Optional[str],
) -> int:
    query = """
        SELECT COUNT(*) AS count
          FROM (
            SELECT artifact_id
              FROM visual_deliveries
             WHERE delivery_status = 'sent'
    """
    params: list[Any] = []
    if since:
        query += " AND delivered_at >= ?"
        params.append(since)
    query += """
             GROUP BY artifact_id
            HAVING COUNT(*) > 1
          )
    """
    row = conn.execute(query, tuple(params)).fetchone()
    return int(row["count"]) if row is not None else 0


def _strategy_atoms(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT bucket, strategy_id, score, count, updated_at, evidence_json
              FROM strategy_atoms
             ORDER BY score DESC, count DESC, bucket ASC, strategy_id ASC
             LIMIT 10
            """
        ).fetchall()
    atoms: list[dict[str, Any]] = []
    for row in rows:
        try:
            evidence = json.loads(row["evidence_json"] or "{}")
        except json.JSONDecodeError:
            evidence = {}
        atoms.append(
            {
                "bucket": row["bucket"],
                "strategy_id": row["strategy_id"],
                "score": float(row["score"]),
                "count": int(row["count"]),
                "updated_at": row["updated_at"],
                "evidence": evidence if isinstance(evidence, dict) else {},
            }
        )
    return atoms


if __name__ == "__main__":
    sys.exit(main())
