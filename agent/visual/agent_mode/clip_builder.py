"""Video clip building helpers for Visual Agent Mode."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.types import VisualArtifactRole, VisualMission


def build_video_clips(
    mission: VisualMission,
    graph: VisualAssetGraph,
    *,
    generate_video: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> Dict[str, Any]:
    clips: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for selected in _selected_image_assets(graph)[: mission.video_budget]:
        args = {
            "prompt": mission.output_goal,
            "image_url": selected.get("local_path"),
            "duration": mission.constraints.get("duration", 6),
        }
        if mission.constraints.get("aspect_ratio"):
            args["aspect_ratio"] = mission.constraints["aspect_ratio"]

        payload = generate_video(args)
        if payload.get("success") and payload.get("visual_artifact_id"):
            clip = _clip_from_payload(payload)
            clips.append(clip)
            video = graph.add_asset(
                role=VisualArtifactRole.GENERATED_VIDEO,
                artifact_id=clip["artifact_id"],
                local_path=clip.get("video"),
                metadata={
                    "request_id": clip.get("request_id"),
                    "attempt_id": clip.get("attempt_id"),
                    "aspect_ratio": payload.get("aspect_ratio"),
                },
            )
            graph.link(selected["asset_id"], video.asset_id)
        else:
            failures.append(dict(payload))

    return {
        "success": bool(clips),
        "clip_count": len(clips),
        "failure_count": len(failures),
        "clips": clips,
        "failures": failures,
    }


def _selected_image_assets(graph: VisualAssetGraph) -> List[Dict[str, Any]]:
    return [
        asset
        for asset in graph.to_dict()["assets"]
        if asset.get("role") == VisualArtifactRole.SELECTED_IMAGE.value
        and asset.get("local_path")
    ]


def _clip_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    clip = dict(payload)
    clip["artifact_id"] = payload["visual_artifact_id"]
    clip["request_id"] = payload.get("visual_request_id")
    clip["attempt_id"] = payload.get("visual_attempt_id")
    return clip
