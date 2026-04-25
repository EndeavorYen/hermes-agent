"""Deterministic Layer-2 ledger consolidation.

This module is intentionally non-generative: it merges exact normalized duplicates,
ages weak unsupported candidates, quarantines contradiction-dominated candidates,
and prunes stale low-support items. It never writes durable MEMORY/USER state.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_time import now as _hermes_now
from memory.layer2_store import Layer2Store, _clean_optional_text, _parse_iso_datetime


def _iso(value: datetime) -> str:
    return value.isoformat()


def _event(
    conn,
    *,
    candidate_id: int,
    event_type: str,
    event_ts: str,
    notes: str,
    job_id: str = "nightly-layer2-consolidate",
) -> None:
    conn.execute(
        """
        INSERT INTO candidate_events (
            candidate_id, event_type, event_ts, source_ref, source_event_id,
            counts_for_recurrence, support_delta, contradict_delta,
            notes, job_id
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
    now: Optional[str | datetime] = None,
    stale_after_days: int = 14,
    prune_after_days: int = 30,
    job_id: str = "nightly-layer2-consolidate",
) -> List[Dict[str, Any]]:
    """Run deterministic, idempotent Layer-2 hygiene.

    Actions:
    - merge deterministic canonical-key collisions
    - active -> quarantined if contradictions dominate support
    - active -> stale if low-support and unsupported for stale_after_days
    - stale -> pruned if still low-support after prune_after_days

    No durable memory/user writes happen here.
    """

    ledger = store or Layer2Store(db_path)
    if isinstance(now, datetime):
        now_dt = now
    elif now:
        parsed = _parse_iso_datetime(str(now))
        now_dt = parsed or _hermes_now()
    else:
        now_dt = _hermes_now()
    now_s = _iso(now_dt)
    stale_cutoff = _iso(now_dt - timedelta(days=stale_after_days))
    prune_cutoff = _iso(now_dt - timedelta(days=prune_after_days))

    audits: List[Dict[str, Any]] = []
    audits.extend(ledger.merge_canonical_key_collisions())

    with ledger._connect() as conn:  # noqa: SLF001 - consolidation is a store-maintenance peer.
        # Quarantine contradiction-dominated active candidates. Keep support records;
        # only change recall eligibility/status.
        rows = conn.execute(
            """
            SELECT * FROM candidates
            WHERE status = 'active'
              AND contradict_count > 0
              AND contradict_count >= support_count
            ORDER BY id ASC
            """
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE candidates SET status = 'quarantine', updated_at = ? WHERE id = ?",
                (now_s, row["id"]),
            )
            _event(
                conn,
                candidate_id=row["id"],
                event_type="quarantine",
                event_ts=now_s,
                notes="contradictions dominate support",
                job_id=job_id,
            )
            audits.append(
                {
                    "audit_label": "candidate_quarantined",
                    "candidate_id": row["id"],
                    "canonical_text": row["canonical_text"],
                    "support_count": row["support_count"],
                    "contradict_count": row["contradict_count"],
                }
            )

        # Mark old low-support active candidates stale when no counted support arrived recently.
        rows = conn.execute(
            """
            SELECT c.*
            FROM candidates c
            WHERE c.status = 'active'
              AND c.support_count < 2
              AND NOT EXISTS (
                  SELECT 1 FROM candidate_events e
                  WHERE e.candidate_id = c.id
                    AND e.counts_for_recurrence = 1
                    AND e.support_delta > 0
                    AND e.event_ts >= ?
              )
            ORDER BY c.id ASC
            """,
            (stale_cutoff,),
        ).fetchall()
        for row in rows:
            created_at = _clean_optional_text(row["created_at"])
            updated_at = _clean_optional_text(row["updated_at"])
            if (created_at and created_at > stale_cutoff) or (updated_at and updated_at > stale_cutoff):
                continue
            conn.execute(
                "UPDATE candidates SET status = 'stale', updated_at = ? WHERE id = ?",
                (now_s, row["id"]),
            )
            _event(
                conn,
                candidate_id=row["id"],
                event_type="stale",
                event_ts=now_s,
                notes=f"low support and no counted support for {stale_after_days}+ days",
                job_id=job_id,
            )
            audits.append(
                {
                    "audit_label": "candidate_marked_stale",
                    "candidate_id": row["id"],
                    "canonical_text": row["canonical_text"],
                    "support_count": row["support_count"],
                }
            )

        # Prune stale low-support candidates only after a longer stale interval.
        rows = conn.execute(
            """
            SELECT * FROM candidates
            WHERE status = 'stale'
              AND support_count < 2
              AND updated_at <= ?
            ORDER BY id ASC
            """,
            (prune_cutoff,),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE candidates SET status = 'pruned', updated_at = ? WHERE id = ?",
                (now_s, row["id"]),
            )
            _event(
                conn,
                candidate_id=row["id"],
                event_type="prune",
                event_ts=now_s,
                notes=f"stale low-support candidate exceeded {prune_after_days}-day prune window",
                job_id=job_id,
            )
            audits.append(
                {
                    "audit_label": "candidate_pruned",
                    "candidate_id": row["id"],
                    "canonical_text": row["canonical_text"],
                    "support_count": row["support_count"],
                }
            )

    return audits


def format_consolidation_report(audits: List[Dict[str, Any]]) -> str:
    if not audits:
        return "Layer-2 consolidation: no changes."
    lines = ["Layer-2 consolidation changes:"]
    for item in audits:
        label = item.get("audit_label", "event")
        text = item.get("canonical_text") or item.get("canonical_key") or item.get("candidate_id")
        lines.append(f"- {label}: {text}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Layer-2 consolidation")
    parser.add_argument("--db", type=Path, default=None, help="Layer-2 sqlite path (defaults to Hermes home)")
    parser.add_argument("--now", default=None, help="Override current timestamp for tests/manual audit")
    parser.add_argument("--json", action="store_true", help="Emit JSON audit instead of text")
    args = parser.parse_args(argv)
    audits = consolidate_layer2(db_path=args.db, now=args.now)
    if args.json:
        print(json.dumps({"changes": audits}, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_consolidation_report(audits))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
