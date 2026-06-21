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

from agent.visual.learning.outcomes import aggregate_visual_strategy_outcomes
from agent.visual.learning.proposals import propose_visual_policy_updates
from agent.visual.tracking import default_visual_ledger_path
from scripts.visual_evidence_report import build_visual_evidence_report
from scripts.visual_strategy_activation_report import build_strategy_activation_report


def build_visual_learning_report(db_path: str | Path) -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return _empty_report()

    outcomes = aggregate_visual_strategy_outcomes(db_path)
    proposals = propose_visual_policy_updates(outcomes)
    evidence = _safe_evidence_report(db_path)
    activation = build_strategy_activation_report(db_path)
    blocked = _blocked_promotions(db_path)
    human_veto_count = sum(
        int(row["human_feedback"]["human_veto_count"])
        for row in outcomes.get("outcomes", [])
        if isinstance(row.get("human_feedback"), dict)
    )
    ask_user_count = sum(
        int(row["active_learning"]["ask_user_count"])
        for row in outcomes.get("outcomes", [])
        if isinstance(row.get("active_learning"), dict)
    )
    ranking_count = sum(
        int(row["active_learning"]["ranking_count"])
        for row in outcomes.get("outcomes", [])
        if isinstance(row.get("active_learning"), dict)
    )

    activation_counts = activation["strategy_activations"]
    evidence_proof = evidence["proof"]
    failures = _failures(
        unsafe_activation_count=int(activation_counts["unsafe_count"]),
        prompt_mutation_read_count=int(activation_counts["prompt_mutation_read_count"]),
        duplicate_delivery_count=int(evidence_proof["duplicate_artifact_delivery_count"]),
        missing_source_metadata_count=int(evidence_proof["missing_source_metadata_count"]),
    )
    return {
        "success": not failures,
        "failures": failures,
        "learning": {
            "bucket_count": int(outcomes["bucket_count"]),
            "strategy_count": int(outcomes["strategy_count"]),
            "top_shadow_proposals": proposals[:10],
            "controlled_strategy_reads": int(activation_counts["read_count"]),
            "blocked_promotions": blocked,
            "rollback_count": int(activation_counts["rolled_back_count"]),
            "prompt_mutation_reads": int(activation_counts["prompt_mutation_read_count"]),
            "human_veto_count": human_veto_count,
            "ask_user_rate": _rate(ask_user_count, ranking_count),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a privacy-safe visual learning report.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_learning_report(args.db_path)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual learning report {status}")
    return 0 if payload["success"] else 1


def _safe_evidence_report(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        if not _table_exists(conn, "visual_requests"):
            return {
                "proof": {
                    "duplicate_artifact_delivery_count": 0,
                    "missing_source_metadata_count": 0,
                }
            }
    return build_visual_evidence_report(db_path)


def _blocked_promotions(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "visual_strategy_activations"):
            return []
        rows = conn.execute(
            """
            SELECT *
            FROM visual_strategy_activations
            ORDER BY created_at DESC, rowid DESC
            """
        ).fetchall()
    blocked: list[dict[str, Any]] = []
    for row in rows:
        decision = _json_value(_row_value(row, "promotion_decision", "promotion_decision_json"))
        if not isinstance(decision, dict) or decision.get("allowed") is True:
            continue
        blocked.append(
            {
                "intent_signature": _row_value(row, "intent_signature"),
                "strategy_signature": _row_value(row, "strategy_signature"),
                "reasons": decision.get("reasons", []),
            }
        )
    return blocked[:10]


def _failures(
    *,
    unsafe_activation_count: int,
    prompt_mutation_read_count: int,
    duplicate_delivery_count: int,
    missing_source_metadata_count: int,
) -> list[str]:
    failures: list[str] = []
    if unsafe_activation_count:
        failures.append("unsafe_strategy_activation")
    if prompt_mutation_read_count:
        failures.append("prompt_mutation_read")
    if duplicate_delivery_count:
        failures.append("duplicate_delivery")
    if missing_source_metadata_count:
        failures.append("missing_source_metadata")
    return failures


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


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _empty_report() -> dict[str, Any]:
    return {
        "success": True,
        "failures": [],
        "learning": {
            "bucket_count": 0,
            "strategy_count": 0,
            "top_shadow_proposals": [],
            "controlled_strategy_reads": 0,
            "blocked_promotions": [],
            "rollback_count": 0,
            "prompt_mutation_reads": 0,
            "human_veto_count": 0,
            "ask_user_rate": 0.0,
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
