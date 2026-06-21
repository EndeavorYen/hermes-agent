from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class MediaProbeResult:
    source: str
    exists: bool
    local_path: str | None
    mime_type: str | None
    bytes: int | None
    sha256: str | None
    width: int | None
    height: int | None
    is_stable: bool
    freshness_status: str


def probe_media_reference(source: str | Path) -> MediaProbeResult:
    source_text = str(source)
    parsed = urlparse(source_text)
    if parsed.scheme in {"http", "https"}:
        return MediaProbeResult(
            source=source_text,
            exists=False,
            local_path=None,
            mime_type=_guess_mime(source_text),
            bytes=None,
            sha256=None,
            width=None,
            height=None,
            is_stable=False,
            freshness_status="unknown",
        )
    return probe_local_media(source)


def probe_local_media(source: str | Path) -> MediaProbeResult:
    source_text = str(source)
    path = _local_path_from_source(source)
    mime_type = _guess_mime(path.name)
    if not path.exists():
        return MediaProbeResult(
            source=source_text,
            exists=False,
            local_path=str(path),
            mime_type=mime_type,
            bytes=None,
            sha256=None,
            width=None,
            height=None,
            is_stable=False,
            freshness_status="missing",
        )

    raw = path.read_bytes()
    width, height, image_mime = _image_metadata(path)
    return MediaProbeResult(
        source=source_text,
        exists=True,
        local_path=str(path),
        mime_type=image_mime or mime_type or "application/octet-stream",
        bytes=len(raw),
        sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        width=width,
        height=height,
        is_stable=True,
        freshness_status="fresh",
    )


def _local_path_from_source(source: str | Path) -> Path:
    if isinstance(source, Path):
        return source
    parsed = urlparse(source)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    return Path(source)


def _guess_mime(name: str) -> str | None:
    guessed, _ = mimetypes.guess_type(name)
    return guessed


def _image_metadata(path: Path) -> tuple[int | None, int | None, str | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            mime_type = Image.MIME.get(image.format or "")
            return image.width, image.height, mime_type
    except Exception:
        return None, None, None
