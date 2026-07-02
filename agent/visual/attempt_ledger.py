from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from datetime import timezone
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
    new_shadow_update_id,
    new_strategy_activation_id,
)


_JSON_COLUMNS = {
    "normalized_intent",
    "normalized_intent_json",
    "policy_context_json",
    "parameters_requested",
    "parameters_requested_json",
    "parameters_effective",
    "parameters_effective_json",
    "input_artifacts_json",
    "metadata",
    "details",
    "scores",
    "score_json",
    "raw_output_json",
    "rationale_json",
    "parsed",
    "parsed_json",
    "proposed_change",
    "proposed_change_json",
    "promotion_decision",
    "promotion_decision_json",
    "evidence",
    "evidence_json",
}

_BOOL_COLUMNS = {"is_stable"}

_ID_COLUMN_CANDIDATES = {
    "visual_requests": ("id", "request_id"),
    "visual_attempts": ("id", "attempt_id"),
    "visual_artifacts": ("id", "artifact_id"),
    "visual_judgments": ("id", "judgment_id"),
    "visual_rankings": ("id", "ranking_id"),
    "visual_deliveries": ("id", "delivery_id"),
    "visual_feedback": ("id", "feedback_id"),
    "visual_shadow_updates": ("id", "shadow_update_id"),
    "visual_strategy_activations": ("id", "strategy_activation_id"),
}

_COLUMN_ALIASES = {
    "visual_requests": {
        "id": "request_id",
        "normalized_intent": "normalized_intent_json",
        "metadata": "policy_context_json",
    },
    "visual_attempts": {
        "id": "attempt_id",
        "parameters_requested": "parameters_requested_json",
        "parameters_effective": "parameters_effective_json",
        "input_artifacts": "input_artifacts_json",
        "error_type": "provider_error_type",
        "error_message": "provider_error_message",
    },
    "visual_artifacts": {
        "id": "artifact_id",
        "uri": "source_url",
        "duration_seconds": "duration_ms",
    },
    "visual_judgments": {
        "id": "judgment_id",
        "score": "confidence",
        "details": "score_json",
    },
    "visual_rankings": {
        "id": "ranking_id",
        "scores": "score_json",
        "metadata": "rationale_json",
    },
    "visual_deliveries": {
        "id": "delivery_id",
    },
    "visual_feedback": {
        "id": "feedback_id",
        "feedback_text": "raw_text",
        "parsed": "parsed_json",
        "metadata": "parsed_json",
    },
    "visual_shadow_updates": {
        "id": "shadow_update_id",
        "proposed_change": "proposed_change_json",
        "evidence": "evidence_json",
    },
    "visual_strategy_activations": {
        "id": "strategy_activation_id",
        "promotion_decision": "promotion_decision_json",
        "metadata": "metadata_json",
    },
}


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


