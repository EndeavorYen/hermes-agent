from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
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
            "Create one image and one short video: professional fashion editorial portrait of an adult woman model in refined black tights, "
            "beautiful natural face, elegant full-body pose, long-leg composition, tasteful studio glamour."
        ),
        "require_video": True,
        "duration": 4,
        "candidate_budget": 2,
        "video_budget": 1,
    },
]
DEFAULT_MIN_QUALITY_SCORE = 0.55
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

    with _hermes_home_context(work_dir):
        with _fixture_provider_context(mode, work_dir):
            package_args = {
                "prompt": prompt,
                "include_video": require_video,
                "video_budget": video_budget,
                "duration": duration,
                "aspect_ratio": "1:1",
            }
            if candidate_budget is not None:
                package_args["candidate_budget"] = candidate_budget
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


def build_visual_live_provider_e2e_suite_report(
    *,
    mode: str = "live",
    work_dir: str | Path | None = None,
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    case_specs = cases or DEFAULT_E2E_CASES
    case_reports = []
    failures: list[str] = []
    for case in case_specs:
        case_id = str(case.get("case_id") or f"case_{len(case_reports) + 1}")
        report = build_visual_live_provider_e2e_report(
            mode=mode,
            work_dir=_case_work_dir(work_dir, case_id),
            prompt=str(case.get("prompt") or DEFAULT_PROMPT),
            candidate_budget=case.get("candidate_budget"),
            video_budget=int(case.get("video_budget") or 1),
            duration=int(case.get("duration") or 4),
            require_video=case.get("require_video") is not False,
        )
        case_report = {
            "case_id": case_id,
            "success": report.get("success") is True,
            "failures": list(report.get("failures") or []),
            "payload": report.get("payload"),
            "evidence": report.get("evidence"),
        }
        case_reports.append(case_report)
        failures.extend(f"{case_id}:{failure}" for failure in case_report["failures"])
    return {
        "success": not failures,
        "provider_mode": mode,
        "case_count": len(case_reports),
        "failures": failures,
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
        "providers": providers,
        "require_video": require_video,
        "quality_gate": quality_gate,
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
    if payload.get("success") is not True:
        failures.append(str(payload.get("error_type") or "provider_generation_failed"))
    if evidence.get("image_count", 0) < 1:
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


def _provider_failure_counters(attempts: list[dict[str, Any]]) -> tuple[Counter[str], Counter[str]]:
    classes: Counter[str] = Counter()
    codes: Counter[str] = Counter()
    for row in attempts:
        error_type = row.get("error_type") or row.get("provider_error_type")
        error_message = row.get("error_message") or row.get("provider_error_message")
        if not (error_type or error_message):
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


def _nested_value(payload: Any, key: str) -> Any:
    return payload.get(key) if isinstance(payload, dict) else None


def _coerce_score(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, numeric))


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


def _case_work_dir(work_dir: str | Path | None, case_id: str) -> Path | None:
    if work_dir is None:
        return None
    return Path(work_dir) / "quality-suite" / case_id


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
def _fixture_provider_context(mode: str, work_dir: str | Path | None):
    if mode != "fixture":
        yield
        return
    from tools import visual_package_tool

    fixture_dir = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(prefix="hermes-visual-fixture-"))
    fixture_dir.mkdir(parents=True, exist_ok=True)
    image_path = fixture_dir / "live-e2e-fixture.png"
    video_path = fixture_dir / "live-e2e-fixture.mp4"
    image_path.write_bytes(_ONE_PIXEL_PNG)
    video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")

    old_image = visual_package_tool.generate_image
    old_video = visual_package_tool.generate_video
    visual_package_tool.generate_image = lambda **kwargs: {
        "success": True,
        "image": str(image_path),
        "provider": "fixture",
        "model": "image-fixture",
    }
    visual_package_tool.generate_video = lambda **kwargs: {
        "success": True,
        "video": str(video_path),
        "provider": "fixture",
        "model": "video-fixture",
    }
    try:
        yield
    finally:
        visual_package_tool.generate_image = old_image
        visual_package_tool.generate_video = old_video


if __name__ == "__main__":
    raise SystemExit(main())
