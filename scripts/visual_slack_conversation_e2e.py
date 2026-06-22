#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

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

    if captured_event is None:
        slack_delivery: dict[str, Any] = {
            "status": "skipped",
            "reason": "slack_ingress_failed",
        }
    else:
        if not str(getattr(captured_event, "text", "") or "").strip():
            failures.append("slack_ingress_missing_text")
        delivery_thread_id = getattr(captured_event.source, "thread_id", None)
        slack_delivery = build_visual_slack_delivery_e2e_report(
            mode=mode,
            work_dir=work_dir,
            prompt=str(getattr(captured_event, "text", "") or ""),
            target=str(getattr(captured_event.source, "chat_id", "") or destination_id),
            thread_id=delivery_thread_id,
            candidate_budget=candidate_budget,
            video_budget=video_budget,
            duration=duration,
            require_video=require_video,
            upload=upload,
        )
        if slack_delivery.get("success") is not True:
            failures.append("slack_delivery_failed")

    return {
        "success": not failures,
        "mode": mode,
        "failures": sorted(set(str(item) for item in failures if item)),
        "ingress": ingress_summary,
        "conversation_route": conversation_route,
        "slack_delivery": slack_delivery,
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


def _failure_result(*, mode: str, failures: list[str]) -> dict[str, Any]:
    return {
        "success": False,
        "mode": mode,
        "failures": failures,
        "ingress": {},
        "conversation_route": {},
        "slack_delivery": {},
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
