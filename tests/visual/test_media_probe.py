from __future__ import annotations

import base64


def _tiny_png(width: int = 2, height: int = 3) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def test_probe_png_dimensions(tmp_path):
    from agent.visual.media_probe import probe_local_media

    png = tmp_path / "tiny.png"
    png.write_bytes(_tiny_png())

    meta = probe_local_media(png)
    assert meta.exists is True
    assert meta.mime_type == "image/png"
    assert meta.width == 2
    assert meta.height == 3
    assert meta.bytes > 0
    assert meta.sha256.startswith("sha256:")
    assert meta.is_stable is True


def test_probe_missing_path_reports_unstable():
    from agent.visual.media_probe import probe_local_media

    meta = probe_local_media("/tmp/does-not-exist.png")
    assert meta.exists is False
    assert meta.is_stable is False
    assert meta.freshness_status == "unknown"


def test_probe_data_uri_png_dimensions():
    from agent.visual.media_probe import probe_local_media

    encoded = base64.b64encode(_tiny_png(width=720, height=1280)).decode("ascii")
    meta = probe_local_media(f"data:image/png;base64,{encoded}")

    assert meta.exists is True
    assert meta.mime_type == "image/png"
    assert meta.width == 720
    assert meta.height == 1280
    assert meta.sha256.startswith("sha256:")
