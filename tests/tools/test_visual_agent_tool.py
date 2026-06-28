import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@pytest.mark.asyncio
async def test_visual_agent_generate_plans_natural_image_plus_video_request(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps(
            {
                "success": True,
                "images": ["/tmp/current.png"],
                "videos": ["/tmp/current.mp4"],
            }
        )

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請用這張 reference 產出一張圖片和一段 6 秒影片",
            "attachments": ["/tmp/ref.png"],
        }
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["visual_agent_plan"]["tool_name"] == "visual_package_generate"
    assert payload["visual_agent_plan"]["reason"] == "image_plus_video_request"
    assert captured["prompt"] == "請用這張 reference 產出一張圖片和一段 6 秒影片"
    assert captured["attachments"] == ["/tmp/ref.png"]
    assert captured["include_image"] is True
    assert captured["include_video"] is True
    assert captured["candidate_budget"] == 2
    assert captured["candidate_budget_source"] == "planner_default"
    assert captured["video_budget"] == 1


@pytest.mark.asyncio
async def test_visual_agent_generate_materializes_data_uri_attachment(monkeypatch, tmp_path):
    from tools import visual_agent_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    captured = {}
    data_uri = "data:image/png;base64," + base64.b64encode(_ONE_PIXEL_PNG).decode("ascii")

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請用這張 reference 產出一張圖片",
            "attachments": [data_uri],
        }
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    attachment = captured["attachments"][0]
    assert not attachment.startswith("data:image")
    assert attachment.startswith(str(tmp_path / "cache" / "visual-agent-attachments"))
    assert Path(attachment).read_bytes() == _ONE_PIXEL_PNG


@pytest.mark.asyncio
async def test_visual_agent_generate_binds_ref_indices_to_visible_upload_order(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
            "attachments": ["/tmp/upload-first-character.png", "/tmp/upload-second-pose.png"],
        }
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert captured["attachments"] == [
        "/tmp/upload-first-character.png",
        "/tmp/upload-second-pose.png",
    ]
    assert "first uploaded image in the user's visible attachment order" in captured["prompt"]
    binding = captured["reference_binding"]
    assert binding == {
        "mode": "ordered_references",
        "reference_order_source": "user_visible_upload_order",
        "role_policy": "derive_from_user_prompt",
        "reference_order": [
            {
                "index": 1,
                "role_hint": "character_identity",
                "attachment": "/tmp/upload-first-character.png",
            },
            {
                "index": 2,
                "role_hint": "pose_composition",
                "attachment": "/tmp/upload-second-pose.png",
            },
        ],
    }


@pytest.mark.asyncio
async def test_visual_agent_generate_derives_roles_from_prompt_not_ref_defaults(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "ref1 和 ref2 都是人物，ref3 是服裝，請融合成一張圖片",
            "attachments": [
                "/tmp/upload-first-person.png",
                "/tmp/upload-second-person.png",
                "/tmp/upload-third-clothes.png",
            ],
        }
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert captured["attachments"] == [
        "/tmp/upload-first-person.png",
        "/tmp/upload-second-person.png",
        "/tmp/upload-third-clothes.png",
    ]
    assert "Do not assume fixed roles" in captured["prompt"]
    binding = captured["reference_binding"]
    assert binding["reference_order_source"] == "user_visible_upload_order"
    assert "character_reference" not in binding
    assert "pose_reference" not in binding
    assert "character_reference_index" not in binding
    assert "pose_reference_index" not in binding
    assert binding["reference_order"] == [
        {
            "index": 1,
            "role_hint": "character_identity",
            "attachment": "/tmp/upload-first-person.png",
        },
        {
            "index": 2,
            "role_hint": "character_identity",
            "attachment": "/tmp/upload-second-person.png",
        },
        {
            "index": 3,
            "role_hint": "wardrobe",
            "attachment": "/tmp/upload-third-clothes.png",
        },
    ]


