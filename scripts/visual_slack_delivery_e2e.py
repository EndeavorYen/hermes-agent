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

from hermes_constants import get_hermes_home
from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.delivery_manifest import build_visual_delivery_manifest
from agent.visual.delivery_manifest import select_deliverable_artifacts
from agent.visual.operator_setup import operator_setup_actions_from_video_fallback_diagnostics as _operator_setup_actions_from_video_fallback_diagnostics
from agent.visual.tracking import default_visual_ledger_path
from agent.visual.tracking import record_visual_delivery_status
from agent.visual.tracking import visual_delivery_context
from scripts.visual_live_provider_e2e import DEFAULT_PROMPT
from scripts.visual_live_provider_e2e import _fixture_provider_context
from scripts.visual_live_provider_e2e import _hermes_home_for_mode
from scripts.visual_live_provider_e2e import _hermes_home_context
from scripts.visual_live_provider_e2e import inspect_visual_e2e_evidence
from scripts.visual_live_provider_e2e import run_visual_package


def build_visual_slack_delivery_e2e_report(
    *,
    mode: str = "fixture",
    work_dir: str | Path | None = None,
    prompt: str = DEFAULT_PROMPT,
    attachments: list[str] | None = None,
    target: str | None = None,
    thread_id: str | None = None,
    include_image: bool | None = None,
    aspect_ratio: str | None = None,
    candidate_budget: int = 1,
    video_budget: int = 1,
    duration: int = 4,
    require_video: bool = True,
    upload: bool | None = None,
    storyboard: dict[str, Any] | None = None,
    character_design_ref_only: bool | None = None,
    composition_guide_only: bool | None = None,
    hybrid_final_combine: bool | None = None,
) -> dict[str, Any]:
    mode = mode.strip().lower()
    if mode not in {"fixture", "live"}:
        return _failure_result(mode, ["unsupported_mode"], target=target, thread_id=thread_id)

    destination_id = _resolve_target(mode=mode, target=target)
    if not destination_id:
        return _failure_result(mode, ["missing_slack_target"], target=target, thread_id=thread_id)

    with _hermes_home_context(_hermes_home_for_mode(mode=mode, work_dir=work_dir)):
        with _fixture_provider_context(mode, work_dir, force_storyboard_composition=bool(storyboard)):
            package_args = {
                "prompt": prompt,
                "include_video": require_video,
                "candidate_budget": candidate_budget,
                "video_budget": video_budget,
                "duration": duration,
                "aspect_ratio": aspect_ratio or "1:1",
            }
            if include_image is not None:
                package_args["include_image"] = include_image
            if attachments:
                package_args["attachments"] = attachments
            if storyboard:
                package_args["include_image"] = False
                package_args["storyboard"] = storyboard
            if character_design_ref_only is not None:
                package_args["character_design_ref_only"] = character_design_ref_only
            if composition_guide_only is not None:
                package_args["composition_guide_only"] = composition_guide_only
            if hybrid_final_combine is not None:
                package_args["hybrid_final_combine"] = hybrid_final_combine
            payload = run_visual_package(package_args)

        visual_evidence = inspect_visual_e2e_evidence(payload, require_video=require_video)
        manifest = build_visual_delivery_manifest(payload)
        deliverables = select_deliverable_artifacts(manifest)
        manifest_failures = [
            str(item)
            for item in manifest.get("failures", [])
            if item
        ] if isinstance(manifest, dict) else []
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
            record_summary=record_summary,
        )

    failures = _delivery_failures(
        payload=payload,
        visual_evidence=visual_evidence,
        deliverables=deliverables,
        delivery_metadata=delivery_metadata,
        delivery_evidence=delivery_evidence,
        record_summary=record_summary,
        mode=mode,
        manifest_failures=manifest_failures,
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
            "video_source": visual_evidence.get("video_source", {}),
            "provider_failure_classes": visual_evidence.get("provider_failure_classes", {}),
            "provider_error_codes": visual_evidence.get("provider_error_codes", {}),
            "retry_attempt_count": visual_evidence.get("retry_attempt_count", 0),
            "inline_vision_failure_count": visual_evidence.get("inline_vision_failure_count", 0),
            "inline_vision_failure_classes": visual_evidence.get("inline_vision_failure_classes", {}),
            "recovery_summary": visual_evidence.get("recovery_summary", {}),
            "quality_repair_summary": visual_evidence.get("quality_repair_summary", {}),
            "quality_gate": visual_evidence.get("quality_gate", {}),
            "storyboard_execution": visual_evidence.get("storyboard_execution", {}),
        },
        "delivery": delivery_evidence,
        "delivery_manifest": {
            "failure_count": len(manifest_failures),
            "failures": manifest_failures,
        },
        "record_summary": record_summary,
    }


