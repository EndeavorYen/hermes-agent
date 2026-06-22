#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.feedback_policy import resolve_visual_feedback_policy
from tools.visual_package_tool import _apply_first_pass_quality_guidance
from tools.visual_package_tool import _quality_guidance_plan


@dataclass(frozen=True)
class ClosedLoopCase:
    case_id: str
    action: dict[str, Any]
    wants_image: bool
    wants_video: bool
    default_candidate_budget: int
    request_category: str
    expected_checks: tuple[str, ...]


_PRIVATE_PROMPT = "closed-loop private prompt"


_CASES: tuple[ClosedLoopCase, ...] = (
    ClosedLoopCase(
        case_id="focus_operator_legwear",
        action={
            "type": "apply_quality_focus_operator",
            "track": "aesthetic",
            "source": "live_quality_burn",
            "focus": "legwear_material",
            "dimension": "fashion_material_quality",
            "strategy_operator": "refine_legwear_material",
            "repair_hint": "improve_fashion_material_quality",
            "quality_issues": ["stockings_bad"],
            "requires_human_feedback": False,
        },
        wants_image=True,
        wants_video=True,
        default_candidate_budget=1,
        request_category="fashion_portrait",
        expected_checks=(
            "candidate_budget_increased",
            "rerank_enabled",
            "quality_repair_enabled",
            "image_guidance_enabled",
            "prompt_guidance_applied",
            "dimension_guidance_present",
            "quality_focus_operator_recorded",
        ),
    ),
    ClosedLoopCase(
        case_id="image_first_video_operator",
        action={
            "type": "prefer_image_first_video",
            "track": "provider",
            "source": "live_quality_burn",
            "strategy_operator": "image_first_rank_then_video",
            "requires_human_feedback": False,
        },
        wants_image=True,
        wants_video=True,
        default_candidate_budget=1,
        request_category="product",
        expected_checks=(
            "candidate_budget_increased",
            "rerank_enabled",
            "image_first_video_enabled",
        ),
    ),
    ClosedLoopCase(
        case_id="proven_strategy_operator",
        action={
            "type": "prefer_strategy",
            "track": "aesthetic",
            "source": "live_quality_burn",
            "bucket": "live_visual_agent_mode",
            "strategy_signature": "image_first_rank_then_video",
            "candidate_budget": 2,
            "confidence": 0.84,
            "requires_human_feedback": False,
        },
        wants_image=True,
        wants_video=True,
        default_candidate_budget=1,
        request_category="product",
        expected_checks=(
            "candidate_budget_increased",
            "rerank_enabled",
            "image_first_video_enabled",
            "strategy_preference_applied",
        ),
    ),
    ClosedLoopCase(
        case_id="preference_dimension_evidence_operator",
        action={
            "type": "require_preference_dimension_evidence",
            "track": "evaluation",
            "source": "live_quality_burn",
            "focus": "adult_fashion_portrait",
            "dimension": "subject_beauty",
            "evaluation_operator": "inline_vision_preference_dimensions",
            "requires_human_feedback": False,
        },
        wants_image=True,
        wants_video=True,
        default_candidate_budget=1,
        request_category="fashion_portrait",
        expected_checks=(
            "preference_dimension_evidence_required",
        ),
    ),
)


def build_visual_closed_loop_regression_report() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for case in _CASES:
        summary = _evaluate_case(case)
        cases.append(summary)
        case_failures = summary.get("failures") if isinstance(summary.get("failures"), list) else []
        if case_failures:
            failures.append({"case_id": case.case_id, "failures": case_failures})
    return {
        "success": not failures,
        "case_count": len(cases),
        "failure_count": len(failures),
        "failures": failures,
        "cases": cases,
        "self_review": {
            "raw_prompt_exposed": False,
            "reduces_human_intervention": True,
            "checks_policy_application": True,
        },
    }


