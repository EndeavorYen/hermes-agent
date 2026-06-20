"""Agent-facing visual package generation tool."""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import asdict, replace
from typing import Any, Dict, List

from agent.visual.agent_mode.assembler import assemble_visual_package
from agent.visual.agent_mode.asset_graph import VisualAssetGraph
from agent.visual.agent_mode.clip_builder import build_video_clips as _build_video_clips
from agent.visual.agent_mode.image_batch import select_image_candidates as _select_image_candidates
from agent.visual.agent_mode.loop_policy import VisualLoopPolicy, decide_next_action
from agent.visual.agent_mode.mission_planner import plan_visual_mission
from agent.visual.agent_mode.reward import score_visual_outcome
from agent.visual.agent_mode.types import VisualArtifactRole, VisualMission
from agent.visual.ids import new_artifact_id
from tools.registry import registry, tool_error


VISUAL_AGENT_GENERATE_SCHEMA: Dict[str, Any] = {
    "name": "visual_agent_generate",
    "description": (
        "Run Hermes as a visual production agent: plan a visual mission, "
        "generate image candidates, select current artifacts, optionally "
        "create video clips, and return a package ready for delivery. "
        "Use this for natural user requests that ask for images plus videos, "
        "image-to-video packages, product showcases, character/photo sets with clips, "
        "visual materials that include a short clip, or Chinese requests such as "
        "產出圖片和影片 / 產圖產影片 / 做一組視覺素材含短片. "
        "Do not require the user to mention this tool name or internal parameters."
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
                "description": "Autonomy level from 0 to 4. Defaults to 2 so natural package requests can auto-select images for video. Only set this when the user explicitly wrote autonomy_level=... in the prompt.",
                "default": 2,
            },
            "candidate_budget": {
                "type": "integer",
                "description": "Optional image candidate count override. Only set this when the user explicitly wrote candidate_budget=... in the prompt.",
            },
            "video_budget": {
                "type": "integer",
                "description": "Optional video clip count override. Only set this when the user explicitly wrote video_budget=... in the prompt.",
            },
            "max_selected": {
                "type": "integer",
                "description": "Optional maximum selected image artifacts to include. Only set this when the user explicitly wrote max_selected=... in the prompt; otherwise omit to select the number of images requested by the user.",
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
    confidence = _candidate_confidence(image_result.get("candidates") or [])
    action = decide_next_action(
        mission,
        candidate_count=int(image_result.get("candidate_count") or 0),
        accepted_count=int(image_result.get("candidate_count") or 0),
        failure_count=int(image_result.get("failure_count") or 0),
        confidence=confidence,
    )
    if action == "select_images":
        select_image_candidates(
            graph,
            image_result.get("candidates") or [],
            max_selected=_max_selected_from_args(args, prompt, mission),
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
    _add_package_status(
        payload,
        mission,
        action=action,
        image_result=image_result,
        video_result=video_result,
        confidence=confidence,
    )
    payload.setdefault("delivery_metadata", {})["reward_trace"] = _build_reward_trace(
        payload,
        image_result=image_result,
        video_result=video_result,
        confidence=confidence,
    )
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
            prompt=_image_stage_prompt(mission),
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
            fallback = _fallback_candidate_from_failed_mission(result)
            if fallback is not None:
                successful.append(fallback)
                graph.add_asset(
                    role=VisualArtifactRole.GENERATED_IMAGE,
                    artifact_id=fallback["artifact_id"],
                    local_path=fallback["image"],
                    metadata=dict(fallback.get("metadata") or {}),
                )
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
    autonomy_level = (
        _coerce_int(args.get("autonomy_level"), default=2)
        if _internal_param_explicit(prompt, "autonomy_level")
        else 2
    )
    mission = plan_visual_mission(
        prompt,
        attachments=list(args.get("attachments") or []),
        autonomy_level=autonomy_level,
    )
    replacements: Dict[str, Any] = {}
    if (
        _internal_param_explicit(prompt, "candidate_budget")
        and _coerce_positive_int(args.get("candidate_budget")) is not None
    ):
        replacements["candidate_budget"] = _coerce_positive_int(args.get("candidate_budget"))
    if (
        _internal_param_explicit(prompt, "video_budget")
        and _coerce_positive_int(args.get("video_budget")) is not None
    ):
        replacements["video_budget"] = _coerce_positive_int(args.get("video_budget"))
    return replace(mission, **replacements) if replacements else mission


def _max_selected_from_args(
    args: Dict[str, Any],
    prompt: str,
    mission: VisualMission,
) -> int:
    explicit = (
        _coerce_positive_int(args.get("max_selected"))
        if _internal_param_explicit(prompt, "max_selected")
        else None
    )
    if explicit is not None:
        return explicit
    planned = plan_visual_mission(
        prompt,
        attachments=list(args.get("attachments") or []),
        autonomy_level=mission.autonomy_level,
    )
    return max(1, int(planned.candidate_budget or 1))


def _internal_param_explicit(prompt: str, name: str) -> bool:
    return bool(re.search(rf"\b{re.escape(name.lower())}\s*=", (prompt or "").lower()))


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


def _image_stage_prompt(mission: VisualMission) -> str:
    goal = _strip_video_delivery_terms(mission.output_goal)
    if "video" not in mission.requested_outputs:
        return goal
    return (
        "Create exactly one standalone still image for the visual package.\n"
        "Use only the still-photo subject and scene below.\n"
        "Never render split-screen panels, storyboards, contact sheets, UI labels, "
        "captions, comparison panels, player controls, or embedded preview frames.\n"
        f"Still-image brief: {goal}"
    )


def _strip_video_delivery_terms(text: str) -> str:
    cleaned = re.sub(
        r"\b(?:and|plus|with)\s+(?:one|a|an|[1-9]\d*)\s+"
        r"(?:short\s+)?(?:video|videos|clip|clips|animation|animations)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:one|a|an|[1-9]\d*)\s+(?:short\s+)?"
        r"(?:video|videos|clip|clips|animation|animations)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or text.strip()


def _fallback_candidate_from_failed_mission(result: Dict[str, Any]) -> Dict[str, Any] | None:
    if result.get("error_type") != "qc_failed":
        return None
    best = result.get("best_candidate")
    if not isinstance(best, dict):
        return None
    image = best.get("image")
    if not isinstance(image, str) or not image.strip():
        return None
    metadata = {
        "qc_failed_fallback": True,
        "request_id": best.get("visual_request_id"),
        "attempt_id": best.get("visual_attempt_id"),
        "provider": best.get("provider"),
        "model": best.get("model"),
    }
    return {
        "artifact_id": best.get("visual_artifact_id") or new_artifact_id(),
        "image": image.strip(),
        "score": _best_candidate_score(best),
        "metadata": metadata,
    }


def _best_candidate_score(best: Dict[str, Any]) -> float:
    qc = best.get("qc") if isinstance(best.get("qc"), dict) else {}
    raw_score = qc.get("score")
    try:
        return round(max(0.0, min(1.0, float(raw_score) / 100.0)), 4)
    except (TypeError, ValueError):
        return 0.55


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


def _add_package_status(
    payload: Dict[str, Any],
    mission: VisualMission,
    *,
    action: str,
    image_result: Dict[str, Any],
    video_result: Dict[str, Any],
    confidence: float,
) -> None:
    images = list(payload.get("images") or [])
    videos = list(payload.get("videos") or [])
    missing_outputs: List[str] = []
    stop_reasons: List[str] = []

    if "image" in mission.requested_outputs and not images:
        missing_outputs.append("image")
        if action == "ask_user":
            if confidence < VisualLoopPolicy().low_confidence_threshold:
                stop_reasons.append("low_image_confidence")
            else:
                stop_reasons.append("manual_selection_required")
        elif action == "fail":
            stop_reasons.append("image_stage_failed")
        elif not image_result.get("success"):
            stop_reasons.append("image_stage_failed")
    if "video" in mission.requested_outputs and not videos:
        missing_outputs.append("video")
        if images:
            stop_reasons.append("video_stage_failed")
        elif not video_result.get("success"):
            stop_reasons.append("video_stage_not_started")

    if not stop_reasons and action in {"ask_user", "fail"}:
        stop_reasons.append(action)

    if not payload.get("success"):
        package_status = "stopped"
    elif missing_outputs:
        package_status = "partial_success"
    else:
        package_status = "success"

    payload["package_status"] = package_status
    payload["missing_outputs"] = missing_outputs
    payload["stop_reasons"] = stop_reasons
    if stop_reasons:
        payload["stop_reason"] = stop_reasons[0]


def _build_reward_trace(
    payload: Dict[str, Any],
    *,
    image_result: Dict[str, Any],
    video_result: Dict[str, Any],
    confidence: float,
) -> Dict[str, Any]:
    images = list(payload.get("images") or [])
    videos = list(payload.get("videos") or [])
    package_status = str(payload.get("package_status") or "")
    provider_error_type = _first_failure_error_type(image_result, video_result)
    delivery_health = {
        "success": 1.0,
        "partial_success": 0.5,
    }.get(package_status, 0.0)
    reward = score_visual_outcome(
        {
            "provider_error_type": provider_error_type,
            "artifact_valid": bool(images or videos),
            "artifact_quality": confidence if images else 0.0,
            "delivery_health": delivery_health,
            "preference_score": 0.5,
            "confidence": confidence,
        }
    )
    return {
        "mode": "shadow",
        "reward_model": "visual-reward-v0",
        "reward": reward.to_dict(),
        "evidence": {
            "image_stage_success": bool(image_result.get("success")),
            "video_stage_success": bool(video_result.get("success")),
            "selected_image_count": len(images),
            "selected_video_count": len(videos),
            "package_status": package_status,
            "has_provider_error": bool(provider_error_type),
        },
    }


def _first_failure_error_type(*stage_results: Dict[str, Any]) -> str | None:
    for result in stage_results:
        failures = result.get("failures") if isinstance(result, dict) else None
        if not isinstance(failures, list):
            continue
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            error_type = str(failure.get("error_type") or "").strip()
            if error_type:
                return error_type
    return None


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
