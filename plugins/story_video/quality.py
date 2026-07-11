from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


OPENAI_PROVIDERS = frozenset({"openai", "openai-codex"})
QUALITY_THRESHOLD = 80.0
SHOT_SCALES = frozenset(
    {"establishing", "wide", "medium", "close_up", "macro", "insert"}
)
CLOSE_EVIDENCE_SCALES = frozenset({"close_up", "macro", "insert"})
REQUIRED_SHOT_FIELDS = (
    "narration_text",
    "narrative_role",
    "viewer_takeaway",
    "subject",
    "action",
    "evidence_detail",
    "shot_scale",
    "camera_angle",
    "focal_point",
    "subtitle_safe_area",
    "acceptance_criteria",
    "risk_class",
)
DIMENSION_WEIGHTS = {
    "text_alignment": 25.0,
    "focal_clarity": 20.0,
    "evidence_specificity": 15.0,
    "professional_quality": 15.0,
    "scientific_credibility": 15.0,
    "continuity_and_diversity": 10.0,
}


@dataclass(frozen=True)
class LedgerQualityReport:
    ok: bool
    violations: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateDecision:
    status: str
    selected_candidate_id: str | None
    ranked_candidate_ids: tuple[str, ...]
    best_score: float
    rejected: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _provider(value: Any) -> str:
    return _text(value).lower().replace("_", "-")


def _duration_seconds(value: Any) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return 0.0
    return duration if math.isfinite(duration) and duration > 0 else 0.0


def _shot_count_bounds(duration_sec: float) -> tuple[int, int]:
    if duration_sec <= 0:
        return 1, 0
    minutes = duration_sec / 60.0
    return max(1, math.ceil(minutes * 8.0)), max(1, math.ceil(minutes * 12.0))


