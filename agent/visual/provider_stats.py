from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger


_SUCCESS_STATUSES = {"completed", "success", "succeeded", "sent"}
_POLICY_ERROR_MARKERS = (
    "content_moderation",
    "moderation",
    "policy",
    "safety",
    "guardrail",
)


@dataclass(frozen=True)
class ProviderReliability:
    provider_model: str
    attempt_count: int
    generation_success_rate: float
    delivery_success_rate: float
    policy_failure_rate: float

    def to_record(self) -> dict[str, Any]:
        return {
            "provider_model": self.provider_model,
            "attempt_count": self.attempt_count,
            "generation_success_rate": self.generation_success_rate,
            "delivery_success_rate": self.delivery_success_rate,
            "policy_failure_rate": self.policy_failure_rate,
        }


def compute_provider_reliability(
    ledger: VisualAttemptLedger,
    *,
    bucket: str | None = None,
    request_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    with sqlite3.connect(ledger.db_path) as conn:
        conn.row_factory = sqlite3.Row
        request_ids = _matching_request_ids(conn, bucket=bucket, request_id=request_id)
        attempts = _attempt_rows(conn, request_ids=request_ids)
        deliveries = _delivery_rows(conn, request_ids=request_ids)

    attempt_key_by_id: dict[str, str] = {}
    grouped: dict[str, dict[str, int]] = {}
    for attempt in attempts:
        attempt_id = _row_value(attempt, "id", "attempt_id")
        provider = str(_row_value(attempt, "provider") or "unknown")
        model = str(_row_value(attempt, "model") or "unknown")
        provider_model = f"{provider}:{model}"
        if attempt_id:
            attempt_key_by_id[str(attempt_id)] = provider_model
        group = grouped.setdefault(
            provider_model,
            {
                "attempt_count": 0,
                "generation_success_count": 0,
                "policy_failure_count": 0,
                "delivery_count": 0,
                "delivery_success_count": 0,
            },
        )
        group["attempt_count"] += 1
        if _is_generation_success(attempt):
            group["generation_success_count"] += 1
        if _is_policy_failure(attempt):
            group["policy_failure_count"] += 1

    for delivery in deliveries:
        attempt_id = _row_value(delivery, "attempt_id")
        provider_model = attempt_key_by_id.get(str(attempt_id)) if attempt_id else None
        if provider_model is None:
            continue
        group = grouped.setdefault(
            provider_model,
            {
                "attempt_count": 0,
                "generation_success_count": 0,
                "policy_failure_count": 0,
                "delivery_count": 0,
                "delivery_success_count": 0,
            },
        )
        group["delivery_count"] += 1
        if _delivery_status(delivery) == "sent":
            group["delivery_success_count"] += 1

    return {
        provider_model: ProviderReliability(
            provider_model=provider_model,
            attempt_count=counts["attempt_count"],
            generation_success_rate=_rate(
                counts["generation_success_count"],
                counts["attempt_count"],
            ),
            delivery_success_rate=_rate(
                counts["delivery_success_count"],
                counts["delivery_count"],
            ),
            policy_failure_rate=_rate(
                counts["policy_failure_count"],
                counts["attempt_count"],
            ),
        ).to_record()
        for provider_model, counts in sorted(grouped.items())
    }


def top_provider_reliability(
    ledger: VisualAttemptLedger,
    *,
    bucket: str | None = None,
    request_id: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    stats = compute_provider_reliability(ledger, bucket=bucket, request_id=request_id)
    ranked = sorted(
        stats.values(),
        key=lambda row: (
            -float(row["generation_success_rate"]),
            -float(row["delivery_success_rate"]),
            float(row["policy_failure_rate"]),
            -int(row["attempt_count"]),
            str(row["provider_model"]),
        ),
    )
    return ranked[:limit]


def _matching_request_ids(
    conn: sqlite3.Connection,
    *,
    bucket: str | None,
    request_id: str | None,
) -> set[str] | None:
    if bucket is None and request_id is None:
        return None
    columns = _column_names(conn, "visual_requests")
    id_column = _first_column(columns, "id", "request_id")
    if request_id is not None and bucket is None:
        return {request_id}
    metadata_columns = [
        column
        for column in ("metadata", "policy_context_json", "normalized_intent_json", "normalized_intent")
        if column in columns
    ]
    if id_column is None:
        return set()

    rows = conn.execute(
        f"SELECT {id_column}, {', '.join(metadata_columns) if metadata_columns else 'NULL AS empty_metadata'} "
        "FROM visual_requests"
    ).fetchall()
    matched: set[str] = set()
    for row in rows:
        for column in metadata_columns:
            if _json_contains_bucket(row[column], bucket):
                row_id = str(row[id_column])
                if request_id is None or row_id == request_id:
                    matched.add(row_id)
                break
    return matched


def _attempt_rows(
    conn: sqlite3.Connection,
    *,
    request_ids: set[str] | None,
) -> list[sqlite3.Row]:
    if not _table_exists(conn, "visual_attempts"):
        return []
    if request_ids is not None and not request_ids:
        return []
    sql = "SELECT * FROM visual_attempts"
    params: tuple[str, ...] = ()
    if request_ids is not None:
        placeholders = ", ".join("?" for _ in request_ids)
        sql += f" WHERE request_id IN ({placeholders})"
        params = tuple(sorted(request_ids))
    return conn.execute(sql, params).fetchall()


def _delivery_rows(
    conn: sqlite3.Connection,
    *,
    request_ids: set[str] | None,
) -> list[sqlite3.Row]:
    if not _table_exists(conn, "visual_deliveries"):
        return []
    if request_ids is not None and not request_ids:
        return []
    sql = "SELECT * FROM visual_deliveries"
    params: tuple[str, ...] = ()
    if request_ids is not None:
        placeholders = ", ".join("?" for _ in request_ids)
        sql += f" WHERE request_id IN ({placeholders})"
        params = tuple(sorted(request_ids))
    return conn.execute(sql, params).fetchall()


def _json_contains_bucket(value: Any, bucket: str) -> bool:
    if not value:
        return False
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return False
    if isinstance(value, dict):
        if value.get("intent_signature") == bucket or value.get("bucket") == bucket:
            return True
        return any(_json_contains_bucket(item, bucket) for item in value.values())
    if isinstance(value, list):
        return any(_json_contains_bucket(item, bucket) for item in value)
    return value == bucket


def _is_generation_success(row: sqlite3.Row) -> bool:
    status = str(_row_value(row, "status") or "").lower()
    if status in _SUCCESS_STATUSES:
        return True
    return not status and not _row_value(row, "error_type", "provider_error_type")


def _is_policy_failure(row: sqlite3.Row) -> bool:
    error_type = str(_row_value(row, "error_type", "provider_error_type") or "").lower()
    error_message = str(_row_value(row, "error_message", "provider_error_message") or "").lower()
    haystack = f"{error_type} {error_message}"
    return any(marker in haystack for marker in _POLICY_ERROR_MARKERS)


def _delivery_status(row: sqlite3.Row) -> str:
    return str(_row_value(row, "delivery_status", "status") or "").lower()


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _row_value(row: sqlite3.Row, *columns: str) -> Any:
    row_columns = set(row.keys())
    for column in columns:
        if column in row_columns:
            return row[column]
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _first_column(columns: set[str], *candidates: str) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None
