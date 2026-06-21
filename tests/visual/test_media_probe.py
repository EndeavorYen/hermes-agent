from pathlib import Path


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
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