def _scene_shots(ledger: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    collected: list[tuple[str, dict[str, Any]]] = []
    scenes = ledger.get("scenes")
    if not isinstance(scenes, list):
        return collected
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        scene_id = _text(scene.get("scene_id")) or f"scene[{index}]"
        shots = scene.get("shots")
        if not isinstance(shots, list):
            continue
        for shot in shots:
            if isinstance(shot, dict):
                collected.append((scene_id, shot))
    return collected


def validate_quality_ledger(ledger: dict[str, Any]) -> LedgerQualityReport:
    violations: list[str] = []
    scenes = ledger.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return LedgerQualityReport(False, ("scene_ledger.scenes",), {"shot_count": 0})

    for index, scene in enumerate(scenes):
        scene_id = (
            _text(scene.get("scene_id"))
            if isinstance(scene, dict)
            else f"scene[{index}]"
        ) or f"scene[{index}]"
        if not isinstance(scene, dict):
            violations.append(scene_id)
            continue
        shots = scene.get("shots")
        if not isinstance(shots, list) or not shots:
            violations.append(f"{scene_id}.shots")

    shot_rows = _scene_shots(ledger)
    seen_ids: set[str] = set()
    scales: list[str] = []
    close_evidence_count = 0
    for scene_id, shot in shot_rows:
        shot_id = _text(shot.get("shot_id")) or f"{scene_id}.shot"
        if not _text(shot.get("shot_id")):
            violations.append(f"{shot_id}.shot_id")
        elif shot_id in seen_ids:
            violations.append(f"duplicate_shot_id:{shot_id}")
        seen_ids.add(shot_id)
        for field_name in REQUIRED_SHOT_FIELDS:
            value = shot.get(field_name)
            if field_name == "acceptance_criteria":
                if not isinstance(value, list) or not any(_text(item) for item in value):
                    violations.append(f"{shot_id}.{field_name}")
            elif not _text(value):
                violations.append(f"{shot_id}.{field_name}")
        scale = _text(shot.get("shot_scale")).lower()
        if scale and scale not in SHOT_SCALES:
            violations.append(f"{shot_id}.shot_scale:{scale}")
        scales.append(scale)
        if scale in CLOSE_EVIDENCE_SCALES:
            close_evidence_count += 1

    duration_sec = _duration_seconds(
        ledger.get("target_duration_sec") or ledger.get("duration_sec")
    )
    minimum_shots, maximum_shots = _shot_count_bounds(duration_sec)
    shot_count = len(shot_rows)
    if duration_sec and shot_count < minimum_shots:
        violations.append(
            f"shot_density_below_quality_first_minimum:{shot_count}<{minimum_shots}"
        )
    if duration_sec and shot_count > maximum_shots:
        violations.append(
            f"shot_density_above_quality_first_maximum:{shot_count}>{maximum_shots}"
        )

    production_type = _text(ledger.get("production_type")).lower()
    close_ratio = close_evidence_count / shot_count if shot_count else 0.0
    if production_type in {"science_explainer", "documentary", "science_documentary"}:
        if shot_count and close_ratio < 0.25:
            violations.append(
                f"science_close_evidence_ratio_below_target:{close_ratio:.3f}<0.250"
            )

    run_scale = ""
    run_length = 0
    for _, shot in shot_rows:
        scale = _text(shot.get("shot_scale")).lower()
        if scale and scale == run_scale:
            run_length += 1
        else:
            run_scale = scale
            run_length = 1
        if run_length == 3 and not _text(shot.get("intentional_scale_repeat_reason")):
            violations.append(f"repeated_shot_scale_without_reason:{scale}:3")

    metrics = {
        "duration_sec": duration_sec,
        "shot_count": shot_count,
        "minimum_shots": minimum_shots,
        "maximum_shots": maximum_shots,
        "close_evidence_count": close_evidence_count,
        "close_evidence_ratio": round(close_ratio, 4),
    }
    return LedgerQualityReport(not violations, tuple(violations), metrics)


def candidate_budget_for_shot(shot: dict[str, Any]) -> int:
    risk = _text(shot.get("risk_class")).lower()
    if risk in {"high", "hero", "key_evidence", "character", "anatomy"}:
        return 3
    if risk in {"low", "transition", "background"}:
        return 1
    return 2


def _scale_instruction(scale: str) -> str:
    mapping = {
        "establishing": "establishing wide shot; the environment gives scale while the subject remains readable",
        "wide": "wide shot; the primary subject remains clearly readable",
        "medium": "medium shot; primary subject occupies roughly 35-55% of the frame",
        "close_up": "close-up shot; primary subject occupies roughly 55-75% of the frame",
        "macro": "macro evidence shot; the evidence detail fills the frame and remains anatomically coherent",
        "insert": "insert detail shot; isolate the evidence object from distracting context",
    }
    return mapping.get(scale, mapping["medium"])


def compile_shot_prompt(
    *,
    ledger: dict[str, Any],
    scene: dict[str, Any],
    shot: dict[str, Any],
) -> str:
    shot_type = _text(shot.get("shot_type") or "single_camera")
    scale = _text(shot.get("shot_scale") or "medium").lower()
    style = _text(ledger.get("visual_style")) or "professional documentary photography"
    setting = _text(scene.get("setting")) or "context appropriate to the spoken claim"
    acceptance = "; ".join(
        _text(item)
        for item in shot.get("acceptance_criteria") or []
        if _text(item)
    )
    if shot_type in {"comparison", "diagram_background", "recap_comparison"}:
        composition = (
            "Structured comparison composition with clearly separated subjects, "
            "consistent scale logic, clean local-overlay space, and no generated text."
        )
    else:
        composition = (
            "One coherent camera-real scene, not a collage, panel grid, infographic, "
            "or montage."
        )
    parts = (
        f"Viewer takeaway: {_text(shot.get('viewer_takeaway'))}.",
        f"Primary subject: {_text(shot.get('subject'))}.",
        f"Observable action: {_text(shot.get('action'))}.",
        f"Evidence that must be readable: {_text(shot.get('evidence_detail'))}.",
        f"Shot design: {_scale_instruction(scale)}; camera angle: {_text(shot.get('camera_angle'))}; focal point: {_text(shot.get('focal_point'))}.",
        composition,
        f"Subordinate setting: {setting}.",
        f"Visual style: {style}; professional natural light, credible materials, coherent anatomy and geometry, 16:9 landscape.",
        f"Continuity anchors: {_text(shot.get('continuity_anchors')) or 'preserve the approved subject, period, palette, and environment logic'}.",
        f"Composition safety: {_text(shot.get('subtitle_safe_area'))}; keep the focal evidence outside the subtitle band.",
        f"Acceptance criteria: {acceptance}." if acceptance else "",
        "No generated text, labels, captions, watermark, logo, modern contamination, glossy toy/CGI look, malformed anatomy, or irrelevant spectacle.",
    )
    return " ".join(part for part in parts if part)


def _finite_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score):
        return None
    return max(0.0, min(100.0, score))


