from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


_SUCCESS_STATUSES = {"completed", "success", "succeeded", "sent"}
_POLICY_MARKERS = ("content_moderation", "moderation", "policy", "safety", "guardrail")


def aggregate_visual_strategy_outcomes(
    db_path: str | Path,
    *,
    bucket: str | None = None,
) -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return _empty_report()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "visual_requests"):
            return _empty_report()
        requests = _rows(conn, "visual_requests")
        rankings = _rows(conn, "visual_rankings")
        attempts = _rows(conn, "visual_attempts")
        artifacts = _rows(conn, "visual_artifacts")
        judgments = _rows(conn, "visual_judgments")
        deliveries = _rows(conn, "visual_deliveries")
        feedback = _rows(conn, "visual_feedback")

    request_bucket = {
        _record_id(row, "id", "request_id"): _request_bucket(row)
        for row in requests
        if _record_id(row, "id", "request_id")
    }
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for ranking in rankings:
        request_id = str(ranking.get("request_id") or "")
        if not request_id:
            continue
        group_bucket = request_bucket.get(request_id) or bucket or "unknown"
        if bucket is not None and group_bucket != bucket:
            continue
        strategy_signature = _ranking_strategy_signature(ranking)
        group = groups.setdefault(
            (group_bucket, strategy_signature),
            {
                "bucket": group_bucket,
                "strategy_signature": strategy_signature,
                "request_ids": set(),
                "rankings": [],
            },
        )
        group["request_ids"].add(request_id)
        group["rankings"].append(ranking)

    outcomes = [
        _build_outcome(group, attempts, artifacts, judgments, deliveries, feedback)
        for group in groups.values()
    ]
    outcomes.sort(key=lambda row: (row["bucket"], row["strategy_signature"]))
    return {
        "success": True,
        "bucket_count": len({row["bucket"] for row in outcomes}),
        "strategy_count": len(outcomes),
        "outcomes": outcomes,
    }


