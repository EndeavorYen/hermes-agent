from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.eval_report import build_visual_regression_report
from agent.visual.tracking import default_visual_ledger_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a privacy-safe visual regression report.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_regression_report(args.db_path)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual regression report {status}")
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
