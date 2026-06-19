from __future__ import annotations

import json

import pytest

from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.mission_planner import plan_visual_mission
from agent.visual.agent_mode.types import VisualArtifactRole


@pytest.mark.asyncio
async def test_visual_agent_generate_runs_image_video_package(monkeypatch):
    from tools import visual_agent_tool

    def fake_generate_image_candidates(mission, graph):
        graph.add_asset(
            role=VisualArtifactRole.GENERATED_IMAGE,
            artifact_id="var_image",
            local_path="/tmp/image.png",
        )
        return {
            "success": True,
            "candidates": [{"artifact_id": "var_image", "score": 0.9, "image": "/tmp/image.png"}],
            "candidate_count": 1,
            "failure_count": 0,
        }

    def fake_select_image_candidates(graph, candidates, max_selected=2):
        graph.add_asset(
            role=VisualArtifactRole.SELECTED_IMAGE,
            artifact_id="var_image",
            local_path="/tmp/image.png",
        )
        return ["var_image"]

    def fake_build_video_clips(mission, graph):
        graph.add_asset(
            role=VisualArtifactRole.GENERATED_VIDEO,
            artifact_id="var_video",
            local_path="/tmp/video.mp4",
        )
        return {"success": True, "clips": [{"artifact_id": "var_video"}]}

    monkeypatch.setattr(
        visual_agent_tool,
        "generate_image_candidates",
        fake_generate_image_candidates,
    )
    monkeypatch.setattr(
        visual_agent_tool,
        "select_image_candidates",
        fake_select_image_candidates,
    )
    monkeypatch.setattr(
        visual_agent_tool,
        "build_video_clips",
        fake_build_video_clips,
    )

    payload = json.loads(
        await visual_agent_tool._handle_visual_agent_generate(
            {
                "prompt": "Create one image and one video.",
                "attachments": ["/tmp/ref.png"],
                "autonomy_level": 2,
            }
        )
    )

    assert payload["success"] is True
    assert payload["mission_id"].startswith("vms_")
    assert payload["selected_image_artifact_ids"] == ["var_image"]
    assert payload["selected_video_artifact_ids"] == ["var_video"]
    assert payload["images"] == ["/tmp/image.png"]
    assert payload["videos"] == ["/tmp/video.mp4"]
    assert payload["delivery_metadata"]["selected_visual_artifact_ids"] == [
        "var_image",
        "var_video",
    ]


@pytest.mark.asyncio
async def test_visual_agent_generate_natural_chinese_image_video_request_defaults_to_package(monkeypatch):
    from tools import visual_agent_tool

    def fake_generate_image_candidates(mission, graph):
        graph.add_asset(
            role=VisualArtifactRole.GENERATED_IMAGE,
            artifact_id="var_pen_image",
            local_path="/tmp/pen.png",
        )
        return {
            "success": True,
            "candidates": [
                {"artifact_id": "var_pen_image", "score": 0.91, "image": "/tmp/pen.png"}
            ],
            "candidate_count": 1,
            "failure_count": 0,
        }

    def fake_build_video_clips(mission, graph):
        graph.add_asset(
            role=VisualArtifactRole.GENERATED_VIDEO,
            artifact_id="var_pen_video",
            local_path="/tmp/pen.mp4",
        )
        return {"success": True, "clips": [{"artifact_id": "var_pen_video"}]}

    monkeypatch.setattr(
        visual_agent_tool,
        "generate_image_candidates",
        fake_generate_image_candidates,
    )
    monkeypatch.setattr(
        visual_agent_tool,
        "build_video_clips",
        fake_build_video_clips,
    )

    payload = json.loads(
        await visual_agent_tool._handle_visual_agent_generate(
            {
                "prompt": "請幫我產出一張圖片和一段影片：一支霧黑鋼筆放在白紙上，柔和窗光，乾淨產品攝影。"
            }
        )
    )

    assert payload["success"] is True
    assert payload["selected_image_artifact_ids"] == ["var_pen_image"]
    assert payload["selected_video_artifact_ids"] == ["var_pen_video"]
    assert payload["images"] == ["/tmp/pen.png"]
    assert payload["videos"] == ["/tmp/pen.mp4"]


def test_visual_agent_generate_tool_is_registered():
    import tools.visual_agent_tool  # noqa: F401
    from tools.registry import registry

    entry = registry.get_entry("visual_agent_generate")
    assert entry is not None
    assert entry.toolset == "image_gen"
    assert entry.is_async is True
    assert "visual production agent" in entry.schema["description"]
    assert "Do not require the user to mention this tool name" in entry.schema["description"]
    assert entry.schema["parameters"]["properties"]["autonomy_level"]["default"] == 2


@pytest.mark.asyncio
async def test_generate_image_candidates_keeps_best_qc_failed_candidate(monkeypatch):
    from tools import image_mission_tool
    from tools import visual_agent_tool

    async def fake_run_image_generation_mission(**kwargs):
        return {
            "success": False,
            "error": "No generated candidate passed visual QC.",
            "error_type": "qc_failed",
            "best_candidate": {
                "image": "/tmp/best-near-miss.png",
                "qc": {"score": 72},
                "provider": "xai",
                "model": "grok-imagine-image-quality",
            },
        }

    monkeypatch.setattr(
        image_mission_tool,
        "run_image_generation_mission",
        fake_run_image_generation_mission,
    )
    mission = plan_visual_mission("Create one product image.", autonomy_level=2)
    graph = VisualAssetGraph(mission_id=mission.mission_id)

    result = await visual_agent_tool.generate_image_candidates(mission, graph)

    assert result["success"] is True
    assert result["candidate_count"] == 1
    assert result["failure_count"] == 1
    assert result["candidates"][0]["image"] == "/tmp/best-near-miss.png"
    assert result["candidates"][0]["score"] == 0.72
    assert result["candidates"][0]["metadata"]["qc_failed_fallback"] is True
    assert graph.selected_artifact_ids(VisualArtifactRole.GENERATED_IMAGE)


@pytest.mark.asyncio
async def test_generate_image_candidates_uses_standalone_still_brief_for_visual_package(monkeypatch):
    from tools import image_mission_tool
    from tools import visual_agent_tool

    seen_prompts = []

    async def fake_run_image_generation_mission(**kwargs):
        seen_prompts.append(kwargs["prompt"])
        return {
            "success": True,
            "image": "/tmp/mug.png",
            "visual_artifact_id": "var_mug",
            "visual_request_id": "vrq_mug",
            "visual_attempt_id": "vat_mug",
        }

    monkeypatch.setattr(
        image_mission_tool,
        "run_image_generation_mission",
        fake_run_image_generation_mission,
    )
    mission = plan_visual_mission(
        "Create one clean product-style image and one short video of a minimalist white ceramic mug on a wooden desk.",
        autonomy_level=2,
    )
    graph = VisualAssetGraph(mission_id=mission.mission_id)

    result = await visual_agent_tool.generate_image_candidates(mission, graph)

    assert result["success"] is True
    assert seen_prompts
    prompt = seen_prompts[0].lower()
    assert "standalone still image" in prompt
    assert "minimalist white ceramic mug" in prompt
    assert "short video" not in prompt
    assert "split-screen" in prompt
