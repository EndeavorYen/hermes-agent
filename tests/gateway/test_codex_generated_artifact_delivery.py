from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.run import _deliver_generated_artifact_event


@pytest.mark.asyncio
async def test_generated_image_is_uploaded_to_platform(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    image_path = tmp_path / "generated_images" / "thread-1" / "generated.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png")
    adapter = SimpleNamespace(
        send_image_file=AsyncMock(return_value=SimpleNamespace(success=True))
    )

    delivered = await _deliver_generated_artifact_event(
        adapter,
        "C123",
        {
            "path": str(image_path),
            "media_type": "image/png",
            "artifact_index": 2,
            "target": 3,
        },
        {"thread_id": "123.456"},
    )

    assert delivered is True
    adapter.send_image_file.assert_awaited_once_with(
        chat_id="C123",
        image_path=str(image_path),
        caption="Image 2/3 completed",
        metadata={"thread_id": "123.456"},
    )


@pytest.mark.asyncio
async def test_missing_generated_image_is_not_uploaded(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    adapter = SimpleNamespace(send_image_file=AsyncMock())

    delivered = await _deliver_generated_artifact_event(
        adapter,
        "C123",
        {
            "path": str(tmp_path / "generated_images" / "missing.png"),
            "media_type": "image/png",
        },
        None,
    )

    assert delivered is False
    adapter.send_image_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_generated_artifact_outside_codex_root_is_rejected(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    outside = tmp_path / "private.png"
    outside.write_bytes(b"private")
    adapter = SimpleNamespace(send_image_file=AsyncMock())

    delivered = await _deliver_generated_artifact_event(
        adapter,
        "C123",
        {"path": str(outside), "media_type": "image/png"},
        None,
    )

    assert delivered is False
    adapter.send_image_file.assert_not_awaited()
