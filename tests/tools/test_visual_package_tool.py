import base64
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

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
    quality_run = payload["delivery_metadata"]["visual_quality_run"]
    assert quality_run["requires_video"] is True
    assert quality_run["summary"]["case_count"] == 1
    assert quality_run["summary"]["failed_case_count"] == 0
    assert 0.0 <= quality_run["summary"]["min_quality_score"] < 1.0
    assert quality_run["summary"]["video_missing_after_image_count"] == 0
    assert quality_run["summary"]["image_first_video_source_failure_count"] == 0
    assert quality_run["self_review"]["image_first_video_source_covered"] is True
    assert "霧黑鋼筆" not in json.dumps(quality_run, ensure_ascii=False)
    assert payload["autonomous_validation"]["decision"] == "accept"
    assert payload["autonomous_validation"]["evidence"]["learning_trace_count"] >= 2
    assert payload["autonomous_orchestration"]["runtime_hook"] == "post_generation"
    assert payload["autonomous_orchestration"]["next_action"] == "accept_and_monitor"


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
async def test_visual_package_video_only_uses_single_ranked_source_without_delivering_images(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    first_source = tmp_path / "first-source.png"
    second_source = tmp_path / "second-source.png"
    video = tmp_path / "video.mp4"
    first_source.write_bytes(_ONE_PIXEL_PNG)
    second_source.write_bytes(_ONE_PIXEL_PNG + b"second")
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        image_path = first_source if len(image_calls) == 1 else second_source
        return {
            "success": True,
            "image": str(image_path),
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
                "prompt": "請產生一段產品展示影片：霧黑鋼筆放在白紙上，柔和窗光。",
                "candidate_budget": 2,
                "candidate_budget_source": "planner_default",
                "video_budget": 1,
            }
        )
    )

    assert len(image_calls) == 2
    assert payload["success"] is True
    assert payload["images"] == []
    assert payload["videos"] == [str(video)]
    selected_source = payload["generation_strategy"]["video_source_image"]
    assert selected_source in {str(first_source), str(second_source)}
    assert video_calls[0]["image_url"] == selected_source
    assert isinstance(video_calls[0]["image_url"], str)
    assert video_calls[0]["image_url"] not in {str([str(first_source), str(second_source)])}
    assert video_calls[0]["duration"] == 6
    assert payload["generation_strategy"]["video_source_artifact_id"]
    assert payload["delivery_metadata"]["selected_visual_artifact_ids"] == [
        payload["rankings"]["video"]["selected_artifact_id"]
    ]
    assert set(payload["delivery_metadata"]["visual_artifacts"]) >= {str(video)}
    assert {
        entry["artifact_id"]
        for entry in payload["delivery_metadata"]["visual_artifacts"].values()
    } == {payload["rankings"]["video"]["selected_artifact_id"]}
    assert payload["generation_payloads"]["image"][0]["image"] is None
    assert payload["generation_payloads"]["image"][1]["image"] is None


@pytest.mark.asyncio
async def test_visual_package_image_first_video_prompts_single_source_frame(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "source.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"video")
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image-fixture",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **_kwargs: {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video-fixture",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產生一段影片：一支霧黑鋼筆放在白紙上，柔和窗光。",
                "include_image": False,
                "include_video": True,
                "candidate_budget": 2,
                "candidate_budget_source": "planner_default",
            }
        )
    )

    assert payload["success"] is True
    assert image_calls
    image_prompt = image_calls[0]["prompt"]
    assert "single still source frame" in image_prompt
    assert "not a video storyboard" in image_prompt
    assert "Do not create a collage" in image_prompt
    assert "four-panel layout" in image_prompt


def test_visual_package_schema_exposes_agent_mode_controls():
    from tools.visual_package_tool import VISUAL_PACKAGE_SCHEMA

    properties = VISUAL_PACKAGE_SCHEMA["parameters"]["properties"]

    assert "include_image" in properties
    assert "include_video" in properties
    assert "storyboard" in properties
    assert "image_provider" in properties


def test_visual_package_reference_binding_does_not_default_ref_roles():
    from tools.visual_package_tool import _normalise_reference_binding

    binding = _normalise_reference_binding(
        {
            "mode": "ordered_references",
            "role_policy": "derive_from_user_prompt",
            "reference_order": [
                {"index": 1, "role_hint": "character_identity"},
                {"index": 2, "role_hint": "character_identity"},
                {"index": 3, "role_hint": "wardrobe"},
            ],
        },
        ["/tmp/person-a.png", "/tmp/person-b.png", "/tmp/clothes.png"],
    )

    assert binding is not None
    assert binding["mode"] == "ordered_references"
    assert binding["reference_order_source"] == "user_visible_upload_order"
    assert binding["role_policy"] == "derive_from_user_prompt"
    assert "character_reference" not in binding
    assert "pose_reference" not in binding
    assert "character_reference_index" not in binding
    assert "pose_reference_index" not in binding
    assert binding["reference_order"] == [
        {"index": 1, "role_hint": "character_identity", "attachment": "/tmp/person-a.png"},
        {"index": 2, "role_hint": "character_identity", "attachment": "/tmp/person-b.png"},
        {"index": 3, "role_hint": "wardrobe", "attachment": "/tmp/clothes.png"},
    ]


def test_visual_package_reference_binding_prompt_is_role_neutral():
    from tools.visual_package_tool import _apply_reference_binding_prompt

    prompt = _apply_reference_binding_prompt(
        "ref1 和 ref2 都是人物，ref3 是服裝，請融合成一張圖片",
        {
            "mode": "ordered_references",
            "reference_order_source": "user_visible_upload_order",
            "role_policy": "derive_from_user_prompt",
        },
    )

    assert "Reference binding" in prompt
    assert "Do not assume fixed roles" in prompt
    assert "clothing, wardrobe" in prompt
    assert "reference 1 only for character identity" not in prompt


def test_visual_package_reference_binding_prompt_lists_explicit_roles_without_paths():
    from tools.visual_package_tool import _apply_reference_binding_prompt

    prompt = _apply_reference_binding_prompt(
        "把 ref1 的角色套用 ref2 的姿勢",
        {
            "mode": "ordered_references",
            "reference_order_source": "user_visible_upload_order",
            "role_policy": "derive_from_user_prompt",
            "reference_order": [
                {
                    "index": 1,
                    "role_hint": "character_identity",
                    "attachment": "/tmp/character.png",
                },
                {
                    "index": 2,
                    "role_hint": "pose_composition",
                    "attachment": "/tmp/pose.png",
                },
            ],
        },
    )

    assert "ref 1 role: character_identity" in prompt
    assert "ref 2 role: pose_composition" in prompt
    assert "Do not transfer character identity from a pose/composition reference" in prompt
    assert "/tmp/character.png" not in prompt
    assert "/tmp/pose.png" not in prompt


def test_visual_package_pose_composition_guide_preserves_visible_structure(monkeypatch, tmp_path):
    from PIL import Image
    from PIL import ImageDraw
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    source = tmp_path / "pose.png"
    image = Image.new("RGB", (180, 320), (40, 160, 220))
    draw = ImageDraw.Draw(image)
    draw.rectangle((55, 45, 125, 240), fill=(240, 120, 40))
    draw.ellipse((65, 20, 115, 70), fill=(250, 220, 180))
    draw.line((90, 240, 40, 315), fill=(40, 30, 30), width=18)
    draw.line((95, 240, 150, 315), fill=(40, 30, 30), width=18)
    image.save(source)

    guide_path = visual_package_tool._pose_composition_guide_image(str(source))

    assert guide_path is not None
    guide = Image.open(guide_path).convert("RGB")
    pixels = list(guide.getdata())
    nonwhite_ratio = sum(1 for pixel in pixels if min(pixel) < 245) / len(pixels)
    assert nonwhite_ratio > 0.2
    assert min(min(pixel) for pixel in pixels) >= 170
    assert all(abs(r - g) <= 2 and abs(g - b) <= 2 for r, g, b in pixels[:: max(1, len(pixels) // 100)])


def test_visual_package_pose_composition_guide_avoids_contour_map_artifacts(monkeypatch, tmp_path):
    from PIL import Image
    from PIL import ImageDraw
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    source = tmp_path / "high-contrast-pose.png"
    image = Image.new("RGB", (180, 320), (248, 248, 248))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 210, 180, 320), fill=(120, 80, 60))
    draw.ellipse((62, 18, 118, 76), fill=(245, 215, 185))
    draw.polygon([(70, 80), (126, 74), (135, 220), (54, 230)], fill=(30, 30, 36))
    draw.line((78, 225, 35, 318), fill=(6, 6, 12), width=24)
    draw.line((104, 225, 160, 318), fill=(6, 6, 12), width=24)
    image.save(source)

    guide_path = visual_package_tool._pose_composition_guide_image(str(source))

    assert guide_path is not None
    guide = Image.open(guide_path).convert("L")
    pixels = list(guide.getdata())
    dark_ratio = sum(1 for pixel in pixels if pixel < 120) / len(pixels)
    deep_shadow_ratio = sum(1 for pixel in pixels if pixel < 170) / len(pixels)
    assert dark_ratio == 0
    assert deep_shadow_ratio == 0


def test_visual_package_pose_edge_guide_preserves_contours_without_color(monkeypatch, tmp_path):
    from PIL import Image
    from PIL import ImageDraw
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    source = tmp_path / "pose.png"
    image = Image.new("RGB", (180, 320), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((65, 20, 115, 70), fill=(250, 220, 180), outline=(30, 30, 30), width=4)
    draw.rectangle((55, 70, 125, 240), fill=(240, 120, 40), outline=(30, 30, 30), width=4)
    draw.line((90, 240, 40, 315), fill=(40, 30, 30), width=18)
    draw.line((95, 240, 150, 315), fill=(40, 30, 30), width=18)
    image.save(source)

    guide_path = visual_package_tool._pose_composition_edge_guide_image(str(source))

    assert guide_path is not None
    guide = Image.open(guide_path).convert("RGB")
    pixels = list(guide.getdata())
    dark_ratio = sum(1 for pixel in pixels if max(pixel) < 80) / len(pixels)
    white_ratio = sum(1 for pixel in pixels if min(pixel) > 245) / len(pixels)
    assert 0.01 < dark_ratio < 0.35
    assert white_ratio > 0.45
    assert all(abs(r - g) <= 2 and abs(g - b) <= 2 for r, g, b in pixels[:: max(1, len(pixels) // 100)])


def test_visual_package_pose_edge_guide_suppresses_interior_texture(monkeypatch, tmp_path):
    from PIL import Image
    from PIL import ImageDraw
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    source = tmp_path / "textured-pose.png"
    image = Image.new("RGB", (180, 320), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 60, 130, 245), fill=(180, 180, 180), outline=(20, 20, 20), width=5)
    for y in range(70, 235, 4):
        draw.line((55, y, 125, y), fill=(30, 30, 30), width=1)
    draw.line((90, 245, 35, 315), fill=(20, 20, 20), width=16)
    draw.line((95, 245, 155, 315), fill=(20, 20, 20), width=16)
    image.save(source)

    guide_path = visual_package_tool._pose_composition_edge_guide_image(str(source))

    assert guide_path is not None
    guide = Image.open(guide_path).convert("L")
    inner = guide.crop((65, 90, 115, 215))
    inner_pixels = list(inner.getdata())
    inner_dark_ratio = sum(1 for pixel in inner_pixels if pixel < 80) / len(inner_pixels)
    assert inner_dark_ratio < 0.18


@pytest.mark.asyncio
async def test_visual_package_uses_pose_guide_without_raw_pose_reference(monkeypatch, tmp_path):
    from PIL import Image
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ref1 = tmp_path / "character.png"
    ref2 = tmp_path / "pose.png"
    image = tmp_path / "image.png"
    Image.new("RGB", (160, 240), (240, 240, 255)).save(ref1)
    Image.new("RGB", (180, 320), (60, 120, 180)).save(ref2)
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
            "vision_observation": {
                "reference_adherence": 0.92,
                "character_identity_adherence": 0.92,
                "pose_composition_adherence": 0.9,
                "wardrobe_adherence": 0.9,
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
                "include_video": False,
                "candidate_budget": 1,
                "reference_conditioning_policy": "structure_guide",
                "attachments": [str(ref1), str(ref2)],
                "reference_binding": {
                    "reference_order": [
                        {"index": 1, "role_hint": "character_identity"},
                        {"index": 2, "role_hint": "pose_composition"},
                    ]
                },
            }
        )
    )

    provider_refs = image_calls[0]["reference_image_urls"]
    assert provider_refs[0] == str(ref1)
    assert provider_refs[1] != str(ref2)
    assert len(provider_refs) == 2
    assert str(ref2) not in provider_refs
    assert "reference_role_guides" in provider_refs[1]
    assert Path(provider_refs[1]).is_file()
    assert "provider image 2 is a derived pose/composition guide from user ref 2" in image_calls[0]["prompt"]
    assert "derived pose/contour guide" not in image_calls[0]["prompt"]
    assert "original pose reference is intentionally not sent" in image_calls[0]["prompt"]
    assert payload["success"] is True
    assert payload["generation_strategy"]["reference_conditioning"]["provider_reference_images"] == [
        {"provider_index": 1, "index": 1, "role_hint": "character_identity", "conditioning": "original"},
        {
            "provider_index": 2,
            "index": 2,
            "role_hint": "pose_composition",
            "conditioning": "pose_composition_guide",
            "derived_from_index": 2,
            "original_policy": "omitted_to_prevent_identity_drift",
        },
    ]


def test_visual_package_diversifies_reference_conditioning_for_identity_pose_conflict(monkeypatch, tmp_path):
    from PIL import Image
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ref1 = tmp_path / "character.png"
    ref2 = tmp_path / "pose.png"
    Image.new("RGB", (160, 240), (240, 240, 255)).save(ref1)
    Image.new("RGB", (180, 320), (60, 120, 180)).save(ref2)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_path = tmp_path / f"image-{len(image_calls)}.png"
        image_path.write_bytes(_ONE_PIXEL_PNG)
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image_path),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
            "vision_observation": {
                "reference_adherence": 0.92,
                "character_identity_adherence": 0.92,
                "pose_composition_adherence": 0.9,
                "wardrobe_adherence": 0.9,
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        asyncio.run(
            visual_package_tool._handle_visual_package_generate(
                {
                    "prompt": "把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
                    "include_video": False,
                    "candidate_budget": 2,
                    "attachments": [str(ref1), str(ref2)],
                    "reference_binding": {
                        "reference_order": [
                            {"index": 1, "role_hint": "character_identity"},
                            {"index": 2, "role_hint": "pose_composition"},
                        ]
                    },
                }
            )
        )
    )

    assert payload["success"] is True
    assert len(image_calls) == 2
    assert image_calls[0]["reference_image_urls"] == [str(ref1), str(ref2)]
    assert "role-locked original pose/composition reference" in image_calls[0]["prompt"]
    assert image_calls[1]["reference_image_urls"][0] == str(ref1)
    assert str(ref2) not in image_calls[1]["reference_image_urls"]
    assert "derived pose/composition guide" in image_calls[1]["prompt"]
    assert "pose/contour guide" not in image_calls[1]["prompt"]
    assert payload["generation_strategy"]["reference_conditioning_variants"] == [
        "role_locked_originals",
        "structure_guide",
    ]


@pytest.mark.asyncio
async def test_visual_package_defaults_image_aspect_to_pose_reference(monkeypatch, tmp_path):
    from PIL import Image
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ref1 = tmp_path / "character.png"
    ref2 = tmp_path / "pose.png"
    image = tmp_path / "image.png"
    Image.new("RGB", (240, 240), (240, 240, 255)).save(ref1)
    Image.new("RGB", (720, 1280), (60, 120, 180)).save(ref2)
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
            "vision_observation": {
                "reference_adherence": 0.92,
                "character_identity_adherence": 0.92,
                "pose_composition_adherence": 0.9,
                "wardrobe_adherence": 0.9,
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
                "include_video": False,
                "candidate_budget": 1,
                "attachments": [str(ref1), str(ref2)],
                "reference_binding": {
                    "reference_order": [
                        {"index": 1, "role_hint": "character_identity"},
                        {"index": 2, "role_hint": "pose_composition"},
                    ]
                },
            }
        )
    )

    assert payload["success"] is True
    assert image_calls[0]["aspect_ratio"] == "portrait"
    assert payload["generation_strategy"]["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_visual_package_replaces_raw_pose_reference_when_user_references_fill_provider_slots(monkeypatch, tmp_path):
    from PIL import Image
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ref1 = tmp_path / "character.png"
    ref2 = tmp_path / "pose.png"
    ref3 = tmp_path / "wardrobe.png"
    image = tmp_path / "image.png"
    for ref in (ref1, ref2, ref3):
        Image.new("RGB", (180, 320), (60, 120, 180)).save(ref)
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
            "vision_observation": {
                "reference_adherence": 0.92,
                "character_identity_adherence": 0.92,
                "pose_composition_adherence": 0.9,
                "wardrobe_adherence": 0.9,
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "ref1 是角色，ref2 是姿勢，ref3 是服裝",
                "include_video": False,
                "candidate_budget": 1,
                "reference_conditioning_policy": "structure_guide",
                "attachments": [str(ref1), str(ref2), str(ref3)],
                "reference_binding": {
                    "reference_order": [
                        {"index": 1, "role_hint": "character_identity"},
                        {"index": 2, "role_hint": "pose_composition"},
                        {"index": 3, "role_hint": "wardrobe"},
                    ]
                },
            }
        )
    )

    assert payload["success"] is True
    provider_refs = image_calls[0]["reference_image_urls"]
    assert provider_refs[0] == str(ref1)
    assert provider_refs[1] != str(ref2)
    assert provider_refs[2] == str(ref3)
    assert str(ref2) not in provider_refs
    assert "provider image 3 = user ref 3" in image_calls[0]["prompt"]
    assert "provider image 2 is a derived pose/composition guide from user ref 2" in image_calls[0]["prompt"]
    assert "pose/contour guide" not in image_calls[0]["prompt"]


