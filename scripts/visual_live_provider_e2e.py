from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import sys
import tempfile
import threading
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.provider_failures import classify_visual_provider_failure
from agent.visual.tracking import default_visual_ledger_path


DEFAULT_PROMPT = (
    "Clean product photography of a matte black fountain pen on white paper, "
    "soft window light, minimal desk scene, professional commercial style."
)
CORE_PORTRAIT_QUALITY_DIMENSIONS = [
    "subject_beauty",
    "face_naturalness",
    "glamour_impact",
    "fashion_material_quality",
    "pose_composition",
]
QUALITY_FOCUS_DIMENSIONS = {
    "adult_fashion_portrait": "subject_beauty",
    "natural_face": "face_naturalness",
    "legwear_material": "fashion_material_quality",
    "long_leg_composition": "pose_composition",
    "tasteful_glamour": "glamour_impact",
}
DEFAULT_E2E_CASES = [
    {
        "case_id": "product_photo_video",
        "prompt": DEFAULT_PROMPT,
        "require_video": True,
        "duration": 4,
        "video_budget": 1,
    },
    {
        "case_id": "fashion_portrait_video",
        "prompt": (
            "Create one image and one short video: professional fashion editorial portrait of an adult fashion model in refined black eveningwear "
            "with semi-opaque legwear, beautiful natural face, elegant full-body runway pose, long-leg composition, polished editorial studio lighting."
        ),
        "require_video": True,
        "duration": 4,
        "candidate_budget": 2,
        "video_budget": 1,
        "quality_contract": {
            "required_dimensions": CORE_PORTRAIT_QUALITY_DIMENSIONS,
            "quality_focus": [
                "adult_fashion_portrait",
                "natural_face",
                "legwear_material",
                "long_leg_composition",
                "tasteful_glamour",
                "image_first_video",
            ],
            "requires_image_first_video": True,
        },
    },
]
FIXTURE_VIDEO_REPAIR_CASE = {
    "case_id": "video_quality_repair",
    "prompt": "Create one image and one short video: clean product photography with stable natural motion.",
    "require_video": True,
    "duration": 4,
    "candidate_budget": 1,
    "video_budget": 1,
    "force_video_quality_repair": True,
}
DEFAULT_MIN_QUALITY_SCORE = 0.55
DEFAULT_CASE_TIMEOUT_SECONDS = 240.0
_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def build_visual_live_provider_e2e_report(
    *,
    mode: str = "live",
    work_dir: str | Path | None = None,
    prompt: str = DEFAULT_PROMPT,
    candidate_budget: int | None = None,
    video_budget: int = 1,
    duration: int = 4,
    require_video: bool = True,
    force_video_quality_repair: bool = False,
    storyboard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode = mode.strip().lower()
    if mode not in {"live", "fixture"}:
        return _failure_result(
            mode,
            ["unsupported_mode"],
            payload=None,
            provider_checks={},
            evidence={},
        )
    provider_checks = _provider_checks(require_video=require_video)
    if mode == "live" and not _providers_available(provider_checks):
        failures = [
            f"provider_unavailable:{kind}"
            for kind, available in provider_checks.items()
            if not available
        ]
        return _failure_result(
            mode,
            failures,
            payload=None,
            provider_checks=provider_checks,
            evidence={},
        )

    with _hermes_home_context(_hermes_home_for_mode(mode=mode, work_dir=work_dir)):
        with _fixture_provider_context(
            mode,
            work_dir,
            force_video_quality_repair=force_video_quality_repair,
            force_storyboard_composition=bool(storyboard),
        ):
            package_args = {
                "prompt": prompt,
                "include_video": require_video,
                "video_budget": video_budget,
                "duration": duration,
                "aspect_ratio": "1:1",
            }
            if candidate_budget is not None:
                package_args["candidate_budget"] = candidate_budget
            if storyboard:
                package_args["include_image"] = False
                package_args["storyboard"] = storyboard
            payload = run_visual_package(package_args)
        evidence = inspect_visual_e2e_evidence(
            payload,
            require_video=require_video,
        )

    failures = _payload_failures(payload, evidence, mode=mode, require_video=require_video)
    return {
        "success": not failures,
        "provider_mode": mode,
        "failures": failures,
        "provider_checks": provider_checks,
        "payload": _safe_payload_summary(payload),
        "evidence": evidence,
    }


def build_visual_storyboard_execution_report(
    *,
    mode: str = "fixture",
    work_dir: str | Path | None = None,
) -> dict[str, Any]:
    storyboard = {
        "enabled": True,
        "shot_count": 2,
        "candidate_budget_per_shot": 2,
        "source_image_policy": "one_ranked_image_per_shot",
        "composition_target": "single_coherent_video",
        "delivery_policy": "deliver_composed_video_when_available_else_selected_clips",
    }
    report = build_visual_live_provider_e2e_report(
        mode=mode,
        work_dir=work_dir,
        prompt="請做一支 2 段分鏡的連貫產品影片：霧黑鋼筆放在白紙上，柔和窗光。",
        candidate_budget=2,
        video_budget=1,
        duration=4,
        require_video=True,
        storyboard=storyboard,
    )
    evidence = report.get("evidence") if isinstance(report.get("evidence"), dict) else {}
    storyboard_evidence = evidence.get("storyboard_execution") if isinstance(evidence.get("storyboard_execution"), dict) else {}
    failures = list(report.get("failures") or [])
    failures.extend(_storyboard_execution_failures(storyboard_evidence))
    return {
        **report,
        "success": not failures,
        "failures": sorted(set(str(item) for item in failures if item)),
    }


def build_visual_live_provider_e2e_suite_report(
    *,
    mode: str = "live",
    work_dir: str | Path | None = None,
    cases: list[dict[str, Any]] | None = None,
    case_timeout_seconds: float | int | None = None,
    include_video_repair_probe: bool | None = None,
) -> dict[str, Any]:
    case_specs = cases or _default_e2e_cases(
        mode,
        include_video_repair_probe=include_video_repair_probe,
    )
    case_reports = []
    failures: list[str] = []
    for case in case_specs:
        case_id = str(case.get("case_id") or f"case_{len(case_reports) + 1}")
        timeout_seconds = _case_timeout_seconds(
            case.get("case_timeout_seconds", case_timeout_seconds)
        )
        try:
            with _case_timeout_alarm(timeout_seconds):
                report = build_visual_live_provider_e2e_report(
                    mode=mode,
                    work_dir=_case_work_dir(work_dir, case_id),
                    prompt=str(case.get("prompt") or DEFAULT_PROMPT),
                    candidate_budget=case.get("candidate_budget"),
                    video_budget=int(case.get("video_budget") or 1),
                    duration=int(case.get("duration") or 4),
                    require_video=case.get("require_video") is not False,
                    force_video_quality_repair=case.get("force_video_quality_repair") is True,
                    storyboard=case.get("storyboard") if isinstance(case.get("storyboard"), dict) else None,
                )
        except VisualE2ECaseTimeout:
            report = _case_timeout_report(mode=mode, timeout_seconds=timeout_seconds)
        case_report = {
            "case_id": case_id,
            "success": report.get("success") is True,
            "failures": list(report.get("failures") or []),
            "payload": report.get("payload"),
            "evidence": report.get("evidence"),
            "quality_contract": _case_quality_contract(case),
        }
        evidence = report.get("evidence") if isinstance(report.get("evidence"), dict) else {}
        case_report["recovery_summary"] = evidence.get("recovery_summary", {})
        case_report["quality_repair_summary"] = evidence.get("quality_repair_summary", {})
        case_reports.append(case_report)
        failures.extend(f"{case_id}:{failure}" for failure in case_report["failures"])
    quality_focus_summary = _suite_quality_focus_summary(case_reports)
    failures.extend(_suite_quality_focus_failures(quality_focus_summary))
    return {
        "success": not failures,
        "provider_mode": mode,
        "case_count": len(case_reports),
        "case_timeout_seconds": _case_timeout_seconds(case_timeout_seconds),
        "failures": failures,
        "recovery_summary": _suite_recovery_summary(case_reports),
        "quality_repair_summary": _suite_quality_repair_summary(case_reports),
        "quality_contract_summary": _suite_quality_contract_summary(case_reports),
        "quality_focus_summary": quality_focus_summary,
        "cases": case_reports,
    }


def run_visual_package(args: dict[str, Any]) -> dict[str, Any]:
    from tools.visual_package_tool import _handle_visual_package_generate

    raw = asyncio.run(_handle_visual_package_generate(args))
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "success": False,
            "error_type": "invalid_json",
            "error": raw[:500],
        }


