from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.eval_report import build_visual_regression_report
from agent.visual.tracking import default_visual_ledger_path
from scripts.visual_autonomous_loop_report import build_visual_autonomous_loop_report
from scripts.visual_learning_report import build_visual_learning_report


def build_visual_autonomous_healthcheck(
    db_path: str | Path,
    *,
    autonomy_level: int = 2,
) -> dict[str, Any]:
    db_path = Path(db_path)
    autonomous_loop = build_visual_autonomous_loop_report(db_path, autonomy_level=autonomy_level)
    regression = autonomous_loop.get("regression")
    if not isinstance(regression, dict):
        regression = build_visual_regression_report(db_path)
    learning = build_visual_learning_report(db_path)

    reports = {
        "autonomous_loop": autonomous_loop,
        "regression": regression,
        "learning": learning,
    }
    failures = [
        name
        for name, report in reports.items()
        if not isinstance(report, dict) or report.get("success") is not True
    ]
    return {
        "success": not failures,
        "health_status": "pass" if not failures else "fail",
        "failures": failures,
        "db_path": str(db_path),
        "autonomy_level": autonomy_level,
        "reports": reports,
        "self_review": {
            "reduces_human_intervention": autonomous_loop.get("self_review", {}).get(
                "reduces_human_intervention",
                False,
            ),
            "prompt_mutation_allowed": False,
            "privacy_safe": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the visual autonomous healthcheck.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--autonomy-level", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_autonomous_healthcheck(args.db_path, autonomy_level=args.autonomy_level)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"visual autonomous healthcheck {payload['health_status']}")
    if args.allow_failures:
        return 0
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
