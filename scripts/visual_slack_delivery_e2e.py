from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.delivery_manifest import build_visual_delivery_manifest
from agent.visual.delivery_manifest import select_deliverable_artifacts
from agent.visual.tracking import default_visual_ledger_path
from agent.visual.tracking import record_visual_delivery_status
from agent.visual.tracking import visual_delivery_context
from scripts.visual_live_provider_e2e import DEFAULT_PROMPT
from scripts.visual_live_provider_e2e import _fixture_provider_context
from scripts.visual_live_provider_e2e import _hermes_home_context
from scripts.visual_live_provider_e2e import inspect_visual_e2e_evidence
from scripts.visual_live_provider_e2e import run_visual_package


def build_visual_slack_delivery_e2e_report(
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
        return _failure_result(mode, ["unsupported_mode"], target=target, thread_id=thread_id)

    destination_id = _resolve_target(mode=mode, target=target)
    if not destination_id:
        return _failure_result(mode, ["missing_slack_target"], target=target, thread_id=thread_id)

    with _hermes_home_context(work_dir):
        with _fixture_provider_context(mode, work_dir):
            payload = run_visual_package(
                {
                    "prompt": prompt,
                    "include_video": require_video,
                    "candidate_budget": candidate_budget,
                    "video_budget": video_budget,
                    "duration": duration,
                    "aspect_ratio": "1:1",
                }
            )

        visual_evidence = inspect_visual_e2e_evidence(payload, require_video=require_video)
        manifest = build_visual_delivery_manifest(payload)
        deliverables = select_deliverable_artifacts(manifest)
        delivery_metadata = payload.get("delivery_metadata") if isinstance(payload, dict) else None
        if _should_live_upload(mode=mode, upload=upload):
            record_summary = asyncio.run(
                _upload_live_slack_deliverables(
                    metadata=delivery_metadata,
                    deliverables=deliverables,
                    destination_id=destination_id,
                    thread_id=thread_id,
                )
            )
        elif mode == "live":
            record_summary = {
                "recorded_count": 0,
                "missing_context_refs": [],
                "upload_enabled": False,
            }
        else:
            record_summary = _record_slack_delivery_evidence(
                metadata=delivery_metadata,
                deliverables=deliverables,
                destination_id=destination_id,
                thread_id=thread_id,
            )
        delivery_evidence = inspect_slack_delivery_evidence(
            payload=payload,
            deliverables=deliverables,
            destination_id=destination_id,
            thread_id=thread_id,
        )

    failures = _delivery_failures(
        payload=payload,
        deliverables=deliverables,
        delivery_metadata=delivery_metadata,
        delivery_evidence=delivery_evidence,
        record_summary=record_summary,
        mode=mode,
    )
    return {
        "success": not failures,
        "mode": mode,
        "failures": failures,
        "target": {
            "platform": "slack",
            "destination_id": destination_id,
            "thread_id": thread_id,
        },
        "visual": {
            "request_id": visual_evidence.get("request_id"),
            "image_count": visual_evidence.get("image_count", 0),
            "video_count": visual_evidence.get("video_count", 0),
            "artifact_count": visual_evidence.get("artifact_count", 0),
            "judgment_count": visual_evidence.get("judgment_count", 0),
            "ranking_count": visual_evidence.get("ranking_count", 0),
        },
        "delivery": delivery_evidence,
        "record_summary": record_summary,
    }


def inspect_slack_delivery_evidence(
    *,
    payload: dict[str, Any] | None,
    deliverables: list[dict[str, Any]],
    destination_id: str,
    thread_id: str | None,
) -> dict[str, Any]:
    request_id = ""
    if isinstance(payload, dict):
        request_id = str(payload.get("visual_request_id") or "")
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    deliveries = ledger.list_deliveries(request_id=request_id) if request_id else []
    expected_artifact_ids = {
        str(item.get("artifact_id") or "")
        for item in deliverables
        if item.get("artifact_id")
    }
    relevant = [
        row
        for row in deliveries
        if row.get("platform") == "slack"
        and row.get("destination_id") == destination_id
        and (thread_id is None or row.get("thread_id") == thread_id)
    ]
    sent_rows = [row for row in relevant if row.get("delivery_status") == "sent"]
    sent_artifact_ids = {
        str(row.get("artifact_id") or "")
        for row in sent_rows
        if row.get("artifact_id")
    }
    duplicate_delivery_count = _duplicate_delivery_count(sent_rows)
    return {
        "request_id": request_id,
        "deliverable_count": len(deliverables),
        "delivery_count": len(relevant),
        "sent_count": len(sent_rows),
        "failed_count": sum(1 for row in relevant if row.get("delivery_status") == "failed"),
        "skipped_count": sum(
            1 for row in relevant if str(row.get("delivery_status") or "").startswith("skipped")
        ),
        "duplicate_delivery_count": duplicate_delivery_count,
        "expected_artifact_ids": sorted(expected_artifact_ids),
        "sent_artifact_ids": sorted(sent_artifact_ids),
        "missing_delivery_artifact_ids": sorted(expected_artifact_ids - sent_artifact_ids),
        "message_ids": sorted(
            str(row.get("message_id") or "")
            for row in sent_rows
            if row.get("message_id")
        ),
    }


def _record_slack_delivery_evidence(
    *,
    metadata: dict[str, Any] | None,
    deliverables: list[dict[str, Any]],
    destination_id: str,
    thread_id: str | None,
) -> dict[str, Any]:
    recorded = 0
    missing_context_refs: list[str] = []
    for item in deliverables:
        ref = str(item.get("ref") or "")
        if not ref:
            continue
        context = visual_delivery_context(
            metadata,
            ref,
            platform="slack",
            destination_id=destination_id,
            thread_id=thread_id,
        )
        if context is None:
            missing_context_refs.append(ref)
            continue
        status = str(context.get("skip_status") or "sent")
        message_id = None
        if status == "sent":
            message_id = f"fixture-slack:{context['artifact_id']}"
        record_visual_delivery_status(
            context,
            status,
            message_id=message_id,
        )
        recorded += 1
    return {
        "recorded_count": recorded,
        "missing_context_refs": missing_context_refs,
        "upload_enabled": False,
    }


async def _upload_live_slack_deliverables(
    *,
    metadata: dict[str, Any] | None,
    deliverables: list[dict[str, Any]],
    destination_id: str,
    thread_id: str | None,
) -> dict[str, Any]:
    delivery_metadata = dict(metadata or {})
    if thread_id:
        delivery_metadata["thread_id"] = thread_id
        delivery_metadata["visual_thread_id"] = thread_id

    image_refs: list[tuple[str, str]] = []
    video_paths: list[str] = []
    skipped_refs: list[str] = []
    errors: list[str] = []
    for item in deliverables:
        ref = str(item.get("ref") or "")
        if not ref:
            continue
        kind = str(item.get("kind") or "").lower()
        local_path = _local_path_from_ref(ref)
        if not local_path:
            skipped_refs.append(ref)
            continue
        if kind == "image" or local_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            image_refs.append((_file_uri(local_path), ""))
        elif kind == "video" or local_path.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
            video_paths.append(local_path)
        else:
            skipped_refs.append(ref)

    try:
        adapter = _make_live_slack_adapter()
        if image_refs:
            await adapter.send_multiple_images(destination_id, image_refs, metadata=delivery_metadata)
        for video_path in video_paths:
            await adapter.send_video(destination_id, video_path, metadata=delivery_metadata)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}:{exc}")

    return {
        "recorded_count": 0,
        "missing_context_refs": [],
        "upload_enabled": True,
        "uploaded_image_count": len(image_refs),
        "uploaded_video_count": len(video_paths),
        "skipped_refs": skipped_refs,
        "errors": errors,
    }


