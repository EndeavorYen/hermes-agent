from __future__ import annotations

from typing import Any

from agent.visual.eval_dimensions import combine_weighted_scores


VERSION = "visual_reward_model.v0.2"

DEFAULT_WEIGHTS = {
    "artifact_validity": 0.20,
    "provider_reliability": 0.15,
    "delivery_health": 0.10,
    "reference_adherence": 0.15,
    "aesthetic_fit": 0.15,
    "novelty": 0.05,
    "motion_quality": 0.10,
    "user_preference_fit": 0.05,
    "preference_dimension_fit": 0.05,
}


def score_visual_candidate(
    candidate: dict[str, Any],
    *,
    provider_stats: dict[str, Any],
    preference_profile: dict[str, Any],
) -> dict[str, Any]:
    hard_gate_passed = candidate.get("hard_gate", {}).get("passed") is True
    judge_scores = candidate.get("judge_scores") if isinstance(candidate.get("judge_scores"), dict) else {}
    provider_reliability, delivery_health, provider_confidence = _provider_scores(
        candidate,
        provider_stats,
    )
    dimensions = {
        "artifact_validity": _artifact_validity(candidate) if hard_gate_passed else 0.0,
        "provider_reliability": provider_reliability,
        "delivery_health": delivery_health,
        "reference_adherence": _dimension(judge_scores, "reference_adherence", 0.5),
        "aesthetic_fit": _dimension(judge_scores, "aesthetic_fit", 0.5),
        "novelty": _dimension(judge_scores, "novelty", 0.5),
        "motion_quality": _motion_quality(candidate, judge_scores),
        "user_preference_fit": _preference_fit(candidate, preference_profile),
        "preference_dimension_fit": _preference_dimension_fit(candidate),
    }
    final_score = 0.0 if not hard_gate_passed else combine_weighted_scores(dimensions, DEFAULT_WEIGHTS)
    confidence = _confidence(
        hard_gate_passed=hard_gate_passed,
        judge_scores=judge_scores,
        provider_confidence=provider_confidence,
        preference_profile=preference_profile,
    )
    return {
        "version": VERSION,
        "dimensions": dimensions,
        "weights": DEFAULT_WEIGHTS,
        "final_score": final_score,
        "confidence": confidence,
        "uncertainty_reasons": _uncertainty_reasons(
            judge_scores=judge_scores,
            candidate=candidate,
            preference_profile=preference_profile,
            provider_confidence=provider_confidence,
        ),
    }


def _artifact_validity(candidate: dict[str, Any]) -> float:
    return _clamp(candidate.get("scores", {}).get("final_score", 1.0))


def _provider_scores(
    candidate: dict[str, Any],
    provider_stats: dict[str, Any],
) -> tuple[float, float, float]:
    row = _provider_row(candidate, provider_stats)
    if row is None:
        return 0.5, 0.5, 0.0
    reliability = _clamp(row.get("generation_success_rate", 0.5))
    delivery = _clamp(row.get("delivery_success_rate", 0.5))
    attempt_count = int(_coerce_float(row.get("attempt_count", 0)))
    provider_confidence = min(1.0, attempt_count / 10.0) if attempt_count else 0.5
    return reliability, delivery, provider_confidence


def _provider_row(candidate: dict[str, Any], provider_stats: dict[str, Any]) -> dict[str, Any] | None:
    provider = candidate.get("provider")
    model = candidate.get("model")
    if provider and model:
        row = provider_stats.get(f"{provider}:{model}")
        if isinstance(row, dict):
            return row
    if len(provider_stats) == 1:
        only_row = next(iter(provider_stats.values()))
        return only_row if isinstance(only_row, dict) else None
    return None


def _motion_quality(candidate: dict[str, Any], judge_scores: dict[str, Any]) -> float:
    if "motion_quality" in judge_scores:
        return _dimension(judge_scores, "motion_quality", 0.5)
    return 1.0 if candidate.get("kind") != "video" else 0.5


