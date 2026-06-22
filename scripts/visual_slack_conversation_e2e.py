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
        if not str(getattr(captured_event, "text", "") or "").strip():
            failures.append("slack_ingress_missing_text")
        delivery_thread_id = getattr(captured_event.source, "thread_id", None)
        delivery_kwargs = {
            "mode": mode,
            "work_dir": work_dir,
            "prompt": str(getattr(captured_event, "text", "") or ""),
            "target": str(getattr(captured_event.source, "chat_id", "") or destination_id),
            "thread_id": delivery_thread_id,
            "candidate_budget": candidate_budget,
            "video_budget": video_budget,
            "duration": duration,
            "require_video": require_video,
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
    return {
        "success": not failures,
        "mode": mode,
        "failures": sorted(set(str(item) for item in failures if item)),
        "ingress": ingress_summary,
        "conversation_route": conversation_route,
        "initial_slack_delivery": initial_slack_delivery,
        "slack_delivery": slack_delivery,
        "repair_attempt": repair_attempt,
        "next_actions": next_actions,
        "privacy": {
            "raw_prompt_omitted": True,
            "stores_prompt_hash_only": True,
        },
    }


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
        content_moderation_count = provider_failure_classes.get("content_moderation", 0)
        if content_moderation_count > 0:
            actions.append(
                _action(
                    "safe_reframe_provider_retry",
                    "provider",
                    "slack_conversation_content_moderation_failure",
                    confidence=0.75,
                    evidence_count=content_moderation_count,
                    provider_failure_classes=provider_failure_classes,
                    provider_error_codes=provider_error_codes,
                )
            )
        elif any(provider_failure_classes.get(key, 0) > 0 for key in ("timeout", "empty_response")):
            actions.append(
                _action(
                    "retry_provider_feasible_variant",
                    "provider",
                    "slack_conversation_retryable_provider_failure",
                    confidence=0.65,
                    evidence_count=provider_failure_count,
                    provider_failure_classes=provider_failure_classes,
                    provider_error_codes=provider_error_codes,
                )
            )
        elif any(provider_failure_classes.get(key, 0) > 0 for key in ("provider_unavailable", "rate_limited")):
            actions.append(
                _action(
                    "retry_provider_later",
                    "provider",
                    "slack_conversation_provider_temporarily_unavailable",
                    confidence=0.6,
                    evidence_count=provider_failure_count,
                    provider_failure_classes=provider_failure_classes,
                    provider_error_codes=provider_error_codes,
                )
            )

    if _quality_repair_failure(slack_delivery):
        actions.extend(_next_actions_from_quality_gate(_dict(visual.get("quality_gate"))))
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
        print(f"visual slack conversation e2e {status}")
    if args.allow_failures:
        return 0
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
