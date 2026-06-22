from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_BASELINE_WINDOW = 3
DEFAULT_RECENT_WINDOW = 3
DEFAULT_MAX_RUNS = 20
QUALITY_DEGRADATION_THRESHOLD = -0.15


def build_live_quality_trend_report(
    reports: list[dict[str, Any]],
    *,
    baseline_window: int = DEFAULT_BASELINE_WINDOW,
    recent_window: int = DEFAULT_RECENT_WINDOW,
) -> dict[str, Any]:
    runs = _normalised_runs(reports)
    baseline, recent = _split_windows(runs, baseline_window=baseline_window, recent_window=recent_window)
    summary = _summary(runs, baseline, recent)
    degradations = _degradations(summary)
    next_actions = _next_actions(summary, degradations, recent)
    return {
        "success": len(degradations) == 0,
        "run_count": len(runs),
        "window": {
            "baseline_run_count": len(baseline),
            "recent_run_count": len(recent),
            "baseline_window": max(1, int(baseline_window)),
            "recent_window": max(1, int(recent_window)),
        },
        "summary": summary,
        "degradations": degradations,
        "next_actions": next_actions,
        "self_review": {
            "reduces_human_intervention": bool(next_actions),
            "human_feedback_required": not bool(next_actions),
            "privacy_safe": True,
            "provider_and_aesthetic_tracks_separated": True,
        },
    }


def build_live_quality_trend_report_from_dir(
    output_dir: str | Path,
    *,
    baseline_window: int = DEFAULT_BASELINE_WINDOW,
    recent_window: int = DEFAULT_RECENT_WINDOW,
    max_runs: int = DEFAULT_MAX_RUNS,
) -> dict[str, Any]:
    reports = _read_reports(Path(output_dir), max_runs=max_runs)
    return build_live_quality_trend_report(
        reports,
        baseline_window=baseline_window,
        recent_window=recent_window,
    )


def _read_reports(output_dir: Path, *, max_runs: int) -> list[dict[str, Any]]:
    runs_dir = output_dir / "runs"
    if runs_dir.exists():
        paths = sorted(runs_dir.glob("*.json"))
    else:
        paths = [output_dir / "latest.json"] if (output_dir / "latest.json").exists() else []
    reports: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            reports.append(payload)
    reports = sorted(
        reports,
        key=lambda report: (
            str(report.get("generated_at") or ""),
            str(report.get("run_id") or ""),
        ),
    )
    return reports[-max(1, int(max_runs)) :]


