from __future__ import annotations


def _tiny_png(width: int = 2, height: int = 3) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def test_artifact_store_imports_local_file_and_records_metadata(tmp_path):
    from agent.visual.artifact_store import ArtifactStore

    source = tmp_path / "source.png"
    source.write_bytes(_tiny_png())

    store = ArtifactStore(root=tmp_path / "store")
    artifact = store.import_local_file(
        source,
        request_id="vrq_test",
        attempt_id="vat_test",
        kind="image",
    )

    assert artifact.artifact_id.startswith("var_")
    assert artifact.local_path is not None
    assert artifact.local_path != str(source)
    assert artifact.local_path.endswith(".png")
    assert artifact.content_hash.startswith("sha256:")
    assert artifact.mime_type == "image/png"
    assert artifact.width == 2
    assert artifact.height == 3
    assert artifact.is_stable is True
    assert artifact.freshness_status == "fresh"
    assert artifact.to_ledger_kwargs()["request_id"] == "vrq_test"


def test_artifact_store_marks_missing_source_unstable(tmp_path):
    from agent.visual.artifact_store import ArtifactStore

    store = ArtifactStore(root=tmp_path / "store")
    artifact = store.describe_reference(
        "/tmp/missing.png",
        request_id="vrq_test",
        attempt_id="vat_test",
        kind="image",
    )

    assert artifact.local_path == "/tmp/missing.png"
    assert artifact.is_stable is False
    assert artifact.freshness_status == "unknown"
    assert artifact.content_hash is None
