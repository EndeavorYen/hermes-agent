"""Deterministic Layer-2 ledger consolidation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from hermes_time import now as _hermes_now
from memory.layer2_store import Layer2Store


def _parse_dt(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
    return _hermes_now()


def _event(conn, *, candidate_id: int, event_type: str, event_ts: str, notes: str, job_id: str) -> None:
    conn.execute(
        """
        INSERT INTO candidate_events (
            candidate_id, event_type, event_ts, source_ref, source_event_id,
            counts_for_recurrence, support_delta, contradict_delta, notes, job_id
        ) VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
        """,
        (
            candidate_id,
            event_type,
            event_ts,
            f"consolidator:{job_id}:{event_ts}",
            f"consolidator:{job_id}:{event_type}:{candidate_id}:{event_ts}",
            notes,
            job_id,
        ),
    )


def consolidate_layer2(
    *,
    store: Optional[Layer2Store] = None,
    db_path: Optional[Path] = None,
    now: str | datetime | None = None,
    stale_after_days: int = 14,
    prune_after_days: int = 30,
    question_forced_exit_support_threshold: int = 8,
    question_forced_exit_after_days: int = 14,
    job_id: str = "nightly-layer2-consolidate",
) -> list[dict[str, Any]]:
    ledger = store or Layer2Store(db_path)
    now_dt = _parse_dt(now)
    now_s = now_dt.isoformat()
    stale_cutoff = (now_dt - timedelta(days=stale_after_days)).isoformat()
    prune_cutoff = (now_dt - timedelta(days=prune_after_days)).isoformat()
    forced_exit_cutoff = (now_dt - timedelta(days=question_forced_exit_after_days)).isoformat()
    audits: list[dict[str, Any]] = []

    with ledger._connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM candidates
            WHERE status = 'active'
              AND contradict_count > 0
              AND contradict_count >= support_count
            ORDER BY id
            """
        ).fetchall()
        for row in rows:
            conn.execute("UPDATE candidates SET status = 'quarantine', updated_at = ? WHERE id = ?", (now_s, row["id"]))
            _event(conn, candidate_id=row["id"], event_type="quarantine", event_ts=now_s, notes="contradictions dominate support", job_id=job_id)
            audits.append(
                {
                    "audit_label": "candidate_quarantined",
                    "candidate_id": row["id"],
                    "canonical_text": row["canonical_text"],
                    "support_count": row["support_count"],
                    "contradict_count": row["contradict_count"],
                }
            )

        rows = conn.execute(
            """
            SELECT * FROM candidates
            WHERE status = 'active'
              AND lower(trim(COALESCE(kind, ''))) = 'question'
              AND support_count >= ?
              AND created_at <= ?
            ORDER BY support_count DESC, id
            """,
            (question_forced_exit_support_threshold, forced_exit_cutoff),
        ).fetchall()
        for row in rows:
            conn.execute("UPDATE candidates SET status = 'quarantine', updated_at = ? WHERE id = ?", (now_s, row["id"]))
            _event(
                conn,
                candidate_id=row["id"],
                event_type="forced_exit_quarantine",
                event_ts=now_s,
                notes="high-support unresolved question exceeded forced-exit TTL",
                job_id=job_id,
            )
            audits.append(
                {
                    "audit_label": "question_forced_exit_quarantined",
                    "candidate_id": row["id"],
                    "canonical_text": row["canonical_text"],
                    "support_count": row["support_count"],
                }
            )

        rows = conn.execute(
            """
            SELECT c.*
            FROM candidates c
            WHERE c.status = 'active'
              AND c.support_count < 2
              AND c.updated_at <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM candidate_events e
                  WHERE e.candidate_id = c.id
                    AND e.counts_for_recurrence = 1
                    AND e.support_delta > 0
                    AND e.event_ts >= ?
              )
            ORDER BY c.id
            """,
            (stale_cutoff, stale_cutoff),
        ).fetchall()
        for row in rows:
            conn.execute("UPDATE candidates SET status = 'stale', updated_at = ? WHERE id = ?", (now_s, row["id"]))
            _event(conn, candidate_id=row["id"], event_type="stale", event_ts=now_s, notes="old low-support candidate", job_id=job_id)
            audits.append(
                {
                    "audit_label": "candidate_marked_stale",
                    "candidate_id": row["id"],
                    "canonical_text": row["canonical_text"],
                    "support_count": row["support_count"],
                }
            )

        rows = conn.execute(
            """
            SELECT * FROM candidates
            WHERE status = 'stale'
              AND support_count < 2
              AND updated_at <= ?
            ORDER BY id
            """,
            (prune_cutoff,),
        ).fetchall()
        for row in rows:
            conn.execute("UPDATE candidates SET status = 'pruned', updated_at = ? WHERE id = ?", (now_s, row["id"]))
            _event(conn, candidate_id=row["id"], event_type="prune", event_ts=now_s, notes="old stale low-support candidate", job_id=job_id)
            audits.append(
                {
                    "audit_label": "candidate_pruned",
                    "candidate_id": row["id"],
                    "canonical_text": row["canonical_text"],
                    "support_count": row["support_count"],
                }
            )

    return audits


def format_consolidation_report(audits: list[dict[str, Any]]) -> str:
    if not audits:
        return "Layer-2 consolidation: no changes."
    lines = ["Layer-2 consolidation changes:"]
    for item in audits:
        label = item.get("audit_label", "event")
        text = item.get("canonical_text") or item.get("candidate_id")
        lines.append(f"- {label}: {text}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Layer-2 consolidation")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--now", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    audits = consolidate_layer2(db_path=args.db, now=args.now)
    if args.json:
        print(json.dumps({"changes": audits}, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_consolidation_report(audits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
