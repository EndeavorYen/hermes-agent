from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.tracking import default_visual_ledger_path
from scripts.visual_agent_mode_regression_report import build_visual_agent_mode_regression_report
from scripts.visual_autonomous_healthcheck import build_visual_autonomous_healthcheck
from scripts.visual_live_provider_e2e import build_visual_live_provider_e2e_report


def build_visual_e2e_automation_report(
    *,
    work_dir: str | Path | None = None,
    include_live: bool = False,
) -> dict[str, Any]:
    agent_mode = build_visual_agent_mode_regression_report()
    fixture_e2e = build_visual_live_provider_e2e_report(mode="fixture", work_dir=work_dir)
    health = build_visual_autonomous_healthcheck(_ledger_path_for_work_dir(work_dir), autonomy_level=2)
    if include_live:
        live_e2e = (
            build_visual_live_provider_e2e_report(mode="live", work_dir=None)
            if live_provider_enabled()
            else {"status": "skipped", "reason": "live_provider_not_enabled"}
        )
    else:
        live_e2e = {"status": "not_requested"}

    failures = []
    if agent_mode.get("success") is not True:
        failures.append("agent_mode_failed")
    if fixture_e2e.get("success") is not True:
        failures.append("fixture_e2e_failed")
    if health.get("success") is not True:
        failures.append("health_failed")
    if isinstance(live_e2e, dict) and live_e2e.get("success") is False:
        failures.append("live_e2e_failed")
    return {
        "success": not failures,
        "mode": "fixture+live" if include_live else "fixture",
        "failures": failures,
        "agent_mode": agent_mode,
        "fixture_e2e": fixture_e2e,
        "live_e2e": live_e2e,
        "health": health,
    }


def live_provider_enabled() -> bool:
    return str(os.environ.get("HERMES_VISUAL_LIVE_E2E") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run visual E2E automation with fixture-first gating.")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--include-live", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_e2e_automation_report(
        work_dir=args.work_dir,
        include_live=args.include_live,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual e2e automation report {status}")
    if args.allow_failures:
        return 0
    return 0 if payload["success"] else 1


def _ledger_path_for_work_dir(work_dir: str | Path | None) -> Path:
    if work_dir is None:
        return default_visual_ledger_path()
    return Path(work_dir) / "visual" / "attempt_ledger.sqlite3"


if __name__ == "__main__":
    raise SystemExit(main())
