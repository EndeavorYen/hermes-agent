import json

import pytest


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_visual_package_generate_returns_selected_image_and_video(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image-fixture",
        },
    )
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video-fixture",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片和一段影片：霧黑鋼筆，柔和窗光。"}
        )
    )

    assert payload["success"] is True
    assert payload["images"] == [str(image)]
    assert payload["videos"] == [str(video)]
    assert payload["package_status"] == "success"
    assert payload["delivery_metadata"]["selected_visual_artifact_ids"]


@pytest.mark.asyncio
async def test_visual_package_generate_uses_selected_image_for_video(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    video_calls = []

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {"success": True, "image": str(image), "provider": "fixture", "model": "image-fixture"},
    )

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {"success": True, "video": str(video), "provider": "fixture", "model": "video-fixture"}

    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    await visual_package_tool._handle_visual_package_generate(
        {"prompt": "image plus short video of a matte black pen"}
    )

    assert video_calls[0]["image_url"] == str(image)


@pytest.mark.asyncio
async def test_visual_package_generate_selects_successful_remote_video_url(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {"success": True, "image": str(image), "provider": "fixture", "model": "image-fixture"},
    )
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {
            "success": True,
            "video": "https://vidgen.x.ai/xai-vidgen-bucket/current.mp4",
            "provider": "fixture",
            "model": "video-fixture",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片和一段影片：霧黑鋼筆。"}
        )
    )

    assert payload["success"] is True
    assert payload["videos"] == ["https://vidgen.x.ai/xai-vidgen-bucket/current.mp4"]
    assert len(payload["delivery_metadata"]["selected_visual_artifact_ids"]) == 2
