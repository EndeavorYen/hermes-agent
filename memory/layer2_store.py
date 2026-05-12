"""SQLite-backed shared Layer-2 sidecar memory.

Minimal audit-first implementation:
- stores candidate facts separately from durable memory
- records every candidate event with provenance and recurrence-count flags
- parses fenced Layer-2 payloads from cron and chat producers
- optionally promotes approved facts into built-in MEMORY.md / USER.md
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hermes_constants import get_hermes_home
from hermes_time import now as _hermes_now
from tools.memory_tool import MemoryStore

logger = logging.getLogger(__name__)

_LAYER2_FENCE_RE = re.compile(
    r"```hermes-layer2\s*\n(?P<body>.*?)\n```",
    re.IGNORECASE | re.DOTALL,
)


def canonical_key_for_text(value: str | None) -> str:
    """Return a deterministic dedupe key for Layer-2 candidate text.

    This is intentionally conservative: it handles exact/case/whitespace and
    terminal-punctuation variants without fuzzy or semantic merging. The human
    display text remains ``canonical_text``; this key is only for ledger identity.
    """
    text = (value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" \t\r\n.,;:!?。！？；：、，")
    text = re.sub(r"\s+", " ", text)
    return text


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_destination(raw: str | None) -> str | None:
    value = _clean_optional_text(raw)
    if value == "memory":
        return "prior"
    return value


def durable_store_target(destination: str | None) -> str | None:
    value = _clean_optional_text(destination)
    if value == "prior":
        return "memory"
    return value


def _default_layer2_db_path() -> Path:
    return get_hermes_home() / "memory" / "layer2.sqlite3"


def _legacy_layer2_db_path() -> Path:
    return get_hermes_home() / "cron" / "layer2_memory.sqlite3"


def _copy_legacy_db_if_needed(target_path: Path) -> None:
    legacy_path = _legacy_layer2_db_path()
    if target_path.exists() or not legacy_path.exists() or legacy_path == target_path:
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(legacy_path.read_bytes())


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _json_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return json.dumps(value, sort_keys=True)


def _json_string_list(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        values = [str(item).strip() for item in value if str(item).strip()]
    else:
        text = str(value).strip()
        values = [text] if text else []
    if not values:
        return None
    return json.dumps(sorted(set(values)))


def _derive_provenance(source_ref: str | None) -> Dict[str, Optional[str]]:
    source = _clean_optional_text(source_ref)
    if not source:
        return {"job_id": None, "job_run_id": None, "session_id": None}
    parts = source.split(":")
    if len(parts) >= 3 and parts[0] == "cron":
        return {
            "job_id": parts[1] or None,
            "job_run_id": parts[2] or None,
            "session_id": parts[2] or None,
        }
    return {"job_id": None, "job_run_id": None, "session_id": None}


class Layer2Store:
    """SQLite-backed candidate ledger for Layer-2 memory signals."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _default_layer2_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path is None:
            _copy_legacy_db_if_needed(self.db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_text TEXT NOT NULL UNIQUE,
                    canonical_key TEXT,
                    kind TEXT,
                    proposed_target TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    support_count INTEGER NOT NULL DEFAULT 0,
                    contradict_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    promoted_ref TEXT,
                    routing_destination TEXT,
                    subject_scope TEXT,
                    subject_id TEXT
                );

                CREATE TABLE IF NOT EXISTS candidate_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_ts TEXT NOT NULL,
                    source_ref TEXT,
                    source_event_id TEXT,
                    counts_for_recurrence INTEGER NOT NULL DEFAULT 1,
                    support_delta INTEGER NOT NULL DEFAULT 0,
                    contradict_delta INTEGER NOT NULL DEFAULT 0,
                    durable_target TEXT,
                    durable_content TEXT,
                    notes TEXT,
                    routing_destination TEXT,
                    job_id TEXT,
                    job_run_id TEXT,
                    session_id TEXT,
                    prompt_snapshot_id TEXT,
                    routing_reason_codes TEXT,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_candidate_events_candidate_id
                    ON candidate_events(candidate_id);
                CREATE INDEX IF NOT EXISTS idx_candidate_events_source_event_id
                    ON candidate_events(source_event_id);

                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary_text TEXT NOT NULL,
                    kind TEXT,
                    source_ref TEXT,
                    subject_scope TEXT,
                    subject_id TEXT,
                    job_id TEXT,
                    job_run_id TEXT,
                    session_id TEXT,
                    prompt_snapshot_id TEXT,
                    tags_json TEXT,
                    metadata_json TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_text TEXT NOT NULL,
                    kind TEXT,
                    source_ref TEXT,
                    source_event_id TEXT,
                    subject_scope TEXT,
                    subject_id TEXT,
                    job_id TEXT,
                    job_run_id TEXT,
                    session_id TEXT,
                    prompt_snapshot_id TEXT,
                    tags_json TEXT,
                    metadata_json TEXT,
                    observed_at TEXT NOT NULL,
                    episode_id INTEGER,
                    FOREIGN KEY(episode_id) REFERENCES episodes(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_episodes_updated_at
                    ON episodes(updated_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_observations_observed_at
                    ON observations(observed_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_observations_source_event_id
                    ON observations(source_event_id);

                CREATE TABLE IF NOT EXISTS context_packs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pack_name TEXT NOT NULL UNIQUE,
                    kind TEXT,
                    title TEXT,
                    content_text TEXT NOT NULL,
                    source_ref TEXT,
                    subject_scope TEXT,
                    subject_id TEXT,
                    job_id TEXT,
                    job_run_id TEXT,
                    session_id TEXT,
                    prompt_snapshot_id TEXT,
                    tags_json TEXT,
                    metadata_json TEXT,
                    refresh_policy_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_context_packs_updated_at
                    ON context_packs(updated_at DESC, id DESC);
                """
            )
            _ensure_column(conn, "candidates", "canonical_key", "TEXT")
            self._migrate_canonical_keys(conn)
            _ensure_column(conn, "candidates", "routing_destination", "TEXT")
            _ensure_column(conn, "candidates", "subject_scope", "TEXT")
            _ensure_column(conn, "candidates", "subject_id", "TEXT")
            _ensure_column(conn, "candidate_events", "routing_destination", "TEXT")
            _ensure_column(conn, "candidate_events", "job_id", "TEXT")
            _ensure_column(conn, "candidate_events", "job_run_id", "TEXT")
            _ensure_column(conn, "candidate_events", "session_id", "TEXT")
            _ensure_column(conn, "candidate_events", "prompt_snapshot_id", "TEXT")
            _ensure_column(conn, "candidate_events", "routing_reason_codes", "TEXT")
            _ensure_column(conn, "episodes", "kind", "TEXT")
            _ensure_column(conn, "episodes", "source_ref", "TEXT")
            _ensure_column(conn, "episodes", "subject_scope", "TEXT")
            _ensure_column(conn, "episodes", "subject_id", "TEXT")
            _ensure_column(conn, "episodes", "job_id", "TEXT")
            _ensure_column(conn, "episodes", "job_run_id", "TEXT")
            _ensure_column(conn, "episodes", "session_id", "TEXT")
            _ensure_column(conn, "episodes", "prompt_snapshot_id", "TEXT")
            _ensure_column(conn, "episodes", "tags_json", "TEXT")
            _ensure_column(conn, "episodes", "metadata_json", "TEXT")
            _ensure_column(conn, "episodes", "started_at", "TEXT")
            _ensure_column(conn, "episodes", "ended_at", "TEXT")
            _ensure_column(conn, "episodes", "created_at", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "episodes", "updated_at", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "observations", "kind", "TEXT")
            _ensure_column(conn, "observations", "source_ref", "TEXT")
            _ensure_column(conn, "observations", "source_event_id", "TEXT")
            _ensure_column(conn, "observations", "subject_scope", "TEXT")
            _ensure_column(conn, "observations", "subject_id", "TEXT")
            _ensure_column(conn, "observations", "job_id", "TEXT")
            _ensure_column(conn, "observations", "job_run_id", "TEXT")
            _ensure_column(conn, "observations", "session_id", "TEXT")
            _ensure_column(conn, "observations", "prompt_snapshot_id", "TEXT")
            _ensure_column(conn, "observations", "tags_json", "TEXT")
            _ensure_column(conn, "observations", "metadata_json", "TEXT")
            _ensure_column(conn, "observations", "observed_at", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "observations", "episode_id", "INTEGER")
            _ensure_column(conn, "context_packs", "kind", "TEXT")
            _ensure_column(conn, "context_packs", "title", "TEXT")
            _ensure_column(conn, "context_packs", "source_ref", "TEXT")
            _ensure_column(conn, "context_packs", "subject_scope", "TEXT")
            _ensure_column(conn, "context_packs", "subject_id", "TEXT")
            _ensure_column(conn, "context_packs", "job_id", "TEXT")
            _ensure_column(conn, "context_packs", "job_run_id", "TEXT")
            _ensure_column(conn, "context_packs", "session_id", "TEXT")
            _ensure_column(conn, "context_packs", "prompt_snapshot_id", "TEXT")
            _ensure_column(conn, "context_packs", "tags_json", "TEXT")
            _ensure_column(conn, "context_packs", "metadata_json", "TEXT")
            _ensure_column(conn, "context_packs", "refresh_policy_json", "TEXT")
            _ensure_column(conn, "context_packs", "created_at", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "context_packs", "updated_at", "TEXT NOT NULL DEFAULT ''")

    def _migrate_canonical_keys(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT id, canonical_text, canonical_key FROM candidates ORDER BY id ASC").fetchall()
        for row in rows:
            key = (row["canonical_key"] or "").strip() or canonical_key_for_text(row["canonical_text"])
            conn.execute("UPDATE candidates SET canonical_key = ? WHERE id = ?", (key, row["id"]))
        self.merge_canonical_key_collisions(conn=conn)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_canonical_key_unique "
            "ON candidates(canonical_key) WHERE canonical_key IS NOT NULL AND canonical_key != ''"
        )

    def merge_canonical_key_collisions(self, *, conn: sqlite3.Connection | None = None) -> List[Dict[str, Any]]:
        """Merge deterministic canonical-key duplicate candidates.

        Safe to run repeatedly. It only merges rows whose normalized key is
        identical (case/whitespace/terminal-punctuation variants).
        """
        owns_conn = conn is None
        connection = conn or self._connect()
        audits: List[Dict[str, Any]] = []
        try:
            groups = connection.execute(
                """
                SELECT canonical_key, COUNT(*) AS n
                FROM candidates
                WHERE canonical_key IS NOT NULL AND canonical_key != ''
                GROUP BY canonical_key
                HAVING n > 1
                """
            ).fetchall()
            for group in groups:
                rows = connection.execute(
                    "SELECT * FROM candidates WHERE canonical_key = ? ORDER BY support_count DESC, LENGTH(canonical_text) DESC, id ASC",
                    (group["canonical_key"],),
                ).fetchall()
                if len(rows) < 2:
                    continue
                survivor = rows[0]
                survivor_id = survivor["id"]
                victim_ids = [row["id"] for row in rows[1:]]
                total_support = sum(int(row["support_count"] or 0) for row in rows)
                total_contradict = sum(int(row["contradict_count"] or 0) for row in rows)
                statuses = {str(row["status"] or "active") for row in rows}
                if "promoted" in statuses:
                    merged_status = "promoted"
                elif "active" in statuses:
                    merged_status = "active"
                elif "quarantine" in statuses:
                    merged_status = "quarantine"
                elif "quarantined" in statuses:
                    merged_status = "quarantine"
                elif "stale" in statuses:
                    merged_status = "stale"
                else:
                    merged_status = survivor["status"]
                latest_updated = max(str(row["updated_at"] or "") for row in rows)
                for victim_id in victim_ids:
                    connection.execute(
                        "UPDATE candidate_events SET candidate_id = ? WHERE candidate_id = ?",
                        (survivor_id, victim_id),
                    )
                connection.execute(
                    """
                    UPDATE candidates
                    SET support_count = ?, contradict_count = ?, status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (total_support, total_contradict, merged_status, latest_updated, survivor_id),
                )
                connection.execute(
                    f"DELETE FROM candidates WHERE id IN ({','.join('?' for _ in victim_ids)})",
                    victim_ids,
                )
                audits.append({
                    "audit_label": "candidates_merged",
                    "survivor_id": survivor_id,
                    "merged_candidate_ids": victim_ids,
                    "canonical_key": group["canonical_key"],
                    "canonical_text": survivor["canonical_text"],
                })
            if owns_conn:
                connection.commit()
        finally:
            if owns_conn:
                connection.close()
        return audits

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        return dict(row) if row is not None else None

    def get_candidate(self, canonical_text: str) -> Optional[Dict[str, Any]]:
        key = canonical_key_for_text(canonical_text)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM candidates WHERE canonical_key = ? OR canonical_text = ? ORDER BY id ASC LIMIT 1",
                (key, canonical_text.strip()),
            ).fetchone()
        return self._row_to_dict(row)

    def list_candidates(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM candidates ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_candidates_by_status(
        self,
        *,
        status: str | None = "active",
        max_items: int = 20,
        query_text: str | None = None,
        subject_scope: str | None = None,
        subject_id: str | None = None,
        min_support_count: int = 0,
    ) -> List[Dict[str, Any]]:
        limit = max(1, int(max_items))
        min_support = max(0, int(min_support_count))
        requested_status = (status or "active").strip().lower()
        requested_scope = _clean_optional_text(subject_scope)
        requested_subject_id = _clean_optional_text(subject_id)
        query_terms = {
            term
            for term in re.split(r"[^a-z0-9]+", (query_text or "").lower())
            if len(term) >= 2
        }
        sql = "SELECT * FROM candidates WHERE support_count >= ?"
        params: list[Any] = [min_support]
        if requested_status != "all":
            sql += " AND status = ?"
            params.append(requested_status)
        sql += " ORDER BY updated_at DESC, id DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            candidate = dict(row)
            if requested_scope and _clean_optional_text(candidate.get("subject_scope")) != requested_scope:
                continue
            if requested_subject_id and _clean_optional_text(candidate.get("subject_id")) != requested_subject_id:
                continue
            haystack = " ".join(
                filter(None, [str(candidate.get("canonical_text") or ""), str(candidate.get("kind") or "")])
            ).lower()
            if query_terms and not any(term in haystack for term in query_terms):
                continue
            results.append(candidate)
            if len(results) >= limit:
                break
        return results

    def list_events(self, canonical_text: str) -> List[Dict[str, Any]]:
        candidate = self.get_candidate(canonical_text)
        if not candidate:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM candidate_events WHERE candidate_id = ? ORDER BY id ASC",
                (candidate["id"],),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_episodes(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_observations(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM observations ORDER BY observed_at DESC, id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_context_pack(self, pack_name: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM context_packs WHERE pack_name = ?",
                ((pack_name or "").strip(),),
            ).fetchone()
        return self._row_to_dict(row)

    def list_context_packs(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM context_packs ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def record_context_pack(
        self,
        *,
        pack_name: str,
        content_text: str,
        kind: Optional[str] = None,
        title: Optional[str] = None,
        source_ref: Optional[str] = None,
        subject_scope: Optional[str] = None,
        subject_id: Optional[str] = None,
        job_id: Optional[str] = None,
        job_run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        prompt_snapshot_id: Optional[str] = None,
        tags: Any = None,
        metadata: Any = None,
        refresh_policy: Any = None,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        name = (pack_name or "").strip()
        content = (content_text or "").strip()
        if not name:
            raise ValueError("pack_name is required")
        if not content:
            raise ValueError("content_text is required")
        derived = _derive_provenance(source_ref)
        now = created_at or _hermes_now().isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, created_at FROM context_packs WHERE pack_name = ?",
                (name,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO context_packs (
                        pack_name, kind, title, content_text, source_ref,
                        subject_scope, subject_id, job_id, job_run_id, session_id,
                        prompt_snapshot_id, tags_json, metadata_json, refresh_policy_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        _clean_optional_text(kind),
                        _clean_optional_text(title),
                        content,
                        _clean_optional_text(source_ref),
                        _clean_optional_text(subject_scope),
                        _clean_optional_text(subject_id),
                        _clean_optional_text(job_id) or derived["job_id"],
                        _clean_optional_text(job_run_id) or derived["job_run_id"],
                        _clean_optional_text(session_id) or derived["session_id"],
                        _clean_optional_text(prompt_snapshot_id),
                        _json_string_list(tags),
                        _json_text(metadata),
                        _json_text(refresh_policy),
                        now,
                        now,
                    ),
                )
                row = conn.execute("SELECT * FROM context_packs WHERE pack_name = ?", (name,)).fetchone()
            else:
                conn.execute(
                    """
                    UPDATE context_packs
                    SET kind = ?,
                        title = ?,
                        content_text = ?,
                        source_ref = ?,
                        subject_scope = ?,
                        subject_id = ?,
                        job_id = ?,
                        job_run_id = ?,
                        session_id = ?,
                        prompt_snapshot_id = ?,
                        tags_json = ?,
                        metadata_json = ?,
                        refresh_policy_json = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _clean_optional_text(kind),
                        _clean_optional_text(title),
                        content,
                        _clean_optional_text(source_ref),
                        _clean_optional_text(subject_scope),
                        _clean_optional_text(subject_id),
                        _clean_optional_text(job_id) or derived["job_id"],
                        _clean_optional_text(job_run_id) or derived["job_run_id"],
                        _clean_optional_text(session_id) or derived["session_id"],
                        _clean_optional_text(prompt_snapshot_id),
                        _json_string_list(tags),
                        _json_text(metadata),
                        _json_text(refresh_policy),
                        now,
                        existing["id"],
                    ),
                )
                row = conn.execute("SELECT * FROM context_packs WHERE id = ?", (existing["id"],)).fetchone()
        return dict(row)

    def record_episode(
        self,
        *,
        summary_text: str,
        kind: Optional[str] = None,
        source_ref: Optional[str] = None,
        subject_scope: Optional[str] = None,
        subject_id: Optional[str] = None,
        job_id: Optional[str] = None,
        job_run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        prompt_snapshot_id: Optional[str] = None,
        tags: Any = None,
        metadata: Any = None,
        started_at: Optional[str] = None,
        ended_at: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        summary = (summary_text or "").strip()
        if not summary:
            raise ValueError("summary_text is required")
        derived = _derive_provenance(source_ref)
        now = created_at or _hermes_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO episodes (
                    summary_text, kind, source_ref, subject_scope, subject_id,
                    job_id, job_run_id, session_id, prompt_snapshot_id,
                    tags_json, metadata_json, started_at, ended_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary,
                    _clean_optional_text(kind),
                    _clean_optional_text(source_ref),
                    _clean_optional_text(subject_scope),
                    _clean_optional_text(subject_id),
                    _clean_optional_text(job_id) or derived["job_id"],
                    _clean_optional_text(job_run_id) or derived["job_run_id"],
                    _clean_optional_text(session_id) or derived["session_id"],
                    _clean_optional_text(prompt_snapshot_id),
                    _json_string_list(tags),
                    _json_text(metadata),
                    _clean_optional_text(started_at),
                    _clean_optional_text(ended_at),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM episodes WHERE id = last_insert_rowid()").fetchone()
        return dict(row)

    def record_observation(
        self,
        *,
        observation_text: str,
        kind: Optional[str] = None,
        source_ref: Optional[str] = None,
        source_event_id: Optional[str] = None,
        subject_scope: Optional[str] = None,
        subject_id: Optional[str] = None,
        job_id: Optional[str] = None,
        job_run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        prompt_snapshot_id: Optional[str] = None,
        tags: Any = None,
        metadata: Any = None,
        observed_at: Optional[str] = None,
        episode_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        observation = (observation_text or "").strip()
        if not observation:
            raise ValueError("observation_text is required")
        derived = _derive_provenance(source_ref)
        now = observed_at or _hermes_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO observations (
                    observation_text, kind, source_ref, source_event_id, subject_scope, subject_id,
                    job_id, job_run_id, session_id, prompt_snapshot_id,
                    tags_json, metadata_json, observed_at, episode_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation,
                    _clean_optional_text(kind),
                    _clean_optional_text(source_ref),
                    _clean_optional_text(source_event_id),
                    _clean_optional_text(subject_scope),
                    _clean_optional_text(subject_id),
                    _clean_optional_text(job_id) or derived["job_id"],
                    _clean_optional_text(job_run_id) or derived["job_run_id"],
                    _clean_optional_text(session_id) or derived["session_id"],
                    _clean_optional_text(prompt_snapshot_id),
                    _json_string_list(tags),
                    _json_text(metadata),
                    now,
                    episode_id,
                ),
            )
            row = conn.execute("SELECT * FROM observations WHERE id = last_insert_rowid()").fetchone()
        return dict(row)

    def query_episodes_for_pack(self, *, max_items: int = 2) -> List[Dict[str, Any]]:
        limit = max(0, int(max_items))
        if limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY updated_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def query_observations_for_pack(self, *, max_items: int = 2) -> List[Dict[str, Any]]:
        limit = max(0, int(max_items))
        if limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM observations ORDER BY observed_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def query_context_packs_for_pack(
        self,
        *,
        explicit_pack_names: list[str] | None = None,
        query_text: str | None = None,
        max_items: int = 2,
    ) -> List[Dict[str, Any]]:
        limit = max(0, int(max_items))
        if limit <= 0:
            return []

        requested_names = [str(item).strip() for item in (explicit_pack_names or []) if str(item).strip()]
        query = (query_text or "").strip().lower()
        if not requested_names and not query:
            return []

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM context_packs ORDER BY updated_at DESC, id DESC"
            ).fetchall()

        packs = [dict(row) for row in rows]
        if requested_names:
            order = {name: idx for idx, name in enumerate(requested_names)}
            selected = [pack for pack in packs if pack.get("pack_name") in order]
            selected.sort(key=lambda pack: order.get(pack.get("pack_name"), len(order)))
            return selected[:limit]

        query_terms = {term for term in re.split(r"[^a-z0-9]+", query) if len(term) >= 3}
        scored: List[tuple[int, Dict[str, Any]]] = []
        for pack in packs:
            haystack = " ".join(
                filter(
                    None,
                    [
                        str(pack.get("pack_name") or ""),
                        str(pack.get("title") or ""),
                        str(pack.get("kind") or ""),
                        str(pack.get("content_text") or ""),
                        str(pack.get("tags_json") or ""),
                    ],
                )
            ).lower()
            score = sum(1 for term in query_terms if term in haystack)
            if score > 0:
                scored.append((score, pack))
        scored.sort(key=lambda item: (-item[0], -(item[1].get("id") or 0)))
        return [pack for _, pack in scored[:limit]]

    def query_candidates_for_pack(
        self,
        destinations: list[str] | None = None,
        max_items: int = 6,
        min_support_count: int = 2,
        query_text: str | None = None,
        subject_scope: str | None = None,
        subject_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        limit = max(1, int(max_items))
        min_support = max(0, int(min_support_count))
        normalized_destinations = {
            value
            for value in (normalize_destination(item) for item in (destinations or []))
            if value
        }
        requested_scope = _clean_optional_text(subject_scope)
        requested_subject_id = _clean_optional_text(subject_id)
        query_terms = {
            term
            for term in re.split(r"[^a-z0-9]+", (query_text or "").lower())
            if len(term) >= 2
        }

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM candidates
                WHERE status = 'active'
                  AND support_count >= ?
                ORDER BY support_count DESC, updated_at DESC, id DESC
                """,
                (min_support,),
            ).fetchall()

        scored_results: List[tuple[int, int, int, Dict[str, Any]]] = []
        for row in rows:
            candidate = dict(row)
            candidate["proposed_target"] = normalize_destination(candidate.get("proposed_target"))
            candidate["routing_destination"] = normalize_destination(
                candidate.get("routing_destination") or candidate.get("proposed_target")
            )
            if normalized_destinations and candidate["routing_destination"] not in normalized_destinations:
                continue
            if requested_scope and _clean_optional_text(candidate.get("subject_scope")) != requested_scope:
                continue
            if requested_subject_id and _clean_optional_text(candidate.get("subject_id")) != requested_subject_id:
                continue
            haystack = " ".join(
                filter(
                    None,
                    [
                        str(candidate.get("canonical_text") or ""),
                        str(candidate.get("kind") or ""),
                        str(candidate.get("routing_destination") or ""),
                    ],
                )
            ).lower()
            query_score = sum(1 for term in query_terms if term in haystack)
            if query_terms and query_score <= 0:
                continue
            support = int(candidate.get("support_count") or 0)
            contradict = int(candidate.get("contradict_count") or 0)
            net_support = support - contradict
            scored_results.append(
                (query_score, net_support, int(candidate.get("id") or 0), candidate)
            )

        scored_results.sort(key=lambda item: (-item[0], -item[1], -item[2]))
        return [candidate for *_unused, candidate in scored_results[:limit]]

    def record_event(
        self,
        *,
        event_type: str,
        canonical_text: str,
        kind: Optional[str] = None,
        proposed_target: Optional[str] = None,
        status: Optional[str] = None,
        promoted_ref: Optional[str] = None,
        source_ref: Optional[str] = None,
        source_event_id: Optional[str] = None,
        counts_for_recurrence: bool = True,
        durable_target: Optional[str] = None,
        durable_content: Optional[str] = None,
        notes: Optional[str] = None,
        event_ts: Optional[str] = None,
        routing_destination: Optional[str] = None,
        subject_scope: Optional[str] = None,
        subject_id: Optional[str] = None,
        job_id: Optional[str] = None,
        job_run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        prompt_snapshot_id: Optional[str] = None,
        routing_reason_codes: Any = None,
    ) -> Dict[str, Any]:
        canonical = (canonical_text or "").strip()
        if not canonical:
            raise ValueError("canonical_text is required")
        canonical_key = canonical_key_for_text(canonical)
        if not canonical_key:
            raise ValueError("canonical_text must contain non-punctuation content")

        event_name = (event_type or "").strip().lower()
        if event_name not in {"create", "strengthen", "contradict", "prune", "promote"}:
            raise ValueError(f"Unsupported Layer-2 event_type: {event_type!r}")

        normalized_target = normalize_destination(proposed_target)
        normalized_routing_destination = normalize_destination(routing_destination or proposed_target)
        normalized_durable_target = durable_store_target(durable_target)
        derived = _derive_provenance(source_ref)
        job_id = _clean_optional_text(job_id) or derived["job_id"]
        job_run_id = _clean_optional_text(job_run_id) or derived["job_run_id"]
        session_id = _clean_optional_text(session_id) or derived["session_id"]
        prompt_snapshot_id = _clean_optional_text(prompt_snapshot_id)
        subject_scope = _clean_optional_text(subject_scope)
        subject_id = _clean_optional_text(subject_id)
        notes = _clean_optional_text(notes)
        source_ref = _clean_optional_text(source_ref)
        source_event_id = _clean_optional_text(source_event_id)
        routing_reason_codes_json = _json_text(routing_reason_codes)

        now = event_ts or _hermes_now().isoformat()
        effective_counts_for_recurrence = bool(counts_for_recurrence)
        audit_label_override: str | None = None
        support_delta = 1 if effective_counts_for_recurrence and event_name in {"create", "strengthen"} else 0
        contradict_delta = 1 if effective_counts_for_recurrence and event_name == "contradict" else 0
        next_status = status

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM candidates WHERE canonical_key = ? OR canonical_text = ? ORDER BY id ASC LIMIT 1",
                (canonical_key, canonical),
            ).fetchone()
            created = row is None
            candidate_id = row["id"] if row is not None else None
            if next_status is None:
                if event_name == "prune":
                    next_status = "pruned"
                elif event_name == "promote":
                    next_status = "promoted"
                elif row is not None:
                    # Do not implicitly reactivate quarantined/stale/pruned candidates when a
                    # later non-transition event merely mentions or strengthens the same text.
                    next_status = row["status"]
                else:
                    next_status = "active"
            if (
                candidate_id is not None
                and effective_counts_for_recurrence
                and event_name in {"create", "strengthen"}
                and job_id
            ):
                now_dt = _parse_iso_datetime(now)
                cutoff = (now_dt - timedelta(hours=24)).isoformat() if now_dt else None
                if cutoff:
                    recent = conn.execute(
                        """
                        SELECT id FROM candidate_events
                        WHERE candidate_id = ?
                          AND job_id = ?
                          AND event_type IN ('create', 'strengthen')
                          AND counts_for_recurrence = 1
                          AND event_ts >= ?
                        LIMIT 1
                        """,
                        (candidate_id, job_id, cutoff),
                    ).fetchone()
                    if recent is not None:
                        effective_counts_for_recurrence = False
                        support_delta = 0
                        contradict_delta = 0
                        audit_label_override = "daily_replay_suppressed"
            if candidate_id is not None and source_event_id:
                existing_event = conn.execute(
                    """
                    SELECT id, event_type FROM candidate_events
                    WHERE candidate_id = ? AND source_event_id = ?
                    """,
                    (candidate_id, source_event_id),
                ).fetchone()
                if existing_event is not None:
                    current = conn.execute(
                        "SELECT * FROM candidates WHERE id = ?",
                        (candidate_id,),
                    ).fetchone()
                    return {
                        "audit_label": "duplicate_ignored",
                        "candidate": dict(current),
                        "event": {
                            "id": existing_event["id"],
                            "event_type": event_name,
                            "event_ts": now,
                            "source_ref": source_ref,
                            "source_event_id": source_event_id,
                            "counts_for_recurrence": effective_counts_for_recurrence,
                            "support_delta": 0,
                            "contradict_delta": 0,
                            "durable_target": normalized_durable_target,
                            "durable_content": durable_content,
                            "notes": notes,
                            "routing_destination": normalized_routing_destination,
                            "job_id": job_id,
                            "job_run_id": job_run_id,
                            "session_id": session_id,
                            "prompt_snapshot_id": prompt_snapshot_id,
                            "routing_reason_codes": routing_reason_codes_json,
                        },
                    }
            if created:
                conn.execute(
                    """
                    INSERT INTO candidates (
                        canonical_text, canonical_key, kind, proposed_target, status,
                        support_count, contradict_count, created_at, updated_at, promoted_ref,
                        routing_destination, subject_scope, subject_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        canonical,
                        canonical_key,
                        kind,
                        normalized_target,
                        next_status,
                        support_delta,
                        contradict_delta,
                        now,
                        now,
                        promoted_ref,
                        normalized_routing_destination,
                        subject_scope,
                        subject_id,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM candidates WHERE canonical_key = ?",
                    (canonical_key,),
                ).fetchone()
            else:
                merged_kind = kind or row["kind"]
                merged_target = normalized_target or row["proposed_target"]
                merged_ref = promoted_ref or row["promoted_ref"]
                merged_destination = normalized_routing_destination or row["routing_destination"]
                merged_subject_scope = subject_scope or row["subject_scope"]
                merged_subject_id = subject_id or row["subject_id"]
                conn.execute(
                    """
                    UPDATE candidates
                    SET kind = ?,
                        proposed_target = ?,
                        status = ?,
                        support_count = support_count + ?,
                        contradict_count = contradict_count + ?,
                        updated_at = ?,
                        promoted_ref = ?,
                        routing_destination = ?,
                        subject_scope = ?,
                        subject_id = ?
                    WHERE id = ?
                    """,
                    (
                        merged_kind,
                        merged_target,
                        next_status,
                        support_delta,
                        contradict_delta,
                        now,
                        merged_ref,
                        merged_destination,
                        merged_subject_scope,
                        merged_subject_id,
                        row["id"],
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM candidates WHERE id = ?",
                    (row["id"],),
                ).fetchone()

            conn.execute(
                """
                INSERT INTO candidate_events (
                    candidate_id, event_type, event_ts, source_ref, source_event_id,
                    counts_for_recurrence, support_delta, contradict_delta,
                    durable_target, durable_content, notes, routing_destination,
                    job_id, job_run_id, session_id, prompt_snapshot_id, routing_reason_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    event_name,
                    now,
                    source_ref,
                    source_event_id,
                    1 if effective_counts_for_recurrence else 0,
                    support_delta,
                    contradict_delta,
                    normalized_durable_target,
                    durable_content,
                    notes,
                    normalized_routing_destination,
                    job_id,
                    job_run_id,
                    session_id,
                    prompt_snapshot_id,
                    routing_reason_codes_json,
                ),
            )
            event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        candidate = dict(row)
        audit_label = audit_label_override or {
            "create": "candidate_created",
            "strengthen": "candidate_strengthened",
            "contradict": "candidate_contradicted",
            "prune": "candidate_pruned",
            "promote": "candidate_promoted",
        }[event_name]
        return {
            "audit_label": audit_label,
            "candidate": candidate,
            "event": {
                "id": event_id,
                "event_type": event_name,
                "event_ts": now,
                "source_ref": source_ref,
                "source_event_id": source_event_id,
                "counts_for_recurrence": effective_counts_for_recurrence,
                "support_delta": support_delta,
                "contradict_delta": contradict_delta,
                "durable_target": normalized_durable_target,
                "durable_content": durable_content,
                "notes": notes,
                "routing_destination": normalized_routing_destination,
                "job_id": job_id,
                "job_run_id": job_run_id,
                "session_id": session_id,
                "prompt_snapshot_id": prompt_snapshot_id,
                "routing_reason_codes": routing_reason_codes_json,
            },
        }


def parse_layer2_payload(final_response: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Extract a fenced Layer-2 payload and return (clean_text, payload)."""
    text = final_response or ""
    match = _LAYER2_FENCE_RE.search(text)
    if not match:
        return text, None

    body = match.group("body").strip()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.warning("Ignoring invalid hermes-layer2 payload: %s", exc)
        return text, None

    if not isinstance(payload, dict):
        logger.warning("Ignoring hermes-layer2 payload that is not a JSON object")
        return text, None

    clean = (text[: match.start()] + text[match.end() :]).strip()
    return clean, payload


def _memory_pipeline_config(job: Dict[str, Any]) -> Dict[str, Any]:
    cfg = job.get("memory_pipeline")
    return cfg if isinstance(cfg, dict) else {}


def job_allows_layer2(job: Dict[str, Any]) -> bool:
    cfg = _memory_pipeline_config(job)
    return bool(cfg.get("enabled"))


def _allowed_promotion_targets(job: Dict[str, Any]) -> set[str]:
    cfg = _memory_pipeline_config(job)
    raw = cfg.get("allow_durable_promotion_targets") or []
    if raw is True:
        return {"memory", "user"}
    if isinstance(raw, str):
        return {raw.strip().lower()} if raw.strip() else set()
    if isinstance(raw, (list, tuple, set)):
        return {str(item).strip().lower() for item in raw if str(item).strip()}
    return set()


def apply_layer2_payload(
    job: Dict[str, Any],
    payload: Optional[Dict[str, Any]],
    *,
    source_ref: str,
    store: Optional[Layer2Store] = None,
    job_id: Optional[str] = None,
    job_run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    prompt_snapshot_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Apply a parsed Layer-2 payload if the job opts into the memory pipeline."""
    if not payload or not job_allows_layer2(job):
        return []

    ledger = store or Layer2Store()
    derived = _derive_provenance(source_ref)
    resolved_job_id = _clean_optional_text(job_id) or _clean_optional_text(job.get("id")) or derived["job_id"]
    resolved_job_run_id = _clean_optional_text(job_run_id) or derived["job_run_id"]
    resolved_session_id = _clean_optional_text(session_id) or derived["session_id"]
    resolved_prompt_snapshot_id = _clean_optional_text(prompt_snapshot_id)
    audit_events: List[Dict[str, Any]] = []
    observation_source_event_ids: set[str] = set()
    raw_observations = payload.get("observations")
    if isinstance(raw_observations, list):
        for idx, item in enumerate(raw_observations):
            if not isinstance(item, dict):
                continue
            observation_text = str(item.get("observation_text") or item.get("content") or "").strip()
            if not observation_text:
                continue
            observation_source_event_ids.add(
                _clean_optional_text(item.get("source_event_id")) or f"{source_ref}:observation:{idx}"
            )

    candidate_events = payload.get("candidate_events")
    if isinstance(candidate_events, list):
        for idx, item in enumerate(candidate_events):
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or item.get("event_type") or "").strip().lower()
            canonical_text = str(item.get("canonical_text") or "").strip()
            if action not in {"create", "strengthen", "contradict", "prune"} or not canonical_text:
                continue
            item_source_ref = _clean_optional_text(item.get("source_ref")) or source_ref
            item_source_event_id = _clean_optional_text(item.get("source_event_id")) or f"{source_ref}:candidate:{idx}"
            counts_for_recurrence = bool(item.get("counts_for_recurrence", True))
            raw_evidence_ids = item.get("evidence_source_event_ids")
            if raw_evidence_ids is None:
                raw_evidence_ids = item.get("evidence_source_event_id")
            if isinstance(raw_evidence_ids, str):
                evidence_ids = {_clean_optional_text(raw_evidence_ids)}
            elif isinstance(raw_evidence_ids, (list, tuple, set)):
                evidence_ids = {_clean_optional_text(value) for value in raw_evidence_ids}
            else:
                # Backward-compatible form: a candidate event may use the same
                # source_event_id as the observation it directly derives from.
                evidence_ids = {item_source_event_id}
            evidence_ids = {value for value in evidence_ids if value}
            has_observation_evidence = bool(evidence_ids & observation_source_event_ids)
            demote_unbacked = (
                counts_for_recurrence
                and action in {"create", "strengthen", "contradict"}
                and not has_observation_evidence
            )
            if demote_unbacked:
                counts_for_recurrence = False
            applied = ledger.record_event(
                event_type=action,
                canonical_text=canonical_text,
                kind=_clean_optional_text(item.get("kind")),
                proposed_target=_clean_optional_text(item.get("proposed_target")),
                status=_clean_optional_text(item.get("status")),
                source_ref=item_source_ref,
                source_event_id=item_source_event_id,
                counts_for_recurrence=counts_for_recurrence,
                notes=_clean_optional_text(item.get("notes")),
                routing_destination=_clean_optional_text(item.get("routing_destination")),
                subject_scope=_clean_optional_text(item.get("subject_scope")),
                subject_id=_clean_optional_text(item.get("subject_id")),
                job_id=resolved_job_id,
                job_run_id=resolved_job_run_id,
                session_id=resolved_session_id,
                prompt_snapshot_id=resolved_prompt_snapshot_id,
                routing_reason_codes=item.get("routing_reason_codes"),
            )
            if demote_unbacked:
                applied["audit_label"] = "unbacked_candidate_demoted"
                applied["event"]["counts_for_recurrence"] = False
            audit_events.append(applied)

    episodes = payload.get("episodes")
    if isinstance(episodes, list):
        for item in episodes:
            if not isinstance(item, dict):
                continue
            summary_text = str(item.get("summary_text") or item.get("content") or "").strip()
            if not summary_text:
                continue
            stored = ledger.record_episode(
                summary_text=summary_text,
                kind=_clean_optional_text(item.get("kind")),
                source_ref=_clean_optional_text(item.get("source_ref")) or source_ref,
                subject_scope=_clean_optional_text(item.get("subject_scope")),
                subject_id=_clean_optional_text(item.get("subject_id")),
                job_id=resolved_job_id,
                job_run_id=resolved_job_run_id,
                session_id=resolved_session_id,
                prompt_snapshot_id=resolved_prompt_snapshot_id,
                tags=item.get("tags"),
                metadata=item.get("metadata"),
                started_at=_clean_optional_text(item.get("started_at")),
                ended_at=_clean_optional_text(item.get("ended_at")),
                created_at=_clean_optional_text(item.get("created_at")),
            )
            audit_events.append({"audit_label": "episode_stored", "episode": stored})

    observations = payload.get("observations")
    if isinstance(observations, list):
        for idx, item in enumerate(observations):
            if not isinstance(item, dict):
                continue
            observation_text = str(item.get("observation_text") or item.get("content") or "").strip()
            if not observation_text:
                continue
            stored = ledger.record_observation(
                observation_text=observation_text,
                kind=_clean_optional_text(item.get("kind")),
                source_ref=_clean_optional_text(item.get("source_ref")) or source_ref,
                source_event_id=_clean_optional_text(item.get("source_event_id"))
                or f"{source_ref}:observation:{idx}",
                subject_scope=_clean_optional_text(item.get("subject_scope")),
                subject_id=_clean_optional_text(item.get("subject_id")),
                job_id=resolved_job_id,
                job_run_id=resolved_job_run_id,
                session_id=resolved_session_id,
                prompt_snapshot_id=resolved_prompt_snapshot_id,
                tags=item.get("tags"),
                metadata=item.get("metadata"),
                observed_at=_clean_optional_text(item.get("observed_at")),
                episode_id=item.get("episode_id"),
            )
            audit_events.append({"audit_label": "observation_stored", "observation": stored})

    context_packs = payload.get("context_packs")
    if isinstance(context_packs, list):
        for item in context_packs:
            if not isinstance(item, dict):
                continue
            pack_name = str(item.get("pack_name") or item.get("name") or "").strip()
            content_text = str(item.get("content_text") or item.get("content") or "").strip()
            if not pack_name or not content_text:
                continue
            stored = ledger.record_context_pack(
                pack_name=pack_name,
                content_text=content_text,
                kind=_clean_optional_text(item.get("kind")),
                title=_clean_optional_text(item.get("title")),
                source_ref=_clean_optional_text(item.get("source_ref")) or source_ref,
                subject_scope=_clean_optional_text(item.get("subject_scope")),
                subject_id=_clean_optional_text(item.get("subject_id")),
                job_id=resolved_job_id,
                job_run_id=resolved_job_run_id,
                session_id=resolved_session_id,
                prompt_snapshot_id=resolved_prompt_snapshot_id,
                tags=item.get("tags"),
                metadata=item.get("metadata"),
                refresh_policy=item.get("refresh_policy"),
                created_at=_clean_optional_text(item.get("created_at")),
            )
            audit_events.append({"audit_label": "context_pack_stored", "context_pack": stored})

    allowed_targets = _allowed_promotion_targets(job)
    promotions = payload.get("promotions")
    if isinstance(promotions, list):
        memory_store: Optional[MemoryStore] = None
        for idx, item in enumerate(promotions):
            if not isinstance(item, dict):
                continue
            target = str(item.get("target") or "").strip().lower()
            content = str(item.get("content") or item.get("canonical_text") or "").strip()
            canonical_text = str(item.get("canonical_text") or content).strip()
            if target not in {"memory", "user"} or not canonical_text or not content:
                continue
            if target not in allowed_targets:
                continue
            if memory_store is None:
                memory_store = MemoryStore()
                memory_store.load_from_disk()
            durable_target = durable_store_target(target)
            result = memory_store.add(durable_target, content)
            if not result.get("success"):
                audit_events.append(
                    {
                        "audit_label": "durable_write_failed",
                        "target": durable_target,
                        "content": content,
                        "error": result.get("error") or "unknown error",
                    }
                )
                continue
            promoted_ref = f"{durable_target}:{content}"
            item_source_ref = _clean_optional_text(item.get("source_ref")) or source_ref
            applied = ledger.record_event(
                event_type="promote",
                canonical_text=canonical_text,
                kind=_clean_optional_text(item.get("kind")),
                proposed_target=target,
                status="promoted",
                promoted_ref=promoted_ref,
                source_ref=item_source_ref,
                source_event_id=_clean_optional_text(item.get("source_event_id"))
                or f"{source_ref}:promotion:{idx}",
                counts_for_recurrence=False,
                durable_target=durable_target,
                durable_content=content,
                notes=_clean_optional_text(item.get("notes")) or "durable_write",
                routing_destination=_clean_optional_text(item.get("routing_destination")) or target,
                subject_scope=_clean_optional_text(item.get("subject_scope")),
                subject_id=_clean_optional_text(item.get("subject_id")),
                job_id=resolved_job_id,
                job_run_id=resolved_job_run_id,
                session_id=resolved_session_id,
                prompt_snapshot_id=resolved_prompt_snapshot_id,
                routing_reason_codes=item.get("routing_reason_codes"),
            )
            audit_events.append(applied)
            audit_events.append(
                {
                    "audit_label": "durable_write",
                    "target": durable_target,
                    "content": content,
                    "candidate": applied["candidate"],
                }
            )

    return audit_events


def format_layer2_audit_section(audit_events: List[Dict[str, Any]]) -> str:
    if not audit_events:
        return ""
    lines = ["## Layer-2 Audit", ""]
    for item in audit_events:
        label = item.get("audit_label", "layer2_event")
        if label == "durable_write":
            lines.append(
                f"- durable_write → {item.get('target')}: {item.get('content')}"
            )
            continue
        if label == "durable_write_failed":
            lines.append(
                f"- durable_write_failed → {item.get('target')}: {item.get('error')}"
            )
            continue
        candidate = item.get("candidate") or {}
        event = item.get("event") or {}
        destination = (
            candidate.get("routing_destination")
            or event.get("routing_destination")
            or candidate.get("proposed_target")
            or "-"
        )
        lines.append(
            "- "
            f"{label}: [{candidate.get('status', 'unknown')}] "
            f"{destination} / {candidate.get('kind') or '-'} / "
            f"{candidate.get('canonical_text')!r} "
            f"(support={candidate.get('support_count', 0)}, "
            f"contradict={candidate.get('contradict_count', 0)}, "
            f"counts={bool(event.get('counts_for_recurrence', True))})"
        )
    return "\n".join(lines)


def _clean_optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
