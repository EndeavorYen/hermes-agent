"""SQLite-backed Layer-2 sidecar ledger for local learning cron jobs."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from hermes_constants import get_hermes_home
from hermes_time import now as _hermes_now
from memory.layer2_schema import validate_layer2_payload

logger = logging.getLogger(__name__)

_LAYER2_FENCE_RE = re.compile(
    r"```hermes-layer2\s*\n(?P<body>.*?)\n```",
    re.IGNORECASE | re.DOTALL,
)


def _clean_optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def canonical_key_for_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" \t\r\n.,;:!?")
    return re.sub(r"\s+", " ", text)


def normalize_destination(raw: str | None) -> str | None:
    value = _clean_optional_text(raw)
    if value == "memory":
        return "prior"
    return value


def _default_layer2_db_path() -> Path:
    return get_hermes_home() / "memory" / "layer2.sqlite3"


def _legacy_layer2_db_path() -> Path:
    return get_hermes_home() / "cron" / "layer2_memory.sqlite3"


def _backup_sqlite_db(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _copy_legacy_db_if_needed(target_path: Path) -> None:
    legacy_path = _legacy_layer2_db_path()
    if target_path.exists() or not legacy_path.exists() or legacy_path == target_path:
        return
    _backup_sqlite_db(legacy_path, target_path)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _json_string_list(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        values = [str(item).strip() for item in value if str(item).strip()]
    else:
        values = [str(value).strip()]
    values = [value for value in values if value]
    return json.dumps(sorted(set(values))) if values else None


class Layer2Store:
    """Audit-first local Layer-2 ledger.

    This is intentionally a compatibility bridge for local cron contracts. New
    cross-session recall should prefer upstream memory-provider plugins.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _default_layer2_db_path()
        if db_path is None:
            _copy_legacy_db_if_needed(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
                    episode_id INTEGER
                );
                """
            )
            _ensure_column(conn, "candidates", "canonical_key", "TEXT")
            _ensure_column(conn, "candidates", "routing_destination", "TEXT")
            _ensure_column(conn, "candidates", "subject_scope", "TEXT")
            _ensure_column(conn, "candidates", "subject_id", "TEXT")
            _ensure_column(conn, "candidate_events", "routing_destination", "TEXT")
            _ensure_column(conn, "candidate_events", "job_id", "TEXT")
            _ensure_column(conn, "candidate_events", "job_run_id", "TEXT")
            _ensure_column(conn, "candidate_events", "session_id", "TEXT")
            _ensure_column(conn, "candidate_events", "prompt_snapshot_id", "TEXT")
            _ensure_column(conn, "candidate_events", "routing_reason_codes", "TEXT")
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
            self._migrate_canonical_keys(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidate_events_candidate_id "
                "ON candidate_events(candidate_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidate_events_source_event_id "
                "ON candidate_events(source_event_id)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_canonical_key_unique "
                "ON candidates(canonical_key) WHERE canonical_key IS NOT NULL AND canonical_key != ''"
            )

    def _migrate_canonical_keys(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT id, canonical_text, canonical_key FROM candidates").fetchall()
        for row in rows:
            key = _clean_optional_text(row["canonical_key"]) or canonical_key_for_text(row["canonical_text"])
            conn.execute("UPDATE candidates SET canonical_key = ? WHERE id = ?", (key, row["id"]))

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
        return dict(row) if row is not None else None

    def get_candidate(self, canonical_text: str) -> Optional[dict[str, Any]]:
        key = canonical_key_for_text(canonical_text)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM candidates WHERE canonical_key = ? OR canonical_text = ? ORDER BY id LIMIT 1",
                (key, canonical_text.strip()),
            ).fetchone()
        return self._row_to_dict(row)

    def list_events(self, canonical_text: str) -> list[dict[str, Any]]:
        candidate = self.get_candidate(canonical_text)
        if not candidate:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM candidate_events WHERE candidate_id = ? ORDER BY id",
                (candidate["id"],),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_candidates(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM candidates ORDER BY updated_at DESC, id DESC").fetchall()
        return [dict(row) for row in rows]

    def query_candidates_for_pack(
        self,
        *,
        query_text: str | None = None,
        min_support_count: int = 0,
        max_items: int = 20,
    ) -> list[dict[str, Any]]:
        terms = {term for term in re.split(r"[^a-z0-9]+", (query_text or "").lower()) if len(term) >= 2}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM candidates
                WHERE status = 'active' AND support_count >= ?
                ORDER BY support_count DESC, updated_at DESC, id DESC
                """,
                (max(0, int(min_support_count)),),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            haystack = item.get("canonical_text", "").lower()
            if terms and not all(term in haystack for term in terms):
                continue
            results.append(item)
            if len(results) >= max_items:
                break
        return results

    def record_observation(
        self,
        *,
        observation_text: str,
        source_ref: str | None = None,
        source_event_id: str | None = None,
        kind: str | None = None,
        job_id: str | None = None,
        job_run_id: str | None = None,
        session_id: str | None = None,
        prompt_snapshot_id: str | None = None,
        tags: Any = None,
        metadata: Any = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        now = observed_at or _hermes_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO observations (
                    observation_text, kind, source_ref, source_event_id,
                    job_id, job_run_id, session_id, prompt_snapshot_id,
                    tags_json, metadata_json, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_text,
                    kind,
                    source_ref,
                    source_event_id,
                    job_id,
                    job_run_id,
                    session_id,
                    prompt_snapshot_id,
                    _json_string_list(tags),
                    json.dumps(metadata, sort_keys=True) if metadata is not None else None,
                    now,
                ),
            )
            row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            row = conn.execute("SELECT * FROM observations WHERE id = ?", (row_id,)).fetchone()
        return dict(row)

    def record_event(
        self,
        *,
        event_type: str,
        canonical_text: str,
        kind: str | None = None,
        proposed_target: str | None = None,
        status: str | None = None,
        source_ref: str | None = None,
        source_event_id: str | None = None,
        counts_for_recurrence: bool = True,
        notes: str | None = None,
        routing_destination: str | None = None,
        subject_scope: str | None = None,
        subject_id: str | None = None,
        job_id: str | None = None,
        job_run_id: str | None = None,
        session_id: str | None = None,
        prompt_snapshot_id: str | None = None,
        routing_reason_codes: Any = None,
        event_ts: str | None = None,
    ) -> dict[str, Any]:
        action = event_type.strip().lower()
        if action not in {"create", "strengthen", "contradict", "prune", "promote", "stale", "quarantine", "forced_exit_quarantine"}:
            raise ValueError(f"Unsupported Layer-2 event_type: {event_type}")
        text = canonical_text.strip()
        if not text:
            raise ValueError("canonical_text is required")

        key = canonical_key_for_text(text)
        now = event_ts or _hermes_now().isoformat()
        normalized_target = normalize_destination(proposed_target)
        normalized_destination = normalize_destination(routing_destination) or normalized_target
        counts = bool(counts_for_recurrence)
        support_delta = 1 if counts and action in {"create", "strengthen", "promote"} else 0
        contradict_delta = 1 if counts and action == "contradict" else 0
        event_status = {
            "prune": "pruned",
            "stale": "stale",
            "quarantine": "quarantine",
            "forced_exit_quarantine": "quarantine",
            "promote": "promoted",
        }.get(action)
        next_status = status or event_status

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM candidates WHERE canonical_key = ? OR canonical_text = ? ORDER BY id LIMIT 1",
                (key, text),
            ).fetchone()
            if row and source_event_id:
                duplicate = conn.execute(
                    "SELECT id FROM candidate_events WHERE candidate_id = ? AND source_event_id = ? LIMIT 1",
                    (row["id"], source_event_id),
                ).fetchone()
                if duplicate:
                    return {
                        "audit_label": "duplicate_ignored",
                        "candidate": dict(row),
                        "event": {"source_event_id": source_event_id, "counts_for_recurrence": False},
                    }

            if row is None:
                conn.execute(
                    """
                    INSERT INTO candidates (
                        canonical_text, canonical_key, kind, proposed_target, status,
                        support_count, contradict_count, created_at, updated_at,
                        routing_destination, subject_scope, subject_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        text,
                        key,
                        kind,
                        normalized_target,
                        next_status or "active",
                        support_delta,
                        contradict_delta,
                        now,
                        now,
                        normalized_destination,
                        subject_scope,
                        subject_id,
                    ),
                )
                row = conn.execute("SELECT * FROM candidates WHERE canonical_key = ?", (key,)).fetchone()
            else:
                conn.execute(
                    """
                    UPDATE candidates
                    SET kind = COALESCE(?, kind),
                        proposed_target = COALESCE(?, proposed_target),
                        status = COALESCE(?, status),
                        support_count = support_count + ?,
                        contradict_count = contradict_count + ?,
                        updated_at = ?,
                        routing_destination = COALESCE(?, routing_destination),
                        subject_scope = COALESCE(?, subject_scope),
                        subject_id = COALESCE(?, subject_id)
                    WHERE id = ?
                    """,
                    (
                        kind,
                        normalized_target,
                        next_status,
                        support_delta,
                        contradict_delta,
                        now,
                        normalized_destination,
                        subject_scope,
                        subject_id,
                        row["id"],
                    ),
                )
                row = conn.execute("SELECT * FROM candidates WHERE id = ?", (row["id"],)).fetchone()

            conn.execute(
                """
                INSERT INTO candidate_events (
                    candidate_id, event_type, event_ts, source_ref, source_event_id,
                    counts_for_recurrence, support_delta, contradict_delta, notes,
                    routing_destination, job_id, job_run_id, session_id,
                    prompt_snapshot_id, routing_reason_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    action,
                    now,
                    source_ref,
                    source_event_id,
                    1 if counts else 0,
                    support_delta,
                    contradict_delta,
                    notes,
                    normalized_destination,
                    job_id,
                    job_run_id,
                    session_id,
                    prompt_snapshot_id,
                    _json_string_list(routing_reason_codes),
                ),
            )
            event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        label = {
            "create": "candidate_created",
            "strengthen": "candidate_strengthened",
            "contradict": "candidate_contradicted",
            "prune": "candidate_pruned",
            "promote": "candidate_promoted",
            "stale": "candidate_marked_stale",
            "quarantine": "candidate_quarantined",
            "forced_exit_quarantine": "question_forced_exit_quarantined",
        }[action]
        return {
            "audit_label": label,
            "candidate": dict(row),
            "event": {
                "id": event_id,
                "event_type": action,
                "event_ts": now,
                "source_ref": source_ref,
                "source_event_id": source_event_id,
                "counts_for_recurrence": counts,
                "support_delta": support_delta,
                "contradict_delta": contradict_delta,
                "notes": notes,
            },
        }


