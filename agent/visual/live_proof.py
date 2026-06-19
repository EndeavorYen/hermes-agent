"""Read-only acceptance checks for live Visual Agent Mode delivery proof."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class LiveProofArtifact:
    delivery_id: str
    request_id: str
    attempt_id: str
    artifact_id: str
    kind: str
    local_path: Optional[str]
    source_url: Optional[str]
    mime_type: Optional[str]
    delivered_at: Optional[str]


@dataclass(frozen=True)
class VisualAgentLiveProof:
    success: bool
    ledger_path: str
    since: Optional[str]
    platform: str
    destination_id: Optional[str]
    thread_id: Optional[str]
    missing: list[str]
    counts: dict[str, Any]
    artifacts: list[LiveProofArtifact]
    missing_artifact_delivery_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "ledger_path": self.ledger_path,
            "since": self.since,
            "platform": self.platform,
            "destination_id": self.destination_id,
            "thread_id": self.thread_id,
            "missing": list(self.missing),
            "counts": dict(self.counts),
            "artifacts": [asdict(artifact) for artifact in self.artifacts],
            "missing_artifact_delivery_ids": list(self.missing_artifact_delivery_ids),
        }


def verify_visual_agent_live_proof(
    ledger_path: str | Path,
    *,
    since: Optional[str] = None,
    platform: str = "slack",
    destination_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    require_image: bool = True,
    require_video: bool = True,
) -> VisualAgentLiveProof:
    """Verify that a live visual package was delivered after *since*.

    This verifier intentionally reads only delivery/artifact metadata. It does
    not inspect raw prompts or generated media contents.
    """
    path = Path(ledger_path).expanduser()
    platform_key = str(platform or "").strip().lower() or "slack"
    base_counts: dict[str, Any] = {
        "delivery_status_counts": {},
        "sent_delivery_count": 0,
        "joined_artifact_count": 0,
        "missing_artifact_join_count": 0,
        "artifact_kind_counts": {},
        "request_count": 0,
    }
    if not path.exists():
        return _result(
            False,
            path,
            since,
            platform_key,
            destination_id,
            thread_id,
            ["ledger_missing"],
            base_counts,
            [],
            [],
        )

    try:
        with _connect(path) as conn:
            if not _has_required_tables(conn):
                return _result(
                    False,
                    path,
                    since,
                    platform_key,
                    destination_id,
                    thread_id,
                    ["ledger_uninitialized"],
                    base_counts,
                    [],
                    [],
                )
            status_counts = _fetch_status_counts(
                conn,
                since=since,
                platform=platform_key,
                destination_id=destination_id,
                thread_id=thread_id,
            )
            rows = _fetch_sent_delivery_rows(
                conn,
                since=since,
                platform=platform_key,
                destination_id=destination_id,
                thread_id=thread_id,
            )
    except sqlite3.Error as exc:
        counts = dict(base_counts)
        counts["sqlite_error"] = str(exc)
        return _result(
            False,
            path,
            since,
            platform_key,
            destination_id,
            thread_id,
            ["ledger_read_error"],
            counts,
            [],
            [],
        )

    artifacts: list[LiveProofArtifact] = []
    missing_delivery_ids: list[str] = []
    kind_counts: dict[str, int] = {}
    request_ids: set[str] = set()
    for row in rows:
        request_ids.add(str(row["request_id"]))
        kind = row["kind"]
        if kind is None:
            missing_delivery_ids.append(str(row["delivery_id"]))
            continue
        normalized_kind = str(kind).strip().lower()
        kind_counts[normalized_kind] = kind_counts.get(normalized_kind, 0) + 1
        artifacts.append(
            LiveProofArtifact(
                delivery_id=str(row["delivery_id"]),
                request_id=str(row["request_id"]),
                attempt_id=str(row["attempt_id"]),
                artifact_id=str(row["artifact_id"]),
                kind=normalized_kind,
                local_path=row["local_path"],
                source_url=row["source_url"],
                mime_type=row["mime_type"],
                delivered_at=row["delivered_at"],
            )
        )

    counts = {
        "delivery_status_counts": status_counts,
        "sent_delivery_count": len(rows),
        "joined_artifact_count": len(artifacts),
        "missing_artifact_join_count": len(missing_delivery_ids),
        "artifact_kind_counts": kind_counts,
        "request_count": len(request_ids),
    }
    missing: list[str] = []
    if not rows:
        missing.append("no_sent_deliveries")
    else:
        if missing_delivery_ids:
            missing.append("missing_artifact_join")
        if require_image and kind_counts.get("image", 0) < 1:
            missing.append("missing_image_delivery")
        if require_video and kind_counts.get("video", 0) < 1:
            missing.append("missing_video_delivery")

    return _result(
        not missing,
        path,
        since,
        platform_key,
        destination_id,
        thread_id,
        missing,
        counts,
        artifacts,
        missing_delivery_ids,
    )


def _result(
    success: bool,
    path: Path,
    since: Optional[str],
    platform: str,
    destination_id: Optional[str],
    thread_id: Optional[str],
    missing: list[str],
    counts: dict[str, Any],
    artifacts: list[LiveProofArtifact],
    missing_delivery_ids: list[str],
) -> VisualAgentLiveProof:
    return VisualAgentLiveProof(
        success=success,
        ledger_path=str(path),
        since=since,
        platform=platform,
        destination_id=destination_id,
        thread_id=thread_id,
        missing=missing,
        counts=counts,
        artifacts=artifacts,
        missing_artifact_delivery_ids=missing_delivery_ids,
    )


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _has_required_tables(conn: sqlite3.Connection) -> bool:
    rows = conn.execute(
        """
        SELECT name
          FROM sqlite_master
         WHERE type = 'table'
           AND name IN ('visual_deliveries', 'visual_artifacts')
        """
    ).fetchall()
    return {str(row["name"]) for row in rows} == {
        "visual_deliveries",
        "visual_artifacts",
    }


def _fetch_status_counts(
    conn: sqlite3.Connection,
    *,
    since: Optional[str],
    platform: str,
    destination_id: Optional[str],
    thread_id: Optional[str],
) -> dict[str, int]:
    query = """
        SELECT delivery_status, COUNT(*) AS count
          FROM visual_deliveries
         WHERE lower(platform) = ?
    """
    params: list[Any] = [platform]
    query, params = _append_delivery_filters(
        query,
        params,
        since=since,
        destination_id=destination_id,
        thread_id=thread_id,
    )
    query += " GROUP BY delivery_status ORDER BY delivery_status"
    rows = conn.execute(query, tuple(params)).fetchall()
    return {str(row["delivery_status"]): int(row["count"]) for row in rows}


def _fetch_sent_delivery_rows(
    conn: sqlite3.Connection,
    *,
    since: Optional[str],
    platform: str,
    destination_id: Optional[str],
    thread_id: Optional[str],
) -> list[sqlite3.Row]:
    query = """
        SELECT d.delivery_id,
               d.request_id,
               d.attempt_id,
               d.artifact_id,
               d.delivered_at,
               a.kind,
               a.local_path,
               a.source_url,
               a.mime_type
          FROM visual_deliveries d
          LEFT JOIN visual_artifacts a ON a.artifact_id = d.artifact_id
         WHERE lower(d.platform) = ?
           AND d.delivery_status = 'sent'
    """
    params: list[Any] = [platform]
    query, params = _append_delivery_filters(
        query,
        params,
        since=since,
        destination_id=destination_id,
        thread_id=thread_id,
        table_alias="d",
    )
    query += " ORDER BY d.delivered_at DESC, d.delivery_id DESC"
    return conn.execute(query, tuple(params)).fetchall()


def _append_delivery_filters(
    query: str,
    params: list[Any],
    *,
    since: Optional[str],
    destination_id: Optional[str],
    thread_id: Optional[str],
    table_alias: Optional[str] = None,
) -> tuple[str, list[Any]]:
    prefix = f"{table_alias}." if table_alias else ""
    if destination_id:
        query += f" AND {prefix}destination_id = ?"
        params.append(destination_id)
    if thread_id:
        query += f" AND {prefix}thread_id = ?"
        params.append(thread_id)
    if since:
        query += f" AND {prefix}delivered_at >= ?"
        params.append(since)
    return query, params