@pytest.mark.asyncio
async def test_visual_agent_generate_routes_text_only_video_to_image_first(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": [], "videos": ["/tmp/current.mp4"]})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {"prompt": "幫我產生一段 6 秒時尚短片，主體是霧黑鋼筆"}
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["visual_agent_plan"]["reason"] == "text_to_video_image_first_request"
    assert captured["include_image"] is False
    assert captured["include_video"] is True
    assert captured["candidate_budget"] == 2
    assert captured["candidate_budget_source"] == "planner_default"
    assert captured["video_budget"] == 1
    assert captured["duration"] == 6
    assert payload["images"] == []


@pytest.mark.asyncio
async def test_visual_agent_generate_passes_storyboard_contract_for_multishot_video(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": [], "videos": ["/tmp/current.mp4"]})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {"prompt": "請做一支 3 段分鏡的連貫產品影片：霧黑鋼筆放在白紙上，柔和窗光。"}
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["visual_agent_plan"]["reason"] == "storyboard_video_request"
    assert captured["include_image"] is False
    assert captured["include_video"] is True
    assert captured["storyboard"]["shot_count"] == 3
    assert captured["storyboard"]["source_image_policy"] == "one_ranked_image_per_shot"
    assert payload["visual_agent_plan"]["arguments"]["storyboard"]["composition_target"] == "single_coherent_video"


@pytest.mark.asyncio
async def test_visual_agent_generate_accepts_friendly_draw_character_prompt(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {"prompt": "幫我畫一位銀髮高冷美少女角色，乾淨背景"}
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["visual_agent_plan"]["reason"] == "image_request"
    assert captured["include_image"] is True
    assert captured["include_video"] is False
    assert captured["candidate_budget"] == 2
    assert captured["candidate_budget_source"] == "planner_default"


@pytest.mark.asyncio
async def test_visual_agent_generate_routes_grok_imagine_request_to_xai_provider(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請使用 Grok Imagine 固定這位角色，產出不同姿勢的精緻圖片",
            "attachments": ["/tmp/ref.png"],
        }
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert captured["attachments"] == ["/tmp/ref.png"]
    assert captured["image_provider"] == "xai"
    assert payload["visual_agent_plan"]["arguments"]["image_provider"] == "xai"


@pytest.mark.asyncio
async def test_visual_agent_generate_passes_default_xai_media_provider_contract(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = await visual_agent_tool._handle_visual_agent_generate({"prompt": "幫我產出一張圖片"})
    payload = json.loads(raw)

    assert captured["image_provider"] == "xai"
    assert captured["image_provider_source"] == "visual_agent_default"
    assert payload["visual_agent_provider_contract"]["visual_agent_llm_provider"] == "xai-oauth"
    assert payload["visual_agent_provider_contract"]["base_llm_model"] == "gpt-5.5"


@pytest.mark.asyncio
async def test_visual_agent_generate_rejects_prompt_disclosure_without_regenerating(monkeypatch):
    from tools import visual_agent_tool

    async def fake_visual_package_generate(args, **kwargs):
        raise AssertionError("prompt disclosure must not dispatch visual generation")

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {"prompt": "請給我剛剛產圖用的 prompt"}
    )
    payload = json.loads(raw)

    assert payload["error"] == "visual_agent_generate is for image/video generation, not prompt disclosure"
    assert payload["request_type"] == "visual_prompt_disclosure"


@pytest.mark.asyncio
async def test_visual_agent_generate_uses_grok_planner_for_direct_handoff(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fake_call_llm(**kwargs):
        captured["llm_call"] = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"visual_prompt": "更大膽但保留原意的 xAI 視覺提示詞"})
                    )
                )
            ]
        )

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fake_call_llm)

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請產出一張圖片",
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
            "visual_agent_handoff_mode": "pre_llm_direct",
        }
    )
    payload = json.loads(raw)

    assert captured["llm_call"]["provider"] == "xai-oauth"
    assert captured["llm_call"]["model"] == "grok-4.3"
    assert captured["prompt"] == "更大膽但保留原意的 xAI 視覺提示詞"
    assert captured["visual_agent_original_prompt"] == "請產出一張圖片"
    assert payload["visual_agent_llm_plan"]["status"] == "planned"
    assert payload["visual_agent_llm_plan"]["provider"] == "xai-oauth"


