from __future__ import annotations

from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.clip_builder import build_video_clips
from agent.visual.agent_mode.mission_planner import plan_visual_mission
from agent.visual.agent_mode.types import VisualArtifactRole


def test_build_video_clips_uses_selected_images_only():
    mission = plan_visual_mission("Create images and one video.", autonomy_level=2)
    graph = VisualAssetGraph(mission_id=mission.mission_id)
    generated = graph.add_asset(
        role=VisualArtifactRole.GENERATED_IMAGE,
        artifact_id="var_generated",
        local_path="/tmp/generated.png",
    )
    selected = graph.add_asset(
        role=VisualArtifactRole.SELECTED_IMAGE,
        artifact_id="var_selected",
        local_path="/tmp/selected.png",
    )
    graph.link(generated.asset_id, selected.asset_id)
    calls = []

    def fake_video(args):
        calls.append(args)
        return {
            "success": True,
            "video": "/tmp/clip.mp4",
            "visual_artifact_id": "var_video",
            "aspect_ratio": "9:16",
        }

    result = build_video_clips(mission, graph, generate_video=fake_video)

    assert result["success"] is True
    assert calls[0]["image_url"] == "/tmp/selected.png"
    assert calls[0]["prompt"] == mission.output_goal
    assert graph.selected_artifact_ids(VisualArtifactRole.GENERATED_VIDEO) == ["var_video"]


def test_build_video_clips_passes_explicit_aspect_ratio_only_when_requested():
    mission = plan_visual_mission("Create one image and one video.", autonomy_level=2)
    mission.constraints["aspect_ratio"] = "9:16"
    graph = VisualAssetGraph(mission_id=mission.mission_id)
    graph.add_asset(
        role=VisualArtifactRole.SELECTED_IMAGE,
        artifact_id="var_selected",
        local_path="/tmp/selected.png",
    )
    calls = []

    def fake_video(args):
        calls.append(args)
        return {"success": False, "error": "dry_run"}

    build_video_clips(mission, graph, generate_video=fake_video)

    assert calls[0]["aspect_ratio"] == "9:16"
