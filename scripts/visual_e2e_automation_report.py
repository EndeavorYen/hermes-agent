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
from scripts.visual_conversation_route_report import build_visual_conversation_route_report
from scripts.visual_feedback_loop_report import build_visual_feedback_loop_report
from scripts.visual_quality_calibration_report import build_quality_calibration_report
from scripts.visual_live_provider_e2e import build_visual_live_provider_e2e_report
from scripts.visual_live_provider_e2e import build_visual_live_provider_e2e_suite_report
from scripts.visual_live_quality_burn import build_visual_live_quality_burn_report
from scripts.visual_slack_conversation_e2e import build_visual_slack_conversation_e2e_report
from scripts.visual_slack_delivery_e2e import build_visual_slack_delivery_e2e_report


def build_visual_e2e_automation_report(
    *,
    work_dir: str | Path | None = None,
    include_live: bool = False,
    include_live_slack_upload: bool = False,
    case_timeout_seconds: float | int | None = None,
) -> dict[str, Any]:
    agent_mode = build_visual_agent_mode_regression_report()
    conversation_route = build_visual_conversation_route_report()
    fixture_e2e = build_visual_live_provider_e2e_report(mode="fixture", work_dir=work_dir)
    fixture_quality_suite_kwargs = {"mode": "fixture", "work_dir": work_dir}
    if case_timeout_seconds is not None:
        fixture_quality_suite_kwargs["case_timeout_seconds"] = case_timeout_seconds
    fixture_quality_suite = build_visual_live_provider_e2e_suite_report(**fixture_quality_suite_kwargs)
    slack_conversation = build_visual_slack_conversation_e2e_report(mode="fixture", work_dir=work_dir)
    slack_delivery = build_visual_slack_delivery_e2e_report(mode="fixture", work_dir=work_dir)
    live_slack_delivery = (
        build_visual_slack_delivery_e2e_report(mode="live", work_dir=None, upload=True)
        if include_live_slack_upload
        else {"status": "not_requested"}
    )
    health = build_visual_autonomous_healthcheck(_ledger_path_for_work_dir(work_dir), autonomy_level=2)
    feedback_loop = build_visual_feedback_loop_report(_ledger_path_for_work_dir(work_dir))
    quality_calibration = build_quality_calibration_report(_ledger_path_for_work_dir(work_dir))
    if include_live:
        live_e2e = (
            build_visual_live_provider_e2e_report(mode="live", work_dir=None)
            if live_provider_enabled()
            else {"status": "skipped", "reason": "live_provider_not_enabled"}
        )
        if live_provider_enabled():
            live_quality_suite_kwargs = {"mode": "live", "work_dir": None}
            if case_timeout_seconds is not None:
                live_quality_suite_kwargs["case_timeout_seconds"] = case_timeout_seconds
            live_quality_suite = build_visual_live_provider_e2e_suite_report(**live_quality_suite_kwargs)
            live_quality_burn = build_visual_live_quality_burn_report(
                mode="live",
                work_dir=None,
                case_timeout_seconds=case_timeout_seconds,
                suite_report=live_quality_suite,
            )
        else:
            live_quality_suite = {"status": "skipped", "reason": "live_provider_not_enabled"}
            live_quality_burn = {"status": "skipped", "reason": "live_provider_not_enabled"}
    else:
        live_e2e = {"status": "not_requested"}
        live_quality_suite = {"status": "not_requested"}
        live_quality_burn = {"status": "not_requested"}

    self_improvement = _self_improvement_summary(
        fixture_quality_suite=fixture_quality_suite,
        live_quality_suite=live_quality_suite,
        live_quality_burn=live_quality_burn,
        slack_conversation=slack_conversation,
    )
    failures = []
    if agent_mode.get("success") is not True:
        failures.append("agent_mode_failed")
    if conversation_route.get("success") is not True:
        failures.append("conversation_route_failed")
    if fixture_e2e.get("success") is not True:
        failures.append("fixture_e2e_failed")
    if fixture_quality_suite.get("success") is not True:
        failures.append("fixture_quality_suite_failed")
    if slack_conversation.get("success") is not True:
        failures.append("slack_conversation_failed")
    if slack_delivery.get("success") is not True:
        failures.append("slack_delivery_failed")
    if health.get("success") is not True:
        failures.append("health_failed")
    if feedback_loop.get("success") is not True:
        failures.append("feedback_loop_failed")
    if quality_calibration.get("success") is not True:
        failures.append("quality_calibration_failed")
    if isinstance(live_e2e, dict) and live_e2e.get("success") is False:
        failures.append("live_e2e_failed")
    if isinstance(live_quality_suite, dict) and live_quality_suite.get("success") is False:
        failures.append("live_quality_suite_failed")
    if isinstance(live_slack_delivery, dict) and live_slack_delivery.get("success") is False:
        failures.append("live_slack_delivery_failed")
    return {
        "success": not failures,
        "mode": "fixture+live" if include_live else "fixture",
        "failures": failures,
        "agent_mode": agent_mode,
        "conversation_route": conversation_route,
        "fixture_e2e": fixture_e2e,
        "fixture_quality_suite": fixture_quality_suite,
        "slack_conversation": slack_conversation,
        "slack_delivery": slack_delivery,
        "live_slack_delivery": live_slack_delivery,
        "live_e2e": live_e2e,
        "live_quality_suite": live_quality_suite,
        "live_quality_burn": live_quality_burn,
        "health": health,
        "feedback_loop": feedback_loop,
        "self_improvement": self_improvement,
        "quality_calibration": quality_calibration,
    }


