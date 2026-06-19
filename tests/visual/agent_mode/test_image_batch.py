from __future__ import annotations

from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.image_batch import generate_image_candidates, select_image_candidates
from agent.visual.agent_mode.mission_planner import plan_visual_mission
from agent.visual.agent_mode.types import VisualArtifactRole


def test_generate_image_candidates_records_successful_candidates():
    mission = plan_visual_mission("Generate two image options.")
    graph = VisualAssetGraph(mission_id=mission.mission_id)
    calls = []

    def fake_generate_once(**kwargs):
        calls.append(kwargs)
        idx = len(calls)
        return {
            "success": True,
            "image": f"/tmp/generated-{idx}.png",
            "visual_artifact_id": f"var_image_{idx}",
            "visual_request_id": f"vrq_image_{idx}",
            "visual_attempt_id": f"vat_image_{idx}",
        }

    result = generate_image_candidates(mission, graph, generate_once=fake_generate_once)

    assert result["success"] is True
    assert len(calls) == 2
    assert graph.selected_artifact_ids(VisualArtifactRole.GENERATED_IMAGE) == [
        "var_image_1",
        "var_image_2",
    ]


def test_generate_image_candidates_keeps_failures_out_of_graph():
    mission = plan_visual_mission("Generate two image options.")
    graph = VisualAssetGraph(mission_id=mission.mission_id)
    calls = []

    def fake_generate_once(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {"success": False, "error": "provider_timeout"}
        return {
            "success": True,
            "image": "/tmp/generated-2.png",
            "visual_artifact_id": "var_image_2",
            "visual_request_id": "vrq_image_2",
            "visual_attempt_id": "vat_image_2",
        }

    result = generate_image_candidates(mission, graph, generate_once=fake_generate_once)

    assert result["success"] is True
    assert result["candidate_count"] == 1
    assert result["failure_count"] == 1
    assert graph.selected_artifact_ids(VisualArtifactRole.GENERATED_IMAGE) == ["var_image_2"]


def test_select_image_candidates_marks_selected_images():
    graph = VisualAssetGraph(mission_id="vms_test")
    graph.add_asset(
        role=VisualArtifactRole.GENERATED_IMAGE,
        artifact_id="var_low",
        local_path="/tmp/low.png",
    )
    graph.add_asset(
        role=VisualArtifactRole.GENERATED_IMAGE,
        artifact_id="var_high",
        local_path="/tmp/high.png",
    )

    selected = select_image_candidates(
        graph,
        [
            {"artifact_id": "var_low", "score": 0.55},
            {"artifact_id": "var_high", "score": 0.91},
        ],
        max_selected=1,
    )

    assert selected == ["var_high"]
    assert graph.selected_artifact_ids(VisualArtifactRole.SELECTED_IMAGE) == ["var_high"]
    selected_asset = [
        asset
        for asset in graph.to_dict()["assets"]
        if asset.get("role") == VisualArtifactRole.SELECTED_IMAGE.value
    ][0]
    assert selected_asset["metadata"]["selection_rank"] == 1
    assert selected_asset["metadata"]["selection_score"] == 0.91
    assert selected_asset["metadata"]["selection_decision"] == "selected"
    assert selected_asset["metadata"]["ranker_version"] == "visual-agent-score-v1"
