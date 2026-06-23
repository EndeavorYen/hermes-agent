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
from agent.visual.action_dedupe import dedupe_actions as _dedupe_actions
from agent.visual.runtime_environment import build_visual_runtime_environment_diagnostic
from scripts.visual_agent_mode_regression_report import build_visual_agent_mode_regression_report
from scripts.visual_autonomous_healthcheck import build_visual_autonomous_healthcheck
from scripts.visual_closed_loop_regression_report import build_visual_closed_loop_regression_report
from scripts.visual_conversation_route_report import build_visual_conversation_route_report
from scripts.visual_feedback_loop_report import build_visual_feedback_loop_report
from scripts.visual_quality_calibration_report import build_quality_calibration_report
from scripts.visual_live_provider_e2e import build_visual_live_provider_e2e_report
from scripts.visual_live_provider_e2e import build_visual_live_provider_e2e_suite_report
from scripts.visual_live_provider_e2e import build_visual_storyboard_execution_report
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
    runtime_environment = build_visual_runtime_environment_diagnostic(
        include_live=include_live,
        include_live_slack_upload=include_live_slack_upload,
    )
    if runtime_environment.get("success") is not True:
        return _runtime_environment_failure_report(runtime_environment)
    agent_mode = build_visual_agent_mode_regression_report()
    closed_loop_regression = build_visual_closed_loop_regression_report()
    conversation_route = build_visual_conversation_route_report()
    fixture_e2e = build_visual_live_provider_e2e_report(mode="fixture", work_dir=work_dir)
    storyboard_execution = build_visual_storyboard_execution_report(mode="fixture", work_dir=work_dir)
    storyboard_contract = {
        "enabled": True,
        "shot_count": 2,
        "candidate_budget_per_shot": 2,
        "source_image_policy": "one_ranked_image_per_shot",
        "composition_target": "single_coherent_video",
        "delivery_policy": "deliver_composed_video_when_available_else_selected_clips",
    }
    fixture_quality_suite_kwargs = {
        "mode": "fixture",
        "work_dir": work_dir,
        "include_video_repair_probe": True,
    }
    if case_timeout_seconds is not None:
        fixture_quality_suite_kwargs["case_timeout_seconds"] = case_timeout_seconds
    fixture_quality_suite = build_visual_live_provider_e2e_suite_report(**fixture_quality_suite_kwargs)
    slack_conversation = build_visual_slack_conversation_e2e_report(mode="fixture", work_dir=work_dir)
    slack_delivery = build_visual_slack_delivery_e2e_report(mode="fixture", work_dir=work_dir)
    storyboard_slack_delivery = build_visual_slack_delivery_e2e_report(
        mode="fixture",
        work_dir=work_dir,
        prompt="請做一支 2 段分鏡的連貫產品影片：霧黑鋼筆放在白紙上，柔和窗光。",
        candidate_budget=2,
        video_budget=1,
        storyboard=storyboard_contract,
    )
    live_slack_delivery = (
        build_visual_slack_delivery_e2e_report(mode="live", work_dir=None, upload=True)
        if include_live_slack_upload
        else {"status": "not_requested"}
    )
    health = build_visual_autonomous_healthcheck(_ledger_path_for_work_dir(work_dir), autonomy_level=2)
    feedback_loop = build_visual_feedback_loop_report(_ledger_path_for_work_dir(work_dir))
    quality_calibration = build_quality_calibration_report(_ledger_path_for_work_dir(work_dir))
    if include_live:
        live_e2e = build_visual_live_provider_e2e_report(mode="live", work_dir=None)
        live_quality_suite_kwargs = {
            "mode": "live",
            "work_dir": None,
            "include_video_repair_probe": True,
        }
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
        live_e2e = {"status": "not_requested"}
        live_quality_suite = {"status": "not_requested"}
        live_quality_burn = {"status": "not_requested"}

    self_improvement = _self_improvement_summary(
        fixture_quality_suite=fixture_quality_suite,
        live_quality_suite=live_quality_suite,
        live_quality_burn=live_quality_burn,
        slack_conversation=slack_conversation,
        feedback_loop=feedback_loop,
    )
    failures = []
    if agent_mode.get("success") is not True:
        failures.append("agent_mode_failed")
    if closed_loop_regression.get("success") is not True:
        failures.append("closed_loop_regression_failed")
    if conversation_route.get("success") is not True:
        failures.append("conversation_route_failed")
    if fixture_e2e.get("success") is not True:
        failures.append("fixture_e2e_failed")
    if storyboard_execution.get("success") is not True:
        failures.append("storyboard_execution_failed")
    if fixture_quality_suite.get("success") is not True:
        failures.append("fixture_quality_suite_failed")
    if slack_conversation.get("success") is not True:
        failures.append("slack_conversation_failed")
    if slack_delivery.get("success") is not True:
        failures.append("slack_delivery_failed")
    if storyboard_slack_delivery.get("success") is not True:
        failures.append("storyboard_slack_delivery_failed")
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
        "runtime_environment": runtime_environment,
        "agent_mode": agent_mode,
        "closed_loop_regression": closed_loop_regression,
        "conversation_route": conversation_route,
        "fixture_e2e": fixture_e2e,
        "storyboard_execution": storyboard_execution,
        "fixture_quality_suite": fixture_quality_suite,
        "slack_conversation": slack_conversation,
        "slack_delivery": slack_delivery,
        "storyboard_slack_delivery": storyboard_slack_delivery,
        "live_slack_delivery": live_slack_delivery,
        "live_e2e": live_e2e,
        "live_quality_suite": live_quality_suite,
        "live_quality_burn": live_quality_burn,
        "health": health,
        "feedback_loop": feedback_loop,
        "self_improvement": self_improvement,
        "quality_calibration": quality_calibration,
    }