@pytest.mark.asyncio
async def test_visual_package_pose_guides_share_provider_slot_budget_across_multiple_pose_refs(monkeypatch, tmp_path):
    from PIL import Image
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    pose1 = tmp_path / "pose-one.png"
    pose2 = tmp_path / "pose-two.png"
    image = tmp_path / "image.png"
    Image.new("RGB", (180, 320), (60, 120, 180)).save(pose1)
    Image.new("RGB", (200, 320), (90, 80, 150)).save(pose2)
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
            "vision_observation": {
                "reference_adherence": 0.92,
                "character_identity_adherence": 0.92,
                "pose_composition_adherence": 0.9,
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請融合 ref1 和 ref2 的姿勢構圖，產出一張新圖片",
                "include_video": False,
                "candidate_budget": 1,
                "reference_conditioning_policy": "structure_contour",
                "attachments": [str(pose1), str(pose2)],
                "reference_binding": {
                    "reference_order": [
                        {"index": 1, "role_hint": "pose_composition"},
                        {"index": 2, "role_hint": "pose_composition"},
                    ]
                },
            }
        )
    )

    provider_refs = image_calls[0]["reference_image_urls"]
    assert payload["success"] is True
    assert len(provider_refs) == 3
    assert str(pose1) not in provider_refs
    assert str(pose2) not in provider_refs
    conditionings = [
        item["conditioning"]
        for item in payload["generation_strategy"]["reference_conditioning"]["provider_reference_images"]
    ]
    assert conditionings == [
        "pose_composition_guide",
        "pose_composition_guide",
        "pose_composition_edge_guide",
    ]


@pytest.mark.asyncio
async def test_visual_package_records_references_omitted_by_provider_slot_budget(monkeypatch, tmp_path):
    from PIL import Image
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    refs = [tmp_path / f"ref-{index}.png" for index in range(1, 5)]
    image = tmp_path / "image.png"
    for index, ref in enumerate(refs, start=1):
        Image.new("RGB", (180, 320), (40 * index, 60, 180)).save(ref)
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
            "vision_observation": {
                "reference_adherence": 0.92,
                "character_identity_adherence": 0.92,
                "pose_composition_adherence": 0.9,
                "wardrobe_adherence": 0.9,
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "ref1 是角色，ref2 是姿勢，ref3 是服裝，ref4 是風格",
                "include_video": False,
                "candidate_budget": 1,
                "attachments": [str(ref) for ref in refs],
                "reference_binding": {
                    "reference_order": [
                        {"index": 1, "role_hint": "character_identity"},
                        {"index": 2, "role_hint": "pose_composition"},
                        {"index": 3, "role_hint": "wardrobe"},
                        {"index": 4, "role_hint": "style_reference"},
                    ]
                },
            }
        )
    )

    assert len(image_calls[0]["reference_image_urls"]) == 3
    conditioning = payload["generation_strategy"]["reference_conditioning"]
    assert conditioning["omitted_provider_references"] == [
        {"index": 4, "role_hint": "style_reference", "reason": "provider_reference_slot_budget"}
    ]


def test_visual_package_internal_image_generation_disables_image_agent_route(monkeypatch):
    from tools import image_generation_tool
    from tools import visual_package_tool

    captured = {}

    def fake_handle_image_generate(args, **_kwargs):
        captured.update(args)
        return json.dumps(
            {
                "success": True,
                "image": "/tmp/internal.png",
                "provider": "fixture",
                "model": "fixture-image",
            }
        )

    monkeypatch.setattr(image_generation_tool, "_handle_image_generate", fake_handle_image_generate)

    payload = visual_package_tool.generate_image(prompt="請用 visual agent mode 產出一張圖片")

    assert payload["success"] is True
    assert captured["_disable_visual_agent_route"] is True
    assert captured["_disable_visual_tracking"] is True


@pytest.mark.asyncio
async def test_visual_package_forwards_explicit_image_provider_override(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    reference = tmp_path / "reference.png"
    image = tmp_path / "image.png"
    reference.write_bytes(_ONE_PIXEL_PNG)
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請用 Grok 依照 reference 產出一張圖片",
                "attachments": [str(reference)],
                "image_provider": "xai",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert image_calls[0]["_provider"] == "xai"
    assert image_calls[0]["reference_image_urls"] == [str(reference)]


@pytest.mark.asyncio
async def test_visual_package_records_image_provider_source_in_generation_strategy(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)

    def fake_generate_image(**kwargs):
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "幫我產出一張圖片",
                "image_provider": "xai",
                "image_provider_source": "visual_agent_default",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert payload["generation_strategy"]["image_provider"] == "xai"
    assert payload["generation_strategy"]["image_provider_source"] == "visual_agent_default"


def test_visual_package_records_reference_inputs_in_attempt_ledger(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)

    def fake_generate_image(**kwargs):
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        asyncio.run(
            visual_package_tool._handle_visual_package_generate(
                {
                    "prompt": "把 ref1 的角色套用 ref2 的姿勢，產出圖片",
                    "attachments": ["/tmp/character.png", "/tmp/pose.png"],
                    "reference_binding": {
                        "mode": "ordered_references",
                        "reference_order_source": "user_visible_upload_order",
                        "role_policy": "derive_from_user_prompt",
                        "reference_order": [
                            {"index": 1, "role_hint": "character_identity"},
                            {"index": 2, "role_hint": "pose_composition"},
                        ],
                    },
                    "include_image": True,
                    "include_video": False,
                    "inline_vision_judge": False,
                    "candidate_budget": 1,
                },
            )
        )
    )

    assert payload["success"] is False
    assert payload["error_type"] == "delivery_gate_blocked"
    assert payload["delivery_gate"]["image"]["reason"] == "active_learning_review_required"
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    attempts = ledger._list("visual_attempts")
    assert len(attempts) >= 1
    attempt = sorted(attempts, key=lambda item: item["candidate_index"])[0]
    assert attempt["input_artifacts_json"] == [
        {
            "index": 1,
            "role_hint": "character_identity",
            "uri": "/tmp/character.png",
            "source": "user_visible_upload_order",
        },
        {
            "index": 2,
            "role_hint": "pose_composition",
            "uri": "/tmp/pose.png",
            "source": "user_visible_upload_order",
        },
    ]
    parameters = attempt.get("parameters_requested_json") or attempt.get("parameters_requested")
    assert parameters["reference_image_count"] == 2
    assert parameters["reference_binding"]["reference_order"][0]["role_hint"] == (
        "character_identity"
    )
    assert ledger.get_request(payload["visual_request_id"])["status"] == "failed"


@pytest.mark.asyncio
async def test_visual_package_infers_grok_provider_from_prompt(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請改用 Grok Imagine 產圖看看",
                "include_image": True,
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert image_calls[0]["_provider"] == "xai"
    assert payload["generation_strategy"]["image_provider"] == "xai"


@pytest.mark.asyncio
async def test_visual_package_followup_reuses_session_visual_references(monkeypatch, tmp_path):
    from gateway.session_context import (
        reset_visual_reference_context,
        set_visual_reference_context,
    )
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    ref_token = set_visual_reference_context(["/tmp/previous-selected.png", "/tmp/original-ref.png"])
    try:
        payload = json.loads(
            await visual_package_tool._handle_visual_package_generate(
                {
                    "prompt": "把上一張改成夜景，角色外貌保持一致",
                    "include_image": True,
                    "include_video": False,
                    "candidate_budget": 1,
                }
            )
        )
    finally:
        reset_visual_reference_context(ref_token)

    assert payload["success"] is True
    assert image_calls[0]["reference_image_urls"] == [
        "/tmp/previous-selected.png",
        "/tmp/original-ref.png",
    ]
    assert payload["generation_strategy"]["image_reference_source"] == "session_visual_context"


def test_visual_package_routes_controlled_grok_web_provider_when_enabled(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    image = tmp_path / "grok-web.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "grok-web-imagine",
            "model": "grok-web-imagine",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        asyncio.run(
            visual_package_tool._handle_visual_package_generate(
                {
                    "prompt": "請用 Grok Web Imagine 產出更精緻的圖片",
                    "include_image": True,
                    "include_video": False,
                    "candidate_budget": 1,
                    "image_provider": "grok-web-imagine",
                    "image_provider_source": "prompt_override",
                    "visual_agent_handoff_mode": "pre_llm_direct",
                }
            )
        )
    )

    assert payload["success"] is True
    assert image_calls[0]["_provider"] == "grok-web-imagine"
    assert payload["generation_strategy"]["image_provider"] == "grok-web-imagine"
    assert payload["generation_strategy"]["grok_web_imagine_policy"] == {
        "enabled": True,
        "mode": "controlled_visual_agent_provider",
        "source": "prompt_override",
        "handoff_mode": "pre_llm_direct",
    }


def test_visual_package_grok_web_polish_pass_edits_selected_candidate(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    source = tmp_path / "source.png"
    polished = tmp_path / "polished.png"
    source.write_bytes(_ONE_PIXEL_PNG)
    polished.write_bytes(_ONE_PIXEL_PNG + b"polished")
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        if len(image_calls) == 1:
            return {
                "success": True,
                "image": str(source),
                "provider": "xai",
                "model": "grok-imagine-image-quality",
                "vision_observation": {
                    "reference_adherence": 0.72,
                    "subject_quality": 0.72,
                    "face_quality": 0.72,
                    "visual_appeal": 0.72,
                    "composition": 0.72,
                },
            }
        return {
            "success": True,
            "image": str(polished),
            "provider": "grok-web-imagine",
            "model": "grok-web-imagine",
            "vision_observation": {
                "reference_adherence": 0.95,
                "subject_quality": 0.95,
                "face_quality": 0.95,
                "visual_appeal": 0.95,
                "composition": 0.95,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        asyncio.run(
            visual_package_tool._handle_visual_package_generate(
                {
                    "prompt": "請產出精緻角色圖片",
                    "include_image": True,
                    "include_video": False,
                    "candidate_budget": 1,
                    "image_provider": "xai",
                    "polish_provider": "grok-web-imagine",
                }
            )
        )
    )

    assert payload["success"] is True
    assert len(image_calls) == 2
    assert image_calls[0]["_provider"] == "xai"
    assert image_calls[1]["_provider"] == "grok-web-imagine"
    assert image_calls[1]["image_url"] == str(source)
    assert image_calls[1]["reference_image_urls"] is None
    assert "polish" in image_calls[1]["prompt"].lower()
    assert payload["images"] == [str(polished)]
    assert payload["generation_strategy"]["polish_pass"] == {
        "enabled": True,
        "provider": "grok-web-imagine",
        "selected_source_image": str(source),
        "status": "completed",
    }


def test_visual_package_followup_uses_previous_selected_image_as_edit_anchor(monkeypatch, tmp_path):
    from gateway.session_context import (
        reset_visual_reference_context,
        set_visual_reference_context,
    )
    from PIL import Image
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    anchor = tmp_path / "previous-selected.png"
    character = tmp_path / "character.png"
    pose = tmp_path / "pose.png"
    output = tmp_path / "edited.png"
    Image.new("RGB", (768, 1344), (230, 230, 245)).save(anchor)
    Image.new("RGB", (768, 1344), (245, 245, 255)).save(character)
    Image.new("RGB", (768, 1344), (220, 210, 200)).save(pose)
    output.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(output),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
            "vision_observation": {
                "reference_adherence": 0.92,
                "character_identity_adherence": 0.92,
                "pose_composition_adherence": 0.9,
                "wardrobe_adherence": 0.9,
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    ref_token = set_visual_reference_context(
        [
            {
                "uri": str(anchor),
                "role_hint": "edit_anchor",
                "source": "previous_selected_artifact",
            },
            {
                "uri": str(character),
                "role_hint": "character_identity",
                "source": "previous_tool_reference",
                "user_ref_index": 1,
            },
            {
                "uri": str(pose),
                "role_hint": "pose_composition",
                "source": "previous_tool_reference",
                "user_ref_index": 2,
            },
        ]
    )
    try:
        payload = json.loads(
            asyncio.run(
                visual_package_tool._handle_visual_package_generate(
                    {
                        "prompt": "很好，但足底應該也包含連身衣，而不是露出來的裸足，請改進",
                        "include_image": True,
                        "include_video": False,
                        "candidate_budget": 1,
                    }
                )
            )
        )
    finally:
        reset_visual_reference_context(ref_token)

    assert payload["success"] is True
    assert image_calls[0]["reference_image_urls"] == [str(anchor), str(character), str(pose)]
    assert image_calls[0]["aspect_ratio"] == "portrait"
    prompt = image_calls[0]["prompt"]
    assert "previous selected output" in prompt
    assert "edit anchor" in prompt
    assert "user ref 1 role: character_identity" in prompt
    assert "user ref 2 role: pose_composition" in prompt
    assert "change only the requested details" in prompt
    assert payload["generation_strategy"]["image_reference_source"] == "session_visual_context"
    assert payload["generation_strategy"]["reference_binding"]["reference_order"][0] == {
        "index": 1,
        "role_hint": "edit_anchor",
        "user_ref_index": "previous_selected_output",
    }


@pytest.mark.asyncio
async def test_visual_package_product_video_ignores_portrait_only_vision_defects(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "product.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    video_calls = []

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        },
    )

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(video),
            "provider": "xai",
            "model": "grok-imagine-video",
        }

    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)
    monkeypatch.setattr(
        visual_package_tool,
        "analyze_candidate_with_vision_tool",
        lambda _candidate: {
            "reference_adherence": 0.2,
            "face_quality": 0.2,
            "visual_appeal": 0.85,
            "composition": 0.85,
            "stocking_quality": 0.2,
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：一支霧黑鋼筆放在白紙上，柔和窗光，乾淨產品攝影。",
                "candidate_budget": 1,
                "video_budget": 1,
                "inline_vision_judge": True,
            }
        )
    )

    assert payload["success"] is True
    assert payload["images"] == [str(image)]
    assert payload["videos"] == [str(video)]
    assert video_calls[0]["image_url"] == str(image)
    assert payload["delivery_gate"]["image"]["allowed"] is True
    assert payload["delivery_gate"]["image"]["quality_issues"] == []


@pytest.mark.asyncio
async def test_visual_package_blocks_low_quality_video_delivery(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "source.png"
    video = tmp_path / "stretched-video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")

    def fake_probe_media_reference(ref):
        is_video = str(ref).endswith(".mp4")
        return SimpleNamespace(
            sha256=f"hash:{ref}",
            is_stable=True,
            freshness_status="fresh",
            local_path=str(ref),
            mime_type="video/mp4" if is_video else "image/png",
            bytes=10,
            width=1920 if is_video else 768,
            height=1080 if is_video else 768,
            duration_seconds=4.0 if is_video else None,
        )

    monkeypatch.setattr(visual_package_tool, "probe_media_reference", fake_probe_media_reference)
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
            "vision_observation": {
                "aspect_integrity": 0.2,
                "motion_quality": 0.25,
                "artifact_defects": ["weak_aspect_integrity", "weak_motion_or_duration_evidence"],
            },
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：乾淨產品攝影。",
                "aspect_ratio": "1:1",
                "candidate_budget": 1,
                "video_budget": 1,
            }
        )
    )

    assert payload["success"] is False
    assert payload["package_status"] == "partial"
    assert payload["images"] == [str(image)]
    assert payload["videos"] == []
    assert payload["error_type"] == "delivery_gate_blocked"
    assert payload["delivery_gate"]["video"]["allowed"] is False
    assert payload["delivery_gate"]["video"]["reason"] == "video_quality_issue_blocked"
    assert payload["delivery_gate"]["video"]["quality_issues"] == [
        "aspect_integrity_bad",
        "motion_bad",
    ]
    assert payload["delivery_metadata"]["selected_visual_artifact_ids"] == [
        payload["generation_strategy"]["video_source_artifact_id"]
    ]


@pytest.mark.asyncio
async def test_visual_package_repairs_blocked_video_before_delivery(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "source.png"
    bad_video = tmp_path / "bad-video.mp4"
    good_video = tmp_path / "good-video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    bad_video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    good_video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomgood")
    video_calls = []

    def fake_probe_media_reference(ref):
        is_video = str(ref).endswith(".mp4")
        return SimpleNamespace(
            sha256=f"hash:{ref}",
            is_stable=True,
            freshness_status="fresh",
            local_path=str(ref),
            mime_type="video/mp4" if is_video else "image/png",
            bytes=10,
            width=768,
            height=768,
            duration_seconds=4.0 if is_video else None,
        )

    monkeypatch.setattr(visual_package_tool, "probe_media_reference", fake_probe_media_reference)
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

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        if len(video_calls) == 1:
            return {
                "success": True,
                "video": str(bad_video),
                "provider": "fixture",
                "model": "video-fixture",
                "vision_observation": {
                    "aspect_integrity": 0.2,
                    "motion_quality": 0.25,
                    "artifact_defects": ["weak_aspect_integrity", "weak_motion_or_duration_evidence"],
                },
            }
        return {
            "success": True,
            "video": str(good_video),
            "provider": "fixture",
            "model": "video-fixture",
            "vision_observation": {
                "aspect_integrity": 0.95,
                "motion_quality": 0.9,
                "confidence": 0.9,
                "artifact_defects": [],
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：乾淨產品攝影。",
                "aspect_ratio": "1:1",
                "candidate_budget": 1,
                "video_budget": 1,
                "duration": 4,
            }
        )
    )

    assert payload["success"] is True
    assert payload["videos"] == [str(good_video)]
    assert len(video_calls) == 2
    assert "Video quality repair pass" in video_calls[1]["prompt"]
    assert payload["delivery_gate"]["video"]["allowed"] is True
    assert payload["delivery_gate"]["video"]["repair_attempted"] is True
    assert payload["delivery_gate"]["video"]["repaired_from"]["quality_issues"] == [
        "aspect_integrity_bad",
        "motion_bad",
    ]
    assert payload["delivery_metadata"]["selected_visual_artifact_ids"] == [
        payload["generation_strategy"]["video_source_artifact_id"],
        payload["rankings"]["video"]["selected_artifact_id"],
    ]

    attempts = VisualAttemptLedger(default_visual_ledger_path())._list("visual_attempts")
    repair_attempts = [
        attempt
        for attempt in attempts
        if isinstance(attempt.get("metadata"), dict)
        and isinstance(attempt["metadata"].get("quality_repair"), dict)
        and attempt["metadata"]["quality_repair"].get("modality") == "video"
    ]
    assert len(repair_attempts) == 1
    assert repair_attempts[0]["metadata"]["quality_repair"]["reason"] == "video_quality_issue_blocked"


