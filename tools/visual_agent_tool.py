"""Agent-facing visual package generation tool."""

from __future__ import annotations

import inspect
import json
from dataclasses import asdict, replace
from typing import Any, Dict, List

from agent.visual.agent_mode.assembler import assemble_visual_package
from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.clip_builder import build_video_clips as _build_video_clips
from agent.visual.agent_mode.image_batch import select_image_candidates as _select_image_candidates
from agent.visual.agent_mode.loop_policy import decide_next_action
from agent.visual.agent_mode.mission_planner import plan_visual_mission
from agent.visual.agent_mode.types import VisualArtifactRole, VisualMission
from agent.visual.ids import new_artifact_id
from tools.registry import registry, tool_error


VISUAL_AGENT_GENERATE_SCHEMA: Dict[str, Any] = {
    "name": "visual_agent_generate",
    "description": (
        "Run Hermes as a visual production agent: plan a visual mission, "
        "generate image candidates, select current artifacts, optionally "
        "create video clips, and return a package ready for delivery."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "User goal for the visual package.",
            },
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional local paths or URLs for reference material.",
            },
            "autonomy_level": {
                "type": "integer",
                "description": "Autonomy level from 0 to 4. Level 2 can auto-select images.",
                "default": 1,
            },
            "candidate_budget": {
                "type": "integer",
                "description": "Optional image candidate count override.",
            },
            "video_budget": {
                "type": "integer",
                "description": "Optional video clip count override.",
            },
            "max_selected": {
                "type": "integer",
                "description": "Maximum selected image artifacts to include.",
                "default": 2,
            },
        },
        "required": ["prompt"],
    },
}


async def _handle_visual_agent_generate(args: Dict[str, Any], **_kw: Any) -> str:
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return tool_error("prompt is required for visual agent generation", success=False)

    mission = _mission_from_args(args, prompt)
    graph = VisualAssetGraph(mission_id=mission.mission_id)
    for attachment in mission.input_assets:
        graph.add_asset(
            role=VisualArtifactRole.UPLOADED_REFERENCE,
            local_path=attachment,
        )

    image_result = await _maybe_await(generate_image_candidates(mission, graph))
    action = decide_next_action(
        mission,
        candidate_count=int(image_result.get("candidate_count") or 0),
        accepted_count=int(image_result.get("candidate_count") or 0),
        failure_count=int(image_result.get("failure_count") or 0),
        confidence=_candidate_confidence(image_result.get("candidates") or []),
    )
    if action == "select_images":
        select_image_candidates(
            graph,
            image_result.get("candidates") or [],
            max_selected=_coerce_positive_int(args.get("max_selected"), default=2),
        )

    video_result: Dict[str, Any] = {"success": False, "clips": [], "failures": []}
    if "video" in mission.requested_outputs and graph.selected_artifact_ids(VisualArtifactRole.SELECTED_IMAGE):
        video_result = await _maybe_await(build_video_clips(mission, graph))

    package = assemble_visual_package(mission, graph)
    payload = asdict(package)
    payload["images"] = _local_paths(graph, VisualArtifactRole.SELECTED_IMAGE)
    payload["videos"] = _local_paths(graph, VisualArtifactRole.GENERATED_VIDEO)
    payload["image_result"] = _public_stage_result(image_result)
    payload["video_result"] = _public_stage_result(video_result)
    if not package.success and action in {"ask_user", "fail"}:
        payload["stop_reason"] = action
    return json.dumps(payload, indent=2, ensure_ascii=False)