def _runtime_environment_failure_report(runtime_environment: dict[str, Any]) -> dict[str, Any]:
    reason = "runtime_environment_missing_dependencies"
    skipped = _skipped_component(reason)
    next_actions = _action_list(runtime_environment.get("next_actions"))
    return {
        "success": False,
        "mode": "runtime_environment_failed",
        "failures": [reason],
        "runtime_environment": runtime_environment,
        "agent_mode": skipped,
        "closed_loop_regression": skipped,
        "conversation_route": skipped,
        "fixture_e2e": skipped,
        "storyboard_execution": skipped,
        "fixture_quality_suite": skipped,
        "slack_conversation": skipped,
        "slack_delivery": skipped,
        "storyboard_slack_delivery": skipped,
        "live_slack_delivery": skipped,
        "live_e2e": skipped,
        "live_quality_suite": skipped,
        "live_quality_burn": skipped,
        "health": skipped,
        "feedback_loop": skipped,
        "self_improvement": {
            "next_actions": next_actions,
            "action_count": len(next_actions),
            "reduces_human_intervention": False,
            "privacy_safe": True,
        },
        "quality_calibration": skipped,
    }


def _skipped_component(reason: str) -> dict[str, str]:
    return {
        "status": "skipped",
        "reason": reason,
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
    feedback_loop: dict[str, Any],
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    actions.extend(_action_list(slack_conversation.get("next_actions")))
    actions.extend(_action_list(feedback_loop.get("next_actions")))
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
    if not isinstance(suite, dict):
        return []
    actions = _quality_suite_focus_actions(
        suite.get("quality_focus_summary")
        if isinstance(suite.get("quality_focus_summary"), dict)
        else {},
        source=source,
    )
    if suite.get("success") is not True:
        return actions
    repair = suite.get("quality_repair_summary")
    repair = repair if isinstance(repair, dict) else {}
    by_modality = repair.get("by_modality")
    by_modality = by_modality if isinstance(by_modality, dict) else {}
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


def _quality_suite_focus_actions(summary: dict[str, Any], *, source: str) -> list[dict[str, Any]]:
    outcomes = summary.get("outcomes") if isinstance(summary.get("outcomes"), list) else []
    failed_by_focus: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        if not isinstance(outcome, dict) or outcome.get("success") is True:
            continue
        focus = str(outcome.get("focus") or "").strip()
        if not focus:
            continue
        entry = failed_by_focus.setdefault(
            focus,
            {
                "case_ids": [],
                "dimension": str(outcome.get("dimension") or "").strip(),
                "quality_issues": [],
            },
        )
        case_id = str(outcome.get("case_id") or "").strip()
        if case_id and case_id not in entry["case_ids"]:
            entry["case_ids"].append(case_id)
        for issue in _string_list(outcome.get("quality_issues")):
            if issue not in entry["quality_issues"]:
                entry["quality_issues"].append(issue)
        if not entry["dimension"]:
            entry["dimension"] = _dimension_for_focus(focus)
    if not failed_by_focus:
        for focus in _string_list(summary.get("failed_focuses")):
            failed_by_focus[focus] = {
                "case_ids": [],
                "dimension": _dimension_for_focus(focus),
                "quality_issues": [],
            }

    actions: list[dict[str, Any]] = []
    for focus, details in failed_by_focus.items():
        case_ids = _string_list(details.get("case_ids"))
        evidence_count = max(1, len(case_ids))
        if focus == "image_first_video":
            actions.append(
                _action(
                    "prefer_image_first_video",
                    "provider",
                    f"{source}_quality_focus_image_first_video_failed",
                    source=source,
                    confidence=0.82,
                    evidence_count=evidence_count,
                    focus=focus,
                    strategy_operator="image_first_rank_then_video",
                    case_ids=case_ids,
                )
            )
            continue
        dimension = str(details.get("dimension") or _dimension_for_focus(focus)).strip()
        quality_issues = _string_list(details.get("quality_issues"))
        if _only_missing_preference_dimension_evidence(quality_issues):
            actions.append(
                _action(
                    "require_preference_dimension_evidence",
                    "evaluation",
                    f"{source}_missing_preference_dimension_evidence",
                    source=source,
                    confidence=0.84,
                    evidence_count=evidence_count,
                    focus=focus,
                    dimension=dimension,
                    evaluation_operator="inline_vision_preference_dimensions",
                    case_ids=case_ids,
                    quality_issues=quality_issues,
                )
            )
            continue
        actions.append(
            _action(
                "apply_quality_focus_operator",
                "aesthetic",
                f"{source}_quality_focus_failed",
                source=source,
                confidence=0.76,
                evidence_count=evidence_count,
                focus=focus,
                dimension=dimension,
                strategy_operator=_strategy_operator_for_focus(focus),
                repair_hint=_repair_hint_for_dimension(dimension),
                case_ids=case_ids,
                quality_issues=quality_issues,
            )
        )
    return actions


def _action(
    action_type: str,
    track: str,
    reason: str,
    *,
    source: str,
    confidence: float,
    evidence_count: int,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "type": action_type,
        "track": track,
        "reason": reason,
        "confidence": round(confidence, 4),
        "evidence_count": max(0, int(evidence_count)),
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": source,
        **extra,
    }


def _dimension_for_focus(focus: str) -> str:
    return {
        "adult_fashion_portrait": "subject_beauty",
        "natural_face": "face_naturalness",
        "legwear_material": "fashion_material_quality",
        "long_leg_composition": "pose_composition",
        "tasteful_glamour": "glamour_impact",
    }.get(focus, "")


def _strategy_operator_for_focus(focus: str) -> str:
    return {
        "adult_fashion_portrait": "refine_adult_fashion_portrait",
        "natural_face": "refine_face_naturalness",
        "legwear_material": "refine_legwear_material",
        "long_leg_composition": "refine_long_leg_composition",
        "tasteful_glamour": "refine_tasteful_glamour",
    }.get(focus, f"refine_{focus}")


def _repair_hint_for_dimension(dimension: str) -> str:
    return {
        "subject_beauty": "improve_subject_beauty",
        "face_naturalness": "improve_face_naturalness",
        "glamour_impact": "increase_glamour_impact",
        "fashion_material_quality": "improve_fashion_material_quality",
        "pose_composition": "improve_pose_composition",
        "motion_quality": "improve_motion_quality",
    }.get(dimension, f"improve_{dimension}")


def _only_missing_preference_dimension_evidence(quality_issues: list[str]) -> bool:
    return bool(quality_issues) and all(
        issue.startswith("missing_preference_dimension_evidence:")
        for issue in quality_issues
    )


def _action_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


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
