from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def build_visual_evidence_report(db_path: str | Path) -> dict[str, Any]:
    db_path = Path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        request_count = _count(conn, "visual_requests")
        attempt_count = _count(conn, "visual_attempts")
        artifact_count = _count(conn, "visual_artifacts")
        delivery_count = _count(conn, "visual_deliveries")
        feedback_count = _count(conn, "visual_feedback")
        duplicate_count = _duplicate_sent_delivery_count(conn)
        missing_metadata_count = _missing_source_metadata_count(conn)

    proof = {
        "duplicate_artifact_delivery_count": duplicate_count,
        "missing_source_metadata_count": missing_metadata_count,
    }
    return {
        "success": duplicate_count == 0 and missing_metadata_count == 0,
        "requests": {"count": request_count},
        "attempts": {"count": attempt_count},
        "artifacts": {"count": artifact_count},
        "deliveries": {"count": delivery_count},
        "feedback": {"count": feedback_count},
        "proof": proof,
    }


def _count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def _duplicate_sent_delivery_count(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM visual_deliveries d
        JOIN visual_artifacts a ON a.id = d.artifact_id
        WHERE d.delivery_status = 'sent'
          AND a.content_hash IS NOT NULL
        GROUP BY d.request_id, d.destination, a.content_hash
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    return sum(int(row["count"]) - 1 for row in rows)


def _missing_source_metadata_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM visual_artifacts
        WHERE content_hash IS NULL
           OR freshness_status IS NULL
           OR kind IS NULL
           OR (local_path IS NULL AND uri IS NULL)
        """
    ).fetchone()
    return int(row["count"])
