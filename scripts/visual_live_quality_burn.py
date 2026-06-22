from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hermes_constants import get_hermes_home
from scripts.visual_live_provider_e2e import DEFAULT_E2E_CASES
from scripts.visual_live_provider_e2e import build_visual_live_provider_e2e_suite_report


DEFAULT_MAX_CASES = 2
DEFAULT_CASE_TIMEOUT_SECONDS = 240.0


def build_visual_live_quality_burn_report(
    *,
    mode: str = "live",
    output_dir: str | Path | None = None,
    work_dir: str | Path | None = None,
    max_cases: int = DEFAULT_MAX_CASES,
    case_timeout_seconds: float | int | None = None,
    suite_report: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = _normalise_now(now)
    mode = _normalise_mode(mode)
    output_dir = (
        Path(output_dir)
        if output_dir is not None
        else get_hermes_home() / "visual" / "live_quality_burn"
    )
    selected_cases = _selected_cases(max_cases)
    timeout_seconds = _float_timeout(case_timeout_seconds)
    suite = suite_report if isinstance(suite_report, dict) else build_visual_live_provider_e2e_suite_report(
        mode=mode,
        work_dir=work_dir,
        cases=selected_cases,
        case_timeout_seconds=timeout_seconds,
    )
    summary = _summary(suite)
    next_actions = _next_actions(suite, summary)
    report = {
        "success": suite.get("success") is True,
        "run_id": _run_id(now),
        "generated_at": now.isoformat(),
        "mode": mode,
        "burn_budget": {
            "max_cases": _clamp_max_cases(max_cases),
            "case_timeout_seconds": timeout_seconds,
            "case_count": len(selected_cases),
        },
        "summary": summary,
        "next_actions": next_actions,
        "suite": suite,
        "failures": list(suite.get("failures") or []),
        "self_review": {
            "reduces_human_intervention": bool(next_actions),
            "human_feedback_required": not bool(next_actions),
            "privacy_safe": True,
            "provider_and_aesthetic_tracks_separated": True,
        },
    }
    _write_report(output_dir, report)
    return report


def _selected_cases(max_cases: int) -> list[dict[str, Any]]:
    limit = _clamp_max_cases(max_cases)
    return [dict(case) for case in DEFAULT_E2E_CASES[:limit]]


def _clamp_max_cases(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_MAX_CASES
    return max(1, min(len(DEFAULT_E2E_CASES), parsed))


def _float_timeout(value: float | int | None) -> float:
    if value is None:
        return DEFAULT_CASE_TIMEOUT_SECONDS
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CASE_TIMEOUT_SECONDS
    return max(1.0, parsed)


def _summary(suite: dict[str, Any]) -> dict[str, Any]:
    cases = suite.get("cases") if isinstance(suite.get("cases"), list) else []
    quality_scores = _case_quality_scores(cases)
    quality_issues = _quality_issues(cases)
    preference_dimension_failures = _preference_dimension_failures(cases)
    video_missing_after_image_case_ids = _video_missing_after_image_case_ids(cases)
    video_source_summary = _image_first_video_source_summary(cases)
    failed_cases = [
        str(case.get("case_id") or "")
        for case in cases
        if isinstance(case, dict) and case.get("success") is not True
    ]
    recovery = suite.get("recovery_summary") if isinstance(suite.get("recovery_summary"), dict) else {}
    repair = suite.get("quality_repair_summary") if isinstance(suite.get("quality_repair_summary"), dict) else {}
    quality_contract = (
        suite.get("quality_contract_summary")
        if isinstance(suite.get("quality_contract_summary"), dict)
        else {}
    )
    quality_focus = (
        suite.get("quality_focus_summary")
        if isinstance(suite.get("quality_focus_summary"), dict)
        else {}
    )
    return {
        "case_count": _int(suite.get("case_count"), default=len(cases)),
        "failed_case_count": len([case_id for case_id in failed_cases if case_id]),
        "failed_case_ids": [case_id for case_id in failed_cases if case_id],
        "min_quality_score": min(quality_scores) if quality_scores else None,
        "quality_issue_count": len(quality_issues),
        "quality_issues": quality_issues,
        "preference_dimension_failure_count": len(preference_dimension_failures),
        "preference_dimension_failures": preference_dimension_failures,
        "image_first_video_source_case_count": video_source_summary["case_count"],
        "image_first_video_source_covered_count": video_source_summary["covered_count"],
        "image_first_video_source_failure_count": video_source_summary["failure_count"],
        "image_first_video_source_failure_case_ids": video_source_summary["failure_case_ids"],
        "video_missing_after_image_count": len(video_missing_after_image_case_ids),
        "video_missing_after_image_case_ids": video_missing_after_image_case_ids,
        "provider_failure_count": _int(recovery.get("provider_failure_count")),
        "negotiation_success_case_count": _int(recovery.get("negotiation_success_case_count")),
        "quality_repair_attempt_count": _int(repair.get("attempt_count")),
        "quality_repair_success_count": _int(repair.get("success_count")),
        "quality_repair_selected_count": _int(repair.get("selected_repair_count")),
        "core_quality_contract_case_count": _int(quality_contract.get("contract_case_count")),
        "core_quality_contract_case_ids": _list(quality_contract.get("contract_case_ids")),
        "core_quality_dimensions": _list(quality_contract.get("core_quality_dimensions")),
        "core_quality_dimensions_missing": _list(quality_contract.get("core_quality_dimensions_missing")),
        "core_quality_coverage_ready": quality_contract.get("core_quality_coverage_ready")
        if "core_quality_coverage_ready" in quality_contract
        else None,
        "core_quality_required_dimensions": _list(quality_contract.get("required_dimensions")),
        "quality_focus_outcome_count": _int(quality_focus.get("outcome_count")),
        "quality_focus_success_count": _int(quality_focus.get("success_count")),
        "quality_focus_failure_count": _int(quality_focus.get("failure_count")),
        "quality_focus_successes": _list(quality_focus.get("successful_focuses")),
        "quality_focus_failures": _list(quality_focus.get("failed_focuses")),
        "quality_focus_failed_case_ids": _quality_focus_failed_case_ids(quality_focus),
    }


def _case_quality_scores(cases: list[Any]) -> list[float]:
    scores: list[float] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
        gate = evidence.get("quality_gate") if isinstance(evidence.get("quality_gate"), dict) else {}
        score = _float_or_none(gate.get("min_score"))
        if score is not None:
            scores.append(score)
    return scores


def _quality_issues(cases: list[Any]) -> list[str]:
    issues: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
        gate = evidence.get("quality_gate") if isinstance(evidence.get("quality_gate"), dict) else {}
        for issue in gate.get("quality_issues") or []:
            if isinstance(issue, str) and issue and issue not in issues:
                issues.append(issue)
    return issues


def _preference_dimension_failures(cases: list[Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for case in cases:
        if not isinstance(case, dict):
            continue
        evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
        gate = evidence.get("quality_gate") if isinstance(evidence.get("quality_gate"), dict) else {}
        raw_failures = gate.get("preference_dimension_failures")
        if not isinstance(raw_failures, list):
            continue
        for failure in raw_failures:
            if not isinstance(failure, dict):
                continue
            dimension = str(failure.get("dimension") or "").strip()
            issue = str(failure.get("issue") or "").strip()
            score = _float_or_none(failure.get("score"))
            if not dimension:
                continue
            key = (dimension, issue)
            if key in seen:
                continue
            seen.add(key)
            entry: dict[str, Any] = {
                "dimension": dimension,
                "issue": issue,
            }
            if score is not None:
                entry["score"] = round(max(0.0, min(1.0, score)), 4)
            failures.append(entry)
    return failures


def _video_missing_after_image_case_ids(cases: list[Any]) -> list[str]:
    case_ids: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
        if _int(evidence.get("image_count")) < 1 or _int(evidence.get("video_count")) > 0:
            continue
        if not _case_requires_video(case, evidence):
            continue
        case_id = str(case.get("case_id") or "").strip()
        if case_id:
            case_ids.append(case_id)
    return case_ids


def _case_requires_video(case: dict[str, Any], evidence: dict[str, Any]) -> bool:
    if evidence.get("require_video") is True or case.get("require_video") is True:
        return True
    failures = case.get("failures")
    if not isinstance(failures, list):
        failures = []
    return any(str(failure) == "missing_video_output" for failure in failures)


def _image_first_video_source_summary(cases: list[Any]) -> dict[str, Any]:
    case_count = 0
    covered_count = 0
    failure_case_ids: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
        video_source = evidence.get("video_source") if isinstance(evidence.get("video_source"), dict) else {}
        if not video_source:
            continue
        case_count += 1
        if video_source.get("uses_ranked_selected_image") is True:
            covered_count += 1
            continue
        case_id = str(case.get("case_id") or "").strip()
        if case_id:
            failure_case_ids.append(case_id)
    return {
        "case_count": case_count,
        "covered_count": covered_count,
        "failure_count": len(failure_case_ids),
        "failure_case_ids": failure_case_ids,
    }


def _quality_focus_failed_case_ids(summary: dict[str, Any]) -> list[str]:
    outcomes = summary.get("outcomes")
    if not isinstance(outcomes, list):
        return []
    case_ids: list[str] = []
    for outcome in outcomes:
        if not isinstance(outcome, dict) or outcome.get("success") is True:
            continue
        case_id = str(outcome.get("case_id") or "").strip()
        if case_id and case_id not in case_ids:
            case_ids.append(case_id)
    return case_ids


def _next_actions(suite: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    failures = {str(failure) for failure in suite.get("failures") or []}
    if summary.get("quality_issue_count", 0) > 0 or any(
        "quality_gate_failed" in failure or "selected_quality_issue_detected" in failure
        for failure in failures
    ):
        evidence_count = max(1, _int(summary.get("quality_issue_count")))
        actions.append(
            _action(
                "increase_candidate_budget",
                "aesthetic",
                "live_quality_burn_quality_gate_failed",
                confidence=0.75,
                evidence_count=evidence_count,
                max_candidate_budget=4,
            )
        )
        actions.append(
            _action(
                "rerank_before_slack",
                "aesthetic",
                "live_quality_burn_low_quality_candidates",
                confidence=0.8,
                evidence_count=evidence_count,
            )
        )
    for failure in summary.get("preference_dimension_failures") or []:
        if not isinstance(failure, dict):
            continue
        dimension = str(failure.get("dimension") or "").strip()
        if not dimension:
            continue
        actions.append(
            _action(
                "repair_low_preference_dimension",
                "aesthetic",
                "live_quality_burn_preference_dimension_low",
                confidence=0.72,
                evidence_count=1,
                dimension=dimension,
                quality_issue=str(failure.get("issue") or "").strip(),
                repair_hint=_repair_hint_for_dimension(dimension),
            )
        )
    quality_focus = suite.get("quality_focus_summary") if isinstance(suite.get("quality_focus_summary"), dict) else {}
    actions.extend(_quality_focus_actions(quality_focus))
    if _int(summary.get("video_missing_after_image_count")) > 0:
        actions.append(
            _action(
                "prefer_image_first_video",
                "provider",
                "live_quality_burn_video_missing_after_image",
                confidence=0.78,
                evidence_count=_int(summary.get("video_missing_after_image_count")),
            )
        )
    if _int(summary.get("image_first_video_source_failure_count")) > 0:
        actions.append(
            _action(
                "prefer_image_first_video",
                "provider",
                "live_quality_burn_video_source_not_ranked_image",
                confidence=0.82,
                evidence_count=_int(summary.get("image_first_video_source_failure_count")),
            )
        )
    recovery = suite.get("recovery_summary") if isinstance(suite.get("recovery_summary"), dict) else {}
    if _int(recovery.get("provider_failure_count")) > 0:
        actions.append(
            _action(
                "safe_reframe_provider_retry",
                "provider",
                "live_quality_burn_provider_failures",
                confidence=0.7,
                evidence_count=_int(recovery.get("provider_failure_count")),
                provider_failure_classes=_int_mapping(recovery.get("provider_failure_classes")),
                provider_error_codes=_int_mapping(recovery.get("provider_error_codes")),
            )
        )
    repair = suite.get("quality_repair_summary") if isinstance(suite.get("quality_repair_summary"), dict) else {}
    actions.extend(_quality_repair_actions(repair))
    if not actions and _high_quality_pass(suite, summary):
        actions.append(
            {
                "type": "prefer_strategy",
                "track": "aesthetic",
                "reason": "live_quality_burn_high_quality_pass",
                "confidence": _float_confidence(summary.get("min_quality_score")),
                "evidence_count": _int(summary.get("case_count")),
                "requires_human_feedback": False,
                "activation_status": "shadow",
                "source": "live_quality_burn",
                "bucket": "live_visual_agent_mode",
                "strategy_signature": "image_first_rank_then_video",
                "candidate_budget": 2,
            }
        )
    return _dedupe_actions(actions)


def _quality_focus_actions(summary: dict[str, Any]) -> list[dict[str, Any]]:
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
        for issue in _list(outcome.get("quality_issues")):
            if issue not in entry["quality_issues"]:
                entry["quality_issues"].append(issue)
        if not entry["dimension"]:
            entry["dimension"] = _dimension_for_focus(focus)
    if not failed_by_focus:
        for focus in _list(summary.get("failed_focuses")):
            failed_by_focus[focus] = {
                "case_ids": [],
                "dimension": _dimension_for_focus(focus),
                "quality_issues": [],
            }

    actions: list[dict[str, Any]] = []
    for focus, details in failed_by_focus.items():
        case_ids = _list(details.get("case_ids"))
        evidence_count = max(1, len(case_ids))
        if focus == "image_first_video":
            actions.append(
                _action(
                    "prefer_image_first_video",
                    "provider",
                    "live_quality_burn_quality_focus_image_first_video_failed",
                    confidence=0.82,
                    evidence_count=evidence_count,
                    focus=focus,
                    strategy_operator="image_first_rank_then_video",
                    case_ids=case_ids,
                )
            )
            continue
        dimension = str(details.get("dimension") or _dimension_for_focus(focus)).strip()
        actions.append(
            _action(
                "apply_quality_focus_operator",
                "aesthetic",
                "live_quality_burn_quality_focus_failed",
                confidence=0.76,
                evidence_count=evidence_count,
                focus=focus,
                dimension=dimension,
                strategy_operator=_strategy_operator_for_focus(focus),
                repair_hint=_repair_hint_for_dimension(dimension),
                case_ids=case_ids,
                quality_issues=_list(details.get("quality_issues")),
            )
        )
    return actions


def _high_quality_pass(suite: dict[str, Any], summary: dict[str, Any]) -> bool:
    if suite.get("success") is not True:
        return False
    min_quality = _float_or_none(summary.get("min_quality_score"))
    return (
        min_quality is not None
        and min_quality >= 0.75
        and _int(summary.get("quality_issue_count")) == 0
        and _int(summary.get("failed_case_count")) == 0
    )


def _quality_repair_actions(repair: dict[str, Any]) -> list[dict[str, Any]]:
    by_modality = repair.get("by_modality") if isinstance(repair.get("by_modality"), dict) else {}
    actions: list[dict[str, Any]] = []
    for modality, modality_summary in by_modality.items():
        if not isinstance(modality, str) or not isinstance(modality_summary, dict):
            continue
        attempt_count = _int(modality_summary.get("attempt_count"))
        success_count = _int(modality_summary.get("success_count"))
        selected_count = _int(modality_summary.get("selected_repair_count"))
        if attempt_count <= 0 or success_count <= 0 or selected_count <= 0:
            continue
        success_rate = _rate(success_count, attempt_count)
        selected_repair_rate = _rate(selected_count, attempt_count)
        actions.append(
            _action(
                "prefer_quality_repair_retry",
                "repair",
                f"live_quality_burn_{modality}_repair_succeeded",
                confidence=min(0.9, 0.55 + success_rate * 0.35),
                evidence_count=attempt_count,
                source="live_quality_burn",
                modality=modality,
                success_rate=success_rate,
                selected_repair_rate=selected_repair_rate,
            )
        )
    return actions


def _repair_hint_for_dimension(dimension: str) -> str:
    return {
        "subject_beauty": "improve_subject_beauty",
        "face_naturalness": "improve_face_naturalness",
        "glamour_impact": "increase_glamour_impact",
        "fashion_material_quality": "improve_fashion_material_quality",
        "pose_composition": "improve_pose_composition",
        "motion_quality": "improve_motion_quality",
    }.get(dimension, f"improve_{dimension}")


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


def _action(
    action_type: str,
    track: str,
    reason: str,
    *,
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
        "source": "live_quality_burn",
        **extra,
    }


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for action in actions:
        key = (
            str(action.get("type") or ""),
            str(action.get("source") or ""),
            str(action.get("modality") or ""),
            str(action.get("focus") or ""),
            str(action.get("dimension") or ""),
            str(action.get("strategy_operator") or action.get("strategy_signature") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _normalise_mode(mode: str) -> str:
    value = str(mode or "live").strip().lower()
    return value if value in {"live", "fixture"} else "live"


def _normalise_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _run_id(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _write_report(output_dir: Path, report: dict[str, Any]) -> None:
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    _write_json(runs_dir / f"{report['run_id']}.json", report)
    _write_json(output_dir / "latest.json", report)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    mapping: dict[str, int] = {}
    for key, count in value.items():
        text = str(key or "").strip()
        parsed = _int(count)
        if text and parsed > 0:
            mapping[text] = parsed
    return mapping


def _list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    strings: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in strings:
            strings.append(text)
    return strings


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_confidence(value: Any) -> float:
    parsed = _float_or_none(value)
    if parsed is None:
        return 0.0
    return round(max(0.0, min(1.0, parsed)), 4)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run visual live quality burn and produce autonomous next actions.")
    parser.add_argument("--mode", choices=["live", "fixture"], default="live")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--max-cases", type=int, default=DEFAULT_MAX_CASES)
    parser.add_argument("--case-timeout-seconds", type=float, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_live_quality_burn_report(
        mode=args.mode,
        output_dir=args.output_dir,
        work_dir=args.work_dir,
        max_cases=args.max_cases,
        case_timeout_seconds=args.case_timeout_seconds,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual live quality burn {status} run_id={payload['run_id']}")
    if args.allow_failures:
        return 0
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
