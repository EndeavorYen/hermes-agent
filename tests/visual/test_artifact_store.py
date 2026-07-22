from pathlib import Path


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_artifact_store_imports_local_file_under_request_directory(tmp_path):
    from agent.visual.artifact_store import ArtifactStore

    source = tmp_path / "source.png"
    source.write_bytes(_ONE_PIXEL_PNG)

    store = ArtifactStore(tmp_path / "artifacts")
    artifact = store.import_local_file(
        source,
        request_id="vrq_test",
        attempt_id="vat_test",
        kind="image",
        artifact_id="var_test",
    )

    assert artifact.artifact_id == "var_test"
    assert artifact.request_id == "vrq_test"
    assert artifact.attempt_id == "vat_test"
    assert artifact.local_path is not None
    assert "vrq_test" in artifact.local_path
    assert Path(artifact.local_path).read_bytes() == _ONE_PIXEL_PNG
    assert artifact.content_hash.startswith("sha256:")
    assert artifact.mime_type == "image/png"
    assert artifact.width == 1
    assert artifact.height == 1
    assert artifact.is_stable is True
    assert artifact.freshness_status == "fresh"


def test_artifact_store_imports_file_uri(tmp_path):
    from agent.visual.artifact_store import ArtifactStore

    source = tmp_path / "source.png"
    source.write_bytes(_ONE_PIXEL_PNG)

    store = ArtifactStore(tmp_path / "artifacts")
    artifact = store.import_local_file(
        source.as_uri(),
        request_id="vrq_test",
        attempt_id="vat_test",
        kind="image",
        artifact_id="var_test",
    )

    assert artifact.local_path is not None
    assert Path(artifact.local_path).exists()
    assert artifact.freshness_status == "fresh"
