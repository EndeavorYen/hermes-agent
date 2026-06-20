#!/usr/bin/env python3
"""Run a deterministic Visual Agent Mode evidence-loop smoke test."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
MP4_STUB = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomvisual-smoke"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a local synthetic image/video visual package, record delivery "
            "and feedback evidence, then run strict proof and aggregate report."
        )
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Directory for the isolated Hermes home and fixture artifacts.",
    )
    parser.add_argument("--platform", default="slack")
    parser.add_argument("--destination-id", default="CSELFSMOKE")
    parser.add_argument("--thread-id", default="self-smoke-thread")
    parser.add_argument("--user-id", default="USELFSMOKE")
    parser.add_argument("--message-id", default="self-smoke-user-message")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.work_dir:
        payload = run_self_smoke(
            Path(args.work_dir),
            platform=args.platform,
            destination_id=args.destination_id,
            thread_id=args.thread_id,
            user_id=args.user_id,
            message_id=args.message_id,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="hermes-visual-smoke-") as temp_dir:
            payload = run_self_smoke(
                Path(temp_dir),
                platform=args.platform,
                destination_id=args.destination_id,
                thread_id=args.thread_id,
                user_id=args.user_id,
                message_id=args.message_id,
            )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload.get("success") else 1


def run_self_smoke(
    work_dir: Path,
    *,
    platform: str,
    destination_id: str,
    thread_id: str | None,
    user_id: str,
    message_id: str,
) -> dict[str, Any]:
    from hermes_constants import (
        reset_hermes_home_override,
        set_hermes_home_override,
    )

    work_dir = work_dir.expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    hermes_home = work_dir / "hermes_home"
    hermes_home.mkdir(parents=True, exist_ok=True)

    token = set_hermes_home_override(hermes_home)
    try:
        return _run_self_smoke_under_home(
            work_dir,
            hermes_home=hermes_home,
            platform=platform,
            destination_id=destination_id,
            thread_id=thread_id,
            user_id=user_id,
            message_id=message_id,
        )
    finally:
        reset_hermes_home_override(token)


def _run_self_smoke_under_home(
    work_dir: Path,
    *,
    hermes_home: Path,
    platform: str,
    destination_id: str,
    thread_id: str | None,
    user_id: str,
    message_id: str,
) -> dict[str, Any]:
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.live_proof import verify_visual_agent_live_proof
    from agent.visual.source_context import (
        VisualSourceContext,
        clear_visual_source_context,
        set_visual_source_context,
    )
    from agent.visual.tracking import (
        default_visual_ledger_path,
        record_visual_generation_attempt,
    )
    from scripts.visual_agent_report import build_visual_agent_report

    fixtures = work_dir / "fixtures"
    image_path = fixtures / "smoke-image.png"
    video_path = fixtures / "smoke-video.mp4"
    fixtures.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(PNG_1X1)
    video_path.write_bytes(MP4_STUB)

    platform_key = str(platform or "").strip().lower() or "slack"
    created_at = _utc_now_iso()
    source_context = VisualSourceContext(
        platform=platform_key,
        channel_id=destination_id,
        thread_id=thread_id,
        user_id=user_id,
        message_id=message_id,
        conversation_id=f"{platform_key}:{destination_id}",
    )
    source_token = set_visual_source_context(source_context)
    try:
        image_payload = record_visual_generation_attempt(
            {
                "success": True,
                "image": str(image_path),
                "provider": "self-smoke",
                "model": "fixture-image",
            },
            user_prompt="visual agent self smoke",
            prompt_original="visual agent self smoke",
            prompt_mediated="visual agent self smoke",
            modality="image",
            operation="self_smoke",
            artifact_key="image",
            kind="image",
            provider="self-smoke",
            model="fixture-image",
        )
        video_payload = record_visual_generation_attempt(
            {
                "success": True,
                "video": str(video_path),
                "provider": "self-smoke",
                "model": "fixture-video",
            },
            user_prompt="visual agent self smoke",
            prompt_original="visual agent self smoke",
            prompt_mediated="visual agent self smoke",
            modality="video",
            operation="self_smoke",
            artifact_key="video",
            kind="video",
            provider="self-smoke",
            model="fixture-video",
        )
    finally:
        clear_visual_source_context(source_token)

    ledger_path = default_visual_ledger_path()
    ledger = VisualAttemptLedger(ledger_path)
    ledger.initialize()
    delivery_message_id = "self-smoke-delivery-message"
    for payload, kind in ((image_payload, "image"), (video_payload, "video")):
        ledger.record_delivery(
            request_id=str(payload["visual_request_id"]),
            attempt_id=str(payload["visual_attempt_id"]),
            artifact_id=str(payload["visual_artifact_id"]),
            platform=platform_key,
            destination_id=destination_id,
            thread_id=thread_id,
            message_id=delivery_message_id,
            delivery_status="sent",
            delivered_at=created_at,
        )

    feedback_recorded = _record_feedback(
        platform=platform_key,
        destination_id=destination_id,
        thread_id=thread_id,
    )
    feedback_count = _feedback_count(ledger)
    proof = verify_visual_agent_live_proof(
        ledger_path,
        since=created_at,
        platform=platform_key,
        destination_id=destination_id,
        thread_id=thread_id,
    )
    report = build_visual_agent_report(ledger_path, since=created_at)
    success = (
        proof.success
        and proof.counts.get("missing_request_source_metadata_count") == 0
        and proof.counts.get("duplicate_artifact_delivery_count") == 0
        and bool(feedback_recorded)
        and feedback_count >= 2
    )
    return {
        "success": bool(success),
        "hermes_home": str(hermes_home),
        "ledger_path": str(ledger_path),
        "since": created_at,
        "source": {
            "platform": platform_key,
            "destination_id": destination_id,
            "thread_id": thread_id,
        },
        "artifacts": {
            "image": {
                "request_id": image_payload.get("visual_request_id"),
                "attempt_id": image_payload.get("visual_attempt_id"),
                "artifact_id": image_payload.get("visual_artifact_id"),
            },
            "video": {
                "request_id": video_payload.get("visual_request_id"),
                "attempt_id": video_payload.get("visual_attempt_id"),
                "artifact_id": video_payload.get("visual_artifact_id"),
            },
        },
        "feedback": {
            "recorded": bool(feedback_recorded),
            "count": feedback_count,
        },
        "proof": proof.to_dict(),
        "report": report,
    }


def _record_feedback(
    *,
    platform: str,
    destination_id: str,
    thread_id: str | None,
) -> bool:
    from gateway.config import Platform, PlatformConfig
    from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType
    from gateway.session import SessionSource

    class SmokeAdapter(BasePlatformAdapter):
        async def connect(self):
            return True

        async def disconnect(self):
            return None

        async def send(self, *args, **kwargs):
            return None

        async def get_chat_info(self, *args):
            return {}

    platform_enum = Platform(platform)
    adapter = SmokeAdapter(
        config=PlatformConfig(enabled=True, token="self-smoke"),
        platform=platform_enum,
    )
    event = MessageEvent(
        text="1st image good, keep this direction\n2nd video good, stable motion",
        message_type=MessageType.TEXT,
        source=SessionSource(
            platform=platform_enum,
            chat_id=destination_id,
            thread_id=thread_id,
        ),
    )
    return adapter._record_inbound_visual_feedback(event)


def _feedback_count(ledger) -> int:
    with ledger._connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM visual_feedback").fetchone()
    return int(row["count"]) if row is not None else 0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    sys.exit(main())
