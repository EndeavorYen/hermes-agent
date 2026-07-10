from __future__ import annotations

import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path

from agent.visual.ids import new_artifact_id
from agent.visual.media_probe import MediaProbeResult, probe_local_media


@dataclass(frozen=True)
class StoredArtifact:
    artifact_id: str
    request_id: str
    attempt_id: str | None
    kind: str
    local_path: str | None
    content_hash: str | None
    mime_type: str | None
    bytes: int | None
    width: int | None
    height: int | None
    is_stable: bool
    freshness_status: str


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def import_local_file(
        self,
        source: str | Path,
        *,
        request_id: str,
        attempt_id: str | None,
        kind: str,
        artifact_id: str | None = None,
    ) -> StoredArtifact:
        source_meta = probe_local_media(source)
        if not source_meta.exists or source_meta.local_path is None:
            raise FileNotFoundError(str(source))

        artifact_id = artifact_id or new_artifact_id()
        request_dir = self.root / request_id
        request_dir.mkdir(parents=True, exist_ok=True)

        source_path = Path(source_meta.local_path)
        target = request_dir / f"{artifact_id}{_suffix_for(source_path, source_meta)}"
        shutil.copy2(source_path, target)

        stored = probe_local_media(target)
        return StoredArtifact(
            artifact_id=artifact_id,
            request_id=request_id,
            attempt_id=attempt_id,
            kind=kind,
            local_path=stored.local_path,
            content_hash=stored.sha256,
            mime_type=stored.mime_type,
            bytes=stored.bytes,
            width=stored.width,
            height=stored.height,
            is_stable=stored.is_stable,
            freshness_status=stored.freshness_status,
        )


def _suffix_for(path: Path, meta: MediaProbeResult) -> str:
    if path.suffix:
        return path.suffix
    if meta.mime_type:
        return mimetypes.guess_extension(meta.mime_type) or ".bin"
    return ".bin"
