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
from agent.visual.action_dedupe import dedupe_actions as _dedupe_actions
from agent.visual.operator_setup import operator_setup_actions_from_actions as _operator_setup_actions_from_actions
from agent.visual.operator_setup import operator_setup_actions_from_video_fallback_diagnostics as _operator_setup_actions_from_video_fallback_diagnostics
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
    include_video_repair_probe: bool = False,
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
        include_video_repair_probe=include_video_repair_probe,
    )
    summary = _summary(suite)
    next_actions = _next_actions(suite, summary)
    operator_setup_actions = _operator_setup_actions_from_actions(next_actions)
    burn_budget = {
        "max_cases": _clamp_max_cases(max_cases),
        "case_timeout_seconds": timeout_seconds,
        "case_count": len(selected_cases),
    }
    if include_video_repair_probe:
        burn_budget["include_video_repair_probe"] = True
    report = {
        "success": suite.get("success") is True,
        "run_id": _run_id(now),
        "generated_at": now.isoformat(),
        "mode": mode,
        "burn_budget": burn_budget,
        "summary": summary,
        "next_actions": next_actions,
        "suite": suite,
        "failures": list(suite.get("failures") or []),
        "self_review": {
            "reduces_human_intervention": bool(next_actions) and not operator_setup_actions,
            "human_feedback_required": not bool(next_actions),
            "requires_operator_setup": bool(operator_setup_actions),
            "operator_setup_actions": operator_setup_actions,
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
    promotion_cases = [case for case in cases if not _diagnostic_case(case)]
    quality_scores = _case_quality_scores(cases)
    promotion_quality_scores = _case_quality_scores(promotion_cases)
    quality_issues = _quality_issues(cases)
    promotion_quality_issues = _quality_issues(promotion_cases)
    preference_dimension_failures = _preference_dimension_failures(cases)
    promotion_preference_dimension_failures = _preference_dimension_failures(promotion_cases)
    video_missing_after_image_case_ids = _video_missing_after_image_case_ids(cases)
    video_source_summary = _image_first_video_source_summary(cases)
    failed_cases = [
        str(case.get("case_id") or "")
        for case in cases
        if isinstance(case, dict) and case.get("success") is not True
    ]
    promotion_failed_cases = [
        str(case.get("case_id") or "")
        for case in promotion_cases
        if isinstance(case, dict) and case.get("success") is not True
    ]
    recovery = suite.get("recovery_summary") if isinstance(suite.get("recovery_summary"), dict) else {}
    repair = suite.get("quality_repair_summary") if isinstance(suite.get("quality_repair_summary"), dict) else {}
    repair_effectiveness = _repair_effectiveness_summary(cases)
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
        "promotion_case_count": len([case for case in promotion_cases if isinstance(case, dict)]),
        "failed_case_count": len([case_id for case_id in failed_cases if case_id]),
        "failed_case_ids": [case_id for case_id in failed_cases if case_id],
        "promotion_failed_case_count": len(
            [case_id for case_id in promotion_failed_cases if case_id]
        ),
        "promotion_failed_case_ids": [
            case_id for case_id in promotion_failed_cases if case_id
        ],
        "min_quality_score": min(quality_scores) if quality_scores else None,
        "promotion_min_quality_score": min(promotion_quality_scores)
        if promotion_quality_scores
        else None,
        "quality_issue_count": len(quality_issues),
        "quality_issues": quality_issues,
        "promotion_quality_issue_count": len(promotion_quality_issues),
        "promotion_quality_issues": promotion_quality_issues,
        "preference_dimension_failure_count": len(preference_dimension_failures),
        "preference_dimension_failures": preference_dimension_failures,
        "promotion_preference_dimension_failure_count": len(
            promotion_preference_dimension_failures
        ),
        "promotion_preference_dimension_failures": promotion_preference_dimension_failures,
        "image_first_video_source_case_count": video_source_summary["case_count"],
        "image_first_video_source_covered_count": video_source_summary["covered_count"],
        "image_first_video_source_failure_count": video_source_summary["failure_count"],
        "image_first_video_source_failure_case_ids": video_source_summary["failure_case_ids"],
        "image_first_video_source_not_single_count": video_source_summary["not_single_count"],
        "image_first_video_source_not_single_case_ids": video_source_summary["not_single_case_ids"],
        "video_missing_after_image_count": len(video_missing_after_image_case_ids),
        "video_missing_after_image_case_ids": video_missing_after_image_case_ids,
        "provider_failure_count": _int(recovery.get("provider_failure_count")),
        "negotiation_success_case_count": _int(recovery.get("negotiation_success_case_count")),
        "quality_repair_attempt_count": _int(repair.get("attempt_count")),
        "quality_repair_success_count": _int(repair.get("success_count")),
        "quality_repair_selected_count": _int(repair.get("selected_repair_count")),
        "quality_repair_effectiveness_attempt_count": repair_effectiveness["attempt_count"],
        "quality_repair_effectiveness_improved_count": repair_effectiveness["improved_count"],
        "quality_repair_effectiveness_regressed_count": repair_effectiveness["regressed_count"],
        "quality_repair_effectiveness_avg_score_delta": repair_effectiveness["avg_score_delta"],
        "quality_repair_effectiveness_resolved_issues": repair_effectiveness["resolved_quality_issues"],
        "quality_repair_effectiveness_remaining_issues": repair_effectiveness["remaining_quality_issues"],
        "quality_repair_effectiveness_by_modality": repair_effectiveness["by_modality"],
        "quality_repair_effectiveness_outcomes": repair_effectiveness["outcomes"],
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


def _diagnostic_case(case: Any) -> bool:
    if not isinstance(case, dict):
        return False
    return str(case.get("case_id") or "") in {"video_quality_repair"}


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
    not_single_case_ids: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
        video_source = evidence.get("video_source") if isinstance(evidence.get("video_source"), dict) else {}
        if not video_source or not _has_materialized_video_source(video_source):
            continue
        case_count += 1
        case_id = str(case.get("case_id") or "").strip()
        source_is_single = video_source.get("single_video_source_image") is not False
        if video_source.get("uses_ranked_selected_image") is True and source_is_single:
            covered_count += 1
            continue
        if case_id:
            failure_case_ids.append(case_id)
            if source_is_single is False:
                not_single_case_ids.append(case_id)
    return {
        "case_count": case_count,
        "covered_count": covered_count,
        "failure_count": len(failure_case_ids),
        "failure_case_ids": failure_case_ids,
        "not_single_count": len(not_single_case_ids),
        "not_single_case_ids": not_single_case_ids,
    }


def _has_materialized_video_source(video_source: dict[str, Any]) -> bool:
    if _int(video_source.get("video_source_image_count")) > 0:
        return True
    return bool(
        str(video_source.get("source_image_artifact_id") or "").strip()
        or str(video_source.get("ranked_selected_image_artifact_id") or "").strip()
    )


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


def _repair_effectiveness_summary(cases: list[Any]) -> dict[str, Any]:
    outcomes: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
        effectiveness = (
            evidence.get("quality_repair_effectiveness")
            if isinstance(evidence.get("quality_repair_effectiveness"), dict)
            else {}
        )
        raw_outcomes = effectiveness.get("outcomes")
        if isinstance(raw_outcomes, list):
            outcomes.extend([dict(outcome) for outcome in raw_outcomes if isinstance(outcome, dict)])
            continue
        if _int(effectiveness.get("attempt_count")) <= 0:
            continue
        outcomes.append(
            {
                "modality": "unknown",
                "score_delta": _float_or_none(effectiveness.get("avg_score_delta")) or 0.0,
                "resolved_quality_issues": _list(effectiveness.get("resolved_quality_issues")),
                "remaining_quality_issues": _list(effectiveness.get("remaining_quality_issues")),
                "improved": _int(effectiveness.get("improved_count")) > 0,
                "regressed": _int(effectiveness.get("regressed_count")) > 0,
            }
        )
    return _repair_effectiveness_from_outcomes(outcomes)


def _repair_effectiveness_from_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    if not outcomes:
        return {
            "attempt_count": 0,
            "improved_count": 0,
            "regressed_count": 0,
            "avg_score_delta": 0.0,
            "resolved_quality_issues": [],
            "remaining_quality_issues": [],
            "by_modality": {},
            "outcomes": [],
        }
    by_modality: dict[str, list[dict[str, Any]]] = {}
    for outcome in outcomes:
        modality = str(outcome.get("modality") or "unknown").strip() or "unknown"
        by_modality.setdefault(modality, []).append(outcome)
    return {
        "attempt_count": len(outcomes),
        "improved_count": sum(1 for outcome in outcomes if outcome.get("improved") is True),
        "regressed_count": sum(1 for outcome in outcomes if outcome.get("regressed") is True),
        "avg_score_delta": _average_score_delta(outcomes),
        "resolved_quality_issues": _unique_outcome_issues(outcomes, "resolved_quality_issues"),
        "remaining_quality_issues": _unique_outcome_issues(outcomes, "remaining_quality_issues"),
        "by_modality": {
            modality: {
                "attempt_count": len(items),
                "improved_count": sum(1 for item in items if item.get("improved") is True),
                "regressed_count": sum(1 for item in items if item.get("regressed") is True),
                "avg_score_delta": _average_score_delta(items),
                "resolved_quality_issues": _unique_outcome_issues(items, "resolved_quality_issues"),
                "remaining_quality_issues": _unique_outcome_issues(items, "remaining_quality_issues"),
            }
            for modality, items in by_modality.items()
        },
        "outcomes": outcomes,
    }


def _average_score_delta(outcomes: list[dict[str, Any]]) -> float:
    if not outcomes:
        return 0.0
    return round(
        sum(_float_or_none(outcome.get("score_delta")) or 0.0 for outcome in outcomes)
        / len(outcomes),
        4,
    )


def _unique_outcome_issues(outcomes: list[dict[str, Any]], key: str) -> list[str]:
    issues: list[str] = []
    for outcome in outcomes:
        for issue in _list(outcome.get(key)):
            if issue not in issues:
                issues.append(issue)
    return issues


def _next_actions(suite: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    failures = {str(failure) for failure in suite.get("failures") or []}
    recovery = suite.get("recovery_summary") if isinstance(suite.get("recovery_summary"), dict) else {}
    provider_account_blocked_without_quality_evidence = _provider_account_blocked_without_quality_evidence(
        summary,
        recovery,
    )
    promotion_failures = {
        failure for failure in failures if not failure.startswith("video_quality_repair:")
    }
    promotion_quality_issue_count = _int(
        summary.get("promotion_quality_issue_count"),
        default=_int(summary.get("quality_issue_count")),
    )
    has_promotion_quality_evidence = _has_promotion_quality_evidence(
        summary,
        promotion_quality_issue_count=promotion_quality_issue_count,
    )
    if (
        has_promotion_quality_evidence
        and not provider_account_blocked_without_quality_evidence
        and (
        promotion_quality_issue_count > 0
        or any(
            "quality_gate_failed" in failure or "selected_quality_issue_detected" in failure
            for failure in promotion_failures
        )
        )
    ):
        evidence_count = max(1, promotion_quality_issue_count)
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
    preference_dimension_failures = (
        summary.get("promotion_preference_dimension_failures")
        if isinstance(summary.get("promotion_preference_dimension_failures"), list)
        else summary.get("preference_dimension_failures")
    )
    for failure in preference_dimension_failures or []:
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
    if (
        _int(summary.get("video_missing_after_image_count")) > 0
        and not _provider_failure_explains_missing_video(recovery)
    ):
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
    if _int(summary.get("image_first_video_source_not_single_count")) > 0:
        actions.append(
            _action(
                "prefer_image_first_video",
                "provider",
                "live_quality_burn_video_source_not_single_image",
                confidence=0.84,
                evidence_count=_int(summary.get("image_first_video_source_not_single_count")),
            )
        )
        actions.append(
            _action(
                "enforce_single_video_source_image",
                "provider",
                "live_quality_burn_video_source_not_single_image",
                confidence=0.86,
                evidence_count=_int(summary.get("image_first_video_source_not_single_count")),
                modality="video",
                quality_issue="source_frame_grid",
                repair_hint="use_single_ranked_selected_image",
            )
        )
    video_aspect_mismatch_count = _video_aspect_mismatch_count(suite)
    if video_aspect_mismatch_count > 0:
        actions.append(
            _action(
                "enforce_video_source_aspect_ratio",
                "provider",
                "live_quality_burn_video_aspect_ratio_mismatch",
                confidence=0.86,
                evidence_count=video_aspect_mismatch_count,
                modality="video",
                quality_issue="aspect_integrity_bad",
                repair_hint="preserve_source_aspect_ratio",
            )
        )
    actions.extend(_provider_failure_actions(recovery))
    repair = suite.get("quality_repair_summary") if isinstance(suite.get("quality_repair_summary"), dict) else {}
    actions.extend(_quality_repair_actions(repair, summary=summary))
    if _high_quality_pass(suite, summary) and _strategy_promotion_actions_allowed(actions, suite):
        actions.append(
            {
                "type": "prefer_strategy",
                "track": "aesthetic",
                "reason": "live_quality_burn_high_quality_pass",
                "confidence": _float_confidence(
                    summary.get("promotion_min_quality_score")
                    if summary.get("promotion_min_quality_score") is not None
                    else summary.get("min_quality_score")
                ),
                "evidence_count": _int(
                    summary.get("promotion_case_count"),
                    default=_int(summary.get("case_count")),
                ),
                "requires_human_feedback": False,
                "activation_status": "shadow",
                "source": "live_quality_burn",
                "bucket": "live_visual_agent_mode",
                "strategy_signature": "image_first_rank_then_video",
                "candidate_budget": 2,
            }
        )
    return _dedupe_actions(actions)


def _provider_failure_explains_missing_video(recovery: dict[str, Any]) -> bool:
    return _int(recovery.get("provider_failure_count")) > 0


def _has_promotion_quality_evidence(
    summary: dict[str, Any],
    *,
    promotion_quality_issue_count: int,
) -> bool:
    if promotion_quality_issue_count > 0:
        return True
    preference_failures = (
        summary.get("promotion_preference_dimension_failures")
        if isinstance(summary.get("promotion_preference_dimension_failures"), list)
        else summary.get("preference_dimension_failures")
    )
    if isinstance(preference_failures, list) and preference_failures:
        return True
    return _float_or_none(summary.get("promotion_min_quality_score")) is not None


def _video_aspect_mismatch_count(suite: dict[str, Any]) -> int:
    count = 0
    for case in suite.get("cases") or []:
        if not isinstance(case, dict):
            continue
        failures = [str(failure) for failure in case.get("failures") or []]
        evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
        video_media_quality = (
            evidence.get("video_media_quality")
            if isinstance(evidence.get("video_media_quality"), dict)
            else {}
        )
        if _has_video_aspect_mismatch_failure(failures) or _has_video_aspect_mismatch_evidence(
            video_media_quality
        ):
            count += 1
    if count:
        return count
    return sum(
        1
        for failure in suite.get("failures") or []
        if "video_aspect_ratio_mismatch" in str(failure)
    )


def _has_video_aspect_mismatch_failure(failures: list[str]) -> bool:
    return any("video_aspect_ratio_mismatch" in failure for failure in failures)


def _has_video_aspect_mismatch_evidence(video_media_quality: dict[str, Any]) -> bool:
    videos = video_media_quality.get("videos")
    if not isinstance(videos, list):
        return False
    return any(
        isinstance(video, dict) and video.get("aspect_ratio_matches") is False
        for video in videos
    )


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
        quality_issues = _list(details.get("quality_issues"))
        if _only_missing_preference_dimension_evidence(quality_issues):
            actions.append(
                _action(
                    "require_preference_dimension_evidence",
                    "evaluation",
                    "live_quality_burn_missing_preference_dimension_evidence",
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
                "live_quality_burn_quality_focus_failed",
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


def _only_missing_preference_dimension_evidence(quality_issues: list[str]) -> bool:
    return bool(quality_issues) and all(
        issue.startswith("missing_preference_dimension_evidence:")
        for issue in quality_issues
    )


def _high_quality_pass(suite: dict[str, Any], summary: dict[str, Any]) -> bool:
    if suite.get("success") is not True:
        return False
    min_quality = _float_or_none(summary.get("promotion_min_quality_score"))
    if min_quality is None:
        min_quality = _float_or_none(summary.get("min_quality_score"))
    return (
        min_quality is not None
        and min_quality >= 0.75
        and _int(
            summary.get("promotion_quality_issue_count"),
            default=_int(summary.get("quality_issue_count")),
        )
        == 0
        and _int(
            summary.get("promotion_failed_case_count"),
            default=_int(summary.get("failed_case_count")),
        )
        == 0
    )


def _strategy_promotion_actions_allowed(
    actions: list[dict[str, Any]],
    suite: dict[str, Any],
) -> bool:
    if not actions:
        return True
    if not all(str(action.get("track") or "") == "repair" for action in actions):
        return False
    cases = suite.get("cases") if isinstance(suite.get("cases"), list) else []
    return any(_diagnostic_case(case) for case in cases)


def _provider_failure_actions(recovery: dict[str, Any]) -> list[dict[str, Any]]:
    provider_failure_count = _int(recovery.get("provider_failure_count"))
    if provider_failure_count <= 0:
        return []

    provider_failure_classes = _int_mapping(recovery.get("provider_failure_classes"))
    provider_error_codes = _int_mapping(recovery.get("provider_error_codes"))
    actions: list[dict[str, Any]] = []
    quota_count = provider_failure_classes.get("quota_exceeded", 0)
    unavailable_count = provider_failure_classes.get("provider_unavailable", 0)
    if quota_count > 0:
        actions.append(
            _action(
                "resolve_provider_quota_or_switch_provider",
                "provider",
                "live_quality_burn_provider_quota_exceeded",
                confidence=0.95,
                evidence_count=quota_count,
                provider_failure_classes={"quota_exceeded": quota_count},
                provider_error_codes=provider_error_codes,
            )
        )
    if unavailable_count > 0:
        actions.append(
            _action(
                "check_provider_connectivity_or_retry",
                "provider",
                "live_quality_burn_provider_unavailable",
                confidence=0.88,
                evidence_count=unavailable_count,
                provider_failure_classes={"provider_unavailable": unavailable_count},
                provider_error_codes=provider_error_codes,
            )
        )
    no_video_fallback_count = _int(recovery.get("no_video_fallback_available_count"))
    if no_video_fallback_count > 0:
        video_fallback_diagnostics = _dict_list(recovery.get("video_fallback_diagnostics"))
        operator_setup_actions = _operator_setup_actions_from_video_fallback_diagnostics(
            video_fallback_diagnostics
        )
        actions.append(
            _action(
                "configure_video_fallback_provider",
                "provider",
                "live_quality_burn_no_video_fallback_available",
                confidence=0.9,
                evidence_count=no_video_fallback_count,
                provider_failure_classes=provider_failure_classes,
                provider_error_codes=provider_error_codes,
                **(
                    {"video_fallback_diagnostics": video_fallback_diagnostics}
                    if video_fallback_diagnostics
                    else {}
                ),
                **(
                    {
                        "requires_operator_setup": True,
                        "operator_setup_actions": operator_setup_actions,
                    }
                    if operator_setup_actions
                    else {}
                ),
            )
        )

    retryable_count = max(0, provider_failure_count - quota_count - unavailable_count)
    if retryable_count > 0:
        retryable_classes = {
            key: count
            for key, count in provider_failure_classes.items()
            if key not in {"quota_exceeded", "provider_unavailable"}
        }
        actions.append(
            _action(
                "safe_reframe_provider_retry",
                "provider",
                "live_quality_burn_provider_failures",
                confidence=0.7,
                evidence_count=retryable_count,
                provider_failure_classes=retryable_classes or provider_failure_classes,
                provider_error_codes=provider_error_codes,
            )
        )
    return actions


def _provider_account_blocked_without_quality_evidence(
    summary: dict[str, Any],
    recovery: dict[str, Any],
) -> bool:
    if _int_mapping(recovery.get("provider_failure_classes")).get("quota_exceeded", 0) <= 0:
        return False
    if _int(
        summary.get("promotion_quality_issue_count"),
        default=_int(summary.get("quality_issue_count")),
    ) > 0:
        return False
    preference_failures = (
        summary.get("promotion_preference_dimension_failures")
        if isinstance(summary.get("promotion_preference_dimension_failures"), list)
        else summary.get("preference_dimension_failures")
    )
    if isinstance(preference_failures, list) and preference_failures:
        return False
    quality_score = _float_or_none(summary.get("promotion_min_quality_score"))
    if quality_score is None:
        quality_score = _float_or_none(summary.get("min_quality_score"))
    return quality_score is None


def _quality_repair_actions(repair: dict[str, Any], *, summary: dict[str, Any]) -> list[dict[str, Any]]:
    by_modality = repair.get("by_modality") if isinstance(repair.get("by_modality"), dict) else {}
    effectiveness_by_modality = (
        summary.get("quality_repair_effectiveness_by_modality")
        if isinstance(summary.get("quality_repair_effectiveness_by_modality"), dict)
        else {}
    )
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
        effectiveness = (
            effectiveness_by_modality.get(modality)
            if isinstance(effectiveness_by_modality.get(modality), dict)
            else {}
        )
        improved_count = _int(effectiveness.get("improved_count"))
        regressed_count = _int(effectiveness.get("regressed_count"))
        avg_score_delta = _float_or_none(effectiveness.get("avg_score_delta"))
        reason = f"live_quality_burn_{modality}_repair_succeeded"
        extra: dict[str, Any] = {}
        if _int(effectiveness.get("attempt_count")) > 0 and improved_count > 0:
            reason = f"live_quality_burn_{modality}_repair_improved_quality"
            extra = {
                "improved_count": improved_count,
                "regressed_count": regressed_count,
                "avg_score_delta": round(avg_score_delta or 0.0, 4),
                "resolved_quality_issues": _list(effectiveness.get("resolved_quality_issues")),
                "remaining_quality_issues": _list(effectiveness.get("remaining_quality_issues")),
            }
        actions.append(
            _action(
                "prefer_quality_repair_retry",
                "repair",
                reason,
                confidence=min(0.9, 0.55 + success_rate * 0.35),
                evidence_count=attempt_count,
                source="live_quality_burn",
                modality=modality,
                success_rate=success_rate,
                selected_repair_rate=selected_repair_rate,
                **extra,
            )
        )
        if _int(effectiveness.get("attempt_count")) > 0 and improved_count <= 0:
            actions.append(
                _action(
                    "escalate_quality_repair_strategy",
                    "repair",
                    f"live_quality_burn_{modality}_repair_not_improving",
                    confidence=0.78,
                    evidence_count=_int(effectiveness.get("attempt_count")),
                    source="live_quality_burn",
                    modality=modality,
                    improved_count=improved_count,
                    regressed_count=regressed_count,
                    avg_score_delta=round(avg_score_delta or 0.0, 4),
                    remaining_quality_issues=_list(effectiveness.get("remaining_quality_issues")),
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


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


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
    parser.add_argument("--include-video-repair-probe", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_live_quality_burn_report(
        mode=args.mode,
        output_dir=args.output_dir,
        work_dir=args.work_dir,
        max_cases=args.max_cases,
        case_timeout_seconds=args.case_timeout_seconds,
        include_video_repair_probe=args.include_video_repair_probe,
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
