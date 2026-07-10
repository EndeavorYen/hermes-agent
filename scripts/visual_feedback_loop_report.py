from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.tracking import default_visual_ledger_path
from scripts.visual_evidence_report import build_visual_evidence_report


_POLICY_MARKERS = ("content_moderation", "moderation", "policy", "safety", "guardrail")
_SUCCESS_STATUSES = {"completed", "success", "succeeded", "sent"}
_PREFERENCE_DIMENSION_THRESHOLD = 0.60
_ISSUE_TO_DIMENSION = {
    "subject_not_attractive": "subject_beauty",
    "not_beautiful": "subject_beauty",
    "face_unnatural": "face_naturalness",
    "stockings_bad": "fashion_material_quality",
    "composition_bad": "pose_composition",
    "motion_bad": "motion_quality",
    "static_video": "motion_quality",
    "aspect_integrity_bad": "motion_quality",
}
_FEEDBACK_ISSUE_TO_REPAIR_ISSUE = {
    "static_video": "motion_bad",
}
_DIMENSION_TO_ISSUE = {
    "subject_beauty": "subject_not_attractive",
    "face_naturalness": "face_unnatural",
    "fashion_material_quality": "stockings_bad",
    "pose_composition": "composition_bad",
    "motion_quality": "motion_bad",
}
_DIMENSION_REPAIR_HINT = {
    "subject_beauty": "improve_subject_beauty",
    "face_naturalness": "improve_face_naturalness",
    "fashion_material_quality": "improve_fashion_material_quality",
    "pose_composition": "improve_pose_composition",
    "motion_quality": "improve_motion_quality",
}
_PREFERENCE_DIMENSION_ORDER = {
    "subject_beauty": 0,
    "face_naturalness": 1,
    "glamour_impact": 2,
    "fashion_material_quality": 3,
    "pose_composition": 4,
    "motion_quality": 5,
}