@pytest.mark.asyncio
async def test_visual_package_repairs_video_blocking_issue_even_when_active_learning_would_ask(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "source.png"
    bad_video = tmp_path / "bad-video.mp4"
    good_video = tmp_path / "good-video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    bad_video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    good_video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomgood")
    video_calls = []

    def fake_probe_media_reference(ref):
        is_video = str(ref).endswith(".mp4")
        return SimpleNamespace(
            sha256=f"hash:{ref}",
            is_stable=True,
            freshness_status="fresh",
            local_path=str(ref),
            mime_type="video/mp4" if is_video else "image/png",
            bytes=10,
            width=768,
            height=768,
            duration_seconds=4.0 if is_video else None,
        )

    monkeypatch.setattr(visual_package_tool, "probe_media_reference", fake_probe_media_reference)
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

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        if len(video_calls) == 1:
            return {
                "success": True,
                "video": str(bad_video),
                "provider": "fixture",
                "model": "video-fixture",
                "vision_observation": {
                    "aspect_integrity": 0.2,
                    "motion_quality": 0.25,
                    "confidence": 0.9,
                    "artifact_defects": ["weak_aspect_integrity", "weak_motion_or_duration_evidence"],
                },
            }
        return {
            "success": True,
            "video": str(good_video),
            "provider": "fixture",
            "model": "video-fixture",
            "vision_observation": {
                "aspect_integrity": 0.95,
                "motion_quality": 0.9,
                "confidence": 0.9,
                "artifact_defects": [],
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：乾淨產品攝影。",
                "aspect_ratio": "1:1",
                "candidate_budget": 1,
                "video_budget": 1,
                "duration": 4,
            }
        )
    )

    assert payload["success"] is True
    assert payload["videos"] == [str(good_video)]
    assert len(video_calls) == 2
    assert payload["delivery_gate"]["video"]["repaired_from"]["reason"] == "video_quality_issue_blocked"
    assert payload["delivery_gate"]["video"]["repaired_from"]["quality_issues"] == [
        "aspect_integrity_bad",
        "motion_bad",
    ]


@pytest.mark.asyncio
async def test_visual_package_applies_video_self_validation_action_to_video_repair(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "prefer_quality_repair_retry",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "source": "fixture_quality_suite",
                                "modality": "video",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "source.png"
    bad_video = tmp_path / "bad-video.mp4"
    good_video = tmp_path / "good-video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    bad_video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    good_video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomgood")
    video_calls = []

    def fake_probe_media_reference(ref):
        is_video = str(ref).endswith(".mp4")
        return SimpleNamespace(
            sha256=f"hash:{ref}",
            is_stable=True,
            freshness_status="fresh",
            local_path=str(ref),
            mime_type="video/mp4" if is_video else "image/png",
            bytes=10,
            width=768,
            height=768,
            duration_seconds=4.0 if is_video else None,
        )

    monkeypatch.setattr(visual_package_tool, "probe_media_reference", fake_probe_media_reference)
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

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        if len(video_calls) == 1:
            return {
                "success": True,
                "video": str(bad_video),
                "provider": "fixture",
                "model": "video-fixture",
                "vision_observation": {
                    "aspect_integrity": 0.2,
                    "motion_quality": 0.25,
                    "artifact_defects": ["weak_aspect_integrity", "weak_motion_or_duration_evidence"],
                },
            }
        return {
            "success": True,
            "video": str(good_video),
            "provider": "fixture",
            "model": "video-fixture",
            "vision_observation": {
                "aspect_integrity": 0.95,
                "motion_quality": 0.9,
                "confidence": 0.9,
                "artifact_defects": [],
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：乾淨產品攝影。",
                "aspect_ratio": "1:1",
                "candidate_budget": 1,
                "video_budget": 1,
                "duration": 4,
            }
        )
    )

    assert payload["success"] is True
    assert payload["generation_strategy"]["feedback_policy"]["quality_repair_modes"] == {
        "image": "default",
        "video": "preferred",
    }
    assert "Proven video quality repair strategy" in video_calls[1]["prompt"]

    attempts = VisualAttemptLedger(default_visual_ledger_path())._list("visual_attempts")
    repair_attempts = [
        attempt
        for attempt in attempts
        if isinstance(attempt.get("metadata"), dict)
        and isinstance(attempt["metadata"].get("quality_repair"), dict)
        and attempt["metadata"]["quality_repair"].get("modality") == "video"
    ]
    assert repair_attempts[0]["metadata"]["quality_repair"]["policy_mode"] == "preferred"


@pytest.mark.asyncio
async def test_visual_package_applies_self_validation_guidance_to_first_image_prompt(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "prefer_quality_repair_retry",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "source": "fixture_quality_suite",
                                "modality": "image",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：時尚寫真。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert "First-pass visual quality guidance" in image_calls[0]["prompt"]
    assert "clean facial features" in image_calls[0]["prompt"]
    assert payload["generation_strategy"]["quality_guidance"]["image"]["mode"] == "preferred"


@pytest.mark.asyncio
async def test_visual_package_applies_self_validation_guidance_to_first_video_prompt(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "prefer_quality_repair_retry",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "source": "fixture_quality_suite",
                                "modality": "video",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "source.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []

    def fake_probe_media_reference(ref):
        is_video = str(ref).endswith(".mp4")
        return SimpleNamespace(
            sha256=f"hash:{ref}",
            is_stable=True,
            freshness_status="fresh",
            local_path=str(ref),
            mime_type="video/mp4" if is_video else "image/png",
            bytes=10,
            width=768,
            height=768,
            duration_seconds=4.0 if is_video else None,
        )

    monkeypatch.setattr(visual_package_tool, "probe_media_reference", fake_probe_media_reference)

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video",
            "vision_observation": {
                "aspect_integrity": 0.95,
                "motion_quality": 0.9,
                "confidence": 0.9,
                "artifact_defects": [],
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：乾淨產品攝影。",
                "include_video": True,
                "candidate_budget": 1,
                "video_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert "First-pass visual quality guidance" not in image_calls[0]["prompt"]
    assert "First-pass video quality guidance" in video_calls[0]["prompt"]
    assert "avoid slow motion" in video_calls[0]["prompt"]
    assert "avoid slow cinematic-only push-in" in video_calls[0]["prompt"]
    assert "visible subject, camera, or environmental movement" in video_calls[0]["prompt"]
    assert payload["generation_strategy"]["quality_guidance"]["video"]["mode"] == "preferred"


@pytest.mark.asyncio
async def test_visual_package_applies_motion_dimension_guidance_to_video_only(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "repair_low_preference_dimension",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "source": "live_quality_burn",
                                "dimension": "motion_quality",
                                "quality_issue": "motion_bad",
                                "repair_hint": "improve_motion_quality",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "source.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []

    def fake_probe_media_reference(ref):
        is_video = str(ref).endswith(".mp4")
        return SimpleNamespace(
            sha256=f"hash:{ref}",
            is_stable=True,
            freshness_status="fresh",
            local_path=str(ref),
            mime_type="video/mp4" if is_video else "image/png",
            bytes=10,
            width=768,
            height=768,
            duration_seconds=4.0 if is_video else None,
        )

    monkeypatch.setattr(visual_package_tool, "probe_media_reference", fake_probe_media_reference)

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video",
            "vision_observation": {
                "aspect_integrity": 0.95,
                "motion_quality": 0.9,
                "confidence": 0.9,
                "artifact_defects": [],
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：乾淨產品攝影。",
                "include_video": True,
                "candidate_budget": 1,
                "video_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert "motion_quality" not in image_calls[0]["prompt"]
    assert "Dimension-specific quality guidance" in video_calls[0]["prompt"]
    assert "motion_quality: use clear real-time movement with stable anatomy" in video_calls[0]["prompt"]
    assert payload["generation_strategy"]["feedback_policy"]["quality_repair_modes"] == {
        "image": "default",
        "video": "preferred",
    }


@pytest.mark.asyncio
async def test_visual_package_video_only_with_attachment_uses_generated_source_by_default(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    source = tmp_path / "source.png"
    generated = tmp_path / "generated.png"
    video = tmp_path / "video.mp4"
    source.write_bytes(_ONE_PIXEL_PNG)
    generated.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {"success": True, "image": str(generated), "provider": "fixture", "model": "image-fixture"}

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {"success": True, "video": str(video), "provider": "fixture", "model": "video-fixture"}

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "用這張圖產生 6 秒短片",
                "attachments": [str(source)],
                "include_image": False,
                "include_video": True,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert payload["images"] == []
    assert payload["videos"] == [str(video)]
    assert image_calls[0]["reference_image_urls"] == [str(source)]
    assert video_calls[0]["image_url"] == str(generated)
    assert payload["generation_strategy"]["image_first_for_video"] is True
    assert payload["generation_strategy"]["video_source_image"] == str(generated)


@pytest.mark.asyncio
async def test_visual_package_image_plus_video_with_attachment_animates_selected_image(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    reference = tmp_path / "reference.png"
    selected = tmp_path / "selected.png"
    video = tmp_path / "video.mp4"
    reference.write_bytes(_ONE_PIXEL_PNG)
    selected.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    video_calls = []

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {"success": True, "image": str(selected), "provider": "fixture", "model": "image-fixture"},
    )

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {"success": True, "video": str(video), "provider": "fixture", "model": "video-fixture"}

    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "用這張 reference 產出一張圖片和一段影片",
                "attachments": [str(reference)],
            }
        )
    )

    assert payload["success"] is True
    assert payload["images"] == [str(selected)]
    assert payload["videos"] == [str(video)]
    assert payload["generation_strategy"]["image_first_for_video"] is True
    assert video_calls[0]["image_url"] == str(selected)
    assert (
        payload["generation_strategy"]["video_source_artifact_id"]
        == payload["rankings"]["image"]["selected_artifact_id"]
    )


@pytest.mark.asyncio
async def test_visual_package_text_only_video_uses_internal_image_first(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {"success": True, "image": str(image), "provider": "fixture", "model": "image-fixture"}

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {"success": True, "video": str(video), "provider": "fixture", "model": "video-fixture"}

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "幫我產生一段 6 秒時尚短片，主體是霧黑鋼筆",
                "include_image": False,
                "include_video": True,
                "candidate_budget": 2,
            }
        )
    )

    assert payload["success"] is True
    assert payload["images"] == []
    assert payload["videos"] == [str(video)]
    assert len(image_calls) == 2
    assert video_calls[0]["image_url"] == str(image)
    assert payload["generation_strategy"]["image_first_for_video"] is True
    assert (
        payload["generation_strategy"]["video_source_artifact_id"]
        == payload["rankings"]["image"]["selected_artifact_id"]
    )

    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    video_attempts = [
        row for row in ledger._list("visual_attempts")
        if row["model"] == "video-fixture"
    ]
    assert video_attempts[0]["parameters_requested"]["source_image_artifact_id"] == (
        payload["generation_strategy"]["video_source_artifact_id"]
    )


@pytest.mark.asyncio
async def test_visual_package_text_only_video_uses_single_ranked_image_when_candidate_budget_is_four(
    monkeypatch,
    tmp_path,
):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    generated_images = []
    for index in range(4):
        image = tmp_path / f"candidate-{index}.png"
        image.write_bytes(_ONE_PIXEL_PNG)
        generated_images.append(image)
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        image = generated_images[len(image_calls) - 1]
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image-fixture",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "fashion_material_quality": 0.9,
            },
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {"success": True, "video": str(video), "provider": "fixture", "model": "video-fixture"}

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "幫我產生一段 6 秒時尚短片，主體是霧黑鋼筆",
                "include_image": False,
                "include_video": True,
                "candidate_budget": 4,
                "video_budget": 1,
            }
        )
    )

    image_paths = {str(image) for image in generated_images}
    assert payload["success"] is True
    assert payload["images"] == []
    assert payload["videos"] == [str(video)]
    assert len(image_calls) == 4
    assert len(video_calls) == 1
    assert isinstance(video_calls[0]["image_url"], str)
    assert video_calls[0]["image_url"] == payload["generation_strategy"]["video_source_image"]
    assert video_calls[0]["image_url"] in image_paths
    assert "reference_image_urls" not in video_calls[0]
    assert "image_urls" not in video_calls[0]
    assert "images" not in video_calls[0]
    assert len(payload["rankings"]["image"]["ranked_artifact_ids"]) == 4
    assert payload["generation_strategy"]["image_first_for_video"] is True


@pytest.mark.asyncio
async def test_visual_package_does_not_animate_candidate_grid_source(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    grid_image = tmp_path / "candidate-grid.png"
    grid_image.write_bytes(_ONE_PIXEL_PNG)
    video_calls = []

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **_kwargs: {
            "success": True,
            "image": str(grid_image),
            "provider": "fixture",
            "model": "image-fixture",
            "vision_observation": {
                "visual_appeal": 0.9,
                "composition": 0.9,
                "confidence": 0.9,
                "artifact_defects": ["candidate_grid_layout"],
            },
        },
    )

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(tmp_path / "should-not-exist.mp4"),
            "provider": "fixture",
            "model": "video-fixture",
        }

    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "幫我產生一段 6 秒產品展示短片，主體是霧黑鋼筆",
                "include_image": False,
                "include_video": True,
                "candidate_budget": 1,
                "video_budget": 1,
            }
        )
    )

    assert payload["success"] is False
    assert payload["videos"] == []
    assert video_calls == []
    assert payload["generation_strategy"]["image_first_for_video"] is True
    assert payload["generation_strategy"]["video_source_image"] is None
    assert payload["delivery_gate"]["image"]["allowed"] is False
    assert payload["delivery_gate"]["image"]["quality_issues"] == ["source_frame_grid"]
    assert payload["generation_payloads"]["video"]["error_type"] == "missing_video_source_image"


@pytest.mark.asyncio
async def test_visual_package_storyboard_generates_ranked_clip_per_shot(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image_paths = []
    for shot_index in range(2):
        for candidate_index in range(2):
            image = tmp_path / f"shot-{shot_index + 1}-candidate-{candidate_index + 1}.png"
            image.write_bytes(_ONE_PIXEL_PNG)
            image_paths.append(image)
    video_paths = []
    for shot_index in range(2):
        video = tmp_path / f"shot-{shot_index + 1}.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
        video_paths.append(video)
    image_calls = []
    video_calls = []
    compose_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        image = image_paths[len(image_calls) - 1]
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image-fixture",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "fashion_material_quality": 0.9,
            },
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        video = video_paths[len(video_calls) - 1]
        return {"success": True, "video": str(video), "provider": "fixture", "model": "video-fixture"}

    def fake_compose_storyboard_clips(video_paths, **kwargs):
        compose_calls.append({"video_paths": list(video_paths), **kwargs})
        return {
            "success": False,
            "provider": "local",
            "model": "fixture-concat",
            "error_type": "fixture_composition_unavailable",
            "error": "fixture keeps selected clips to exercise fallback delivery",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)
    monkeypatch.setattr(visual_package_tool, "_compose_storyboard_clips", fake_compose_storyboard_clips)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請做一支 2 段分鏡的連貫產品影片：霧黑鋼筆放在白紙上。",
                "include_image": False,
                "include_video": True,
                "aspect_ratio": "1:1",
                "duration": 4,
                "candidate_budget": 2,
                "video_budget": 1,
                "storyboard": {
                    "enabled": True,
                    "shot_count": 2,
                    "candidate_budget_per_shot": 2,
                    "source_image_policy": "one_ranked_image_per_shot",
                    "composition_target": "single_coherent_video",
                    "shots": [
                        {"shot_id": "shot_1", "role": "establishing_context"},
                        {"shot_id": "shot_2", "role": "detail_closeup"},
                    ],
                },
            }
        )
    )

    first_shot_sources = {str(path) for path in image_paths[:2]}
    second_shot_sources = {str(path) for path in image_paths[2:]}
    generation_json = json.dumps(payload["generation_payloads"], ensure_ascii=False)
    delivery_json = json.dumps(payload["delivery_metadata"], ensure_ascii=False)

    assert payload["success"] is True
    assert payload["images"] == []
    assert payload["videos"] == [str(video_paths[0]), str(video_paths[1])]
    assert len(image_calls) == 4
    assert len(video_calls) == 2
    assert compose_calls[0]["video_paths"] == [str(video_paths[0]), str(video_paths[1])]
    assert video_calls[0]["image_url"] in first_shot_sources
    assert video_calls[1]["image_url"] in second_shot_sources
    assert video_calls[0]["source_media"]["reference_count"] == 1
    assert video_calls[0]["source_media"]["references"] == [video_calls[0]["image_url"]]
    assert video_calls[1]["source_media"]["reference_count"] == 1
    assert video_calls[1]["source_media"]["references"] == [video_calls[1]["image_url"]]
    assert "reference_image_urls" not in video_calls[0]
    assert "image_urls" not in video_calls[0]
    assert "images" not in video_calls[0]
    for image in image_paths:
        assert str(image) not in delivery_json
        assert str(image) not in generation_json
    storyboard_execution = payload["generation_strategy"]["storyboard_execution"]
    assert storyboard_execution["status"] == "clips_ready"
    assert storyboard_execution["shot_count"] == 2
    assert storyboard_execution["clip_count"] == 2
    assert storyboard_execution["composition_status"] == "failed"
    assert storyboard_execution["composition_error"]["error_type"] == "fixture_composition_unavailable"
    assert storyboard_execution["source_image_policy"] == "one_ranked_image_per_shot"
    assert [shot["shot_id"] for shot in storyboard_execution["shots"]] == ["shot_1", "shot_2"]
    assert all(shot["uses_single_ranked_image"] is True for shot in storyboard_execution["shots"])
    assert all(shot["source_media_reference_count"] == 1 for shot in storyboard_execution["shots"])
    assert all(shot["source_media_single_source_image"] is True for shot in storyboard_execution["shots"])
    assert len(payload["delivery_metadata"]["selected_visual_artifact_ids"]) == 2