def _evaluate_case(case: ClosedLoopCase) -> dict[str, Any]:
    baseline = resolve_visual_feedback_policy(
        {"next_actions": [], "policy_sources": ["baseline"]},
        wants_image=case.wants_image,
        wants_video=case.wants_video,
        explicit_candidate_budget=None,
        default_candidate_budget=case.default_candidate_budget,
    )
    applied = resolve_visual_feedback_policy(
        {
            "next_actions": [case.action],
            "policy_sources": ["feedback_loop", "scheduled_self_validation"],
        },
        wants_image=case.wants_image,
        wants_video=case.wants_video,
        explicit_candidate_budget=None,
        default_candidate_budget=case.default_candidate_budget,
    )
    guidance = _quality_guidance_plan(applied, request_category=case.request_category)
    image_guidance = guidance.get("image") if isinstance(guidance.get("image"), dict) else {}
    guided_prompt = _apply_first_pass_quality_guidance(_PRIVATE_PROMPT, image_guidance)
    dimension_terms = _dimension_terms(applied)
    checks = _checks(
        baseline=baseline,
        applied=applied,
        image_guidance=image_guidance,
        guided_prompt=guided_prompt,
        dimension_terms=dimension_terms,
    )
    failures = [name for name in case.expected_checks if checks.get(name) is not True]
    return {
        "case_id": case.case_id,
        "action_type": str(case.action.get("type") or ""),
        "success": not failures,
        "failures": failures,
        "policy_delta": {
            "candidate_budget_before": baseline.get("candidate_budget"),
            "candidate_budget_after": applied.get("candidate_budget"),
            "candidate_budget_increased": checks["candidate_budget_increased"],
            "candidate_budget_source": applied.get("candidate_budget_source"),
            "rerank_enabled": checks["rerank_enabled"],
            "quality_repair_enabled": checks["quality_repair_enabled"],
            "image_first_video_enabled": checks["image_first_video_enabled"],
            "strategy_preference_applied": checks["strategy_preference_applied"],
            "preference_dimension_evidence_required": checks["preference_dimension_evidence_required"],
        },
        "quality_guidance": {
            "image_enabled": checks["image_guidance_enabled"],
            "prompt_guidance_applied": checks["prompt_guidance_applied"],
            "dimension_terms": dimension_terms,
        },
        "applied_action_types": _string_list(applied.get("applied_action_types")),
        "applied_action_sources": _string_list(applied.get("applied_action_sources")),
    }


def _checks(
    *,
    baseline: dict[str, Any],
    applied: dict[str, Any],
    image_guidance: dict[str, Any],
    guided_prompt: str,
    dimension_terms: list[str],
) -> dict[str, bool]:
    baseline_budget = _int(baseline.get("candidate_budget"))
    applied_budget = _int(applied.get("candidate_budget"))
    return {
        "candidate_budget_increased": applied_budget > baseline_budget,
        "rerank_enabled": applied.get("rerank_before_delivery") is True,
        "quality_repair_enabled": (
            applied.get("quality_repair_mode") in {"preferred", "escalated"}
            or _repair_mode(applied, "image") in {"preferred", "escalated"}
        ),
        "image_first_video_enabled": applied.get("prefer_image_first_video") is True,
        "strategy_preference_applied": isinstance(applied.get("strategy_preference"), dict),
        "preference_dimension_evidence_required": (
            applied.get("require_preference_dimension_evidence") is True
            and bool(applied.get("required_preference_dimensions"))
        ),
        "image_guidance_enabled": image_guidance.get("enabled") is True,
        "prompt_guidance_applied": guided_prompt != _PRIVATE_PROMPT and _PRIVATE_PROMPT in guided_prompt,
        "dimension_guidance_present": bool(dimension_terms),
        "quality_focus_operator_recorded": bool(applied.get("quality_focus_operators")),
    }


def _dimension_terms(policy: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in policy.get("repair_dimensions") or []:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        if dimension and dimension not in values:
            values.append(dimension)
    return values


def _repair_mode(policy: dict[str, Any], modality: str) -> str:
    modes = policy.get("quality_repair_modes")
    if not isinstance(modes, dict):
        return ""
    return str(modes.get(modality) or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    strings: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in strings:
            strings.append(text)
    return strings


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate visual self-improvement closed-loop policy application.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = build_visual_closed_loop_regression_report()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        status = "passed" if payload["success"] else "failed"
        print(f"visual closed-loop regression {status}")
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