def _normalised_runs(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for index, report in enumerate(reports):
        if not isinstance(report, dict):
            continue
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        preference_failures = _preference_dimension_failures(summary.get("preference_dimension_failures"))
        runs.append(
            {
                "run_id": str(report.get("run_id") or f"run_{index + 1}"),
                "generated_at": str(report.get("generated_at") or ""),
                "success": report.get("success") is True,
                "case_count": _int(summary.get("case_count")),
                "min_quality_score": _float_or_none(summary.get("min_quality_score")),
                "quality_issue_count": _int(summary.get("quality_issue_count")),
                "provider_failure_count": _int(summary.get("provider_failure_count")),
                "video_missing_after_image_count": _int(summary.get("video_missing_after_image_count")),
                "image_first_video_source_failure_count": _int(
                    summary.get("image_first_video_source_failure_count")
                ),
                "preference_dimension_failure_count": _int(summary.get("preference_dimension_failure_count")),
                "preference_dimension_failures": preference_failures,
            }
        )
    return sorted(runs, key=lambda run: (run["generated_at"], run["run_id"]))


def _split_windows(
    runs: list[dict[str, Any]],
    *,
    baseline_window: int,
    recent_window: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not runs:
        return [], []
    recent_count = min(max(1, int(recent_window)), max(1, len(runs) // 2))
    recent = runs[-recent_count:]
    baseline_pool = runs[:-recent_count]
    if not baseline_pool:
        return recent, recent
    baseline = baseline_pool[-max(1, int(baseline_window)) :]
    return baseline, recent


def _summary(
    runs: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    recent: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_score = _avg_score(baseline)
    recent_score = _avg_score(recent)
    provider_baseline = _sum(baseline, "provider_failure_count")
    provider_recent = _sum(recent, "provider_failure_count")
    video_baseline = _video_failure_count(baseline)
    video_recent = _video_failure_count(recent)
    preference_baseline = _sum(baseline, "preference_dimension_failure_count")
    preference_recent = _sum(recent, "preference_dimension_failure_count")
    quality_issue_baseline = _sum(baseline, "quality_issue_count")
    quality_issue_recent = _sum(recent, "quality_issue_count")
    return {
        "run_ids": [run["run_id"] for run in runs],
        "baseline_run_ids": [run["run_id"] for run in baseline],
        "recent_run_ids": [run["run_id"] for run in recent],
        "baseline_avg_min_quality_score": baseline_score,
        "recent_avg_min_quality_score": recent_score,
        "quality_score_delta": _score_delta(recent_score, baseline_score),
        "baseline_provider_failure_count": provider_baseline,
        "recent_provider_failure_count": provider_recent,
        "baseline_video_generation_failure_count": video_baseline,
        "recent_video_generation_failure_count": video_recent,
        "baseline_preference_dimension_failure_count": preference_baseline,
        "recent_preference_dimension_failure_count": preference_recent,
        "baseline_quality_issue_count": quality_issue_baseline,
        "recent_quality_issue_count": quality_issue_recent,
        "recent_preference_dimensions": _recent_preference_dimensions(recent),
    }


def _degradations(summary: dict[str, Any]) -> list[str]:
    degradations: list[str] = []
    quality_delta = summary.get("quality_score_delta")
    if isinstance(quality_delta, int | float) and quality_delta <= QUALITY_DEGRADATION_THRESHOLD:
        degradations.append("quality_score_degraded")
    if _int(summary.get("recent_video_generation_failure_count")) > _int(
        summary.get("baseline_video_generation_failure_count")
    ):
        degradations.append("video_generation_degraded")
    if _int(summary.get("recent_provider_failure_count")) > _int(summary.get("baseline_provider_failure_count")):
        degradations.append("provider_failures_spiked")
    if _int(summary.get("recent_preference_dimension_failure_count")) > _int(
        summary.get("baseline_preference_dimension_failure_count")
    ):
        degradations.append("preference_dimension_failures_spiked")
    return degradations


def _next_actions(
    summary: dict[str, Any],
    degradations: list[str],
    recent: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if "quality_score_degraded" in degradations:
        evidence_count = max(1, _int(summary.get("recent_quality_issue_count")))
        actions.append(
            _action(
                "increase_candidate_budget",
                "aesthetic",
                "live_quality_trend_quality_score_degraded",
                confidence=0.82,
                evidence_count=evidence_count,
                max_candidate_budget=4,
            )
        )
        actions.append(
            _action(
                "rerank_before_slack",
                "aesthetic",
                "live_quality_trend_recent_quality_low",
                confidence=0.84,
                evidence_count=evidence_count,
            )
        )
    if "video_generation_degraded" in degradations:
        actions.append(
            _action(
                "prefer_image_first_video",
                "provider",
                "live_quality_trend_video_generation_degraded",
                confidence=0.8,
                evidence_count=_int(summary.get("recent_video_generation_failure_count")),
            )
        )
    if "provider_failures_spiked" in degradations:
        actions.append(
            _action(
                "safe_reframe_provider_retry",
                "provider",
                "live_quality_trend_provider_failures_spiked",
                confidence=0.76,
                evidence_count=_int(summary.get("recent_provider_failure_count")),
            )
        )
    if "preference_dimension_failures_spiked" in degradations:
        dimension, issue = _top_recent_preference_failure(recent)
        actions.append(
            _action(
                "repair_low_preference_dimension",
                "aesthetic",
                "live_quality_trend_preference_dimension_low",
                confidence=0.74,
                evidence_count=_int(summary.get("recent_preference_dimension_failure_count")),
                dimension=dimension,
                quality_issue=issue,
                repair_hint=_repair_hint_for_dimension(dimension),
            )
        )
    return _dedupe_actions(actions)


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
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "evidence_count": max(0, int(evidence_count)),
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "live_quality_trends",
        **extra,
    }


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for action in actions:
        key = (
            str(action.get("type") or ""),
            str(action.get("source") or ""),
            str(action.get("dimension") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


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
        entry = {"dimension": dimension, "issue": issue}
        score = _float_or_none(item.get("score"))
        if score is not None:
            entry["score"] = round(max(0.0, min(1.0, score)), 4)
        failures.append(entry)
    return failures


def _recent_preference_dimensions(recent: list[dict[str, Any]]) -> list[str]:
    dimensions: list[str] = []
    for run in recent:
        for failure in run.get("preference_dimension_failures") or []:
            dimension = str(failure.get("dimension") or "").strip()
            if dimension and dimension not in dimensions:
                dimensions.append(dimension)
    return dimensions


def _top_recent_preference_failure(recent: list[dict[str, Any]]) -> tuple[str, str]:
    counts: Counter[tuple[str, str]] = Counter()
    for run in recent:
        for failure in run.get("preference_dimension_failures") or []:
            dimension = str(failure.get("dimension") or "").strip()
            issue = str(failure.get("issue") or "").strip()
            if dimension:
                counts[(dimension, issue)] += 1
    if not counts:
        return "unknown_preference_dimension", ""
    return counts.most_common(1)[0][0]


def _repair_hint_for_dimension(dimension: str) -> str:
    return {
        "subject_beauty": "improve_subject_beauty",
        "face_naturalness": "improve_face_naturalness",
        "glamour_impact": "increase_glamour_impact",
        "fashion_material_quality": "improve_fashion_material_quality",
        "pose_composition": "improve_pose_composition",
        "motion_quality": "improve_motion_quality",
    }.get(dimension, f"improve_{dimension}")


def _avg_score(runs: list[dict[str, Any]]) -> float | None:
    scores = [run["min_quality_score"] for run in runs if isinstance(run.get("min_quality_score"), int | float)]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def _score_delta(recent_score: float | None, baseline_score: float | None) -> float | None:
    if recent_score is None or baseline_score is None:
        return None
    return round(recent_score - baseline_score, 4)


def _video_failure_count(runs: list[dict[str, Any]]) -> int:
    return _sum(runs, "video_missing_after_image_count") + _sum(runs, "image_first_video_source_failure_count")


def _sum(runs: list[dict[str, Any]], key: str) -> int:
    return sum(_int(run.get(key)) for run in runs)


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

