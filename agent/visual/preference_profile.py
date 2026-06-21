from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger


EXPLICIT_FEEDBACK_WEIGHT = 1.0
WEAK_LABEL_WEIGHT = 0.25
MINIMUM_CONFIDENCE_SAMPLE_COUNT = 5
EWMA_ALPHA = 0.35


@dataclass(frozen=True)
class PreferenceProfile:
    bucket: str | None
    sample_count: int
    confidence: float
    signals: dict[str, dict[str, Any]]
    issues: dict[str, dict[str, Any]]

    def to_record(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "sample_count": self.sample_count,
            "confidence": self.confidence,
            "minimum_confidence_sample_count": MINIMUM_CONFIDENCE_SAMPLE_COUNT,
            "signals": self.signals,
            "issues": self.issues,
            "production_mutation_allowed": False,
        }


def build_preference_profile(
    ledger: VisualAttemptLedger,
    *,
    bucket: str | None = None,
) -> dict[str, Any]:
    with sqlite3.connect(ledger.db_path) as conn:
        conn.row_factory = sqlite3.Row
        request_ids = _matching_request_ids(conn, bucket=bucket)
        feedback_rows = _feedback_rows(conn, request_ids=request_ids)

    signal_stats: dict[str, _RunningPreference] = {}
    issue_stats: dict[str, _RunningPreference] = {}
    for row in feedback_rows:
        parsed = _parsed_feedback(row)
        polarity = _coerce_float(_row_value(row, "polarity"))
        feedback_weight = _feedback_weight(row, parsed)
        for signal in _string_list(parsed.get("signals")):
            value = max(0.1, polarity)
            _update(signal_stats, signal, value=value, weight=feedback_weight)
        for issue in _string_list(parsed.get("issues")):
            value = max(0.1, -polarity if polarity < 0 else 1.0 - max(0.0, polarity))
            _update(issue_stats, issue, value=value, weight=feedback_weight)

    sample_count = len(feedback_rows)
    profile = PreferenceProfile(
        bucket=bucket,
        sample_count=sample_count,
        confidence=round(min(1.0, sample_count / MINIMUM_CONFIDENCE_SAMPLE_COUNT), 4),
        signals={
            key: value.to_record("weight")
            for key, value in sorted(signal_stats.items())
        },
        issues={
            key: value.to_record("penalty")
            for key, value in sorted(issue_stats.items())
        },
    )
    return profile.to_record()


@dataclass
class _RunningPreference:
    value: float
    sample_count: int
    effective_weight: float

    def to_record(self, value_key: str) -> dict[str, Any]:
        return {
            value_key: round(self.value, 4),
            "sample_count": self.sample_count,
            "effective_weight": round(self.effective_weight, 4),
        }


def _update(
    stats: dict[str, _RunningPreference],
    tag: str,
    *,
    value: float,
    weight: float,
) -> None:
    value = _clamp(value)
    if tag not in stats:
        stats[tag] = _RunningPreference(
            value=value,
            sample_count=1,
            effective_weight=weight,
        )
        return
    current = stats[tag]
    alpha = min(1.0, EWMA_ALPHA * weight)
    current.value = current.value * (1.0 - alpha) + value * alpha
    current.sample_count += 1
    current.effective_weight += weight


def _matching_request_ids(conn: sqlite3.Connection, *, bucket: str | None) -> set[str] | None:
    if bucket is None:
        return None
    columns = _column_names(conn, "visual_requests")
    id_column = _first_column(columns, "id", "request_id")
    if id_column is None:
        return set()
    metadata_columns = [
        column
        for column in ("metadata", "policy_context_json", "normalized_intent_json", "normalized_intent")
        if column in columns
    ]
    if not metadata_columns:
        return set()

    rows = conn.execute(
        f"SELECT {id_column}, {', '.join(metadata_columns)} FROM visual_requests"
    ).fetchall()
    matched: set[str] = set()
    for row in rows:
        for column in metadata_columns:
            if _json_contains_bucket(row[column], bucket):
                matched.add(str(row[id_column]))
                break
    return matched


def _feedback_rows(
    conn: sqlite3.Connection,
    *,
    request_ids: set[str] | None,
) -> list[sqlite3.Row]:
    if not _table_exists(conn, "visual_feedback"):
        return []
    if request_ids is not None and not request_ids:
        return []
    sql = "SELECT * FROM visual_feedback"
    params: tuple[str, ...] = ()
    if request_ids is not None:
        placeholders = ", ".join("?" for _ in request_ids)
        sql += f" WHERE request_id IN ({placeholders})"
        params = tuple(sorted(request_ids))
    sql += " ORDER BY created_at, rowid"
    return conn.execute(sql, params).fetchall()


def _parsed_feedback(row: sqlite3.Row) -> dict[str, Any]:
    parsed = _row_value(row, "parsed", "parsed_json")
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _feedback_weight(row: sqlite3.Row, parsed: dict[str, Any]) -> float:
    metadata = _row_value(row, "metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    source = parsed.get("source")
    if isinstance(metadata, dict):
        source = metadata.get("source", source)
    return WEAK_LABEL_WEIGHT if source == "weak_label" else EXPLICIT_FEEDBACK_WEIGHT


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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _row_value(row: sqlite3.Row, *columns: str) -> Any:
    row_columns = set(row.keys())
    for column in columns:
        if column in row_columns:
            return row[column]
    return None


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


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
