from pathlib import Path
from types import SimpleNamespace


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

_MINIMAL_JPEG_640_360 = (
    b"\xff\xd8"
    b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xc0\x00\x11\x08\x01\x68\x02\x80\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    b"\xff\xd9"
)


def test_probe_local_png_reports_hash_mime_dimensions_and_freshness(tmp_path):
    from agent.visual.media_probe import probe_local_media

    image = tmp_path / "one.png"
    image.write_bytes(_ONE_PIXEL_PNG)

    meta = probe_local_media(image)

    assert meta.exists is True
    assert meta.local_path == str(image)
    assert meta.mime_type == "image/png"
    assert meta.width == 1
    assert meta.height == 1
    assert meta.bytes == len(_ONE_PIXEL_PNG)
    assert meta.sha256.startswith("sha256:")
    assert meta.is_stable is True
    assert meta.freshness_status == "fresh"


def test_probe_file_uri_resolves_to_local_path(tmp_path):
    from agent.visual.media_probe import probe_local_media

    image = tmp_path / "one.png"
    image.write_bytes(_ONE_PIXEL_PNG)

    meta = probe_local_media(Path(image).as_uri())

    assert meta.exists is True
    assert meta.local_path == str(image)
    assert meta.mime_type == "image/png"
    assert meta.freshness_status == "fresh"


def test_probe_local_mp4_reports_ffprobe_dimensions_duration(tmp_path, monkeypatch):
    from agent.visual import media_probe
    from agent.visual.media_probe import probe_local_media

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(
            stdout=(
                '{"streams": [{"codec_type": "video", "width": 1024, "height": 576}], '
                '"format": {"duration": "4.25"}}'
            )
        )

    monkeypatch.setattr(media_probe.subprocess, "run", fake_run)

    meta = probe_local_media(video)

    assert calls
    assert meta.exists is True
    assert meta.mime_type == "video/mp4"
    assert meta.width == 1024
    assert meta.height == 576
    assert meta.duration_seconds == 4.25
    assert meta.freshness_status == "fresh"


def test_probe_local_jpeg_reports_header_dimensions_without_pil(tmp_path, monkeypatch):
    from agent.visual import media_probe
    from agent.visual.media_probe import probe_local_media

    image = tmp_path / "photo.jpg"
    image.write_bytes(_MINIMAL_JPEG_640_360)

    monkeypatch.setattr(media_probe, "_pil_image_metadata", lambda path: (None, None, None))

    meta = probe_local_media(image)

    assert meta.exists is True
    assert meta.mime_type == "image/jpeg"
    assert meta.width == 640
    assert meta.height == 360


def test_probe_remote_url_without_cache_is_unknown_not_fresh():
    from agent.visual.media_probe import probe_media_reference

    meta = probe_media_reference("https://example.com/generated.png")

    assert meta.exists is False
    assert meta.local_path is None
    assert meta.source == "https://example.com/generated.png"
    assert meta.mime_type == "image/png"
    assert meta.sha256 is None
    assert meta.is_stable is False
    assert meta.freshness_status == "unknown"