@pytest.mark.asyncio
async def test_visual_package_storyboard_delivers_composed_video_when_composition_succeeds(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image_paths = []
    for shot_index in range(2):
        for candidate_index in range(2):
            image = tmp_path / f"compose-shot-{shot_index + 1}-candidate-{candidate_index + 1}.png"
            image.write_bytes(_ONE_PIXEL_PNG)
            image_paths.append(image)
    clip_paths = []
    for shot_index in range(2):
        video = tmp_path / f"compose-shot-{shot_index + 1}.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
        clip_paths.append(video)
    composed_video = tmp_path / "composed-storyboard.mp4"
    composed_video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []
    compose_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image_paths[len(image_calls) - 1]),
            "provider": "fixture",
            "model": "image-fixture",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "fashion_material_quality": 0.9,
            },
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(clip_paths[len(video_calls) - 1]),
            "provider": "fixture",
            "model": "video-fixture",
        }

    def fake_compose_storyboard_clips(video_paths, **kwargs):
        compose_calls.append({"video_paths": list(video_paths), **kwargs})
        return {
            "success": True,
            "video": str(composed_video),
            "provider": "local",
            "model": "fixture-concat",
            "clip_count": len(video_paths),
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)
    monkeypatch.setattr(visual_package_tool, "_compose_storyboard_clips", fake_compose_storyboard_clips, raising=False)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請做一支 2 段分鏡的連貫產品影片：霧黑鋼筆放在白紙上。",
                "include_image": False,
                "include_video": True,
                "aspect_ratio": "1:1",
                "duration": 4,
                "candidate_budget": 2,
                "video_budget": 1,
                "storyboard": {
                    "enabled": True,
                    "shot_count": 2,
                    "candidate_budget_per_shot": 2,
                    "source_image_policy": "one_ranked_image_per_shot",
                    "composition_target": "single_coherent_video",
                },
            }
        )
    )

    generation_json = json.dumps(payload["generation_payloads"], ensure_ascii=False)
    delivery_json = json.dumps(payload["delivery_metadata"], ensure_ascii=False)
    storyboard_execution = payload["generation_strategy"]["storyboard_execution"]

    assert payload["success"] is True
    assert payload["images"] == []
    assert payload["videos"] == [str(composed_video)]
    assert len(video_calls) == 2
    assert compose_calls[0]["video_paths"] == [str(clip_paths[0]), str(clip_paths[1])]
    assert storyboard_execution["status"] == "composed"
    assert storyboard_execution["clip_count"] == 2
    assert storyboard_execution["composition_status"] == "composed"
    assert storyboard_execution["composed_video"] == str(composed_video)
    assert storyboard_execution["delivery_policy"] == "deliver_composed_video_when_available_else_selected_clips"
    assert len(payload["delivery_metadata"]["selected_visual_artifact_ids"]) == 1
    for clip in clip_paths:
        assert str(clip) not in delivery_json
        assert str(clip) not in generation_json
    assert str(composed_video) in delivery_json
    assert str(composed_video) in generation_json

    selected_artifact_id = payload["delivery_metadata"]["selected_visual_artifact_ids"][0]
    judgments = VisualAttemptLedger(default_visual_ledger_path())._list("visual_judgments")
    composed_judgments = [
        row
        for row in judgments
        if row["artifact_id"] == selected_artifact_id and row["judge_name"] == "visual_quality_judge"
    ]
    assert composed_judgments

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    selected_artifact = next(
        row for row in ledger._list("visual_artifacts") if row.get("artifact_id") == selected_artifact_id or row.get("id") == selected_artifact_id
    )
    selected_attempt_id = selected_artifact.get("attempt_id")
    composed_attempt = next(
        row for row in ledger._list("visual_attempts") if row.get("attempt_id") == selected_attempt_id or row.get("id") == selected_attempt_id
    )
    requested_parameters = composed_attempt["parameters_requested"]
    assert requested_parameters["aspect_ratio"] == "1:1"
    assert requested_parameters["duration_seconds"] == 8


@pytest.mark.asyncio
async def test_visual_package_uses_preference_aligned_image_for_video_source(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    generic_image = tmp_path / "generic.png"
    aligned_image = tmp_path / "aligned.png"
    video = tmp_path / "video.mp4"
    generic_image.write_bytes(_ONE_PIXEL_PNG)
    aligned_image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []

    def fake_probe_media_reference(ref):
        ref_text = str(ref)
        is_video = ref_text.endswith(".mp4")
        return SimpleNamespace(
            sha256=f"sha256:{ref_text}",
            is_stable=True,
            freshness_status="fresh",
            local_path=ref_text,
            mime_type="video/mp4" if is_video else "image/png",
            bytes=100,
            width=768,
            height=768,
            duration_seconds=4.0 if is_video else None,
        )

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        if len(image_calls) == 1:
            return {
                "success": True,
                "image": str(generic_image),
                "provider": "xai",
                "model": "image",
                "vision_observation": {
                    "reference_adherence": 0.9,
                    "subject_quality": 0.24,
                    "face_quality": 0.26,
                    "visual_appeal": 0.96,
                    "glamour_impact": 0.25,
                    "composition": 0.9,
                    "pose_composition": 0.3,
                    "pose_novelty": 0.9,
                    "fashion_material_quality": 0.28,
                    "confidence": 0.96,
                },
            }
        return {
            "success": True,
            "image": str(aligned_image),
            "provider": "xai",
            "model": "image",
            "vision_observation": {
                "reference_adherence": 0.82,
                "subject_quality": 0.82,
                "face_quality": 0.84,
                "visual_appeal": 0.78,
                "glamour_impact": 0.8,
                "composition": 0.78,
                "pose_composition": 0.78,
                "pose_novelty": 0.74,
                "fashion_material_quality": 0.83,
                "confidence": 0.78,
            },
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(video),
            "provider": "xai",
            "model": "video",
            "vision_observation": {
                "aspect_integrity": 0.95,
                "motion_quality": 0.9,
                "composition": 0.85,
                "confidence": 0.9,
                "artifact_defects": [],
            },
        }

    monkeypatch.setattr(visual_package_tool, "probe_media_reference", fake_probe_media_reference)
    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張性感時尚寫真圖片和一段短影片，重視美女臉、絲襪質感、腿部構圖。",
                "include_image": True,
                "include_video": True,
                "candidate_budget": 2,
                "video_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(image_calls) == 2
    assert video_calls[0]["image_url"] == str(aligned_image)
    assert payload["generation_strategy"]["video_source_image"] == str(aligned_image)
    assert payload["rankings"]["image"]["ranked_artifact_ids"][0] == (
        payload["generation_strategy"]["video_source_artifact_id"]
    )


@pytest.mark.asyncio
async def test_visual_package_text_only_video_does_not_fall_back_to_direct_video_when_images_fail(
    monkeypatch,
    tmp_path,
):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    def fake_generate_image(**kwargs):
        return {
            "success": False,
            "image": None,
            "error": "image provider unavailable",
            "error_type": "connection_error",
            "provider": "fixture",
            "model": "image-fixture",
        }

    def fail_generate_video(**kwargs):
        raise AssertionError(f"must not call direct text-to-video without a source image: {kwargs}")

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fail_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "幫我產生一段 6 秒時尚短片，主體是霧黑鋼筆",
                "include_image": False,
                "include_video": True,
                "candidate_budget": 2,
            }
        )
    )

    assert payload["success"] is False
    assert payload["videos"] == []
    assert payload["generation_payloads"]["video"]["error_type"] == "missing_video_source_image"
    assert payload["generation_strategy"]["image_first_for_video"] is True


@pytest.mark.asyncio
async def test_visual_package_video_aspect_follows_selected_source_image(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "portrait.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    video_calls = []

    def fake_probe_media_reference(ref):
        return SimpleNamespace(
            sha256=f"hash:{ref}",
            is_stable=True,
            freshness_status="fresh",
            local_path=str(ref) if str(ref).startswith("/") else None,
            mime_type="image/png" if str(ref).endswith(".png") else "video/mp4",
            bytes=10,
            width=720 if str(ref).endswith(".png") else 0,
            height=1280 if str(ref).endswith(".png") else 0,
        )

    monkeypatch.setattr(visual_package_tool, "probe_media_reference", fake_probe_media_reference)
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
        {"prompt": "image plus video", "aspect_ratio": "16:9"}
    )

    assert video_calls[0]["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_visual_package_generate_materializes_successful_remote_video_url(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    remote_video_url = "https://vidgen.x.ai/xai-vidgen-bucket/current.mp4"
    cached_video = tmp_path / "cached-current.mp4"

    def fake_download_remote_media(url, *, kind):
        assert url == remote_video_url
        assert kind == "video"
        cached_video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
        return str(cached_video)

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
            "video": remote_video_url,
            "provider": "fixture",
            "model": "video-fixture",
        },
    )
    monkeypatch.setattr(
        visual_package_tool,
        "download_remote_media",
        fake_download_remote_media,
        raising=False,
    )

    def fake_probe_media_reference(ref):
        is_video = str(ref).endswith(".mp4")
        return SimpleNamespace(
            sha256=f"hash:{ref}",
            is_stable=True,
            freshness_status="fresh",
            local_path=str(ref) if str(ref).startswith("/") else None,
            mime_type="video/mp4" if is_video else "image/png",
            bytes=10,
            width=1024,
            height=576,
            duration_seconds=6.0 if is_video else None,
        )

    monkeypatch.setattr(visual_package_tool, "probe_media_reference", fake_probe_media_reference)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片和一段影片：霧黑鋼筆。"}
        )
    )

    assert payload["success"] is True
    assert payload["videos"] == [str(cached_video)]
    assert len(payload["delivery_metadata"]["selected_visual_artifact_ids"]) == 2
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    artifacts = ledger._list(
        "visual_artifacts",
        where="request_id = ?",
        params=(payload["visual_request_id"],),
    )
    video_artifact = next(row for row in artifacts if row["kind"] == "video")
    assert video_artifact["width"] == 1024
    assert video_artifact["height"] == 576
    assert video_artifact["duration_seconds"] == 6.0


@pytest.mark.asyncio
async def test_visual_package_does_not_select_remote_video_when_materialization_fails(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    remote_video_url = "https://vidgen.x.ai/xai-vidgen-bucket/current.mp4"

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
            "video": remote_video_url,
            "provider": "fixture",
            "model": "video-fixture",
        },
    )
    monkeypatch.setattr(
        visual_package_tool,
        "download_remote_media",
        lambda url, *, kind: (_ for _ in ()).throw(RuntimeError("download failed")),
        raising=False,
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片和一段影片：霧黑鋼筆。"}
        )
    )

    assert payload["success"] is False
    assert payload["package_status"] == "partial"
    assert payload["videos"] == []
    assert remote_video_url not in payload["videos"]


@pytest.mark.asyncio
async def test_visual_package_generates_multiple_image_candidates_and_posts_only_winner(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    paths = []
    for index in range(2):
        path = tmp_path / f"image-{index}.png"
        path.write_bytes(_ONE_PIXEL_PNG)
        paths.append(path)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "image": str(paths[len(calls) - 1]),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {"success": False, "error": "not requested", "provider": "fixture", "model": "video"},
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：霧黑鋼筆。", "candidate_budget": 2, "include_video": False}
        )
    )

    assert len(calls) == 2
    assert len(payload["images"]) == 1
    selected_refs = set(payload["images"] + payload["videos"])
    rejected_refs = {str(path) for path in paths} - selected_refs
    assert rejected_refs
    assert len(
        {
            entry["artifact_id"]
            for entry in payload["delivery_metadata"]["visual_artifacts"].values()
        }
    ) == 1
    assert len(payload["delivery_metadata"]["selected_visual_artifact_ids"]) == 1
    delivery_json = json.dumps(payload["delivery_metadata"], ensure_ascii=False)
    generation_json = json.dumps(payload["generation_payloads"], ensure_ascii=False)
    for ref in rejected_refs:
        assert ref not in delivery_json
        assert ref not in generation_json


@pytest.mark.asyncio
async def test_visual_package_records_shadow_learning_but_keeps_delivery_selected_only(monkeypatch, tmp_path):
    from agent.visual.tracking import default_visual_ledger_path
    from agent.visual.self_validation import run_visual_self_validation
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：霧黑鋼筆。", "include_video": False}
        )
    )

    assert payload["success"] is True
    assert payload["rankings"]["image"]["decision"] in {"post", "ask_user"}
    assert payload["delivery_metadata"]["selected_visual_artifact_ids"]
    assert payload["learning"]["mode"] == "shadow"
    validation = run_visual_self_validation(
        default_visual_ledger_path(),
        request_id=payload["visual_request_id"],
    )
    assert validation["success"] is True


@pytest.mark.asyncio
async def test_visual_package_reads_controlled_strategy_without_prompt_mutation(monkeypatch, tmp_path):
    from agent.visual.intent_signature import build_intent_signature
    from agent.visual.strategy_activation import record_strategy_activation
    from agent.visual.tracking import default_visual_ledger_path
    from scripts.visual_strategy_activation_report import build_strategy_activation_report
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    prompt = "請產出一張圖片：霧黑鋼筆。"
    intent_signature = build_intent_signature(
        {
            "kind": "visual_package",
            "wants_image": True,
            "wants_video": False,
            "aspect_ratio": "16:9",
            "modality": "package",
            "operation": "visual_package_generate",
        }
    )
    ledger = visual_package_tool.VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    activation_id = record_strategy_activation(
        ledger,
        shadow_update_id="vsh_demo",
        intent_signature=intent_signature,
        strategy_signature="vstrat_controlled_demo",
        activation_status="controlled",
        promotion_decision={
            "decision": "promote_controlled",
            "allowed": True,
            "confidence": 0.88,
        },
        metadata={"atom_signatures": ["composition.full_subject_visible@v1"]},
    )
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": prompt, "include_video": False, "candidate_budget": 1}
        )
    )

    assert payload["success"] is True
    assert payload["learning"]["mode"] == "controlled_read_only"
    assert payload["learning"]["strategy_plan"]["activation_status"] == "controlled"
    assert payload["learning"]["strategy_plan"]["activation_id"] == activation_id
    assert payload["learning"]["strategy_plan"]["prompt_mutation_allowed"] is False
    assert image_calls[0]["prompt"] == prompt
    report = build_strategy_activation_report(default_visual_ledger_path())
    assert report["strategy_activations"]["read_count"] == 1
    assert report["strategy_activations"]["prompt_mutation_read_count"] == 0


@pytest.mark.asyncio
async def test_visual_package_applies_controlled_image_first_strategy_to_runtime_policy(monkeypatch, tmp_path):
    from agent.visual.strategy_activation import record_strategy_activation
    from agent.visual.strategy_policy import GLOBAL_VISUAL_AGENT_INTENT_SIGNATURE
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    ledger = visual_package_tool.VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    record_strategy_activation(
        ledger,
        shadow_update_id="vsh_global",
        intent_signature=GLOBAL_VISUAL_AGENT_INTENT_SIGNATURE,
        strategy_signature="image_first_rank_then_video",
        activation_status="controlled",
        promotion_decision={
            "decision": "promote_controlled",
            "allowed": True,
            "confidence": 0.8206,
        },
        metadata={"scope": "global_visual_agent_mode"},
    )
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：霧黑鋼筆。",
                "candidate_budget": 1,
                "candidate_budget_source": "planner_default",
                "video_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(image_calls) == 2
    assert payload["generation_strategy"]["candidate_budget"] == 2
    assert payload["generation_strategy"]["candidate_budget_source"] == "controlled_strategy"
    assert payload["generation_strategy"]["image_first_for_video"] is True
    assert payload["generation_strategy"]["feedback_policy"]["rerank_before_delivery"] is True
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == ["prefer_strategy"]
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_sources"] == ["controlled_strategy"]
    assert payload["learning"]["mode"] == "controlled_read_only"
    assert payload["learning"]["strategy_plan"]["strategy_signature"] == "image_first_rank_then_video"


@pytest.mark.asyncio
async def test_visual_package_applies_feedback_dimension_repairs_from_auto_judge(monkeypatch, tmp_path):
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = visual_package_tool.VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    previous_request_id = ledger.record_request(
        status="completed",
        metadata={"intent_signature": "visig_glamour"},
    )
    previous_attempt_id = ledger.record_attempt(
        request_id=previous_request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        status="completed",
    )
    previous_artifact_id = ledger.record_artifact(
        request_id=previous_request_id,
        attempt_id=previous_attempt_id,
        kind="image",
        local_path="/tmp/private-low-dim.jpg",
        content_hash="sha256:private-low-dim",
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=previous_request_id,
        attempt_id=previous_attempt_id,
        artifact_id=previous_artifact_id,
        judge_name="visual_quality_judge",
        score=0.42,
        verdict="fail",
        details={
            "quality_issues": ["face_unnatural", "stockings_bad"],
            "preference_dimensions": {
                "face_naturalness": 0.28,
                "fashion_material_quality": 0.31,
                "pose_composition": 0.78,
            },
        },
    )
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "fashion_material_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：時尚寫真。",
                "include_video": False,
                "candidate_budget": 1,
                "candidate_budget_source": "planner_default",
            }
        )
    )

    assert payload["success"] is True
    assert payload["generation_strategy"]["candidate_budget"] == 4
    assert payload["generation_strategy"]["candidate_budget_source"] == "feedback_loop"
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == [
        "increase_candidate_budget",
        "rerank_before_slack",
        "repair_low_preference_dimension",
    ]
    assert payload["generation_strategy"]["feedback_policy"]["repair_dimensions"] == [
        {
            "dimension": "face_naturalness",
            "quality_issue": "face_unnatural",
            "repair_hint": "improve_face_naturalness",
        },
        {
            "dimension": "fashion_material_quality",
            "quality_issue": "stockings_bad",
            "repair_hint": "improve_fashion_material_quality",
        },
    ]
    assert "face_naturalness" in image_calls[0]["prompt"]
    assert "fashion_material_quality" in image_calls[0]["prompt"]


@pytest.mark.asyncio
async def test_visual_package_records_quality_judgment_for_candidates(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：霧黑鋼筆。", "include_video": False, "candidate_budget": 1}
        )
    )

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    rankings = _list_rows(ledger, "visual_rankings")
    quality_judgments = [
        row
        for row in _list_rows(ledger, "visual_judgments")
        if row["judge_name"] == "visual_quality_judge"
    ]
    assert quality_judgments
    assert quality_judgments[0]["metadata"]["intent_signature"].startswith("visig_")
    assert quality_judgments[0]["metadata"]["strategy_signature"].startswith("vstrat_")
    assert quality_judgments[0]["metadata"]["modality"] == "image"
    assert "judge_sources" in quality_judgments[0]["metadata"]
    assert quality_judgments[0]["metadata"]["judge_sources"]["composition"] == "vision"
    assert rankings[0]["scores"]["reward"]["dimensions"]["aesthetic_fit"] != 0.5


@pytest.mark.asyncio
async def test_visual_package_quality_judge_flags_duplicate_candidate_hash(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "same-image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出兩張圖片：霧黑鋼筆。", "include_video": False, "candidate_budget": 2}
        )
    )

    assert payload["success"] is True
    judgments = VisualAttemptLedger(default_visual_ledger_path())._list("visual_judgments")
    duplicate_judgments = [
        row
        for row in judgments
        if "duplicate_content_hash" in row["details"].get("uncertainty_reasons", [])
    ]
    assert duplicate_judgments


