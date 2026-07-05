from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.tracking import default_visual_ledger_path


def build_shadow_learning_report(
    db_path: str | Path,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return _empty_report()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "visual_shadow_updates"):
            return _empty_report()
        rows = _shadow_rows(conn, request_id=request_id)

    top = [_row_to_report(row) for row in rows[:10]]
    active_count = sum(1 for row in rows if str(_row_value(row, "activation_status") or "") == "active")
    return {
        "success": active_count == 0,
        "shadow_updates": {
            "count": len(rows),
            "active_count": active_count,
            "top": top,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a privacy-safe visual shadow learning report.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--request-id", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = build_shadow_learning_report(args.db_path, request_id=args.request_id)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual shadow learning report {status}")
    return 0 if payload["success"] else 1


def _shadow_rows(
    conn: sqlite3.Connection,
    *,
    request_id: str | None,
) -> list[sqlite3.Row]:
    request_filter = ""
    params: tuple[str, ...] = ()
    if request_id is not None:
        request_filter = " WHERE request_id = ?"
        params = (request_id,)
    return conn.execute(
        f"""
        SELECT *
        FROM visual_shadow_updates
        {request_filter}
        ORDER BY confidence DESC, created_at DESC, rowid DESC
        """,
        params,
    ).fetchall()


def _row_to_report(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "intent_signature": _row_value(row, "intent_signature"),
        "strategy_signature": _row_value(row, "strategy_signature"),
        "proposed_change": _json_value(_row_value(row, "proposed_change", "proposed_change_json")),
        "evidence": _json_value(_row_value(row, "evidence", "evidence_json")),
        "confidence": _row_value(row, "confidence"),
        "activation_status": _row_value(row, "activation_status"),
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, (dict, list)) else {}


def _row_value(row: sqlite3.Row, *columns: str) -> Any:
    row_columns = set(row.keys())
    for column in columns:
        if column in row_columns:
            return row[column]
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _empty_report() -> dict[str, Any]:
    return {
        "success": True,
        "shadow_updates": {
            "count": 0,
            "active_count": 0,
            "top": [],
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
