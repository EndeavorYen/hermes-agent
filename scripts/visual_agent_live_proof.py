#!/usr/bin/env python3
"""Verify live Visual Agent Mode image/video delivery evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent.visual.live_proof import verify_visual_agent_live_proof
from agent.visual.tracking import default_visual_ledger_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read the visual attempt ledger and verify Slack image/video delivery proof."
    )
    parser.add_argument(
        "--ledger-path",
        default=None,
        help="Path to visual attempt ledger. Defaults to Hermes visual_tracking config.",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Only count deliveries at or after this ISO timestamp.",
    )
    parser.add_argument(
        "--since-local-date",
        default=None,
        help=(
            "Only count deliveries at or after local midnight for YYYY-MM-DD. "
            "Converted to UTC before querying the ledger."
        ),
    )
    parser.add_argument(
        "--timezone",
        default=None,
        help=(
            "IANA timezone for --since-local-date, e.g. Asia/Taipei. "
            "Defaults to the system local timezone."
        ),
    )
    parser.add_argument("--platform", default="slack")
    parser.add_argument("--destination-id", default=None)
    parser.add_argument("--thread-id", default=None)
    parser.add_argument(
        "--no-require-image",
        action="store_true",
        help="Do not require a delivered image artifact.",
    )
    parser.add_argument(
        "--no-require-video",
        action="store_true",
        help="Do not require a delivered video artifact.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Pretty-print JSON output. Kept explicit for readable operator commands.",
    )
    args = parser.parse_args(argv)

    ledger_path = Path(args.ledger_path).expanduser() if args.ledger_path else default_visual_ledger_path()
    try:
        since = _resolve_since(
            since=args.since,
            since_local_date=args.since_local_date,
            timezone_name=args.timezone,
        )
    except ValueError as exc:
        parser.error(str(exc))
    proof = verify_visual_agent_live_proof(
        ledger_path,
        since=since,
        platform=args.platform,
        destination_id=args.destination_id,
        thread_id=args.thread_id,
        require_image=not args.no_require_image,
        require_video=not args.no_require_video,
    )
    payload = proof.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if proof.success else 1


def _resolve_since(
    *,
    since: str | None,
    since_local_date: str | None,
    timezone_name: str | None,
) -> str | None:
    if since and since_local_date:
        raise ValueError("Use either --since or --since-local-date, not both.")
    if not since_local_date:
        return since

    try:
        local_midnight = datetime.strptime(since_local_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("--since-local-date must use YYYY-MM-DD.") from exc

    tzinfo = _timezone_from_name(timezone_name)
    return (
        local_midnight.replace(tzinfo=tzinfo)
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _timezone_from_name(timezone_name: str | None):
    if not timezone_name:
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone for --timezone: {timezone_name}") from exc


if __name__ == "__main__":
    sys.exit(main())
