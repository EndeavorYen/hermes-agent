#!/usr/bin/env python3
"""Verify live Visual Agent Mode image/video delivery evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
    proof = verify_visual_agent_live_proof(
        ledger_path,
        since=args.since,
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


if __name__ == "__main__":
    sys.exit(main())
