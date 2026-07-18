from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .engagement import (
    VISUAL_TRUTH_MODES,
    engagement_contract_enabled,
    is_camera_reveal_shot,
)
from .editorial_quality import EDITORIAL_PROFILE_ID
from .repair_planner import (
    BLOCKER_CODES,
    apply_repair_strategy,
    classify_blockers,
    plan_repair,
)
from .quality import (
    DIMENSION_WEIGHTS,
    QUALITY_THRESHOLD,
    candidate_budget_for_shot,
    candidate_quality_score,
    compile_shot_prompt,
    rank_candidate_assessments,
    validate_quality_ledger,
)
from .music import compile_music_bed, plan_music_cues
from .release_art import compile_release_art_brief, compose_release_art
from .sequence_quality import sequence_dimension_violations
from .shot_contract import (
    manifest_row_matches_shot_contract as _manifest_row_matches_shot_contract,
)
from .shot_contract import shot_contract_hash as _shot_contract_hash
from .state import StoryVideoRunContext, StoryVideoStateStore


MAX_REPAIR_ROUNDS = 3
MAX_CONTRACT_REPLANS = 2
MAX_REPLANNED_CONTRACT_CANDIDATES = 2
QUALITY_CONTRACT_VERSION = 4
BEST_EFFORT_QUALITY_FLOOR = 75.0
_PLUGIN_LLM: Any = None

_REPLAN_REQUIRED_FIELDS = (
    "subject",
    "action",
    "evidence_detail",
    "shot_scale",
    "camera_angle",
    "focal_point",
    "subtitle_safe_area",
    "acceptance_criteria",
)
_REPLAN_MUTABLE_FIELDS = (
    *_REPLAN_REQUIRED_FIELDS,
    "visual_truth_mode",
    "attention_hook",
    "story_moment",
    "action_consequence",
    "composition_energy",
    "viewer_emotion",
    "engagement_criteria",
    "calm_reason",
    "evidence_bridge",
    "intentional_scale_repeat_reason",
)
_REPLAN_IMMUTABLE_FIELDS = (
    "shot_id",
    "narration_text",
    "narrative_role",
    "viewer_takeaway",
    "risk_class",
)
_SHOT_SCALES = {"establishing", "wide", "medium", "close_up", "macro", "insert"}


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
                    "blocker_codes",
                    "dimensions",
                    "evidence",
                    "focal_point_normalized",
                ],
                "properties": {
                    "candidate_id": {"type": "string"},
                    "hard_blockers": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "blocker_codes": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(BLOCKER_CODES)},
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
                    "focal_point_normalized": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["x", "y"],
                        "properties": {
                            "x": {"type": "number", "minimum": 0, "maximum": 1},
                            "y": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                    },
                },
            },
        }
    },
}

