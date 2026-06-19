"""Local media probing helpers for visual artifacts."""

from __future__ import annotations

import hashlib
import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class MediaProbeResult:
    path: str
    exists: bool
    mime_type: Optional[str] = None
    bytes: int = 0
    sha256: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    duration_ms: Optional[int] = None
    frame_count: Optional[int] = None
    is_stable: bool = False
    freshness_status: str = "unknown"


def probe_local_media(path: str | Path) -> MediaProbeResult:
    data_uri = _decode_data_uri(path)
    if data_uri is not None:
        mime, raw = data_uri
        width, height = _probe_image_dimensions(raw, Path("inline"))
        return MediaProbeResult(
            path=str(path),
            exists=True,
            mime_type=mime or _detect_mime(raw, Path("inline")),
            bytes=len(raw),
            sha256=f"sha256:{hashlib.sha256(raw).hexdigest()}",
            width=width,
            height=height,
            is_stable=True,
            freshness_status="fresh",
        )

    resolved = _local_path(path)
    if resolved is None or not resolved.is_file():
        return MediaProbeResult(
            path=str(path),
            exists=False,
            is_stable=False,
            freshness_status="unknown",
        )

    raw = resolved.read_bytes()
    width, height = _probe_image_dimensions(raw, resolved)
    mime = _detect_mime(raw, resolved)
    return MediaProbeResult(
        path=str(resolved),
        exists=True,
        mime_type=mime,
        bytes=len(raw),
        sha256=f"sha256:{hashlib.sha256(raw).hexdigest()}",
        width=width,
        height=height,
        is_stable=True,
        freshness_status="fresh",
    )


def _decode_data_uri(value: str | Path) -> Optional[tuple[Optional[str], bytes]]:
    if isinstance(value, Path):
        return None
    text = str(value or "").strip()
    if not text.lower().startswith("data:image/") or "," not in text:
        return None
    header, encoded = text.split(",", 1)
    if ";base64" not in header.lower():
        return None
    mime = header[5:].split(";", 1)[0].strip().lower() or None
    try:
        return mime, base64.b64decode(encoded)
    except Exception:
        return None


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


def _detect_mime(raw: bytes, path: Path) -> Optional[str]:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    guessed = mimetypes.guess_type(path.name)[0]
    return guessed


def _probe_image_dimensions(raw: bytes, path: Path) -> tuple[Optional[int], Optional[int]]:
    png = _png_dimensions(raw)
    if png:
        return png
    gif = _gif_dimensions(raw)
    if gif:
        return gif
    jpeg = _jpeg_dimensions(raw)
    if jpeg:
        return jpeg
    pillow = _pillow_dimensions(path)
    if pillow:
        return pillow
    return None, None


def _png_dimensions(raw: bytes) -> Optional[tuple[int, int]]:
    if len(raw) < 24 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if raw[12:16] != b"IHDR":
        return None
    width = int.from_bytes(raw[16:20], "big")
    height = int.from_bytes(raw[20:24], "big")
    if width > 0 and height > 0:
        return width, height
    return None


def _gif_dimensions(raw: bytes) -> Optional[tuple[int, int]]:
    if len(raw) < 10 or not raw.startswith((b"GIF87a", b"GIF89a")):
        return None
    width = int.from_bytes(raw[6:8], "little")
    height = int.from_bytes(raw[8:10], "little")
    if width > 0 and height > 0:
        return width, height
    return None


def _jpeg_dimensions(raw: bytes) -> Optional[tuple[int, int]]:
    if not raw.startswith(b"\xff\xd8"):
        return None
    index = 2
    while index + 9 < len(raw):
        if raw[index] != 0xFF:
            index += 1
            continue
        marker = raw[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(raw):
            return None
        segment_len = int.from_bytes(raw[index:index + 2], "big")
        if segment_len < 2 or index + segment_len > len(raw):
            return None
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if segment_len >= 7:
                height = int.from_bytes(raw[index + 3:index + 5], "big")
                width = int.from_bytes(raw[index + 5:index + 7], "big")
                if width > 0 and height > 0:
                    return width, height
        index += segment_len
    return None


def _pillow_dimensions(path: Path) -> Optional[tuple[int, int]]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        if width > 0 and height > 0:
            return int(width), int(height)
    except Exception:
        return None
    return None
