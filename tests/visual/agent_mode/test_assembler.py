from __future__ import annotations

from agent.visual.agent_mode.assembler import assemble_visual_package
from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.mission_planner import plan_visual_mission
from agent.visual.agent_mode.types import VisualArtifactRole


def test_assembler_returns_selected_image_and_video_artifacts():
    mission = plan_visual_mission("Create images and one video.", autonomy_level=2)
    graph = VisualAssetGraph(mission_id=mission.mission_id)
    graph.add_asset(
        role=VisualArtifactRole.SELECTED_IMAGE,
        artifact_id="var_image",
        local_path="/tmp/image.png",
    )
    graph.add_asset(
        role=VisualArtifactRole.GENERATED_VIDEO,
        artifact_id="var_video",
        local_path="/tmp/video.mp4",
    )

    result = assemble_visual_package(mission, graph)

    assert result.success is True
    assert result.mission_id == mission.mission_id
    assert result.selected_image_artifact_ids == ["var_image"]
    assert result.selected_video_artifact_ids == ["var_video"]
    assert result.delivery_metadata["selected_visual_artifact_ids"] == ["var_image", "var_video"]
    assert "1 image" in result.summary
    assert "1 video" in result.summary


def test_assembler_stops_when_no_selected_artifacts_exist():
    mission = plan_visual_mission("Create images and one video.", autonomy_level=2)
    graph = VisualAssetGraph(mission_id=mission.mission_id)

    result = assemble_visual_package(mission, graph)

    assert result.success is False
    assert result.stop_reason == "no_selected_artifacts"
