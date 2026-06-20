"""Conservative strategy atom learning store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from agent.visual.ids import utc_now_iso


_ALLOWED_EVIDENCE_KEYS = {
    "artifact_id",
    "request_id",
    "attempt_id",
    "provider",
    "model",
    "error_type",
    "feedback_polarity",
    "score_components",
    "provider_health",
    "artifact_quality",
    "delivery_health",
    "preference_score",
    "overall_score",
    "confidence",
}


class StrategyAtomStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_atoms (
                    bucket TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    score REAL NOT NULL,
                    count INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    PRIMARY KEY(bucket, strategy_id)
                )
                """
            )

    def record_outcome(
        self,
        *,
        bucket: str,
        strategy_id: str,
        reward: float,
        evidence: Dict[str, Any],
    ) -> None:
        safe_evidence = _safe_evidence(evidence)
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT score, count
                FROM strategy_atoms
                WHERE bucket = ? AND strategy_id = ?
                """,
                (bucket, strategy_id),
            ).fetchone()
            if existing is None:
                score = _clamp_reward(reward)
                count = 1
            else:
                old_score = float(existing["score"])
                count = int(existing["count"]) + 1
                score = round((0.8 * old_score) + (0.2 * _clamp_reward(reward)), 4)

            conn.execute(
                """
                INSERT INTO strategy_atoms (
                    bucket, strategy_id, score, count, updated_at, evidence_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(bucket, strategy_id) DO UPDATE SET
                    score = excluded.score,
                    count = excluded.count,
                    updated_at = excluded.updated_at,
                    evidence_json = excluded.evidence_json
                """,
                (
                    bucket,
                    strategy_id,
                    score,
                    count,
                    utc_now_iso(),
                    json.dumps(safe_evidence, sort_keys=True),
                ),
            )

    def top_strategies(self, bucket: str, limit: int = 5) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT strategy_id, score, count, updated_at, evidence_json
                FROM strategy_atoms
                WHERE bucket = ?
                ORDER BY score DESC, count DESC, strategy_id ASC
                LIMIT ?
                """,
                (bucket, limit),
            ).fetchall()
        return [
            {
                "strategy_id": row["strategy_id"],
                "score": float(row["score"]),
                "count": int(row["count"]),
                "updated_at": row["updated_at"],
                "evidence": json.loads(row["evidence_json"] or "{}"),
            }
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def _safe_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in dict(evidence or {}).items()
        if key in _ALLOWED_EVIDENCE_KEYS
    }


def _clamp_reward(reward: float) -> float:
    return max(0.0, min(1.0, float(reward)))
