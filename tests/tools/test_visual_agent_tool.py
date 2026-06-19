from __future__ import annotations

import json

import pytest

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


def test_visual_agent_generate_tool_is_registered():
    import tools.visual_agent_tool  # noqa: F401
    from tools.registry import registry

    entry = registry.get_entry("visual_agent_generate")
    assert entry is not None
    assert entry.toolset == "image_gen"
    assert entry.is_async is True
    assert "visual production agent" in entry.schema["description"]