def build_visual_feedback_loop_report(db_path: str | Path) -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return _empty_report(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "visual_requests"):
            return _empty_report(db_path)
        attempts = _rows(conn, "visual_attempts")
        artifacts = _rows(conn, "visual_artifacts")
        judgments = _rows(conn, "visual_judgments")
        deliveries = _rows(conn, "visual_deliveries")
        feedback = _rows(conn, "visual_feedback")
        request_count = _count(conn, "visual_requests")

    evidence = _safe_evidence_report(db_path)
    human_feedback = _human_feedback_signals(feedback)
    signals = {
        "provider": _provider_signals(attempts, artifacts),
        "aesthetic": _aesthetic_signals(
            judgments,
            feedback_dimension_failures=human_feedback["preference_dimension_failures"],
        ),
        "delivery": _delivery_signals(evidence, deliveries),
        "repair": _repair_signals(attempts, artifacts, judgments, deliveries),
        "human_feedback": human_feedback,
    }
    counts = {
        "request_count": request_count,
        "attempt_count": len(attempts),
        "artifact_count": len(artifacts),
        "judgment_count": len(judgments),
        "delivery_count": len(deliveries),
        "human_feedback_count": len(feedback),
    }
    next_actions = _next_actions(signals)
    failures = _failures(signals)
    automated_action_count = sum(
        1 for action in next_actions if action.get("requires_human_feedback") is not True
    )
    return {
        "success": not failures,
        "failures": failures,
        "db_path": str(db_path),
        "counts": counts,
        "signals": signals,
        "next_actions": next_actions,
        "self_review": {
            "reduces_human_intervention": automated_action_count > 0,
            "automated_action_count": automated_action_count,
            "human_feedback_required": automated_action_count == 0,
            "provider_and_aesthetic_tracks_separated": True,
            "privacy_safe": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a visual feedback-loop report.")
    parser.add_argument("--db-path", type=Path, default=default_visual_ledger_path())
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)

    payload = build_visual_feedback_loop_report(args.db_path)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual feedback loop report {status}")
    if args.allow_failures:
        return 0
    return 0 if payload["success"] else 1


def _provider_signals(
    attempts: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    generation_success_count = sum(1 for attempt in attempts if _attempt_success(attempt))
    generation_failure_count = sum(1 for attempt in attempts if _attempt_failure(attempt))
    policy_failure_count = sum(1 for attempt in attempts if _policy_failure(attempt))
    video_failure_count = sum(1 for attempt in attempts if _attempt_failure(attempt) and _video_attempt(attempt))
    return {
        "generation_success_count": generation_success_count,
        "generation_failure_count": generation_failure_count,
        "generation_success_rate": _rate(generation_success_count, len(attempts)),
        "policy_failure_count": policy_failure_count,
        "policy_failure_rate": _rate(policy_failure_count, len(attempts)),
        "video_failure_count": video_failure_count,
        "image_artifact_count": sum(1 for artifact in artifacts if str(artifact.get("kind") or "") == "image"),
        "video_artifact_count": sum(1 for artifact in artifacts if str(artifact.get("kind") or "") == "video"),
    }


def _aesthetic_signals(
    judgments: list[dict[str, Any]],
    *,
    feedback_dimension_failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scores = [_score(row) for row in judgments]
    pass_count = sum(1 for row in judgments if str(row.get("verdict") or "").lower() == "pass")
    low_quality_count = sum(
        1
        for row in judgments
        if _score(row) < 0.60 or str(row.get("verdict") or "").lower() == "fail"
    )
    preference_dimension_failures = _merge_preference_dimension_failures(
        _preference_dimension_failures(judgments),
        feedback_dimension_failures or [],
    )
    return {
        "judgment_count": len(judgments),
        "low_quality_judgment_count": low_quality_count,
        "average_quality_score": _average(scores),
        "pass_rate": _rate(pass_count, len(judgments)),
        "quality_issue_counts": _quality_issue_counts(judgments),
        "preference_dimension_failures": preference_dimension_failures,
    }


def _human_feedback_signals(feedback: list[dict[str, Any]]) -> dict[str, Any]:
    issue_counts: dict[str, int] = {}
    dimension_failures: dict[str, dict[str, Any]] = {}
    feedback_with_issues_count = 0
    negative_feedback_count = 0
    for row in feedback:
        issues = _feedback_issues(row)
        if issues:
            feedback_with_issues_count += 1
        if _float(row.get("polarity")) < 0:
            negative_feedback_count += 1
        seen_dimensions: set[str] = set()
        for issue in issues:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
            dimension = _ISSUE_TO_DIMENSION.get(issue)
            if not dimension or dimension in seen_dimensions:
                continue
            seen_dimensions.add(dimension)
            _record_dimension_failure(
                dimension_failures,
                dimension=dimension,
                issue=_FEEDBACK_ISSUE_TO_REPAIR_ISSUE.get(issue, issue),
                score=None,
            )
    return {
        "feedback_count": len(feedback),
        "negative_feedback_count": negative_feedback_count,
        "feedback_with_issues_count": feedback_with_issues_count,
        "feedback_issue_counts": dict(sorted(issue_counts.items())),
        "preference_dimension_failures": _ordered_dimension_failures(dimension_failures),
    }


def _delivery_signals(evidence: dict[str, Any], deliveries: list[dict[str, Any]]) -> dict[str, Any]:
    proof = evidence.get("proof") if isinstance(evidence.get("proof"), dict) else {}
    sent_count = sum(1 for row in deliveries if _delivery_status(row) == "sent")
    failed_count = sum(1 for row in deliveries if _delivery_status(row) in {"failed", "error"})
    return {
        "delivery_count": len(deliveries),
        "successful_delivery_count": sent_count,
        "failed_delivery_count": failed_count,
        "duplicate_delivery_count": _int(proof.get("duplicate_artifact_delivery_count")),
        "missing_source_metadata_count": _int(proof.get("missing_source_metadata_count")),
    }


def _repair_signals(
    attempts: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    judgments: list[dict[str, Any]],
    deliveries: list[dict[str, Any]],
) -> dict[str, Any]:
    repair_attempt_ids = {
        _record_id(attempt)
        for attempt in attempts
        if _record_id(attempt) and _quality_repair_metadata(attempt)
    }
    repair_artifact_ids = {
        _record_id(artifact)
        for artifact in artifacts
        if str(artifact.get("attempt_id") or "") in repair_attempt_ids and _record_id(artifact)
    }
    successful_judgments = {
        str(judgment.get("artifact_id") or "")
        for judgment in judgments
        if str(judgment.get("artifact_id") or "") in repair_artifact_ids
        and _score(judgment) >= 0.60
        and str(judgment.get("verdict") or "").lower() != "fail"
    }
    delivered_repair_artifacts = {
        str(delivery.get("artifact_id") or "")
        for delivery in deliveries
        if str(delivery.get("artifact_id") or "") in repair_artifact_ids
        and _delivery_status(delivery) == "sent"
    }
    reasons: dict[str, int] = {}
    for attempt in attempts:
        metadata = _quality_repair_metadata(attempt)
        if not metadata:
            continue
        reason = str(metadata.get("reason") or "unknown")
        reasons[reason] = reasons.get(reason, 0) + 1
    attempt_count = len(repair_attempt_ids)
    success_count = len(successful_judgments)
    delivery_success_count = len(delivered_repair_artifacts)
    return {
        "quality_repair_attempt_count": attempt_count,
        "quality_repair_success_count": success_count,
        "quality_repair_delivery_success_count": delivery_success_count,
        "quality_repair_success_rate": _rate(success_count, attempt_count),
        "quality_repair_delivery_success_rate": _rate(delivery_success_count, attempt_count),
        "quality_repair_reasons": reasons,
    }


def _next_actions(signals: dict[str, Any]) -> list[dict[str, Any]]:
    provider = signals["provider"]
    aesthetic = signals["aesthetic"]
    delivery = signals["delivery"]
    repair = signals.get("repair", {})
    actions: list[dict[str, Any]] = []
    if delivery["duplicate_delivery_count"] > 0:
        actions.append(
            _action(
                "repair_delivery_dedup",
                "delivery",
                "sent_duplicate_artifacts_detected",
                confidence=1.0,
                evidence_count=delivery["duplicate_delivery_count"],
                blocks_delivery=True,
            )
        )
    if delivery["missing_source_metadata_count"] > 0:
        actions.append(
            _action(
                "repair_artifact_source_metadata",
                "delivery",
                "artifact_delivery_records_missing_source_metadata",
                confidence=1.0,
                evidence_count=delivery["missing_source_metadata_count"],
                blocks_delivery=True,
            )
        )
    if (
        aesthetic["low_quality_judgment_count"] > 0
        and provider["generation_success_count"] > 0
    ):
        actions.append(
            _action(
                "increase_candidate_budget",
                "aesthetic",
                "provider_renders_but_auto_judge_rejected_quality",
                confidence=0.65,
                evidence_count=aesthetic["low_quality_judgment_count"],
                max_candidate_budget=4,
            )
        )
        actions.append(
            _action(
                "rerank_before_slack",
                "aesthetic",
                "do_not_ship_low_scoring_candidates_without_ranking",
                confidence=0.70,
                evidence_count=aesthetic["low_quality_judgment_count"],
            )
        )
    for failure in aesthetic.get("preference_dimension_failures") or []:
        if not isinstance(failure, dict):
            continue
        dimension = str(failure.get("dimension") or "").strip()
        if not dimension:
            continue
        actions.append(
            _action(
                "repair_low_preference_dimension",
                "aesthetic",
                "feedback_loop_preference_dimension_low",
                confidence=0.74,
                evidence_count=_int(failure.get("count")) or 1,
                dimension=dimension,
                quality_issue=str(failure.get("issue") or _DIMENSION_TO_ISSUE.get(dimension, "")).strip(),
                repair_hint=_DIMENSION_REPAIR_HINT.get(dimension, f"improve_{dimension}"),
                modalities=_modalities_for_dimension(dimension),
            )
        )
    if provider["video_failure_count"] > 0 and provider["image_artifact_count"] > 0:
        actions.append(
            _action(
                "prefer_image_first_video",
                "provider",
                "video_generation_failed_after_image_source_exists",
                confidence=0.75,
                evidence_count=provider["video_failure_count"],
            )
        )
    if provider["policy_failure_count"] > 0:
        actions.append(
            _action(
                "safe_reframe_provider_retry",
                "provider",
                "provider_policy_failure_requires_prompt_reframe",
                confidence=0.70,
                evidence_count=provider["policy_failure_count"],
            )
        )
    repair_attempt_count = _int(repair.get("quality_repair_attempt_count"))
    repair_success_rate = _float(repair.get("quality_repair_success_rate"))
    repair_delivery_success_rate = _float(repair.get("quality_repair_delivery_success_rate"))
    if repair_attempt_count > 0 and repair_success_rate >= 0.60:
        actions.append(
            _action(
                "prefer_quality_repair_retry",
                "repair",
                "quality_repair_retry_has_positive_success_rate",
                confidence=min(0.90, 0.55 + repair_success_rate * 0.35),
                evidence_count=repair_attempt_count,
                success_rate=repair_success_rate,
                delivery_success_rate=repair_delivery_success_rate,
            )
        )
    if repair_attempt_count >= 3 and repair_success_rate < 0.50:
        actions.append(
            _action(
                "escalate_quality_repair_strategy",
                "repair",
                "quality_repair_retry_success_rate_low",
                confidence=max(0.60, 1.0 - repair_success_rate),
                evidence_count=repair_attempt_count,
                success_rate=repair_success_rate,
                max_candidate_budget=4,
            )
        )
    return actions


def _action(
    action_type: str,
    track: str,
    reason: str,
    *,
    confidence: float,
    evidence_count: int,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "type": action_type,
        "track": track,
        "reason": reason,
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "evidence_count": int(evidence_count),
        "requires_human_feedback": False,
        "activation_status": "next_run",
    }
    payload.update(extra)
    return payload


def _failures(signals: dict[str, Any]) -> list[str]:
    delivery = signals["delivery"]
    failures: list[str] = []
    if delivery["duplicate_delivery_count"] > 0:
        failures.append("duplicate_delivery")
    if delivery["missing_source_metadata_count"] > 0:
        failures.append("missing_source_metadata")
    return failures


def _safe_evidence_report(db_path: Path) -> dict[str, Any]:
    try:
        return build_visual_evidence_report(db_path)
    except sqlite3.Error:
        return {"proof": {"duplicate_artifact_delivery_count": 0, "missing_source_metadata_count": 0}}


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    return [
        {key: _decode_value(row[key]) for key in row.keys()}
        for row in conn.execute(f"SELECT * FROM {table}").fetchall()
    ]


def _count(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0])


def _attempt_success(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    return status in _SUCCESS_STATUSES or (
        not status and not row.get("error_type") and not row.get("provider_error_type")
    )


def _attempt_failure(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    return status in {"failed", "error", "timeout"} or bool(
        row.get("error_type")
        or row.get("provider_error_type")
        or row.get("error_message")
        or row.get("provider_error_message")
    )


def _policy_failure(row: dict[str, Any]) -> bool:
    haystack = (
        f"{row.get('error_type') or row.get('provider_error_type') or ''} "
        f"{row.get('error_message') or row.get('provider_error_message') or ''}"
    ).lower()
    return any(marker in haystack for marker in _POLICY_MARKERS)


def _video_attempt(row: dict[str, Any]) -> bool:
    haystack = (
        f"{row.get('model') or ''} "
        f"{row.get('parameters_requested') or row.get('parameters_requested_json') or ''} "
        f"{row.get('parameters_effective') or row.get('parameters_effective_json') or ''}"
    ).lower()
    return "video" in haystack or "duration" in haystack


def _delivery_status(row: dict[str, Any]) -> str:
    return str(row.get("delivery_status") or row.get("status") or "").lower()


def _score(row: dict[str, Any]) -> float:
    return _float(row.get("score", row.get("confidence")))


def _quality_issue_counts(judgments: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in judgments:
        for issue in _quality_issues(row):
            counts[issue] = counts.get(issue, 0) + 1
    return dict(sorted(counts.items()))


def _preference_dimension_failures(judgments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: dict[str, dict[str, Any]] = {}
    for row in judgments:
        details = _judgment_details(row)
        dimensions = details.get("preference_dimensions")
        seen_dimensions: set[str] = set()
        if isinstance(dimensions, dict):
            for dimension, raw_score in dimensions.items():
                score = _float_or_none(raw_score)
                if score is None or score >= _PREFERENCE_DIMENSION_THRESHOLD:
                    continue
                dimension_text = str(dimension)
                seen_dimensions.add(dimension_text)
                _record_dimension_failure(
                    failures,
                    dimension=dimension_text,
                    issue=_DIMENSION_TO_ISSUE.get(dimension_text, ""),
                    score=score,
                )
        for issue in _quality_issues(row):
            dimension = _ISSUE_TO_DIMENSION.get(issue)
            if not dimension:
                continue
            score = _float_or_none(dimensions.get(dimension)) if isinstance(dimensions, dict) else None
            if dimension in seen_dimensions:
                _record_dimension_issue(failures, dimension=dimension, issue=issue, score=score)
            else:
                seen_dimensions.add(dimension)
                _record_dimension_failure(
                    failures,
                    dimension=dimension,
                    issue=issue,
                    score=score,
                )
    return _ordered_dimension_failures(failures)


def _merge_preference_dimension_failures(
    *groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            dimension = str(item.get("dimension") or "").strip()
            if not dimension:
                continue
            entry = merged.setdefault(
                dimension,
                {
                    "dimension": dimension,
                    "issue": str(item.get("issue") or _DIMENSION_TO_ISSUE.get(dimension, "")).strip(),
                    "score": _float_or_none(item.get("score")),
                    "count": 0,
                },
            )
            entry["count"] = _int(entry.get("count")) + (_int(item.get("count")) or 1)
            issue = str(item.get("issue") or "").strip()
            if issue and not entry.get("issue"):
                entry["issue"] = issue
            score = _float_or_none(item.get("score"))
            if score is not None:
                current = _float_or_none(entry.get("score"))
                entry["score"] = score if current is None else min(current, score)
    return _ordered_dimension_failures(merged)


def _ordered_dimension_failures(
    failures: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        failures.values(),
        key=lambda item: (
            -_int(item.get("count")),
            _PREFERENCE_DIMENSION_ORDER.get(str(item.get("dimension") or ""), 99),
            str(item.get("dimension") or ""),
        ),
    )


def _record_dimension_failure(
    failures: dict[str, dict[str, Any]],
    *,
    dimension: str,
    issue: str,
    score: float | None,
) -> None:
    dimension = dimension.strip()
    if not dimension:
        return
    entry = failures.setdefault(
        dimension,
        {
            "dimension": dimension,
            "issue": issue or _DIMENSION_TO_ISSUE.get(dimension, ""),
            "score": score,
            "count": 0,
        },
    )
    entry["count"] = _int(entry.get("count")) + 1
    if issue and not entry.get("issue"):
        entry["issue"] = issue
    if score is not None:
        current = _float_or_none(entry.get("score"))
        entry["score"] = score if current is None else min(current, score)


def _record_dimension_issue(
    failures: dict[str, dict[str, Any]],
    *,
    dimension: str,
    issue: str,
    score: float | None,
) -> None:
    entry = failures.get(dimension)
    if entry is None:
        _record_dimension_failure(failures, dimension=dimension, issue=issue, score=score)
        return
    if issue and not entry.get("issue"):
        entry["issue"] = issue
    if score is not None:
        current = _float_or_none(entry.get("score"))
        entry["score"] = score if current is None else min(current, score)


def _quality_issues(row: dict[str, Any]) -> list[str]:
    details = _judgment_details(row)
    issues = details.get("quality_issues")
    if not isinstance(issues, list):
        return []
    return [str(issue).strip() for issue in issues if str(issue).strip()]


def _feedback_issues(row: dict[str, Any]) -> list[str]:
    parsed = row.get("parsed")
    if not isinstance(parsed, dict):
        parsed = row.get("parsed_json") if isinstance(row.get("parsed_json"), dict) else {}
    issues = parsed.get("issues") if isinstance(parsed, dict) else None
    if not isinstance(issues, list):
        return []
    return [str(issue).strip() for issue in issues if str(issue).strip()]


def _judgment_details(row: dict[str, Any]) -> dict[str, Any]:
    details = row.get("details")
    if isinstance(details, dict):
        return details
    details = row.get("details_json")
    return details if isinstance(details, dict) else {}


def _modalities_for_dimension(dimension: str) -> list[str]:
    if dimension == "motion_quality":
        return ["video"]
    return ["image"]


def _record_id(row: dict[str, Any]) -> str:
    for column in ("id", "attempt_id", "artifact_id", "judgment_id", "delivery_id"):
        value = row.get(column)
        if isinstance(value, str) and value:
            return value
    return ""


def _quality_repair_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
    quality_repair = metadata.get("quality_repair") if isinstance(metadata, dict) else None
    return quality_repair if isinstance(quality_repair, dict) else {}


def _decode_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _empty_report(db_path: Path) -> dict[str, Any]:
    return {
        "success": True,
        "failures": [],
        "db_path": str(db_path),
        "counts": {
            "request_count": 0,
            "attempt_count": 0,
            "artifact_count": 0,
            "judgment_count": 0,
            "delivery_count": 0,
            "human_feedback_count": 0,
        },
        "signals": {
            "provider": {
                "generation_success_count": 0,
                "generation_failure_count": 0,
                "generation_success_rate": 0.0,
                "policy_failure_count": 0,
                "policy_failure_rate": 0.0,
                "video_failure_count": 0,
                "image_artifact_count": 0,
                "video_artifact_count": 0,
            },
            "aesthetic": {
                "judgment_count": 0,
                "low_quality_judgment_count": 0,
                "average_quality_score": 0.0,
                "pass_rate": 0.0,
            },
            "delivery": {
                "delivery_count": 0,
                "successful_delivery_count": 0,
                "failed_delivery_count": 0,
                "duplicate_delivery_count": 0,
                "missing_source_metadata_count": 0,
            },
            "repair": {
                "quality_repair_attempt_count": 0,
                "quality_repair_success_count": 0,
                "quality_repair_delivery_success_count": 0,
                "quality_repair_success_rate": 0.0,
                "quality_repair_delivery_success_rate": 0.0,
                "quality_repair_reasons": {},
            },
            "human_feedback": {"feedback_count": 0},
        },
        "next_actions": [],
        "self_review": {
            "reduces_human_intervention": False,
            "automated_action_count": 0,
            "human_feedback_required": True,
            "provider_and_aesthetic_tracks_separated": True,
            "privacy_safe": True,
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