def _default_e2e_cases(
    mode: str,
    *,
    include_video_repair_probe: bool | None = None,
) -> list[dict[str, Any]]:
    cases = [dict(case) for case in DEFAULT_E2E_CASES]
    mode_text = str(mode or "").strip().lower()
    if include_video_repair_probe is None:
        include_video_repair_probe = mode_text == "fixture"
    if include_video_repair_probe:
        cases.append(dict(FIXTURE_VIDEO_REPAIR_CASE))
    return cases


def _case_quality_contract(case: dict[str, Any]) -> dict[str, Any]:
    contract = case.get("quality_contract")
    if not isinstance(contract, dict):
        return {}
    required_dimensions = _string_list(contract.get("required_dimensions"))
    quality_focus = _string_list(contract.get("quality_focus"))
    result: dict[str, Any] = {}
    if required_dimensions:
        result["required_dimensions"] = required_dimensions
    if quality_focus:
        result["quality_focus"] = quality_focus
    if contract.get("requires_image_first_video") is True:
        result["requires_image_first_video"] = True
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    strings: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in strings:
            strings.append(text)
    return strings


def _suite_quality_contract_summary(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    contract_case_ids: list[str] = []
    required_dimensions: list[str] = []
    image_first_video_case_ids: list[str] = []
    for case in case_reports:
        contract = case.get("quality_contract") if isinstance(case.get("quality_contract"), dict) else {}
        if not contract:
            continue
        case_id = str(case.get("case_id") or "").strip()
        if case_id:
            contract_case_ids.append(case_id)
        for dimension in _string_list(contract.get("required_dimensions")):
            if dimension not in required_dimensions:
                required_dimensions.append(dimension)
        if contract.get("requires_image_first_video") is True and case_id:
            image_first_video_case_ids.append(case_id)
    missing = [
        dimension
        for dimension in CORE_PORTRAIT_QUALITY_DIMENSIONS
        if dimension not in required_dimensions
    ]
    return {
        "contract_case_count": len(contract_case_ids),
        "contract_case_ids": contract_case_ids,
        "required_dimensions": required_dimensions,
        "core_quality_dimensions": list(CORE_PORTRAIT_QUALITY_DIMENSIONS),
        "core_quality_dimensions_missing": missing,
        "core_quality_coverage_ready": not missing,
        "image_first_video_contract_case_ids": image_first_video_case_ids,
    }


def _suite_quality_focus_summary(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [
        outcome
        for case in case_reports
        for outcome in _case_quality_focus_outcomes(case)
    ]
    successful_focuses: list[str] = []
    failed_focuses: list[str] = []
    for outcome in outcomes:
        focus = str(outcome.get("focus") or "")
        if not focus:
            continue
        if outcome.get("success") is True:
            if focus not in successful_focuses:
                successful_focuses.append(focus)
        elif focus not in failed_focuses:
            failed_focuses.append(focus)
    return {
        "outcome_count": len(outcomes),
        "success_count": len([outcome for outcome in outcomes if outcome.get("success") is True]),
        "failure_count": len([outcome for outcome in outcomes if outcome.get("success") is not True]),
        "successful_focuses": successful_focuses,
        "failed_focuses": failed_focuses,
        "outcomes": outcomes,
    }


def _suite_quality_focus_failures(summary: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    outcomes = summary.get("outcomes") if isinstance(summary.get("outcomes"), list) else []
    for outcome in outcomes:
        if not isinstance(outcome, dict) or outcome.get("success") is True:
            continue
        case_id = str(outcome.get("case_id") or "").strip()
        focus = str(outcome.get("focus") or "").strip()
        if case_id and focus:
            failures.append(f"{case_id}:quality_focus_failed:{focus}")
    return failures


def _case_quality_focus_outcomes(case: dict[str, Any]) -> list[dict[str, Any]]:
    contract = case.get("quality_contract") if isinstance(case.get("quality_contract"), dict) else {}
    focuses = _string_list(contract.get("quality_focus"))
    if not focuses:
        return []
    evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
    gate = evidence.get("quality_gate") if isinstance(evidence.get("quality_gate"), dict) else {}
    quality_issues = _string_list(gate.get("quality_issues"))
    preference_failures = _preference_dimension_failures(gate.get("preference_dimension_failures"))
    preference_evidence = _preference_dimension_evidence(gate.get("preference_dimension_evidence"))
    min_score = _coerce_score(gate.get("min_score"))
    outcomes: list[dict[str, Any]] = []
    for focus in focuses:
        dimension = QUALITY_FOCUS_DIMENSIONS.get(focus, "")
        dimension_evidence = preference_evidence.get(dimension, []) if dimension else []
        focus_failures = [
            failure
            for failure in preference_failures
            if dimension and failure.get("dimension") == dimension
        ]
        focus_issues = _focus_quality_issues(
            focus,
            quality_issues=quality_issues,
            preference_failures=focus_failures,
        )
        if dimension and not dimension_evidence and not focus_failures:
            focus_issues.append(f"missing_preference_dimension_evidence:{dimension}")
        success = _positive_int(evidence.get("image_count")) and not focus_issues
        if focus == "image_first_video":
            video_source = evidence.get("video_source") if isinstance(evidence.get("video_source"), dict) else {}
            success = (
                _positive_int(evidence.get("video_count"))
                and video_source.get("uses_ranked_selected_image") is True
            )
        outcome: dict[str, Any] = {
            "case_id": str(case.get("case_id") or ""),
            "focus": focus,
            "success": success,
            "dimension": dimension,
            "dimension_evidence_count": len(dimension_evidence),
            "min_quality_score": round(min_score, 4) if min_score is not None else None,
            "quality_issues": focus_issues,
            "preference_dimension_failures": focus_failures,
        }
        if not dimension:
            outcome.pop("dimension")
            outcome.pop("dimension_evidence_count")
        outcomes.append(outcome)
    return outcomes


def _positive_int(value: Any) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _focus_quality_issues(
    focus: str,
    *,
    quality_issues: list[str],
    preference_failures: list[dict[str, Any]],
) -> list[str]:
    focus_issue = {
        "adult_fashion_portrait": "subject_not_attractive",
        "natural_face": "face_unnatural",
        "legwear_material": "stockings_bad",
        "long_leg_composition": "composition_bad",
        "tasteful_glamour": "not_glamorous",
    }.get(focus)
    issues: list[str] = []
    if focus_issue and focus_issue in quality_issues:
        issues.append(focus_issue)
    for failure in preference_failures:
        issue = str(failure.get("issue") or "").strip()
        if issue and issue not in issues:
            issues.append(issue)
    return issues


def _preference_dimension_failures(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    failures: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        issue = str(item.get("issue") or "").strip()
        if not dimension:
            continue
        entry: dict[str, Any] = {"dimension": dimension, "issue": issue}
        score = _coerce_score(item.get("score"))
        if score is not None:
            entry["score"] = round(score, 4)
        failures.append(entry)
    return failures


def _preference_dimension_evidence(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        return {}
    evidence: dict[str, list[dict[str, Any]]] = {}
    for dimension, raw_entries in value.items():
        dimension_text = str(dimension or "").strip()
        if not dimension_text or not isinstance(raw_entries, list):
            continue
        entries: list[dict[str, Any]] = []
        for item in raw_entries:
            if not isinstance(item, dict):
                continue
            artifact_id = str(item.get("artifact_id") or "").strip()
            score = _coerce_score(item.get("score"))
            if not artifact_id or score is None:
                continue
            entries.append({"artifact_id": artifact_id, "score": round(score, 4)})
        if entries:
            evidence[dimension_text] = entries
    return evidence


def inspect_visual_e2e_evidence(
    payload: dict[str, Any] | None,
    *,
    require_video: bool,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    request_id = str(payload.get("visual_request_id") or "")
    if not request_id:
        return {
            "request_id": "",
            "image_count": len(payload.get("images") or []),
            "video_count": len(payload.get("videos") or []),
            "video_source": _video_source_evidence(payload, require_video=require_video),
        }
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    attempts = _rows_for_request(ledger, "visual_attempts", request_id)
    artifacts = _rows_for_request(ledger, "visual_artifacts", request_id)
    judgments = _judgment_rows_for_request(
        ledger,
        request_id=request_id,
        attempts=attempts,
        artifacts=artifacts,
    )
    rankings = _rows_for_request(ledger, "visual_rankings", request_id)
    shadow_updates = _rows_for_request(ledger, "visual_shadow_updates", request_id)
    providers = sorted(
        {
            str(row.get("provider") or "")
            for row in attempts
            if str(row.get("provider") or "")
        }
    )
    provider_failure_classes, provider_error_codes = _provider_failure_counters(attempts)
    learning_trace_count = sum(1 for row in rankings if _ranking_has_learning_trace(row))
    judgments_with_learning_metadata = sum(
        1 for row in judgments if _judgment_has_learning_metadata(row)
    )
    inline_vision_judgment_count = sum(
        1 for row in judgments if _judgment_uses_inline_vision(row)
    )
    retry_attempt_count = _retry_attempt_count(payload=payload, attempts=attempts)
    recovery_summary = _recovery_summary(
        payload=payload,
        provider_failure_classes=provider_failure_classes,
        provider_error_codes=provider_error_codes,
        retry_attempt_count=retry_attempt_count,
    )
    quality_repair_summary = _quality_repair_summary(
        payload=payload,
        attempts=attempts,
        artifacts=artifacts,
    )
    quality_gate = _quality_gate(
        payload=payload,
        artifacts=artifacts,
        judgments=judgments,
        threshold=_min_quality_score_threshold(),
    )
    return {
        "request_id": request_id,
        "image_count": len(payload.get("images") or []),
        "video_count": len(payload.get("videos") or []),
        "attempt_count": len(attempts),
        "artifact_count": len(artifacts),
        "judgment_count": len(judgments),
        "ranking_count": len(rankings),
        "shadow_update_count": len(shadow_updates),
        "learning_trace_count": learning_trace_count,
        "judgments_with_learning_metadata": judgments_with_learning_metadata,
        "inline_vision_judgment_count": inline_vision_judgment_count,
        "provider_failure_classes": dict(provider_failure_classes),
        "provider_error_codes": dict(provider_error_codes),
        "retry_attempt_count": retry_attempt_count,
        "recovery_summary": recovery_summary,
        "quality_repair_summary": quality_repair_summary,
        "providers": providers,
        "require_video": require_video,
        "quality_gate": quality_gate,
        "video_source": _video_source_evidence(payload, require_video=require_video),
        "storyboard_execution": _storyboard_execution_evidence(payload),
    }


def image_requirements_available() -> bool:
    from tools.image_generation_tool import check_image_generation_requirements

    return check_image_generation_requirements()


def video_requirements_available() -> bool:
    from tools.video_generation_tool import check_video_generation_requirements

    return check_video_generation_requirements()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a live visual provider E2E learning gate.")
    parser.add_argument("--mode", choices=["live", "fixture"], default="live")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--candidate-budget", type=int, default=None)
    parser.add_argument("--video-budget", type=int, default=1)
    parser.add_argument("--duration", type=int, default=4)
    parser.add_argument("--no-video", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="Write the structured E2E report to this path.",
    )
    parser.add_argument(
        "--capture-log-path",
        type=Path,
        default=None,
        help="Capture provider stdout/stderr noise to this path.",
    )
    args = parser.parse_args(argv)

    payload = _build_report_from_args(args)
    if args.report_path is not None:
        _write_json_report(args.report_path, payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        details = []
        if args.report_path is not None:
            details.append(f"report={args.report_path}")
        if args.capture_log_path is not None:
            details.append(f"log={args.capture_log_path}")
        suffix = f" {' '.join(details)}" if details else ""
        print(f"visual live provider e2e {status}{suffix}")
    return 0 if payload["success"] else 1


def _build_report_from_args(args: argparse.Namespace) -> dict[str, Any]:
    kwargs = {
        "mode": args.mode,
        "work_dir": args.work_dir,
        "prompt": args.prompt,
        "candidate_budget": args.candidate_budget,
        "video_budget": args.video_budget,
        "duration": args.duration,
        "require_video": not args.no_video,
    }
    if args.capture_log_path is None:
        return build_visual_live_provider_e2e_report(**kwargs)

    args.capture_log_path.parent.mkdir(parents=True, exist_ok=True)
    with args.capture_log_path.open("w", encoding="utf-8") as stream:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            return build_visual_live_provider_e2e_report(**kwargs)


def _write_json_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _provider_checks(*, require_video: bool) -> dict[str, bool]:
    checks = {"image": image_requirements_available()}
    if require_video:
        checks["video"] = video_requirements_available()
    return checks


def _providers_available(provider_checks: dict[str, bool]) -> bool:
    return all(provider_checks.values())


def _payload_failures(
    payload: dict[str, Any] | None,
    evidence: dict[str, Any],
    *,
    mode: str,
    require_video: bool,
) -> list[str]:
    failures: list[str] = []
    if not isinstance(payload, dict):
        return ["missing_payload"]
    video_source = evidence.get("video_source") if isinstance(evidence.get("video_source"), dict) else {}
    storyboard_execution = (
        evidence.get("storyboard_execution")
        if isinstance(evidence.get("storyboard_execution"), dict)
        else {}
    )
    has_internal_ranked_video_source = (
        require_video
        and evidence.get("video_count", 0) >= 1
        and video_source.get("uses_ranked_selected_image") is True
    )
    has_storyboard_video_source = (
        require_video
        and evidence.get("video_count", 0) >= 1
        and storyboard_execution.get("status") in {"composed", "clips_ready"}
    )
    if payload.get("success") is not True:
        failures.append(str(payload.get("error_type") or "provider_generation_failed"))
    if evidence.get("image_count", 0) < 1 and not has_internal_ranked_video_source and not has_storyboard_video_source:
        failures.append("missing_image_output")
    if require_video and evidence.get("video_count", 0) < 1:
        failures.append("missing_video_output")
    if evidence.get("judgment_count", 0) < (2 if require_video else 1):
        failures.append("missing_quality_judgments")
    if evidence.get("ranking_count", 0) < (2 if require_video else 1):
        failures.append("missing_rankings")
    if evidence.get("learning_trace_count", 0) < (2 if require_video else 1):
        failures.append("missing_learning_trace")
    if evidence.get("judgments_with_learning_metadata", 0) < (2 if require_video else 1):
        failures.append("missing_judgment_learning_metadata")
    provider_failures = evidence.get("provider_failure_classes")
    if (
        mode == "live"
        and isinstance(provider_failures, dict)
        and provider_failures.get("provider_unavailable", 0) >= 1
        and evidence.get("retry_attempt_count", 0) >= 1
        and payload.get("success") is not True
    ):
        failures.append("provider_unavailable_after_retry")
    if mode == "live" and evidence.get("image_count", 0) >= 1 and evidence.get("inline_vision_judgment_count", 0) < 1:
        failures.append("missing_inline_vision_judgment")
    quality_gate = evidence.get("quality_gate")
    if mode == "live" and isinstance(quality_gate, dict) and quality_gate.get("success") is False:
        failures.append("quality_gate_failed")
    if mode == "live" and isinstance(quality_gate, dict) and quality_gate.get("quality_issues"):
        failures.append("selected_quality_issue_detected")
    if (
        mode == "live"
        and require_video
        and evidence.get("video_count", 0) >= 1
        and video_source.get("uses_ranked_selected_image") is not True
        and not has_storyboard_video_source
    ):
        failures.append("video_not_using_ranked_image_source")
    if mode == "live" and _contains_fixture_provider(payload, evidence):
        failures.append("non_live_provider_detected")
    return sorted(set(failures))


def _contains_fixture_provider(payload: dict[str, Any], evidence: dict[str, Any]) -> bool:
    provider_values = set(evidence.get("providers") or [])
    generation_payloads = payload.get("generation_payloads")
    if isinstance(generation_payloads, dict):
        for item in generation_payloads.values():
            if isinstance(item, list):
                provider_values.update(
                    str(row.get("provider") or "")
                    for row in item
                    if isinstance(row, dict)
                )
            elif isinstance(item, dict):
                provider_values.add(str(item.get("provider") or ""))
    normalized = {value.strip().lower() for value in provider_values if value}
    return not normalized or bool(normalized & {"fixture", "mock", "test"})


def _safe_payload_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {
        "success": payload.get("success"),
        "package_status": payload.get("package_status"),
        "visual_request_id": payload.get("visual_request_id"),
        "image_count": len(payload.get("images") or []),
        "video_count": len(payload.get("videos") or []),
        "error_type": payload.get("error_type"),
        "error": payload.get("error"),
    }


def _storyboard_execution_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    generation_strategy = (
        payload.get("generation_strategy")
        if isinstance(payload.get("generation_strategy"), dict)
        else {}
    )
    execution = (
        generation_strategy.get("storyboard_execution")
        if isinstance(generation_strategy.get("storyboard_execution"), dict)
        else {}
    )
    videos = [str(item) for item in payload.get("videos") or [] if isinstance(item, str)]
    shots = execution.get("shots") if isinstance(execution.get("shots"), list) else []
    source_clips = [
        str(shot.get("clip_path"))
        for shot in shots
        if isinstance(shot, dict) and isinstance(shot.get("clip_path"), str)
    ]
    bad_source_shot_ids = [
        str(shot.get("shot_id") or f"shot_{index + 1}")
        for index, shot in enumerate(shots)
        if isinstance(shot, dict) and shot.get("uses_single_ranked_image") is not True
    ]
    composed_video = _string_or_none(execution.get("composed_video"))
    return {
        "status": execution.get("status"),
        "shot_count": execution.get("shot_count"),
        "clip_count": execution.get("clip_count"),
        "composition_status": execution.get("composition_status"),
        "delivery_policy": execution.get("delivery_policy"),
        "composed_video": composed_video,
        "delivers_composed_video": bool(composed_video and videos == [composed_video]),
        "delivers_source_clips": any(clip in videos for clip in source_clips),
        "shots_use_single_ranked_images": (not bad_source_shot_ids) if shots else None,
        "bad_source_shot_ids": bad_source_shot_ids,
    }


def _storyboard_execution_failures(evidence: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if evidence.get("status") != "composed":
        failures.append("storyboard_not_composed")
    if evidence.get("composition_status") != "composed":
        failures.append("storyboard_composition_not_composed")
    if evidence.get("clip_count") != 2:
        failures.append("storyboard_wrong_clip_count")
    if evidence.get("delivers_composed_video") is not True:
        failures.append("storyboard_composed_video_not_delivered")
    if evidence.get("delivers_source_clips") is True:
        failures.append("storyboard_source_clips_delivered")
    if evidence.get("shots_use_single_ranked_images") is not True:
        failures.append("storyboard_shot_source_not_single_ranked_image")
    return failures


def _video_source_evidence(payload: dict[str, Any], *, require_video: bool) -> dict[str, Any]:
    generation_strategy = (
        payload.get("generation_strategy")
        if isinstance(payload.get("generation_strategy"), dict)
        else {}
    )
    rankings = payload.get("rankings") if isinstance(payload.get("rankings"), dict) else {}
    image_ranking = rankings.get("image") if isinstance(rankings.get("image"), dict) else {}
    source_image_artifact_id = _string_or_none(generation_strategy.get("video_source_artifact_id"))
    ranked_selected_image_artifact_id = _string_or_none(image_ranking.get("selected_artifact_id"))
    return {
        "require_video": bool(require_video),
        "image_first_for_video": generation_strategy.get("image_first_for_video") is True,
        "source_image_artifact_id": source_image_artifact_id,
        "ranked_selected_image_artifact_id": ranked_selected_image_artifact_id,
        "uses_ranked_selected_image": bool(
            source_image_artifact_id
            and ranked_selected_image_artifact_id
            and source_image_artifact_id == ranked_selected_image_artifact_id
        ),
    }


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _provider_failure_counters(attempts: list[dict[str, Any]]) -> tuple[Counter[str], Counter[str]]:
    classes: Counter[str] = Counter()
    codes: Counter[str] = Counter()
    for row in attempts:
        provider = str(row.get("provider") or row.get("provider_name") or "").strip()
        error_type = row.get("error_type") or row.get("provider_error_type")
        error_message = row.get("error_message") or row.get("provider_error_message")
        if not (error_type or error_message):
            continue
        if not provider and _is_internal_pipeline_error(error_type):
            continue
        failure = classify_visual_provider_failure(
            {
                "success": False,
                "error_type": error_type,
                "error": error_message,
            }
        )
        failure_class = str(failure.get("failure_class") or "")
        provider_code = str(failure.get("provider_message_code") or error_type or "")
        if failure_class:
            classes[failure_class] += 1
        if provider_code:
            codes[provider_code] += 1
    return classes, codes


def _is_internal_pipeline_error(error_type: Any) -> bool:
    return str(error_type or "").strip() in {
        "missing_video_source_image",
    }


def _recovery_summary(
    *,
    payload: dict[str, Any],
    provider_failure_classes: Counter[str],
    provider_error_codes: Counter[str],
    retry_attempt_count: int,
) -> dict[str, Any]:
    provider_failure_count = sum(provider_failure_classes.values())
    negotiation_attempted = provider_failure_count > 0 and retry_attempt_count > 0
    negotiation_success = negotiation_attempted and payload.get("success") is True
    recovered_failure_classes = sorted(provider_failure_classes) if negotiation_success else []
    return {
        "provider_failure_count": provider_failure_count,
        "provider_failure_classes": dict(provider_failure_classes),
        "provider_error_codes": dict(provider_error_codes),
        "retry_attempt_count": retry_attempt_count,
        "negotiation_attempted": negotiation_attempted,
        "negotiation_success": negotiation_success,
        "content_moderation_recovered": "content_moderation" in recovered_failure_classes,
        "recovered_failure_classes": recovered_failure_classes,
    }


def _suite_recovery_summary(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    provider_failure_classes: Counter[str] = Counter()
    provider_error_codes: Counter[str] = Counter()
    provider_failure_count = 0
    retry_attempt_count = 0
    negotiation_attempted_case_count = 0
    negotiation_success_case_count = 0
    content_moderation_recovered_case_count = 0
    recovered_failure_classes: set[str] = set()
    for case in case_reports:
        summary = case.get("recovery_summary") if isinstance(case.get("recovery_summary"), dict) else {}
        provider_failure_count += int(_coerce_score(summary.get("provider_failure_count")) or 0)
        retry_attempt_count += int(_coerce_score(summary.get("retry_attempt_count")) or 0)
        provider_failure_classes.update(_counter_from_mapping(summary.get("provider_failure_classes")))
        provider_error_codes.update(_counter_from_mapping(summary.get("provider_error_codes")))
        if summary.get("negotiation_attempted") is True:
            negotiation_attempted_case_count += 1
        if summary.get("negotiation_success") is True:
            negotiation_success_case_count += 1
        if summary.get("content_moderation_recovered") is True:
            content_moderation_recovered_case_count += 1
        for failure_class in summary.get("recovered_failure_classes") or []:
            if isinstance(failure_class, str) and failure_class:
                recovered_failure_classes.add(failure_class)
    return {
        "provider_failure_count": provider_failure_count,
        "provider_failure_classes": dict(provider_failure_classes),
        "provider_error_codes": dict(provider_error_codes),
        "retry_attempt_count": retry_attempt_count,
        "negotiation_attempted_case_count": negotiation_attempted_case_count,
        "negotiation_success_case_count": negotiation_success_case_count,
        "content_moderation_recovered_case_count": content_moderation_recovered_case_count,
        "recovered_failure_classes": sorted(recovered_failure_classes),
    }


def _quality_repair_summary(
    *,
    payload: dict[str, Any],
    attempts: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    repair_attempts: dict[str, dict[str, Any]] = {}
    for attempt in attempts:
        attempt_id = _row_id(attempt, "attempt_id", "id")
        metadata = _quality_repair_metadata(attempt)
        if attempt_id and metadata:
            repair_attempts[attempt_id] = metadata

    selected_ids = _selected_artifact_ids(payload)
    repair_artifacts = [
        artifact
        for artifact in artifacts
        if str(artifact.get("attempt_id") or "") in repair_attempts
    ]
    selected_repair_artifacts = [
        artifact
        for artifact in repair_artifacts
        if _row_id(artifact, "artifact_id", "id") in selected_ids
    ]
    by_modality: dict[str, dict[str, int]] = {}
    for attempt_id, metadata in repair_attempts.items():
        modality = str(metadata.get("modality") or "unknown")
        row = by_modality.setdefault(
            modality,
            {"attempt_count": 0, "success_count": 0, "selected_repair_count": 0},
        )
        row["attempt_count"] += 1
        selected_for_attempt = [
            artifact
            for artifact in selected_repair_artifacts
            if str(artifact.get("attempt_id") or "") == attempt_id
        ]
        if selected_for_attempt:
            row["success_count"] += 1
            row["selected_repair_count"] += len(selected_for_attempt)

    attempt_count = len(repair_attempts)
    selected_repair_count = len(selected_repair_artifacts)
    success_count = sum(row["success_count"] for row in by_modality.values())
    return {
        "attempt_count": attempt_count,
        "success_count": success_count,
        "selected_repair_count": selected_repair_count,
        "success_rate": _rate(success_count, attempt_count),
        "selected_repair_rate": _rate(selected_repair_count, attempt_count),
        "by_modality": by_modality,
    }


def _suite_quality_repair_summary(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    by_modality: dict[str, dict[str, int]] = {}
    attempt_count = 0
    success_count = 0
    selected_repair_count = 0
    for case in case_reports:
        summary = case.get("quality_repair_summary") if isinstance(case.get("quality_repair_summary"), dict) else {}
        attempt_count += int(_coerce_score(summary.get("attempt_count")) or 0)
        success_count += int(_coerce_score(summary.get("success_count")) or 0)
        selected_repair_count += int(_coerce_score(summary.get("selected_repair_count")) or 0)
        modality_summary = summary.get("by_modality")
        if not isinstance(modality_summary, dict):
            continue
        for modality, values in modality_summary.items():
            if not isinstance(modality, str) or not isinstance(values, dict):
                continue
            row = by_modality.setdefault(
                modality,
                {"attempt_count": 0, "success_count": 0, "selected_repair_count": 0},
            )
            row["attempt_count"] += int(_coerce_score(values.get("attempt_count")) or 0)
            row["success_count"] += int(_coerce_score(values.get("success_count")) or 0)
            row["selected_repair_count"] += int(_coerce_score(values.get("selected_repair_count")) or 0)
    return {
        "attempt_count": attempt_count,
        "success_count": success_count,
        "selected_repair_count": selected_repair_count,
        "success_rate": _rate(success_count, attempt_count),
        "selected_repair_rate": _rate(selected_repair_count, attempt_count),
        "by_modality": by_modality,
    }


def _quality_repair_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    repair = metadata.get("quality_repair") if isinstance(metadata, dict) else None
    if isinstance(repair, dict):
        return repair
    parameters = row.get("parameters_requested")
    if not isinstance(parameters, dict):
        parameters = row.get("parameters_requested_json")
    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except json.JSONDecodeError:
            parameters = {}
    if isinstance(parameters, dict) and parameters.get("quality_repair") is True:
        return {"modality": "video"}
    return {}


def _row_id(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _counter_from_mapping(value: Any) -> Counter[str]:
    counter: Counter[str] = Counter()
    if not isinstance(value, dict):
        return counter
    for key, count in value.items():
        if not isinstance(key, str) or not key:
            continue
        counter[key] += int(_coerce_score(count) or 0)
    return counter


def _retry_attempt_count(*, payload: dict[str, Any], attempts: list[dict[str, Any]]) -> int:
    payload_retries = _payload_retry_count(payload)
    if payload_retries:
        return payload_retries
    return sum(1 for row in attempts if _attempt_is_retry(row))


def _payload_retry_count(payload: dict[str, Any]) -> int:
    generation_payloads = payload.get("generation_payloads")
    if not isinstance(generation_payloads, dict):
        return 0
    count = 0
    for value in generation_payloads.values():
        items = value if isinstance(value, list) else [value]
        count += sum(1 for item in items if isinstance(item, dict) and item.get("retry_of") is not None)
    return count


def _attempt_is_retry(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return metadata.get("retry_of") is not None


def _rows_for_request(
    ledger: VisualAttemptLedger,
    table: str,
    request_id: str,
) -> list[dict[str, Any]]:
    try:
        return ledger._list(table, where="request_id = ?", params=(request_id,))
    except Exception:
        return []


def _judgment_rows_for_request(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    attempts: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = _rows_for_request(ledger, "visual_judgments", request_id)
    if rows:
        return rows

    artifact_ids = _id_values(artifacts, "artifact_id", "id")
    attempt_ids = _id_values(attempts, "attempt_id", "id") | _id_values(artifacts, "attempt_id")
    fallback_rows: list[dict[str, Any]] = []
    for artifact_id in sorted(artifact_ids):
        fallback_rows.extend(_rows_for_column(ledger, "visual_judgments", "artifact_id", artifact_id))
    for attempt_id in sorted(attempt_ids):
        fallback_rows.extend(_rows_for_column(ledger, "visual_judgments", "attempt_id", attempt_id))
    return _dedupe_rows(fallback_rows, "judgment_id", "id")


def _rows_for_column(
    ledger: VisualAttemptLedger,
    table: str,
    column: str,
    value: str,
) -> list[dict[str, Any]]:
    try:
        return ledger._list(table, where=f"{column} = ?", params=(value,))
    except Exception:
        return []


def _id_values(rows: list[dict[str, Any]], *keys: str) -> set[str]:
    values: set[str] = set()
    for row in rows:
        for key in keys:
            value = row.get(key)
            if isinstance(value, str) and value:
                values.add(value)
    return values


def _dedupe_rows(rows: list[dict[str, Any]], *id_keys: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        row_id = next(
            (str(row.get(key)) for key in id_keys if row.get(key)),
            f"row:{index}",
        )
        if row_id in seen:
            continue
        seen.add(row_id)
        deduped.append(row)
    return deduped


def _ranking_has_learning_trace(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    if isinstance(metadata.get("active_learning"), dict):
        return True
    rationale = row.get("rationale_json") if isinstance(row.get("rationale_json"), dict) else {}
    return isinstance(rationale.get("active_learning"), dict)


def _judgment_has_learning_metadata(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    if all(metadata.get(key) for key in ("intent_signature", "strategy_signature", "modality")):
        return True
    return _is_legacy_quality_judgment(row)


def _judgment_uses_inline_vision(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    if metadata.get("vision_observation_source") == "inline_vision_judge":
        return True
    for key in ("details", "score_json"):
        payload = row.get(key) if isinstance(row.get(key), dict) else {}
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        if evidence.get("source") == "inline_vision_judge":
            return True
    return False


def _quality_gate(
    *,
    payload: dict[str, Any],
    artifacts: list[dict[str, Any]],
    judgments: list[dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    selected_ids = _selected_artifact_ids(payload)
    if not selected_ids:
        selected_ids = {
            str(row.get("artifact_id") or row.get("id") or "")
            for row in artifacts
            if row.get("artifact_id") or row.get("id")
        }
    latest_scores: dict[str, float] = {}
    quality_issues_by_artifact: dict[str, list[str]] = {}
    preference_dimension_failures_by_artifact: dict[str, list[dict[str, Any]]] = {}
    preference_dimension_evidence: dict[str, list[dict[str, Any]]] = {}
    for row in judgments:
        if row.get("judge_name") != "visual_quality_judge":
            continue
        artifact_id = str(row.get("artifact_id") or "")
        if not artifact_id or artifact_id not in selected_ids:
            continue
        score = _judgment_quality_score(row)
        if score is None:
            continue
        latest_scores[artifact_id] = score
        quality_issues = _judgment_quality_issues(row)
        if quality_issues:
            quality_issues_by_artifact[artifact_id] = quality_issues
        preference_dimension_failures = _judgment_preference_dimension_failures(row, artifact_id=artifact_id)
        if preference_dimension_failures:
            preference_dimension_failures_by_artifact[artifact_id] = preference_dimension_failures
        for dimension, score in _judgment_preference_dimension_scores(row).items():
            preference_dimension_evidence.setdefault(dimension, []).append(
                {"artifact_id": artifact_id, "score": round(score, 4)}
            )
    low_quality_artifacts = [
        artifact_id
        for artifact_id, score in latest_scores.items()
        if score < threshold
    ]
    min_score = min(latest_scores.values()) if latest_scores else None
    quality_issue_artifacts = sorted(quality_issues_by_artifact)
    quality_issues = sorted(
        {
            issue
            for issues in quality_issues_by_artifact.values()
            for issue in issues
        }
    )
    preference_dimension_failures = [
        failure
        for failures in preference_dimension_failures_by_artifact.values()
        for failure in failures
    ]
    return {
        "success": bool(latest_scores) and not low_quality_artifacts,
        "threshold": threshold,
        "score_count": len(latest_scores),
        "min_score": round(min_score, 4) if min_score is not None else None,
        "artifact_scores": {key: round(value, 4) for key, value in latest_scores.items()},
        "low_quality_artifacts": low_quality_artifacts,
        "quality_issue_artifacts": quality_issue_artifacts,
        "quality_issues": quality_issues,
        "quality_issues_by_artifact": quality_issues_by_artifact,
        "preference_dimension_failures": preference_dimension_failures,
        "preference_dimension_failures_by_artifact": preference_dimension_failures_by_artifact,
        "preference_dimension_evidence": preference_dimension_evidence,
    }


def _selected_artifact_ids(payload: dict[str, Any]) -> set[str]:
    delivery_metadata = payload.get("delivery_metadata")
    if not isinstance(delivery_metadata, dict):
        return set()
    selected = delivery_metadata.get("selected_visual_artifact_ids")
    if not isinstance(selected, list):
        return set()
    return {str(item) for item in selected if item}


def _judgment_quality_score(row: dict[str, Any]) -> float | None:
    for value in (
        row.get("score"),
        _nested_value(row.get("details"), "confidence"),
        _nested_value(row.get("score_json"), "confidence"),
    ):
        score = _coerce_score(value)
        if score is not None:
            return score
    for payload in (row.get("details"), row.get("score_json")):
        scores = _nested_value(payload, "scores")
        if isinstance(scores, dict):
            values = [
                _coerce_score(value)
                for value in scores.values()
            ]
            values = [value for value in values if value is not None]
            if values:
                return sum(values) / len(values)
    return None


def _judgment_quality_issues(row: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for payload in (row.get("details"), row.get("score_json")):
        if not isinstance(payload, dict):
            continue
        raw_issues = payload.get("quality_issues")
        if not isinstance(raw_issues, list):
            continue
        for issue in raw_issues:
            if isinstance(issue, str) and issue and issue not in issues:
                issues.append(issue)
    return issues


def _judgment_preference_dimension_failures(
    row: dict[str, Any],
    *,
    artifact_id: str,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in (row.get("details"), row.get("score_json")):
        if not isinstance(payload, dict):
            continue
        dimensions = payload.get("preference_dimensions")
        if not isinstance(dimensions, dict):
            continue
        quality_issues = _judgment_quality_issues(row)
        for dimension, raw_score in dimensions.items():
            dimension_text = str(dimension or "").strip()
            if not dimension_text or dimension_text in seen:
                continue
            score = _coerce_score(raw_score)
            if score is None or score >= 0.5:
                continue
            seen.add(dimension_text)
            failures.append(
                {
                    "artifact_id": artifact_id,
                    "dimension": dimension_text,
                    "score": round(score, 4),
                    "issue": _preference_dimension_issue(dimension_text, quality_issues),
                }
            )
    return failures


def _judgment_preference_dimension_scores(row: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for payload in (row.get("details"), row.get("score_json")):
        if not isinstance(payload, dict):
            continue
        dimensions = payload.get("preference_dimensions")
        if not isinstance(dimensions, dict):
            continue
        for dimension, raw_score in dimensions.items():
            dimension_text = str(dimension or "").strip()
            if not dimension_text:
                continue
            score = _coerce_score(raw_score)
            if score is None:
                continue
            scores[dimension_text] = score
    return scores


def _preference_dimension_issue(dimension: str, quality_issues: list[str]) -> str:
    issue = {
        "subject_beauty": "subject_not_attractive",
        "face_naturalness": "face_unnatural",
        "glamour_impact": "not_glamorous",
        "fashion_material_quality": "stockings_bad",
        "pose_composition": "composition_bad",
        "motion_quality": "motion_bad",
    }.get(dimension, "")
    if issue in quality_issues:
        return issue
    return issue


def _nested_value(payload: Any, key: str) -> Any:
    return payload.get(key) if isinstance(payload, dict) else None


def _coerce_score(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, numeric))


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _min_quality_score_threshold() -> float:
    raw = os.environ.get("HERMES_VISUAL_E2E_MIN_QUALITY_SCORE")
    if raw is None or not raw.strip():
        return DEFAULT_MIN_QUALITY_SCORE
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return DEFAULT_MIN_QUALITY_SCORE


def _is_legacy_quality_judgment(row: dict[str, Any]) -> bool:
    if row.get("judge_name") != "visual_quality_judge":
        return False
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    score_json = row.get("score_json") if isinstance(row.get("score_json"), dict) else {}
    payload = details or score_json
    return bool(payload.get("version") or payload.get("scores") or row.get("confidence"))


def _failure_result(
    mode: str,
    failures: list[str],
    *,
    payload: dict[str, Any] | None,
    provider_checks: dict[str, bool],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "success": False,
        "provider_mode": mode,
        "failures": failures,
        "provider_checks": provider_checks,
        "payload": _safe_payload_summary(payload),
        "evidence": evidence,
    }


class VisualE2ECaseTimeout(TimeoutError):
    pass


def _case_timeout_seconds(value: Any) -> float | None:
    if value is None:
        return DEFAULT_CASE_TIMEOUT_SECONDS
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CASE_TIMEOUT_SECONDS
    if seconds <= 0:
        return None
    return seconds


@contextlib.contextmanager
def _case_timeout_alarm(timeout_seconds: float | None):
    if (
        timeout_seconds is None
        or threading.current_thread() is not threading.main_thread()
        or not _case_timeout_alarm_supported()
    ):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def _handle_timeout(_signum, _frame):
        raise VisualE2ECaseTimeout(f"visual E2E case exceeded {timeout_seconds:g}s")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0 or previous_timer[1] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def _case_timeout_report(*, mode: str, timeout_seconds: float | None) -> dict[str, Any]:
    return {
        "success": False,
        "provider_mode": mode,
        "failures": ["case_timeout"],
        "provider_checks": {},
        "payload": None,
        "evidence": {
            "request_id": "",
            "case_timeout_seconds": timeout_seconds,
            "recovery_summary": {
                "provider_failure_count": 1,
                "provider_failure_classes": {"case_timeout": 1},
                "provider_error_codes": {"case_timeout": 1},
                "retry_attempt_count": 0,
                "negotiation_attempted": False,
                "negotiation_success": False,
                "content_moderation_recovered": False,
                "recovered_failure_classes": [],
            },
        },
    }


def _case_timeout_alarm_supported() -> bool:
    return all(hasattr(signal, name) for name in ("SIGALRM", "ITIMER_REAL", "getitimer", "setitimer"))


def _case_work_dir(work_dir: str | Path | None, case_id: str) -> Path | None:
    if work_dir is None:
        return None
    return Path(work_dir) / "quality-suite" / case_id


def _hermes_home_for_mode(*, mode: str, work_dir: str | Path | None) -> str | Path | None:
    if str(mode or "").strip().lower() == "live":
        return None
    return work_dir


@contextlib.contextmanager
def _hermes_home_context(work_dir: str | Path | None):
    if work_dir is None:
        yield
        return
    previous = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = str(Path(work_dir))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = previous


@contextlib.contextmanager
def _fixture_provider_context(
    mode: str,
    work_dir: str | Path | None,
    *,
    force_video_quality_repair: bool = False,
    force_storyboard_composition: bool = False,
):
    if mode != "fixture":
        if force_video_quality_repair:
            with _live_video_quality_repair_probe_context():
                yield
        else:
            yield
        return
    from tools import visual_package_tool

    fixture_dir = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(prefix="hermes-visual-fixture-"))
    fixture_dir.mkdir(parents=True, exist_ok=True)
    image_path = fixture_dir / "live-e2e-fixture.png"
    video_path = fixture_dir / "live-e2e-fixture.mp4"
    repaired_video_path = fixture_dir / "live-e2e-fixture-repaired.mp4"
    composed_video_path = fixture_dir / "live-e2e-fixture-storyboard-composed.mp4"
    image_path.write_bytes(_ONE_PIXEL_PNG)
    video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    repaired_video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomrepaired")
    composed_video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomcomposed")

    old_image = visual_package_tool.generate_image
    old_video = visual_package_tool.generate_video
    old_probe = visual_package_tool.probe_media_reference
    old_compose = visual_package_tool._compose_storyboard_clips
    video_calls = 0

    def fixture_video(**kwargs):
        nonlocal video_calls
        video_calls += 1
        if force_video_quality_repair and video_calls == 1:
            return {
                "success": True,
                "video": str(video_path),
                "provider": "fixture",
                "model": "video-fixture",
                "vision_observation": {
                    "aspect_integrity": 0.2,
                    "motion_quality": 0.25,
                    "artifact_defects": ["weak_aspect_integrity", "weak_motion_or_duration_evidence"],
                },
            }
        return {
            "success": True,
            "video": str(repaired_video_path if force_video_quality_repair else video_path),
            "provider": "fixture",
            "model": "video-fixture",
            "vision_observation": {
                "aspect_integrity": 0.95,
                "motion_quality": 0.9,
                "confidence": 0.9,
                "artifact_defects": [],
            },
        }

    def fixture_image(**kwargs):
        return {
            "success": True,
            "image": str(image_path),
            "provider": "fixture",
            "model": "image-fixture",
            "vision_observation": {
                "visual_appeal": 0.88,
                "composition": 0.86,
                "aspect_integrity": 1.0,
                "subject_quality": 0.9,
                "face_quality": 0.88,
                "glamour_impact": 0.84,
                "fashion_material_quality": 0.9,
                "pose_composition": 0.87,
                "confidence": 0.86,
                "artifact_defects": [],
                "evidence": {
                    "source": "fixture_quality_suite",
                    "summary": "deterministic fixture vision observation",
                },
            },
        }

    def fixture_probe_media_reference(ref):
        is_video = str(ref).lower().endswith((".mp4", ".mov", ".webm"))
        return SimpleNamespace(
            sha256=f"fixture:{ref}",
            is_stable=True,
            freshness_status="fresh",
            local_path=str(ref) if str(ref).startswith("/") else None,
            mime_type="video/mp4" if is_video else "image/png",
            bytes=10,
            width=768,
            height=768,
            duration_seconds=4.0 if is_video else None,
        )

    visual_package_tool.generate_image = fixture_image
    visual_package_tool.generate_video = fixture_video
    visual_package_tool.probe_media_reference = fixture_probe_media_reference
    if force_storyboard_composition:
        visual_package_tool._compose_storyboard_clips = lambda video_paths, **_kwargs: {
            "success": True,
            "video": str(composed_video_path),
            "provider": "local",
            "model": "fixture-concat",
            "clip_count": len(video_paths),
        }
    try:
        yield
    finally:
        visual_package_tool.generate_image = old_image
        visual_package_tool.generate_video = old_video
        visual_package_tool.probe_media_reference = old_probe
        visual_package_tool._compose_storyboard_clips = old_compose


@contextlib.contextmanager
def _live_video_quality_repair_probe_context():
    from tools import visual_package_tool

    old_video = visual_package_tool.generate_video
    video_calls = 0

    def repair_probe_video(**kwargs):
        nonlocal video_calls
        video_calls += 1
        payload = old_video(**kwargs)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            return payload
        payload = dict(payload)
        observation = payload.get("vision_observation")
        observation = dict(observation) if isinstance(observation, dict) else {}
        if video_calls == 1:
            observation.update(
                {
                    "aspect_integrity": 0.2,
                    "motion_quality": 0.25,
                    "artifact_defects": [
                        "weak_aspect_integrity",
                        "weak_motion_or_duration_evidence",
                    ],
                }
            )
            payload["quality_probe"] = {
                "type": "live_video_quality_repair_probe",
                "phase": "forced_initial_motion_failure",
            }
        else:
            observation.setdefault("aspect_integrity", 0.95)
            observation.setdefault("motion_quality", 0.9)
            observation.setdefault("confidence", 0.9)
            observation.setdefault("artifact_defects", [])
            payload["quality_probe"] = {
                "type": "live_video_quality_repair_probe",
                "phase": "repair_candidate_observed",
            }
        payload["vision_observation"] = observation
        return payload

    visual_package_tool.generate_video = repair_probe_video
    try:
        yield
    finally:
        visual_package_tool.generate_video = old_video


if __name__ == "__main__":
    raise SystemExit(main())
