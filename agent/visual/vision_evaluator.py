from __future__ import annotations

from typing import Any

from agent.visual.independent_vision_audit import parse_vision_judge_analysis
from agent.visual.judges.vision import build_vision_judge_observation


def build_candidate_vision_observation(
    candidate: dict[str, Any],
    *,
    fallback_observation: dict[str, Any],
    inline_enabled: bool = False,
    analyzer=None,
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
        try:
            vision = parse_vision_judge_analysis(analyzer(candidate))
        except Exception:
            return fallback_observation
        return _merge_observations(
            fallback_observation,
            vision,
            source="inline_vision_judge",
        )
    return fallback_observation


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
        "visual_appeal",
        "composition",
        "pose_novelty",
        "aspect_integrity",
        "motion_quality",
        "confidence",
    ):
        if key in vision:
            merged[key] = vision[key]
    merged["artifact_defects"] = list(
        dict.fromkeys(
            [
                *[
                    str(item)
                    for item in (fallback or {}).get("artifact_defects", [])
                    if isinstance(item, str) and item.strip()
                ],
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
