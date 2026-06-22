from __future__ import annotations

from typing import Any

from agent.visual.judges.vision import build_vision_judge_observation


def build_candidate_vision_observation(
    candidate: dict[str, Any],
    *,
    fallback_observation: dict[str, Any],
) -> dict[str, Any]:
    raw = _raw_candidate_vision_observation(candidate)
    if not raw:
        return fallback_observation
    vision = build_vision_judge_observation(raw)
    return _merge_observations(fallback_observation, vision)


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
) -> dict[str, Any]:
    merged = dict(fallback or {})
    for key in (
        "reference_adherence",
        "subject_quality",
        "visual_appeal",
        "composition",
        "pose_novelty",
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
        "source": "candidate_vision_observation",
        "summary": "privacy-safe independent visual quality observation",
    }
    return merged