def _decode_row(table: str, row: sqlite3.Row) -> dict[str, Any]:
    decoded = {key: _decode(key, row[key]) for key in row.keys()}
    if (
        table == "visual_artifacts"
        and "duration_seconds" not in decoded
        and decoded.get("duration_ms") is not None
    ):
        decoded["duration_seconds"] = float(decoded["duration_ms"]) / 1000.0
    return decoded


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
                    destination TEXT,
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

                CREATE TABLE IF NOT EXISTS visual_shadow_updates (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    intent_signature TEXT,
                    strategy_signature TEXT,
                    proposed_change TEXT,
                    evidence TEXT,
                    confidence REAL,
                    activation_status TEXT,
                    FOREIGN KEY(request_id) REFERENCES visual_requests(id)
                );

                CREATE TABLE IF NOT EXISTS visual_strategy_activations (
                    id TEXT PRIMARY KEY,
                    shadow_update_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    intent_signature TEXT NOT NULL,
                    strategy_signature TEXT NOT NULL,
                    activation_status TEXT NOT NULL,
                    promotion_decision TEXT,
                    rollback_of TEXT,
                    metadata TEXT,
                    FOREIGN KEY(shadow_update_id) REFERENCES visual_shadow_updates(id),
                    FOREIGN KEY(rollback_of) REFERENCES visual_strategy_activations(id)
                );
                """
            )
            self._ensure_column(conn, "visual_deliveries", "destination", "TEXT")
            self._ensure_column(conn, "visual_attempts", "input_artifacts_json", "TEXT")
            self._ensure_created_at_columns(conn)

    def record_request(self, **kwargs: Any) -> str:
        return self._insert("visual_requests", "id", kwargs, new_request_id)

    def update_request_status(self, request_id: str, status: str) -> None:
        with self._connect() as conn:
            columns_available = self._table_columns(conn, "visual_requests")
            actual_id_column = self._actual_id_column(
                "visual_requests",
                columns_available,
                preferred="id",
            )
            if "status" not in columns_available:
                return
            cursor = conn.execute(
                f"UPDATE visual_requests SET status = ? WHERE {actual_id_column} = ?",
                (status, request_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(request_id)

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

    def record_shadow_update(self, **kwargs: Any) -> str:
        return self._insert("visual_shadow_updates", "id", kwargs, new_shadow_update_id)

    def record_strategy_activation(self, **kwargs: Any) -> str:
        return self._insert("visual_strategy_activations", "id", kwargs, new_strategy_activation_id)

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

    def get_shadow_update(self, record_id: str) -> dict[str, Any]:
        return self._get("visual_shadow_updates", record_id)

    def get_strategy_activation(self, record_id: str) -> dict[str, Any]:
        return self._get("visual_strategy_activations", record_id)

    def list_deliveries(self, *, request_id: str | None = None) -> list[dict[str, Any]]:
        if request_id is None:
            return self._list("visual_deliveries")
        return self._list("visual_deliveries", where="request_id = ?", params=(request_id,))

    def latest_delivered_prompt_context(
        self,
        *,
        platform: str | None = None,
        destination_id: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any] | None:
        where_parts = ["d.delivery_status = ?"]
        params: list[Any] = ["sent"]
        if platform:
            where_parts.append("d.platform = ?")
            params.append(str(platform))
        if destination_id:
            where_parts.append("d.destination_id = ?")
            params.append(str(destination_id))
        if thread_id:
            where_parts.append("d.thread_id = ?")
            params.append(str(thread_id))

        with self._connect() as conn:
            request_id_column = self._actual_id_column(
                "visual_requests",
                self._table_columns(conn, "visual_requests"),
                preferred="id",
            )
            attempt_id_column = self._actual_id_column(
                "visual_attempts",
                self._table_columns(conn, "visual_attempts"),
                preferred="id",
            )
            artifact_id_column = self._actual_id_column(
                "visual_artifacts",
                self._table_columns(conn, "visual_artifacts"),
                preferred="id",
            )
            delivery_id_column = self._actual_id_column(
                "visual_deliveries",
                self._table_columns(conn, "visual_deliveries"),
                preferred="id",
            )
            attempt_join = "COALESCE(NULLIF(d.attempt_id, ''), art.attempt_id)"
            where_sql = " AND ".join(where_parts)
            row = conn.execute(
                f"""
                SELECT
                    d.{delivery_id_column} AS delivery_id,
                    d.request_id AS request_id,
                    {attempt_join} AS attempt_id,
                    d.artifact_id AS artifact_id,
                    d.platform AS platform,
                    d.destination_id AS destination_id,
                    d.thread_id AS thread_id,
                    d.created_at AS created_at,
                    r.user_prompt AS user_prompt,
                    a.prompt_original AS prompt_original,
                    a.prompt_mediated AS prompt_mediated,
                    a.provider AS provider,
                    a.model AS model
                FROM visual_deliveries d
                JOIN visual_requests r ON d.request_id = r.{request_id_column}
                LEFT JOIN visual_artifacts art ON d.artifact_id = art.{artifact_id_column}
                LEFT JOIN visual_attempts a ON {attempt_join} = a.{attempt_id_column}
                WHERE {where_sql}
                ORDER BY d.created_at DESC, d.rowid DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    def list_strategy_activations(
        self,
        *,
        intent_signature: str | None = None,
        strategy_signature: str | None = None,
    ) -> list[dict[str, Any]]:
        where_parts: list[str] = []
        params: list[str] = []
        if intent_signature is not None:
            where_parts.append("intent_signature = ?")
            params.append(intent_signature)
        if strategy_signature is not None:
            where_parts.append("strategy_signature = ?")
            params.append(strategy_signature)
        return self._list(
            "visual_strategy_activations",
            where=" AND ".join(where_parts) if where_parts else None,
            params=tuple(params),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _ensure_created_at_columns(self, conn: sqlite3.Connection) -> None:
        tables = (
            "visual_requests",
            "visual_attempts",
            "visual_artifacts",
            "visual_judgments",
            "visual_rankings",
            "visual_deliveries",
            "visual_feedback",
            "visual_shadow_updates",
            "visual_strategy_activations",
        )
        for table in tables:
            self._ensure_column(conn, table, "created_at", "TEXT")
            conn.execute(
                f"""
                UPDATE {table}
                SET created_at = CURRENT_TIMESTAMP
                WHERE created_at IS NULL OR created_at = ''
                """
            )

    def _insert(
        self,
        table: str,
        id_column: str,
        values: dict[str, Any],
        id_factory,
    ) -> str:
        record_id = str(values.pop(id_column, "") or id_factory())
        with self._connect() as conn:
            columns_available = self._table_columns(conn, table)
        actual_id_column = self._actual_id_column(table, columns_available, preferred=id_column)
        row = self._prepare_row_for_table(
            table,
            columns_available,
            {actual_id_column: record_id, **values},
        )
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
            columns_available = self._table_columns(conn, table)
            actual_id_column = self._actual_id_column(table, columns_available, preferred="id")
            row = conn.execute(f"SELECT * FROM {table} WHERE {actual_id_column} = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return _decode_row(table, row)

    def _list(
        self,
        table: str,
        *,
        where: str | None = None,
        params: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        sql += " ORDER BY created_at, rowid"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_decode_row(table, row) for row in rows]

    def _actual_id_column(
        self,
        table: str,
        columns_available: set[str],
        *,
        preferred: str,
    ) -> str:
        if preferred in columns_available:
            return preferred
        for candidate in _ID_COLUMN_CANDIDATES.get(table, (preferred,)):
            if candidate in columns_available:
                return candidate
        raise sqlite3.OperationalError(f"{table} is missing an id column")

    def _prepare_row_for_table(
        self,
        table: str,
        columns_available: set[str],
        row: dict[str, Any],
    ) -> dict[str, Any]:
        aliases = _COLUMN_ALIASES.get(table, {})
        prepared: dict[str, Any] = {}
        for key, value in row.items():
            target = key if key in columns_available else aliases.get(key)
            if target not in columns_available:
                continue
            if target in prepared and key not in columns_available:
                continue
            if target == "duration_ms" and value is not None:
                value = int(float(value) * 1000)
            prepared[target] = value

        self._apply_legacy_defaults(table, columns_available, prepared)
        return prepared

    def _apply_legacy_defaults(
        self,
        table: str,
        columns_available: set[str],
        prepared: dict[str, Any],
    ) -> None:
        if "created_at" in columns_available and "created_at" not in prepared:
            prepared["created_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        legacy_schema = "id" not in columns_available
        if not legacy_schema:
            return
        if table == "visual_requests":
            prepared.setdefault("user_prompt", "")
            prepared.setdefault("normalized_intent_json", {})
            prepared.setdefault("modality", "")
            prepared.setdefault("operation", "")
            prepared.setdefault("status", "")
        elif table == "visual_attempts":
            prepared.setdefault("candidate_index", 0)
            prepared.setdefault("provider", "")
            prepared.setdefault("model", "")
            prepared.setdefault("prompt_original", "")
            prepared.setdefault("prompt_mediated", "")
        elif table == "visual_artifacts":
            prepared.setdefault("kind", "")
            prepared.setdefault("is_stable", False)
            prepared.setdefault("freshness_status", "unknown")
        elif table == "visual_judgments":
            prepared.setdefault("judge_name", "")
            prepared.setdefault("judge_version", "")
            prepared.setdefault("score_json", {})
            prepared.setdefault("confidence", 0.0)
        elif table == "visual_rankings":
            prepared.setdefault("ranker_version", "")
            prepared.setdefault("score_json", {})
            prepared.setdefault("confidence", 0.0)
            prepared.setdefault("decision", "")
        elif table == "visual_deliveries":
            for key in (
                "attempt_id",
                "artifact_id",
                "platform",
                "destination_id",
                "delivery_status",
            ):
                if prepared.get(key) is None:
                    prepared[key] = ""
                prepared.setdefault(key, "")
        elif table == "visual_feedback":
            prepared.setdefault("feedback_type", "comment")
        elif table == "visual_shadow_updates":
            prepared.setdefault("activation_status", "shadow")

        for key in list(prepared):
            if key not in columns_available:
                del prepared[key]

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
