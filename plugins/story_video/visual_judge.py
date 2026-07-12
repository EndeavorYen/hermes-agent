from __future__ import annotations

import json
import mimetypes
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .quality import (
    DIMENSION_WEIGHTS,
    QUALITY_THRESHOLD,
    candidate_budget_for_shot,
    candidate_quality_score,
    compile_shot_prompt,
    rank_candidate_assessments,
)
from .state import StoryVideoRunContext, StoryVideoStateStore


MAX_REPAIR_ROUNDS = 5
_PLUGIN_LLM: Any = None


CANDIDATE_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_id",
                    "hard_blockers",
                    "dimensions",
                    "evidence",
                ],
                "properties": {
                    "candidate_id": {"type": "string"},
                    "hard_blockers": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "dimensions": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(DIMENSION_WEIGHTS),
                        "properties": {
                            name: {"type": "number", "minimum": 0, "maximum": 100}
                            for name in DIMENSION_WEIGHTS
                        },
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
            },
        }
    },
}


def configure_plugin_llm(llm: Any) -> None:
    global _PLUGIN_LLM
    _PLUGIN_LLM = llm


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _provider(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _project_path(context: StoryVideoRunContext, value: Any) -> Path:
    path = Path(str(value or ""))
    if not path.is_absolute():
        path = context.project_dir / path
    return path.resolve()


def _relative(context: StoryVideoRunContext, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(context.project_dir.resolve()))
    except ValueError:
        return str(path.resolve())


def _find_shot(
    context: StoryVideoRunContext,
    shot_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ledger = _load_json(context.project_dir / "scene_ledger.json")
    if not isinstance(ledger, dict):
        raise ValueError("scene_ledger.json is missing or invalid")
    scenes = ledger.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("scene_ledger.json has no scenes")
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        shots = scene.get("shots")
        if not isinstance(shots, list):
            continue
        for shot in shots:
            if isinstance(shot, dict) and str(shot.get("shot_id") or "") == shot_id:
                return ledger, scene, shot
    raise ValueError(f"unknown shot_id: {shot_id}")


def _compile_prompt(
    context: StoryVideoRunContext,
    *,
    shot_id: str,
) -> dict[str, Any]:
    ledger, scene, shot = _find_shot(context, shot_id)
    prompt = compile_shot_prompt(ledger=ledger, scene=scene, shot=shot)
    manifest = _load_json(
        context.project_dir / "manifests" / "shot_candidate_manifest.json"
    ) or {}
    previous_rows = [
        row
        for row in manifest.get("outputs") or []
        if isinstance(row, dict) and str(row.get("shot_id") or "") == shot_id
    ]
    previous = max(
        previous_rows,
        key=lambda row: (
            int(row.get("repair_round") or 0),
            str(row.get("reviewed_at") or ""),
        ),
        default=None,
    )
    blockers = [
        str(item).strip()
        for item in (previous or {}).get("hard_blockers") or []
        if str(item).strip()
    ]
    previous_round = int((previous or {}).get("repair_round") or 0)
    previous_status = str((previous or {}).get("status") or "")
    previous_strategy_reset = (previous or {}).get("strategy_reset") is True
    strategy_reset = (
        previous_status == "quality_budget_exhausted"
        and not previous_strategy_reset
    )
    if previous_status == "quality_budget_exhausted" and previous_strategy_reset:
        return {
            "success": False,
            "action": "compile_prompt",
            "shot_id": shot_id,
            "status": "human_review_required",
            "hard_blockers": blockers,
            "error": "The one-time composition strategy reset also failed.",
        }
    if blockers:
        prompt += (
            " Prior QC blocker(s): "
            + "; ".join(blockers)
            + ". Repair directive: materially change the composition instead of "
            "repeating the prior framing. Keep the declared subtitle-safe area "
            "completely free of the focal subject, hands, supports, and evidence."
        )
    if strategy_reset:
        prompt += (
            " This is the one-time composition strategy reset after the normal repair "
            "budget was exhausted. Use a wider or offset framing with all focal evidence "
            "grouped away from the subtitle-safe area; do not imitate the previous crop."
        )
    candidate_id_hint = (
        f"{shot_id}_LAYOUT_C01"
        if strategy_reset
        else f"{shot_id}_C{min(previous_round + 1, MAX_REPAIR_ROUNDS):02d}"
    )
    prompt_path = context.project_dir / "prompts" / f"{shot_id}.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    return {
        "success": True,
        "action": "compile_prompt",
        "shot_id": shot_id,
        "prompt": prompt,
        "prompt_path": _relative(context, prompt_path),
        "candidate_budget": candidate_budget_for_shot(shot),
        "generation_policy": "qc_driven_selective_regeneration",
        "max_repair_rounds": MAX_REPAIR_ROUNDS,
        "quality_threshold": QUALITY_THRESHOLD,
        "repair_feedback_applied": bool(blockers),
        "strategy_reset": strategy_reset,
        "remaining_strategy_reset_candidates": 1 if strategy_reset else 0,
        "candidate_id_hint": candidate_id_hint,
    }


def _review_instructions(shot: dict[str, Any], candidate_ids: list[str]) -> str:
    return "\n".join(
        (
            "You are the independent visual quality judge for a professional story video.",
            "Inspect every candidate image and score only what is visibly supported.",
            "The generation provider and the judging provider are both required to be OpenAI.",
            f"Shot contract: {json.dumps(shot, ensure_ascii=False, sort_keys=True)}",
            f"Candidate image order: {json.dumps(candidate_ids, ensure_ascii=False)}",
            "Hard blockers include wrong spoken-claim content, scientific contradiction, malformed anatomy or geometry, generated text/watermark, unclear focus, subtitle collision, and an image that adds no information beyond adjacent shots.",
            "Return one row for every candidate id. Scores use 0-100. Evidence must cite concrete visible observations, not metadata or prompt intent.",
        )
    )


def _image_input(path: Path) -> dict[str, Any]:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return {
        "type": "image",
        "data": path.read_bytes(),
        "mime_type": mime,
        "file_name": path.name,
    }


def _judge_candidates(
    context: StoryVideoRunContext,
    *,
    shot_id: str,
    candidates: list[dict[str, Any]],
    repair_round: int,
    llm: Any,
) -> dict[str, Any]:
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        match = re.search(
            r"(?:^|_)C(\d+)$",
            str(candidate.get("candidate_id") or ""),
            re.IGNORECASE,
        )
        if match is not None:
            repair_round = max(repair_round, int(match.group(1)))
    strategy_reset = any(row.get("strategy_reset") is True for row in candidates)
    if not 1 <= repair_round <= MAX_REPAIR_ROUNDS:
        return {
            "success": False,
            "error_type": "story_video_invalid_repair_round",
            "error": f"repair_round must be 1-{MAX_REPAIR_ROUNDS}",
        }
    if not candidates:
        return {
            "success": False,
            "error_type": "story_video_candidates_missing",
            "error": "judge_candidates requires at least one candidate",
        }
    if len(candidates) != 1:
        return {
            "success": False,
            "error_type": "story_video_single_candidate_required",
            "error": (
                "Submit exactly one image per QC round; regenerate only after "
                "a shot is marked repair_required."
            ),
        }
    ledger, scene, shot = _find_shot(context, shot_id)
    candidate_rows: list[dict[str, Any]] = []
    candidate_paths: dict[str, Path] = {}
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            return {
                "success": False,
                "error_type": "story_video_candidate_invalid",
                "error": f"candidate[{index}] is not an object",
            }
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id or candidate_id in seen:
            return {
                "success": False,
                "error_type": "story_video_candidate_id_invalid",
                "error": f"candidate[{index}] has missing or duplicate candidate_id",
            }
        seen.add(candidate_id)
        if _provider(candidate.get("provider")) not in {"openai", "openai-codex"}:
            return {
                "success": False,
                "error_type": "story_video_non_openai_candidate",
                "error": f"candidate {candidate_id} is not from OpenAI",
            }
        path = _project_path(context, candidate.get("path") or candidate.get("local_path"))
        if not path.is_file():
            return {
                "success": False,
                "error_type": "story_video_candidate_file_missing",
                "error": f"candidate file missing: {path}",
            }
        candidate_paths[candidate_id] = path
        candidate_rows.append(candidate)

    prompt_info = _compile_prompt(context, shot_id=shot_id)
    candidate_ids = [str(row["candidate_id"]) for row in candidate_rows]
    inputs: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Compiled source-art prompt: {prompt_info['prompt']}\n"
                f"Scene context: {json.dumps(scene, ensure_ascii=False, sort_keys=True)}"
            ),
        }
    ]
    inputs.extend(_image_input(candidate_paths[candidate_id]) for candidate_id in candidate_ids)
    if llm is None:
        return {
            "success": False,
            "error_type": "story_video_visual_judge_unavailable",
            "error": "story-video plugin LLM is not configured",
        }
    try:
        result = llm.complete_structured(
            instructions=_review_instructions(shot, candidate_ids),
            input=inputs,
            json_schema=CANDIDATE_REVIEW_SCHEMA,
            json_mode=True,
            schema_name="story_video_candidate_review",
            provider="openai-codex",
            temperature=0,
            max_tokens=2400,
            timeout=180,
            purpose="story_video_candidate_vision_review",
        )
    except Exception as exc:
        return {
            "success": False,
            "error_type": "story_video_visual_judge_failed",
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    judge_provider = _provider(getattr(result, "provider", ""))
    if judge_provider not in {"openai", "openai-codex"}:
        return {
            "success": False,
            "error_type": "story_video_non_openai_judge",
            "error": f"visual judge resolved to {judge_provider or '<missing>'}",
        }
    parsed = getattr(result, "parsed", None)
    rows = parsed.get("candidates") if isinstance(parsed, dict) else None
    if not isinstance(rows, list) or {
        str(row.get("candidate_id") or "") for row in rows if isinstance(row, dict)
    } != set(candidate_ids):
        return {
            "success": False,
            "error_type": "story_video_visual_judge_invalid_response",
            "error": "visual judge did not return exactly one row per candidate",
        }
    response_id = str(
        (getattr(result, "audit", {}) or {}).get("response_id") or ""
    ).strip()
    assessments: list[dict[str, Any]] = []
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        source = next(item for item in candidate_rows if item["candidate_id"] == candidate_id)
        assessments.append(
            {
                **row,
                "provider": source.get("provider"),
                "judge_provider": judge_provider,
            }
        )
    decision = rank_candidate_assessments(assessments, threshold=QUALITY_THRESHOLD)
    selected_path = context.project_dir / "images" / f"{shot_id}.png"
    if decision.selected_candidate_id:
        selected_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate_paths[decision.selected_candidate_id], selected_path)

    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest = _load_json(manifest_path) or {
        "schema": "story_video_shot_candidate_manifest_v1",
        "provider": "openai-codex",
        "judge_provider": "openai-codex",
        "quality_threshold": QUALITY_THRESHOLD,
        "outputs": [],
    }
    previous = [
        row
        for row in manifest.get("outputs") or []
        if isinstance(row, dict) and str(row.get("shot_id") or "") != shot_id
    ]
    current_rows: list[dict[str, Any]] = []
    selected_id = decision.selected_candidate_id
    terminal_status = (
        "selected_current"
        if selected_id
        else "quality_budget_exhausted"
        if repair_round >= MAX_REPAIR_ROUNDS or strategy_reset
        else "repair_required"
    )
    for assessment in assessments:
        candidate_id = str(assessment.get("candidate_id") or "")
        source = next(item for item in candidate_rows if item["candidate_id"] == candidate_id)
        score = candidate_quality_score(assessment.get("dimensions")) or 0.0
        blockers = [str(item) for item in assessment.get("hard_blockers") or []]
        current_rows.append(
            {
                "shot_id": shot_id,
                "shot_scale": str(shot.get("shot_scale") or ""),
                "candidate_id": candidate_id,
                "selected": candidate_id == selected_id,
                "status": (
                    "selected_current"
                    if candidate_id == selected_id
                    else "rejected"
                    if selected_id
                    else terminal_status
                ),
                "provider": _provider(source.get("provider")),
                "model": str(source.get("model") or ""),
                "generation_response_id": str(source.get("response_id") or ""),
                "judge_provider": judge_provider,
                "judge_model": str(getattr(result, "model", "") or ""),
                "prompt_path": str(prompt_info["prompt_path"]),
                "candidate_path": _relative(context, candidate_paths[candidate_id]),
                "local_path": (
                    _relative(context, selected_path)
                    if candidate_id == selected_id
                    else _relative(context, candidate_paths[candidate_id])
                ),
                "quality_score": score,
                "hard_blockers": blockers,
                "quality_dimensions": assessment.get("dimensions"),
                "vision_evidence": {
                    "status": "PASS",
                    "response_id": response_id,
                    "evidence": assessment.get("evidence") or [],
                },
                "repair_round": repair_round,
                "strategy_reset": strategy_reset,
                "reviewed_at": _utc_now(),
            }
        )
    manifest.update(
        {
            "provider": "openai-codex",
            "judge_provider": "openai-codex",
            "quality_threshold": QUALITY_THRESHOLD,
            "outputs": sorted(
                [*previous, *current_rows],
                key=lambda row: (str(row.get("shot_id") or ""), str(row.get("candidate_id") or "")),
            ),
            "updated_at": _utc_now(),
        }
    )
    _write_json_atomic(manifest_path, manifest)
    status = (
        "selected"
        if selected_id
        else "quality_budget_exhausted"
        if repair_round >= MAX_REPAIR_ROUNDS or strategy_reset
        else "repair_required"
    )
    return {
        "success": bool(selected_id),
        "action": "judge_candidates",
        "shot_id": shot_id,
        "status": status,
        "repair_round": repair_round,
        "selected_candidate_id": selected_id,
        "selected_asset": _relative(context, selected_path) if selected_id else "",
        "ranked_candidate_ids": list(decision.ranked_candidate_ids),
        "best_score": decision.best_score,
        "quality_threshold": QUALITY_THRESHOLD,
        "strategy_reset": strategy_reset,
        "manifest": _relative(context, manifest_path),
        "judge_provider": judge_provider,
        "judge_model": str(getattr(result, "model", "") or ""),
        "judge_response_id": response_id,
    }


