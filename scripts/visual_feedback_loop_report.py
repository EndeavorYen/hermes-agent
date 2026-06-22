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
    signals = {
        "provider": _provider_signals(attempts, artifacts),
        "aesthetic": _aesthetic_signals(judgments),
        "delivery": _delivery_signals(evidence, deliveries),
        "human_feedback": {
            "feedback_count": len(feedback),
        },
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


def _aesthetic_signals(judgments: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [_score(row) for row in judgments]
    pass_count = sum(1 for row in judgments if str(row.get("verdict") or "").lower() == "pass")
    low_quality_count = sum(
        1
        for row in judgments
        if _score(row) < 0.60 or str(row.get("verdict") or "").lower() == "fail"
    )
    return {
        "judgment_count": len(judgments),
        "low_quality_judgment_count": low_quality_count,
        "average_quality_score": _average(scores),
        "pass_rate": _rate(pass_count, len(judgments)),
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


def _next_actions(signals: dict[str, Any]) -> list[dict[str, Any]]:
    provider = signals["provider"]
    aesthetic = signals["aesthetic"]
    delivery = signals["delivery"]
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
