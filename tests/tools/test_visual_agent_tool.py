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
    assert captured["video_budget"] == 1


@pytest.mark.asyncio
async def test_visual_agent_generate_routes_text_only_video_to_image_first(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **kwargs):
        captured.update(args)
        return json.dumps({"success": True, "images": ["/tmp/source.png"], "videos": ["/tmp/current.mp4"]})

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
    assert captured["include_image"] is True
    assert captured["include_video"] is True
    assert captured["candidate_budget"] == 2
    assert captured["video_budget"] == 1
    assert captured["duration"] == 6
    assert payload["images"] == ["/tmp/source.png"]


def test_visual_agent_generate_is_registered():
    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()

    assert "visual_agent_generate" in registry._tools
    entry = registry._tools["visual_agent_generate"]
    assert entry.is_async is True
    assert entry.toolset == "image_gen"