def inspect_slack_delivery_evidence(
    *,
    payload: dict[str, Any] | None,
    deliverables: list[dict[str, Any]],
    destination_id: str,
    thread_id: str | None,
    record_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_id = ""
    if isinstance(payload, dict):
        request_id = str(payload.get("visual_request_id") or "")
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    try:
        deliveries = ledger.list_deliveries(request_id=request_id) if request_id else []
    except Exception:
        deliveries = []
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
    upload_gate = _upload_gate_evidence(
        deliverables=deliverables,
        record_summary=record_summary,
    )
    internal_source_gate = _internal_source_image_delivery_evidence(
        payload=payload,
        deliverables=deliverables,
    )
    partial_video_gate = _partial_video_unavailable_delivery_evidence(
        payload=payload,
        deliverables=deliverables,
    )
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
        "unexpected_delivery_artifact_ids": sorted(sent_artifact_ids - expected_artifact_ids),
        "message_ids": sorted(
            str(row.get("message_id") or "")
            for row in sent_rows
            if row.get("message_id")
        ),
        **upload_gate,
        **internal_source_gate,
        **partial_video_gate,
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
    skipped_refs: list[str] = []
    for item in deliverables:
        ref = str(item.get("ref") or "")
        if not ref:
            continue
        if item.get("uploadable_file") is False:
            skipped_refs.append(ref)
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
        "skipped_refs": skipped_refs,
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

    image_uploads: list[dict[str, str]] = []
    video_uploads: list[dict[str, str]] = []
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
        upload = {
            "artifact_id": str(item.get("artifact_id") or ""),
            "ref": ref,
            "local_path": local_path,
        }
        if kind == "image" or local_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            upload["upload_ref"] = _file_uri(local_path)
            image_uploads.append(upload)
        elif kind == "video" or local_path.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
            upload["upload_ref"] = local_path
            video_uploads.append(upload)
        else:
            skipped_refs.append(ref)

    try:
        adapter = _make_live_slack_adapter()
        if image_uploads:
            image_refs = [(item["upload_ref"], "") for item in image_uploads]
            image_result = await adapter.send_multiple_images(destination_id, image_refs, metadata=delivery_metadata)
            for upload in image_uploads:
                _ensure_live_upload_record(
                    metadata=delivery_metadata,
                    artifact_ref=upload["upload_ref"],
                    destination_id=destination_id,
                    thread_id=thread_id,
                    result=image_result,
                )
        for upload in video_uploads:
            video_result = await adapter.send_video(destination_id, upload["upload_ref"], metadata=delivery_metadata)
            _ensure_live_upload_record(
                metadata=delivery_metadata,
                artifact_ref=upload["upload_ref"],
                destination_id=destination_id,
                thread_id=thread_id,
                result=video_result,
            )
    except Exception as exc:
        errors.append(f"{type(exc).__name__}:{exc}")

    return {
        "recorded_count": 0,
        "missing_context_refs": [],
        "upload_enabled": True,
        "uploaded_image_count": len(image_uploads),
        "uploaded_video_count": len(video_uploads),
        "uploaded_image_artifact_ids": _artifact_ids(image_uploads),
        "uploaded_video_artifact_ids": _artifact_ids(video_uploads),
        "uploaded_image_refs": [item["upload_ref"] for item in image_uploads],
        "uploaded_video_refs": [item["upload_ref"] for item in video_uploads],
        "skipped_refs": skipped_refs,
        "errors": errors,
    }


def _ensure_live_upload_record(
    *,
    metadata: dict[str, Any],
    artifact_ref: str,
    destination_id: str,
    thread_id: str | None,
    result: Any,
) -> None:
    context = visual_delivery_context(
        metadata,
        artifact_ref,
        platform="slack",
        destination_id=destination_id,
        thread_id=thread_id,
    )
    if context is None or _has_sent_delivery(context):
        return
    if not _upload_result_success(result):
        return
    record_visual_delivery_status(
        context,
        "sent",
        message_id=_upload_result_message_id(result),
    )


def _has_sent_delivery(context: dict[str, Any]) -> bool:
    ledger = context.get("ledger")
    if not isinstance(ledger, VisualAttemptLedger):
        return False
    for row in ledger.list_deliveries(request_id=str(context.get("request_id") or "")):
        if (
            row.get("artifact_id") == context.get("artifact_id")
            and row.get("platform") == context.get("platform")
            and row.get("destination_id") == context.get("destination_id")
            and row.get("thread_id") == context.get("thread_id")
            and row.get("delivery_status") == "sent"
        ):
            return True
    return False


def _upload_result_success(result: Any) -> bool:
    if result is None:
        return True
    if isinstance(result, dict):
        return (
            result.get("success") is not False
            and result.get("ok") is not False
            and not result.get("error")
        )
    success = getattr(result, "success", None)
    if success is not None:
        return bool(success)
    error = getattr(result, "error", None)
    return error in (None, "")


def _upload_result_message_id(result: Any) -> str | None:
    if isinstance(result, dict):
        for key in ("message_id", "ts", "message_ts", "id"):
            value = result.get(key)
            if value not in (None, ""):
                return str(value)
        raw = result.get("raw_response")
        if raw is not result:
            return _upload_result_message_id(raw)
    for attr in ("message_id", "ts", "message_ts", "id"):
        value = getattr(result, attr, None)
        if value not in (None, ""):
            return str(value)
    raw_response = getattr(result, "raw_response", None)
    if raw_response is not None and raw_response is not result:
        return _upload_result_message_id(raw_response)
    return None


def _make_live_slack_adapter() -> Any:
    _load_runtime_env()
    from gateway.config import Platform
    from gateway.config import PlatformConfig
    from gateway.config import load_gateway_config

    AsyncWebClient, SlackAdapter = _slack_adapter_exports()

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


def _slack_adapter_exports() -> tuple[Any, Any]:
    try:
        from plugins.platforms.slack.adapter import AsyncWebClient
        from plugins.platforms.slack.adapter import SlackAdapter

        return AsyncWebClient, SlackAdapter
    except Exception:
        from gateway.platforms.slack import AsyncWebClient
        from gateway.platforms.slack import SlackAdapter

        return AsyncWebClient, SlackAdapter


def _load_runtime_env() -> None:
    from hermes_cli.env_loader import load_hermes_dotenv

    load_hermes_dotenv()


def _delivery_failures(
    *,
    payload: dict[str, Any] | None,
    visual_evidence: dict[str, Any] | None = None,
    deliverables: list[dict[str, Any]],
    delivery_metadata: Any,
    delivery_evidence: dict[str, Any],
    record_summary: dict[str, Any],
    mode: str,
    manifest_failures: list[str] | None = None,
) -> list[str]:
    failures: list[str] = []
    failures.extend(manifest_failures or [])
    if not isinstance(payload, dict):
        return ["missing_payload"]
    partial_video_delivery = delivery_evidence.get("partial_video_unavailable_delivery") is True
    if payload.get("success") is not True and not partial_video_delivery:
        failures.append(str(payload.get("error_type") or "visual_generation_failed"))
    quality_gate = visual_evidence.get("quality_gate") if isinstance(visual_evidence, dict) else None
    quality_gate_failed = isinstance(quality_gate, dict) and quality_gate.get("success") is False
    if quality_gate_failed:
        failures.append("quality_gate_failed")
    if quality_gate_failed and quality_gate.get("quality_issues"):
        failures.append("selected_quality_issue_detected")
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
    if delivery_evidence.get("unexpected_delivery_artifact_ids"):
        failures.append("unexpected_delivery_artifacts")
    if delivery_evidence.get("internal_source_image_delivered") is True:
        failures.append("internal_source_image_delivered")
    if delivery_evidence.get("duplicate_delivery_count", 0) > 0:
        failures.append("duplicate_delivery_records")
    if mode == "live" and record_summary.get("upload_enabled") is True:
        if delivery_evidence.get("missing_uploaded_artifact_ids"):
            failures.append("missing_native_uploads")
        if delivery_evidence.get("unexpected_uploaded_artifact_ids"):
            failures.append("unexpected_native_uploads")
        if delivery_evidence.get("uploaded_remote_video_url_count", 0) > 0:
            failures.append("video_uploaded_as_remote_url")
    return sorted(set(failures))


def _upload_gate_evidence(
    *,
    deliverables: list[dict[str, Any]],
    record_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = record_summary if isinstance(record_summary, dict) else {}
    expected_uploadable = [
        item
        for item in deliverables
        if item.get("uploadable_file") is True and item.get("artifact_id")
    ]
    expected_artifact_ids = {
        str(item.get("artifact_id") or "")
        for item in expected_uploadable
        if item.get("artifact_id")
    }
    uploaded_image_ids = _string_set(summary.get("uploaded_image_artifact_ids"))
    uploaded_video_ids = _string_set(summary.get("uploaded_video_artifact_ids"))
    uploaded_artifact_ids = uploaded_image_ids | uploaded_video_ids
    upload_enabled = summary.get("upload_enabled") is True

    missing = expected_artifact_ids - uploaded_artifact_ids if upload_enabled else set()
    unexpected = uploaded_artifact_ids - expected_artifact_ids if upload_enabled else set()
    uploaded_video_refs = _string_list(summary.get("uploaded_video_refs"))
    return {
        "uploaded_image_file_count": len(uploaded_image_ids),
        "uploaded_video_file_count": len(uploaded_video_ids),
        "uploaded_remote_video_url_count": sum(
            1 for ref in uploaded_video_refs if _delivery_ref_type(ref) == "remote_url"
        ),
        "expected_uploaded_artifact_ids": sorted(expected_artifact_ids),
        "uploaded_artifact_ids": sorted(uploaded_artifact_ids),
        "missing_uploaded_artifact_ids": sorted(missing),
        "unexpected_uploaded_artifact_ids": sorted(unexpected),
    }


def _internal_source_image_delivery_evidence(
    *,
    payload: dict[str, Any] | None,
    deliverables: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "internal_source_image_delivered": False,
            "internal_source_image_artifact_ids": [],
        }
    strategy = payload.get("generation_strategy")
    if not isinstance(strategy, dict):
        return {
            "internal_source_image_delivered": False,
            "internal_source_image_artifact_ids": [],
        }
    if strategy.get("requested_image") is not False:
        return {
            "internal_source_image_delivered": False,
            "internal_source_image_artifact_ids": [],
        }
    source_artifact_id = str(strategy.get("video_source_artifact_id") or "")
    if not source_artifact_id:
        return {
            "internal_source_image_delivered": False,
            "internal_source_image_artifact_ids": [],
        }
    delivered_source_ids = sorted(
        {
            str(item.get("artifact_id") or "")
            for item in deliverables
            if str(item.get("artifact_id") or "") == source_artifact_id
            and str(item.get("kind") or "").lower() == "image"
        }
    )
    return {
        "internal_source_image_delivered": bool(delivered_source_ids),
        "internal_source_image_artifact_ids": delivered_source_ids,
    }


def _partial_video_unavailable_delivery_evidence(
    *,
    payload: dict[str, Any] | None,
    deliverables: list[dict[str, Any]],
) -> dict[str, Any]:
    default = {
        "partial_video_unavailable_delivery": False,
        "partial_video_unavailable_reason": "",
        "partial_video_operator_setup_actions": [],
    }
    if not isinstance(payload, dict):
        return default
    if str(payload.get("package_status") or "").strip().lower() != "partial":
        return default
    strategy = payload.get("generation_strategy")
    if not isinstance(strategy, dict) or strategy.get("requested_image") is not True:
        return default
    if not _nonempty_list(payload.get("images")) or _nonempty_list(payload.get("videos")):
        return default
    if not any(str(item.get("kind") or "").lower() == "image" for item in deliverables):
        return default
    diagnostics = _video_fallback_diagnostics(payload)
    if not diagnostics and not _video_payload_reports_no_fallback(payload):
        return default
    return {
        "partial_video_unavailable_delivery": True,
        "partial_video_unavailable_reason": "no_video_fallback_available",
        "partial_video_operator_setup_actions": (
            _operator_setup_actions_from_video_fallback_diagnostics(diagnostics)
        ),
    }


def _video_payload_reports_no_fallback(payload: dict[str, Any]) -> bool:
    for item in _video_payload_items(payload):
        quarantine = item.get("provider_quarantine")
        if isinstance(quarantine, dict) and quarantine.get("no_video_fallback_available") is True:
            return True
    return False


def _video_fallback_diagnostics(payload: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for item in _video_payload_items(payload):
        quarantine = item.get("provider_quarantine")
        if not isinstance(quarantine, dict):
            continue
        if quarantine.get("no_video_fallback_available") is not True:
            continue
        diagnostic = quarantine.get("video_fallback_diagnostic")
        if isinstance(diagnostic, dict):
            diagnostics.append(dict(diagnostic))
    return diagnostics


def _video_payload_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    generation_payloads = payload.get("generation_payloads")
    if not isinstance(generation_payloads, dict):
        return []
    return _dict_items(generation_payloads.get("video"))


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _artifact_ids(uploaded: list[dict[str, str]]) -> list[str]:
    return [item["artifact_id"] for item in uploaded if item.get("artifact_id")]


def _string_set(value: Any) -> set[str]:
    return set(_string_list(value))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in (None, "")]


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
    try:
        _load_runtime_env()
    except Exception:
        pass
    env_target = (
        os.environ.get("HERMES_VISUAL_SLACK_E2E_TARGET")
        or os.environ.get("SLACK_HOME_CHANNEL")
    )
    if env_target:
        return env_target
    config_target = (
        _load_top_level_config_value("HERMES_VISUAL_SLACK_E2E_TARGET")
        or _load_top_level_config_value("SLACK_HOME_CHANNEL")
    )
    if config_target:
        return str(config_target)
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


def _load_top_level_config_value(key: str) -> Any:
    try:
        import yaml

        config_path = get_hermes_home() / "config.yaml"
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if value in (None, ""):
        return None
    return value


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


def _delivery_ref_type(ref: str) -> str:
    parsed = urlparse(ref)
    if parsed.scheme == "file":
        return "file_uri"
    if parsed.scheme in {"http", "https"}:
        return "remote_url"
    if parsed.scheme == "":
        return "local_path"
    return "other"


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
    parser.add_argument("--character-design-ref-only", action="store_true")
    parser.add_argument("--composition-guide-only", action="store_true")
    parser.add_argument("--hybrid-final-combine", action="store_true")
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
        character_design_ref_only=True if args.character_design_ref_only else None,
        composition_guide_only=True if args.composition_guide_only else None,
        hybrid_final_combine=True if args.hybrid_final_combine else None,
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
