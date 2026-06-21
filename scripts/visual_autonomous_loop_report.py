from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.autonomous_rollout import evaluate_autonomous_rollout_candidate
from agent.visual.eval_report import build_visual_regression_report
from agent.visual.learning.outcomes import aggregate_visual_strategy_outcomes
from agent.visual.learning.proposals import propose_visual_policy_updates
from agent.visual.tracking import default_visual_ledger_path


def build_visual_autonomous_loop_report(
    db_path: str | Path,
    *,
    autonomy_level: int = 2,
) -> dict[str, Any]:
    db_path = Path(db_path)
    regression = build_visual_regression_report(db_path)
    outcomes = aggregate_visual_strategy_outcomes(db_path)
    proposals = propose_visual_policy_updates(outcomes)
    runtime_checks = _runtime_checks(regression)
    rollout_decisions = [
        evaluate_autonomous_rollout_candidate(
            proposal,
            runtime_checks=runtime_checks,
            autonomy_level=autonomy_level,
        )
        for proposal in proposals
    ]
    failures = _failures(regression, rollout_decisions)
    controlled_count = sum(1 for decision in rollout_decisions if decision.get("allowed") is True)
    return {
        "success": not failures,
        "failures": failures,
        "db_path": str(db_path),
        "autonomy_level": autonomy_level,
        "regression": regression,
        "learning": {
            "bucket_count": outcomes.get("bucket_count", 0),
            "strategy_count": outcomes.get("strategy_count", 0),
            "proposal_count": len(proposals),
            "proposal_types": sorted({str(proposal.get("type") or "") for proposal in proposals}),
        },
        "rollout": {
            "controlled_candidate_count": controlled_count,
            "shadow_only_count": len(rollout_decisions) - controlled_count,
            "decisions": rollout_decisions,
        },
        "self_review": {
            "reduces_human_intervention": controlled_count > 0 and regression.get("success") is True,
            "prompt_mutation_allowed": False,
            "remaining_human_inputs": _remaining_human_inputs(rollout_decisions),
            "rollback_path": "disable controlled candidates and keep proposals shadow-only",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a visual autonomous-loop report.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--autonomy-level", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_autonomous_loop_report(args.db_path, autonomy_level=args.autonomy_level)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual autonomous loop report {status}")
    return 0 if payload["success"] else 1


def _runtime_checks(regression: dict[str, Any]) -> dict[str, int]:
    counts = regression.get("counts") if isinstance(regression.get("counts"), dict) else {}
    return {
        "duplicate_delivery_count": _int(counts.get("duplicate_deliveries")),
        "missing_source_metadata_count": _int(counts.get("missing_source_metadata")),
        "prompt_mutation_read_count": _int(counts.get("prompt_mutation_reads")),
        "unsafe_activation_count": _int(counts.get("unsafe_activations")),
    }


def _failures(
    regression: dict[str, Any],
    rollout_decisions: list[dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    if regression.get("success") is not True:
        failures.append("regression_failed")
    if any(decision.get("reason") == "prompt_mutation_detected" for decision in rollout_decisions):
        failures.append("prompt_mutation_detected")
    return failures


def _remaining_human_inputs(rollout_decisions: list[dict[str, Any]]) -> list[str]:
    if any(decision.get("allowed") is True for decision in rollout_decisions):
        return []
    reasons = {
        reason
        for decision in rollout_decisions
        for reason in decision.get("reasons", [])
        if str(reason).startswith("insufficient_") or reason == "autonomy_level_below_controlled_threshold"
    }
    return sorted(reasons)


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