def live_provider_enabled() -> bool:
    return str(os.environ.get("HERMES_VISUAL_LIVE_E2E") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _self_improvement_summary(
    *,
    fixture_quality_suite: dict[str, Any],
    live_quality_suite: dict[str, Any],
    live_quality_burn: dict[str, Any],
    slack_conversation: dict[str, Any],
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    actions.extend(_action_list(slack_conversation.get("next_actions")))
    actions.extend(
        _quality_suite_next_actions(
            fixture_quality_suite,
            source="fixture_quality_suite",
        )
    )
    actions.extend(
        _quality_suite_next_actions(
            live_quality_suite,
            source="live_quality_suite",
        )
    )
    actions.extend(_action_list(live_quality_burn.get("next_actions") if isinstance(live_quality_burn, dict) else []))
    actions = _dedupe_actions(actions)
    return {
        "next_actions": actions,
        "action_count": len(actions),
        "reduces_human_intervention": bool(actions),
        "privacy_safe": True,
    }


def _quality_suite_next_actions(suite: dict[str, Any], *, source: str) -> list[dict[str, Any]]:
    if not isinstance(suite, dict) or suite.get("success") is not True:
        return []
    repair = suite.get("quality_repair_summary")
    repair = repair if isinstance(repair, dict) else {}
    by_modality = repair.get("by_modality")
    by_modality = by_modality if isinstance(by_modality, dict) else {}
    actions: list[dict[str, Any]] = []
    for modality, summary in by_modality.items():
        if not isinstance(modality, str) or not isinstance(summary, dict):
            continue
        attempt_count = _int(summary.get("attempt_count"))
        success_count = _int(summary.get("success_count"))
        selected_count = _int(summary.get("selected_repair_count"))
        if attempt_count <= 0 or success_count <= 0 or selected_count <= 0:
            continue
        success_rate = _rate(success_count, attempt_count)
        selected_repair_rate = _rate(selected_count, attempt_count)
        actions.append(
            {
                "type": "prefer_quality_repair_retry",
                "track": "repair",
                "reason": f"{source}_{modality}_repair_succeeded",
                "confidence": min(0.9, 0.55 + success_rate * 0.35),
                "evidence_count": attempt_count,
                "requires_human_feedback": False,
                "activation_status": "next_run",
                "source": source,
                "modality": modality,
                "success_rate": success_rate,
                "selected_repair_rate": selected_repair_rate,
            }
        )
    return actions


def _action_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for action in actions:
        key = (
            str(action.get("type") or ""),
            str(action.get("source") or ""),
            str(action.get("modality") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run visual E2E automation with fixture-first gating.")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--include-live", action="store_true")
    parser.add_argument("--include-live-slack-upload", action="store_true")
    parser.add_argument("--case-timeout-seconds", type=float, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_e2e_automation_report(
        work_dir=args.work_dir,
        include_live=args.include_live,
        include_live_slack_upload=args.include_live_slack_upload,
        case_timeout_seconds=args.case_timeout_seconds,
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