def _make_live_slack_adapter() -> Any:
    _load_runtime_env()
    from gateway.config import Platform
    from gateway.config import PlatformConfig
    from gateway.config import load_gateway_config
    from gateway.platforms.slack import AsyncWebClient
    from gateway.platforms.slack import SlackAdapter

    config = load_gateway_config()
    pconfig = config.platforms.get(Platform.SLACK)
    raw_token = ""
    if pconfig is not None and pconfig.token:
        raw_token = pconfig.token
    raw_token = raw_token or os.environ.get("SLACK_BOT_TOKEN", "")
    bot_token = raw_token.split(",", 1)[0].strip()
    if not bot_token:
        raise RuntimeError("SLACK_BOT_TOKEN is not configured")
    if pconfig is None:
        pconfig = PlatformConfig(enabled=True, token=bot_token)
    adapter = SlackAdapter(pconfig)
    adapter._app = SimpleNamespace(client=AsyncWebClient(token=bot_token))
    return adapter


def _load_runtime_env() -> None:
    from hermes_cli.env_loader import load_hermes_dotenv

    load_hermes_dotenv()


def _delivery_failures(
    *,
    payload: dict[str, Any] | None,
    deliverables: list[dict[str, Any]],
    delivery_metadata: Any,
    delivery_evidence: dict[str, Any],
    record_summary: dict[str, Any],
    mode: str,
) -> list[str]:
    failures: list[str] = []
    if not isinstance(payload, dict):
        return ["missing_payload"]
    if payload.get("success") is not True:
        failures.append(str(payload.get("error_type") or "visual_generation_failed"))
    if not isinstance(delivery_metadata, dict):
        failures.append("missing_delivery_metadata")
    if not deliverables:
        failures.append("missing_deliverables")
    if record_summary.get("missing_context_refs"):
        failures.append("missing_delivery_context")
    if mode == "live" and record_summary.get("upload_enabled") is not True:
        failures.append("live_upload_not_enabled")
    if record_summary.get("errors"):
        failures.append("live_upload_failed")
    if delivery_evidence.get("delivery_count", 0) < delivery_evidence.get("deliverable_count", 0):
        failures.append("missing_delivery_records")
    if delivery_evidence.get("sent_count", 0) < delivery_evidence.get("deliverable_count", 0):
        failures.append("missing_sent_deliveries")
    if delivery_evidence.get("missing_delivery_artifact_ids"):
        failures.append("missing_delivery_artifacts")
    if delivery_evidence.get("duplicate_delivery_count", 0) > 0:
        failures.append("duplicate_delivery_records")
    return sorted(set(failures))


