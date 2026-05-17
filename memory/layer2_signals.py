"""Signal detector for deciding whether Layer-2 dream validation should run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional

from hermes_time import now as _hermes_now
from memory.layer2_store import Layer2Store


@dataclass(frozen=True)
class Layer2SignalDecision:
    should_run_dream: bool
    reason_codes: list[str]
    event_count: int


def detect_layer2_signals(*, store: Optional[Layer2Store] = None, since: str) -> Layer2SignalDecision:
    ledger = store or Layer2Store()
    with ledger._connect() as conn:
        rows = conn.execute(
            """
            SELECT event_type, COUNT(*) AS n
            FROM candidate_events
            WHERE event_ts >= ?
            GROUP BY event_type
            """,
            (since,),
        ).fetchall()
    counts = {row["event_type"]: int(row["n"] or 0) for row in rows}
    reason_codes: list[str] = []
    if (
        counts.get("contradict", 0) > 0
        or counts.get("quarantine", 0) > 0
        or counts.get("forced_exit_quarantine", 0) > 0
    ):
        reason_codes.append("contradiction_spike")
    if counts.get("promote", 0) > 0:
        reason_codes.append("promotion_happened")
    if counts.get("create", 0) + counts.get("strengthen", 0) >= 8:
        reason_codes.append("candidate_volume_spike")
    return Layer2SignalDecision(
        should_run_dream=bool(reason_codes),
        reason_codes=reason_codes,
        event_count=sum(counts.values()),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Detect whether Layer-2 needs dream validation")
    parser.add_argument("--since")
    parser.add_argument("--lookback-hours", type=float)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--wake-gate", action="store_true")
    args = parser.parse_args(argv)

    since = args.since
    if not since and args.lookback_hours is not None:
        since = (_hermes_now() - timedelta(hours=args.lookback_hours)).isoformat()
    if not since:
        parser.error("--since or --lookback-hours is required")

    store = Layer2Store(args.db) if args.db else None
    decision = detect_layer2_signals(store=store, since=since)
    payload = dict(decision.__dict__)
    if args.wake_gate:
        payload["wakeAgent"] = decision.should_run_dream
    payload["since"] = since
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
