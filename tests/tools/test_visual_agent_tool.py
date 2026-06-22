import json

import pytest


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
    assert captured["candidate_budget"] == 1
    assert captured["candidate_budget_source"] == "planner_default"
    assert captured["video_budget"] == 1


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
    assert captured["candidate_budget"] == 1
    assert captured["candidate_budget_source"] == "planner_default"


def test_visual_agent_generate_is_registered():
    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()

    assert "visual_agent_generate" in registry._tools
    entry = registry._tools["visual_agent_generate"]
    assert entry.is_async is True
    assert entry.toolset == "image_gen"
    assert "draw/anime/character art" in entry.schema["description"]
    assert "storyboard/multi-shot" in entry.schema["description"]
