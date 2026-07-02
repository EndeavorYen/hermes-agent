import json

import pytest


@pytest.mark.asyncio
async def test_visual_agent_generate_plans_natural_image_plus_video_request(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **_kwargs):
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
    assert payload["visual_agent_provider_contract"]["visual_agent_llm_provider"] == "xai-oauth"
    assert captured["prompt"] == "請用這張 reference 產出一張圖片和一段 6 秒影片"
    assert captured["attachments"] == ["/tmp/ref.png"]
    assert captured["include_image"] is True
    assert captured["include_video"] is True
    assert captured["candidate_budget"] == 2
    assert captured["candidate_budget_source"] == "planner_default"
    assert captured["video_budget"] == 1
    assert captured["duration"] == 6


@pytest.mark.asyncio
async def test_visual_agent_generate_routes_text_only_video_to_image_first(monkeypatch):
    from tools import visual_agent_tool

    captured = {}

    async def fake_visual_package_generate(args, **_kwargs):
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
async def test_visual_agent_generate_rejects_prompt_disclosure_without_dispatch(monkeypatch):
    from tools import visual_agent_tool

    async def fail_visual_package_generate(args, **_kwargs):
        raise AssertionError("prompt disclosure must not dispatch visual generation")

    monkeypatch.setattr(
        visual_agent_tool,
        "_handle_visual_package_generate",
        fail_visual_package_generate,
    )

    raw = await visual_agent_tool._handle_visual_agent_generate(
        {"prompt": "請給我剛剛產圖用的 prompt"}
    )
    payload = json.loads(raw)

    assert payload["error"] == (
        "visual_agent_generate is for image/video generation, not prompt disclosure"
    )
    assert payload["request_type"] == "visual_prompt_disclosure"


def test_visual_agent_generate_is_registered_and_core_visible():
    from tools.registry import discover_builtin_tools, registry
    from toolsets import resolve_toolset

    discover_builtin_tools()

    entry = registry.get_entry("visual_agent_generate")
    assert entry is not None
    assert entry.toolset == "image_gen"
    assert entry.is_async is True

    image_gen_tools = set(resolve_toolset("image_gen"))
    assert "visual_agent_generate" in image_gen_tools
    assert "visual_package_generate" in image_gen_tools

    cli_tools = set(resolve_toolset("hermes-cli"))
    assert "visual_agent_generate" in cli_tools
    assert "visual_package_generate" in cli_tools
