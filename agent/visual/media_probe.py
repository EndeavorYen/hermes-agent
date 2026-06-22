from __future__ import annotations

import hashlib
import json
import mimetypes
import subprocess
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
    duration_seconds: float | None
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
            duration_seconds=None,
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
            duration_seconds=None,
            is_stable=False,
            freshness_status="missing",
        )

    raw = path.read_bytes()
    width, height, image_mime = _image_metadata(path)
    video_width, video_height, duration_seconds = _video_metadata(path, image_mime or mime_type)
    return MediaProbeResult(
        source=source_text,
        exists=True,
        local_path=str(path),
        mime_type=image_mime or mime_type or "application/octet-stream",
        bytes=len(raw),
        sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        width=width or video_width,
        height=height or video_height,
        duration_seconds=duration_seconds,
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
    width, height, mime_type = _pil_image_metadata(path)
    if width and height:
        return width, height, mime_type
    return _image_header_metadata(path)


def _pil_image_metadata(path: Path) -> tuple[int | None, int | None, str | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            mime_type = Image.MIME.get(image.format or "")
            return image.width, image.height, mime_type
    except Exception:
        return None, None, None


def _image_header_metadata(path: Path) -> tuple[int | None, int | None, str | None]:
    try:
        header = path.read_bytes()[:32]
    except Exception:
        return None, None, None
    if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        return (width or None), (height or None), "image/png"
    if header.startswith(b"\xff\xd8"):
        return _jpeg_header_metadata(path)
    return None, None, None


def _jpeg_header_metadata(path: Path) -> tuple[int | None, int | None, str | None]:
    try:
        data = path.read_bytes()
    except Exception:
        return None, None, None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break
        segment_length = int.from_bytes(data[index:index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            break
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        } and segment_length >= 7:
            height = int.from_bytes(data[index + 3:index + 5], "big")
            width = int.from_bytes(data[index + 5:index + 7], "big")
            return (width or None), (height or None), "image/jpeg"
        index += segment_length
    return None, None, "image/jpeg"


def _video_metadata(path: Path, mime_type: str | None) -> tuple[int | None, int | None, float | None]:
    if not _looks_like_video(path, mime_type):
        return None, None, None
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        payload = json.loads(result.stdout or "{}")
    except Exception:
        return None, None, None

    stream = _first_video_stream(payload)
    width = _positive_int(stream.get("width")) if stream else None
    height = _positive_int(stream.get("height")) if stream else None
    duration = _positive_float(
        (payload.get("format") or {}).get("duration")
        if isinstance(payload.get("format"), dict)
        else None
    )
    if duration is None and stream:
        duration = _positive_float(stream.get("duration"))
    return width, height, duration


def _looks_like_video(path: Path, mime_type: str | None) -> bool:
    if isinstance(mime_type, str) and mime_type.startswith("video/"):
        return True
    return path.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv", ".avi", ".3gp"}


def _first_video_stream(payload: dict[str, object]) -> dict[str, object] | None:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return None
    for item in streams:
        if isinstance(item, dict) and item.get("codec_type") == "video":
            return item
    return None


def _positive_int(value: object) -> int | None:
    try:
        numeric = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _positive_float(value: object) -> float | None:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None