@pytest.mark.asyncio
async def test_visual_package_auto_increases_candidate_budget_from_feedback_loop(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    seed_request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_seed"})
    seed_attempt_id = ledger.record_attempt(
        request_id=seed_request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        status="completed",
    )
    seed_artifact_id = ledger.record_artifact(
        request_id=seed_request_id,
        attempt_id=seed_attempt_id,
        kind="image",
        local_path=str(tmp_path / "seed.png"),
        content_hash="sha256:seed-low-quality",
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=seed_request_id,
        attempt_id=seed_attempt_id,
        artifact_id=seed_artifact_id,
        judge_name="visual_quality_judge",
        score=0.35,
        verdict="fail",
    )

    paths = []
    for index in range(4):
        path = tmp_path / f"image-{index}.png"
        path.write_bytes(_ONE_PIXEL_PNG)
        paths.append(path)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "image": str(paths[len(calls) - 1]),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：霧黑鋼筆。", "include_video": False}
        )
    )

    assert payload["success"] is True
    assert len(calls) == 4
    assert payload["generation_strategy"]["candidate_budget"] == 4
    assert payload["generation_strategy"]["candidate_budget_source"] == "feedback_loop"
    assert payload["generation_strategy"]["feedback_policy"]["rerank_before_delivery"] is True
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == [
        "increase_candidate_budget",
        "rerank_before_slack",
    ]


@pytest.mark.asyncio
async def test_visual_package_allows_feedback_to_raise_planner_default_candidate_budget(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    seed_request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_seed"})
    seed_attempt_id = ledger.record_attempt(
        request_id=seed_request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        status="completed",
    )
    seed_artifact_id = ledger.record_artifact(
        request_id=seed_request_id,
        attempt_id=seed_attempt_id,
        kind="image",
        local_path=str(tmp_path / "seed.png"),
        content_hash="sha256:seed-low-quality",
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=seed_request_id,
        attempt_id=seed_attempt_id,
        artifact_id=seed_artifact_id,
        judge_name="visual_quality_judge",
        score=0.35,
        verdict="fail",
    )

    paths = []
    for index in range(4):
        path = tmp_path / f"image-{index}.png"
        path.write_bytes(_ONE_PIXEL_PNG)
        paths.append(path)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "image": str(paths[len(calls) - 1]),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：霧黑鋼筆。",
                "include_video": False,
                "candidate_budget": 1,
                "candidate_budget_source": "planner_default",
            }
        )
    )

    assert payload["success"] is True
    assert len(calls) == 4
    assert payload["generation_strategy"]["candidate_budget"] == 4
    assert payload["generation_strategy"]["candidate_budget_source"] == "feedback_loop"