def _duplicate_delivery_count(rows: list[dict[str, Any]]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for row in rows:
        key = str(row.get("artifact_id") or row.get("message_id") or "")
        if not key:
            continue
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def _resolve_target(*, mode: str, target: str | None) -> str | None:
    if target:
        return target
    env_target = (
        os.environ.get("HERMES_VISUAL_SLACK_E2E_TARGET")
        or os.environ.get("SLACK_HOME_CHANNEL")
    )
    if env_target:
        return env_target
    try:
        from gateway.config import Platform
        from gateway.config import load_gateway_config

        home_channel = load_gateway_config().get_home_channel(Platform.SLACK)
        if home_channel and home_channel.chat_id:
            return home_channel.chat_id
    except Exception:
        pass
    if mode == "fixture":
        return "fixture-slack-target"
    return None


def _should_live_upload(*, mode: str, upload: bool | None) -> bool:
    if mode != "live":
        return False
    if upload is not None:
        return upload
    return str(os.environ.get("HERMES_VISUAL_SLACK_LIVE_UPLOAD") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _local_path_from_ref(ref: str) -> str | None:
    parsed = urlparse(ref)
    if parsed.scheme == "file":
        return unquote(parsed.path)
    if parsed.scheme == "":
        return str(Path(ref))
    return None


def _file_uri(path: str) -> str:
    return f"file://{quote(str(Path(path)))}"


def _failure_result(
    mode: str,
    failures: list[str],
    *,
    target: str | None,
    thread_id: str | None,
) -> dict[str, Any]:
    return {
        "success": False,
        "mode": mode,
        "failures": failures,
        "target": {
            "platform": "slack",
            "destination_id": target,
            "thread_id": thread_id,
        },
        "visual": {},
        "delivery": {},
        "record_summary": {},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a visual Slack delivery evidence gate.")
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

    report = build_visual_slack_delivery_e2e_report(
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
        print(f"visual slack delivery e2e {status}")
    if args.allow_failures:
        return 0
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