def _status(context: StoryVideoRunContext) -> dict[str, Any]:
    path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest = _load_json(path) or {}
    outputs = [row for row in manifest.get("outputs") or [] if isinstance(row, dict)]
    selected = sorted(
        {str(row.get("shot_id") or "") for row in outputs if row.get("selected") is True}
        - {""}
    )
    blocked = sorted(
        {
            str(row.get("shot_id") or "")
            for row in outputs
            if row.get("selected") is not True
            and str(row.get("status") or "") in {"repair_required", "quality_budget_exhausted"}
        }
        - {""}
    )
    return {
        "success": True,
        "action": "status",
        "manifest": _relative(context, path),
        "selected_shot_count": len(selected),
        "selected_shot_ids": selected,
        "blocked_shot_ids": blocked,
    }


def _required_project_file(
    context: StoryVideoRunContext,
    value: Any,
    *,
    label: str,
) -> tuple[Path, str]:
    path = _project_path(context, value)
    try:
        relative = str(path.relative_to(context.project_dir.resolve()))
    except ValueError as exc:
        raise ValueError(f"{label} is outside the story-video project") from exc
    if not path.is_file():
        raise ValueError(f"missing {label}: {relative}")
    return path, relative


def _prepare_render(context: StoryVideoRunContext) -> dict[str, Any]:
    ledger = _load_json(context.project_dir / "scene_ledger.json")
    candidate_manifest = _load_json(
        context.project_dir / "manifests" / "shot_candidate_manifest.json"
    )
    narration_manifest = _load_json(
        context.project_dir / "manifests" / "narration_manifest.json"
    )
    if not isinstance(ledger, dict):
        raise ValueError("scene_ledger.json is missing or invalid")
    if not isinstance(candidate_manifest, dict):
        raise ValueError("shot_candidate_manifest.json is missing or invalid")
    if not isinstance(narration_manifest, dict):
        raise ValueError("narration_manifest.json is missing or invalid")

    selected_by_shot: dict[str, dict[str, Any]] = {}
    for output in candidate_manifest.get("outputs") or []:
        if not isinstance(output, dict) or output.get("selected") is not True:
            continue
        shot_id = str(output.get("shot_id") or "").strip()
        if not shot_id:
            continue
        if _provider(output.get("provider")) not in {"openai", "openai-codex"}:
            raise ValueError(f"selected shot {shot_id} is not from OpenAI")
        selected_by_shot[shot_id] = output

    narration_by_scene = {
        str(output.get("scene_id") or "").strip(): output
        for output in narration_manifest.get("outputs") or []
        if isinstance(output, dict) and str(output.get("scene_id") or "").strip()
    }
    raw_scenes = ledger.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("scene_ledger.json has no scenes")

    scenes: list[dict[str, Any]] = []
    selected_images: list[str] = []
    for scene in raw_scenes:
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or "").strip()
        narration = narration_by_scene.get(scene_id)
        if not scene_id or narration is None:
            raise ValueError(f"missing narration output for scene {scene_id or '<unknown>'}")
        _audio_path, audio_relative = _required_project_file(
            context,
            narration.get("audio"),
            label=f"audio for {scene_id}",
        )
        display_text = str(narration.get("display_text") or "").strip()
        if not display_text:
            raise ValueError(f"missing display_text for scene {scene_id}")
        shots: list[dict[str, Any]] = []
        raw_shots = scene.get("shots")
        if not isinstance(raw_shots, list) or not raw_shots:
            raise ValueError(f"scene {scene_id} has no shots")
        for shot in raw_shots:
            if not isinstance(shot, dict):
                continue
            shot_id = str(shot.get("shot_id") or "").strip()
            selected = selected_by_shot.get(shot_id)
            if selected is None:
                raise ValueError(f"missing selected image for shot {shot_id}")
            _image_path, image_relative = _required_project_file(
                context,
                selected.get("local_path"),
                label=f"image for {shot_id}",
            )
            selected_images.append(image_relative)
            shots.append(
                {
                    "shot_id": shot_id,
                    "selected": True,
                    "image": image_relative,
                    "narration": str(shot.get("narration_text") or display_text),
                }
            )
        scenes.append(
            {
                "scene_id": scene_id,
                "selected": True,
                "audio": audio_relative,
                "narration": display_text,
                "shots": shots,
            }
        )
    if not selected_images:
        raise ValueError("render requires selected shot images")

    opening_image = "release_art/opening_card.png"
    if not (context.project_dir / opening_image).is_file():
        opening_image = selected_images[0]
    ending_image = "release_art/ending_card.png"
    if not (context.project_dir / ending_image).is_file():
        ending_image = selected_images[-1]

    render_input = {
        "schema": "story_video_render_input_v2",
        "project_title": context.topic,
        "title": context.topic,
        "resolution": {"width": 1920, "height": 1080},
        "fps": 30,
        "post_speech_hold_sec": 0.85,
        "max_post_speech_hold_sec": 1.5,
        "motion_policy": "stable_center_zoom",
        "zoom_max": 1.025,
        "subtitle": {"max_lines": 2, "max_chars_per_line": 29},
        "opening_card": {
            "title": context.topic,
            "image": opening_image,
            "duration_sec": 2.0 if opening_image.startswith("release_art/") else 1.0,
        },
        "ending_card": {
            "title": "探索仍在繼續",
            "image": ending_image,
            "duration_sec": 5.0 if ending_image.startswith("release_art/") else 1.0,
        },
        "scenes": scenes,
        "output": "video/final.mp4",
    }
    path = context.project_dir / "render_input.json"
    _write_json_atomic(path, render_input)
    return {
        "success": True,
        "action": "prepare_render",
        "render_input": _relative(context, path),
        "renderer": (
            "skills/creative/story-video-production-pipeline/scripts/"
            "render_story_video.py"
        ),
        "scene_count": len(scenes),
        "selected_shot_count": len(selected_images),
    }