@pytest.mark.asyncio
async def test_visual_package_respects_explicit_candidate_budget_over_feedback_loop(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    seed_request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_seed"})
    seed_attempt_id = ledger.record_attempt(
        request_id=seed_request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        status="completed",
    )
    seed_artifact_id = ledger.record_artifact(
        request_id=seed_request_id,
        attempt_id=seed_attempt_id,
        kind="image",
        local_path=str(tmp_path / "seed.png"),
        content_hash="sha256:seed-low-quality",
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=seed_request_id,
        attempt_id=seed_attempt_id,
        artifact_id=seed_artifact_id,
        judge_name="visual_quality_judge",
        score=0.35,
        verdict="fail",
    )

    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：霧黑鋼筆。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(calls) == 1
    assert payload["generation_strategy"]["candidate_budget"] == 1
    assert payload["generation_strategy"]["candidate_budget_source"] == "user"


@pytest.mark.asyncio
async def test_visual_package_applies_preferred_quality_repair_policy(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()
    seed_request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_seed"})
    repair_attempt_id = ledger.record_attempt(
        request_id=seed_request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        status="completed",
        metadata={
            "quality_repair": {
                "reason": "active_learning_fail_closed",
                "quality_issues": ["subject_not_attractive"],
            }
        },
    )
    repair_artifact_id = ledger.record_artifact(
        request_id=seed_request_id,
        attempt_id=repair_attempt_id,
        kind="image",
        local_path=str(tmp_path / "seed-repair.png"),
        content_hash="sha256:seed-repair",
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=seed_request_id,
        attempt_id=repair_attempt_id,
        artifact_id=repair_artifact_id,
        judge_name="visual_quality_judge",
        score=0.92,
        verdict="pass",
    )
    ledger.record_delivery(
        request_id=seed_request_id,
        attempt_id=repair_attempt_id,
        artifact_id=repair_artifact_id,
        platform="slack",
        destination_id="C123",
        delivery_status="sent",
    )

    bad_image = tmp_path / "bad-image.png"
    good_image = tmp_path / "good-image.png"
    bad_image.write_bytes(_ONE_PIXEL_PNG)
    good_image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "success": True,
                "image": str(bad_image),
                "provider": "fixture",
                "model": "image",
                "vision_observation": {
                    "face_quality": 0.2,
                    "visual_appeal": 0.2,
                    "composition": 0.2,
                    "stocking_quality": 0.2,
                },
            }
        return {
            "success": True,
            "image": str(good_image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：時尚寫真。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert payload["generation_strategy"]["feedback_policy"]["quality_repair_mode"] == "preferred"
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == [
        "prefer_quality_repair_retry"
    ]
    assert "Proven quality repair strategy" in calls[1]["prompt"]
    attempts = VisualAttemptLedger(default_visual_ledger_path())._list("visual_attempts")
    repair_attempts = [
        attempt
        for attempt in attempts
        if isinstance(attempt.get("metadata"), dict)
        and isinstance(attempt["metadata"].get("quality_repair"), dict)
        and attempt["metadata"]["quality_repair"].get("policy_mode") == "preferred"
    ]
    assert len(repair_attempts) == 1


@pytest.mark.asyncio
async def test_visual_package_applies_self_validation_next_actions(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "prefer_quality_repair_retry",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "confidence": 0.9,
                                "source": "fixture_quality_suite",
                                "modality": "image",
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    bad_image = tmp_path / "bad-image.png"
    good_image = tmp_path / "good-image.png"
    bad_image.write_bytes(_ONE_PIXEL_PNG)
    good_image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "success": True,
                "image": str(bad_image),
                "provider": "fixture",
                "model": "image",
                "vision_observation": {
                    "face_quality": 0.2,
                    "visual_appeal": 0.2,
                    "composition": 0.2,
                    "stocking_quality": 0.2,
                },
            }
        return {
            "success": True,
            "image": str(good_image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：時尚寫真。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert payload["generation_strategy"]["feedback_policy"]["quality_repair_mode"] == "preferred"
    assert payload["generation_strategy"]["feedback_policy"]["policy_sources"] == [
        "feedback_loop",
        "scheduled_self_validation",
    ]
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == [
        "prefer_quality_repair_retry"
    ]
    assert "Proven quality repair strategy" in calls[1]["prompt"]


@pytest.mark.asyncio
async def test_visual_package_applies_self_validation_strategy_preference(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "prefer_strategy",
                                "requires_human_feedback": False,
                                "activation_status": "shadow",
                                "confidence": 0.91,
                                "source": "live_quality_burn",
                                "bucket": "live_visual_agent_mode",
                                "strategy_signature": "image_first_rank_then_video",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：霧黑鋼筆。",
                "candidate_budget": 1,
                "candidate_budget_source": "planner_default",
                "video_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(image_calls) == 2
    assert payload["generation_strategy"]["candidate_budget"] == 2
    assert payload["generation_strategy"]["feedback_policy"]["strategy_preference"]["strategy_signature"] == (
        "image_first_rank_then_video"
    )
    assert payload["learning"]["mode"] == "feedback_preferred_read_only"
    assert payload["learning"]["strategy_plan"]["strategy_signature"] == "image_first_rank_then_video"
    assert payload["learning"]["strategy_plan"]["prompt_mutation_allowed"] is False
    learning_rows = VisualAttemptLedger(default_visual_ledger_path())._list("visual_shadow_updates")
    assert {row["strategy_signature"] for row in learning_rows} == {"image_first_rank_then_video"}


@pytest.mark.asyncio
async def test_visual_package_live_strategy_budget_overrides_stale_feedback_budget(monkeypatch, tmp_path):
    from scripts import visual_feedback_loop_report
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(
        visual_feedback_loop_report,
        "build_visual_feedback_loop_report",
        lambda _path: {
            "next_actions": [
                {
                    "type": "increase_candidate_budget",
                    "max_candidate_budget": 4,
                    "source": "feedback_loop",
                    "requires_human_feedback": False,
                }
            ]
        },
    )
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "prefer_strategy",
                                "requires_human_feedback": False,
                                "activation_status": "shadow",
                                "confidence": 0.82,
                                "source": "live_quality_burn",
                                "bucket": "live_visual_agent_mode",
                                "strategy_signature": "image_first_rank_then_video",
                                "candidate_budget": 2,
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：霧黑鋼筆。",
                "candidate_budget": 1,
                "candidate_budget_source": "planner_default",
                "video_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(image_calls) == 2
    assert payload["generation_strategy"]["candidate_budget"] == 2
    assert payload["generation_strategy"]["candidate_budget_source"] == "live_quality_burn"
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == [
        "increase_candidate_budget",
        "prefer_strategy",
    ]


@pytest.mark.asyncio
async def test_visual_package_uses_image_first_video_policy_for_attachment_video(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "prefer_image_first_video",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "confidence": 0.78,
                                "source": "live_quality_burn",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    reference = tmp_path / "reference.png"
    generated_image = tmp_path / "generated-image.png"
    video = tmp_path / "video.mp4"
    reference.write_bytes(_ONE_PIXEL_PNG)
    generated_image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(generated_image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一段短影片：優雅產品展示。",
                "attachments": [str(reference)],
                "include_video": True,
                "video_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(image_calls) == 2
    assert image_calls[0]["reference_image_urls"] == [str(reference)]
    assert video_calls[0]["image_url"] == str(generated_image)
    assert payload["images"] == []
    assert payload["videos"] == [str(video)]
    assert payload["generation_strategy"]["generated_image"] is True
    assert payload["generation_strategy"]["image_first_for_video"] is True
    assert payload["generation_strategy"]["video_source_image"] == str(generated_image)
    assert payload["generation_strategy"]["feedback_policy"]["prefer_image_first_video"] is True


@pytest.mark.asyncio
async def test_visual_package_applies_preference_dimension_guidance_from_self_validation(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "repair_low_preference_dimension",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "confidence": 0.72,
                                "source": "live_quality_burn",
                                "dimension": "face_naturalness",
                                "quality_issue": "face_unnatural",
                                "repair_hint": "improve_face_naturalness",
                            },
                            {
                                "type": "repair_low_preference_dimension",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "confidence": 0.72,
                                "source": "live_quality_burn",
                                "dimension": "fashion_material_quality",
                                "quality_issue": "stockings_bad",
                                "repair_hint": "improve_fashion_material_quality",
                            },
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image_path = tmp_path / "image.png"
    image_path.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "image": str(image_path),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "fashion_material_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：時尚寫真。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert payload["generation_strategy"]["feedback_policy"]["repair_dimensions"] == [
        {
            "dimension": "face_naturalness",
            "quality_issue": "face_unnatural",
            "repair_hint": "improve_face_naturalness",
        },
        {
            "dimension": "fashion_material_quality",
            "quality_issue": "stockings_bad",
            "repair_hint": "improve_fashion_material_quality",
        },
    ]
    assert "Dimension-specific quality guidance" in calls[0]["prompt"]
    assert "face_naturalness" in calls[0]["prompt"]
    assert "fashion_material_quality" in calls[0]["prompt"]


@pytest.mark.asyncio
async def test_visual_package_requires_preference_dimension_evidence_from_self_validation(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "require_preference_dimension_evidence",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "confidence": 0.84,
                                "source": "live_quality_burn",
                                "dimension": "subject_beauty",
                                "focus": "adult_fashion_portrait",
                                "evaluation_operator": "inline_vision_preference_dimensions",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image_path = tmp_path / "image.png"
    image_path.write_bytes(_ONE_PIXEL_PNG)
    vision_calls = []

    def fake_generate_image(**kwargs):
        return {
            "success": True,
            "image": str(image_path),
            "provider": "fixture",
            "model": "image",
        }

    def fake_inline_vision(candidate):
        vision_calls.append(candidate["artifact_path"])
        return {
            "subject_quality": 0.92,
            "face_quality": 0.9,
            "glamour_impact": 0.86,
            "fashion_material_quality": 0.88,
            "pose_composition": 0.87,
            "visual_appeal": 0.9,
            "composition": 0.88,
            "confidence": 0.9,
            "evidence": {"source": "inline_vision_judge"},
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "analyze_candidate_with_vision_tool", fake_inline_vision)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：時尚寫真。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert vision_calls == [str(image_path)]
    assert payload["generation_strategy"]["feedback_policy"]["require_preference_dimension_evidence"] is True
    assert payload["generation_strategy"]["feedback_policy"]["required_preference_dimensions"] == ["subject_beauty"]


@pytest.mark.asyncio
async def test_visual_package_applies_quality_focus_operator_guidance_from_self_validation(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "apply_quality_focus_operator",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "confidence": 0.76,
                                "source": "live_quality_burn",
                                "focus": "legwear_material",
                                "dimension": "fashion_material_quality",
                                "strategy_operator": "refine_legwear_material",
                                "repair_hint": "improve_fashion_material_quality",
                                "quality_issues": ["stockings_bad"],
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image_path = tmp_path / "image.png"
    image_path.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "image": str(image_path),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "fashion_material_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：時尚寫真。",
                "include_video": False,
                "candidate_budget": 1,
                "candidate_budget_source": "planner_default",
            }
        )
    )

    assert payload["success"] is True
    assert len(calls) == 2
    assert payload["generation_strategy"]["candidate_budget"] == 2
    assert payload["generation_strategy"]["candidate_budget_source"] == "live_quality_burn"
    assert payload["generation_strategy"]["feedback_policy"]["quality_focus_operators"] == [
        {
            "focus": "legwear_material",
            "dimension": "fashion_material_quality",
            "strategy_operator": "refine_legwear_material",
            "source": "live_quality_burn",
        }
    ]
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == [
        "apply_quality_focus_operator"
    ]
    assert "Dimension-specific quality guidance" in calls[0]["prompt"]
    assert "fashion_material_quality" in calls[0]["prompt"]


@pytest.mark.asyncio
async def test_visual_package_applies_live_quality_trend_actions_with_source(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "increase_candidate_budget",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "source": "live_quality_trends",
                                "max_candidate_budget": 4,
                            },
                            {
                                "type": "prefer_image_first_video",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "source": "live_quality_trends",
                            },
                            {
                                "type": "repair_low_preference_dimension",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "source": "live_quality_trends",
                                "dimension": "fashion_material_quality",
                                "quality_issue": "stockings_bad",
                                "repair_hint": "improve_fashion_material_quality",
                            },
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    video = tmp_path / "video.mp4"
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
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "fashion_material_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一段短影片：時尚寫真。",
                "include_video": True,
                "video_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(image_calls) == 4
    assert len(video_calls) == 1
    assert payload["generation_strategy"]["image_first_for_video"] is True
    assert payload["generation_strategy"]["candidate_budget"] == 4
    assert payload["generation_strategy"]["candidate_budget_source"] == "live_quality_trends"
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_sources"] == [
        "live_quality_trends"
    ]
    assert payload["generation_strategy"]["feedback_policy"]["repair_dimensions"] == [
        {
            "dimension": "fashion_material_quality",
            "quality_issue": "stockings_bad",
            "repair_hint": "improve_fashion_material_quality",
            "source": "live_quality_trends",
        }
    ]
    assert "fashion_material_quality" in image_calls[0]["prompt"]


@pytest.mark.asyncio
async def test_visual_package_applies_safe_reframe_retry_budget_from_self_validation(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "safe_reframe_provider_retry",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "confidence": 0.7,
                                "source": "live_quality_burn",
                                "provider_failure_classes": {"content_moderation": 2},
                                "provider_error_codes": {"api_error": 2},
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            return {
                "success": False,
                "error_type": "api_error",
                "error": "Generated image rejected by content moderation.",
                "provider": "xai",
                "model": "grok-imagine-image-quality",
            }
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：時尚寫真。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(calls) == 3
    assert payload["generation_strategy"]["feedback_policy"]["provider_recovery_mode"] == "safe_reframe"
    assert payload["generation_strategy"]["feedback_policy"]["provider_retry_budget"] == 2
    assert payload["generation_strategy"]["feedback_policy"]["provider_failure_context"] == {
        "provider_failure_classes": {"content_moderation": 2},
        "provider_error_codes": {"api_error": 2},
    }
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == [
        "safe_reframe_provider_retry"
    ]
    assert "policy-compliant editorial visual variant" in calls[1]["prompt"]
    assert "policy-compliant editorial visual variant" in calls[2]["prompt"]
    assert payload["generation_payloads"]["image"][0]["recovery"]["audit"]["retry_budget_remaining"] == 2
    assert payload["generation_payloads"]["image"][1]["recovery"]["audit"]["retry_budget_remaining"] == 1
    assert payload["generation_payloads"]["image"][2]["retry_of"] == 1


@pytest.mark.asyncio
async def test_visual_package_applies_provider_connectivity_retry_without_safe_reframe(
    monkeypatch,
    tmp_path,
):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "runtime_policy": {
                    "success": True,
                    "decision": "apply_next_run",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "next_actions": [
                        {
                            "type": "check_provider_connectivity_or_retry",
                            "requires_human_feedback": False,
                            "activation_status": "next_run",
                            "confidence": 0.88,
                            "source": "live_quality_burn",
                            "provider_failure_classes": {"provider_unavailable": 16},
                            "provider_error_codes": {"connection_error": 16},
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "success": False,
                "error_type": "connection_error",
                "error": "xAI connection error: failed to resolve api.x.ai",
                "provider": "xai-oauth",
                "model": "grok-imagine-image-quality",
            }
        return {
            "success": True,
            "image": str(image),
            "provider": "xai-oauth",
            "model": "grok-imagine-image-quality",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：乾淨產品攝影。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(calls) == 2
    policy = payload["generation_strategy"]["feedback_policy"]
    assert policy["provider_recovery_mode"] == "provider_connectivity_retry"
    assert policy["provider_retry_budget"] == 1
    assert policy["provider_failure_context"] == {
        "provider_failure_classes": {"provider_unavailable": 16},
        "provider_error_codes": {"connection_error": 16},
    }
    assert policy["applied_action_types"] == ["check_provider_connectivity_or_retry"]
    assert calls[1]["prompt"] == calls[0]["prompt"]
    assert "policy-compliant editorial visual variant" not in calls[1]["prompt"]


@pytest.mark.asyncio
async def test_visual_package_honors_provider_account_blocked_zero_retry_budget(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "resolve_provider_quota_or_switch_provider",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "confidence": 0.95,
                                "source": "live_quality_burn",
                                "provider_failure_classes": {"quota_exceeded": 1},
                                "provider_error_codes": {
                                    "personal-team-blocked:spending-limit": 1
                                },
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        return {
            "success": False,
            "error_type": "api_error",
            "error": (
                'xAI image gen failed (403): {"code":"personal-team-blocked:spending-limit",'
                '"error":"You have run out of credits or need a Grok subscription."}'
            ),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：產品攝影。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is False
    assert len(calls) == 1
    assert payload["generation_strategy"]["feedback_policy"]["provider_recovery_mode"] == (
        "provider_account_blocked"
    )
    assert payload["generation_strategy"]["feedback_policy"]["provider_retry_budget"] == 0
    assert payload["generation_payloads"]["image"]["recovery"]["reason"] == (
        "provider_quota_or_subscription_required"
    )
    assert payload["generation_payloads"]["image"]["recovery"]["audit"][
        "provider_message_code"
    ] == "personal-team-blocked:spending-limit"
    assert payload["generation_payloads"]["image"]["recovery"]["audit"][
        "retry_budget_remaining"
    ] == 0


@pytest.mark.asyncio
async def test_visual_package_surfaces_missing_video_fallback_policy(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "configure_video_fallback_provider",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "confidence": 0.9,
                                "source": "live_quality_burn",
                                "provider_failure_classes": {"quota_exceeded": 2},
                                "provider_error_codes": {
                                    "personal-team-blocked:spending-limit": 2
                                },
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **_kwargs: {
            "success": True,
            "image": str(image),
            "provider": "codex",
            "model": "gpt-image-fallback",
            "vision_observation": {
                "face_quality": 0.9,
                "fashion_material_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        },
    )
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **_kwargs: {
            "success": True,
            "video": str(video),
            "provider": "xai",
            "model": "grok-imagine-video",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：產品攝影。",
                "include_image": True,
                "include_video": True,
                "candidate_budget": 1,
                "video_budget": 1,
            }
        )
    )

    policy = payload["generation_strategy"]["feedback_policy"]
    assert policy["provider_recovery_mode"] == "video_fallback_unavailable"
    assert policy["provider_retry_budget"] == 0
    assert policy["provider_failure_context"] == {
        "provider_failure_classes": {"quota_exceeded": 2},
        "provider_error_codes": {"personal-team-blocked:spending-limit": 2},
    }
    assert policy["applied_action_types"] == ["configure_video_fallback_provider"]


@pytest.mark.asyncio
async def test_visual_package_skips_video_when_runtime_policy_reports_missing_video_fallback(
    monkeypatch,
    tmp_path,
):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "configure_video_fallback_provider",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "confidence": 0.9,
                                "source": "live_quality_burn",
                                "provider_failure_classes": {"quota_exceeded": 3},
                                "provider_error_codes": {
                                    "personal-team-blocked:spending-limit": 2,
                                    "provider_quarantined": 1,
                                },
                                "video_fallback_diagnostics": [
                                    {
                                        "failed_provider": "xai",
                                        "failed_provider_family": "xai",
                                        "registered_provider_names": ["fal", "xai"],
                                        "available_provider_names": [],
                                        "unavailable_provider_names": ["fal"],
                                        "fallback_provider_names": [],
                                        "setup_actions": [
                                            {
                                                "provider": "fal",
                                                "env_vars": ["FAL_KEY"],
                                                "configured_env_vars": [],
                                                "missing_env_vars": ["FAL_KEY"],
                                                "post_setup": "",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    video_calls = []

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **_kwargs: {
            "success": True,
            "image": str(image),
            "provider": "codex",
            "model": "gpt-image-fallback",
            "vision_observation": {
                "face_quality": 0.9,
                "fashion_material_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        },
    )
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: video_calls.append(kwargs)
        or {
            "success": True,
            "video": str(tmp_path / "should-not-exist.mp4"),
            "provider": "xai",
            "model": "grok-imagine-video",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：產品攝影。",
                "include_image": True,
                "include_video": True,
                "candidate_budget": 1,
                "video_budget": 1,
            }
        )
    )

    assert video_calls == []
    assert payload["images"] == [str(image)]
    assert payload["videos"] == []
    video_payload = payload["generation_payloads"]["video"]
    assert video_payload["error_type"] == "provider_quarantined"
    assert video_payload["provider_quarantine"]["no_video_fallback_available"] is True
    assert video_payload["provider_quarantine"]["video_fallback_diagnostic"] == {
        "failed_provider": "xai",
        "failed_provider_family": "xai",
        "registered_provider_names": ["fal", "xai"],
        "available_provider_names": [],
        "unavailable_provider_names": ["fal"],
        "fallback_provider_names": [],
        "setup_actions": [
            {
                "provider": "fal",
                "env_vars": ["FAL_KEY"],
                "configured_env_vars": [],
                "missing_env_vars": ["FAL_KEY"],
                "post_setup": "",
            }
        ],
    }
    assert video_payload["failure"]["failure_class"] == "quota_exceeded"
    assert payload["generation_strategy"]["feedback_policy"]["provider_recovery_mode"] == (
        "video_fallback_unavailable"
    )


@pytest.mark.asyncio
async def test_visual_package_falls_back_to_available_image_provider_after_quota_block(
    monkeypatch,
    tmp_path,
):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "fallback.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        if kwargs.get("_provider") == "codex":
            return {
                "success": True,
                "image": str(image),
                "provider": "codex",
                "model": "gpt-image-fallback",
                "vision_observation": {
                    "face_quality": 0.9,
                    "fashion_material_quality": 0.9,
                    "visual_appeal": 0.9,
                    "composition": 0.9,
                },
            }
        return {
            "success": False,
            "error_type": "api_error",
            "error": (
                'xAI image gen failed (403): {"code":"personal-team-blocked:spending-limit",'
                '"error":"You have run out of credits or need a Grok subscription."}'
            ),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "_available_image_provider_fallbacks",
        lambda failed_provider=None: ["codex"],
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：產品攝影。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(calls) == 2
    assert calls[1]["_provider"] == "codex"
    image_payloads = payload["generation_payloads"]["image"]
    assert image_payloads[0]["failure"]["failure_class"] == "quota_exceeded"
    assert image_payloads[1]["success"] is True
    assert image_payloads[1]["provider"] == "codex"
    assert image_payloads[1]["provider_fallback"] == {
        "from_provider": "xai",
        "to_provider": "codex",
        "failure_class": "quota_exceeded",
        "retry_of": 0,
    }
    assert payload["images"] == [str(image)]


@pytest.mark.asyncio
async def test_visual_package_falls_back_to_available_video_provider_after_quota_block(
    monkeypatch,
    tmp_path,
):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "source.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    video = tmp_path / "fallback.mp4"
    video.write_bytes(b"fallback video")
    video_calls = []

    def fake_generate_image(**kwargs):
        return {
            "success": True,
            "image": str(image),
            "provider": "codex",
            "model": "gpt-image-fallback",
            "vision_observation": {
                "face_quality": 0.9,
                "fashion_material_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
            },
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        if kwargs.get("_provider") == "fal":
            return {
                "success": True,
                "video": str(video),
                "provider": "fal",
                "model": "fallback-video",
            }
        return {
            "success": False,
            "error_type": "api_error",
            "error": (
                'xAI video gen failed (403): {"code":"personal-team-blocked:spending-limit",'
                '"error":"You have run out of credits or need a Grok subscription."}'
            ),
            "provider": "xai",
            "model": "grok-imagine-video",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)
    monkeypatch.setattr(
        visual_package_tool,
        "_available_video_provider_fallbacks",
        lambda failed_provider=None: ["fal"],
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：產品攝影。",
                "include_image": True,
                "include_video": True,
                "candidate_budget": 1,
                "video_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(video_calls) == 2
    assert video_calls[1]["_provider"] == "fal"
    video_payloads = payload["generation_payloads"]["video"]
    assert video_payloads[0]["failure"]["failure_class"] == "quota_exceeded"
    assert video_payloads[1]["success"] is True
    assert video_payloads[1]["provider"] == "fal"
    assert video_payloads[1]["provider_fallback"] == {
        "from_provider": "xai",
        "to_provider": "fal",
        "failure_class": "quota_exceeded",
        "retry_of": 0,
    }
    assert payload["videos"] == [str(video)]


@pytest.mark.asyncio
async def test_visual_package_stops_image_candidates_after_quota_without_fallback(
    monkeypatch,
    tmp_path,
):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": False,
            "error_type": "api_error",
            "error": (
                'xAI image gen failed (403): {"code":"personal-team-blocked:spending-limit",'
                '"error":"You have run out of credits or need a Grok subscription."}'
            ),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "_available_image_provider_fallbacks",
        lambda failed_provider=None: [],
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出四張圖片：產品攝影。",
                "include_image": True,
                "include_video": False,
                "candidate_budget": 4,
            }
        )
    )

    assert len(image_calls) == 1
    assert payload["success"] is False
    assert payload["images"] == []
    image_payload = payload["generation_payloads"]["image"]
    assert image_payload["failure"]["failure_class"] == "quota_exceeded"
    assert image_payload["recovery"]["reason"] == "provider_quota_or_subscription_required"


@pytest.mark.asyncio
async def test_visual_package_skips_xai_video_when_quota_known_and_no_video_fallback(
    monkeypatch,
    tmp_path,
):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "fallback.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    image_calls = []
    video_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        if kwargs.get("_provider") == "codex":
            return {
                "success": True,
                "image": str(image),
                "provider": "codex",
                "model": "gpt-image-fallback",
                "vision_observation": {
                    "face_quality": 0.9,
                    "fashion_material_quality": 0.9,
                    "visual_appeal": 0.9,
                    "composition": 0.9,
                },
            }
        return {
            "success": False,
            "error_type": "api_error",
            "error": (
                'xAI image gen failed (403): {"code":"personal-team-blocked:spending-limit",'
                '"error":"You have run out of credits or need a Grok subscription."}'
            ),
            "provider": "xai-oauth",
            "model": "grok-imagine-image-quality",
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": False,
            "error_type": "api_error",
            "error": "xAI video should have been quarantined before this call",
            "provider": "xai",
            "model": "grok-imagine-video-1.5",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)
    monkeypatch.setattr(
        visual_package_tool,
        "_available_image_provider_fallbacks",
        lambda failed_provider=None: ["codex"],
    )
    monkeypatch.setattr(
        visual_package_tool,
        "_available_video_provider_fallbacks",
        lambda failed_provider=None: [],
    )
    monkeypatch.setattr(
        visual_package_tool,
        "_active_video_provider_identity",
        lambda: ("xai", "grok-imagine-video-1.5"),
        raising=False,
    )
    monkeypatch.setattr(
        visual_package_tool,
        "_video_provider_fallback_diagnostic",
        lambda failed_provider=None: {
            "failed_provider": "xai",
            "failed_provider_family": "xai",
            "registered_provider_names": ["fal", "xai"],
            "available_provider_names": [],
            "unavailable_provider_names": ["fal"],
            "fallback_provider_names": [],
            "setup_actions": [
                    {
                        "provider": "fal",
                        "env_vars": ["FAL_KEY"],
                        "configured_env_vars": [],
                        "missing_env_vars": ["FAL_KEY"],
                        "post_setup": "",
                    }
            ],
        },
        raising=False,
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：產品攝影。",
                "include_image": True,
                "include_video": True,
                "candidate_budget": 1,
                "video_budget": 1,
            }
        )
    )

    assert len(image_calls) == 2
    assert video_calls == []
    video_payload = payload["generation_payloads"]["video"]
    assert video_payload["success"] is False
    assert video_payload["error_type"] == "provider_quarantined"
    assert video_payload["provider_quarantine"]["no_video_fallback_available"] is True
    assert video_payload["provider_quarantine"]["video_fallback_diagnostic"] == {
        "failed_provider": "xai",
        "failed_provider_family": "xai",
        "registered_provider_names": ["fal", "xai"],
        "available_provider_names": [],
        "unavailable_provider_names": ["fal"],
        "fallback_provider_names": [],
        "setup_actions": [
                {
                    "provider": "fal",
                    "env_vars": ["FAL_KEY"],
                    "configured_env_vars": [],
                    "missing_env_vars": ["FAL_KEY"],
                    "post_setup": "",
                }
        ],
    }
    assert video_payload["failure"]["failure_class"] == "quota_exceeded"
    assert payload["videos"] == []


def test_visual_package_video_fallback_diagnostic_lists_unavailable_setup_actions(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("FAL_KEY", raising=False)

    class FakeVideoProvider:
        def __init__(self, name, available, setup_schema):
            self.name = name
            self._available = available
            self._setup_schema = setup_schema

        def is_available(self):
            return self._available

        def get_setup_schema(self):
            return self._setup_schema

    monkeypatch.setattr(
        visual_package_tool,
        "_video_provider_registry_snapshot",
        lambda: [
            FakeVideoProvider(
                "fal",
                False,
                {
                    "env_vars": [{"key": "FAL_KEY"}],
                    "post_setup": "",
                },
            ),
            FakeVideoProvider(
                "xai",
                True,
                {
                    "env_vars": [],
                    "post_setup": "xai_grok",
                },
            ),
        ],
        raising=False,
    )

    diagnostic = visual_package_tool._video_provider_fallback_diagnostic(failed_provider="xai")

    assert diagnostic == {
        "failed_provider": "xai",
        "failed_provider_family": "xai",
        "registered_provider_names": ["fal", "xai"],
        "available_provider_names": [],
        "unavailable_provider_names": ["fal"],
        "fallback_provider_names": [],
        "setup_actions": [
            {
                "provider": "fal",
                "env_vars": ["FAL_KEY"],
                "configured_env_vars": [],
                "missing_env_vars": ["FAL_KEY"],
                "post_setup": "",
            }
        ],
    }


@pytest.mark.asyncio
async def test_visual_package_ignores_failed_self_validation_next_actions(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": False,
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "prefer_quality_repair_retry",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：霧黑鋼筆。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert payload["generation_strategy"]["feedback_policy"]["quality_repair_mode"] == "default"
    assert payload["generation_strategy"]["feedback_policy"]["policy_sources"] == ["feedback_loop"]
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == []


@pytest.mark.asyncio
async def test_visual_package_applies_runtime_policy_from_failed_self_validation(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": False,
                "runtime_policy": {
                    "success": True,
                    "decision": "apply_next_run",
                    "generated_at": "2026-06-22T08:00:00+00:00",
                    "expires_at": "2999-06-23T08:00:00+00:00",
                    "next_actions": [
                        {
                            "type": "increase_candidate_budget",
                            "requires_human_feedback": False,
                            "activation_status": "next_run",
                            "source": "live_quality_trends",
                            "max_candidate_budget": 4,
                        },
                        {
                            "type": "prefer_image_first_video",
                            "requires_human_feedback": False,
                            "activation_status": "next_run",
                            "source": "live_quality_trends",
                        },
                    ],
                },
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "prefer_quality_repair_retry",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "source": "unsafe_failed_report_fallback",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一段短影片：霧黑鋼筆。", "include_video": True}
        )
    )

    assert payload["success"] is True
    assert len(image_calls) == 4
    assert payload["generation_strategy"]["candidate_budget"] == 4
    assert payload["generation_strategy"]["candidate_budget_source"] == "live_quality_trends"
    assert payload["generation_strategy"]["image_first_for_video"] is True
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == [
        "increase_candidate_budget",
        "prefer_image_first_video",
    ]
    assert payload["generation_strategy"]["feedback_policy"]["quality_repair_mode"] == "default"


@pytest.mark.asyncio
async def test_visual_package_ignores_expired_runtime_policy(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "runtime_policy": {
                    "success": True,
                    "decision": "apply_next_run",
                    "generated_at": "2000-01-01T00:00:00+00:00",
                    "expires_at": "2000-01-02T00:00:00+00:00",
                    "next_actions": [
                        {
                            "type": "increase_candidate_budget",
                            "requires_human_feedback": False,
                            "activation_status": "next_run",
                            "source": "live_quality_trends",
                            "max_candidate_budget": 4,
                        }
                    ],
                },
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "increase_candidate_budget",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "source": "stale_fallback_should_not_apply",
                                "max_candidate_budget": 4,
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片：霧黑鋼筆。",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(calls) == 1
    assert payload["generation_strategy"]["candidate_budget"] == 1
    assert payload["generation_strategy"]["feedback_policy"]["policy_sources"] == ["feedback_loop"]
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == []


@pytest.mark.asyncio
async def test_visual_package_ignores_suspended_runtime_policy_without_fallback(
    monkeypatch,
    tmp_path,
):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    latest_report = tmp_path / "visual" / "self_validation" / "latest.json"
    latest_report.parent.mkdir(parents=True)
    latest_report.write_text(
        json.dumps(
            {
                "success": True,
                "runtime_policy": {
                    "success": False,
                    "decision": "suspend_quality_regressed",
                    "reason": "runtime_policy_quality_regressed",
                    "generated_at": "2026-06-22T08:00:00+00:00",
                    "expires_at": "2999-06-23T08:00:00+00:00",
                    "next_actions": [],
                    "suspended_action_types": [
                        "increase_candidate_budget",
                        "prefer_image_first_video",
                    ],
                    "privacy_safe": True,
                },
                "automation": {
                    "self_improvement": {
                        "next_actions": [
                            {
                                "type": "increase_candidate_budget",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "source": "quality_regressed_fallback_should_not_apply",
                                "max_candidate_budget": 4,
                            },
                            {
                                "type": "prefer_image_first_video",
                                "requires_human_feedback": False,
                                "activation_status": "next_run",
                                "source": "quality_regressed_fallback_should_not_apply",
                            },
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    image = tmp_path / "image.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_video",
        lambda **kwargs: {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video",
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一段短影片：霧黑鋼筆。",
                "include_video": True,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert len(image_calls) == 1
    assert payload["generation_strategy"]["candidate_budget"] == 1
    assert payload["generation_strategy"]["feedback_policy"]["policy_sources"] == ["feedback_loop"]
    assert payload["generation_strategy"]["feedback_policy"]["applied_action_types"] == []


@pytest.mark.asyncio
async def test_visual_package_carries_provider_vision_observation_into_judgment(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.2,
                "visual_appeal": 0.3,
                "composition": 0.7,
                "stocking_quality": 0.2,
            },
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：時尚寫真。", "include_video": False, "candidate_budget": 1}
        )
    )

    quality_judgments = [
        row
        for row in VisualAttemptLedger(default_visual_ledger_path())._list("visual_judgments")
        if row["judge_name"] == "visual_quality_judge"
    ]

    assert payload["success"] is False
    assert payload["delivery_gate"]["image"]["allowed"] is False
    assert quality_judgments[0]["details"]["quality_issues"] == [
        "subject_not_attractive",
        "not_beautiful",
        "not_glamorous",
        "stockings_bad",
        "face_unnatural",
    ]


@pytest.mark.asyncio
async def test_visual_package_blocks_delivery_when_active_learning_fails_closed(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "bad-image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.2,
                "visual_appeal": 0.2,
                "composition": 0.2,
                "stocking_quality": 0.2,
            },
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：時尚寫真。", "include_video": False, "candidate_budget": 1}
        )
    )

    assert payload["success"] is False
    assert payload["package_status"] == "failed"
    assert payload["error_type"] == "delivery_gate_blocked"
    assert payload["error"] == "visual candidate blocked by active-learning delivery gate"
    assert payload["images"] == []
    assert payload["delivery_metadata"]["selected_visual_artifact_ids"] == []
    assert payload["learning"]["active_learning"]["image"]["action"] == "fail_closed"
    assert payload["delivery_gate"]["image"]["allowed"] is False
    assert payload["delivery_gate"]["image"]["reason"] == "active_learning_fail_closed"
    assert payload["delivery_gate"]["image"]["quality_issues"] == [
        "subject_not_attractive",
        "not_beautiful",
        "composition_bad",
        "stockings_bad",
    ]


@pytest.mark.asyncio
async def test_visual_package_repairs_blocked_image_before_delivery(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    bad_image = tmp_path / "bad-image.png"
    good_image = tmp_path / "good-image.png"
    bad_image.write_bytes(_ONE_PIXEL_PNG)
    good_image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "success": True,
                "image": str(bad_image),
                "provider": "fixture",
                "model": "image",
                "vision_observation": {
                    "face_quality": 0.2,
                    "visual_appeal": 0.2,
                    "composition": 0.2,
                    "stocking_quality": 0.2,
                },
            }
        return {
            "success": True,
            "image": str(good_image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：時尚寫真。", "include_video": False, "candidate_budget": 1}
        )
    )

    assert payload["success"] is True
    assert payload["images"] == [str(good_image)]
    assert len(calls) == 2
    assert "Quality repair pass" in calls[1]["prompt"]
    assert payload["delivery_gate"]["image"]["allowed"] is True
    assert payload["delivery_gate"]["image"]["repair_attempted"] is True
    assert payload["delivery_gate"]["image"]["repaired_from"]["reason"] == "active_learning_fail_closed"
    assert len(payload["delivery_metadata"]["selected_visual_artifact_ids"]) == 1
    attempts = VisualAttemptLedger(default_visual_ledger_path())._list("visual_attempts")
    repair_attempts = [
        attempt
        for attempt in attempts
        if isinstance(attempt.get("metadata"), dict)
        and isinstance(attempt["metadata"].get("quality_repair"), dict)
    ]
    assert len(repair_attempts) == 1
    assert repair_attempts[0]["metadata"]["quality_repair"]["reason"] == "active_learning_fail_closed"


@pytest.mark.asyncio
async def test_visual_package_uses_reference_role_repair_for_identity_drift(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ref1 = tmp_path / "ref1.png"
    ref2 = tmp_path / "ref2.png"
    bad_image = tmp_path / "bad-reference-transfer.png"
    good_image = tmp_path / "good-reference-transfer.png"
    for image in (ref1, ref2, bad_image, good_image):
        image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "success": True,
                "image": str(bad_image),
                "provider": "fixture",
                "model": "image",
                "vision_observation": {
                    "reference_adherence": 0.42,
                    "character_identity_adherence": 0.2,
                    "pose_composition_adherence": 0.88,
                    "wardrobe_adherence": 0.25,
                    "face_quality": 0.8,
                    "visual_appeal": 0.82,
                    "composition": 0.86,
                    "stocking_quality": 0.8,
                    "artifact_defects": ["reference_identity_drift"],
                },
            }
        return {
            "success": True,
            "image": str(good_image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "reference_adherence": 0.92,
                "character_identity_adherence": 0.92,
                "pose_composition_adherence": 0.9,
                "wardrobe_adherence": 0.9,
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
                "artifact_defects": [],
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
                "include_video": False,
                "candidate_budget": 1,
                "attachments": [str(ref1), str(ref2)],
                "reference_binding": {
                    "reference_order": [
                        {"index": 1, "role_hint": "character_identity"},
                        {"index": 2, "role_hint": "pose_composition"},
                    ]
                },
            }
        )
    )

    assert payload["success"] is True
    assert payload["images"] == [str(good_image)]
    assert len(calls) == 2
    assert "Reference role repair pass" in calls[1]["prompt"]
    assert "Use ref 1 only for character_identity" in calls[1]["prompt"]
    assert "Use ref 2 only for pose_composition" in calls[1]["prompt"]
    assert "Do not copy identity, face, hair, wardrobe, color palette, or character traits" in calls[1]["prompt"]
    assert payload["delivery_gate"]["image"]["allowed"] is True
    assert payload["delivery_gate"]["image"]["repair_attempted"] is True
    assert payload["delivery_gate"]["image"]["repaired_from"]["reason"] == "active_learning_review_required"
    assert payload["delivery_gate"]["image"]["repaired_from"]["quality_issues"] == ["reference_identity_drift"]
    attempts = VisualAttemptLedger(default_visual_ledger_path())._list("visual_attempts")
    repair_attempts = [
        attempt
        for attempt in attempts
        if isinstance(attempt.get("metadata"), dict)
        and isinstance(attempt["metadata"].get("quality_repair"), dict)
    ]
    assert len(repair_attempts) == 1
    assert repair_attempts[0]["metadata"]["quality_repair"]["reason"] == "active_learning_review_required"


@pytest.mark.asyncio
async def test_visual_package_adds_candidate_for_low_preference_dimension_before_repair(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    bad_image = tmp_path / "bad-preference-dimensions.png"
    good_image = tmp_path / "good-preference-dimensions.png"
    bad_image.write_bytes(_ONE_PIXEL_PNG)
    good_image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "success": True,
                "image": str(bad_image),
                "provider": "fixture",
                "model": "image",
                "vision_observation": {
                    "subject_quality": 0.4,
                    "face_quality": 0.4,
                    "glamour_impact": 0.8,
                    "fashion_material_quality": 0.4,
                    "pose_composition": 0.4,
                    "composition": 0.95,
                    "visual_appeal": 0.95,
                    "confidence": 0.9,
                },
            }
        return {
            "success": True,
            "image": str(good_image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "subject_quality": 0.92,
                "face_quality": 0.9,
                "glamour_impact": 0.86,
                "fashion_material_quality": 0.88,
                "pose_composition": 0.84,
                "composition": 0.95,
                "visual_appeal": 0.95,
                "confidence": 0.94,
            },
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        visual_package_tool,
        "compute_provider_reliability",
        lambda _ledger, request_id: {
            "fixture:image": {
                "generation_success_rate": 1.0,
                "delivery_success_rate": 1.0,
                "attempt_count": 10,
            }
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：時尚寫真。", "include_video": False, "candidate_budget": 1}
        )
    )

    assert payload["success"] is True
    assert payload["images"] == [str(good_image)]
    assert len(calls) == 2
    assert "Additional candidate pass" in calls[1]["prompt"]
    assert "Quality repair pass" not in calls[1]["prompt"]
    assert payload["delivery_gate"]["image"]["allowed"] is True
    assert payload["delivery_gate"]["image"]["candidate_budget_escalated"] is True
    assert payload["delivery_gate"]["image"]["escalated_from"]["reason"] == "pre_slack_preference_dimension_low"
    assert payload["delivery_gate"]["image"]["escalated_from"]["preference_dimension_fit"] < 0.5
    assert set(payload["delivery_gate"]["image"]["escalated_from"]["quality_issues"]) >= {
        "subject_not_attractive",
        "stockings_bad",
        "composition_bad",
    }
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path

    attempts = VisualAttemptLedger(default_visual_ledger_path())._list("visual_attempts")
    escalation_attempts = [
        attempt
        for attempt in attempts
        if isinstance(attempt.get("metadata"), dict)
        and isinstance(attempt["metadata"].get("candidate_escalation"), dict)
    ]
    assert len(escalation_attempts) == 1
    assert escalation_attempts[0]["metadata"]["candidate_escalation"]["reason"] == (
        "pre_slack_preference_dimension_low"
    )


@pytest.mark.asyncio
async def test_visual_package_does_not_block_product_delivery_on_portrait_only_issues(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "product.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
            "vision_observation": {
                "face_quality": 0.2,
                "visual_appeal": 0.8,
                "composition": 0.8,
                "stocking_quality": 0.2,
            },
        },
    )

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "Clean product photography of a matte black fountain pen on white paper.",
                "include_video": False,
                "candidate_budget": 1,
            }
        )
    )

    assert payload["success"] is True
    assert payload["images"] == [str(image)]
    assert payload["delivery_gate"]["image"]["allowed"] is True
    assert payload["delivery_gate"]["image"]["quality_issues"] == []
    assert payload["delivery_gate"]["image"]["ignored_quality_issues"] == []


def test_score_candidates_carries_quality_issues_into_reward(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from tools import visual_package_tool

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="redacted",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
        metadata={"intent_signature": "visig_demo"},
    )
    candidate = {
        "attempt_id": "vat_demo",
        "artifact_id": "var_demo",
        "artifact_path": str(tmp_path / "candidate.png"),
        "kind": "image",
        "provider": "fixture",
        "model": "image",
        "content_hash": "hash-demo",
        "hard_gate": {"passed": True, "delivery_possible": True},
        "scores": {"resolution": 0.9, "aspect_match": 0.9, "final_score": 0.9},
    }

    monkeypatch.setattr(
        visual_package_tool,
        "build_artifact_observation",
        lambda _candidate: {
            "visual_appeal": 0.8,
            "composition": 0.8,
            "confidence": 0.8,
            "artifact_defects": ["face_quality_low"],
        },
    )

    visual_package_tool._score_candidates(
        ledger,
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        modality="image",
        has_reference_image=False,
        candidates=[candidate],
    )

    assert candidate["quality_issues"] == ["subject_not_attractive"]
    assert candidate["reward"]["dimensions"]["user_preference_fit"] <= 0.5


def test_score_candidates_uses_candidate_vision_observation_for_aesthetic_issues(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from tools import visual_package_tool

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="redacted",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
        metadata={"intent_signature": "visig_demo"},
    )
    candidate = {
        "attempt_id": "vat_demo",
        "artifact_id": "var_demo",
        "artifact_path": str(tmp_path / "candidate.png"),
        "kind": "image",
        "provider": "fixture",
        "model": "image",
        "content_hash": "hash-demo",
        "hard_gate": {"passed": True, "delivery_possible": True},
        "scores": {"resolution": 0.9, "aspect_match": 0.9, "final_score": 0.9},
        "vision_observation": {
            "reference_adherence": 0.85,
            "face_quality": 0.2,
            "visual_appeal": 0.35,
            "composition": 0.7,
            "stocking_quality": 0.2,
        },
    }

    visual_package_tool._score_candidates(
        ledger,
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        modality="image",
        has_reference_image=False,
        candidates=[candidate],
    )

    judgment = ledger._list("visual_judgments")[0]
    assert candidate["quality_issues"] == [
        "subject_not_attractive",
        "not_beautiful",
        "not_glamorous",
        "stockings_bad",
        "face_unnatural",
    ]
    assert candidate["reward"]["dimensions"]["aesthetic_fit"] < 0.5
    assert judgment["metadata"]["judge_sources"]["aesthetic_fit"] == "vision"


def test_score_candidates_carries_preference_dimensions_into_reward(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from tools import visual_package_tool

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="redacted",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
        metadata={"intent_signature": "visig_demo"},
    )
    candidate = {
        "attempt_id": "vat_demo",
        "artifact_id": "var_demo",
        "artifact_path": str(tmp_path / "candidate.png"),
        "kind": "image",
        "provider": "fixture",
        "model": "image",
        "content_hash": "hash-demo",
        "hard_gate": {"passed": True, "delivery_possible": True},
        "scores": {"resolution": 0.9, "aspect_match": 0.9, "final_score": 0.9},
        "vision_observation": {
            "subject_quality": 0.34,
            "face_quality": 0.28,
            "fashion_material_quality": 0.31,
            "pose_composition": 0.42,
            "composition": 0.7,
            "visual_appeal": 0.7,
        },
    }

    visual_package_tool._score_candidates(
        ledger,
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        modality="image",
        has_reference_image=False,
        candidates=[candidate],
    )

    judgment = ledger._list("visual_judgments")[0]
    assert candidate["preference_dimensions"] == {
        "subject_beauty": 0.34,
        "face_naturalness": 0.28,
        "glamour_impact": 0.7,
        "fashion_material_quality": 0.31,
        "pose_composition": 0.42,
    }
    assert candidate["reward"]["dimensions"]["preference_dimension_fit"] < 0.5
    assert judgment["details"]["preference_dimensions"] == candidate["preference_dimensions"]


def test_score_candidates_runs_inline_vision_before_reward(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from tools import visual_package_tool

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="redacted",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
        metadata={"intent_signature": "visig_demo"},
    )
    candidate = {
        "attempt_id": "vat_demo",
        "artifact_id": "var_demo",
        "artifact_path": str(tmp_path / "candidate.png"),
        "kind": "image",
        "provider": "xai",
        "model": "grok-imagine-image-quality",
        "content_hash": "hash-demo",
        "hard_gate": {"passed": True, "delivery_possible": True},
        "scores": {"resolution": 0.9, "aspect_match": 0.9, "final_score": 0.9},
    }

    visual_package_tool._score_candidates(
        ledger,
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        modality="image",
        has_reference_image=False,
        candidates=[candidate],
        inline_vision_judge=True,
        vision_analyzer=lambda _candidate: {
            "analysis": {
                "face_quality": 0.2,
                "visual_appeal": 0.35,
                "composition": 0.7,
                "stocking_quality": 0.2,
            }
        },
    )

    judgment = ledger._list("visual_judgments")[0]
    assert candidate["quality_issues"] == [
        "subject_not_attractive",
        "not_beautiful",
        "not_glamorous",
        "stockings_bad",
        "face_unnatural",
    ]
    assert candidate["reward"]["dimensions"]["aesthetic_fit"] < 0.5
    assert judgment["metadata"]["vision_observation_source"] == "inline_vision_judge"
    assert judgment["details"]["evidence"]["source"] == "inline_vision_judge"


def test_score_candidates_records_inline_vision_provider_failure(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from tools import visual_package_tool

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="redacted",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
        metadata={"intent_signature": "visig_demo"},
    )
    candidate = {
        "attempt_id": "vat_demo",
        "artifact_id": "var_demo",
        "artifact_path": str(tmp_path / "candidate.png"),
        "kind": "image",
        "provider": "openai-codex",
        "model": "gpt-image-2",
        "content_hash": "hash-demo",
        "hard_gate": {"passed": True, "delivery_possible": True},
        "scores": {"resolution": 0.9, "aspect_match": 0.9, "final_score": 0.9},
    }

    visual_package_tool._score_candidates(
        ledger,
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        modality="image",
        has_reference_image=False,
        candidates=[candidate],
        inline_vision_judge=True,
        vision_analyzer=lambda _candidate: {
            "success": False,
            "error": (
                "Error code: 403 - {'code':'personal-team-blocked:spending-limit',"
                "'error':'You have run out of credits or need a Grok subscription.'}"
            ),
            "analysis": "Insufficient credits or payment required.",
        },
    )

    judgment = ledger._list("visual_judgments")[0]
    assert candidate["vision_observation_source"] == "inline_vision_unavailable"
    assert judgment["metadata"]["vision_observation_source"] == "inline_vision_unavailable"
    assert judgment["metadata"]["vision_failure"]["failure_class"] == "quota_exceeded"
    assert judgment["details"]["evidence"]["source"] == "inline_vision_unavailable"
    assert judgment["details"]["vision_failure"]["failure_class"] == "quota_exceeded"


def test_score_candidates_disables_inline_vision_after_quota_failure(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from tools import visual_package_tool

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="redacted",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
        metadata={"intent_signature": "visig_demo"},
    )
    candidates = [
        {
            "attempt_id": f"vat_demo_{index}",
            "artifact_id": f"var_demo_{index}",
            "artifact_path": str(tmp_path / f"candidate-{index}.png"),
            "kind": "image",
            "provider": "xai",
            "model": "grok-imagine-image-quality",
            "content_hash": f"hash-demo-{index}",
            "hard_gate": {"passed": True, "delivery_possible": True},
            "scores": {"resolution": 0.9, "aspect_match": 0.9, "final_score": 0.9},
        }
        for index in range(3)
    ]
    analyzer_calls = []

    def quota_blocked_analyzer(candidate):
        analyzer_calls.append(candidate["artifact_id"])
        return {
            "success": False,
            "error": (
                "Error code: 403 - {'code':'personal-team-blocked:spending-limit',"
                "'error':'You have run out of credits or need a Grok subscription.'}"
            ),
            "analysis": "Insufficient credits or payment required.",
        }

    visual_package_tool._score_candidates(
        ledger,
        request_id=request_id,
        intent_signature="visig_demo",
        strategy_signature="vstrat_demo",
        modality="image",
        has_reference_image=False,
        candidates=candidates,
        inline_vision_judge=True,
        vision_analyzer=quota_blocked_analyzer,
    )

    judgments = ledger._list("visual_judgments")
    assert analyzer_calls == ["var_demo_0"]
    assert candidates[0]["vision_observation_source"] == "inline_vision_unavailable"
    assert candidates[0]["vision_failure"]["failure_class"] == "quota_exceeded"
    assert candidates[1]["vision_observation_source"] == "artifact_observation"
    assert candidates[2]["vision_observation_source"] == "artifact_observation"
    assert judgments[0]["metadata"]["vision_failure"]["failure_class"] == "quota_exceeded"
    assert "vision_failure" not in judgments[1]["metadata"]
    assert "vision_failure" not in judgments[2]["metadata"]


def test_inline_vision_prompt_requests_preference_dimension_metrics():
    from tools.visual_package_tool import INLINE_VISION_JUDGE_PROMPT

    assert "subject_quality" in INLINE_VISION_JUDGE_PROMPT
    assert "face_quality" in INLINE_VISION_JUDGE_PROMPT
    assert "glamour_impact" in INLINE_VISION_JUDGE_PROMPT
    assert "fashion_material_quality" in INLINE_VISION_JUDGE_PROMPT
    assert "pose_composition" in INLINE_VISION_JUDGE_PROMPT
    assert "character_identity_adherence" in INLINE_VISION_JUDGE_PROMPT
    assert "pose_composition_adherence" in INLINE_VISION_JUDGE_PROMPT
    assert "reference_identity_drift" in INLINE_VISION_JUDGE_PROMPT
    assert "guide_artifact_contamination" in INLINE_VISION_JUDGE_PROMPT
    assert "melted_or_wavy_contours" in INLINE_VISION_JUDGE_PROMPT
    assert "distorted_anatomy" in INLINE_VISION_JUDGE_PROMPT


def test_reference_aware_inline_vision_uses_contact_sheet(monkeypatch, tmp_path):
    from tools import vision_tools
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ref1 = tmp_path / "ref1.png"
    ref2 = tmp_path / "ref2.png"
    candidate = tmp_path / "candidate.png"
    from PIL import Image

    for image, color in (
        (ref1, (240, 240, 255)),
        (ref2, (255, 240, 220)),
        (candidate, (230, 255, 240)),
    ):
        Image.new("RGB", (32, 48), color).save(image)

    seen = {}

    async def fake_vision_analyze_tool(image_url, user_prompt, model=None):
        seen["image_url"] = image_url
        seen["user_prompt"] = user_prompt
        seen["model"] = model
        return json.dumps(
            {
                "success": True,
                "analysis": {
                    "reference_adherence": 0.4,
                    "character_identity_adherence": 0.2,
                    "pose_composition_adherence": 0.9,
                    "wardrobe_adherence": 0.3,
                    "artifact_defects": ["reference_identity_drift"],
                },
            }
        )

    monkeypatch.setattr(vision_tools, "vision_analyze_tool", fake_vision_analyze_tool)

    result = visual_package_tool.analyze_candidate_with_vision_tool(
        {
            "artifact_path": str(candidate),
            "input_artifacts": [
                {"index": 1, "role_hint": "character_identity", "uri": str(ref1)},
                {"index": 2, "role_hint": "pose_composition", "uri": str(ref2)},
            ],
        }
    )

    assert result["analysis"]["character_identity_adherence"] == 0.2
    assert seen["image_url"] != str(candidate)
    assert Path(seen["image_url"]).is_file()
    assert "ref 1 role: character_identity" in seen["user_prompt"]
    assert "ref 2 role: pose_composition" in seen["user_prompt"]
    assert "candidate output" in seen["user_prompt"]


def test_delivery_gate_blocks_missing_reference_role_evidence_for_reference_request():
    from tools import visual_package_tool

    gate = visual_package_tool._delivery_gate_decision(
        {"action": "ask_user"},
        {
            "artifact_id": "var_demo",
            "quality_issues": ["reference_role_evidence_missing"],
            "reward": {"dimensions": {"preference_dimension_fit": 0.9}},
        },
        prompt="把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
    )

    assert gate["allowed"] is False
    assert gate["reason"] == "active_learning_review_required"
    assert gate["quality_issues"] == ["reference_role_evidence_missing"]


def test_delivery_gate_blocks_detected_reference_identity_drift():
    from tools import visual_package_tool

    gate = visual_package_tool._delivery_gate_decision(
        {"action": "ask_user"},
        {
            "artifact_id": "var_demo",
            "quality_issues": ["reference_identity_drift"],
            "reward": {"dimensions": {"preference_dimension_fit": 0.92}},
        },
        prompt="把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
    )

    assert gate["allowed"] is False
    assert gate["reason"] == "active_learning_review_required"
    assert gate["quality_issues"] == ["reference_identity_drift"]


def test_package_error_describes_reference_role_gate_without_internal_label():
    from tools import visual_package_tool

    package_error = visual_package_tool._package_error(
        success=False,
        delivery_gate={
            "image": {
                "allowed": False,
                "reason": "active_learning_review_required",
                "quality_issues": ["reference_identity_drift"],
                "repair_attempted": True,
            }
        },
    )

    assert package_error["error_type"] == "delivery_gate_blocked"
    assert package_error["error"] == "reference role transfer did not pass visual quality validation after repair"


def test_delivery_recovery_summary_tracks_blocked_candidate_without_delivery(tmp_path):
    from tools import visual_package_tool

    blocked_image = tmp_path / "blocked.png"
    blocked_image.write_bytes(_ONE_PIXEL_PNG)

    summary = visual_package_tool._delivery_recovery_summary(
        requested_image=True,
        wants_video=False,
        selected_images=[],
        selected_videos=[],
        generation_payloads={
            "image": {
                "success": True,
                "image": str(blocked_image),
                "provider": "xai",
                "model": "grok-imagine-image-quality",
            }
        },
        delivery_gate={
            "image": {
                "allowed": False,
                "reason": "active_learning_review_required",
                "quality_issues": ["reference_identity_drift"],
                "repair_attempted": True,
            }
        },
    )

    assert summary["status"] == "blocked"
    assert summary["blocked_modalities"] == ["image"]
    assert summary["generated_candidate_available"] is True
    assert summary["actions"] == [
        {
            "modality": "image",
            "reason": "active_learning_review_required",
            "quality_issues": ["reference_identity_drift"],
            "repair_attempted": True,
            "candidate_budget_escalated": False,
            "polish_pass_attempted": False,
            "recommended_action": "rerun_reference_repair_or_grok_web_polish",
        }
    ]
    assert summary["deliver_rejected_artifact"] is False


@pytest.mark.asyncio
async def test_visual_package_inline_vision_changes_ranked_image_selection(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(_ONE_PIXEL_PNG + b"first")
    second.write_bytes(_ONE_PIXEL_PNG + b"second")
    images = [first, second]

    def fake_generate_image(**kwargs):
        image = images.pop(0)
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        }

    def fake_inline_vision(candidate):
        if str(candidate["artifact_path"]).endswith("first.png"):
            return {
                "analysis": {
                    "face_quality": 0.2,
                    "visual_appeal": 0.3,
                    "composition": 0.65,
                    "stocking_quality": 0.2,
                }
            }
        return {
            "analysis": {
                "face_quality": 0.9,
                "visual_appeal": 0.9,
                "composition": 0.9,
                "stocking_quality": 0.9,
            }
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "analyze_candidate_with_vision_tool", fake_inline_vision)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出兩張圖片：時尚寫真。",
                "include_video": False,
                "candidate_budget": 2,
            }
        )
    )

    assert payload["success"] is True
    assert payload["images"] == [str(second)]
    assert (
        payload["rankings"]["image"]["ranked_artifact_ids"][0]
        == payload["delivery_metadata"]["selected_visual_artifact_ids"][0]
    )


@pytest.mark.asyncio
async def test_visual_package_hardens_video_prompt_without_stretch(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "portrait.png"
    video = tmp_path / "video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    video_calls = []

    def fake_probe_media_reference(ref):
        return SimpleNamespace(
            sha256=f"hash:{ref}",
            is_stable=True,
            freshness_status="fresh",
            local_path=str(ref) if str(ref).startswith("/") else None,
            mime_type="image/png" if str(ref).endswith(".png") else "video/mp4",
            bytes=10,
            width=720 if str(ref).endswith(".png") else 0,
            height=1280 if str(ref).endswith(".png") else 0,
        )

    monkeypatch.setattr(visual_package_tool, "probe_media_reference", fake_probe_media_reference)
    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **kwargs: {"success": True, "image": str(image), "provider": "fixture", "model": "image"},
    )

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {"success": True, "video": str(video), "provider": "fixture", "model": "video"}

    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "image plus video", "aspect_ratio": "16:9"}
        )
    )

    assert payload["success"] is True
    assert video_calls[0]["aspect_ratio"] == "9:16"
    assert "natural real-time motion" in video_calls[0]["prompt"]
    assert "not slow motion" in video_calls[0]["prompt"]
    assert "visible subject, camera, or environmental movement" in video_calls[0]["prompt"]


@pytest.mark.asyncio
async def test_visual_package_video_uses_one_ranked_source_image_not_candidate_grid(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    images = []
    for index in range(4):
        image = tmp_path / f"candidate-{index}.png"
        image.write_bytes(_ONE_PIXEL_PNG + str(index).encode())
        images.append(image)
    video = tmp_path / "selected-video.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_calls = []
    video_calls = []

    def fake_generate_image(**kwargs):
        image = images[len(image_calls)]
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        }

    def fake_inline_vision(candidate):
        if str(candidate["artifact_path"]).endswith("candidate-2.png"):
            return {
                "analysis": {
                    "face_quality": 0.95,
                    "visual_appeal": 0.95,
                    "composition": 0.95,
                }
            }
        return {
            "analysis": {
                "face_quality": 0.45,
                "visual_appeal": 0.45,
                "composition": 0.45,
            }
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "analyze_candidate_with_vision_tool", fake_inline_vision)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產生一段影片：時尚寫真，動態鏡頭。",
                "include_image": False,
                "include_video": True,
                "candidate_budget": 4,
                "video_budget": 1,
                "inline_vision_judge": True,
            }
        )
    )

    assert len(image_calls) == 4
    assert len(video_calls) == 1
    assert video_calls[0]["image_url"] == str(images[2])
    assert video_calls[0]["source_media"]["reference_count"] == 1
    assert video_calls[0]["source_media"]["references"] == [str(images[2])]
    assert payload["images"] == []
    assert payload["videos"] == [str(video)]
    assert payload["generation_strategy"]["video_source_image"] == str(images[2])
    assert payload["generation_strategy"]["video_source_image_count"] == 1
    assert payload["generation_strategy"]["video_source_policy"] == "single_ranked_selected_image"
    quality_run = payload["delivery_metadata"]["visual_quality_run"]
    assert quality_run["summary"]["video_source_image_count"] == 1
    assert quality_run["self_review"]["single_video_source_image"] is True


@pytest.mark.asyncio
async def test_visual_package_skips_ranked_candidate_grid_when_clean_video_source_exists(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    grid_image = tmp_path / "candidate-grid.png"
    clean_image = tmp_path / "candidate-clean.png"
    repair_image = tmp_path / "repair-should-not-run.png"
    video = tmp_path / "selected-video.mp4"
    for image in (grid_image, clean_image, repair_image):
        image.write_bytes(_ONE_PIXEL_PNG + image.name.encode())
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    image_sequence = [grid_image, clean_image, repair_image]
    image_calls = []
    video_calls = []

    def fake_generate_image(**kwargs):
        image = image_sequence[len(image_calls)]
        image_calls.append(kwargs)
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        }

    def fake_inline_vision(candidate):
        artifact_path = str(candidate["artifact_path"])
        if artifact_path == str(grid_image):
            return {
                "analysis": {
                    "visual_appeal": 0.98,
                    "composition": 0.98,
                    "confidence": 0.95,
                    "artifact_defects": ["candidate_grid_layout"],
                }
            }
        return {
            "analysis": {
                "visual_appeal": 0.7,
                "composition": 0.7,
                "confidence": 0.8,
            }
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(video),
            "provider": "fixture",
            "model": "video",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "analyze_candidate_with_vision_tool", fake_inline_vision)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產生一段影片：時尚寫真，動態鏡頭。",
                "include_image": False,
                "include_video": True,
                "candidate_budget": 2,
                "video_budget": 1,
                "inline_vision_judge": True,
            }
        )
    )

    assert len(image_calls) == 2
    assert len(video_calls) == 1
    assert video_calls[0]["image_url"] == str(clean_image)
    assert video_calls[0]["source_media"]["reference_count"] == 1
    assert video_calls[0]["source_media"]["references"] == [str(clean_image)]
    assert payload["success"] is True
    assert payload["videos"] == [str(video)]
    assert payload["generation_strategy"]["video_source_image"] == str(clean_image)
    assert payload["generation_strategy"]["video_source_image_count"] == 1
    assert payload["generation_strategy"]["video_source_policy"] == "single_ranked_selected_image"
    assert payload["delivery_gate"]["image"]["allowed"] is True
    assert payload["delivery_gate"]["image"]["reason"] == "delivery_allowed"


