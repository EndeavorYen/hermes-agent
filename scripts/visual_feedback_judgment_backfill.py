from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.feedback_judgment_backfill import backfill_feedback_judgments
from agent.visual.tracking import default_visual_ledger_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill visual quality judgments for feedback artifacts.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = backfill_feedback_judgments(
        args.db_path,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    payload["dry_run"] = args.dry_run
    payload["limit"] = args.limit
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        action = "would create" if args.dry_run else "created"
        print(f"visual feedback judgment backfill {action} {payload['created_count']} judgments")
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
