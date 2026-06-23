#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hermes_constants import get_hermes_home
from agent.visual.action_dedupe import dedupe_actions as _dedupe_actions
from agent.visual.agent_mode.planner import plan_visual_agent_request
from gateway.config import PlatformConfig
from gateway.platforms.slack import SlackAdapter
from scripts.visual_conversation_route_report import build_visual_conversation_route_report
from scripts.visual_live_provider_e2e import DEFAULT_PROMPT
from scripts.visual_slack_delivery_e2e import build_visual_slack_delivery_e2e_report
from scripts.visual_slack_delivery_e2e import _resolve_target


def build_visual_slack_conversation_e2e_report(
    *,
    mode: str = "fixture",
    work_dir: str | Path | None = None,
    prompt: str = DEFAULT_PROMPT,
    target: str | None = None,
    thread_id: str | None = None,
    candidate_budget: int = 1,
    video_budget: int = 1,
    duration: int = 4,
    require_video: bool = True,
    upload: bool | None = None,
    repair_budget: int = 1,
    record_quality_run: bool | None = None,
    quality_run_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    mode = mode.strip().lower()
    if mode not in {"fixture", "live"}:
        return _failure_result(mode=mode, failures=["unsupported_mode"])

    destination_id = _resolve_target(mode=mode, target=target)
    if not destination_id:
        return {
            "success": False,
            "mode": mode,
            "failures": ["missing_slack_target"],
            "ingress": {"status": "skipped", "reason": "missing_slack_target"},
            "conversation_route": {},
            "slack_delivery": {"status": "skipped", "reason": "missing_slack_target"},
            "next_actions": [],
            "privacy": {
                "raw_prompt_omitted": True,
                "stores_prompt_hash_only": True,
            },
        }
    ingress_result = _capture_slack_message_event(
        prompt=prompt,
        target=destination_id,
        thread_id=thread_id,
    )
    ingress_summary = _dict(ingress_result.get("summary"))
    failures = list(ingress_result.get("failures") or [])
    captured_event = ingress_result.get("event")

    conversation_route = build_visual_conversation_route_report()
    if conversation_route.get("success") is not True:
        failures.append("conversation_route_failed")

    initial_slack_delivery: dict[str, Any] = {}
    repair_attempt: dict[str, Any] = {"attempted": False, "reason": "not_needed"}
    if captured_event is None:
        slack_delivery: dict[str, Any] = {
            "status": "skipped",
            "reason": "slack_ingress_failed",
        }
    else:
        captured_prompt = str(getattr(captured_event, "text", "") or "")
        attachments = _string_list(getattr(captured_event, "media_urls", None))
        if not captured_prompt.strip():
            failures.append("slack_ingress_missing_text")
        visual_agent_plan = plan_visual_agent_request(captured_prompt, attachments=attachments)
        planned_args = _dict(visual_agent_plan.get("arguments"))
        delivery_thread_id = getattr(captured_event.source, "thread_id", None)
        delivery_kwargs = {
            "mode": mode,
            "work_dir": work_dir,
            "prompt": captured_prompt,
            "attachments": _string_list(planned_args.get("attachments")),
            "target": str(getattr(captured_event.source, "chat_id", "") or destination_id),
            "thread_id": delivery_thread_id,
            "candidate_budget": _planned_int(planned_args.get("candidate_budget"), candidate_budget),
            "video_budget": _planned_int(planned_args.get("video_budget"), video_budget),
            "duration": _planned_int(planned_args.get("duration"), duration),
            "require_video": _planned_bool(planned_args.get("include_video"), require_video),
            "include_image": _planned_optional_bool(planned_args.get("include_image")),
            "aspect_ratio": _planned_optional_str(planned_args.get("aspect_ratio")),
            "storyboard": _planned_optional_dict(planned_args.get("storyboard")),
            "upload": upload,
        }
        slack_delivery = build_visual_slack_delivery_e2e_report(**delivery_kwargs)
        initial_slack_delivery = slack_delivery
        if slack_delivery.get("success") is not True:
            initial_next_actions = _next_actions_from_slack_delivery(slack_delivery)
            repair_attempt = _attempt_repair_delivery(
                delivery_kwargs=delivery_kwargs,
                next_actions=initial_next_actions,
                policy_home=_repair_policy_home(mode=mode, work_dir=work_dir),
                repair_budget=repair_budget,
            )
            repaired_delivery = repair_attempt.get("slack_delivery")
            if repair_attempt.get("success") is True and isinstance(repaired_delivery, dict):
                slack_delivery = repaired_delivery
            else:
                failures.append("slack_delivery_failed")

    next_actions = _dedupe_actions(
        _next_actions_from_slack_delivery(initial_slack_delivery)
        + _next_actions_from_slack_delivery(slack_delivery)
    )
    visual_agent_plan_summary = _summarize_visual_agent_plan(
        visual_agent_plan if "visual_agent_plan" in locals() else {}
    )
    self_review = _build_slack_conversation_self_review(
        slack_delivery=slack_delivery,
        initial_slack_delivery=initial_slack_delivery,
        visual_agent_plan=visual_agent_plan_summary,
        next_actions=next_actions,
        failures=failures,
    )
    report = {
        "success": not failures,
        "mode": mode,
        "failures": sorted(set(str(item) for item in failures if item)),
        "ingress": ingress_summary,
        "visual_agent_plan": visual_agent_plan_summary,
        "conversation_route": conversation_route,
        "initial_slack_delivery": initial_slack_delivery,
        "slack_delivery": slack_delivery,
        "repair_attempt": repair_attempt,
        "self_review": self_review,
        "next_actions": next_actions,
        "privacy": {
            "raw_prompt_omitted": True,
            "stores_prompt_hash_only": True,
        },
    }
    report["quality_run_record"] = _maybe_record_quality_run(
        report=report,
        mode=mode,
        work_dir=work_dir,
        record_quality_run=record_quality_run,
        output_dir=quality_run_output_dir,
    )
    return report


def _capture_slack_message_event(
    *,
    prompt: str,
    target: str,
    thread_id: str | None,
) -> dict[str, Any]:
    captured: list[Any] = []
    config = PlatformConfig(enabled=True, token="xoxb-fake-token")
    adapter = SlackAdapter(config)
    adapter._app = MagicMock()
    adapter._app.client = AsyncMock()
    adapter._bot_user_id = "U_BOT"
    adapter._running = True
    adapter.handle_message = AsyncMock(side_effect=lambda event: captured.append(event))

    ts = thread_id or "1700000000.000001"
    event: dict[str, Any] = {
        "channel": target,
        "channel_type": "im",
        "user": "U_VISUAL_USER",
        "text": prompt,
        "ts": ts,
        "team": "T_VISUAL",
    }
    if thread_id:
        event["thread_ts"] = thread_id

    try:
        with patch.object(
            adapter,
            "_resolve_user_name",
            new=AsyncMock(return_value="visual-tester"),
        ):
            asyncio.run(adapter._handle_slack_message(event))
    except Exception as exc:  # pragma: no cover - defensive report path
        return {
            "success": False,
            "failures": [f"slack_ingress_exception:{type(exc).__name__}"],
            "summary": {
                "success": False,
                "platform": "slack",
                "chat_id": target,
                "thread_id": thread_id,
            },
            "event": None,
        }

    if not captured:
        return {
            "success": False,
            "failures": ["slack_ingress_not_dispatched"],
            "summary": {
                "success": False,
                "platform": "slack",
                "chat_id": target,
                "thread_id": thread_id,
            },
            "event": None,
        }

    message_event = captured[0]
    summary = _summarize_message_event(message_event)
    return {
        "success": True,
        "failures": [],
        "summary": summary,
        "event": message_event,
    }


def _summarize_message_event(message_event: Any) -> dict[str, Any]:
    source = getattr(message_event, "source", None)
    text = str(getattr(message_event, "text", "") or "")
    message_type = getattr(message_event, "message_type", None)
    message_type_value = getattr(message_type, "value", None) or str(message_type or "")
    media_urls = getattr(message_event, "media_urls", None) or []
    return {
        "success": True,
        "platform": "slack",
        "message_type": message_type_value,
        "chat_id": str(getattr(source, "chat_id", "") or ""),
        "chat_type": str(getattr(source, "chat_type", "") or ""),
        "user_id_present": bool(getattr(source, "user_id", "") or ""),
        "thread_id": getattr(source, "thread_id", None),
        "message_id": str(getattr(message_event, "message_id", "") or ""),
        "media_count": len(media_urls),
        "prompt_length": len(text),
        "prompt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _planned_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _planned_bool(value: Any, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _planned_optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _planned_optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _planned_optional_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if item not in (None, "")]


def _summarize_visual_agent_plan(plan: dict[str, Any]) -> dict[str, Any]:
    args = _dict(plan.get("arguments")) if isinstance(plan, dict) else {}
    storyboard = _dict(args.get("storyboard"))
    return {
        "tool_name": plan.get("tool_name") if isinstance(plan, dict) else None,
        "should_use_visual_package": plan.get("should_use_visual_package") if isinstance(plan, dict) else None,
        "reason": plan.get("reason") if isinstance(plan, dict) else None,
        "confidence": plan.get("confidence") if isinstance(plan, dict) else None,
        "arguments": {
            "include_image": args.get("include_image"),
            "include_video": args.get("include_video"),
            "candidate_budget": args.get("candidate_budget"),
            "video_budget": args.get("video_budget"),
            "duration": args.get("duration"),
            "aspect_ratio": args.get("aspect_ratio"),
            "attachment_count": len(_string_list(args.get("attachments"))),
            "storyboard_enabled": bool(storyboard.get("enabled")),
            "storyboard_shot_count": storyboard.get("shot_count"),
        },
    }


def _build_slack_conversation_self_review(
    *,
    slack_delivery: dict[str, Any],
    initial_slack_delivery: dict[str, Any],
    visual_agent_plan: dict[str, Any],
    next_actions: list[dict[str, Any]],
    failures: list[Any],
) -> dict[str, Any]:
    visual = _dict(slack_delivery.get("visual"))
    delivery = _dict(slack_delivery.get("delivery"))
    recovery = _dict(visual.get("recovery_summary"))
    quality_gate = _dict(visual.get("quality_gate"))
    plan_args = _dict(visual_agent_plan.get("arguments"))
    video_source = _dict(visual.get("video_source"))

    provider_failure_count = _int(recovery.get("provider_failure_count"))
    duplicate_delivery_count = _int(delivery.get("duplicate_delivery_count"))
    internal_source_image_delivered = delivery.get("internal_source_image_delivered") is True
    missing_delivery = _string_list(delivery.get("missing_delivery_artifact_ids"))
    unexpected_delivery = _string_list(delivery.get("unexpected_delivery_artifact_ids"))
    deliverable_count = _int(delivery.get("deliverable_count"))
    sent_count = _int(delivery.get("sent_count"))
    quality_issues = _string_list(quality_gate.get("quality_issues"))
    preference_failures = _preference_dimension_failures(quality_gate.get("preference_dimension_failures"))
    quality_gate_success = quality_gate.get("success")
    if quality_gate_success is not False and (quality_gate or visual.get("quality_gate") == {}):
        quality_gate_success = True

    expects_video = plan_args.get("include_video") is True
    expects_video_only = expects_video and plan_args.get("include_image") is False
    image_first_video_source_covered = None
    if expects_video_only:
        image_first_video_source_covered = video_source.get("uses_ranked_selected_image") is True

    delivery_clean = (
        duplicate_delivery_count == 0
        and not internal_source_image_delivered
        and not missing_delivery
        and not unexpected_delivery
        and (deliverable_count == 0 or sent_count >= deliverable_count)
    )
    auto_next_actions = [
        action
        for action in next_actions
        if isinstance(action, dict) and action.get("requires_human_feedback") is not True
    ]
    blocking_reasons = sorted(
        set(
            [
                *[str(item) for item in failures if item],
                *quality_issues,
                *[failure["issue"] for failure in preference_failures if failure.get("issue")],
            ]
        )
    )
    if provider_failure_count > 0:
        blocking_reasons.append("provider_failures_detected")
    if not delivery_clean:
        blocking_reasons.append("delivery_not_clean")
    if image_first_video_source_covered is False:
        blocking_reasons.append("image_first_video_source_not_ranked_selected_image")

    final_success = slack_delivery.get("success") is True and not blocking_reasons
    initial_failed = bool(initial_slack_delivery) and initial_slack_delivery.get("success") is False
    if final_success and initial_failed:
        decision = "accept_after_repair"
    elif final_success:
        decision = "accept"
    elif auto_next_actions:
        decision = "needs_repair"
    else:
        decision = "blocked"

    requires_human_feedback = decision == "blocked" or any(
        action.get("requires_human_feedback") is True
        for action in next_actions
        if isinstance(action, dict)
    )
    return {
        "success": decision in {"accept", "accept_after_repair"},
        "decision": decision,
        "requires_human_feedback": requires_human_feedback,
        "reduces_human_intervention": not requires_human_feedback,
        "auto_next_action_count": len(auto_next_actions),
        "action_types": _action_types(auto_next_actions),
        "quality_gate_success": quality_gate_success,
        "quality_issue_count": len(quality_issues),
        "preference_failure_count": len(preference_failures),
        "provider_failure_count": provider_failure_count,
        "delivery_clean": delivery_clean,
        "deliverable_count": deliverable_count,
        "sent_count": sent_count,
        "duplicate_delivery_count": duplicate_delivery_count,
        "internal_source_image_delivered": internal_source_image_delivered,
        "image_first_video_source_covered": image_first_video_source_covered,
        "native_video_upload_covered": _int(delivery.get("uploaded_video_file_count")) > 0
        and _int(delivery.get("uploaded_remote_video_url_count")) == 0,
        "blocking_reasons": sorted(set(blocking_reasons)),
        "privacy_safe": True,
        "raw_prompt_omitted": True,
    }


def _attempt_repair_delivery(
    *,
    delivery_kwargs: dict[str, Any],
    next_actions: list[dict[str, Any]],
    policy_home: str | Path | None,
    repair_budget: int,
) -> dict[str, Any]:
    budget = _int(repair_budget)
    repair_actions = _repair_actions(next_actions)
    if budget <= 0:
        return {"attempted": False, "reason": "repair_budget_exhausted"}
    if not repair_actions:
        return {"attempted": False, "reason": "no_supported_repair_action"}
    first_action = repair_actions[0]
    action_types = _action_types(repair_actions)
    if policy_home is None:
        return {
            "attempted": False,
            "reason": "missing_policy_home",
            "action_type": first_action.get("type"),
            "action_types": action_types,
        }

    policy_write = _write_repair_policy_latest(policy_home=policy_home, actions=repair_actions)
    if policy_write.get("success") is not True:
        return {
            "attempted": True,
            "success": False,
            "reason": "repair_policy_write_failed",
            "action_type": first_action.get("type"),
            "action_types": action_types,
            "policy_written": False,
            "failures": policy_write.get("failures", []),
        }

    repaired_delivery = build_visual_slack_delivery_e2e_report(**delivery_kwargs)
    return {
        "attempted": True,
        "success": repaired_delivery.get("success") is True,
        "reason": "repair_delivery_succeeded"
        if repaired_delivery.get("success") is True
        else "repair_delivery_failed",
        "action_type": first_action.get("type"),
        "action_types": action_types,
        "policy_written": True,
        "slack_delivery": repaired_delivery,
        "failures": list(repaired_delivery.get("failures") or []),
    }


def _repair_policy_home(*, mode: str, work_dir: str | Path | None) -> Path | None:
    if str(mode or "").strip().lower() == "live":
        return get_hermes_home()
    return Path(work_dir) if work_dir is not None else None


def _repair_actions(next_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_reframe_actions: list[dict[str, Any]] = []
    quality_actions: list[dict[str, Any]] = []
    for action in next_actions:
        if action.get("requires_human_feedback") is True:
            continue
        action_type = action.get("type")
        if action_type == "safe_reframe_provider_retry":
            safe_reframe_actions.append(dict(action))
        elif action_type in {"repair_low_preference_dimension", "increase_candidate_budget", "rerank_before_slack"}:
            quality_actions.append(dict(action))
    if safe_reframe_actions:
        return [safe_reframe_actions[0]]
    if any(action.get("type") == "repair_low_preference_dimension" for action in quality_actions):
        return _dedupe_actions(quality_actions)
    return []


def _write_repair_policy_latest(*, policy_home: str | Path, actions: list[dict[str, Any]]) -> dict[str, Any]:
    latest_path = Path(policy_home) / "visual" / "self_validation" / "latest.json"
    try:
        payload = _read_json(latest_path)
        automation = payload.get("automation") if isinstance(payload.get("automation"), dict) else {}
        self_improvement = (
            automation.get("self_improvement")
            if isinstance(automation.get("self_improvement"), dict)
            else {}
        )
        self_improvement = dict(self_improvement)
        self_improvement["next_actions"] = _dedupe_actions(
            _action_list(self_improvement.get("next_actions")) + actions
        )
        self_improvement["action_count"] = len(self_improvement["next_actions"])
        self_improvement["reduces_human_intervention"] = bool(self_improvement["next_actions"])
        self_improvement["privacy_safe"] = True
        automation = dict(automation)
        automation["self_improvement"] = self_improvement
        payload = dict(payload)
        payload["success"] = True
        payload["mode"] = str(payload.get("mode") or "slack_conversation_repair_policy")
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()
        payload["automation"] = automation
        payload["privacy"] = {
            "raw_prompt_omitted": True,
            "stores_prompt_hash_only": True,
        }
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        latest_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"success": True}
    except Exception as exc:  # noqa: BLE001 - repair retry must return evidence, not crash the gate
        return {"success": False, "failures": [f"{type(exc).__name__}:{exc}"]}


def _maybe_record_quality_run(
    *,
    report: dict[str, Any],
    mode: str,
    work_dir: str | Path | None,
    record_quality_run: bool | None,
    output_dir: str | Path | None,
) -> dict[str, Any]:
    enabled = mode == "live" and (record_quality_run is True or (record_quality_run is None and work_dir is None))
    if not enabled:
        return {"status": "skipped", "reason": "not_enabled"}
    quality_run = _build_quality_run(report)
    target_dir = Path(output_dir) if output_dir is not None else get_hermes_home() / "visual" / "live_quality_burn"
    path = _write_quality_run(target_dir, quality_run)
    return {
        "success": True,
        "run_id": quality_run["run_id"],
        "path": str(path),
        "source": quality_run["source"],
    }


def _build_quality_run(report: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    slack_delivery = _dict(report.get("slack_delivery"))
    visual = _dict(slack_delivery.get("visual"))
    delivery = _dict(slack_delivery.get("delivery"))
    quality_gate = _dict(visual.get("quality_gate"))
    recovery = _dict(visual.get("recovery_summary"))
    plan_args = _dict(_dict(report.get("visual_agent_plan")).get("arguments"))
    request_id = str(visual.get("request_id") or delivery.get("request_id") or "").strip()
    run_id = _quality_run_id(now, request_id)
    quality_score = _quality_score(quality_gate)
    preference_failures = _preference_dimension_failures(quality_gate.get("preference_dimension_failures"))
    quality_issues = _string_list(quality_gate.get("quality_issues"))
    video_source_summary = _quality_run_video_source_summary(
        visual=visual,
        plan_args=plan_args,
        request_id=request_id,
    )
    video_missing_after_image_count = _quality_run_video_missing_after_image_count(
        visual=visual,
        plan_args=plan_args,
    )
    summary = {
        "case_count": 1 if slack_delivery else 0,
        "failed_case_count": 0 if report.get("success") is True else 1,
        "failed_case_ids": [] if report.get("success") is True else [run_id],
        "min_quality_score": quality_score,
        "quality_issue_count": len(quality_issues),
        "quality_issues": quality_issues,
        "preference_dimension_failure_count": len(preference_failures),
        "preference_dimension_failures": preference_failures,
        "image_first_video_source_case_count": video_source_summary["case_count"],
        "image_first_video_source_covered_count": video_source_summary["covered_count"],
        "image_first_video_source_failure_count": video_source_summary["failure_count"],
        "image_first_video_source_failure_case_ids": video_source_summary["failure_case_ids"],
        "video_missing_after_image_count": video_missing_after_image_count,
        "video_missing_after_image_case_ids": [run_id] if video_missing_after_image_count else [],
        "provider_failure_count": _int(recovery.get("provider_failure_count")),
    }
    provider_fallback_attempt_count = _int(recovery.get("provider_fallback_attempt_count"))
    if provider_fallback_attempt_count > 0:
        summary.update(
            {
                "provider_fallback_attempt_count": provider_fallback_attempt_count,
                "provider_fallback_success_count": _int(recovery.get("provider_fallback_success_count")),
                "provider_fallback_recovered_classes": _string_list(
                    recovery.get("provider_fallback_recovered_classes")
                ),
            }
        )
    provider_quarantine_count = _int(recovery.get("provider_quarantine_count"))
    if provider_quarantine_count > 0:
        video_fallback_diagnostics = _dict_list(recovery.get("video_fallback_diagnostics"))
        summary.update(
            {
                "provider_quarantine_count": provider_quarantine_count,
                "no_video_fallback_available_count": _int(
                    recovery.get("no_video_fallback_available_count")
                ),
                "provider_quarantine_classes": _string_list(recovery.get("provider_quarantine_classes")),
            }
        )
        if video_fallback_diagnostics:
            summary["video_fallback_diagnostics"] = video_fallback_diagnostics
    inline_vision_failure_count = _int(visual.get("inline_vision_failure_count"))
    if inline_vision_failure_count > 0:
        summary.update(
            {
                "inline_vision_failure_count": inline_vision_failure_count,
                "inline_vision_failure_classes": _int_mapping(visual.get("inline_vision_failure_classes")),
            }
        )
    return {
        "success": report.get("success") is True,
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "mode": report.get("mode"),
        "source": "slack_conversation_e2e",
        "summary": summary,
        "next_actions": _action_list(report.get("next_actions")),
        "self_review": _dict(report.get("self_review")),
        "privacy": {
            "raw_prompt_omitted": True,
            "stores_prompt_hash_only": True,
        },
    }


def _quality_run_id(now: datetime, request_id: str) -> str:
    suffix = request_id[-8:] if request_id else now.strftime("%f")
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{suffix}"


def _quality_score(quality_gate: dict[str, Any]) -> float | None:
    score = _float_or_none(quality_gate.get("min_score"))
    if score is not None:
        return round(max(0.0, min(1.0, score)), 4)
    if quality_gate.get("success") is True:
        return 1.0
    if quality_gate.get("success") is False:
        return 0.0
    return None


def _quality_run_video_source_summary(
    *,
    visual: dict[str, Any],
    plan_args: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    if plan_args.get("include_video") is not True:
        return {"case_count": 0, "covered_count": 0, "failure_count": 0, "failure_case_ids": []}
    video_source = _dict(visual.get("video_source"))
    if not video_source:
        return {"case_count": 0, "covered_count": 0, "failure_count": 0, "failure_case_ids": []}
    if video_source.get("uses_ranked_selected_image") is True:
        return {"case_count": 1, "covered_count": 1, "failure_count": 0, "failure_case_ids": []}
    return {
        "case_count": 1,
        "covered_count": 0,
        "failure_count": 1,
        "failure_case_ids": [request_id or "slack_conversation_e2e"],
    }


def _quality_run_video_missing_after_image_count(
    *,
    visual: dict[str, Any],
    plan_args: dict[str, Any],
) -> int:
    if plan_args.get("include_video") is not True:
        return 0
    if _int(visual.get("image_count")) < 1:
        return 0
    return 1 if _int(visual.get("video_count")) < 1 else 0


def _write_quality_run(output_dir: Path, quality_run: dict[str, Any]) -> Path:
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{quality_run['run_id']}.json"
    _write_json(path, quality_run)
    _write_json(output_dir / "latest.json", quality_run)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _action_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _next_actions_from_slack_delivery(slack_delivery: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    visual = slack_delivery.get("visual") if isinstance(slack_delivery.get("visual"), dict) else {}
    recovery = visual.get("recovery_summary") if isinstance(visual.get("recovery_summary"), dict) else {}
    provider_failure_count = _int(recovery.get("provider_failure_count"))
    if provider_failure_count > 0:
        provider_failure_classes = _int_mapping(
            recovery.get("provider_failure_classes") or visual.get("provider_failure_classes")
        )
        provider_error_codes = _int_mapping(
            recovery.get("provider_error_codes") or visual.get("provider_error_codes")
        )
        quota_count = provider_failure_classes.get("quota_exceeded", 0)
        if quota_count > 0:
            actions.append(
                _action(
                    "resolve_provider_quota_or_switch_provider",
                    "provider",
                    "slack_conversation_provider_quota_exceeded",
                    confidence=0.95,
                    evidence_count=quota_count,
                    provider_failure_classes={"quota_exceeded": quota_count},
                    provider_error_codes=provider_error_codes,
                )
            )
        no_video_fallback_count = _int(recovery.get("no_video_fallback_available_count"))
        if no_video_fallback_count > 0:
            video_fallback_diagnostics = _dict_list(recovery.get("video_fallback_diagnostics"))
            actions.append(
                _action(
                    "configure_video_fallback_provider",
                    "provider",
                    "slack_conversation_no_video_fallback_available",
                    confidence=0.9,
                    evidence_count=no_video_fallback_count,
                    provider_failure_classes=provider_failure_classes,
                    provider_error_codes=provider_error_codes,
                    **(
                        {"video_fallback_diagnostics": video_fallback_diagnostics}
                        if video_fallback_diagnostics
                        else {}
                    ),
                )
            )
        retryable_failure_count = max(0, provider_failure_count - quota_count)
        retryable_failure_classes = {
            key: count
            for key, count in provider_failure_classes.items()
            if key != "quota_exceeded"
        }
        content_moderation_count = provider_failure_classes.get("content_moderation", 0)
        if retryable_failure_count > 0 and content_moderation_count > 0:
            actions.append(
                _action(
                    "safe_reframe_provider_retry",
                    "provider",
                    "slack_conversation_content_moderation_failure",
                    confidence=0.75,
                    evidence_count=content_moderation_count,
                    provider_failure_classes=retryable_failure_classes or provider_failure_classes,
                    provider_error_codes=provider_error_codes,
                )
            )
        elif retryable_failure_count > 0 and any(
            provider_failure_classes.get(key, 0) > 0 for key in ("timeout", "empty_response")
        ):
            actions.append(
                _action(
                    "retry_provider_feasible_variant",
                    "provider",
                    "slack_conversation_retryable_provider_failure",
                    confidence=0.65,
                    evidence_count=retryable_failure_count,
                    provider_failure_classes=retryable_failure_classes or provider_failure_classes,
                    provider_error_codes=provider_error_codes,
                )
            )
        elif retryable_failure_count > 0 and any(
            provider_failure_classes.get(key, 0) > 0 for key in ("provider_unavailable", "rate_limited")
        ):
            actions.append(
                _action(
                    "retry_provider_later",
                    "provider",
                    "slack_conversation_provider_temporarily_unavailable",
                    confidence=0.6,
                    evidence_count=retryable_failure_count,
                    provider_failure_classes=retryable_failure_classes or provider_failure_classes,
                    provider_error_codes=provider_error_codes,
                )
            )

    quality_gate = _dict(visual.get("quality_gate"))
    quality_actions = []
    if not _provider_account_blocked_without_quality_evidence(
        provider_failure_classes=_int_mapping(
            recovery.get("provider_failure_classes") or visual.get("provider_failure_classes")
        ),
        quality_gate=quality_gate,
    ):
        quality_actions = _next_actions_from_quality_gate(quality_gate)
    if quality_actions and (slack_delivery.get("success") is True or _quality_repair_failure(slack_delivery)):
        actions.extend(quality_actions)
    return _dedupe_actions(actions)


def _quality_repair_failure(slack_delivery: dict[str, Any]) -> bool:
    if slack_delivery.get("success") is True:
        return False
    failures = {str(item) for item in slack_delivery.get("failures") or [] if item}
    return any(
        key in failures
        for key in {
            "quality_gate_failed",
            "selected_quality_issue_detected",
            "pre_slack_preference_dimension_low",
        }
    )


def _provider_account_blocked_without_quality_evidence(
    *,
    provider_failure_classes: dict[str, int],
    quality_gate: dict[str, Any],
) -> bool:
    if provider_failure_classes.get("quota_exceeded", 0) <= 0:
        return False
    if _int(quality_gate.get("score_count")) > 0:
        return False
    if _float_or_none(quality_gate.get("min_score")) is not None:
        return False
    if _string_list(quality_gate.get("quality_issues")):
        return False
    if _preference_dimension_failures(quality_gate.get("preference_dimension_failures")):
        return False
    return True


def _next_actions_from_quality_gate(quality_gate: dict[str, Any]) -> list[dict[str, Any]]:
    if not quality_gate:
        return []
    quality_issues = _string_list(quality_gate.get("quality_issues"))
    preference_failures = _preference_dimension_failures(quality_gate.get("preference_dimension_failures"))
    if quality_gate.get("success") is not False and not quality_issues and not preference_failures:
        return []

    evidence_count = max(1, len(quality_issues), len(preference_failures))
    actions = [
        _action(
            "increase_candidate_budget",
            "aesthetic",
            "slack_conversation_quality_gate_failed",
            confidence=0.75,
            evidence_count=evidence_count,
            max_candidate_budget=4,
        ),
        _action(
            "rerank_before_slack",
            "aesthetic",
            "slack_conversation_low_quality_candidates",
            confidence=0.8,
            evidence_count=evidence_count,
        ),
    ]
    for failure in preference_failures:
        actions.append(
            _action(
                "repair_low_preference_dimension",
                "aesthetic",
                "slack_conversation_preference_dimension_low",
                confidence=0.72,
                evidence_count=1,
                dimension=failure["dimension"],
                quality_issue=failure.get("issue", ""),
                repair_hint=_repair_hint_for_dimension(failure["dimension"]),
            )
        )
    return actions


def _preference_dimension_failures(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    failures: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        if not dimension or dimension in seen:
            continue
        seen.add(dimension)
        failures.append(
            {
                "dimension": dimension,
                "issue": str(item.get("issue") or "").strip(),
            }
        )
    return failures


def _repair_hint_for_dimension(dimension: str) -> str:
    return {
        "subject_beauty": "improve_subject_beauty",
        "face_naturalness": "improve_face_naturalness",
        "glamour_impact": "increase_glamour_impact",
        "fashion_material_quality": "improve_fashion_material_quality",
        "pose_composition": "improve_pose_composition",
        "motion_quality": "improve_motion_quality",
    }.get(dimension, f"improve_{dimension}")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _action_types(actions: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for action in actions:
        action_type = str(action.get("type") or "")
        if action_type and action_type not in values:
            values.append(action_type)
    return values


def _action(
    action_type: str,
    track: str,
    reason: str,
    *,
    confidence: float,
    evidence_count: int,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "type": action_type,
        "track": track,
        "reason": reason,
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "evidence_count": int(evidence_count),
        "requires_human_feedback": False,
        "activation_status": "next_run",
        "source": "slack_conversation_e2e",
    }
    payload.update(extra)
    return payload


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    mapping: dict[str, int] = {}
    for key, count in value.items():
        text = str(key or "").strip()
        parsed = _int(count)
        if text and parsed > 0:
            mapping[text] = parsed
    return mapping


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _failure_result(*, mode: str, failures: list[str]) -> dict[str, Any]:
    return {
        "success": False,
        "mode": mode,
        "failures": failures,
        "ingress": {},
        "conversation_route": {},
        "slack_delivery": {},
        "next_actions": [],
        "privacy": {
            "raw_prompt_omitted": True,
            "stores_prompt_hash_only": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Slack conversational visual E2E evidence gate.")
    parser.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--target", default=None)
    parser.add_argument("--thread-id", default=None)
    parser.add_argument("--candidate-budget", type=int, default=1)
    parser.add_argument("--video-budget", type=int, default=1)
    parser.add_argument("--duration", type=int, default=4)
    parser.add_argument("--no-video", action="store_true")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--repair-budget", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)

    report = build_visual_slack_conversation_e2e_report(
        mode=args.mode,
        work_dir=args.work_dir,
        prompt=args.prompt,
        target=args.target,
        thread_id=args.thread_id,
        candidate_budget=args.candidate_budget,
        video_budget=args.video_budget,
        duration=args.duration,
        require_video=not args.no_video,
        upload=True if args.upload else None,
        repair_budget=args.repair_budget,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        status = "passed" if report["success"] else "failed"
        self_review = _dict(report.get("self_review"))
        decision = str(self_review.get("decision") or "unknown")
        print(f"visual slack conversation e2e {status} (self_review={decision})")
    if args.allow_failures:
        return 0
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
