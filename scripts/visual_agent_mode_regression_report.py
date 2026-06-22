#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

from agent.visual.agent_mode.planner import plan_visual_agent_request


@dataclass(frozen=True)
class VisualAgentCase:
    case_id: str
    prompt: str
    attachments: tuple[str, ...] = ()
    expect_image: bool | None = None
    expect_video: bool | None = None
    min_candidate_budget: int | None = None
    expect_reason: str | None = None
    expect_duration: int | None = None
    expect_aspect_ratio: str | None = None


_CASES: tuple[VisualAgentCase, ...] = (
    VisualAgentCase(
        case_id="image_plus_video_reference",
        prompt="請用這張 reference 產出一張圖片和一段 6 秒影片",
        attachments=("/tmp/ref.png",),
        expect_image=True,
        expect_video=True,
        min_candidate_budget=1,
        expect_reason="image_plus_video_request",
        expect_duration=6,
    ),
    VisualAgentCase(
        case_id="attachment_to_video",
        prompt="用這張圖產生 6 秒短片",
        attachments=("/tmp/ref.png",),
        expect_image=False,
        expect_video=True,
        expect_reason="attachment_to_video_request",
        expect_duration=6,
    ),
    VisualAgentCase(
        case_id="text_video_image_first",
        prompt="幫我產生一段 6 秒時尚短片，主體是霧黑鋼筆",
        expect_image=False,
        expect_video=True,
        min_candidate_budget=2,
        expect_reason="text_to_video_image_first_request",
        expect_duration=6,
    ),
    VisualAgentCase(
        case_id="image_only_product",
        prompt="幫我做一張乾淨產品攝影圖",
        expect_image=True,
        expect_video=False,
        min_candidate_budget=1,
        expect_reason="image_request",
        expect_aspect_ratio="16:9",
    ),
)


def build_visual_agent_mode_regression_report() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for case in _CASES:
        plan = plan_visual_agent_request(case.prompt, attachments=list(case.attachments))
        case_failures = _validate_case(case, plan)
        summary = _summarize_plan(case, plan, failures=case_failures)
        cases.append(summary)
        if case_failures:
            failures.append({"case_id": case.case_id, "failures": case_failures})

    return {
        "success": not failures,
        "case_count": len(cases),
        "failure_count": len(failures),
        "failures": failures,
        "cases": cases,
    }


def _validate_case(case: VisualAgentCase, plan: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    args = plan.get("arguments") if isinstance(plan, dict) else {}
    if not isinstance(args, dict):
        args = {}

    if plan.get("tool_name") != "visual_package_generate":
        failures.append("wrong_tool")
    if not plan.get("should_use_visual_package"):
        failures.append("visual_package_not_selected")
    if case.expect_reason is not None and plan.get("reason") != case.expect_reason:
        failures.append("wrong_reason")
    if case.expect_image is not None and args.get("include_image") is not case.expect_image:
        failures.append("wrong_include_image")
    if case.expect_video is not None and args.get("include_video") is not case.expect_video:
        failures.append("wrong_include_video")
    if case.min_candidate_budget is not None:
        candidate_budget = args.get("candidate_budget")
        if not isinstance(candidate_budget, int) or candidate_budget < case.min_candidate_budget:
            failures.append(f"candidate_budget_lt_{case.min_candidate_budget}")
    if case.expect_duration is not None and args.get("duration") != case.expect_duration:
        failures.append("wrong_duration")
    if case.expect_aspect_ratio is not None and args.get("aspect_ratio") != case.expect_aspect_ratio:
        failures.append("wrong_aspect_ratio")
    if "autonomy_level" in args:
        failures.append("advanced_autonomy_leaked")
    return failures


def _summarize_plan(
    case: VisualAgentCase,
    plan: dict[str, Any],
    *,
    failures: list[str],
) -> dict[str, Any]:
    args = plan.get("arguments") if isinstance(plan, dict) else {}
    if not isinstance(args, dict):
        args = {}
    return {
        "case_id": case.case_id,
        "success": not failures,
        "reason": plan.get("reason"),
        "confidence": plan.get("confidence"),
        "arguments": {
            "include_image": args.get("include_image"),
            "include_video": args.get("include_video"),
            "candidate_budget": args.get("candidate_budget"),
            "video_budget": args.get("video_budget"),
            "duration": args.get("duration"),
            "aspect_ratio": args.get("aspect_ratio"),
            "attachment_count": len(args.get("attachments") or []),
            "has_autonomy_level": "autonomy_level" in args,
        },
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a privacy-safe visual agent mode regression report.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)
    payload = build_visual_agent_mode_regression_report()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "pass" if payload["success"] else "fail"
        print(f"visual agent mode regression report {status}")
    return 0 if payload["success"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