def _build_outcome(
    group: dict[str, Any],
    attempts: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    judgments: list[dict[str, Any]],
    deliveries: list[dict[str, Any]],
    feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    request_ids = {str(item) for item in group["request_ids"]}
    group_attempts = [row for row in attempts if str(row.get("request_id") or "") in request_ids]
    group_artifacts = [row for row in artifacts if str(row.get("request_id") or "") in request_ids]
    artifact_ids = {
        _record_id(row, "id", "artifact_id")
        for row in group_artifacts
        if _record_id(row, "id", "artifact_id")
    }
    group_deliveries = [row for row in deliveries if str(row.get("request_id") or "") in request_ids]
    group_judgments = [row for row in judgments if str(row.get("artifact_id") or "") in artifact_ids]
    group_feedback = [row for row in feedback if str(row.get("artifact_id") or "") in artifact_ids]
    provider_health = _provider_health(group_attempts)
    delivery = _delivery_metrics(group_deliveries, group_artifacts)
    quality = _quality_metrics(group_judgments)
    human_feedback = _feedback_metrics(group_feedback)
    retry = _retry_metrics(group_attempts)
    active_learning = _active_learning_metrics(group["rankings"])
    disagreement = _disagreement_metrics(group_judgments, group_feedback)
    confidence = _confidence(
        request_count=len(request_ids),
        attempt_count=provider_health["attempt_count"],
        delivery_count=delivery["delivery_count"],
        judgment_count=quality["judgment_count"],
        feedback_count=human_feedback["feedback_count"],
        disagreement_rate=disagreement["judge_human_disagreement_rate"],
        human_veto_count=human_feedback["human_veto_count"],
    )
    return {
        "bucket": group["bucket"],
        "strategy_signature": group["strategy_signature"],
        "request_count": len(request_ids),
        "provider_health": provider_health,
        "delivery": delivery,
        "quality": quality,
        "human_feedback": human_feedback,
        "retry": retry,
        "active_learning": active_learning,
        "disagreement": disagreement,
        "confidence": confidence,
    }


def _provider_health(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    providers: dict[str, dict[str, int]] = {}
    success_count = 0
    policy_failure_count = 0
    for attempt in attempts:
        provider = str(attempt.get("provider") or "unknown")
        model = str(attempt.get("model") or "unknown")
        key = f"{provider}:{model}"
        item = providers.setdefault(
            key,
            {
                "attempt_count": 0,
                "generation_success_count": 0,
                "policy_failure_count": 0,
            },
        )
        item["attempt_count"] += 1
        if _attempt_success(attempt):
            item["generation_success_count"] += 1
            success_count += 1
        if _policy_failure(attempt):
            item["policy_failure_count"] += 1
            policy_failure_count += 1
    provider_records = {
        key: {
            "attempt_count": value["attempt_count"],
            "generation_success_rate": _rate(
                value["generation_success_count"],
                value["attempt_count"],
            ),
            "policy_failure_rate": _rate(
                value["policy_failure_count"],
                value["attempt_count"],
            ),
        }
        for key, value in sorted(providers.items())
    }
    return {
        "attempt_count": len(attempts),
        "generation_success_count": success_count,
        "generation_success_rate": _rate(success_count, len(attempts)),
        "policy_failure_count": policy_failure_count,
        "policy_failure_rate": _rate(policy_failure_count, len(attempts)),
        "providers": provider_records,
    }


def _delivery_metrics(
    deliveries: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    artifact_by_id = {
        _record_id(row, "id", "artifact_id"): row
        for row in artifacts
        if _record_id(row, "id", "artifact_id")
    }
    sent = [row for row in deliveries if _delivery_status(row) == "sent"]
    duplicate_count = 0
    seen: dict[tuple[str, str], int] = {}
    for delivery in sent:
        artifact = artifact_by_id.get(str(delivery.get("artifact_id") or ""))
        identity = _artifact_identity(artifact or {})
        if not identity:
            continue
        destination = _delivery_destination(delivery)
        key = (destination, identity)
        seen[key] = seen.get(key, 0) + 1
    duplicate_count = sum(count - 1 for count in seen.values() if count > 1)
    missing_source_count = sum(1 for artifact in artifacts if _missing_source_metadata(artifact))
    return {
        "delivery_count": len(deliveries),
        "successful_delivery_count": len(sent),
        "delivery_success_rate": _rate(len(sent), len(deliveries)),
        "duplicate_delivery_count": duplicate_count,
        "missing_source_metadata_count": missing_source_count,
    }


def _quality_metrics(judgments: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [_coerce_float(_score_value(row)) for row in judgments]
    pass_count = sum(1 for row in judgments if str(row.get("verdict") or "").lower() == "pass")
    return {
        "judgment_count": len(judgments),
        "average_confidence": _average(scores),
        "pass_rate": _rate(pass_count, len(judgments)),
    }


def _feedback_metrics(feedback: list[dict[str, Any]]) -> dict[str, Any]:
    polarities = [_coerce_float(row.get("polarity")) for row in feedback]
    positive = sum(1 for value in polarities if value > 0)
    negative = sum(1 for value in polarities if value < 0)
    veto = sum(1 for row in feedback if _human_veto(row))
    return {
        "feedback_count": len(feedback),
        "positive_count": positive,
        "negative_count": negative,
        "average_polarity": _average(polarities),
        "human_veto_count": veto,
    }


def _retry_metrics(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    retries = [row for row in attempts if _is_retry(row)]
    success = sum(1 for row in retries if _attempt_success(row))
    return {
        "retry_attempt_count": len(retries),
        "retry_success_count": success,
        "retry_success_rate": _rate(success, len(retries)),
    }


def _active_learning_metrics(rankings: list[dict[str, Any]]) -> dict[str, Any]:
    ask_count = 0
    for ranking in rankings:
        metadata = _json_value(ranking.get("metadata", ranking.get("rationale_json")))
        active = metadata.get("active_learning") if isinstance(metadata, dict) else None
        action = str(active.get("action") if isinstance(active, dict) else ranking.get("decision") or "")
        if action == "ask_user" or str(ranking.get("decision") or "") == "ask":
            ask_count += 1
    return {
        "ranking_count": len(rankings),
        "ask_user_count": ask_count,
        "ask_user_rate": _rate(ask_count, len(rankings)),
    }


def _disagreement_metrics(
    judgments: list[dict[str, Any]],
    feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    judgment_scores: dict[str, list[float]] = {}
    for row in judgments:
        artifact_id = str(row.get("artifact_id") or "")
        if artifact_id:
            judgment_scores.setdefault(artifact_id, []).append(_coerce_float(_score_value(row)))
    feedback_polarities: dict[str, list[float]] = {}
    for row in feedback:
        artifact_id = str(row.get("artifact_id") or "")
        if artifact_id:
            feedback_polarities.setdefault(artifact_id, []).append(_coerce_float(row.get("polarity")))

    comparable = 0
    disagree = 0
    for artifact_id, scores in judgment_scores.items():
        if artifact_id not in feedback_polarities:
            continue
        comparable += 1
        judge_score = _average(scores)
        human_polarity = _average(feedback_polarities[artifact_id])
        if (judge_score >= 0.65 and human_polarity < 0) or (judge_score < 0.5 and human_polarity > 0):
            disagree += 1
    return {
        "comparable_count": comparable,
        "judge_human_disagreement_count": disagree,
        "judge_human_disagreement_rate": _rate(disagree, comparable),
    }


def _confidence(
    *,
    request_count: int,
    attempt_count: int,
    delivery_count: int,
    judgment_count: int,
    feedback_count: int,
    disagreement_rate: float,
    human_veto_count: int,
) -> float:
    sample_units = (
        request_count
        + attempt_count * 0.5
        + delivery_count * 0.25
        + judgment_count * 0.5
        + feedback_count * 0.5
    )
    sample_confidence = min(1.0, sample_units / 20.0)
    disagreement_penalty = max(0.0, 1.0 - disagreement_rate * 0.7)
    veto_rate = _rate(human_veto_count, feedback_count)
    veto_penalty = max(0.5, 1.0 - veto_rate * 0.5)
    return round(sample_confidence * disagreement_penalty * veto_penalty, 4)


def _request_bucket(row: dict[str, Any]) -> str:
    for column in ("metadata", "policy_context_json", "normalized_intent", "normalized_intent_json"):
        value = _json_value(row.get(column))
        found = _find_bucket(value)
        if found:
            return found
    return "unknown"


def _ranking_strategy_signature(row: dict[str, Any]) -> str:
    metadata = _json_value(row.get("metadata", row.get("rationale_json")))
    if isinstance(metadata, dict):
        direct = metadata.get("strategy_signature")
        if isinstance(direct, str) and direct:
            return direct
        plan = metadata.get("strategy_plan")
        if isinstance(plan, dict):
            planned = plan.get("strategy_signature")
            if isinstance(planned, str) and planned:
                return planned
    return "unknown"


def _find_bucket(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("intent_signature", "bucket"):
            item = value.get(key)
            if isinstance(item, str) and item:
                return item
        for item in value.values():
            found = _find_bucket(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_bucket(item)
            if found:
                return found
    return None


def _attempt_success(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    if status in _SUCCESS_STATUSES:
        return True
    return not status and not row.get("error_type") and not row.get("provider_error_type")


def _policy_failure(row: dict[str, Any]) -> bool:
    haystack = f"{row.get('error_type') or row.get('provider_error_type') or ''} {row.get('error_message') or row.get('provider_error_message') or ''}".lower()
    return any(marker in haystack for marker in _POLICY_MARKERS)


def _delivery_status(row: dict[str, Any]) -> str:
    return str(row.get("delivery_status") or row.get("status") or "").lower()


def _delivery_destination(row: dict[str, Any]) -> str:
    return str(
        row.get("destination")
        or row.get("destination_id")
        or row.get("platform")
        or "unknown"
    )


def _artifact_identity(row: dict[str, Any]) -> str:
    for column in ("content_hash", "source_url", "uri", "local_path"):
        value = row.get(column)
        if isinstance(value, str) and value:
            return value
    return ""


def _missing_source_metadata(row: dict[str, Any]) -> bool:
    if not row.get("kind") or not row.get("freshness_status"):
        return True
    return not any(row.get(column) for column in ("local_path", "uri", "source_url"))


def _score_value(row: dict[str, Any]) -> Any:
    return row.get("score", row.get("confidence"))


def _human_veto(row: dict[str, Any]) -> bool:
    parsed = _json_value(row.get("parsed", row.get("parsed_json")))
    if isinstance(parsed, dict) and parsed.get("veto") is True:
        return True
    if _coerce_float(row.get("polarity")) < 0:
        return True
    text = str(row.get("feedback_text") or row.get("raw_text") or "")
    return any(marker in text for marker in ("退貨", "差評", "不行"))


def _is_retry(row: dict[str, Any]) -> bool:
    metadata = _json_value(row.get("metadata"))
    return isinstance(metadata, dict) and "retry_of" in metadata


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    return [
        {key: _decode_value(row[key]) for key in row.keys()}
        for row in conn.execute(f"SELECT * FROM {table}").fetchall()
    ]


def _decode_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _record_id(row: dict[str, Any], *columns: str) -> str:
    for column in columns:
        value = row.get(column)
        if isinstance(value, str) and value:
            return value
    return ""


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, (dict, list)) else {}


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _empty_report() -> dict[str, Any]:
    return {
        "success": True,
        "bucket_count": 0,
        "strategy_count": 0,
        "outcomes": [],
    }
