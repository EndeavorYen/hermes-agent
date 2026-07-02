import base64
import json
from pathlib import Path

import pytest


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_visual_package_normalise_attachments_materializes_data_uri(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    data_uri = "data:image/png;base64," + base64.b64encode(_ONE_PIXEL_PNG).decode("ascii")

    attachments = visual_package_tool._normalise_attachments([data_uri])

    assert len(attachments) == 1
    attachment = attachments[0]
    assert not attachment.startswith("data:image")
    assert attachment.startswith(str(tmp_path / "cache" / "visual-agent-attachments"))
    assert Path(attachment).read_bytes() == _ONE_PIXEL_PNG


@pytest.mark.asyncio
async def test_visual_package_generate_rejects_prompt_disclosure_without_generating(monkeypatch):
    from tools import visual_package_tool

    def fail_generate_image(**_kwargs):
        raise AssertionError("prompt disclosure must not generate an image")

    def fail_generate_video(**_kwargs):
        raise AssertionError("prompt disclosure must not generate a video")

    monkeypatch.setattr(visual_package_tool, "generate_image", fail_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fail_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請給我剛剛產圖用的 prompt"}
        )
    )

    assert payload["error"] == (
        "visual_package_generate is for image/video generation, not prompt disclosure"
    )
    assert payload["request_type"] == "visual_prompt_disclosure"


@pytest.mark.asyncio
async def test_visual_package_generate_returns_selected_image_and_video(monkeypatch, tmp_path):
    from tools import visual_package_tool

    image = tmp_path / "selected.png"
    video = tmp_path / "selected.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image-fixture",
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video-fixture",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段 6 秒影片：霧黑鋼筆放在白紙上。",
                "image_provider": "xai",
                "aspect_ratio": "16:9",
            }
        )
    )

    assert payload["success"] is True
    assert payload["images"] == [str(image)]
    assert payload["videos"] == [str(video)]
    assert payload["package_status"] == "success"
    assert image_calls[0]["_provider"] == "xai"
    assert image_calls[0]["aspect_ratio"] == "landscape"
    assert video_calls[0]["image_url"] == str(image)
    assert video_calls[0]["duration"] == 6
    selected_ids = payload["delivery_metadata"]["selected_visual_artifact_ids"]
    assert selected_ids == [
        payload["rankings"]["image"]["selected_artifact_id"],
        payload["rankings"]["video"]["selected_artifact_id"],
    ]


@pytest.mark.asyncio
async def test_visual_package_video_only_uses_single_source_without_delivering_images(
    monkeypatch,
    tmp_path,
):
    from tools import visual_package_tool

    first_source = tmp_path / "source-1.png"
    second_source = tmp_path / "source-2.png"
    video = tmp_path / "selected.mp4"
    first_source.write_bytes(_ONE_PIXEL_PNG + b"first")
    second_source.write_bytes(_ONE_PIXEL_PNG + b"second")
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        source = first_source if len(image_calls) == 1 else second_source
        return {
            "success": True,
            "image": str(source),
            "provider": "fixture",
            "model": "image-fixture",
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video-fixture",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產生一段 6 秒產品展示影片：霧黑鋼筆放在白紙上。",
                "include_image": False,
                "include_video": True,
                "candidate_budget": 2,
                "candidate_budget_source": "planner_default",
                "video_budget": 1,
            }
        )
    )

    assert len(image_calls) == 2
    assert "single still source frame" in image_calls[0]["prompt"]
    assert payload["success"] is True
    assert payload["images"] == []
    assert payload["videos"] == [str(video)]
    assert video_calls[0]["image_url"] == str(first_source)
    assert video_calls[0]["source_media"]["reference_count"] == 1
    assert video_calls[0]["source_media"]["references"] == [str(first_source)]
    assert payload["generation_strategy"]["image_first_for_video"] is True
    assert payload["generation_strategy"]["video_source_image"] == str(first_source)
    assert payload["generation_strategy"]["video_source_image_count"] == 1
    assert payload["generation_strategy"]["video_source_policy"] == "single_ranked_selected_image"
    assert payload["delivery_metadata"]["selected_visual_artifact_ids"] == [
        payload["rankings"]["video"]["selected_artifact_id"]
    ]


def test_visual_package_schema_and_registration_expose_agent_controls():
    from tools.registry import discover_builtin_tools, registry
    from tools.visual_package_tool import VISUAL_PACKAGE_SCHEMA

    discover_builtin_tools()

    properties = VISUAL_PACKAGE_SCHEMA["parameters"]["properties"]
    assert "include_image" in properties
    assert "include_video" in properties
    assert "storyboard" in properties
    assert "image_provider" in properties

    entry = registry.get_entry("visual_package_generate")
    assert entry is not None
    assert entry.toolset == "image_gen"
    assert entry.is_async is True
