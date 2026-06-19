"""Stable local storage for visual generation artifacts."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

from agent.visual.ids import new_artifact_id
from agent.visual.media_probe import probe_local_media


@dataclass(frozen=True)
class VisualArtifactRecord:
    artifact_id: str
    request_id: str
    attempt_id: str
    kind: str
    local_path: Optional[str] = None
    source_url: Optional[str] = None
    content_hash: Optional[str] = None
    perceptual_hash: Optional[str] = None
    mime_type: Optional[str] = None
    bytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_ms: Optional[int] = None
    frame_count: Optional[int] = None
    expires_at: Optional[str] = None
    is_stable: bool = False
    freshness_status: str = "unknown"

    def to_ledger_kwargs(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "request_id": self.request_id,
            "attempt_id": self.attempt_id,
            "kind": self.kind,
            "local_path": self.local_path,
            "source_url": self.source_url,
            "content_hash": self.content_hash,
            "perceptual_hash": self.perceptual_hash,
            "mime_type": self.mime_type,
            "bytes": self.bytes,
            "width": self.width,
            "height": self.height,
            "duration_ms": self.duration_ms,
            "frame_count": self.frame_count,
            "expires_at": self.expires_at,
            "is_stable": self.is_stable,
            "freshness_status": self.freshness_status,
        }


class ArtifactStore:
    """Copies generated artifacts into a stable runtime-private directory."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else _default_artifact_root()

    def import_local_file(
        self,
        source: str | Path,
        *,
        request_id: str,
        attempt_id: str,
        kind: str,
        artifact_id: Optional[str] = None,
    ) -> VisualArtifactRecord:
        aid = artifact_id or new_artifact_id()
        source_path = _local_path(source)
        if source_path is None or not source_path.is_file():
            return self.describe_reference(
                str(source),
                request_id=request_id,
                attempt_id=attempt_id,
                kind=kind,
                artifact_id=aid,
            )

        destination_dir = self.root / request_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        suffix = source_path.suffix or _suffix_for_kind(kind)
        destination = destination_dir / f"{attempt_id}_{aid}{suffix}"
        if source_path.resolve() != destination.resolve():
            shutil.copy2(source_path, destination)

        meta = probe_local_media(destination)
        return VisualArtifactRecord(
            artifact_id=aid,
            request_id=request_id,
            attempt_id=attempt_id,
            kind=kind,
            local_path=str(destination),
            content_hash=meta.sha256 or None,
            mime_type=meta.mime_type,
            bytes=meta.bytes,
            width=meta.width,
            height=meta.height,
            duration_ms=meta.duration_ms,
            frame_count=meta.frame_count,
            is_stable=meta.is_stable,
            freshness_status=meta.freshness_status,
        )

    def describe_reference(
        self,
        value: str | Path,
        *,
        request_id: str,
        attempt_id: str,
        kind: str,
        artifact_id: Optional[str] = None,
    ) -> VisualArtifactRecord:
        text = str(value)
        is_url = text.lower().startswith(("http://", "https://"))
        meta = probe_local_media(value)
        return VisualArtifactRecord(
            artifact_id=artifact_id or new_artifact_id(),
            request_id=request_id,
            attempt_id=attempt_id,
            kind=kind,
            local_path=None if is_url else text,
            source_url=text if is_url else None,
            content_hash=meta.sha256 or None,
            mime_type=meta.mime_type,
            bytes=meta.bytes if meta.exists else None,
            width=meta.width,
            height=meta.height,
            duration_ms=meta.duration_ms,
            frame_count=meta.frame_count,
            is_stable=meta.is_stable,
            freshness_status=meta.freshness_status,
        )


def _default_artifact_root() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "visual" / "artifacts"


def _local_path(value: str | Path) -> Optional[Path]:
    if isinstance(value, Path):
        return value.expanduser()
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower().startswith("file://"):
        parsed = urlparse(text)
        return Path(unquote(parsed.path)).expanduser()
    if text.lower().startswith(("http://", "https://", "data:")):
        return None
    return Path(text).expanduser()


def _suffix_for_kind(kind: str) -> str:
    return ".mp4" if kind == "video" else ".bin"