async def generate_image_candidates(
    mission: VisualMission,
    graph: VisualAssetGraph,
) -> Dict[str, Any]:
    from tools.image_mission_tool import run_image_generation_mission

    successful: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for index in range(mission.candidate_budget):
        result = await run_image_generation_mission(
            prompt=mission.output_goal,
            reference_images=list(mission.input_assets),
            max_attempts=mission.constraints.get("max_attempts"),
        )
        if result.get("success") and result.get("image"):
            artifact_id = result.get("visual_artifact_id") or new_artifact_id()
            candidate = {
                "artifact_id": artifact_id,
                "image": result["image"],
                "score": _mission_result_score(result),
                "request_id": result.get("visual_request_id"),
                "attempt_id": result.get("visual_attempt_id"),
            }
            successful.append(candidate)
            graph.add_asset(
                role=VisualArtifactRole.GENERATED_IMAGE,
                artifact_id=artifact_id,
                local_path=result["image"],
                metadata={
                    "request_id": candidate.get("request_id"),
                    "attempt_id": candidate.get("attempt_id"),
                },
            )
        else:
            failures.append(_public_failure(result))

    return {
        "success": bool(successful),
        "candidate_count": len(successful),
        "failure_count": len(failures),
        "candidates": successful,
        "failures": failures,
    }


def select_image_candidates(
    graph: VisualAssetGraph,
    candidates: List[Dict[str, Any]],
    *,
    max_selected: int = 2,
) -> List[str]:
    return _select_image_candidates(graph, candidates, max_selected=max_selected)


def build_video_clips(
    mission: VisualMission,
    graph: VisualAssetGraph,
) -> Dict[str, Any]:
    from tools.video_generation_tool import _handle_video_generate

    def generate_video(args: Dict[str, Any]) -> Dict[str, Any]:
        raw = _handle_video_generate(args)
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"success": False, "error": str(raw), "error_type": "invalid_json"}
        return payload if isinstance(payload, dict) else {"success": False, "error": str(payload)}

    return _build_video_clips(mission, graph, generate_video=generate_video)


def _mission_from_args(args: Dict[str, Any], prompt: str) -> VisualMission:
    mission = plan_visual_mission(
        prompt,
        attachments=list(args.get("attachments") or []),
        autonomy_level=_coerce_int(args.get("autonomy_level"), default=1),
    )
    replacements: Dict[str, Any] = {}
    if _coerce_positive_int(args.get("candidate_budget")) is not None:
        replacements["candidate_budget"] = _coerce_positive_int(args.get("candidate_budget"))
    if _coerce_positive_int(args.get("video_budget")) is not None:
        replacements["video_budget"] = _coerce_positive_int(args.get("video_budget"))
    return replace(mission, **replacements) if replacements else mission


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _candidate_confidence(candidates: List[Dict[str, Any]]) -> float:
    if not candidates:
        return 0.0
    return max(_score(candidate) for candidate in candidates)


def _score(candidate: Dict[str, Any]) -> float:
    try:
        return float(candidate.get("score", candidate.get("confidence", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _mission_result_score(result: Dict[str, Any]) -> float:
    best = result.get("best") if isinstance(result, dict) else None
    qc = best.get("qc") if isinstance(best, dict) else None
    raw_score = qc.get("score") if isinstance(qc, dict) else None
    try:
        return max(0.0, min(1.0, float(raw_score) / 100.0))
    except (TypeError, ValueError):
        return 1.0


def _local_paths(graph: VisualAssetGraph, role: VisualArtifactRole) -> List[str]:
    return [
        asset["local_path"]
        for asset in graph.to_dict()["assets"]
        if asset.get("role") == role.value and asset.get("local_path")
    ]


def _public_stage_result(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key in {"success", "candidate_count", "failure_count", "clip_count", "failures"}
    }


def _public_failure(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "success": False,
        "error": result.get("error"),
        "error_type": result.get("error_type"),
    }


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_positive_int(value: Any, *, default: int | None = None) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


registry.register(
    name="visual_agent_generate",
    toolset="image_gen",
    schema=VISUAL_AGENT_GENERATE_SCHEMA,
    handler=_handle_visual_agent_generate,
    requires_env=[],
    is_async=True,
    emoji="VA",
)