@pytest.mark.asyncio
async def test_visual_package_retries_empty_image_response_before_ranking(monkeypatch, tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import default_visual_ledger_path
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "retry-image.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    calls = []

    def fake_generate_image(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "success": False,
                "error": "empty_response",
                "provider": "fixture",
                "model": "image",
            }
        return {
            "success": True,
            "image": str(image),
            "provider": "fixture",
            "model": "image",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {"prompt": "請產出一張圖片：霧黑鋼筆。", "include_video": False, "candidate_budget": 1}
        )
    )

    assert len(calls) == 2
    assert payload["success"] is True
    assert payload["images"] == [str(image)]
    assert payload["generation_payloads"]["image"][0]["failure"]["failure_class"] == "empty_response"
    assert payload["generation_payloads"]["image"][0]["recovery"]["decision"] == "retry"
    assert payload["generation_payloads"]["image"][1]["retry_of"] == 0
    attempts = VisualAttemptLedger(default_visual_ledger_path())._list("visual_attempts")
    assert attempts[0]["metadata"]["failure"]["failure_class"] == "empty_response"
    assert attempts[1]["metadata"]["retry_of"] == 0


def test_visual_package_attempt_metadata_preserves_quota_surface():
    from tools.visual_package_tool import _attempt_metadata

    metadata = _attempt_metadata(
        {
            "provider": "grok-web-imagine",
            "provider_family": "grok_web",
            "quota_source": "consumer_web",
            "fallback_attempted": True,
            "fallback_from_provider": "xai",
            "fallback_reason": "xai_api_quota_exceeded",
            "primary_failure_class": "quota_exceeded",
        }
    )

    assert metadata["provider_family"] == "grok_web"
    assert metadata["quota_source"] == "consumer_web"
    assert metadata["fallback_attempted"] is True
    assert metadata["fallback_from_provider"] == "xai"
    assert metadata["fallback_reason"] == "xai_api_quota_exceeded"
    assert metadata["primary_failure_class"] == "quota_exceeded"


