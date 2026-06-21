from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agent.visual.ids import (
    new_artifact_id,
    new_attempt_id,
    new_delivery_id,
    new_feedback_id,
    new_judgment_id,
    new_ranking_id,
    new_request_id,
)


_JSON_COLUMNS = {
    "normalized_intent",
    "parameters_requested",
    "parameters_effective",
    "metadata",
    "details",
    "scores",
    "parsed",
}

_BOOL_COLUMNS = {"is_stable"}


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _encode(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


def _decode(column: str, value: Any) -> Any:
    if column in _JSON_COLUMNS and isinstance(value, str):
        return json.loads(value)
    if column in _BOOL_COLUMNS and value is not None:
        return bool(value)
    return value


def _encode_column(column: str, value: Any) -> Any:
    if column in _BOOL_COLUMNS and value is not None:
        return int(value)
    if column in _JSON_COLUMNS:
        return _encode(value)
    return value


class VisualAttemptLedger:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS visual_requests (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    user_prompt TEXT,
                    normalized_intent TEXT,
                    modality TEXT,
                    operation TEXT,
                    platform TEXT,
                    channel_id TEXT,
                    thread_id TEXT,
                    user_id TEXT,
                    message_id TEXT,
                    conversation_id TEXT,
                    status TEXT,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS visual_attempts (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    candidate_index INTEGER,
                    provider TEXT,
                    model TEXT,
                    prompt_original TEXT,
                    prompt_mediated TEXT,
                    parameters_requested TEXT,
                    parameters_effective TEXT,
                    status TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    metadata TEXT,
                    FOREIGN KEY(request_id) REFERENCES visual_requests(id)
                );

                CREATE TABLE IF NOT EXISTS visual_artifacts (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    attempt_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    kind TEXT,
                    local_path TEXT,
                    uri TEXT,
                    content_hash TEXT,
                    mime_type TEXT,
                    bytes INTEGER,
                    width INTEGER,
                    height INTEGER,
                    duration_seconds REAL,
                    is_stable INTEGER,
                    freshness_status TEXT,
                    metadata TEXT,
                    FOREIGN KEY(request_id) REFERENCES visual_requests(id),
                    FOREIGN KEY(attempt_id) REFERENCES visual_attempts(id)
                );

                CREATE TABLE IF NOT EXISTS visual_judgments (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    attempt_id TEXT,
                    artifact_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    judge_name TEXT,
                    score REAL,
                    verdict TEXT,
                    details TEXT,
                    metadata TEXT,
                    FOREIGN KEY(request_id) REFERENCES visual_requests(id),
                    FOREIGN KEY(attempt_id) REFERENCES visual_attempts(id),
                    FOREIGN KEY(artifact_id) REFERENCES visual_artifacts(id)
                );

                CREATE TABLE IF NOT EXISTS visual_rankings (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    selected_artifact_id TEXT,
                    decision TEXT,
                    scores TEXT,
                    metadata TEXT,
                    FOREIGN KEY(request_id) REFERENCES visual_requests(id),
                    FOREIGN KEY(selected_artifact_id) REFERENCES visual_artifacts(id)
                );

                CREATE TABLE IF NOT EXISTS visual_deliveries (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    attempt_id TEXT,
                    artifact_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    platform TEXT,
                    destination_id TEXT,
                    thread_id TEXT,
                    message_id TEXT,
                    delivery_status TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    metadata TEXT,
                    FOREIGN KEY(request_id) REFERENCES visual_requests(id),
                    FOREIGN KEY(attempt_id) REFERENCES visual_attempts(id),
                    FOREIGN KEY(artifact_id) REFERENCES visual_artifacts(id)
                );

                CREATE TABLE IF NOT EXISTS visual_feedback (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    artifact_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    feedback_text TEXT,
                    polarity REAL,
                    parsed TEXT,
                    metadata TEXT,
                    FOREIGN KEY(request_id) REFERENCES visual_requests(id),
                    FOREIGN KEY(artifact_id) REFERENCES visual_artifacts(id)
                );
                """
            )

    def record_request(self, **kwargs: Any) -> str:
        return self._insert("visual_requests", "id", kwargs, new_request_id)

    def record_attempt(self, **kwargs: Any) -> str:
        return self._insert("visual_attempts", "id", kwargs, new_attempt_id)

    def record_artifact(self, **kwargs: Any) -> str:
        return self._insert("visual_artifacts", "id", kwargs, new_artifact_id)

    def record_judgment(self, **kwargs: Any) -> str:
        return self._insert("visual_judgments", "id", kwargs, new_judgment_id)

    def record_ranking(self, **kwargs: Any) -> str:
        return self._insert("visual_rankings", "id", kwargs, new_ranking_id)

    def record_delivery(self, **kwargs: Any) -> str:
        return self._insert("visual_deliveries", "id", kwargs, new_delivery_id)

    def record_feedback(self, **kwargs: Any) -> str:
        return self._insert("visual_feedback", "id", kwargs, new_feedback_id)

    def get_request(self, record_id: str) -> dict[str, Any]:
        return self._get("visual_requests", record_id)

    def get_attempt(self, record_id: str) -> dict[str, Any]:
        return self._get("visual_attempts", record_id)

    def get_artifact(self, record_id: str) -> dict[str, Any]:
        return self._get("visual_artifacts", record_id)

    def get_delivery(self, record_id: str) -> dict[str, Any]:
        return self._get("visual_deliveries", record_id)

    def get_judgment(self, record_id: str) -> dict[str, Any]:
        return self._get("visual_judgments", record_id)

    def get_ranking(self, record_id: str) -> dict[str, Any]:
        return self._get("visual_rankings", record_id)

    def get_feedback(self, record_id: str) -> dict[str, Any]:
        return self._get("visual_feedback", record_id)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _insert(
        self,
        table: str,
        id_column: str,
        values: dict[str, Any],
        id_factory,
    ) -> str:
        record_id = str(values.pop(id_column, "") or id_factory())
        row = {id_column: record_id, **values}
        encoded = {key: _encode_column(key, value) for key, value in row.items()}
        columns = list(encoded)
        placeholders = ", ".join("?" for _ in columns)
        quoted_columns = ", ".join(columns)
        sql = f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders})"
        with self._connect() as conn:
            conn.execute(sql, [encoded[column] for column in columns])
        return record_id

    def _get(self, table: str, record_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return {key: _decode(key, row[key]) for key in row.keys()}
