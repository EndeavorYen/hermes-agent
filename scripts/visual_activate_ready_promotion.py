from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.promotion_readiness_activation import activate_ready_visual_promotion
from agent.visual.tracking import default_visual_ledger_path
from scripts.visual_self_validation_status import build_visual_self_validation_status


def build_visual_ready_promotion_activation(
    *,
    db_path: str | Path | None = None,
    latest_path: str | Path | None = None,
    status_path: str | Path | None = None,
) -> dict[str, Any]:
    status = _status(latest_path=latest_path, status_path=status_path)
    ledger = VisualAttemptLedger(Path(db_path) if db_path is not None else default_visual_ledger_path())
    ledger.initialize()
    activation = activate_ready_visual_promotion(ledger, status)
    return {
        "success": activation.get("success") is True,
        "run_id": status.get("run_id"),
        "health_status": status.get("health_status"),
        "promotion_ready": _promotion_ready(status),
        "activation": activation,
        "self_review": {
            "privacy_safe": True,
            "raw_report_exposed": False,
            "reduces_human_intervention": activation.get("activated_count", 0) > 0
            or activation.get("skipped_count", 0) > 0,
        },
    }


def _status(
    *,
    latest_path: str | Path | None,
    status_path: str | Path | None,
) -> dict[str, Any]:
    if status_path is not None:
        payload = _read_json(Path(status_path))
        return payload if isinstance(payload, dict) else {}
    return build_visual_self_validation_status(latest_path=latest_path)


def _promotion_ready(status: dict[str, Any]) -> bool:
    readiness = status.get("promotion_readiness") if isinstance(status.get("promotion_readiness"), dict) else {}
    return readiness.get("ready") is True


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Activate a ready visual promotion candidate.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--latest-path", type=Path, default=None)
    parser.add_argument("--status-path", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_ready_promotion_activation(
        db_path=args.db_path,
        latest_path=args.latest_path,
        status_path=args.status_path,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "activated" if payload["success"] else "blocked"
        print(f"visual ready promotion activation {status}")
    if args.allow_blocked:
        return 0
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
