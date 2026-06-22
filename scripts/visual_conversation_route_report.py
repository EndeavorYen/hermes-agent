#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.prompt_builder import build_visual_package_tool_guidance
from agent.visual.agent_mode.planner import plan_visual_agent_request
from tools.visual_agent_tool import VISUAL_AGENT_SCHEMA


@dataclass(frozen=True)
class ConversationRouteCase:
    case_id: str
    prompt: str
    attachments: tuple[str, ...] = ()
    expect_image: bool | None = None
    expect_video: bool | None = None
    min_candidate_budget: int | None = None
    expect_reason: str | None = None
    expect_storyboard: bool | None = None
    min_shot_count: int | None = None


_CASES: tuple[ConversationRouteCase, ...] = (
    ConversationRouteCase(
        case_id="friendly_product_image_video",
        prompt="幫我做一張產品照和一段短片：霧黑鋼筆放在白紙上，柔和窗光。",
        expect_image=True,
        expect_video=True,
        min_candidate_budget=1,
        expect_reason="image_plus_video_request",
    ),
    ConversationRouteCase(
        case_id="friendly_draw_character",
        prompt="幫我畫一位銀髮高冷美少女角色，乾淨背景",
        expect_image=True,
        expect_video=False,
        min_candidate_budget=1,
        expect_reason="image_request",
    ),
    ConversationRouteCase(
        case_id="friendly_text_video",
        prompt="幫我做一段 4 秒乾淨產品短片，主體是一支霧黑鋼筆",
        expect_image=False,
        expect_video=True,
        min_candidate_budget=2,
        expect_reason="text_to_video_image_first_request",
    ),
    ConversationRouteCase(
        case_id="friendly_move_attachment_video",
        prompt="讓這張圖動起來，做成 6 秒自然鏡頭",
        attachments=("/tmp/ref.png",),
        expect_image=False,
        expect_video=True,
        min_candidate_budget=2,
        expect_reason="attachment_to_video_image_first_request",
    ),
    ConversationRouteCase(
        case_id="friendly_storyboard_video",
        prompt="請做一支 3 段分鏡的連貫產品影片：霧黑鋼筆放在白紙上，柔和窗光。",
        expect_image=False,
        expect_video=True,
        min_candidate_budget=2,
        expect_reason="storyboard_video_request",
        expect_storyboard=True,
        min_shot_count=3,
    ),
)


def build_visual_conversation_route_report() -> dict[str, Any]:
    guidance = build_visual_package_tool_guidance(
        {"visual_agent_generate", "visual_package_generate", "image_generate", "video_generate"}
    )
    schema_description = str(VISUAL_AGENT_SCHEMA.get("description") or "")
    contract_failures = _contract_failures(guidance=guidance, schema_description=schema_description)

    cases: list[dict[str, Any]] = []
    case_failures: list[dict[str, Any]] = []
    for case in _CASES:
        plan = plan_visual_agent_request(case.prompt, attachments=list(case.attachments))
        failures = _validate_case(case, plan)
        cases.append(_summarize_case(case, plan, failures=failures))
        if failures:
            case_failures.append({"case_id": case.case_id, "failures": failures})

    failures = [*contract_failures, *[f"case_failed:{item['case_id']}" for item in case_failures]]
    return {
        "success": not failures,
        "recommended_tool": "visual_agent_generate",
        "case_count": len(cases),
        "failures": failures,
        "case_failures": case_failures,
        "contract": {
            "visual_agent_guidance_present": "visual_agent_generate" in guidance,
            "advanced_parameters_not_required": "Do not ask the user for advanced" in guidance,
            "draw_character_guidance_present": "draw/anime/character" in guidance,
            "schema_supports_friendly_prompts": "draw/anime/character art prompts" in schema_description,
        },
        "cases": cases,
    }


def _contract_failures(*, guidance: str, schema_description: str) -> list[str]:
    failures: list[str] = []
    if "visual_agent_generate" not in guidance:
        failures.append("visual_agent_guidance_missing")
    if "Do not ask the user for advanced" not in guidance:
        failures.append("advanced_parameter_avoidance_missing")
    if "draw/anime/character" not in guidance:
        failures.append("draw_character_guidance_missing")
    if "draw/anime/character art prompts" not in schema_description:
        failures.append("visual_agent_schema_friendly_prompt_missing")
    return failures


def _validate_case(case: ConversationRouteCase, plan: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    args = plan.get("arguments") if isinstance(plan, dict) else {}
    if not isinstance(args, dict):
        args = {}
    if plan.get("tool_name") != "visual_package_generate":
        failures.append("wrong_dispatch_tool")
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
    storyboard = args.get("storyboard") if isinstance(args.get("storyboard"), dict) else {}
    if case.expect_storyboard is not None and bool(storyboard.get("enabled")) is not case.expect_storyboard:
        failures.append("wrong_storyboard_enabled")
    if case.min_shot_count is not None:
        shot_count = storyboard.get("shot_count")
        if not isinstance(shot_count, int) or shot_count < case.min_shot_count:
            failures.append(f"shot_count_lt_{case.min_shot_count}")
        if storyboard.get("source_image_policy") != "one_ranked_image_per_shot":
            failures.append("wrong_storyboard_source_policy")
    if "autonomy_level" in args:
        failures.append("advanced_autonomy_leaked")
    return failures


def _summarize_case(
    case: ConversationRouteCase,
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
            "aspect_ratio": args.get("aspect_ratio"),
            "duration": args.get("duration"),
            "attachment_count": len(args.get("attachments") or []),
            "has_autonomy_level": "autonomy_level" in args,
            "storyboard_enabled": bool(
                isinstance(args.get("storyboard"), dict) and args["storyboard"].get("enabled")
            ),
            "storyboard_shot_count": (
                args.get("storyboard", {}).get("shot_count")
                if isinstance(args.get("storyboard"), dict)
                else None
            ),
        },
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a privacy-safe visual conversation route report.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)
    payload = build_visual_conversation_route_report()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = "pass" if payload["success"] else "fail"
        print(f"visual conversation route report {status}")
    return 0 if payload["success"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