@pytest.mark.asyncio
async def test_visual_agent_grok_planner_receives_reference_images_and_roles(monkeypatch, tmp_path):
    from tools import visual_agent_tool

    ref1 = tmp_path / "ref1.png"
    ref2 = tmp_path / "ref2.png"
    ref1.write_bytes(_ONE_PIXEL_PNG)
    ref2.write_bytes(_ONE_PIXEL_PNG)
    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured["package_args"] = dict(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fake_call_llm(**kwargs):
        captured["llm_call"] = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "visual_prompt": (
                                    "Use the character identity from ref 1: silver hair, pale face, "
                                    "white cloak and purple outfit. Apply the concrete pose from ref 2: "
                                    "low-angle seated composition, one leg raised toward the camera, "
                                    "the other leg bent back on the sofa. Do not copy ref 2 identity."
                                )
                            }
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fake_call_llm)

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
            "attachments": [str(ref1), str(ref2)],
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
            "visual_agent_handoff_mode": "pre_llm_direct",
        }
    )
    payload = json.loads(raw)

    content = captured["llm_call"]["messages"][1]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert "ref 1: character_identity" in content[0]["text"]
    assert "ref 2: pose_composition" in content[0]["text"]
    image_parts = [part for part in content if part.get("type") == "image_url"]
    assert len(image_parts) == 2
    assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert image_parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "Do not copy ref 2 identity" in captured["package_args"]["prompt"]
    assert payload["visual_agent_llm_plan"]["image_input_count"] == 2


@pytest.mark.asyncio
async def test_visual_agent_generate_falls_back_when_grok_planner_fails(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fail_call_llm(**kwargs):
        raise RuntimeError("planner down")

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fail_call_llm)

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "請產出一張圖片",
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
        }
    )
    payload = json.loads(raw)

    assert captured["prompt"] == "請產出一張圖片"
    assert payload["visual_agent_llm_plan"]["status"] == "fallback"
    assert payload["visual_agent_llm_plan"]["reason"] == "RuntimeError"


@pytest.mark.asyncio
async def test_visual_agent_grok_planner_fallback_builds_provider_ready_reference_prompt(monkeypatch, tmp_path):
    from tools import visual_agent_tool

    ref1 = tmp_path / "ref1.png"
    ref2 = tmp_path / "ref2.png"
    ref1.write_bytes(_ONE_PIXEL_PNG)
    ref2.write_bytes(_ONE_PIXEL_PNG)
    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/current.png"], "videos": []})

    def fail_call_llm(**kwargs):
        raise RuntimeError("planner down")

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fake_visual_package_generate,
    )
    monkeypatch.setattr("agent.auxiliary_client.call_llm", fail_call_llm)

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {
            "prompt": "把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可",
            "attachments": [str(ref1), str(ref2)],
            "visual_agent_llm_provider": "xai-oauth",
            "visual_agent_llm_model": "grok-4.3",
            "reference_binding": {
                "reference_order": [
                    {"index": 1, "role_hint": "character_identity", "attachment": str(ref1)},
                    {"index": 2, "role_hint": "pose_composition", "attachment": str(ref2)},
                ]
            },
        }
    )
    payload = json.loads(raw)

    prompt = captured["prompt"]
    assert "Provider-ready visual prompt" in prompt
    assert "Reference mapping" in prompt
    assert "ref 1 = character_identity" in prompt
    assert "ref 2 = pose_composition" in prompt
    assert "Role constraints" in prompt
    assert "Do not copy identity, face, hair, wardrobe, color palette, or styling from pose refs" in prompt
    assert "Negative constraints" in prompt
    assert payload["visual_agent_llm_plan"]["status"] == "fallback_deterministic_prompt"
    assert payload["visual_agent_llm_plan"]["prompt_changed"] is True


def test_visual_agent_generate_is_registered():
    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()

    assert "visual_agent_generate" in registry._tools
    entry = registry._tools["visual_agent_generate"]
    assert entry.is_async is True
    assert entry.toolset == "image_gen"
    assert "draw/anime/character art" in entry.schema["description"]
    assert "storyboard/multi-shot" in entry.schema["description"]


def test_visual_agent_schema_says_grok_reference_uses_tool_not_text_only():
    from tools.visual_agent_tool import VISUAL_AGENT_SCHEMA

    description = VISUAL_AGENT_SCHEMA["description"]

    assert "Grok Imagine/xAI" in description
    assert "reference images" in description
    assert "not text-to-image only" in description