SHOT_CONTRACT_REPLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["redesigned_shot"],
    "properties": {
        "redesigned_shot": {
            "type": "object",
            "additionalProperties": False,
            "required": list(_REPLAN_REQUIRED_FIELDS),
            "properties": {
                "subject": {"type": "string", "minLength": 1},
                "action": {"type": "string", "minLength": 1},
                "evidence_detail": {"type": "string", "minLength": 1},
                "shot_scale": {"type": "string", "enum": sorted(_SHOT_SCALES)},
                "camera_angle": {"type": "string", "minLength": 1},
                "focal_point": {"type": "string", "minLength": 1},
                "subtitle_safe_area": {"type": "string", "minLength": 1},
                "acceptance_criteria": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "maxItems": 3,
                },
                "visual_truth_mode": {
                    "type": "string",
                    "enum": sorted(VISUAL_TRUTH_MODES),
                },
                **{
                    field: {"type": "string", "minLength": 1}
                    for field in (
                        "attention_hook",
                        "story_moment",
                        "action_consequence",
                        "composition_energy",
                        "viewer_emotion",
                        "calm_reason",
                        "evidence_bridge",
                        "intentional_scale_repeat_reason",
                    )
                },
                "engagement_criteria": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "maxItems": 3,
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


def _write_candidate_manifest_atomic(path: Path, payload: dict[str, Any]) -> None:
    outputs = [row for row in payload.get("outputs") or [] if isinstance(row, dict)]
    history = [
        row for row in payload.get("attempt_history") or [] if isinstance(row, dict)
    ]
    selected = [row for row in outputs if row.get("selected") is True]
    selected_shot_ids = {
        str(row.get("shot_id") or "").strip() for row in selected
    } - {""}
    latest = max(
        outputs,
        key=lambda row: str(row.get("reviewed_at") or row.get("selected_at") or ""),
        default=None,
    )
    latest_selected = max(
        selected,
        key=lambda row: str(row.get("reviewed_at") or row.get("selected_at") or ""),
        default=None,
    )
    updated = {
        **payload,
        "selected_shot_count": len(selected_shot_ids),
        "generated_candidate_count": len(history) if history else len(outputs),
    }
    if latest is not None:
        updated["current_shot_id"] = str(latest.get("shot_id") or "")
    if latest_selected is not None:
        selected_path = str(
            latest_selected.get("local_path")
            or latest_selected.get("candidate_path")
            or ""
        )
        updated["current_selected_output"] = selected_path
        updated["current_selected_output_path"] = selected_path
        updated["selected_output"] = {
            "shot_id": str(latest_selected.get("shot_id") or ""),
            "candidate_id": str(latest_selected.get("candidate_id") or ""),
            "image_path": selected_path,
            "provider": str(latest_selected.get("provider") or ""),
            "judge_provider": str(latest_selected.get("judge_provider") or ""),
            "judge_score": latest_selected.get("quality_score"),
            "status": "PASS",
        }
    _write_json_atomic(path, updated)


def _persist_terminal_attention(
    context: StoryVideoRunContext,
    *,
    shot_id: str = "",
    error: str = "",
) -> None:
    path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest = _load_json(path) or {}
    if shot_id:
        manifest["terminal_attention"] = {
            "work_status": "human_review_required",
            "shot_id": shot_id,
            "error": error or "Visual repair budget exhausted.",
            "recorded_at": _utc_now(),
        }
    else:
        manifest.pop("terminal_attention", None)
    _write_candidate_manifest_atomic(path, manifest)


def _provider(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _source_image_qc_blockers(
    hard_blockers: Iterable[Any],
    explicit_codes: Iterable[Any] = (),
) -> tuple[list[str], set[str]]:
    blockers = [str(item).strip() for item in hard_blockers if str(item).strip()]
    filtered = [
        blocker
        for blocker in blockers
        if classify_blockers([blocker], ()) != {"subtitle_collision"}
    ]
    codes = {
        str(code).strip()
        for code in explicit_codes
        if str(code).strip() and str(code).strip() != "subtitle_collision"
    }
    if filtered or codes:
        codes = classify_blockers(filtered, codes)
        codes.discard("subtitle_collision")
    return filtered, codes


def _normalize_source_image_qc_row(row: dict[str, Any]) -> dict[str, Any]:
    blockers = [str(item).strip() for item in row.get("hard_blockers") or [] if str(item).strip()]
    explicit_codes = [str(item).strip() for item in row.get("blocker_codes") or [] if str(item).strip()]
    filtered, codes = _source_image_qc_blockers(blockers, explicit_codes)
    ignored_blockers = [item for item in blockers if item not in filtered]
    ignored_codes = [item for item in explicit_codes if item == "subtitle_collision"]
    if not ignored_blockers and not ignored_codes:
        return dict(row)
    return {
        **row,
        "hard_blockers": filtered,
        "blocker_codes": sorted(codes),
        "post_composite_subtitle_qc": True,
        "ignored_source_image_qc_blockers": ignored_blockers,
        "ignored_source_image_qc_blocker_codes": ignored_codes,
        "packaging_fallback": None,
    }


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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cached_qc_result(
    context: StoryVideoRunContext,
    manifest: dict[str, Any],
    *,
    shot_id: str,
    contract_hash: str,
    artifact_sha256: str,
) -> dict[str, Any] | None:
    rows = [
        row
        for row in (
            manifest.get("attempt_history") or manifest.get("outputs") or []
        )
        if isinstance(row, dict)
    ]
    for row in reversed(rows):
        dimensions = row.get("quality_dimensions")
        if (
            str(row.get("shot_id") or "") != shot_id
            or str(row.get("shot_contract_hash") or "") != contract_hash
            or str(row.get("artifact_sha256") or "") != artifact_sha256
            or int(row.get("quality_contract_version") or 0)
            != QUALITY_CONTRACT_VERSION
            or not isinstance(dimensions, dict)
            or any(name not in dimensions for name in DIMENSION_WEIGHTS)
            or (row.get("vision_evidence") or {}).get("status") != "PASS"
        ):
            continue
        selected = row.get("selected") is True
        stored_status = str(row.get("status") or "repair_required")
        status = "selected" if selected else stored_status
        return {
            "success": selected,
            "action": "judge_candidates",
            "shot_id": shot_id,
            "status": status,
            "cache_hit": True,
            "quality_contract_version": QUALITY_CONTRACT_VERSION,
            "artifact_sha256": artifact_sha256,
            "selected_candidate_id": str(row.get("candidate_id") or "") if selected else "",
            "selected_asset": str(row.get("local_path") or "") if selected else "",
            "best_score": float(row.get("quality_score") or 0.0),
            "quality_threshold": QUALITY_THRESHOLD,
            "repair_strategy": str(row.get("repair_strategy") or "initial"),
            "manifest": "manifests/shot_candidate_manifest.json",
            "judge_provider": str(row.get("judge_provider") or "openai-codex"),
            "judge_model": str(row.get("judge_model") or ""),
            "judge_response_id": str(
                (row.get("vision_evidence") or {}).get("response_id") or ""
            ),
        }
    return None


def _subtitle_packaging_fallback(shot: dict[str, Any]) -> dict[str, Any]:
    safe_area = str(shot.get("subtitle_safe_area") or "").strip().lower()
    position = "top" if "bottom" in safe_area or "lower" in safe_area else "bottom"
    return {
        "type": "adaptive_subtitle_band",
        "subtitle_position": position,
        "resolved_blocker_codes": ["subtitle_collision"],
    }


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


def _contract_replan_count(manifest: dict[str, Any], shot_id: str) -> int:
    return sum(
        1
        for row in manifest.get("contract_replans") or []
        if isinstance(row, dict) and str(row.get("shot_id") or "") == shot_id
    )


def _strategy_pivot_completed(manifest: dict[str, Any], shot_id: str) -> bool:
    return any(
        isinstance(row, dict)
        and str(row.get("shot_id") or "") == shot_id
        and row.get("strategy_pivot") is True
        for row in manifest.get("contract_replans") or []
    )


def _contract_replan_work(
    context: StoryVideoRunContext,
    *,
    shot_id: str,
    manifest: dict[str, Any],
    output: dict[str, Any],
    remaining_shot_count: int,
) -> dict[str, Any]:
    _ledger, _scene, shot = _find_shot(context, shot_id)
    revision = _contract_replan_count(manifest, shot_id)
    next_revision = revision + 1
    strategy_pivot_completed = _strategy_pivot_completed(manifest, shot_id)
    strategy_pivot = not strategy_pivot_completed and next_revision >= MAX_CONTRACT_REPLANS
    legacy_strategy_pivot_migration = bool(
        strategy_pivot and revision >= MAX_CONTRACT_REPLANS
    )
    blockers, normalized_codes = _source_image_qc_blockers(
        output.get("hard_blockers") or (),
        output.get("blocker_codes") or (),
    )
    blocker_codes = sorted(normalized_codes)
    if strategy_pivot_completed:
        return {
            "success": False,
            "action": "next_batch_work",
            "shot_id": shot_id,
            "work_status": "human_review_required",
            "status": "human_review_required",
            "error": "Automatic shot-contract replanning exhausted.",
            "replan_revision": revision,
            "max_replan_revisions": max(MAX_CONTRACT_REPLANS, revision),
            "hard_blockers": blockers,
            "blocker_codes": blocker_codes,
            "remaining_shot_count": remaining_shot_count,
        }
    return {
        "success": True,
        "action": "next_batch_work",
        "shot_id": shot_id,
        "work_status": "ready",
        "operation": "replan_shot_contract",
        "replan_revision": next_revision,
        "max_replan_revisions": max(MAX_CONTRACT_REPLANS, next_revision),
        "strategy_pivot": strategy_pivot,
        "legacy_strategy_pivot_migration": legacy_strategy_pivot_migration,
        "immutable_contract": {
            field: shot.get(field) for field in _REPLAN_IMMUTABLE_FIELDS
        },
        "current_mutable_contract": {
            field: shot.get(field) for field in _REPLAN_MUTABLE_FIELDS if field in shot
        },
        "mutable_fields": list(_REPLAN_MUTABLE_FIELDS),
        "hard_blockers": blockers,
        "blocker_codes": blocker_codes,
        "replan_directive": (
            (
                "This is the final bounded visual-strategy pivot. Preserve the approved "
                "narration, takeaway, and risk, but switch to a different representational "
                "family. Do not reuse the failed subject, symbol, geometry, composition, "
                "or medium. You may change visual_truth_mode when an honest physical-world "
                "analogy, inference, or directly observable consequence communicates the "
                "same fact more clearly than another literal reconstruction. Make the "
                "evidence bridge explicit and avoid invented anatomy or medical devices. "
            )
            if strategy_pivot
            else (
                "Preserve the approved narration, takeaway, truth mode, and risk. Replace "
                "the visual design with one coherent, directly readable moment whose "
                "visible evidence supports the same takeaway and avoids every listed "
                "blocker. "
            )
        ) + (
            "Judge the clean source image edge to edge; subtitle layout is a separate "
            "post-composite QC stage."
        ),
        "remaining_shot_count": remaining_shot_count,
    }


def _apply_shot_contract_replan(
    context: StoryVideoRunContext,
    *,
    shot_id: str,
    redesigned_shot: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(redesigned_shot, dict):
        raise ValueError("redesigned_shot must be an object")
    ledger, _scene, shot = _find_shot(context, shot_id)
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest = _load_json(manifest_path) or {}
    current_output = next(
        (
            row
            for row in manifest.get("outputs") or []
            if isinstance(row, dict) and str(row.get("shot_id") or "") == shot_id
        ),
        {},
    )
    next_work = _next_batch_work(context)
    if (
        str(next_work.get("shot_id") or "") != shot_id
        or next_work.get("work_status") != "ready"
        or next_work.get("operation") != "replan_shot_contract"
    ):
        raise ValueError(
            "shot-contract replanning is only allowed after visual repair "
            "strategies are exhausted"
        )
    revision = _contract_replan_count(manifest, shot_id) + 1
    strategy_pivot_completed = _strategy_pivot_completed(manifest, shot_id)
    if strategy_pivot_completed or revision > MAX_CONTRACT_REPLANS + 1:
        raise ValueError("automatic shot-contract replanning is exhausted")
    legacy_strategy_pivot_migration = revision > MAX_CONTRACT_REPLANS

    missing = [
        field
        for field in _REPLAN_REQUIRED_FIELDS
        if field not in redesigned_shot
        or redesigned_shot.get(field) in (None, "", [])
    ]
    if missing:
        raise ValueError(
            "redesigned_shot is missing required fields: " + ", ".join(missing)
        )
    scale = str(redesigned_shot.get("shot_scale") or "").strip()
    if scale not in _SHOT_SCALES:
        raise ValueError("redesigned_shot.shot_scale is invalid")
    criteria = redesigned_shot.get("acceptance_criteria")
    if not isinstance(criteria, list) or not all(
        isinstance(value, str) and value.strip() for value in criteria
    ):
        raise ValueError("redesigned_shot.acceptance_criteria must be non-empty strings")
    if "engagement_criteria" in redesigned_shot:
        engagement = redesigned_shot.get("engagement_criteria")
        if not isinstance(engagement, list) or not all(
            isinstance(value, str) and value.strip() for value in engagement
        ):
            raise ValueError("redesigned_shot.engagement_criteria must be strings")
    if "visual_truth_mode" in redesigned_shot:
        truth_mode = str(redesigned_shot.get("visual_truth_mode") or "").strip()
        if truth_mode not in VISUAL_TRUTH_MODES:
            raise ValueError("redesigned_shot.visual_truth_mode is invalid")

    old_hash = _shot_contract_hash(shot)
    replanned = dict(shot)
    for field in _REPLAN_MUTABLE_FIELDS:
        if field in redesigned_shot:
            value = redesigned_shot[field]
            if isinstance(value, str):
                value = value.strip()
            elif isinstance(value, list):
                value = [item.strip() for item in value]
            replanned[field] = value
    new_hash = _shot_contract_hash(replanned)
    if new_hash == old_hash:
        raise ValueError("redesigned_shot does not change the shot contract")

    original_shot = dict(shot)
    previous_violations = set(validate_quality_ledger(ledger).violations)
    shot.clear()
    shot.update(replanned)
    introduced_violations = [
        violation
        for violation in validate_quality_ledger(ledger).violations
        if violation not in previous_violations
        and violation.startswith("repeated_shot_scale_without_reason:")
    ]
    if introduced_violations:
        shot.clear()
        shot.update(original_shot)
        raise ValueError(
            "redesigned_shot introduces ledger quality violations: "
            + ", ".join(introduced_violations)
        )
    _write_json_atomic(context.project_dir / "scene_ledger.json", ledger)

    replans = [
        dict(row) for row in manifest.get("contract_replans") or [] if isinstance(row, dict)
    ]
    replans.append(
        {
            "event": "shot_contract_replanned",
            "shot_id": shot_id,
            "revision": revision,
            "old_shot_contract_hash": old_hash,
            "new_shot_contract_hash": new_hash,
            "superseded_candidate_id": str(current_output.get("candidate_id") or ""),
            "hard_blockers": [
                str(value) for value in current_output.get("hard_blockers") or [] if value
            ],
            "blocker_codes": [
                str(value) for value in current_output.get("blocker_codes") or [] if value
            ],
            "strategy_pivot": revision >= MAX_CONTRACT_REPLANS,
            "legacy_strategy_pivot_migration": legacy_strategy_pivot_migration,
            "replanned_at": _utc_now(),
        }
    )
    _write_candidate_manifest_atomic(
        manifest_path,
        {**manifest, "contract_replans": replans, "updated_at": _utc_now()},
    )
    next_work = _next_batch_work(context)
    return {
        **next_work,
        "replan_revision": revision,
        "strategy_pivot": revision >= MAX_CONTRACT_REPLANS,
        "legacy_strategy_pivot_migration": legacy_strategy_pivot_migration,
    }


def _auto_replan_shot_contract(
    context: StoryVideoRunContext,
    *,
    next_work: dict[str, Any],
    llm: Any,
) -> dict[str, Any]:
    shot_id = str(next_work.get("shot_id") or "").strip()
    if (
        not shot_id
        or next_work.get("work_status") != "ready"
        or next_work.get("operation") != "replan_shot_contract"
    ):
        return {
            "success": False,
            "work_status": "human_review_required",
            "shot_id": shot_id,
            "error": "No bounded shot-contract replan is available.",
        }
    if llm is None:
        return {
            "success": False,
            "work_status": "human_review_required",
            "shot_id": shot_id,
            "error": "Story-video contract replanner is unavailable.",
        }
    ledger, scene, _shot = _find_shot(context, shot_id)
    request = {
        "replan_revision": int(next_work.get("replan_revision") or 0),
        "strategy_pivot": bool(next_work.get("strategy_pivot")),
        "legacy_strategy_pivot_migration": bool(
            next_work.get("legacy_strategy_pivot_migration")
        ),
        "immutable_contract": next_work.get("immutable_contract") or {},
        "current_mutable_contract": next_work.get("current_mutable_contract") or {},
        "hard_blockers": next_work.get("hard_blockers") or [],
        "blocker_codes": next_work.get("blocker_codes") or [],
        "replan_directive": next_work.get("replan_directive") or "",
        "scene_context": scene,
        "style_bible": ledger.get("style_bible") or {},
    }
    strategy_pivot = bool(next_work.get("strategy_pivot"))
    pivot_instruction = (
        " This is the final bounded pivot: use a different representational family "
        "from the failed contract. Do not reuse its subject, symbol, geometry, "
        "composition, or medium. visual_truth_mode may change when the evidence bridge "
        "makes an analogy or inference explicit."
        if strategy_pivot
        else " Preserve the current visual_truth_mode for this first replan."
    )
    try:
        result = llm.complete_structured(
            instructions=(
                "Redesign one story-video source-image shot contract after bounded visual "
                "repairs failed. Preserve every immutable field. Make one decisive visible "
                "action and one focal subject readable in a single still image. The image "
                "only needs to support the primary viewer takeaway; secondary comparisons, "
                "caveats, and later causal steps remain in narration or adjacent shots. "
                "Do not require text labels, split-screen comparisons, UI, multiple time "
                "states, or one frame to prove every sentence. For scientific or medical "
                "reconstruction, separate literal anatomy from symbolic light or particles "
                "and keep acceptance criteria directly observable."
                + pivot_instruction
                + " Return only the schema."
            ),
            input=[
                {
                    "type": "text",
                    "text": json.dumps(request, ensure_ascii=False, sort_keys=True),
                }
            ],
            json_schema=SHOT_CONTRACT_REPLAN_SCHEMA,
            json_mode=True,
            schema_name="story_video_shot_contract_replan",
            provider="openai-codex",
            temperature=0,
            max_tokens=1800,
            timeout=180,
            purpose="story_video_shot_contract_replan",
        )
    except Exception as exc:
        return {
            "success": False,
            "work_status": "human_review_required",
            "shot_id": shot_id,
            "error": (
                "Automatic shot-contract replan failed: "
                f"{exc.__class__.__name__}: {exc}"
            ),
        }
    provider = _provider(getattr(result, "provider", ""))
    parsed = getattr(result, "parsed", None)
    redesigned = parsed.get("redesigned_shot") if isinstance(parsed, dict) else None
    if provider not in {"openai", "openai-codex"} or not isinstance(redesigned, dict):
        return {
            "success": False,
            "work_status": "human_review_required",
            "shot_id": shot_id,
            "error": "Automatic shot-contract replanner returned invalid OpenAI evidence.",
        }
    try:
        applied = _apply_shot_contract_replan(
            context,
            shot_id=shot_id,
            redesigned_shot=redesigned,
        )
    except (OSError, TypeError, ValueError) as exc:
        return {
            "success": False,
            "work_status": "human_review_required",
            "shot_id": shot_id,
            "error": f"Automatic shot-contract replan was rejected: {exc}",
        }
    if applied.get("success") is not True:
        return {
            **applied,
            "success": False,
            "work_status": "human_review_required",
            "shot_id": shot_id,
            "error": str(
                applied.get("error")
                or "Automatic shot-contract replan did not produce runnable work."
            ),
        }
    return {
        **applied,
        "success": True,
        "work_status": "in_progress",
        "shot_id": shot_id,
        "replan_provider": provider,
        "replan_model": str(getattr(result, "model", "") or ""),
        "replan_response_id": str(
            (getattr(result, "audit", {}) or {}).get("response_id") or ""
        ),
        "strategy_pivot": strategy_pivot,
        "legacy_strategy_pivot_migration": bool(
            next_work.get("legacy_strategy_pivot_migration")
        ),
    }


def _auto_replan_chunk_payload(
    context: StoryVideoRunContext,
    *,
    next_work: dict[str, Any],
    llm: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    replanned = _auto_replan_shot_contract(
        context,
        next_work=next_work,
        llm=llm,
    )
    if replanned.get("success") is True:
        return {
            **payload,
            "success": True,
            "action": "run_batch_chunk",
            "work_status": "in_progress",
            "wave": "contract_replan",
            "failed_shots": [],
            "replanned_shot_id": str(replanned.get("shot_id") or ""),
            "replan_revision": int(replanned.get("replan_revision") or 0),
            "replan_provider": str(replanned.get("replan_provider") or ""),
            "replan_model": str(replanned.get("replan_model") or ""),
            "replan_response_id": str(
                replanned.get("replan_response_id") or ""
            ),
            "strategy_pivot": bool(replanned.get("strategy_pivot")),
            "legacy_strategy_pivot_migration": bool(
                replanned.get("legacy_strategy_pivot_migration")
            ),
        }
    failed = {
        **payload,
        "success": False,
        "action": "run_batch_chunk",
        "work_status": "human_review_required",
        "review_shot_id": str(next_work.get("shot_id") or ""),
        "error": str(replanned.get("error") or "automatic replan failed"),
    }
    _persist_terminal_attention(
        context,
        shot_id=str(failed.get("review_shot_id") or ""),
        error=str(failed.get("error") or ""),
    )
    return failed


def _reconcile_manifest_contracts(
    context: StoryVideoRunContext,
    ledger: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], set[str]]:
    shots = {
        str(shot.get("shot_id") or ""): shot
        for scene in ledger.get("scenes") or []
        if isinstance(scene, dict)
        for shot in scene.get("shots") or []
        if isinstance(shot, dict) and str(shot.get("shot_id") or "").strip()
    }
    legacy_prompts = {
        str(row.get("shot_id") or ""): str(row.get("prompt") or "").strip()
        for row in manifest.get("shots") or []
        if isinstance(row, dict) and str(row.get("shot_id") or "").strip()
    }
    retained: list[dict[str, Any]] = []
    superseded: set[str] = set()
    events = [
        dict(row) for row in manifest.get("contract_events") or [] if isinstance(row, dict)
    ]
    event_keys = {
        (
            str(row.get("shot_id") or ""),
            str(row.get("candidate_id") or ""),
            str(row.get("new_shot_contract_hash") or ""),
        )
        for row in events
    }
    for row in manifest.get("outputs") or []:
        if not isinstance(row, dict):
            continue
        shot_id = str(row.get("shot_id") or "").strip()
        shot = shots.get(shot_id)
        if shot is None or _manifest_row_matches_shot_contract(
            row,
            shot,
            legacy_prompts.get(shot_id, ""),
        ):
            retained.append(row)
            continue
        superseded.add(shot_id)
        new_hash = _shot_contract_hash(shot)
        key = (shot_id, str(row.get("candidate_id") or ""), new_hash)
        if key not in event_keys:
            events.append(
                {
                    "event": "shot_contract_superseded",
                    "shot_id": shot_id,
                    "candidate_id": str(row.get("candidate_id") or ""),
                    "old_shot_contract_hash": str(
                        row.get("shot_contract_hash") or "legacy_unversioned"
                    ),
                    "new_shot_contract_hash": new_hash,
                    "detected_at": _utc_now(),
                }
            )
            event_keys.add(key)
    if not superseded:
        return manifest, superseded
    updated = {
        **manifest,
        "outputs": retained,
        "contract_events": events,
        "updated_at": _utc_now(),
    }
    _write_candidate_manifest_atomic(
        context.project_dir / "manifests" / "shot_candidate_manifest.json",
        updated,
    )
    return updated, superseded


def _compile_prompt(
    context: StoryVideoRunContext,
    *,
    shot_id: str,
) -> dict[str, Any]:
    ledger, scene, shot = _find_shot(context, shot_id)
    manifest = _load_json(
        context.project_dir / "manifests" / "shot_candidate_manifest.json"
    ) or {}
    contract_hash = _shot_contract_hash(shot)
    legacy_prompt = next(
        (
            str(row.get("prompt") or "").strip()
            for row in manifest.get("shots") or []
            if isinstance(row, dict) and str(row.get("shot_id") or "") == shot_id
        ),
        "",
    )
    all_history_rows = [
        _normalize_source_image_qc_row(row)
        for row in manifest.get("attempt_history") or []
        if isinstance(row, dict) and str(row.get("shot_id") or "") == shot_id
    ]
    all_current_rows = [
        _normalize_source_image_qc_row(row)
        for row in manifest.get("outputs") or []
        if isinstance(row, dict) and str(row.get("shot_id") or "") == shot_id
    ]
    history_rows = [
        row
        for row in all_history_rows
        if _manifest_row_matches_shot_contract(row, shot, legacy_prompt)
    ]
    current_rows = [
        row
        for row in all_current_rows
        if _manifest_row_matches_shot_contract(row, shot, legacy_prompt)
    ]
    contract_reset = len(history_rows) != len(all_history_rows) or len(current_rows) != len(
        all_current_rows
    )
    known_candidates = {
        str(row.get("candidate_id") or "") for row in history_rows
    }
    attempts = [*history_rows]
    attempts.extend(
        row
        for row in current_rows
        if str(row.get("candidate_id") or "") not in known_candidates
    )
    attempts.sort(key=lambda row: str(row.get("reviewed_at") or ""))
    sequence_pending = next(
        (row for row in reversed(current_rows) if row.get("sequence_rescue_pending") is True),
        None,
    )
    previous = sequence_pending or (attempts[-1] if attempts else None)
    blockers = [
        str(item).strip()
        for item in (previous or {}).get("hard_blockers") or []
        if str(item).strip()
    ]
    repair_plan = plan_repair([sequence_pending] if sequence_pending is not None else attempts)
    if repair_plan.exhausted:
        return {
            "success": False,
            "action": "compile_prompt",
            "shot_id": shot_id,
            "status": "human_review_required",
            "hard_blockers": blockers,
            "blocker_codes": list(repair_plan.blocker_codes),
            "error": repair_plan.directive,
        }
    effective_shot = apply_repair_strategy(
        shot,
        repair_plan.strategy,
        blocker_codes=repair_plan.blocker_codes,
    )
    prompt = compile_shot_prompt(
        ledger=ledger,
        scene=scene,
        shot=effective_shot,
    )
    if blockers:
        prompt += (
            " Prior QC blocker(s): "
            + "; ".join(blockers)
            + "."
        )
    if sequence_pending is not None:
        prompt += (
            " Sequence-level QC rescue: create a materially distinct current artifact "
            "that fixes the listed sequence defect while preserving the shot contract."
        )
    prompt += f" Adaptive repair strategy: {repair_plan.strategy}. {repair_plan.directive}"
    revision = f"{contract_hash[:8].upper()}_" if contract_reset else ""
    candidate_id_hint = (
        f"{shot_id}_SEQUENCE_RESCUE_C01"
        if sequence_pending is not None
        else f"{shot_id}_{revision}{repair_plan.candidate_suffix}"
    )
    prompt_path = context.project_dir / "prompts" / f"{shot_id}.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    source_image_url = ""
    source_candidate_id = ""
    if repair_plan.strategy == "targeted_repair" and previous is not None:
        source_path = _project_path(
            context,
            previous.get("candidate_path") or previous.get("local_path"),
        )
        if (
            _provider(previous.get("provider")) in {"openai", "openai-codex"}
            and source_path.is_file()
        ):
            source_image_url = str(source_path)
            source_candidate_id = str(previous.get("candidate_id") or "")
    result = {
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
        "hard_blockers": blockers,
        "repair_strategy": repair_plan.strategy,
        "blocker_codes": list(repair_plan.blocker_codes),
        "strategy_reset": repair_plan.strategy == "layout_reset",
        "remaining_strategy_reset_candidates": (
            1 if repair_plan.strategy == "layout_reset" else 0
        ),
        "candidate_id_hint": candidate_id_hint,
        "shot_contract_hash": contract_hash,
        "contract_reset": contract_reset,
        "effective_shot_contract": effective_shot,
        "generation_mode": "image_edit" if source_image_url else "text_to_image",
        "sequence_rescue": sequence_pending is not None,
    }
    style_anchor_path = _style_anchor_source(
        context,
        ledger=ledger,
        manifest=manifest,
        current_shot_id=shot_id,
    )
    if style_anchor_path is not None:
        result.update({
            "reference_image_urls": [str(style_anchor_path)],
            "style_reference_policy": "style_only_do_not_copy_subject_or_composition",
        })
    if source_image_url:
        result.update({
            "source_image_url": source_image_url,
            "source_candidate_id": source_candidate_id,
        })
    return result


def _style_anchor_source(
    context: StoryVideoRunContext,
    *,
    ledger: dict[str, Any],
    manifest: dict[str, Any],
    current_shot_id: str,
) -> Path | None:
    bible = ledger.get("style_bible")
    if not isinstance(bible, dict):
        return None
    anchor_shot_id = str(bible.get("anchor_shot_id") or "").strip()
    if not anchor_shot_id or anchor_shot_id == current_shot_id:
        return None
    for row in manifest.get("outputs") or []:
        if (
            not isinstance(row, dict)
            or str(row.get("shot_id") or "").strip() != anchor_shot_id
            or row.get("selected") is not True
            or str(row.get("status") or "") != "selected_current"
            or _provider(row.get("provider")) not in {"openai", "openai-codex"}
        ):
            continue
        path = _project_path(
            context,
            row.get("local_path") or row.get("candidate_path"),
        )
        if path.is_file():
            return path
    return None


def _review_instructions(
    shot: dict[str, Any],
    candidate_ids: list[str],
    *,
    style_bible: dict[str, Any] | None = None,
    has_style_anchor: bool = False,
) -> str:
    shot_specific: list[str] = []
    if is_camera_reveal_shot(shot):
        shot_specific.append(
            "This is a source frame for a camera reveal. Do not require camera motion "
            "to be visible inside the still; judge the environmental reveal, attention "
            "path, depth hierarchy, and readable aftermath state that the renderer will animate."
        )
    if str(shot.get("visual_truth_mode") or "").strip() == "reconstruction":
        shot_specific.append(
            "A coherent reconstruction may contain the declared environmental evidence. "
            "Use mixed_evidence_reconstruction only when the frame falsely presents a "
            "reconstruction as a preserved specimen or direct observation, not merely "
            "because grounded evidence appears within the reconstructed environment."
        )
    return "\n".join(
        (
            "You are the independent visual quality judge for a professional story video.",
            "Inspect every candidate image and score only what is visibly supported.",
            "The generation provider and the judging provider are both required to be OpenAI.",
            f"Shot contract: {json.dumps(shot, ensure_ascii=False, sort_keys=True)}",
            f"Style bible: {json.dumps(style_bible or {}, ensure_ascii=False, sort_keys=True)}",
            (
                "Style reference image appears before candidate images. Compare medium, "
                "palette, lighting, lens language, texture, atmosphere, and subject treatment; "
                "do not require the candidate to copy its subject or composition."
                if has_style_anchor
                else "No visual style reference is available yet; judge against the textual style bible."
            ),
            f"Candidate image order: {json.dumps(candidate_ids, ensure_ascii=False)}",
            "Hard blockers include wrong spoken-claim content, scientific contradiction, malformed anatomy or geometry, generated text/watermark, unclear focus, an image that adds no information beyond adjacent shots, static_catalog, missing_story_moment, flat_composition, generic documentary or museum-catalog framing, audience_mismatch, sensationalized_claim, mixed_evidence_reconstruction, and style_drift. Subtitle placement is not part of source-image QC because typography is added in post-composite rendering.",
            "Score narrative_engagement from the artifact's attention path, purposeful visual progression, and audience fit. High energy is not inherently better.",
            "Score story_moment_clarity from whether one decisive instant and its immediate consequence are visibly understandable.",
            "Score cinematic_impact from bold depth hierarchy, dramatic but motivated light, scale, visual tension, and a hero subject that immediately earns attention without changing factual content.",
            "Score style_consistency from visible adherence to the locked style bible and, when supplied, the style reference image. Reject a different medium, palette family, lighting logic, lens language, texture treatment, or subject rendering as style_drift even if the isolated image is attractive.",
            "Intentional calm or breathe shots may score highly when the declared calm_reason is supported by a strong focal hierarchy and useful pause; calm alone is not static_catalog.",
            *shot_specific,
            "For every hard blocker, return one or more blocker_codes from: "
            + ", ".join(sorted(BLOCKER_CODES - {"subtitle_collision"}))
            + ". Never return subtitle_collision; subtitles are absent from source-image QC.",
            "Return one row for every candidate id. Scores use 0-100. Also return focal_point_normalized as the center of the most important visible subject or evidence, with x and y in the inclusive 0-1 range. Evidence must cite concrete visible observations, not metadata or prompt intent.",
        )
    )


def _camera_reveal_rejudge_work(
    context: StoryVideoRunContext,
    *,
    shot_id: str,
    manifest: dict[str, Any],
    remaining_shot_count: int,
    legacy_prompt: str,
) -> dict[str, Any] | None:
    _ledger, _scene, shot = _find_shot(context, shot_id)
    if not is_camera_reveal_shot(shot):
        return None
    history = [
        row
        for row in manifest.get("attempt_history") or []
        if isinstance(row, dict)
        and str(row.get("shot_id") or "") == shot_id
        and _manifest_row_matches_shot_contract(row, shot, legacy_prompt)
    ]
    if not history or not plan_repair(history).exhausted:
        return None
    review_suffix = "_CAMERA_REVEAL_REVIEW"
    if any(str(row.get("candidate_id") or "").endswith(review_suffix) for row in history):
        return None
    latest_codes = classify_blockers(
        history[-1].get("hard_blockers") or (),
        history[-1].get("blocker_codes") or (),
    )
    recoverable_codes = {
        "missing_story_moment",
        "audience_mismatch",
        "flat_composition",
        "static_catalog",
    }
    if str(shot.get("visual_truth_mode") or "").strip() == "reconstruction":
        recoverable_codes.add("mixed_evidence_reconstruction")
    if not latest_codes or not latest_codes.issubset(recoverable_codes):
        return None
    eligible: list[tuple[float, dict[str, Any], Path]] = []
    for row in history:
        blockers = [str(item).strip() for item in row.get("hard_blockers") or [] if str(item).strip()]
        evidence = row.get("vision_evidence")
        score = float(row.get("quality_score") or 0.0)
        if (
            row.get("selected") is not True
            or blockers
            or score < QUALITY_THRESHOLD
            or _provider(row.get("provider")) not in {"openai", "openai-codex"}
            or not isinstance(evidence, dict)
            or evidence.get("status") != "PASS"
            or not str(evidence.get("response_id") or "").strip()
        ):
            continue
        candidate_path = _project_path(
            context,
            row.get("candidate_path") or row.get("local_path"),
        )
        if candidate_path.is_file():
            eligible.append((score, row, candidate_path))
    if not eligible:
        return None
    _score, previous, candidate_path = max(eligible, key=lambda item: item[0])
    previous_id = str(previous.get("candidate_id") or shot_id).strip()
    return {
        "success": True,
        "action": "next_batch_work",
        "work_status": "ready",
        "operation": "rejudge_existing",
        "shot_id": shot_id,
        "candidate_budget": 0,
        "quality_threshold": QUALITY_THRESHOLD,
        "candidate": {
            "candidate_id": f"{previous_id}{review_suffix}",
            "path": _relative(context, candidate_path),
            "provider": _provider(previous.get("provider")),
            "model": str(previous.get("model") or ""),
            "response_id": str(previous.get("generation_response_id") or ""),
            "shot_contract_hash": _shot_contract_hash(shot),
            "repair_strategy": "camera_reveal_policy_review",
            "generation_prompt": str(
                previous.get("generation_prompt")
                or previous.get("prompt")
                or legacy_prompt
                or ""
            ).strip(),
        },
        "repair_round": int(previous.get("repair_round") or 1),
        "remaining_shot_count": remaining_shot_count,
        "recovery_reason": "camera_reveal_source_frame_policy_review",
    }


def _image_input(path: Path) -> dict[str, Any]:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return {
        "type": "image",
        "data": path.read_bytes(),
        "mime_type": mime,
        "file_name": path.name,
    }


def _repair_convergence_stalled(
    attempts: list[dict[str, Any]],
    *,
    shot_id: str,
    repair_strategy: str,
    score: float,
    blocker_codes: set[str],
) -> bool:
    if repair_strategy not in {"initial", "targeted_repair"} or not blocker_codes:
        return False
    for row in reversed(attempts):
        if str(row.get("shot_id") or "") != shot_id:
            continue
        previous_score = row.get("quality_score")
        if not isinstance(previous_score, (int, float)):
            continue
        previous_codes = classify_blockers(
            row.get("hard_blockers") or (),
            row.get("blocker_codes") or (),
        )
        if blocker_codes & previous_codes:
            return score < float(previous_score) + 2.0
    return False


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
    candidate_strategy = next(
        (
            str(row.get("repair_strategy") or "").strip()
            for row in candidates
            if str(row.get("repair_strategy") or "").strip()
        ),
        "",
    )
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
    contract_hash = _shot_contract_hash(shot)
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
        candidate_contract_hash = str(candidate.get("shot_contract_hash") or "").strip()
        if not candidate_contract_hash:
            return {
                "success": False,
                "error_type": "story_video_candidate_contract_hash_missing",
                "error": f"candidate {candidate_id} has no shot_contract_hash",
            }
        if candidate_contract_hash != contract_hash:
            return {
                "success": False,
                "error_type": "story_video_candidate_contract_superseded",
                "error": f"candidate {candidate_id} belongs to an older shot contract",
                "expected_shot_contract_hash": contract_hash,
                "candidate_shot_contract_hash": candidate_contract_hash,
            }
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

    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    manifest = _load_json(manifest_path) or {
        "schema": "story_video_shot_candidate_manifest_v1",
        "provider": "openai-codex",
        "judge_provider": "openai-codex",
        "quality_threshold": QUALITY_THRESHOLD,
        "outputs": [],
        "attempt_history": [],
    }
    artifact_hashes = {
        candidate_id: _file_sha256(path)
        for candidate_id, path in candidate_paths.items()
    }
    if len(candidate_rows) == 1:
        cached = _cached_qc_result(
            context,
            manifest,
            shot_id=shot_id,
            contract_hash=contract_hash,
            artifact_sha256=artifact_hashes[candidate_rows[0]["candidate_id"]],
        )
        if cached is not None:
            return cached

    bound_prompts = {
        str(row.get("prompt") or row.get("generation_prompt") or "").strip()
        for row in candidate_rows
        if str(row.get("prompt") or row.get("generation_prompt") or "").strip()
    }
    if len(bound_prompts) > 1:
        return {
            "success": False,
            "error_type": "story_video_candidate_prompt_ambiguous",
            "error": "Candidates must share one bound compiled generation prompt.",
        }
    if bound_prompts:
        bound_prompt = bound_prompts.pop()
        prompt_path = context.project_dir / "prompts" / f"{shot_id}.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(bound_prompt + "\n", encoding="utf-8")
        prompt_info = {
            "success": True,
            "prompt": bound_prompt,
            "prompt_path": _relative(context, prompt_path),
            "effective_shot_contract": shot,
            "repair_strategy": candidate_strategy or "initial",
            "bound_candidate_prompt": True,
        }
    else:
        prompt_info = _compile_prompt(context, shot_id=shot_id)
        if not prompt_info.get("success"):
            return {
                **prompt_info,
                "success": False,
                "error_type": "story_video_candidate_prompt_unavailable",
                "error": (
                    "The repair plan changed after generation and the candidate has no "
                    "single bound compiled prompt. Regenerate through compile_prompt."
                ),
            }
    repair_strategy = candidate_strategy or str(
        prompt_info.get("repair_strategy") or "targeted_repair"
    )
    if strategy_reset and not candidate_strategy:
        repair_strategy = "layout_reset"
    candidate_ids = [str(row["candidate_id"]) for row in candidate_rows]
    style_anchor_path = _style_anchor_source(
        context,
        ledger=ledger,
        manifest=manifest,
        current_shot_id=shot_id,
    )
    inputs: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Compiled source-art prompt: {prompt_info['prompt']}\n"
                f"Scene context: {json.dumps(scene, ensure_ascii=False, sort_keys=True)}"
            ),
        }
    ]
    if style_anchor_path is not None:
        inputs.extend(
            (
                {
                    "type": "text",
                    "text": "Approved style reference image; compare style only, not subject or composition.",
                },
                _image_input(style_anchor_path),
                {"type": "text", "text": "Candidate image follows."},
            )
        )
    inputs.extend(_image_input(candidate_paths[candidate_id]) for candidate_id in candidate_ids)
    if llm is None:
        return {
            "success": False,
            "error_type": "story_video_visual_judge_unavailable",
            "error": "story-video plugin LLM is not configured",
        }
    try:
        result = llm.complete_structured(
            instructions=_review_instructions(
                prompt_info.get("effective_shot_contract") or shot,
                candidate_ids,
                style_bible=(
                    ledger.get("style_bible")
                    if isinstance(ledger.get("style_bible"), dict)
                    else None
                ),
                has_style_anchor=style_anchor_path is not None,
            ),
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
    content_profile = _load_json(context.project_dir / "content_profile.json") or {}
    require_sequence_dimensions = (
        str(content_profile.get("review_profile_id") or "").strip()
        == EDITORIAL_PROFILE_ID
    )
    dimension_blocker_codes = {
        "semantic": "audience_mismatch",
        "story": "missing_story_moment",
        "cinematic": "flat_composition",
        "style": "style_drift",
    }
    assessments: list[dict[str, Any]] = []
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        source = next(item for item in candidate_rows if item["candidate_id"] == candidate_id)
        hard_blockers, blocker_codes = _source_image_qc_blockers(
            row.get("hard_blockers") or (),
            row.get("blocker_codes") or (),
        )
        if require_sequence_dimensions:
            for violation in sequence_dimension_violations(row.get("dimensions")):
                if violation not in hard_blockers:
                    hard_blockers.append(violation)
                group = violation.split(" ", 1)[0]
                blocker_codes.add(dimension_blocker_codes[group])
        assessments.append(
            {
                **row,
                "hard_blockers": hard_blockers,
                "blocker_codes": sorted(blocker_codes),
                "provider": source.get("provider"),
                "judge_provider": judge_provider,
            }
        )
    decision = rank_candidate_assessments(assessments, threshold=QUALITY_THRESHOLD)
    selected_path = context.project_dir / "images" / f"{shot_id}.png"
    prior_attempts = [
        row
        for row in (manifest.get("attempt_history") or manifest.get("outputs") or [])
        if isinstance(row, dict)
        and str(row.get("shot_id") or "") == shot_id
        and _manifest_row_matches_shot_contract(row, shot)
    ]
    previous = [
        row
        for row in manifest.get("outputs") or []
        if isinstance(row, dict) and str(row.get("shot_id") or "") != shot_id
    ]
    current_rows: list[dict[str, Any]] = []
    selected_id = decision.selected_candidate_id
    pivot_strategy = repair_strategy in {
        "layout_reset",
        "evidence_reframe",
        "contextual_replan",
        "documentary_context",
        "story_reframe",
        "audience_reframe",
        "truth_reframe",
        "style_reframe",
    }
    best_assessment = max(
        assessments,
        key=lambda row: candidate_quality_score(row.get("dimensions")) or 0.0,
    )
    best_assessment_score = (
        candidate_quality_score(best_assessment.get("dimensions")) or 0.0
    )
    exhausted_after_current = plan_repair([
        *prior_attempts,
        {
            "shot_id": shot_id,
            "status": "quality_budget_exhausted",
            "repair_strategy": repair_strategy,
            "hard_blockers": best_assessment.get("hard_blockers") or [],
            "blocker_codes": best_assessment.get("blocker_codes") or [],
        },
    ]).exhausted
    _best_blockers, best_blocker_codes = _source_image_qc_blockers(
        best_assessment.get("hard_blockers") or (),
        best_assessment.get("blocker_codes") or (),
    )
    packaging_fallback_selected = bool(
        not selected_id
        and best_assessment_score >= QUALITY_THRESHOLD
        and best_blocker_codes == {"subtitle_collision"}
        and exhausted_after_current
    )
    if packaging_fallback_selected:
        selected_id = str(best_assessment.get("candidate_id") or "")
    best_effort_selected = bool(
        not selected_id
        and not (best_assessment.get("hard_blockers") or [])
        and best_assessment_score >= BEST_EFFORT_QUALITY_FLOOR
        and exhausted_after_current
    )
    if best_effort_selected:
        selected_id = str(best_assessment.get("candidate_id") or "")
    if selected_id:
        selected_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate_paths[selected_id], selected_path)
    convergence_stalled = not selected_id and _repair_convergence_stalled(
        prior_attempts,
        shot_id=shot_id,
        repair_strategy=repair_strategy,
        score=best_assessment_score,
        blocker_codes=_source_image_qc_blockers(
            best_assessment.get("hard_blockers") or (),
            best_assessment.get("blocker_codes") or (),
        )[1],
    )
    terminal_status = (
        "selected_current"
        if selected_id
        else "quality_budget_exhausted"
        if repair_round >= MAX_REPAIR_ROUNDS or pivot_strategy or convergence_stalled
        else "repair_required"
    )
    for assessment in assessments:
        candidate_id = str(assessment.get("candidate_id") or "")
        source = next(item for item in candidate_rows if item["candidate_id"] == candidate_id)
        score = candidate_quality_score(assessment.get("dimensions")) or 0.0
        blockers, normalized_codes = _source_image_qc_blockers(
            assessment.get("hard_blockers") or (),
            assessment.get("blocker_codes") or (),
        )
        blocker_codes = sorted(normalized_codes)
        selected_with_packaging = bool(
            candidate_id == selected_id and packaging_fallback_selected
        )
        current_rows.append(
            {
                "shot_id": shot_id,
                "shot_scale": str(shot.get("shot_scale") or ""),
                "shot_contract_hash": contract_hash,
                "artifact_sha256": artifact_hashes[candidate_id],
                "quality_contract_version": QUALITY_CONTRACT_VERSION,
                "style_id": str(
                    ledger["style_bible"].get("style_id") or ""
                    if isinstance(ledger.get("style_bible"), dict)
                    else ""
                ),
                "style_anchor_path": (
                    _relative(context, style_anchor_path)
                    if style_anchor_path is not None
                    else ""
                ),
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
                "generation_prompt": str(prompt_info["prompt"]),
                "candidate_path": _relative(context, candidate_paths[candidate_id]),
                "local_path": (
                    _relative(context, selected_path)
                    if candidate_id == selected_id
                    else _relative(context, candidate_paths[candidate_id])
                ),
                "quality_score": score,
                "hard_blockers": [] if selected_with_packaging else blockers,
                "blocker_codes": [] if selected_with_packaging else blocker_codes,
                "image_qc_blockers": blockers if selected_with_packaging else [],
                "image_qc_blocker_codes": (
                    blocker_codes if selected_with_packaging else []
                ),
                "packaging_fallback": (
                    _subtitle_packaging_fallback(shot)
                    if selected_with_packaging
                    else None
                ),
                "quality_dimensions": assessment.get("dimensions"),
                "focal_point_normalized": assessment.get("focal_point_normalized"),
                "vision_evidence": {
                    "status": "PASS",
                    "response_id": response_id,
                    "evidence": assessment.get("evidence") or [],
                },
                "repair_round": repair_round,
                "repair_strategy": repair_strategy,
                "strategy_reset": repair_strategy == "layout_reset",
                "convergence_stalled": convergence_stalled,
                "best_effort_selected": best_effort_selected,
                "reviewed_at": _utc_now(),
            }
        )
    history = [
        row for row in manifest.get("attempt_history") or [] if isinstance(row, dict)
    ]
    history_keys = {
        (str(row.get("shot_id") or ""), str(row.get("candidate_id") or ""))
        for row in history
    }
    for row in manifest.get("outputs") or []:
        if not isinstance(row, dict):
            continue
        key = (str(row.get("shot_id") or ""), str(row.get("candidate_id") or ""))
        if key not in history_keys:
            history.append(row)
            history_keys.add(key)
    for row in current_rows:
        key = (str(row.get("shot_id") or ""), str(row.get("candidate_id") or ""))
        if key not in history_keys:
            history.append(row)
            history_keys.add(key)
    manifest.update(
        {
            "phase": context.phase,
            "provider": "openai-codex",
            "judge_provider": "openai-codex",
            "quality_threshold": QUALITY_THRESHOLD,
            "outputs": sorted(
                [*previous, *current_rows],
                key=lambda row: (str(row.get("shot_id") or ""), str(row.get("candidate_id") or "")),
            ),
            "attempt_history": history,
            "updated_at": _utc_now(),
        }
    )
    _write_candidate_manifest_atomic(manifest_path, manifest)
    status = (
        "selected"
        if selected_id
        else "quality_budget_exhausted"
        if repair_round >= MAX_REPAIR_ROUNDS or pivot_strategy or convergence_stalled
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
        "repair_strategy": repair_strategy,
        "strategy_reset": repair_strategy == "layout_reset",
        "convergence_stalled": convergence_stalled,
        "best_effort_selected": best_effort_selected,
        "packaging_fallback_selected": packaging_fallback_selected,
        "best_effort_quality_floor": BEST_EFFORT_QUALITY_FLOOR,
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


def _ordered_shot_ids(context: StoryVideoRunContext) -> list[str]:
    ledger = _load_json(context.project_dir / "scene_ledger.json")
    if not isinstance(ledger, dict):
        raise ValueError("scene_ledger.json is missing or invalid")
    shot_ids: list[str] = []
    for scene in ledger.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for shot in scene.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            shot_id = str(shot.get("shot_id") or "").strip()
            if shot_id:
                shot_ids.append(shot_id)
    if not shot_ids:
        raise ValueError("scene_ledger.json has no shots")
    return shot_ids


def _grandfather_clean_legacy_selections(
    context: StoryVideoRunContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    outputs = [dict(row) for row in manifest.get("outputs") or [] if isinstance(row, dict)]
    events = [dict(row) for row in manifest.get("selection_events") or [] if isinstance(row, dict)]
    event_keys = {
        (
            str(row.get("event") or ""),
            str(row.get("shot_id") or ""),
            str(row.get("candidate_id") or ""),
        )
        for row in events
    }
    legacy_prompts = {
        str(row.get("shot_id") or ""): str(row.get("prompt") or "").strip()
        for row in manifest.get("shots") or []
        if isinstance(row, dict)
    }
    changed = False
    for row in outputs:
        dimensions = row.get("quality_dimensions")
        if (
            row.get("selected") is not True
            or row.get("legacy_qc_grandfathered") is True
            or _provider(row.get("provider")) not in {"openai", "openai-codex"}
            or not isinstance(dimensions, dict)
            or (
                "narrative_engagement" in dimensions
                and "story_moment_clarity" in dimensions
            )
            or row.get("hard_blockers")
            or (row.get("vision_evidence") or {}).get("status") != "PASS"
        ):
            continue
        shot_id = str(row.get("shot_id") or "").strip()
        candidate_id = str(row.get("candidate_id") or "").strip()
        try:
            _ledger, _scene, shot = _find_shot(context, shot_id)
        except ValueError:
            continue
        if not _manifest_row_matches_shot_contract(
            row,
            shot,
            legacy_prompts.get(shot_id, ""),
        ):
            continue
        score = float(row.get("quality_score") or 0.0)
        if score < BEST_EFFORT_QUALITY_FLOOR:
            continue
        candidate_path = _project_path(
            context,
            row.get("local_path") or row.get("candidate_path"),
        )
        if not candidate_path.is_file():
            continue
        row.update({
            "legacy_qc_grandfathered": True,
            "quality_contract_version": int(row.get("quality_contract_version") or 2),
            "accepted_under_quality_contract_version": QUALITY_CONTRACT_VERSION,
            "grandfathered_at": _utc_now(),
        })
        key = ("legacy_qc_grandfathered", shot_id, candidate_id)
        if key not in event_keys:
            events.append({
                "event": "legacy_qc_grandfathered",
                "shot_id": shot_id,
                "candidate_id": candidate_id,
                "quality_score": score,
                "accepted_under_quality_contract_version": QUALITY_CONTRACT_VERSION,
                "selected_at": _utc_now(),
            })
            event_keys.add(key)
        changed = True
    if not changed:
        return manifest
    updated = {
        **manifest,
        "outputs": outputs,
        "selection_events": events,
        "updated_at": _utc_now(),
    }
    _write_candidate_manifest_atomic(
        context.project_dir / "manifests" / "shot_candidate_manifest.json",
        updated,
    )
    return updated


def _promote_bounded_best_effort(
    context: StoryVideoRunContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    outputs = [
        _normalize_source_image_qc_row(row)
        for row in manifest.get("outputs") or []
        if isinstance(row, dict)
    ]
    history = [
        _normalize_source_image_qc_row(row)
        for row in manifest.get("attempt_history") or []
        if isinstance(row, dict)
    ]
    events = [dict(row) for row in manifest.get("selection_events") or [] if isinstance(row, dict)]
    event_keys = {
        (str(row.get("shot_id") or ""), str(row.get("candidate_id") or ""))
        for row in events
    }
    changed = False
    for row in outputs:
        shot_id = str(row.get("shot_id") or "").strip()
        candidate_id = str(row.get("candidate_id") or "").strip()
        try:
            _ledger, _scene, current_shot = _find_shot(context, shot_id)
        except ValueError:
            continue
        legacy_prompt = next(
            (
                str(item.get("prompt") or "").strip()
                for item in manifest.get("shots") or []
                if isinstance(item, dict)
                and str(item.get("shot_id") or "") == shot_id
            ),
            "",
        )
        shot_history = [
            attempt
            for attempt in history
            if str(attempt.get("shot_id") or "") == shot_id
            and _manifest_row_matches_shot_contract(
                attempt,
                current_shot,
                legacy_prompt,
            )
        ]
        blockers = [str(item) for item in row.get("hard_blockers") or []]
        blocker_codes = classify_blockers(
            blockers,
            row.get("blocker_codes") or (),
        )
        score = float(row.get("quality_score") or 0.0)
        clean_best_effort = not blockers and score >= BEST_EFFORT_QUALITY_FLOOR
        packaging_best_effort = bool(
            blockers
            and blocker_codes == {"subtitle_collision"}
            and score >= QUALITY_THRESHOLD
        )
        max_candidates = (
            MAX_REPLANNED_CONTRACT_CANDIDATES
            if _contract_replan_count(manifest, shot_id)
            else MAX_REPAIR_ROUNDS
        )
        contract_candidate_budget_exhausted = len(shot_history) >= max_candidates
        terminal_quality_status = str(row.get("status") or "") == (
            "quality_budget_exhausted"
        ) or (
            str(row.get("status") or "") == "repair_required"
            and contract_candidate_budget_exhausted
        )
        selection_floor = (
            QUALITY_THRESHOLD if packaging_best_effort else BEST_EFFORT_QUALITY_FLOOR
        )
        if (
            not shot_id
            or not candidate_id
            or row.get("selected") is True
            or not terminal_quality_status
            or _provider(row.get("provider")) not in {"openai", "openai-codex"}
            or not (clean_best_effort or packaging_best_effort)
            or (row.get("vision_evidence") or {}).get("status") != "PASS"
            or not (
                plan_repair(shot_history).exhausted
                or contract_candidate_budget_exhausted
            )
        ):
            continue
        candidate_path = _project_path(
            context,
            row.get("candidate_path") or row.get("local_path"),
        )
        if not candidate_path.is_file():
            continue
        selected_path = context.project_dir / "images" / f"{shot_id}.png"
        selected_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate_path, selected_path)
        row.update({
            "selected": True,
            "status": "selected_current",
            "local_path": _relative(context, selected_path),
            "best_effort_selected": True,
            "best_effort_quality_floor": selection_floor,
        })
        if packaging_best_effort:
            _ledger, _scene, shot = _find_shot(context, shot_id)
            row.update({
                "hard_blockers": [],
                "blocker_codes": [],
                "image_qc_blockers": blockers,
                "image_qc_blocker_codes": sorted(blocker_codes),
                "packaging_fallback": _subtitle_packaging_fallback(shot),
            })
        key = (shot_id, candidate_id)
        if key not in event_keys:
            events.append({
                "shot_id": shot_id,
                "candidate_id": candidate_id,
                "event": (
                    "packaging_fallback_selected"
                    if packaging_best_effort
                    else "bounded_best_effort_selected"
                ),
                "quality_score": score,
                "quality_floor": selection_floor,
                "selected_at": _utc_now(),
            })
            event_keys.add(key)
        changed = True
    if not changed:
        return manifest
    updated = {
        **manifest,
        "outputs": outputs,
        "selection_events": events,
        "updated_at": _utc_now(),
    }
    _write_candidate_manifest_atomic(
        context.project_dir / "manifests" / "shot_candidate_manifest.json",
        updated,
    )
    return updated


def _terminal_fallback_source(
    context: StoryVideoRunContext,
    *,
    target_shot_id: str,
    shot_ids: list[str],
    outputs: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> tuple[dict[str, Any], Path, str] | None:
    target_index = shot_ids.index(target_shot_id)
    _ledger, target_scene, _shot = _find_shot(context, target_shot_id)
    target_scene_id = str(target_scene.get("scene_id") or "")
    continuity_sources: list[tuple[tuple[int, int, int], dict[str, Any], Path]] = []
    for row in outputs:
        source_shot_id = str(row.get("shot_id") or "").strip()
        if (
            source_shot_id == target_shot_id
            or source_shot_id not in shot_ids
            or row.get("selected") is not True
            or _provider(row.get("provider")) not in {"openai", "openai-codex"}
        ):
            continue
        source_path = _project_path(
            context,
            row.get("local_path") or row.get("candidate_path"),
        )
        if not source_path.is_file():
            continue
        try:
            _source_ledger, source_scene, _source_shot = _find_shot(
                context,
                source_shot_id,
            )
        except ValueError:
            continue
        source_index = shot_ids.index(source_shot_id)
        rank = (
            0 if str(source_scene.get("scene_id") or "") == target_scene_id else 1,
            0 if source_index < target_index else 1,
            abs(target_index - source_index),
        )
        continuity_sources.append((rank, row, source_path))
    if continuity_sources:
        _rank, row, source_path = min(continuity_sources, key=lambda item: item[0])
        return row, source_path, "continuity_hold"

    best_available: list[tuple[float, dict[str, Any], Path]] = []
    for row in history:
        if (
            str(row.get("shot_id") or "") != target_shot_id
            or _provider(row.get("provider")) not in {"openai", "openai-codex"}
            or (row.get("vision_evidence") or {}).get("status") != "PASS"
        ):
            continue
        source_path = _project_path(
            context,
            row.get("local_path") or row.get("candidate_path"),
        )
        if source_path.is_file():
            best_available.append(
                (float(row.get("quality_score") or 0.0), row, source_path)
            )
    if not best_available:
        return None
    _score, row, source_path = max(best_available, key=lambda item: item[0])
    return row, source_path, "best_available_draft"


def _promote_auto_terminal_fallbacks(
    context: StoryVideoRunContext,
    manifest: dict[str, Any],
    *,
    shot_ids: list[str],
    force_exhausted_shot_ids: Iterable[str] = (),
) -> dict[str, Any]:
    if not context.auto_mode:
        return manifest
    outputs = [dict(row) for row in manifest.get("outputs") or [] if isinstance(row, dict)]
    history = [dict(row) for row in manifest.get("attempt_history") or [] if isinstance(row, dict)]
    events = [dict(row) for row in manifest.get("selection_events") or [] if isinstance(row, dict)]
    by_shot = {
        str(row.get("shot_id") or ""): row
        for row in outputs
        if str(row.get("shot_id") or "")
    }
    legacy_prompts = {
        str(row.get("shot_id") or ""): str(row.get("prompt") or "").strip()
        for row in manifest.get("shots") or []
        if isinstance(row, dict)
    }
    changed = False
    forced = {str(value) for value in force_exhausted_shot_ids if str(value)}
    for shot_id in shot_ids:
        current = by_shot.get(shot_id)
        if (
            current is None
            or current.get("selected") is True
            or str(current.get("status") or "")
            not in {"repair_required", "quality_budget_exhausted"}
            or (
                shot_id not in forced
                and not _strategy_pivot_completed(manifest, shot_id)
            )
        ):
            continue
        try:
            _ledger, _scene, shot = _find_shot(context, shot_id)
        except ValueError:
            continue
        current_history = [
            row
            for row in history
            if str(row.get("shot_id") or "") == shot_id
            and _manifest_row_matches_shot_contract(
                row,
                shot,
                legacy_prompts.get(shot_id, ""),
            )
        ]
        if (
            shot_id not in forced
            and len(current_history) < MAX_REPLANNED_CONTRACT_CANDIDATES
        ):
            continue
        source = _terminal_fallback_source(
            context,
            target_shot_id=shot_id,
            shot_ids=shot_ids,
            outputs=outputs,
            history=history,
        )
        if source is None:
            continue
        source_row, source_path, fallback_type = source
        if shot_id in forced and fallback_type == "best_available_draft":
            source_blockers = [
                str(value)
                for value in source_row.get("hard_blockers") or []
                if value
            ]
            if (
                source_blockers
                or float(source_row.get("quality_score") or 0.0)
                < BEST_EFFORT_QUALITY_FLOOR
            ):
                continue
        target_path = context.project_dir / "images" / f"{shot_id}.png"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        original_blockers = [
            str(value) for value in current.get("hard_blockers") or [] if value
        ]
        original_codes = sorted(
            classify_blockers(
                original_blockers,
                current.get("blocker_codes") or (),
            )
        )
        source_shot_id = str(source_row.get("shot_id") or "")
        candidate_suffix = (
            "CONTINUITY_HOLD"
            if fallback_type == "continuity_hold"
            else "BEST_AVAILABLE_DRAFT"
        )
        fallback_row = {
            **current,
            "candidate_id": f"{shot_id}_{candidate_suffix}",
            "selected": True,
            "status": "selected_current",
            "provider": _provider(source_row.get("provider")),
            "model": str(source_row.get("model") or ""),
            "judge_provider": str(
                source_row.get("judge_provider") or "openai-codex"
            ),
            "quality_score": float(source_row.get("quality_score") or 0.0),
            "quality_score_origin": "source_asset",
            "quality_dimensions": source_row.get("quality_dimensions") or {},
            "vision_evidence": source_row.get("vision_evidence") or {},
            "vision_evidence_applies_to_shot_id": source_shot_id,
            "candidate_path": _relative(context, target_path),
            "local_path": _relative(context, target_path),
            "artifact_sha256": _file_sha256(target_path),
            "shot_contract_hash": _shot_contract_hash(shot),
            "hard_blockers": [],
            "blocker_codes": [],
            "image_qc_blockers": original_blockers,
            "image_qc_blocker_codes": original_codes,
            "final_qc_review_required": True,
            "auto_terminal_fallback": {
                "type": fallback_type,
                "source_shot_id": source_shot_id,
                "source_candidate_id": str(source_row.get("candidate_id") or ""),
                "source_artifact": _relative(context, source_path),
                "reason": (
                    "end-to-end generation budget exhausted"
                    if shot_id in forced
                    else "automatic shot-contract replanning exhausted"
                ),
                "replan_revision": _contract_replan_count(manifest, shot_id),
            },
            "selected_at": _utc_now(),
        }
        outputs = [
            fallback_row if str(row.get("shot_id") or "") == shot_id else row
            for row in outputs
        ]
        by_shot[shot_id] = fallback_row
        events.append({
            "event": "auto_terminal_fallback_selected",
            "shot_id": shot_id,
            "candidate_id": fallback_row["candidate_id"],
            "fallback_type": fallback_type,
            "source_shot_id": source_shot_id,
            "selected_at": fallback_row["selected_at"],
        })
        changed = True
    if not changed:
        return manifest
    updated = {
        **manifest,
        "outputs": outputs,
        "selection_events": events,
        "updated_at": _utc_now(),
    }
    _write_candidate_manifest_atomic(
        context.project_dir / "manifests" / "shot_candidate_manifest.json",
        updated,
    )
    return updated


def _run_batch_chunk(
    context: StoryVideoRunContext,
    *,
    state_store: StoryVideoStateStore,
    llm: Any,
) -> dict[str, Any]:
    from dataclasses import asdict

    from tools.image_generation_tool import generate_image

    from .batch_executor import StoryVideoBatchExecutor
    from .hooks import _batch_parallelism

    shot_ids = _ordered_shot_ids(context)
    manifest_path = context.project_dir / "manifests" / "shot_candidate_manifest.json"
    existing_manifest = _load_json(manifest_path) or {}
    selected_before = {
        str(row.get("shot_id") or "")
        for row in existing_manifest.get("outputs") or []
        if isinstance(row, dict) and row.get("selected") is True
    }
    if shot_ids and set(shot_ids).issubset(selected_before):
        preflight = _next_batch_work(context)
        if preflight.get("operation") == "rejudge_existing":
            judged = _judge_candidates(
                context,
                shot_id=str(preflight.get("shot_id") or ""),
                candidates=[dict(preflight.get("candidate") or {})],
                repair_round=int(preflight.get("repair_round") or 1),
                llm=llm,
            )
            return {
                **judged,
                "action": "run_batch_chunk",
                "work_status": "in_progress",
                "wave": "legacy_rejudge",
                "generated_candidates": 0,
            }
        if preflight.get("work_status") == "human_review_required":
            return {
                **preflight,
                "success": False,
                "action": "run_batch_chunk",
            }

    if context.auto_mode:
        preflight = _next_batch_work(context)
        if preflight.get("operation") == "replan_shot_contract":
            return _auto_replan_chunk_payload(
                context,
                next_work=preflight,
                llm=llm,
                payload={
                    "generated_candidates": 0,
                    "attempted_shots": [],
                    "selected_shots": [],
                },
            )
        if preflight.get("work_status") == "human_review_required":
            shot_id = str(preflight.get("shot_id") or "")
            error = str(
                preflight.get("error") or "Visual repair budget exhausted."
            )
            _persist_terminal_attention(context, shot_id=shot_id, error=error)
            return {
                **preflight,
                "success": False,
                "action": "run_batch_chunk",
                "review_shot_id": shot_id,
            }

    def judge(
        current: StoryVideoRunContext,
        *,
        shot_id: str,
        candidate: dict[str, Any],
        repair_round: int,
    ) -> dict[str, Any]:
        return _judge_candidates(
            current,
            shot_id=shot_id,
            candidates=[candidate],
            repair_round=repair_round,
            llm=llm,
        )

    def cancelled() -> bool:
        latest = state_store.for_run(
            run_id=context.run_id,
            project_dir=context.project_dir,
        )
        return latest is None or latest.status == "stopped"

    executor = StoryVideoBatchExecutor(
        prompt_compiler=_compile_prompt,
        image_generator=generate_image,
        candidate_judge=judge,
        max_workers=_batch_parallelism(),
    )
    summary = executor.run_chunk(context, cancel_check=cancelled)
    _persist_terminal_attention(context)
    payload = asdict(summary)
    payload["success"] = summary.work_status not in {
        "human_review_required",
        "setup_required",
        "terminal_required",
    }
    payload["action"] = "run_batch_chunk"
    if context.auto_mode and summary.work_status in {"in_progress", "terminal_required"}:
        next_work = _next_batch_work(context)
        if next_work.get("operation") == "replan_shot_contract":
            return _auto_replan_chunk_payload(
                context,
                next_work=next_work,
                llm=llm,
                payload=payload,
            )
    if summary.work_status != "terminal_required":
        return payload

    manifest = _load_json(manifest_path) or {}
    selected = {
        str(row.get("shot_id") or "")
        for row in manifest.get("outputs") or []
        if isinstance(row, dict) and row.get("selected") is True
    }
    unresolved = [shot_id for shot_id in shot_ids if shot_id not in selected]
    manifest = _promote_auto_terminal_fallbacks(
        context,
        manifest,
        shot_ids=shot_ids,
        force_exhausted_shot_ids=unresolved,
    )
    selected = {
        str(row.get("shot_id") or "")
        for row in manifest.get("outputs") or []
        if isinstance(row, dict) and row.get("selected") is True
    }
    remaining = [shot_id for shot_id in shot_ids if shot_id not in selected]
    attention_work = _next_batch_work(context) if remaining else {}
    review_shot_id = str(attention_work.get("shot_id") or "").strip()
    if not review_shot_id and remaining:
        review_shot_id = remaining[0]
    review_error = str(
        attention_work.get("error") or "Visual repair budget exhausted."
    ).strip()
    payload.update(
        {
            "success": not remaining,
            "work_status": "complete" if not remaining else "human_review_required",
            "continuity_hold_shots": [
                shot_id
                for shot_id in unresolved
                if shot_id in selected
            ],
            "failed_shots": remaining,
            "review_shot_id": review_shot_id,
            "error": review_error if remaining else "",
        }
    )
    if remaining:
        _persist_terminal_attention(
            context,
            shot_id=review_shot_id,
            error=review_error,
        )
    return payload


def _run_voice_phase(
    context: StoryVideoRunContext,
    *,
    state_store: StoryVideoStateStore,
) -> dict[str, Any]:
    from dataclasses import asdict

    from .tools import validate_phase
    from .voice_executor import StoryVideoVoiceExecutor

    def cancelled() -> bool:
        latest = state_store.for_run(
            run_id=context.run_id,
            project_dir=context.project_dir,
        )
        return latest is None or latest.status == "stopped"

    summary = StoryVideoVoiceExecutor(
        phase_validator=validate_phase,
    ).run(context, cancel_check=cancelled)
    payload = asdict(summary)
    payload["success"] = summary.work_status == "complete"
    payload["action"] = "run_voice_phase"
    payload["provider"] = "local_qwen"
    payload["inference_mode"] = "offline"
    payload["network_fallback"] = "forbidden"
    return payload


def _next_batch_work(context: StoryVideoRunContext) -> dict[str, Any]:
    """Return one deterministic image/QC cycle, prioritizing repairs."""
    shot_ids = _ordered_shot_ids(context)
    ledger = _load_json(context.project_dir / "scene_ledger.json") or {}
    manifest = _load_json(
        context.project_dir / "manifests" / "shot_candidate_manifest.json"
    ) or {}
    manifest, superseded_contracts = _reconcile_manifest_contracts(
        context,
        ledger,
        manifest,
    )
    manifest = _grandfather_clean_legacy_selections(context, manifest)
    manifest = _promote_bounded_best_effort(context, manifest)
    manifest = _promote_auto_terminal_fallbacks(
        context,
        manifest,
        shot_ids=shot_ids,
    )
    legacy_prompts = {
        str(row.get("shot_id") or ""): str(row.get("prompt") or "").strip()
        for row in manifest.get("shots") or []
        if isinstance(row, dict) and str(row.get("shot_id") or "").strip()
    }
    by_shot = {
        str(row.get("shot_id") or ""): row
        for row in manifest.get("outputs") or []
        if isinstance(row, dict) and str(row.get("shot_id") or "").strip()
    }
    unresolved = [
        shot_id
        for shot_id in shot_ids
        if by_shot.get(shot_id, {}).get("selected") is not True
    ]
    style_bible = ledger.get("style_bible")
    anchor_shot_id = (
        str(style_bible.get("anchor_shot_id") or "").strip()
        if isinstance(style_bible, dict)
        else ""
    )
    if anchor_shot_id in unresolved:
        unresolved = [anchor_shot_id, *(
            shot_id for shot_id in unresolved if shot_id != anchor_shot_id
        )]
    contract_resets = [
        shot_id for shot_id in shot_ids if shot_id in superseded_contracts
    ]
    if contract_resets:
        shot_id = contract_resets[0]
        prompt_info = _compile_prompt(context, shot_id=shot_id)
        return {
            **prompt_info,
            "action": "next_batch_work",
            "work_status": "ready" if prompt_info.get("success") else "human_review_required",
            "operation": "generate",
            "contract_reset": True,
            "remaining_shot_count": len(unresolved),
        }
    blocked_statuses = {"repair_required", "quality_budget_exhausted"}
    blocked = [
        shot_id
        for shot_id in unresolved
        if str(by_shot.get(shot_id, {}).get("status") or "") in blocked_statuses
    ]
    if blocked:
        shot_id = blocked[0]
        recovery = _camera_reveal_rejudge_work(
            context,
            shot_id=shot_id,
            manifest=manifest,
            remaining_shot_count=len(unresolved),
            legacy_prompt=legacy_prompts.get(shot_id, ""),
        )
        if recovery is not None:
            return recovery
        _current_ledger, _current_scene, current_shot = _find_shot(context, shot_id)
        current_attempts = [
            row
            for row in manifest.get("attempt_history") or []
            if isinstance(row, dict)
            and str(row.get("shot_id") or "") == shot_id
            and _manifest_row_matches_shot_contract(
                row,
                current_shot,
                legacy_prompts.get(shot_id, ""),
            )
        ]
        max_candidates = (
            MAX_REPLANNED_CONTRACT_CANDIDATES
            if _contract_replan_count(manifest, shot_id)
            else MAX_REPAIR_ROUNDS
        )
        current_output = by_shot.get(shot_id, {})
        if (
            str(current_output.get("status") or "") == "quality_budget_exhausted"
            and max(
                len(current_attempts),
                int(current_output.get("repair_round") or 0),
            )
            >= 2
        ):
            return {
                **_contract_replan_work(
                    context,
                    shot_id=shot_id,
                    manifest=manifest,
                    output=current_output,
                    remaining_shot_count=len(unresolved),
                ),
                "candidate_budget_exhausted": True,
                "attempt_count_for_contract": len(current_attempts),
                "max_candidates_per_contract": max_candidates,
            }
        if len(current_attempts) >= max_candidates:
            return {
                **_contract_replan_work(
                    context,
                    shot_id=shot_id,
                    manifest=manifest,
                    output=by_shot.get(shot_id, {}),
                    remaining_shot_count=len(unresolved),
                ),
                "candidate_budget_exhausted": True,
                "attempt_count_for_contract": len(current_attempts),
                "max_candidates_per_contract": max_candidates,
            }
        prompt_info = _compile_prompt(context, shot_id=shot_id)
        if not prompt_info.get("success"):
            return _contract_replan_work(
                context,
                shot_id=shot_id,
                manifest=manifest,
                output=by_shot.get(shot_id, {}),
                remaining_shot_count=len(unresolved),
            )
        return {
            **prompt_info,
            "action": "next_batch_work",
            "work_status": "ready",
            "operation": "repair",
            "remaining_shot_count": len(unresolved),
        }

    stale_reviews: list[tuple[str, dict[str, Any]]] = []
    if engagement_contract_enabled(ledger):
        for shot_id in shot_ids:
            row = by_shot.get(shot_id, {})
            dimensions = row.get("quality_dimensions")
            if (
                row.get("selected") is True
                and row.get("legacy_qc_grandfathered") is not True
                and _provider(row.get("provider")) in {"openai", "openai-codex"}
                and (
                    int(row.get("quality_contract_version") or 0)
                    < QUALITY_CONTRACT_VERSION
                    or
                    not isinstance(dimensions, dict)
                    or "narrative_engagement" not in dimensions
                    or "story_moment_clarity" not in dimensions
                    or "cinematic_impact" not in dimensions
                    or not isinstance(row.get("focal_point_normalized"), dict)
                )
            ):
                stale_reviews.append((shot_id, row))
    if stale_reviews:
        shot_id, previous = stale_reviews[0]
        candidate_path = next(
            (
                value
                for value in (
                    str(previous.get("candidate_path") or "").strip(),
                    str(previous.get("local_path") or "").strip(),
                )
                if value and _project_path(context, value).is_file()
            ),
            "",
        )
        if candidate_path:
            old_candidate_id = str(previous.get("candidate_id") or shot_id).strip()
            _current_ledger, _current_scene, current_shot = _find_shot(
                context,
                shot_id,
            )
            return {
                "success": True,
                "action": "next_batch_work",
                "work_status": "ready",
                "operation": "rejudge_existing",
                "shot_id": shot_id,
                "candidate_budget": 0,
                "quality_threshold": QUALITY_THRESHOLD,
                "candidate": {
                    "candidate_id": f"{old_candidate_id}_V3_REVIEW",
                    "path": candidate_path,
                    "provider": _provider(previous.get("provider")),
                    "model": str(previous.get("model") or ""),
                    "response_id": str(
                        previous.get("generation_response_id") or ""
                    ),
                    "shot_contract_hash": _shot_contract_hash(current_shot),
                    "repair_strategy": "initial",
                    "generation_prompt": str(
                        previous.get("generation_prompt")
                        or previous.get("prompt")
                        or legacy_prompts.get(shot_id)
                        or ""
                    ).strip(),
                },
                "repair_round": int(previous.get("repair_round") or 1),
                "remaining_review_count": len(stale_reviews),
                "remaining_shot_count": len(unresolved),
            }
        return {
            "success": False,
            "action": "next_batch_work",
            "work_status": "human_review_required",
            "shot_id": shot_id,
            "error_type": "story_video_selected_artifact_missing",
            "error": "Selected legacy art is missing from both candidate_path and local_path.",
            "remaining_review_count": len(stale_reviews),
            "remaining_shot_count": len(unresolved),
        }

    if not unresolved:
        return {
            "success": True,
            "action": "next_batch_work",
            "work_status": "complete",
            "remaining_shot_count": 0,
        }

    shot_id = unresolved[0]
    previous = by_shot.get(shot_id, {})
    prompt_info = _compile_prompt(context, shot_id=shot_id)
    if not prompt_info.get("success"):
        return {
            **prompt_info,
            "action": "next_batch_work",
            "work_status": "human_review_required",
            "remaining_shot_count": len(unresolved),
        }
    return {
        **prompt_info,
        "action": "next_batch_work",
        "work_status": "ready",
        "operation": "repair" if previous else "generate",
        "contract_reset": shot_id in superseded_contracts or prompt_info.get("contract_reset", False),
        "remaining_shot_count": len(unresolved),
    }


def _next_batch_work_group(
    context: StoryVideoRunContext,
    *,
    max_items: int = 3,
) -> dict[str, Any]:
    """Return a bounded group of fresh shots while keeping recovery serialized."""
    limit = max(1, min(int(max_items or 1), 4))
    first = _next_batch_work(context)
    if first.get("work_status") != "ready":
        return first

    singleton = {
        **first,
        "parallelism": 1,
        "work_items": [first],
    }
    ledger = _load_json(context.project_dir / "scene_ledger.json") or {}
    style_bible = ledger.get("style_bible")
    anchor_shot_id = (
        str(style_bible.get("anchor_shot_id") or "").strip()
        if isinstance(style_bible, dict)
        else ""
    )
    if (
        limit == 1
        or first.get("operation") != "generate"
        or first.get("contract_reset") is True
        or str(first.get("shot_id") or "") == anchor_shot_id
    ):
        return singleton

    manifest = _load_json(
        context.project_dir / "manifests" / "shot_candidate_manifest.json"
    ) or {}
    by_shot = {
        str(row.get("shot_id") or ""): row
        for row in manifest.get("outputs") or []
        if isinstance(row, dict) and str(row.get("shot_id") or "").strip()
    }
    first_shot_id = str(first.get("shot_id") or "")
    if first_shot_id in by_shot:
        return singleton

    work_items = [first]
    for shot_id in _ordered_shot_ids(context):
        if len(work_items) >= limit:
            break
        if shot_id == first_shot_id or shot_id in by_shot:
            continue
        prompt_info = _compile_prompt(context, shot_id=shot_id)
        if not prompt_info.get("success"):
            continue
        work_items.append(
            {
                **prompt_info,
                "action": "next_batch_work",
                "work_status": "ready",
                "operation": "generate",
                "remaining_shot_count": first.get("remaining_shot_count", 0),
            }
        )

    if len(work_items) == 1:
        return singleton
    return {
        "success": True,
        "action": "next_batch_work",
        "work_status": "ready",
        "operation": "generate_batch",
        "parallelism": len(work_items),
        "work_items": work_items,
        "remaining_shot_count": first.get("remaining_shot_count", 0),
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


def _compile_release_art(context: StoryVideoRunContext) -> dict[str, Any]:
    ledger = _load_json(context.project_dir / "scene_ledger.json")
    if not isinstance(ledger, dict):
        raise ValueError("scene_ledger.json is missing or invalid")
    brief = compile_release_art_brief(context.topic, ledger)
    content_profile = _load_json(context.project_dir / "content_profile.json") or {}
    release_art_v2 = (
        str(content_profile.get("review_profile_id") or "").strip()
        == EDITORIAL_PROFILE_ID
    )
    manifest = _load_json(
        context.project_dir / "manifests" / "shot_candidate_manifest.json"
    ) or {}
    style_anchor_path = _style_anchor_source(
        context,
        ledger=ledger,
        manifest=manifest,
        current_shot_id="RELEASE_HERO",
    )
    opening_prompt_path = context.project_dir / "prompts" / (
        "RELEASE_OPENING.txt" if release_art_v2 else "RELEASE_HERO.txt"
    )
    opening_prompt_path.parent.mkdir(parents=True, exist_ok=True)
    opening_prompt_path.write_text(brief["opening_prompt"] + "\n", encoding="utf-8")
    ending_prompt_path = context.project_dir / "prompts" / "RELEASE_ENDING.txt"
    if release_art_v2:
        ending_prompt_path.write_text(brief["ending_prompt"] + "\n", encoding="utf-8")
    brief_path = context.project_dir / "release_art" / "brief.json"
    brief_payload = {
        "schema": (
            "story_video_release_art_brief_v2"
            if release_art_v2
            else "story_video_release_art_brief_v1"
        ),
        "run_id": context.run_id,
        "title": brief["title"],
        "subtitle": brief["subtitle"],
        "ending_label": brief["ending_label"],
        "ending_heading": brief["ending_heading"],
        "ending_takeaway": brief["ending_takeaway"],
        "prompt": brief["opening_prompt"],
        "provider": "openai-codex",
        "candidate_id_hint": (
            "RELEASE_OPENING_C01" if release_art_v2 else "RELEASE_HERO_C01"
        ),
    }
    if release_art_v2:
        brief_payload["candidates"] = [
            {
                "role": "opening",
                "candidate_id_hint": "RELEASE_OPENING_C01",
                "prompt": brief["opening_prompt"],
                "prompt_path": "prompts/RELEASE_OPENING.txt",
            },
            {
                "role": "ending",
                "candidate_id_hint": "RELEASE_ENDING_C01",
                "prompt": brief["ending_prompt"],
                "prompt_path": "prompts/RELEASE_ENDING.txt",
            },
        ]
    _write_json_atomic(brief_path, brief_payload)
    result = {
        "success": True,
        "action": "compile_release_art",
        "provider": "openai-codex",
        "candidate_id_hint": brief_payload["candidate_id_hint"],
        "prompt": brief["opening_prompt"],
        "prompt_path": _relative(context, opening_prompt_path),
        "brief": _relative(context, brief_path),
    }
    if release_art_v2:
        result["candidates"] = brief_payload["candidates"]
    if style_anchor_path is not None:
        result.update({
            "reference_image_urls": [str(style_anchor_path)],
            "style_reference_policy": "style_only_do_not_copy_subject_or_composition",
        })
    return result


def _register_release_art(
    context: StoryVideoRunContext,
    candidate: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    content_profile = _load_json(context.project_dir / "content_profile.json") or {}
    release_art_v2 = (
        str(content_profile.get("review_profile_id") or "").strip()
        == EDITORIAL_PROFILE_ID
    )
    rows = [row for row in candidates or [] if isinstance(row, dict)]
    if release_art_v2:
        by_role = {
            str(row.get("role") or "").strip().lower(): row for row in rows
        }
        if set(by_role) != {"opening", "ending"} or len(rows) != 2:
            raise ValueError(
                "release art v2 requires exactly one opening and one ending candidate"
            )
    else:
        by_role = {"opening": candidate, "ending": candidate}

    sources: dict[str, Path] = {}
    source_evidence: dict[str, dict[str, str]] = {}
    for role in ("opening", "ending"):
        row = by_role[role]
        if _provider(row.get("provider")) not in {"openai", "openai-codex"}:
            raise ValueError("dedicated release art must come from OpenAI")
        source = _project_path(context, row.get("path"))
        if not source.is_file():
            raise ValueError(f"release-art {role} candidate file missing: {source}")
        response_id = str(row.get("response_id") or "").strip()
        if not response_id:
            raise ValueError(
                f"release-art {role} candidate requires an OpenAI response_id"
            )
        sources[role] = source
        source_evidence[role] = {
            "provider": "openai-codex",
            "model": str(row.get("model") or ""),
            "response_id": response_id,
            "path": _relative(context, source),
            "sha256": _file_sha256(source),
        }
    if release_art_v2 and (
        source_evidence["opening"]["sha256"]
        == source_evidence["ending"]["sha256"]
    ):
        raise ValueError("release art v2 opening and ending sources must be distinct")

    brief_payload = _load_json(context.project_dir / "release_art" / "brief.json")
    if not isinstance(brief_payload, dict):
        compiled = _compile_release_art(context)
        brief_payload = _load_json(context.project_dir / str(compiled["brief"]))
    if not isinstance(brief_payload, dict):
        raise ValueError("release-art brief is missing or invalid")
    artifacts = compose_release_art(
        opening_source=sources["opening"],
        ending_source=sources["ending"],
        output_dir=context.project_dir / "release_art",
        title=str(brief_payload.get("title") or context.topic),
        subtitle=str(brief_payload.get("subtitle") or ""),
        ending_label=str(brief_payload.get("ending_label") or "今天帶走的發現"),
        ending_heading=str(
            brief_payload.get("ending_heading") or "原來，答案一直藏在線索裡。"
        ),
        ending_takeaway=str(
            brief_payload.get("ending_takeaway")
            or "帶著今天的線索，繼續問下一個好問題。"
        ),
    )
    manifest_path = context.project_dir / "manifests" / "release_art_manifest.json"
    _write_json_atomic(
        manifest_path,
        {
            "schema": (
                "story_video_release_art_manifest_v2"
                if release_art_v2
                else "story_video_release_art_manifest_v1"
            ),
            "run_id": context.run_id,
            "status": "PASS",
            "provider": "openai-codex",
            "model": source_evidence["opening"]["model"],
            "response_id": source_evidence["opening"]["response_id"],
            "prompt_path": (
                "prompts/RELEASE_OPENING.txt"
                if release_art_v2
                else "prompts/RELEASE_HERO.txt"
            ),
            "sources": source_evidence if release_art_v2 else None,
            "ending_copy": {
                "label": str(brief_payload.get("ending_label") or ""),
                "heading": str(brief_payload.get("ending_heading") or ""),
                "takeaway": str(brief_payload.get("ending_takeaway") or ""),
            },
            "artifacts": {
                name: {
                    "path": _relative(context, path),
                    "sha256": _file_sha256(path),
                }
                for name, path in artifacts.items()
            },
            "created_at": _utc_now(),
        },
    )
    return {
        "success": True,
        "action": "register_release_art",
        "manifest": _relative(context, manifest_path),
        "artifacts": {
            name: _relative(context, path) for name, path in artifacts.items()
        },
    }


def _verified_release_art(context: StoryVideoRunContext) -> dict[str, str]:
    manifest = _load_json(
        context.project_dir / "manifests" / "release_art_manifest.json"
    )
    if not isinstance(manifest, dict):
        raise ValueError(
            "dedicated release art manifest is required before render"
        )
    content_profile = _load_json(context.project_dir / "content_profile.json") or {}
    release_art_v2 = (
        str(content_profile.get("review_profile_id") or "").strip()
        == EDITORIAL_PROFILE_ID
    )
    schema = str(manifest.get("schema") or "")
    expected_schema = (
        "story_video_release_art_manifest_v2"
        if release_art_v2
        else "story_video_release_art_manifest_v1"
    )
    if schema != expected_schema:
        raise ValueError("dedicated release art manifest schema is invalid")
    if str(manifest.get("status") or "").upper() != "PASS":
        raise ValueError("dedicated release art manifest is not PASS")
    if str(manifest.get("run_id") or "") != context.run_id:
        raise ValueError("stale dedicated release art belongs to a different run")
    if _provider(manifest.get("provider")) not in {"openai", "openai-codex"}:
        raise ValueError("dedicated release art must come from OpenAI")
    if not release_art_v2 and not str(manifest.get("response_id") or "").strip():
        raise ValueError("dedicated release art lacks OpenAI response evidence")
    if release_art_v2:
        sources = manifest.get("sources")
        if not isinstance(sources, dict):
            raise ValueError("dedicated release art v2 source evidence is missing")
        source_hashes: list[str] = []
        for role in ("opening", "ending"):
            evidence = sources.get(role)
            if (
                not isinstance(evidence, dict)
                or _provider(evidence.get("provider"))
                not in {"openai", "openai-codex"}
                or not str(evidence.get("response_id") or "").strip()
                or not str(evidence.get("path") or "").strip()
                or not str(evidence.get("sha256") or "").strip()
            ):
                raise ValueError(
                    f"dedicated release art v2 {role} source evidence is invalid"
                )
            source_hashes.append(str(evidence["sha256"]))
            source_path = _project_path(context, evidence.get("path")).resolve()
            try:
                source_path.relative_to(context.project_dir.resolve())
            except ValueError as exc:
                raise ValueError(
                    f"dedicated release art v2 {role} source is outside project"
                ) from exc
            if not source_path.is_file():
                raise ValueError(
                    f"dedicated release art v2 {role} source file is missing"
                )
            if _file_sha256(source_path) != str(evidence["sha256"]):
                raise ValueError(
                    f"dedicated release art v2 {role} source hash mismatch"
                )
        if len(set(source_hashes)) != 2:
            raise ValueError("dedicated release art v2 sources are not distinct")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("dedicated release art artifact evidence is missing")
    verified: dict[str, str] = {}
    for name in ("hero_source", "opening_card", "ending_card", "thumbnail"):
        evidence = artifacts.get(name)
        if not isinstance(evidence, dict):
            raise ValueError(f"dedicated release art {name} evidence is missing")
        path = _project_path(context, evidence.get("path")).resolve()
        try:
            relative = path.relative_to(context.project_dir.resolve())
        except ValueError as exc:
            raise ValueError(
                f"dedicated release art {name} must be inside the current project"
            ) from exc
        if not path.is_file():
            raise ValueError(f"dedicated release art {name} file is missing")
        expected_sha = str(evidence.get("sha256") or "").strip()
        if not expected_sha or _file_sha256(path) != expected_sha:
            raise ValueError(f"dedicated release art {name} hash mismatch")
        verified[name] = str(relative)
    return verified


def _measured_voice_chunk_subtitle_cues(
    segment: dict[str, Any], *, scene_id: str
) -> list[dict[str, Any]] | None:
    raw_chunks = segment.get("voice_chunks")
    if raw_chunks is None:
        return None
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise ValueError(f"narration segment in {scene_id} has invalid voice_chunks")
    cues: list[dict[str, Any]] = []
    previous_end = 0.0
    for index, chunk in enumerate(raw_chunks):
        if not isinstance(chunk, dict):
            raise ValueError(f"voice chunk[{index}] in {scene_id} must be an object")
        chunk_id = str(chunk.get("voice_chunk_id") or "").strip()
        text = str(chunk.get("display_text") or "").strip()
        start_sec = float(chunk.get("start_sec") or 0.0)
        end_sec = float(chunk.get("speech_end_sec") or 0.0)
        failed_gate = next(
            (
                gate
                for gate in (
                    "alignment_status",
                    "pronunciation_status",
                    "prosody_status",
                )
                if str(chunk.get(gate) or "").upper() != "PASS"
            ),
            None,
        )
        if not chunk_id or not text:
            raise ValueError(f"voice chunk[{index}] in {scene_id} is incomplete")
        if failed_gate:
            raise ValueError(f"voice chunk {chunk_id} has not passed {failed_gate}")
        if start_sec < previous_end or end_sec <= start_sec:
            raise ValueError(f"voice chunk {chunk_id} has invalid measured timing")
        cues.append(
            {
                "text": text,
                "start_sec": round(start_sec, 4),
                "end_sec": round(end_sec, 4),
                "sentence_count": 1,
            }
        )
        previous_end = end_sec
    timeline_duration = float(segment.get("timeline_duration_sec") or 0.0)
    if timeline_duration <= 0 or cues[-1]["end_sec"] > timeline_duration + 0.05:
        raise ValueError(f"voice chunks in {scene_id} exceed their segment timeline")
    source_text = "".join(str(segment.get("display_text") or "").split())
    cue_text = "".join("".join(str(cue["text"]).split()) for cue in cues)
    if not source_text or cue_text != source_text:
        raise ValueError(f"voice chunks in {scene_id} do not preserve narration")
    return cues


def _canonical_story_scene_id(value: str) -> str:
    normalized = str(value or "").strip().upper()
    match = re.fullmatch(r"SC?(\d+)", normalized)
    if match is None:
        return normalized
    digits = match.group(1)
    return f"S{int(digits):0{max(2, len(digits))}d}"


def _select_background_music(
    context: StoryVideoRunContext,
    ledger: dict[str, Any],
    scenes: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    hermes_home = Path(
        os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")
    ).expanduser()
    library_path = hermes_home / "story_video_music_library.json"
    library = _load_json(library_path)
    if not isinstance(library, dict):
        return None, "NOT_CONFIGURED"
    if str(library.get("schema") or "") == "story_video_music_library_v2":
        ledger_scenes = {
            str(scene.get("scene_id") or "").strip(): scene
            for scene in ledger.get("scenes") or []
            if isinstance(scene, dict) and str(scene.get("scene_id") or "").strip()
        }
        timeline: list[dict[str, Any]] = [
            {
                "scene_id": "RELEASE_OPENING",
                "duration_sec": 3.0,
                "narrative_role": "hook",
            }
        ]
        for scene in scenes or []:
            if not isinstance(scene, dict):
                continue
            scene_id = str(scene.get("scene_id") or "").strip()
            duration = sum(
                float(shot.get("timeline_duration_sec") or 0.0)
                for shot in scene.get("shots") or []
                if isinstance(shot, dict)
            )
            if duration <= 0:
                duration = float(ledger.get("target_duration_sec") or 0.0) / max(
                    1, len(scenes or [])
                )
            timeline.append(
                {
                    "scene_id": scene_id,
                    "duration_sec": duration,
                    "narrative_role": str(
                        (ledger_scenes.get(scene_id) or {}).get("narrative_role") or ""
                    ).strip(),
                }
            )
        timeline.append(
            {
                "scene_id": "RELEASE_ENDING",
                "duration_sec": 5.0,
                "narrative_role": "close",
            }
        )
        plan = plan_music_cues(ledger, library, timeline)
        if plan.get("status") != "SELECTED":
            return None, str(plan.get("status") or "INVALID_LIBRARY")
        try:
            compiled = compile_music_bed(context.project_dir, plan)
        except (OSError, ValueError, subprocess.CalledProcessError):
            return None, "COMPILE_FAILED"
        ducking = plan.get("ducking") or {}
        return (
            {
                "enabled": True,
                "track_id": f"{plan['track_id']}-cued",
                "path": str(compiled["path"]),
                "rights_status": "approved",
                "license": str(plan["license"]),
                "source": str(plan["provenance"]),
                "volume_db": float(plan.get("volume_db", -22.0)),
                "fade_in_sec": float(plan.get("fade_in_sec", 2.0)),
                "fade_out_sec": float(plan.get("fade_out_sec", 4.0)),
                "ducking": {
                    "threshold": float(ducking.get("threshold", 0.03)),
                    "ratio": float(ducking.get("ratio", 10.0)),
                    "attack_ms": int(ducking.get("attack_ms", 80)),
                    "release_ms": int(ducking.get("release_ms", 800)),
                },
            },
            "SELECTED_CUED",
        )
    if str(library.get("schema") or "") != "story_video_music_library_v1":
        return None, "INVALID_LIBRARY"

    engagement = ledger.get("engagement_profile") or {}
    desired_tags = {
        str(engagement.get("mode") or "young_explorer").strip().lower(),
        str(engagement.get("energy") or "high").strip().lower(),
        "discovery",
    }
    candidates: list[tuple[int, str, dict[str, Any], Path]] = []
    for raw in library.get("tracks") or []:
        if not isinstance(raw, dict) or raw.get("enabled") is not True:
            continue
        if str(raw.get("rights_status") or "").strip().lower() != "approved":
            continue
        if not str(raw.get("license") or "").strip():
            continue
        if not str(raw.get("source") or "").strip():
            continue
        track_id = str(raw.get("track_id") or "").strip()
        raw_path = Path(str(raw.get("path") or "")).expanduser()
        track_path = (
            raw_path if raw_path.is_absolute() else library_path.parent / raw_path
        ).resolve()
        if not track_id or not track_path.is_file():
            continue
        moods = {
            str(value).strip().lower()
            for value in raw.get("moods") or []
            if str(value).strip()
        }
        score = len(desired_tags & moods)
        stable_tiebreak = hashlib.sha256(
            f"{context.topic}\x1f{track_id}".encode("utf-8")
        ).hexdigest()
        candidates.append((score, stable_tiebreak, raw, track_path))
    if not candidates:
        return None, "NO_APPROVED_TRACK"
    _score, _tie, selected, track_path = max(
        candidates, key=lambda row: (row[0], row[1])
    )
    ducking = selected.get("ducking") or {}
    return (
        {
            "enabled": True,
            "track_id": str(selected["track_id"]),
            "path": str(track_path),
            "rights_status": "approved",
            "license": str(selected["license"]),
            "source": str(selected["source"]),
            "volume_db": float(selected.get("volume_db", -22.0)),
            "fade_in_sec": float(selected.get("fade_in_sec", 2.0)),
            "fade_out_sec": float(selected.get("fade_out_sec", 4.0)),
            "ducking": {
                "threshold": float(ducking.get("threshold", 0.03)),
                "ratio": float(ducking.get("ratio", 10.0)),
                "attack_ms": int(ducking.get("attack_ms", 80)),
                "release_ms": int(ducking.get("release_ms", 800)),
            },
        },
        "SELECTED",
    )


def _prepare_render(context: StoryVideoRunContext) -> dict[str, Any]:
    ledger = _load_json(context.project_dir / "scene_ledger.json")
    existing_render_input = _load_json(context.project_dir / "render_input.json")
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
    legacy_prompts = {
        str(row.get("shot_id") or ""): str(row.get("prompt") or "").strip()
        for row in candidate_manifest.get("shots") or []
        if isinstance(row, dict) and str(row.get("shot_id") or "").strip()
    }
    for output in candidate_manifest.get("outputs") or []:
        if not isinstance(output, dict) or output.get("selected") is not True:
            continue
        shot_id = str(output.get("shot_id") or "").strip()
        if not shot_id:
            continue
        if _provider(output.get("provider")) not in {"openai", "openai-codex"}:
            raise ValueError(f"selected shot {shot_id} is not from OpenAI")
        selected_by_shot[shot_id] = output

    narration_by_scene: dict[str, dict[str, Any]] = {}
    for output in narration_manifest.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        raw_scene_id = str(output.get("scene_id") or "").strip()
        if not raw_scene_id:
            continue
        canonical_scene_id = _canonical_story_scene_id(raw_scene_id)
        if canonical_scene_id in narration_by_scene:
            raise ValueError(
                f"duplicate narration scene alias for {canonical_scene_id}"
            )
        narration_by_scene[canonical_scene_id] = output
    narration_schema = str(narration_manifest.get("schema") or "")
    semantic_plans_by_scene: dict[str, dict[str, dict[str, Any]]] = {}
    if isinstance(existing_render_input, dict):
        for scene in existing_render_input.get("scenes") or []:
            if not isinstance(scene, dict):
                continue
            scene_id = str(scene.get("scene_id") or "").strip()
            semantic_plans_by_scene[_canonical_story_scene_id(scene_id)] = {
                str(shot.get("shot_id") or "").strip(): shot
                for shot in scene.get("shots") or []
                if isinstance(shot, dict) and str(shot.get("shot_id") or "").strip()
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
        canonical_scene_id = _canonical_story_scene_id(scene_id)
        narration = narration_by_scene.get(canonical_scene_id)
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
        segment_by_shot: dict[str, dict[str, Any]] = {}
        if narration_schema == "story_video_narration_manifest_v4":
            raw_segments = narration.get("segments")
            if not isinstance(raw_segments, list) or not raw_segments:
                raise ValueError(f"missing verified narration segments for scene {scene_id}")
            for segment in raw_segments:
                if not isinstance(segment, dict):
                    continue
                segment_shot_id = str(segment.get("shot_id") or "").strip()
                if not segment_shot_id:
                    raise ValueError(f"narration segment in {scene_id} is missing shot_id")
                failed_gate = next(
                    (
                        gate
                        for gate in (
                            "alignment_status",
                            "pronunciation_status",
                            "prosody_status",
                        )
                        if str(segment.get(gate) or "").upper() != "PASS"
                    ),
                    None,
                )
                if failed_gate:
                    raise ValueError(
                        f"narration segment {segment_shot_id} has not passed {failed_gate}"
                    )
                if float(segment.get("timeline_duration_sec") or 0.0) <= 0:
                    raise ValueError(
                        f"narration segment {segment_shot_id} has no measured timeline"
                    )
                segment_by_shot[segment_shot_id] = segment
        shots: list[dict[str, Any]] = []
        raw_shots = scene.get("shots")
        if not isinstance(raw_shots, list) or not raw_shots:
            raise ValueError(f"scene {scene_id} has no shots")
        ledger_shots = {
            str(shot.get("shot_id") or "").strip(): shot
            for shot in raw_shots
            if isinstance(shot, dict) and str(shot.get("shot_id") or "").strip()
        }
        render_rows: list[tuple[str, list[str], str, dict[str, Any], dict[str, Any] | None]] = []
        if segment_by_shot:
            covered_source_shots: set[str] = set()
            existing_scene_plan = semantic_plans_by_scene.get(
                canonical_scene_id, {}
            )
            for segment_id, segment in segment_by_shot.items():
                semantic_plan = existing_scene_plan.get(segment_id, {})
                raw_source_ids = segment.get("source_shot_ids") or semantic_plan.get(
                    "source_shot_ids"
                )
                if isinstance(raw_source_ids, list):
                    source_shot_ids = [
                        str(value).strip() for value in raw_source_ids if str(value).strip()
                    ]
                elif segment_id in ledger_shots:
                    source_shot_ids = [segment_id]
                else:
                    raise ValueError(
                        f"semantic narration segment {segment_id} has no source_shot_ids"
                    )
                representative_shot_id = str(
                    segment.get("representative_shot_id")
                    or semantic_plan.get("representative_shot_id")
                    or (source_shot_ids[0] if len(source_shot_ids) == 1 else "")
                ).strip()
                if representative_shot_id not in source_shot_ids:
                    raise ValueError(
                        f"semantic narration segment {segment_id} has an invalid representative shot"
                    )
                unknown_sources = [
                    source_id
                    for source_id in source_shot_ids
                    if source_id not in ledger_shots
                ]
                if unknown_sources:
                    raise ValueError(
                        f"semantic narration segment {segment_id} has unknown source shots: "
                        + ", ".join(unknown_sources)
                    )
                duplicate_sources = covered_source_shots.intersection(source_shot_ids)
                if duplicate_sources:
                    raise ValueError(
                        f"semantic narration source shots are reused: "
                        + ", ".join(sorted(duplicate_sources))
                    )
                covered_source_shots.update(source_shot_ids)
                render_rows.append(
                    (
                        segment_id,
                        source_shot_ids,
                        representative_shot_id,
                        ledger_shots[representative_shot_id],
                        segment,
                    )
                )
            uncovered_sources = set(ledger_shots).difference(covered_source_shots)
            if uncovered_sources:
                raise ValueError(
                    f"semantic narration does not cover source shots: "
                    + ", ".join(sorted(uncovered_sources))
                )
        else:
            render_rows = [
                (shot_id, [shot_id], shot_id, shot, None)
                for shot_id, shot in ledger_shots.items()
            ]

        for shot_id, source_shot_ids, representative_shot_id, shot, segment in render_rows:
            selected = selected_by_shot.get(representative_shot_id)
            if selected is None:
                raise ValueError(f"missing selected image for shot {representative_shot_id}")
            if not _manifest_row_matches_shot_contract(
                selected,
                shot,
                legacy_prompts.get(representative_shot_id, ""),
            ):
                raise ValueError(
                    f"selected image for {representative_shot_id} uses superseded shot contract"
                )
            _image_path, image_relative = _required_project_file(
                context,
                selected.get("local_path"),
                label=f"image for {representative_shot_id}",
            )
            selected_images.append(image_relative)
            shot_input = {
                "shot_id": shot_id,
                "selected": True,
                "image": image_relative,
                "narration": str(
                    (segment or {}).get("display_text")
                    or shot.get("narration_text")
                    or display_text
                ),
                "subtitle_position": "bottom",
            }
            focal = selected.get("focal_point_normalized")
            if isinstance(focal, dict):
                try:
                    focal_x = float(focal.get("x"))
                    focal_y = float(focal.get("y"))
                except (TypeError, ValueError):
                    focal_x = focal_y = -1.0
                if 0.0 <= focal_x <= 1.0 and 0.0 <= focal_y <= 1.0:
                    shot_input["focus_end"] = {
                        "x": round(focal_x, 4),
                        "y": round(focal_y, 4),
                    }
            if segment is not None:
                shot_input["source_shot_ids"] = source_shot_ids
                shot_input["representative_shot_id"] = representative_shot_id
                shot_input["timeline_duration_sec"] = float(
                    segment["timeline_duration_sec"]
                )
                shot_input["speech_end_sec"] = float(
                    segment.get("speech_end_sec")
                    or segment["timeline_duration_sec"]
                )
                subtitle_cues = _measured_voice_chunk_subtitle_cues(
                    segment, scene_id=scene_id
                )
                if subtitle_cues is not None:
                    shot_input["subtitle_timing_source"] = (
                        "measured_voice_chunks"
                    )
                    shot_input["subtitle_cues"] = subtitle_cues
            if selected.get("final_qc_review_required") is True:
                shot_input["final_qc_review_required"] = True
                shot_input["auto_terminal_fallback"] = selected.get(
                    "auto_terminal_fallback"
                )
            shots.append(shot_input)
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

    release_art = _verified_release_art(context)
    opening_image = release_art["opening_card"]
    ending_image = release_art["ending_card"]

    background_music, background_music_status = _select_background_music(
        context, ledger, scenes
    )
    render_input = {
        "schema": "story_video_render_input_v2",
        "project_title": context.topic,
        "title": context.topic,
        "resolution": {"width": 1920, "height": 1080},
        "fps": 30,
        "post_speech_hold_sec": 0.18,
        "max_post_speech_hold_sec": 0.6,
        "motion_policy": "cinematic_focus_push",
        "zoom_max": 1.1,
        "subtitle": {
            "max_lines": 2,
            "max_chars_per_line": 29,
            "preferred_sentences_per_cue": 1,
            "max_sentences_per_cue": 2,
            "min_cue_duration_sec": 1.5,
            "hide_outside_speech": True,
            "position": "bottom",
            "production_stage": "post_composite",
            "qc_mode": "fast_post_composite",
        },
        "opening_card": {
            "title": context.topic,
            "image": opening_image,
            "duration_sec": 3.0,
            "precomposed": True,
        },
        "ending_card": {
            "title": "探索仍在繼續",
            "image": ending_image,
            "duration_sec": 5.0,
            "precomposed": True,
        },
        "scenes": scenes,
        "output": "video/final.mp4",
    }
    if background_music is not None:
        render_input["background_music"] = background_music
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
        "background_music_status": background_music_status,
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
        elif action == "run_batch_chunk":
            authorization_id = str(args.get("authorization_id") or "").strip()
            authorization = (
                state_store.autopilot_authorization(
                    context,
                    authorization_id=authorization_id,
                )
                if authorization_id
                else None
            )
            if context.auto_mode and authorization is None:
                payload = {
                    "success": False,
                    "error_type": "story_video_operator_authorization_required",
                    "error": (
                        "run_batch_chunk requires the verified purpose-limited "
                        "authorization_id for this active story-video run"
                    ),
                }
            else:
                payload = _run_batch_chunk(
                    context,
                    state_store=state_store,
                    llm=llm or _PLUGIN_LLM,
                )
                if authorization is not None:
                    payload["authorization_verified"] = True
        elif action == "run_voice_phase":
            authorization_id = str(args.get("authorization_id") or "").strip()
            authorization = (
                state_store.autopilot_authorization(
                    context,
                    authorization_id=authorization_id,
                )
                if authorization_id
                else None
            )
            if context.auto_mode and authorization is None:
                payload = {
                    "success": False,
                    "error_type": "story_video_operator_authorization_required",
                    "error": (
                        "run_voice_phase requires the verified purpose-limited "
                        "authorization_id for this active story-video run"
                    ),
                }
            elif context.phase != "voice":
                payload = {
                    "success": False,
                    "error_type": "story_video_voice_phase_required",
                    "error": f"run_voice_phase cannot run during {context.phase}",
                }
            else:
                payload = _run_voice_phase(
                    context,
                    state_store=state_store,
                )
                if authorization is not None:
                    payload["authorization_verified"] = True
        elif action == "prepare_render":
            payload = _prepare_render(context)
        elif action == "compile_release_art":
            payload = _compile_release_art(context)
        elif action == "register_release_art":
            payload = _register_release_art(
                context,
                args.get("release_art_candidate") or {},
                args.get("release_art_candidates") or [],
            )
        elif action == "next_batch_work":
            payload = _next_batch_work(context)
        elif action == "replan_shot_contract":
            payload = _apply_shot_contract_replan(
                context,
                shot_id=str(args.get("shot_id") or "").strip(),
                redesigned_shot=args.get("redesigned_shot") or {},
            )
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