def story_video_quality_control(
    args: dict[str, Any],
    *,
    session_id: str = "",
    store: StoryVideoStateStore | None = None,
    llm: Any = None,
    **_: Any,
) -> str:
    state_store = store or StoryVideoStateStore()
    context = state_store.for_session(session_id)
    if context is None:
        return json.dumps(
            {
                "success": False,
                "error_type": "story_video_context_missing",
                "error": "No active story-video context for this session.",
            },
            ensure_ascii=False,
        )
    action = str(args.get("action") or "").strip().lower()
    try:
        if action == "compile_prompt":
            payload = _compile_prompt(
                context,
                shot_id=str(args.get("shot_id") or "").strip(),
            )
        elif action == "judge_candidates":
            payload = _judge_candidates(
                context,
                shot_id=str(args.get("shot_id") or "").strip(),
                candidates=[
                    row for row in args.get("candidates") or [] if isinstance(row, dict)
                ],
                repair_round=int(args.get("repair_round") or 1),
                llm=llm or _PLUGIN_LLM,
            )
        elif action == "prepare_render":
            payload = _prepare_render(context)
        elif action == "status":
            payload = _status(context)
        else:
            payload = {
                "success": False,
                "error_type": "story_video_quality_action_invalid",
                "error": f"Unsupported action: {action or '<missing>'}",
            }
    except (OSError, ValueError, TypeError) as exc:
        payload = {
            "success": False,
            "error_type": "story_video_quality_contract_error",
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    return json.dumps(payload, ensure_ascii=False)


__all__ = [
    "CANDIDATE_REVIEW_SCHEMA",
    "configure_plugin_llm",
    "story_video_quality_control",
]
