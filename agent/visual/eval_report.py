from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.visual_evidence_report import build_visual_evidence_report
from scripts.visual_strategy_activation_report import build_strategy_activation_report


def build_visual_regression_report(db_path: str | Path) -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return _empty_report()

    evidence = build_visual_evidence_report(db_path)
    activation = build_strategy_activation_report(db_path)
    counts = {
        "requests": int(evidence["requests"]["count"]),
        "artifacts": int(evidence["artifacts"]["count"]),
        "duplicate_deliveries": int(evidence["proof"]["duplicate_artifact_delivery_count"]),
        "missing_source_metadata": int(evidence["proof"]["missing_source_metadata_count"]),
        "unsafe_activations": int(activation["strategy_activations"]["unsafe_count"]),
        "strategy_reads": int(activation["strategy_activations"]["read_count"]),
        "prompt_mutation_reads": int(activation["strategy_activations"]["prompt_mutation_read_count"]),
        "judgments": _judgment_count(db_path),
    }
    failures = _failures(counts)
    return {
        "success": not failures,
        "db_path": str(db_path),
        "counts": counts,
        "failures": failures,
    }


def _failures(counts: dict[str, int]) -> list[str]:
    failures: list[str] = []
    if counts["duplicate_deliveries"] > 0:
        failures.append("duplicate_delivery")
    if counts["missing_source_metadata"] > 0:
        failures.append("missing_source_metadata")
    if counts["unsafe_activations"] > 0:
        failures.append("unsafe_strategy_activation")
    if counts["prompt_mutation_reads"] > 0:
        failures.append("prompt_mutation_read")
    return failures


def _judgment_count(db_path: Path) -> int:
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'visual_judgments'"
        ).fetchone()
        if row is None:
            return 0
        count = conn.execute("SELECT COUNT(*) AS count FROM visual_judgments").fetchone()
    return int(count[0])


def _empty_report() -> dict[str, Any]:
    return {
        "success": True,
        "db_path": None,
        "counts": {
            "requests": 0,
            "artifacts": 0,
            "duplicate_deliveries": 0,
            "missing_source_metadata": 0,
            "unsafe_activations": 0,
            "strategy_reads": 0,
            "prompt_mutation_reads": 0,
            "judgments": 0,
        },
        "failures": [],
    }
