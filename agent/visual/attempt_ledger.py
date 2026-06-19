"""SQLite-backed ledger for visual generation requests and artifacts."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from agent.visual.ids import (
    new_artifact_id,
    new_attempt_id,
    new_delivery_id,
    new_feedback_id,
    new_judgment_id,
    new_ranking_id,
    new_request_id,
    utc_now_iso,
)

SCHEMA_VERSION = 1

_JSON_COLUMNS = {
    "normalized_intent_json": "normalized_intent",
    "policy_context_json": "policy_context",
    "parameters_requested_json": "parameters_requested",
    "parameters_effective_json": "parameters_effective",
    "input_artifacts_json": "input_artifacts",
    "score_json": "score",
    "raw_output_json": "raw_output",
    "rationale_json": "rationale",
    "parsed_json": "parsed",
}

_BOOL_COLUMNS = {"is_stable"}


class VisualAttemptLedger:
    """Small SQLite wrapper for visual generation evidence records."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS visual_schema_meta (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS visual_requests (
                  request_id TEXT PRIMARY KEY,
                  conversation_id TEXT,
                  user_id TEXT,
                  platform TEXT,
                  channel_id TEXT,
                  thread_id TEXT,
                  user_prompt TEXT NOT NULL,
                  normalized_intent_json TEXT NOT NULL,
                  modality TEXT NOT NULL,
                  operation TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  policy_context_json TEXT,
                  status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS visual_attempts (
                  attempt_id TEXT PRIMARY KEY,
                  request_id TEXT NOT NULL,
                  candidate_index INTEGER NOT NULL,
                  provider TEXT NOT NULL,
                  model TEXT NOT NULL,
                  strategy_id TEXT,
                  strategy_version TEXT,
                  prompt_original TEXT NOT NULL,
                  prompt_mediated TEXT NOT NULL,
                  prompt_negative TEXT,
                  parameters_requested_json TEXT,
                  parameters_effective_json TEXT,
                  input_artifacts_json TEXT,
                  provider_request_id TEXT,
                  provider_latency_ms INTEGER,
                  provider_cost_estimate REAL,
                  provider_error_type TEXT,
                  provider_error_message TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(request_id) REFERENCES visual_requests(request_id)
                );

                CREATE TABLE IF NOT EXISTS visual_artifacts (
                  artifact_id TEXT PRIMARY KEY,
                  attempt_id TEXT NOT NULL,
                  request_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  local_path TEXT,
                  source_url TEXT,
                  content_hash TEXT,
                  perceptual_hash TEXT,
                  mime_type TEXT,
                  bytes INTEGER,
                  width INTEGER,
                  height INTEGER,
                  duration_ms INTEGER,
                  frame_count INTEGER,
                  created_at TEXT NOT NULL,
                  expires_at TEXT,
                  is_stable INTEGER NOT NULL,
                  freshness_status TEXT NOT NULL,
                  FOREIGN KEY(attempt_id) REFERENCES visual_attempts(attempt_id),
                  FOREIGN KEY(request_id) REFERENCES visual_requests(request_id)
                );

                CREATE TABLE IF NOT EXISTS visual_judgments (
                  judgment_id TEXT PRIMARY KEY,
                  artifact_id TEXT NOT NULL,
                  attempt_id TEXT NOT NULL,
                  judge_name TEXT NOT NULL,
                  judge_version TEXT NOT NULL,
                  score_json TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  raw_output_json TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(artifact_id) REFERENCES visual_artifacts(artifact_id),
                  FOREIGN KEY(attempt_id) REFERENCES visual_attempts(attempt_id)
                );

                CREATE TABLE IF NOT EXISTS visual_rankings (
                  ranking_id TEXT PRIMARY KEY,
                  request_id TEXT NOT NULL,
                  ranker_version TEXT NOT NULL,
                  selected_attempt_id TEXT,
                  selected_artifact_id TEXT,
                  score_json TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  decision TEXT NOT NULL,
                  rationale_json TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(request_id) REFERENCES visual_requests(request_id)
                );

                CREATE TABLE IF NOT EXISTS visual_deliveries (
                  delivery_id TEXT PRIMARY KEY,
                  request_id TEXT NOT NULL,
                  attempt_id TEXT NOT NULL,
                  artifact_id TEXT NOT NULL,
                  platform TEXT NOT NULL,
                  destination_id TEXT NOT NULL,
                  thread_id TEXT,
                  message_id TEXT,
                  delivery_status TEXT NOT NULL,
                  error_type TEXT,
                  error_message TEXT,
                  delivered_at TEXT
                );

                CREATE TABLE IF NOT EXISTS visual_feedback (
                  feedback_id TEXT PRIMARY KEY,
                  request_id TEXT NOT NULL,
                  artifact_id TEXT,
                  attempt_id TEXT,
                  platform TEXT,
                  feedback_type TEXT NOT NULL,
                  polarity REAL,
                  strength REAL,
                  raw_text TEXT,
                  parsed_json TEXT,
                  created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO visual_schema_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    def table_names(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        return {str(row["name"]) for row in rows}

    def record_request(
        self,
        *,
        user_prompt: str,
        normalized_intent: Dict[str, Any],
        modality: str,
        operation: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        platform: Optional[str] = None,
        channel_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        policy_context: Optional[Dict[str, Any]] = None,
        status: str = "pending",
        request_id: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> str:
        rid = request_id or new_request_id()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO visual_requests (
                  request_id, conversation_id, user_id, platform, channel_id,
                  thread_id, user_prompt, normalized_intent_json, modality,
                  operation, created_at, policy_context_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rid,
                    conversation_id,
                    user_id,
                    platform,
                    channel_id,
                    thread_id,
                    user_prompt,
                    _to_json(normalized_intent),
                    modality,
                    operation,
                    created_at or utc_now_iso(),
                    _to_json_or_none(policy_context),
                    status,
                ),
            )
        return rid

    def record_attempt(
        self,
        *,
        request_id: str,
        candidate_index: int,
        provider: str,
        model: str,
        prompt_original: str,
        prompt_mediated: str,
        strategy_id: Optional[str] = None,
        strategy_version: Optional[str] = None,
        prompt_negative: Optional[str] = None,
        parameters_requested: Optional[Dict[str, Any]] = None,
        parameters_effective: Optional[Dict[str, Any]] = None,
        input_artifacts: Optional[Dict[str, Any]] = None,
        provider_request_id: Optional[str] = None,
        provider_latency_ms: Optional[int] = None,
        provider_cost_estimate: Optional[float] = None,
        provider_error_type: Optional[str] = None,
        provider_error_message: Optional[str] = None,
        attempt_id: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> str:
        aid = attempt_id or new_attempt_id()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO visual_attempts (
                  attempt_id, request_id, candidate_index, provider, model,
                  strategy_id, strategy_version, prompt_original,
                  prompt_mediated, prompt_negative, parameters_requested_json,
                  parameters_effective_json, input_artifacts_json,
                  provider_request_id, provider_latency_ms,
                  provider_cost_estimate, provider_error_type,
                  provider_error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    aid,
                    request_id,
                    int(candidate_index),
                    provider,
                    model,
                    strategy_id,
                    strategy_version,
                    prompt_original,
                    prompt_mediated,
                    prompt_negative,
                    _to_json_or_none(parameters_requested),
                    _to_json_or_none(parameters_effective),
                    _to_json_or_none(input_artifacts),
                    provider_request_id,
                    provider_latency_ms,
                    provider_cost_estimate,
                    provider_error_type,
                    provider_error_message,
                    created_at or utc_now_iso(),
                ),
            )
        return aid

    def record_artifact(
        self,
        *,
        request_id: str,
        attempt_id: str,
        kind: str,
        local_path: Optional[str] = None,
        source_url: Optional[str] = None,
        content_hash: Optional[str] = None,
        perceptual_hash: Optional[str] = None,
        mime_type: Optional[str] = None,
        bytes: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        duration_ms: Optional[int] = None,
        frame_count: Optional[int] = None,
        expires_at: Optional[str] = None,
        is_stable: bool = False,
        freshness_status: str = "unknown",
        artifact_id: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> str:
        arid = artifact_id or new_artifact_id()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO visual_artifacts (
                  artifact_id, attempt_id, request_id, kind, local_path,
                  source_url, content_hash, perceptual_hash, mime_type, bytes,
                  width, height, duration_ms, frame_count, created_at,
                  expires_at, is_stable, freshness_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    arid,
                    attempt_id,
                    request_id,
                    kind,
                    local_path,
                    source_url,
                    content_hash,
                    perceptual_hash,
                    mime_type,
                    bytes,
                    width,
                    height,
                    duration_ms,
                    frame_count,
                    created_at or utc_now_iso(),
                    expires_at,
                    1 if is_stable else 0,
                    freshness_status,
                ),
            )
        return arid

    def record_judgment(
        self,
        *,
        artifact_id: str,
        attempt_id: str,
        judge_name: str,
        judge_version: str,
        score: Dict[str, Any],
        confidence: float,
        raw_output: Optional[Dict[str, Any]] = None,
        judgment_id: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> str:
        jid = judgment_id or new_judgment_id()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO visual_judgments (
                  judgment_id, artifact_id, attempt_id, judge_name,
                  judge_version, score_json, confidence, raw_output_json,
                  created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    jid,
                    artifact_id,
                    attempt_id,
                    judge_name,
                    judge_version,
                    _to_json(score),
                    confidence,
                    _to_json_or_none(raw_output),
                    created_at or utc_now_iso(),
                ),
            )
        return jid

    def record_ranking(
        self,
        *,
        request_id: str,
        ranker_version: str,
        score: Dict[str, Any],
        confidence: float,
        decision: str,
        selected_attempt_id: Optional[str] = None,
        selected_artifact_id: Optional[str] = None,
        rationale: Optional[Dict[str, Any]] = None,
        ranking_id: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> str:
        rid = ranking_id or new_ranking_id()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO visual_rankings (
                  ranking_id, request_id, ranker_version, selected_attempt_id,
                  selected_artifact_id, score_json, confidence, decision,
                  rationale_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rid,
                    request_id,
                    ranker_version,
                    selected_attempt_id,
                    selected_artifact_id,
                    _to_json(score),
                    confidence,
                    decision,
                    _to_json_or_none(rationale),
                    created_at or utc_now_iso(),
                ),
            )
        return rid

    def record_delivery(
        self,
        *,
        request_id: str,
        attempt_id: str,
        artifact_id: str,
        platform: str,
        destination_id: str,
        thread_id: Optional[str] = None,
        message_id: Optional[str] = None,
        delivery_status: str,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        delivery_id: Optional[str] = None,
        delivered_at: Optional[str] = None,
    ) -> str:
        did = delivery_id or new_delivery_id()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO visual_deliveries (
                  delivery_id, request_id, attempt_id, artifact_id, platform,
                  destination_id, thread_id, message_id, delivery_status,
                  error_type, error_message, delivered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    did,
                    request_id,
                    attempt_id,
                    artifact_id,
                    platform,
                    destination_id,
                    thread_id,
                    message_id,
                    delivery_status,
                    error_type,
                    error_message,
                    delivered_at or utc_now_iso(),
                ),
            )
        return did

    def record_feedback(
        self,
        *,
        request_id: str,
        feedback_type: str,
        artifact_id: Optional[str] = None,
        attempt_id: Optional[str] = None,
        platform: Optional[str] = None,
        polarity: Optional[float] = None,
        strength: Optional[float] = None,
        raw_text: Optional[str] = None,
        parsed: Optional[Dict[str, Any]] = None,
        feedback_id: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> str:
        fid = feedback_id or new_feedback_id()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO visual_feedback (
                  feedback_id, request_id, artifact_id, attempt_id, platform,
                  feedback_type, polarity, strength, raw_text, parsed_json,
                  created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fid,
                    request_id,
                    artifact_id,
                    attempt_id,
                    platform,
                    feedback_type,
                    polarity,
                    strength,
                    raw_text,
                    _to_json_or_none(parsed),
                    created_at or utc_now_iso(),
                ),
            )
        return fid

    def get_request(self, request_id: str) -> Dict[str, Any]:
        return self._get_by_id("visual_requests", "request_id", request_id)

    def get_attempt(self, attempt_id: str) -> Dict[str, Any]:
        return self._get_by_id("visual_attempts", "attempt_id", attempt_id)

    def get_artifact(self, artifact_id: str) -> Dict[str, Any]:
        return self._get_by_id("visual_artifacts", "artifact_id", artifact_id)

    def get_delivery(self, delivery_id: str) -> Dict[str, Any]:
        return self._get_by_id("visual_deliveries", "delivery_id", delivery_id)

    def _get_by_id(self, table: str, key: str, value: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE {key} = ?",
                (value,),
            ).fetchone()
        if row is None:
            raise KeyError(value)
        return _decode_row(row)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _to_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _to_json_or_none(value: Optional[Dict[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    return _to_json(value)


def _decode_row(row: sqlite3.Row) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        out_key = _JSON_COLUMNS.get(key, key)
        if key in _JSON_COLUMNS:
            result[out_key] = json.loads(value) if value else None
        elif key in _BOOL_COLUMNS:
            result[out_key] = bool(value)
        else:
            result[out_key] = value
    return result
