"""Package assembly for Visual Agent Mode missions."""

from __future__ import annotations

from typing import Any, Dict, List

from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.types import (
    VisualArtifactRole,
    VisualMission,
    VisualMissionResult,
)


def assemble_visual_package(
    mission: VisualMission,
    graph: VisualAssetGraph,
) -> VisualMissionResult:
    image_assets = _assets_by_role(graph, VisualArtifactRole.SELECTED_IMAGE)
    video_assets = _assets_by_role(graph, VisualArtifactRole.GENERATED_VIDEO)
    image_ids = _artifact_ids(image_assets)
    video_ids = _artifact_ids(video_assets)

    if not image_ids and not video_ids:
        return VisualMissionResult(
            success=False,
            mission_id=mission.mission_id,
            selected_image_artifact_ids=[],
            selected_video_artifact_ids=[],
            delivery_metadata={
                "visual_mission_id": mission.mission_id,
                "selected_visual_artifact_ids": [],
                "visual_artifacts": {},
            },
            summary="No selected visual artifacts are ready for delivery.",
            stop_reason="no_selected_artifacts",
        )

    return VisualMissionResult(
        success=True,
        mission_id=mission.mission_id,
        selected_image_artifact_ids=image_ids,
        selected_video_artifact_ids=video_ids,
        delivery_metadata={
            "visual_mission_id": mission.mission_id,
            "selected_visual_artifact_ids": image_ids + video_ids,
            "visual_artifacts": _visual_artifact_metadata(
                mission,
                image_assets + video_assets,
            ),
        },
        summary=f"Prepared {_count_phrase(len(image_ids), 'image')} and {_count_phrase(len(video_ids), 'video')}.",
    )


def _assets_by_role(
    graph: VisualAssetGraph,
    role: VisualArtifactRole,
) -> List[Dict[str, Any]]:
    return [
        asset
        for asset in graph.to_dict()["assets"]
        if asset.get("role") == role.value and asset.get("artifact_id")
    ]


def _artifact_ids(assets: List[Dict[str, Any]]) -> List[str]:
    return [asset["artifact_id"] for asset in assets]


def _visual_artifact_metadata(
    mission: VisualMission,
    assets: List[Dict[str, Any]],
) -> Dict[str, Dict[str, str]]:
    visual_artifacts: Dict[str, Dict[str, str]] = {}
    for asset in assets:
        local_path = asset.get("local_path")
        if not local_path:
            continue
        metadata = asset.get("metadata") or {}
        visual_artifacts[local_path] = {
            "artifact_id": asset.get("artifact_id") or "",
            "request_id": metadata.get("request_id") or mission.mission_id,
            "attempt_id": metadata.get("attempt_id") or "",
            "content_hash": metadata.get("content_hash") or "",
        }
    return visual_artifacts


def _count_phrase(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"
