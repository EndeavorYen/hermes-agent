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


def build_strategy_activation_report(
    db_path: str | Path,
    *,
    intent_signature: str | None = None,
    strategy_signature: str | None = None,
) -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return _empty_report()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "visual_strategy_activations"):
            return _empty_report()
        rows = _activation_rows(
            conn,
            intent_signature=intent_signature,
            strategy_signature=strategy_signature,
        )
        reads = _activation_read_counts(conn)

    top = [_row_to_report(row, reads=reads) for row in rows[:10]]
    unsafe_count = sum(1 for row in rows if _is_unsafe_activation(row))
    controlled_count = sum(1 for row in rows if _status(row) == "controlled")
    disabled_count = sum(1 for row in rows if _status(row) == "disabled")
    rolled_back_count = sum(1 for row in rows if _status(row) == "rolled_back")
    read_count = sum(item["read_count"] for item in reads.values())
    prompt_mutation_read_count = sum(item["prompt_mutation_read_count"] for item in reads.values())
    return {
        "success": unsafe_count == 0,
        "strategy_activations": {
            "count": len(rows),
            "controlled_count": controlled_count,
            "disabled_count": disabled_count,
            "rolled_back_count": rolled_back_count,
            "unsafe_count": unsafe_count,
            "read_count": read_count,
            "prompt_mutation_read_count": prompt_mutation_read_count,
            "top": top,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a privacy-safe visual strategy activation report.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--intent-signature", default=None)
    parser.add_argument("--strategy-signature", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = build_strategy_activation_report(
        args.db_path,
        intent_signature=args.intent_signature,
        strategy_signature=args.strategy_signature,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual strategy activation report {status}")
    return 0 if payload["success"] else 1


def _activation_rows(
    conn: sqlite3.Connection,
    *,
    intent_signature: str | None,
    strategy_signature: str | None,
) -> list[sqlite3.Row]:
    where_parts: list[str] = []
    params: list[str] = []
    if intent_signature is not None:
        where_parts.append("intent_signature = ?")
        params.append(intent_signature)
    if strategy_signature is not None:
        where_parts.append("strategy_signature = ?")
        params.append(strategy_signature)
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    return conn.execute(
        f"""
        SELECT *
        FROM visual_strategy_activations
        {where}
        ORDER BY created_at DESC, rowid DESC
        """,
        tuple(params),
    ).fetchall()


def _row_to_report(row: sqlite3.Row, *, reads: dict[str, dict[str, int]]) -> dict[str, Any]:
    promotion_decision = _json_value(_row_value(row, "promotion_decision", "promotion_decision_json"))
    activation_id = str(_row_value(row, "id", "strategy_activation_id") or "")
    read_counts = reads.get(activation_id, {"read_count": 0, "prompt_mutation_read_count": 0})
    return {
        "id": activation_id,
        "shadow_update_id": _row_value(row, "shadow_update_id"),
        "intent_signature": _row_value(row, "intent_signature"),
        "strategy_signature": _row_value(row, "strategy_signature"),
        "activation_status": _status(row),
        "promotion_decision": promotion_decision,
        "rollback_of": _row_value(row, "rollback_of"),
        "read_count": read_counts["read_count"],
        "prompt_mutation_read_count": read_counts["prompt_mutation_read_count"],
        "unsafe": _is_unsafe_activation(row),
    }


def _activation_read_counts(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    if not _table_exists(conn, "visual_rankings"):
        return {}
    counts: dict[str, dict[str, int]] = {}
    for row in conn.execute("SELECT * FROM visual_rankings").fetchall():
        metadata = _json_value(_row_value(row, "metadata", "rationale_json"))
        strategy_plan = metadata.get("strategy_plan") if isinstance(metadata, dict) else None
        if not isinstance(strategy_plan, dict):
            continue
        activation_id = strategy_plan.get("activation_id")
        if not isinstance(activation_id, str) or not activation_id:
            continue
        item = counts.setdefault(
            activation_id,
            {"read_count": 0, "prompt_mutation_read_count": 0},
        )
        item["read_count"] += 1
        if strategy_plan.get("prompt_mutation_allowed") is True:
            item["prompt_mutation_read_count"] += 1
    return counts


def _is_unsafe_activation(row: sqlite3.Row) -> bool:
    if _status(row) != "controlled":
        return False
    promotion_decision = _json_value(_row_value(row, "promotion_decision", "promotion_decision_json"))
    return not (
        isinstance(promotion_decision, dict)
        and promotion_decision.get("allowed") is True
        and promotion_decision.get("decision") == "promote_controlled"
    )


def _status(row: sqlite3.Row) -> str:
    return str(_row_value(row, "activation_status") or "")


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
        "strategy_activations": {
            "count": 0,
            "controlled_count": 0,
            "disabled_count": 0,
            "rolled_back_count": 0,
            "unsafe_count": 0,
            "read_count": 0,
            "prompt_mutation_read_count": 0,
            "top": [],
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
