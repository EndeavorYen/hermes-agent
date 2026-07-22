from __future__ import annotations

import time
from typing import Any

from agent.visual.independent_vision_audit import parse_vision_judge_analysis
from agent.visual.judges.vision import build_vision_judge_observation
from agent.visual.provider_failures import classify_visual_provider_failure


def build_candidate_vision_observation(
    candidate: dict[str, Any],
    *,
    fallback_observation: dict[str, Any],
    inline_enabled: bool = False,
    analyzer=None,
    transient_retry_delay_seconds: float = 0.5,
) -> dict[str, Any]:
    raw = _raw_candidate_vision_observation(candidate)
    if raw:
        vision = build_vision_judge_observation(raw)
        return _merge_observations(
            fallback_observation,
            vision,
            source="candidate_vision_observation",
        )
    if inline_enabled and analyzer is not None and candidate.get("kind") == "image":
        failure: dict[str, Any] | None = None
        for attempt in range(2):
            try:
                raw_inline = analyzer(candidate)
                failure = _inline_vision_failure(raw_inline)
                if failure is None:
                    vision = parse_vision_judge_analysis(raw_inline)
                    merged = _merge_observations(
                        fallback_observation,
                        vision,
                        source="inline_vision_judge",
                    )
                    if attempt:
                        merged["evidence"]["transient_retry_count"] = attempt
                    return merged
            except Exception as exc:
                failure = classify_visual_provider_failure(exc)
            if failure.get("failure_class") != "provider_unavailable":
                break
            if attempt == 0 and transient_retry_delay_seconds > 0:
                time.sleep(transient_retry_delay_seconds)
        return _vision_unavailable_observation(fallback_observation, failure)
    return fallback_observation


def _inline_vision_failure(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("success") is not False:
        return None
    payload = {
        "success": False,
        "error_type": value.get("error_type"),
        "error": value.get("error"),
        "message": value.get("message") or value.get("analysis"),
        "code": value.get("code"),
        "status_code": value.get("status_code"),
    }
    failure = classify_visual_provider_failure(payload)
    failure["source"] = "inline_vision_judge"
    return failure


def _vision_unavailable_observation(fallback: dict[str, Any], failure: dict[str, Any]) -> dict[str, Any]:
    observation = dict(fallback or {})
    observation["vision_failure"] = dict(failure)
    observation["evidence"] = {
        "source": "inline_vision_unavailable",
        "summary": failure.get("operator_summary") or "inline vision judge unavailable",
    }
    return observation


def _raw_candidate_vision_observation(candidate: dict[str, Any]) -> dict[str, Any]:
    direct = candidate.get("vision_observation")
    if isinstance(direct, dict):
        return direct
    metadata = candidate.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("vision_observation") or metadata.get("visual_quality_observation")
        if isinstance(value, dict):
            return value
    return {}


def _merge_observations(
    fallback: dict[str, Any],
    vision: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    merged = dict(fallback or {})
    for key in (
        "reference_adherence",
        "subject_quality",
        "face_quality",
        "visual_appeal",
        "glamour_impact",
        "composition",
        "pose_composition",
        "pose_novelty",
        "fashion_material_quality",
        "edit_anchor_adherence",
        "character_identity_adherence",
        "identity_adherence",
        "character_adherence",
        "face_identity_adherence",
        "pose_composition_adherence",
        "pose_adherence",
        "composition_adherence",
        "wardrobe_adherence",
        "clothing_adherence",
        "outfit_adherence",
        "style_adherence",
        "art_style_adherence",
        "background_adherence",
        "scene_adherence",
        "aspect_integrity",
        "motion_quality",
        "confidence",
    ):
        if key in vision:
            merged[key] = vision[key]
    fallback_defects = _filter_contradicted_fallback_defects(
        [
            str(item)
            for item in (fallback or {}).get("artifact_defects", [])
            if isinstance(item, str) and item.strip()
        ],
        vision,
    )
    merged["artifact_defects"] = list(
        dict.fromkeys(
            [
                *fallback_defects,
                *[
                    str(item)
                    for item in vision.get("artifact_defects", [])
                    if isinstance(item, str) and item.strip()
                ],
            ]
        )
    )
    merged["evidence"] = {
        "source": source,
        "summary": "privacy-safe independent visual quality observation",
    }
    return merged


def _filter_contradicted_fallback_defects(defects: list[str], vision: dict[str, Any]) -> list[str]:
    contradicted: set[str] = set()
    if _dimension_at_least(vision, "aspect_integrity", 0.5):
        contradicted.update({"aspect_mismatch", "weak_aspect_integrity"})
    if _dimension_at_least(vision, "motion_quality", 0.4):
        contradicted.update(
            {
                "duration_mismatch",
                "weak_motion_evidence",
                "weak_motion_or_duration_evidence",
            }
        )
    return [defect for defect in defects if defect not in contradicted]


def _dimension_at_least(vision: dict[str, Any], key: str, threshold: float) -> bool:
    if key not in vision:
        return False
    try:
        return float(vision.get(key)) >= threshold
    except (TypeError, ValueError):
        return False