def _weighted_score(dimensions: Any) -> float | None:
    if not isinstance(dimensions, dict):
        return None
    total = 0.0
    for name, weight in DIMENSION_WEIGHTS.items():
        score = _finite_score(dimensions.get(name))
        if score is None:
            return None
        total += score * (weight / 100.0)
    return round(total, 3)


def rank_candidate_assessments(
    assessments: list[dict[str, Any]],
    *,
    threshold: float = QUALITY_THRESHOLD,
) -> CandidateDecision:
    passing_source: list[tuple[str, float]] = []
    rejected: dict[str, tuple[str, ...]] = {}
    best_score = 0.0
    for index, assessment in enumerate(assessments):
        candidate_id = _text(assessment.get("candidate_id")) or f"candidate[{index}]"
        reasons: list[str] = []
        if _provider(assessment.get("provider")) not in OPENAI_PROVIDERS:
            reasons.append("non_openai_source_provider")
        if _provider(assessment.get("judge_provider")) not in OPENAI_PROVIDERS:
            reasons.append("non_openai_judge_provider")
        blockers = assessment.get("hard_blockers")
        if not isinstance(blockers, list):
            reasons.append("hard_blockers_missing")
        else:
            reasons.extend(
                f"hard_blocker:{_text(item)}" for item in blockers if _text(item)
            )
        evidence = assessment.get("evidence")
        if not isinstance(evidence, list) or not any(_text(item) for item in evidence):
            reasons.append("vision_evidence_missing")
        score = _weighted_score(assessment.get("dimensions"))
        if score is None:
            reasons.append("quality_dimensions_invalid")
        else:
            best_score = max(best_score, score)
        if reasons:
            rejected[candidate_id] = tuple(reasons)
            continue
        passing_source.append((candidate_id, score or 0.0))

    ranked = sorted(passing_source, key=lambda item: (-item[1], item[0]))
    ranked_ids = tuple(candidate_id for candidate_id, _ in ranked)
    passing_threshold = [item for item in ranked if item[1] >= threshold]
    if not passing_threshold:
        return CandidateDecision(
            status="blocked",
            selected_candidate_id=None,
            ranked_candidate_ids=ranked_ids,
            best_score=round(best_score, 3),
            rejected=rejected,
        )
    selected_id, selected_score = passing_threshold[0]
    return CandidateDecision(
        status="selected",
        selected_candidate_id=selected_id,
        ranked_candidate_ids=tuple(
            candidate_id for candidate_id, score in ranked if score >= threshold
        ),
        best_score=round(selected_score, 3),
        rejected=rejected,
    )


__all__ = [
    "CandidateDecision",
    "DIMENSION_WEIGHTS",
    "LedgerQualityReport",
    "QUALITY_THRESHOLD",
    "candidate_budget_for_shot",
    "compile_shot_prompt",
    "rank_candidate_assessments",
    "validate_quality_ledger",
]
