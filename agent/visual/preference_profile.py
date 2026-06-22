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
QUALITY_JUDGE_NAME = "visual_quality_judge"
PREFERENCE_DIMENSION_LOW_THRESHOLD = 0.5

_PREFERENCE_DIMENSION_ISSUES = {
    "subject_beauty": "subject_not_attractive",
    "face_naturalness": "face_unnatural",
    "glamour_impact": "not_glamorous",
    "fashion_material_quality": "stockings_bad",
    "pose_composition": "composition_bad",
    "motion_quality": "motion_bad",
}


@dataclass(frozen=True)
class PreferenceProfile:
    bucket: str | None
    sample_count: int
    explicit_feedback_sample_count: int
    self_supervised_sample_count: int
    effective_sample_count: float
    confidence: float
    signals: dict[str, dict[str, Any]]
    issues: dict[str, dict[str, Any]]

    def to_record(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "sample_count": self.sample_count,
            "explicit_feedback_sample_count": self.explicit_feedback_sample_count,
            "self_supervised_sample_count": self.self_supervised_sample_count,
            "effective_sample_count": round(self.effective_sample_count, 4),
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
        judgment_rows = _quality_judgment_rows(conn, request_ids=request_ids)

    signal_stats: dict[str, _RunningPreference] = {}
    issue_stats: dict[str, _RunningPreference] = {}
    explicit_feedback_sample_count = 0
    effective_sample_count = 0.0
    for row in feedback_rows:
        parsed = _parsed_feedback(row)
        polarity = _coerce_float(_row_value(row, "polarity"))
        feedback_weight = _feedback_weight(row, parsed)
        if feedback_weight >= EXPLICIT_FEEDBACK_WEIGHT:
            explicit_feedback_sample_count += 1
        effective_sample_count += feedback_weight
        for signal in _string_list(parsed.get("signals")):
            value = max(0.1, polarity)
            _update(signal_stats, signal, value=value, weight=feedback_weight)
        for issue in _string_list(parsed.get("issues")):
            value = max(0.1, -polarity if polarity < 0 else 1.0 - max(0.0, polarity))
            _update(issue_stats, issue, value=value, weight=feedback_weight)

    self_supervised_sample_count = 0
    for row in judgment_rows:
        updates = _quality_judgment_issue_updates(row)
        if not updates:
            continue
        self_supervised_sample_count += 1
        effective_sample_count += WEAK_LABEL_WEIGHT
        for issue, value in sorted(updates.items()):
            _update(issue_stats, issue, value=value, weight=WEAK_LABEL_WEIGHT)

    sample_count = len(feedback_rows) + self_supervised_sample_count
    profile = PreferenceProfile(
        bucket=bucket,
        sample_count=sample_count,
        explicit_feedback_sample_count=explicit_feedback_sample_count,
        self_supervised_sample_count=self_supervised_sample_count,
        effective_sample_count=effective_sample_count,
        confidence=round(min(1.0, effective_sample_count / MINIMUM_CONFIDENCE_SAMPLE_COUNT), 4),
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


def _quality_judgment_rows(
    conn: sqlite3.Connection,
    *,
    request_ids: set[str] | None,
) -> list[sqlite3.Row]:
    if not _table_exists(conn, "visual_judgments"):
        return []
    if request_ids is not None and not request_ids:
        return []
    columns = _column_names(conn, "visual_judgments")
    sql = "SELECT * FROM visual_judgments WHERE judge_name = ?"
    params: tuple[str, ...] = (QUALITY_JUDGE_NAME,)
    if request_ids is not None:
        request_filter, request_params = _quality_judgment_request_filter(
            conn,
            columns=columns,
            request_ids=request_ids,
        )
        if request_filter is None:
            return []
        sql += f" AND ({request_filter})"
        params = (QUALITY_JUDGE_NAME, *request_params)
    order_column = "created_at" if "created_at" in columns else "rowid"
    sql += f" ORDER BY {order_column}, rowid"
    return conn.execute(sql, params).fetchall()


def _quality_judgment_request_filter(
    conn: sqlite3.Connection,
    *,
    columns: set[str],
    request_ids: set[str],
) -> tuple[str | None, tuple[str, ...]]:
    filters: list[str] = []
    params: list[str] = []
    request_id_params = tuple(sorted(request_ids))
    placeholders = ", ".join("?" for _ in request_id_params)
    if "request_id" in columns:
        filters.append(f"request_id IN ({placeholders})")
        params.extend(request_id_params)
    artifact_filter = _foreign_request_filter(
        conn,
        source_column="artifact_id",
        source_columns=columns,
        foreign_table="visual_artifacts",
        foreign_id_candidates=("artifact_id", "id"),
        request_ids=request_id_params,
    )
    if artifact_filter is not None:
        filters.append(artifact_filter)
        params.extend(request_id_params)
    attempt_filter = _foreign_request_filter(
        conn,
        source_column="attempt_id",
        source_columns=columns,
        foreign_table="visual_attempts",
        foreign_id_candidates=("attempt_id", "id"),
        request_ids=request_id_params,
    )
    if attempt_filter is not None:
        filters.append(attempt_filter)
        params.extend(request_id_params)
    if not filters:
        return None, ()
    return " OR ".join(filters), tuple(params)


def _foreign_request_filter(
    conn: sqlite3.Connection,
    *,
    source_column: str,
    source_columns: set[str],
    foreign_table: str,
    foreign_id_candidates: tuple[str, ...],
    request_ids: tuple[str, ...],
) -> str | None:
    if source_column not in source_columns:
        return None
    if not request_ids or not _table_exists(conn, foreign_table):
        return None
    foreign_columns = _column_names(conn, foreign_table)
    foreign_id_column = _first_column(foreign_columns, *foreign_id_candidates)
    request_column = _first_column(foreign_columns, "request_id")
    if foreign_id_column is None or request_column is None:
        return None
    placeholders = ", ".join("?" for _ in request_ids)
    return (
        f"{source_column} IN ("
        f"SELECT {foreign_id_column} FROM {foreign_table} "
        f"WHERE {request_column} IN ({placeholders})"
        ")"
    )


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


def _quality_judgment_issue_updates(row: sqlite3.Row) -> dict[str, float]:
    payload = _parsed_judgment(row)
    if not payload:
        return {}
    row_score = _coerce_float_or_none(_row_value(row, "score", "confidence"))
    base_penalty = 1.0 - row_score if row_score is not None else 0.5
    updates: dict[str, float] = {}
    for issue in _string_list(payload.get("quality_issues")):
        updates[issue] = max(updates.get(issue, 0.0), _clamp(max(0.35, base_penalty)))

    dimensions = payload.get("preference_dimensions")
    if isinstance(dimensions, dict):
        for dimension, raw_score in dimensions.items():
            issue = _PREFERENCE_DIMENSION_ISSUES.get(str(dimension or ""))
            score = _coerce_float_or_none(raw_score)
            if issue is None or score is None or score >= PREFERENCE_DIMENSION_LOW_THRESHOLD:
                continue
            updates[issue] = max(updates.get(issue, 0.0), _clamp(1.0 - score))
    return updates


def _parsed_judgment(row: sqlite3.Row) -> dict[str, Any]:
    parsed = _row_value(row, "details", "score_json")
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            parsed = {}
    return parsed if isinstance(parsed, dict) else {}


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


def _coerce_float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
