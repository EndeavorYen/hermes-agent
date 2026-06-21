from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.calibration import build_quality_calibration_report
from agent.visual.tracking import default_visual_ledger_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a privacy-safe visual quality calibration report.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = build_quality_calibration_report(args.db_path)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print("visual quality calibration report passed")
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