@pytest.mark.asyncio
async def test_visual_package_retries_transient_image_failure_before_image_first_video(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "retry-image.png"
    video = tmp_path / "retry-video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"video")
    image_calls = []
    video_calls = []

    def fake_generate_image(**kwargs):
        image_calls.append(kwargs)
        if len(image_calls) == 1:
            return {
                "success": False,
                "error_type": "api_error",
                "error": (
                    "xAI image generation failed (503): upstream connect error or disconnect/reset "
                    "before headers. retried and the latest reset reason: remote connection failure, "
                    "transport failure reason: delayed connect error: Connection refused"
                ),
                "provider": "xai-oauth",
                "model": "grok-imagine-image-quality",
            }
        return {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        }

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        return {
            "success": True,
            "video": str(video),
            "provider": "xai",
            "model": "grok-imagine-video-1.5",
        }

    monkeypatch.setattr(visual_package_tool, "generate_image", fake_generate_image)
    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一段產品影片：霧黑鋼筆放在白紙上，柔和窗光。",
                "include_image": False,
                "include_video": True,
                "candidate_budget": 1,
                "video_budget": 1,
            }
        )
    )

    assert len(image_calls) == 2
    assert video_calls[0]["image_url"] == str(image)
    assert payload["success"] is True
    assert payload["images"] == []
    assert payload["videos"] == [str(video)]
    assert payload["generation_payloads"]["image"][0]["failure"]["failure_class"] == "provider_unavailable"
    assert payload["generation_payloads"]["image"][1]["retry_of"] == 0
    assert payload["generation_strategy"]["image_first_for_video"] is True
    assert payload["generation_strategy"]["video_source_image"] == str(image)


@pytest.mark.asyncio
async def test_visual_package_retries_transient_video_timeout(monkeypatch, tmp_path):
    from tools import visual_package_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "image.png"
    video = tmp_path / "retry-video.mp4"
    image.write_bytes(_ONE_PIXEL_PNG)
    video.write_bytes(b"video")
    video_calls = []

    monkeypatch.setattr(
        visual_package_tool,
        "generate_image",
        lambda **_kwargs: {
            "success": True,
            "image": str(image),
            "provider": "xai",
            "model": "grok-imagine-image-quality",
        },
    )

    def fake_generate_video(**kwargs):
        video_calls.append(kwargs)
        if len(video_calls) == 1:
            return {
                "success": False,
                "error_type": "timeout",
                "error": "xAI video generation failed: ReadTimeout",
                "provider": "xai",
                "model": "grok-imagine-video-1.5",
            }
        return {
            "success": True,
            "video": str(video),
            "provider": "xai",
            "model": "grok-imagine-video-1.5",
        }

    monkeypatch.setattr(visual_package_tool, "generate_video", fake_generate_video)

    payload = json.loads(
        await visual_package_tool._handle_visual_package_generate(
            {
                "prompt": "請產出一張圖片和一段影片：霧黑鋼筆放在白紙上，柔和窗光。",
                "include_image": True,
                "include_video": True,
                "candidate_budget": 1,
                "video_budget": 1,
                "duration": 8,
            }
        )
    )

    assert len(video_calls) == 2
    assert video_calls[1]["duration"] == 4
    assert payload["success"] is True
    assert payload["videos"] == [str(video)]
    assert payload["generation_payloads"]["video"][0]["failure"]["failure_class"] == "timeout"
    assert payload["generation_payloads"]["video"][0]["recovery"]["decision"] == "retry"
    assert payload["generation_payloads"]["video"][1]["retry_of"] == 0


def test_retry_generation_payload_records_retry_failure_with_exhausted_recovery():
    from tools.visual_package_tool import _retry_generation_payload

    retry_payload = _retry_generation_payload(
        generator=lambda **_kwargs: {
            "success": False,
            "error_type": "api_error",
            "error": "xAI image generation failed (503): Connection refused",
            "provider": "xai-oauth",
            "model": "grok-imagine-image-quality",
        },
        payload={"success": False, "error": "empty_response"},
        base_kwargs={"prompt": "product image", "aspect_ratio": "1:1"},
        request={
            "prompt": "product image",
            "arguments": {"prompt": "product image", "aspect_ratio": "1:1"},
        },
        retry_budget_remaining=1,
        retry_of=0,
    )

    assert retry_payload is not None
    assert retry_payload["retry_of"] == 0
    assert retry_payload["failure"]["failure_class"] == "provider_unavailable"
    assert retry_payload["recovery"]["decision"] == "fail"
    assert retry_payload["recovery"]["reason"] == "retry_budget_exhausted"


def _list_rows(ledger, table):
    return ledger._list(table)
