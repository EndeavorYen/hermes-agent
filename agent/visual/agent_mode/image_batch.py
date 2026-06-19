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


def select_image_candidates(
    graph: VisualAssetGraph,
    candidates: List[Dict[str, Any]],
    *,
    max_selected: int = 2,
) -> List[str]:
    selected_artifact_ids: List[str] = []
    generated_assets = _generated_image_assets_by_artifact_id(graph)
    ranked = sorted(candidates, key=_candidate_score, reverse=True)

    for candidate in ranked[:max_selected]:
        artifact_id = candidate.get("artifact_id")
        if not artifact_id or artifact_id not in generated_assets:
            continue
        source = generated_assets[artifact_id]
        selected = graph.add_asset(
            role=VisualArtifactRole.SELECTED_IMAGE,
            artifact_id=artifact_id,
            local_path=source.get("local_path"),
            source_url=source.get("source_url"),
            metadata=dict(source.get("metadata") or {}),
        )
        graph.link(source["asset_id"], selected.asset_id)
        selected_artifact_ids.append(artifact_id)

    return selected_artifact_ids


def _candidate_score(candidate: Dict[str, Any]) -> float:
    value = candidate.get("score", candidate.get("confidence", 0.0))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _generated_image_assets_by_artifact_id(graph: VisualAssetGraph) -> Dict[str, Dict[str, Any]]:
    assets = graph.to_dict()["assets"]
    return {
        asset["artifact_id"]: asset
        for asset in assets
        if asset.get("role") == VisualArtifactRole.GENERATED_IMAGE.value and asset.get("artifact_id")
    }
