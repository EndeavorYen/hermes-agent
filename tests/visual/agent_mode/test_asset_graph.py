from __future__ import annotations

from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.types import VisualArtifactRole


def test_asset_graph_tracks_reference_image_video_lineage():
    graph = VisualAssetGraph(mission_id="vms_test")
    ref = graph.add_asset(role=VisualArtifactRole.UPLOADED_REFERENCE, local_path="/tmp/ref.png")
    image = graph.add_asset(
        role=VisualArtifactRole.SELECTED_IMAGE,
        artifact_id="var_image",
        local_path="/tmp/generated.png",
    )
    video = graph.add_asset(
        role=VisualArtifactRole.GENERATED_VIDEO,
        artifact_id="var_video",
        local_path="/tmp/generated.mp4",
    )
    graph.link(ref.asset_id, image.asset_id)
    graph.link(image.asset_id, video.asset_id)

    assert graph.parents(image.asset_id) == [ref.asset_id]
    assert graph.parents(video.asset_id) == [image.asset_id]
    assert graph.selected_artifact_ids(VisualArtifactRole.SELECTED_IMAGE) == ["var_image"]
    assert graph.selected_artifact_ids(VisualArtifactRole.GENERATED_VIDEO) == ["var_video"]
    assert graph.to_dict()["mission_id"] == "vms_test"


def test_asset_graph_links_parent_once():
    graph = VisualAssetGraph(mission_id="vms_test")
    parent = graph.add_asset(role=VisualArtifactRole.UPLOADED_REFERENCE, local_path="/tmp/ref.png")
    child = graph.add_asset(role=VisualArtifactRole.GENERATED_IMAGE, artifact_id="var_image")

    graph.link(parent.asset_id, child.asset_id)
    graph.link(parent.asset_id, child.asset_id)

    assert graph.parents(child.asset_id) == [parent.asset_id]
