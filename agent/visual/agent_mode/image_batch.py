"""Image candidate generation helpers for Visual Agent Mode."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.types import VisualArtifactRole, VisualMission


def generate_image_candidates(
    mission: VisualMission,
    graph: VisualAssetGraph,
    *,
    generate_once: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    successful: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for index in range(mission.candidate_budget):
        payload = generate_once(
            prompt=mission.output_goal,
            attachments=list(mission.input_assets),
            mission_id=mission.mission_id,
            candidate_index=index,
        )
        if payload.get("success") and payload.get("visual_artifact_id"):
            candidate = _candidate_from_payload(payload)
            successful.append(candidate)
            graph.add_asset(
                role=VisualArtifactRole.GENERATED_IMAGE,
                artifact_id=candidate["artifact_id"],
                local_path=candidate.get("image"),
                metadata={
                    "request_id": candidate.get("request_id"),
                    "attempt_id": candidate.get("attempt_id"),
                },
            )
        else:
            failures.append(dict(payload))

    return {
        "success": bool(successful),
        "candidate_count": len(successful),
        "failure_count": len(failures),
        "candidates": successful,
        "failures": failures,
    }


def _candidate_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    candidate = dict(payload)
    candidate["artifact_id"] = payload["visual_artifact_id"]
    candidate["request_id"] = payload.get("visual_request_id")
    candidate["attempt_id"] = payload.get("visual_attempt_id")
    return candidate