def parse_layer2_payload(final_response: str) -> tuple[str, Optional[dict[str, Any]]]:
    text = final_response or ""
    match = _LAYER2_FENCE_RE.search(text)
    if not match:
        return text, None
    try:
        payload = json.loads(match.group("body").strip())
    except json.JSONDecodeError as exc:
        logger.warning("Ignoring invalid hermes-layer2 payload: %s", exc)
        return text, None
    if not isinstance(payload, dict):
        logger.warning("Ignoring hermes-layer2 payload that is not a JSON object")
        return text, None
    clean = (text[: match.start()] + text[match.end() :]).strip()
    return clean, payload


def job_allows_layer2(job: dict[str, Any]) -> bool:
    cfg = job.get("memory_pipeline")
    return isinstance(cfg, dict) and bool(cfg.get("enabled"))


def apply_layer2_payload(
    job: dict[str, Any],
    payload: Optional[dict[str, Any]],
    *,
    source_ref: str,
    store: Optional[Layer2Store] = None,
    job_id: Optional[str] = None,
    job_run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    prompt_snapshot_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    if not payload or not job_allows_layer2(job):
        return []

    validation = validate_layer2_payload(payload)
    issue_events = [{"audit_label": "validation_issue", "issue": asdict(issue)} for issue in validation.issues]
    if not validation.valid:
        return issue_events

    ledger = store or Layer2Store()
    resolved_job_id = _clean_optional_text(job_id) or _clean_optional_text(job.get("id"))
    resolved_job_run_id = _clean_optional_text(job_run_id)
    resolved_session_id = _clean_optional_text(session_id)
    audit_events: list[dict[str, Any]] = []

    observations = validation.payload.get("observations")
    if isinstance(observations, list):
        for index, item in enumerate(observations):
            if not isinstance(item, dict):
                continue
            text = str(item.get("observation_text") or item.get("content") or "").strip()
            if not text:
                continue
            stored = ledger.record_observation(
                observation_text=text,
                kind=_clean_optional_text(item.get("kind")),
                source_ref=_clean_optional_text(item.get("source_ref")) or source_ref,
                source_event_id=_clean_optional_text(item.get("source_event_id"))
                or f"{source_ref}:observation:{index}",
                job_id=resolved_job_id,
                job_run_id=resolved_job_run_id,
                session_id=resolved_session_id,
                prompt_snapshot_id=prompt_snapshot_id,
                tags=item.get("tags"),
                metadata=item.get("metadata"),
                observed_at=_clean_optional_text(item.get("observed_at")),
            )
            audit_events.append({"audit_label": "observation_stored", "observation": stored})

    events = validation.payload.get("candidate_events")
    if isinstance(events, list):
        for index, item in enumerate(events):
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or item.get("event_type") or "").strip().lower()
            text = str(item.get("canonical_text") or "").strip()
            if action not in {"create", "strengthen", "contradict", "prune"} or not text:
                continue
            applied = ledger.record_event(
                event_type=action,
                canonical_text=text,
                kind=_clean_optional_text(item.get("kind")),
                proposed_target=_clean_optional_text(item.get("proposed_target")),
                status=_clean_optional_text(item.get("status")),
                source_ref=_clean_optional_text(item.get("source_ref")) or source_ref,
                source_event_id=_clean_optional_text(item.get("source_event_id"))
                or f"{source_ref}:candidate:{index}",
                counts_for_recurrence=bool(item.get("counts_for_recurrence", True)),
                notes=_clean_optional_text(item.get("notes")),
                routing_destination=_clean_optional_text(item.get("routing_destination")),
                subject_scope=_clean_optional_text(item.get("subject_scope")),
                subject_id=_clean_optional_text(item.get("subject_id")),
                job_id=resolved_job_id,
                job_run_id=resolved_job_run_id,
                session_id=resolved_session_id,
                prompt_snapshot_id=prompt_snapshot_id,
                routing_reason_codes=item.get("routing_reason_codes"),
            )
            audit_events.append(applied)

    audit_events.extend(issue_events)
    return audit_events


def format_layer2_audit_section(audit_events: list[dict[str, Any]]) -> str:
    if not audit_events:
        return ""
    lines = ["## Layer-2 Audit", ""]
    for item in audit_events:
        label = item.get("audit_label", "layer2_event")
        if label == "observation_stored":
            observation = item.get("observation") or {}
            lines.append(f"- observation_stored: {observation.get('source_event_id') or '-'}")
            continue
        if label == "validation_issue":
            issue = item.get("issue") or {}
            lines.append(f"- validation_issue: {issue.get('code')}: {issue.get('message')}")
            continue
        candidate = item.get("candidate") or {}
        event = item.get("event") or {}
        lines.append(
            "- "
            f"{label}: [{candidate.get('status', 'unknown')}] "
            f"{candidate.get('proposed_target') or '-'} / {candidate.get('kind') or '-'} / "
            f"{candidate.get('canonical_text')!r} "
            f"(support={candidate.get('support_count', 0)}, "
            f"contradict={candidate.get('contradict_count', 0)}, "
            f"counts={bool(event.get('counts_for_recurrence', True))})"
        )
    return "\n".join(lines)
