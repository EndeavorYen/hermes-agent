from __future__ import annotations

from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.image_batch import generate_image_candidates
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