def _preference_fit(candidate: dict[str, Any], preference_profile: dict[str, Any]) -> float:
    quality_issues = _string_list(candidate.get("quality_issues"))
    sample_count = int(_coerce_float(preference_profile.get("sample_count", 0)))
    if sample_count <= 0:
        return 0.45 if quality_issues else 0.5
    signal_score = _candidate_signal_score(candidate, preference_profile)
    issue_penalty = _candidate_issue_penalty(quality_issues, preference_profile)
    return _clamp(0.5 + signal_score * 0.35 - issue_penalty * 0.35)


def _preference_dimension_fit(candidate: dict[str, Any]) -> float:
    dimensions = candidate.get("preference_dimensions")
    if not isinstance(dimensions, dict) or not dimensions:
        return 0.5
    values = [_clamp(value) for value in dimensions.values() if value is not None]
    if not values:
        return 0.5
    return round(sum(values) / len(values), 4)


def _candidate_signal_score(candidate: dict[str, Any], preference_profile: dict[str, Any]) -> float:
    quality_signals = _string_list(candidate.get("quality_signals"))
    if not quality_signals:
        return 0.0
    signals = preference_profile.get("signals")
    if not isinstance(signals, dict):
        return 0.0
    values = [
        _coerce_float(signals.get(signal, {}).get("weight"))
        for signal in quality_signals
        if isinstance(signals.get(signal), dict)
    ]
    if not values:
        return 0.0
    return sum(values) / len(values)


def _candidate_issue_penalty(quality_issues: list[str], preference_profile: dict[str, Any]) -> float:
    if not quality_issues:
        return 0.0
    issues = preference_profile.get("issues")
    if not isinstance(issues, dict):
        return 0.35
    values = [
        _coerce_float(issues.get(issue, {}).get("penalty"))
        if isinstance(issues.get(issue), dict)
        else 0.35
        for issue in quality_issues
    ]
    return sum(values) / len(values)


def _confidence(
    *,
    hard_gate_passed: bool,
    judge_scores: dict[str, Any],
    provider_confidence: float,
    preference_profile: dict[str, Any],
) -> float:
    judge_confidence = min(1.0, len(judge_scores) / 4.0)
    sample_count = int(_coerce_float(preference_profile.get("sample_count", 0)))
    preference_confidence = min(1.0, sample_count / 5.0)
    confidence = provider_confidence * 0.30 + judge_confidence * 0.35 + preference_confidence * 0.35
    if not hard_gate_passed:
        confidence = min(confidence, 0.2)
    return round(_clamp(confidence), 4)


def _uncertainty_reasons(
    *,
    judge_scores: dict[str, Any],
    candidate: dict[str, Any],
    preference_profile: dict[str, Any],
    provider_confidence: float,
) -> list[str]:
    reasons = []
    if "reference_adherence" not in judge_scores:
        reasons.append("reference_adherence_missing")
    if "aesthetic_fit" not in judge_scores:
        reasons.append("aesthetic_fit_missing")
    if int(_coerce_float(preference_profile.get("sample_count", 0))) < 5:
        reasons.append("low_preference_sample_count")
    if provider_confidence < 0.5:
        reasons.append("low_provider_sample_count")
    profile_issues = preference_profile.get("issues")
    profile_issues = profile_issues if isinstance(profile_issues, dict) else {}
    for issue in _string_list(candidate.get("quality_issues")):
        if issue in profile_issues:
            reasons.append(f"matched_preference_issue_{issue}")
        else:
            reasons.append(f"candidate_quality_issue_{issue}")
    dimensions = candidate.get("preference_dimensions")
    if isinstance(dimensions, dict):
        for dimension, value in dimensions.items():
            dimension_text = str(dimension or "").strip()
            if dimension_text and _clamp(value) < 0.5:
                reasons.append(f"low_preference_dimension_{dimension_text}")
    return reasons


def _dimension(judge_scores: dict[str, Any], key: str, default: float) -> float:
    return _clamp(judge_scores.get(key, default))


def _clamp(value: Any) -> float:
    return max(0.0, min(1.0, _coerce_float(value)))


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]
